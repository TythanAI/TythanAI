# TythanAI Security Platform — Community Edition
# Copyright (c) 2026 TythanAI Labs
# Licensed under the Business Source License 1.1 (see LICENSE).

"""
tythan/config.py — provider configuration and context-window defaults.

API keys come from environment variables only; they are never written to
disk by tythan.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

PROVIDERS = ("anthropic", "openai", "openrouter", "ollama", "custom")

DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-8",
    "openai": "gpt-5.2",
    "openrouter": "anthropic/claude-opus-4.8",
    "ollama": "qwen3-coder",
    "custom": "",
}

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}

_KEY_ENV_VARS = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY", "OPENAI_API_KEY"),
    "ollama": (),  # local — no key needed
    "custom": ("TYTHAN_API_KEY", "OPENAI_API_KEY"),
}

# Conservative context-window assumptions (tokens). Local servers commonly
# run with a much smaller context than the underlying model supports, so
# ollama/custom default low; override with --context-window.
_CONTEXT_WINDOWS = {
    "anthropic": 200_000,
    "openai": 128_000,
    "openrouter": 128_000,
    "ollama": 8_192,
    "custom": 8_192,
}


@dataclass
class Config:
    provider: str = "anthropic"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    max_output_tokens: int = 8_192
    context_window: int = 0        # 0 = use provider default
    effort: str = "high"           # Anthropic reasoning effort
    yolo: bool = False             # auto-approve writes/commands
    security_gate: bool = True     # scan agent-authored changes pre-write
    block_critical: bool = True    # refuse writes with CRITICAL findings unless overridden
    max_turns: int = 40            # max tool rounds per user message
    command_timeout: int = 120     # seconds per run_command
    extra_headers: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}; expected one of {PROVIDERS}")
        if not self.model:
            self.model = DEFAULT_MODELS[self.provider]
        if not self.base_url:
            self.base_url = os.environ.get("TYTHAN_BASE_URL", "") or DEFAULT_BASE_URLS.get(self.provider, "")
        if not self.api_key:
            self.api_key = self.resolve_api_key(self.provider)
        if not self.context_window:
            self.context_window = _CONTEXT_WINDOWS[self.provider]

    @staticmethod
    def resolve_api_key(provider: str) -> str:
        for var in _KEY_ENV_VARS.get(provider, ()):
            val = os.environ.get(var)
            if val:
                return val
        return ""

    def require_api_key(self) -> None:
        # Local/self-hosted endpoints commonly run without auth.
        if self.provider in ("ollama", "custom"):
            return
        if not self.api_key:
            vars_ = " or ".join(_KEY_ENV_VARS.get(self.provider, ("TYTHAN_API_KEY",)))
            raise SystemExit(
                f"No API key found for provider {self.provider!r}. Set {vars_} in your environment."
            )
