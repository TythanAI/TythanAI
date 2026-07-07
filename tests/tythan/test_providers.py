import json

import pytest

from tythan.config import Config
from tythan.providers import (
    AnthropicBackend,
    BackendError,
    OpenAICompatBackend,
    make_backend,
)

HISTORY = [
    {"role": "user", "content": "read the file"},
    {"role": "assistant", "content": "reading",
     "tool_calls": [{"id": "c1", "name": "read_file", "arguments": {"path": "a.py"}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "1\tx = 1"},
    {"role": "assistant", "content": "done", "tool_calls": []},
]

TOOLS = [{"name": "read_file", "description": "Read a file",
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                         "required": ["path"]}}]


class TestAnthropicTranslation:
    def test_messages_shape(self):
        msgs = AnthropicBackend._to_messages(HISTORY)
        assert msgs[0] == {"role": "user", "content": "read the file"}
        blocks = msgs[1]["content"]
        assert blocks[0]["type"] == "text"
        assert blocks[1] == {"type": "tool_use", "id": "c1",
                             "name": "read_file", "input": {"path": "a.py"}}
        result_msg = msgs[2]
        assert result_msg["role"] == "user"
        assert result_msg["content"][0]["type"] == "tool_result"
        assert result_msg["content"][0]["tool_use_id"] == "c1"

    def test_consecutive_tool_results_merge(self):
        history = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "1", "name": "a", "arguments": {}},
                {"id": "2", "name": "b", "arguments": {}}]},
            {"role": "tool", "tool_call_id": "1", "content": "r1"},
            {"role": "tool", "tool_call_id": "2", "content": "r2", "is_error": True},
        ]
        msgs = AnthropicBackend._to_messages(history)
        assert len(msgs) == 3
        results = msgs[2]["content"]
        assert len(results) == 2 and results[1]["is_error"] is True

    def test_raw_content_reused_verbatim(self):
        raw = [{"type": "thinking", "thinking": "", "signature": "sig"},
               {"type": "text", "text": "hi"}]
        history = [{"role": "user", "content": "x"},
                   {"role": "assistant", "content": "hi", "_raw": raw}]
        msgs = AnthropicBackend._to_messages(history)
        assert msgs[1]["content"] is raw

    def test_tools_shape(self):
        out = AnthropicBackend._to_tools(TOOLS)
        assert out[0]["input_schema"]["required"] == ["path"]


class FakeResponse:
    def __init__(self, status_code=200, lines=(), body=None):
        self.status_code = status_code
        self._lines = lines
        self._body = body or {}
        self.text = json.dumps(self._body)

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, stream=False, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def sse(events):
    lines = [f"data: {json.dumps(e)}" for e in events]
    lines.append("data: [DONE]")
    return lines


def openai_config(**kw):
    kw.setdefault("provider", "custom")
    kw.setdefault("model", "test-model")
    kw.setdefault("base_url", "http://fake.local/v1")
    kw.setdefault("api_key", "k")
    return Config(**kw)


class TestOpenAICompat:
    def test_request_shape(self):
        session = FakeSession([FakeResponse(lines=sse(
            [{"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]},
             {"choices": [{"delta": {}, "finish_reason": "stop"}]}]))])
        be = OpenAICompatBackend(openai_config(), session=session)
        result = be.run_turn("sys", HISTORY, TOOLS, lambda s: None)
        body = session.calls[0]["json"]
        assert body["messages"][0] == {"role": "system", "content": "sys"}
        assistant = body["messages"][2]
        assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
        assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"path": "a.py"}
        assert body["tools"][0]["type"] == "function"
        assert session.calls[0]["headers"]["Authorization"] == "Bearer k"
        assert result.text == "hi" and result.stop_reason == "stop"

    def test_streamed_tool_call_assembly(self):
        events = [
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_9",
                 "function": {"name": "read_file", "arguments": ""}}]},
                "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": '{"pa'}}]},
                "finish_reason": None}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": 'th": "a.py"}'}}]},
                "finish_reason": "tool_calls"}]},
            {"usage": {"prompt_tokens": 10, "completion_tokens": 5}, "choices": []},
        ]
        session = FakeSession([FakeResponse(lines=sse(events))])
        be = OpenAICompatBackend(openai_config(), session=session)
        result = be.run_turn("s", [{"role": "user", "content": "x"}], TOOLS, lambda s: None)
        assert len(result.tool_calls) == 1
        call = result.tool_calls[0]
        assert call.id == "call_9" and call.arguments == {"path": "a.py"}
        assert result.input_tokens == 10 and result.output_tokens == 5

    def test_malformed_tool_arguments_contained(self):
        events = [{"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c", "function": {"name": "t", "arguments": "{broken"}}]},
            "finish_reason": "tool_calls"}]}]
        session = FakeSession([FakeResponse(lines=sse(events))])
        be = OpenAICompatBackend(openai_config(), session=session)
        result = be.run_turn("s", [{"role": "user", "content": "x"}], TOOLS, lambda s: None)
        assert "_malformed_arguments" in result.tool_calls[0].arguments

    def test_stream_options_fallback(self):
        bad = FakeResponse(status_code=400,
                           body={"error": {"message": "stream_options not supported"}})
        good = FakeResponse(lines=sse(
            [{"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}]))
        session = FakeSession([bad, good])
        be = OpenAICompatBackend(openai_config(), session=session)
        result = be.run_turn("s", [{"role": "user", "content": "x"}], [], lambda s: None)
        assert result.text == "ok"
        assert "stream_options" not in session.calls[1]["json"]
        assert be._supports_stream_options is False

    def test_http_error_raises_backend_error(self):
        session = FakeSession([FakeResponse(
            status_code=401, body={"error": {"message": "bad key"}})])
        be = OpenAICompatBackend(openai_config(), session=session)
        with pytest.raises(BackendError, match="401"):
            be.run_turn("s", [{"role": "user", "content": "x"}], [], lambda s: None)

    def test_summarize(self):
        session = FakeSession([FakeResponse(
            body={"choices": [{"message": {"content": "the summary"}}]})])
        be = OpenAICompatBackend(openai_config(), session=session)
        assert be.summarize("summarize this") == "the summary"


class TestFactory:
    def test_openai_compat_for_ollama(self):
        be = make_backend(Config(provider="ollama"))
        assert isinstance(be, OpenAICompatBackend)

    def test_config_defaults(self):
        cfg = Config(provider="ollama")
        assert cfg.base_url.endswith("/v1")
        assert cfg.context_window == 8192
        cfg2 = Config(provider="anthropic", api_key="k")
        assert cfg2.model == "claude-opus-4-8"
        assert cfg2.context_window == 200_000

    def test_unknown_provider_rejected(self):
        with pytest.raises(ValueError):
            Config(provider="skynet")
