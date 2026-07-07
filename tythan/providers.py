# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/providers.py — model backends.

Two implementations of the Backend interface:

- AnthropicBackend — native Anthropic Messages API via the official
  `anthropic` SDK (streaming, tool use, adaptive thinking + effort with
  graceful fallback for models that don't support them).
- OpenAICompatBackend — any OpenAI-compatible /chat/completions endpoint
  (OpenAI, OpenRouter, Groq, DeepSeek, Ollama, LM Studio, vLLM…) over
  `requests` with SSE streaming.

History items are provider-neutral dicts (see compaction.py); each backend
translates them to its wire format. Assistant entries may carry provider-
specific raw content under "_raw" which the same backend reuses verbatim
(required to round-trip Anthropic thinking blocks).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class TurnResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    raw_assistant: Any = None   # provider-specific content to store as "_raw"


class Backend(Protocol):
    name: str

    def run_turn(self, system: str, history: list[dict], tools: list[dict],
                 on_text: Callable[[str], None]) -> TurnResult: ...

    def summarize(self, prompt: str) -> str: ...


class BackendError(Exception):
    """A provider-level failure, formatted for the user."""


# ─── Anthropic ────────────────────────────────────────────────────────────

class AnthropicBackend:
    name = "anthropic"

    def __init__(self, config) -> None:
        self.config = config
        try:
            import anthropic
        except ImportError as exc:
            raise BackendError(
                "The 'anthropic' package is required for the anthropic provider: "
                "pip install anthropic"
            ) from exc
        self._anthropic = anthropic
        kwargs: dict = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = anthropic.Anthropic(**kwargs)
        # Adaptive thinking + effort aren't supported by every model id the
        # user can point us at; on a 400 naming them we retry without and
        # remember the answer.
        self._modern_params = True

    # ── History translation ──────────────────────────────────────────────

    @staticmethod
    def _to_messages(history: list[dict]) -> list[dict]:
        messages: list[dict] = []
        pending_results: list[dict] = []

        def flush_results() -> None:
            if pending_results:
                messages.append({"role": "user", "content": list(pending_results)})
                pending_results.clear()

        for msg in history:
            role = msg.get("role")
            if role == "tool":
                pending_results.append({
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": str(msg.get("content") or ""),
                    **({"is_error": True} if msg.get("is_error") else {}),
                })
                continue
            flush_results()
            if role == "user":
                messages.append({"role": "user", "content": str(msg.get("content") or "")})
            elif role == "assistant":
                if msg.get("_raw") is not None:
                    messages.append({"role": "assistant", "content": msg["_raw"]})
                    continue
                blocks: list[dict] = []
                if str(msg.get("content") or "").strip():
                    blocks.append({"type": "text", "text": str(msg["content"])})
                for tc in msg.get("tool_calls") or []:
                    blocks.append({
                        "type": "tool_use", "id": tc["id"],
                        "name": tc["name"], "input": tc.get("arguments", {}),
                    })
                if blocks:
                    messages.append({"role": "assistant", "content": blocks})
        flush_results()
        return messages

    @staticmethod
    def _to_tools(tools: list[dict]) -> list[dict]:
        return [
            {"name": t["name"], "description": t["description"],
             "input_schema": t["parameters"]}
            for t in tools
        ]

    # ── Turn execution ───────────────────────────────────────────────────

    def run_turn(self, system: str, history: list[dict], tools: list[dict],
                 on_text: Callable[[str], None]) -> TurnResult:
        params: dict = {
            "model": self.config.model,
            "max_tokens": self.config.max_output_tokens,
            "system": system,
            "messages": self._to_messages(history),
        }
        if tools:
            params["tools"] = self._to_tools(tools)
        if self._modern_params:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {"effort": self.config.effort}
        try:
            return self._stream(params, on_text)
        except self._anthropic.BadRequestError as exc:
            msg = str(exc)
            if self._modern_params and any(k in msg for k in ("thinking", "output_config", "effort")):
                # Model doesn't take adaptive thinking / effort — drop them.
                self._modern_params = False
                params.pop("thinking", None)
                params.pop("output_config", None)
                try:
                    return self._stream(params, on_text)
                except self._anthropic.APIError as exc2:
                    raise BackendError(_anthropic_error(exc2)) from exc2
            raise BackendError(_anthropic_error(exc)) from exc
        except self._anthropic.APIError as exc:
            raise BackendError(_anthropic_error(exc)) from exc

    def _stream(self, params: dict, on_text: Callable[[str], None]) -> TurnResult:
        with self._client.messages.stream(**params) as stream:
            for text in stream.text_stream:
                on_text(text)
            final = stream.get_final_message()
        result = TurnResult(stop_reason=final.stop_reason or "")
        texts: list[str] = []
        for block in final.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                result.tool_calls.append(ToolCall(
                    id=block.id, name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))
        result.text = "".join(texts)
        result.input_tokens = getattr(final.usage, "input_tokens", 0) or 0
        result.output_tokens = getattr(final.usage, "output_tokens", 0) or 0
        # Serialize content blocks so the exact turn (thinking included)
        # can be replayed on the next request.
        result.raw_assistant = [b.model_dump(exclude_none=True) for b in final.content]
        return result

    def summarize(self, prompt: str) -> str:
        try:
            response = self._client.messages.create(
                model=self.config.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
        except self._anthropic.APIError as exc:
            raise BackendError(_anthropic_error(exc)) from exc
        return "".join(b.text for b in response.content if b.type == "text")


def _anthropic_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return "Anthropic rejected the API key (401). Check ANTHROPIC_API_KEY."
    if status == 429:
        return "Rate limited by Anthropic (429). Wait a moment and try again."
    if status == 404:
        return f"Model not found (404). Check the model id. ({exc})"
    return f"Anthropic API error: {exc}"


# ─── OpenAI-compatible ────────────────────────────────────────────────────

class OpenAICompatBackend:
    name = "openai-compatible"

    def __init__(self, config, session=None) -> None:
        self.config = config
        import requests
        self._session = session or requests.Session()
        self._requests = requests
        self._supports_stream_options = True

    # ── History translation ──────────────────────────────────────────────

    @staticmethod
    def _to_messages(system: str, history: list[dict]) -> list[dict]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        for msg in history:
            role = msg.get("role")
            if role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": str(msg.get("content") or ""),
                })
            elif role == "assistant":
                out: dict = {"role": "assistant",
                             "content": str(msg.get("content") or "") or None}
                tcs = msg.get("tool_calls") or []
                if tcs:
                    out["tool_calls"] = [{
                        "id": tc["id"], "type": "function",
                        "function": {"name": tc["name"],
                                     "arguments": json.dumps(tc.get("arguments", {}))},
                    } for tc in tcs]
                messages.append(out)
            elif role == "user":
                messages.append({"role": "user", "content": str(msg.get("content") or "")})
        return messages

    @staticmethod
    def _to_tools(tools: list[dict]) -> list[dict]:
        return [{
            "type": "function",
            "function": {"name": t["name"], "description": t["description"],
                         "parameters": t["parameters"]},
        } for t in tools]

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        headers.update(self.config.extra_headers)
        return headers

    # ── Turn execution ───────────────────────────────────────────────────

    def run_turn(self, system: str, history: list[dict], tools: list[dict],
                 on_text: Callable[[str], None]) -> TurnResult:
        body: dict = {
            "model": self.config.model,
            "messages": self._to_messages(system, history),
            "stream": True,
            "max_tokens": self.config.max_output_tokens,
        }
        if tools:
            body["tools"] = self._to_tools(tools)
        if self._supports_stream_options:
            body["stream_options"] = {"include_usage": True}
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            resp = self._session.post(url, json=body, headers=self._headers(),
                                      stream=True, timeout=(10, 300))
        except self._requests.RequestException as exc:
            raise BackendError(f"Cannot reach {url}: {exc}") from exc
        if resp.status_code == 400 and self._supports_stream_options \
                and "stream_options" in resp.text:
            # Some servers (older Ollama/vLLM) reject stream_options.
            self._supports_stream_options = False
            body.pop("stream_options", None)
            resp = self._session.post(url, json=body, headers=self._headers(),
                                      stream=True, timeout=(10, 300))
        if resp.status_code != 200:
            raise BackendError(_openai_error(resp))
        return self._parse_sse(resp, on_text)

    def _parse_sse(self, resp, on_text: Callable[[str], None]) -> TurnResult:
        result = TurnResult()
        texts: list[str] = []
        # index -> {"id", "name", "arguments"(str)}
        partial_calls: dict[int, dict] = {}
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            usage = chunk.get("usage")
            if usage:
                result.input_tokens = usage.get("prompt_tokens", 0) or 0
                result.output_tokens = usage.get("completion_tokens", 0) or 0
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            if choice.get("finish_reason"):
                result.stop_reason = choice["finish_reason"]
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                texts.append(piece)
                on_text(piece)
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = partial_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
        result.text = "".join(texts)
        for idx in sorted(partial_calls):
            slot = partial_calls[idx]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"].strip() else {}
            except json.JSONDecodeError:
                args = {"_malformed_arguments": slot["arguments"][:2000]}
            if not isinstance(args, dict):
                args = {"value": args}
            result.tool_calls.append(ToolCall(
                id=slot["id"] or f"call_{idx}", name=slot["name"], arguments=args,
            ))
        if result.tool_calls and not result.stop_reason:
            result.stop_reason = "tool_calls"
        return result

    def summarize(self, prompt: str) -> str:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2048,
        }
        try:
            resp = self._session.post(url, json=body, headers=self._headers(),
                                      timeout=(10, 300))
        except self._requests.RequestException as exc:
            raise BackendError(f"Cannot reach {url}: {exc}") from exc
        if resp.status_code != 200:
            raise BackendError(_openai_error(resp))
        data = resp.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""


def _openai_error(resp) -> str:
    detail = ""
    try:
        detail = resp.json().get("error", {}).get("message", "")
    except Exception:
        detail = resp.text[:300]
    if resp.status_code == 401:
        return f"Provider rejected the API key (401). {detail}"
    if resp.status_code == 429:
        return f"Rate limited (429). {detail}"
    if resp.status_code == 404:
        return f"Endpoint or model not found (404). {detail}"
    return f"Provider error {resp.status_code}: {detail}"


def make_backend(config) -> Backend:
    if config.provider == "anthropic":
        return AnthropicBackend(config)
    return OpenAICompatBackend(config)
