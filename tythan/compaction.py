# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/compaction.py — context compaction for long sessions.

Long conversations must not die with a hard context-length error. When the
estimated token count approaches the model's context window, older
conversation *rounds* (a user message plus everything up to the next user
message) are summarized into a single message and the most recent rounds
are kept verbatim.

History items are provider-neutral dicts:
    {"role": "user"|"assistant"|"tool", "content": str,
     "tool_calls": [...]?, "tool_call_id": str?}
Providers translate them to their wire format.
"""
from __future__ import annotations

import json
from typing import Any

# Rough universal heuristic; deliberately pessimistic.
CHARS_PER_TOKEN = 3.6
# Compact when estimated usage crosses this fraction of the window.
COMPACT_THRESHOLD = 0.75


def estimate_tokens(history: list[dict[str, Any]], extra_chars: int = 0) -> int:
    total = extra_chars
    for msg in history:
        total += len(str(msg.get("content") or ""))
        for tc in msg.get("tool_calls") or []:
            total += len(json.dumps(tc, ensure_ascii=False))
    return int(total / CHARS_PER_TOKEN)


def needs_compaction(history: list[dict[str, Any]], context_window: int,
                     reserved_output: int, system_chars: int = 0) -> bool:
    budget = max(1, context_window - reserved_output)
    return estimate_tokens(history, extra_chars=system_chars) > budget * COMPACT_THRESHOLD


def split_rounds(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split history into rounds, each starting at a user message.

    A leading run of non-user messages (e.g. a previous summary) forms its
    own round so it is never spliced into the middle of a real round.
    """
    rounds: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for msg in history:
        if msg.get("role") == "user" and current:
            rounds.append(current)
            current = []
        current.append(msg)
    if current:
        rounds.append(current)
    return rounds


def transcript_for_summary(rounds: list[list[dict[str, Any]]], cap_chars: int = 60_000) -> str:
    """Flatten rounds into a plain-text transcript, capped from the front
    (older content is dropped first — the newest context matters most)."""
    parts: list[str] = []
    for rnd in rounds:
        for msg in rnd:
            role = msg.get("role", "?")
            content = str(msg.get("content") or "")
            for tc in msg.get("tool_calls") or []:
                name = tc.get("name", "?")
                args = json.dumps(tc.get("arguments", {}), ensure_ascii=False)[:400]
                parts.append(f"[assistant called {name}({args})]")
            if content.strip():
                parts.append(f"{role}: {content}")
    text = "\n".join(parts)
    if len(text) > cap_chars:
        text = "…(older context omitted)\n" + text[-cap_chars:]
    return text


def compact(history: list[dict[str, Any]], summary: str,
            keep_rounds: int = 2) -> list[dict[str, Any]]:
    """Replace all but the last `keep_rounds` rounds with a summary message."""
    rounds = split_rounds(history)
    if len(rounds) <= keep_rounds:
        return history
    kept = rounds[-keep_rounds:] if keep_rounds > 0 else []
    new_history: list[dict[str, Any]] = [{
        "role": "user",
        "content": (
            "[Conversation so far was compacted to save context. Summary:]\n"
            + summary.strip()
        ),
    }]
    for rnd in kept:
        new_history.extend(rnd)
    return new_history


SUMMARY_PROMPT = (
    "Summarize the coding-session transcript below so the work can continue "
    "seamlessly. Preserve: the user's goals and constraints, decisions made, "
    "files created/modified (with paths), commands run and their outcomes, "
    "unresolved problems, and anything the user explicitly asked to remember. "
    "Be dense and factual; use bullet points; do not invent details.\n\n"
    "TRANSCRIPT:\n"
)
