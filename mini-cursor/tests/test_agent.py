"""Agent-loop tests with a stubbed backend (no network)."""

from minicursor.agent import Agent
from minicursor.config import Config
from minicursor.providers.base import Backend, ToolCall, TurnResult
from minicursor.ui import UI

from rich.console import Console


class FakeBackend(Backend):
    """Scripted backend: returns pre-baked TurnResults, records history calls."""

    name = "fake"

    def __init__(self, turns: list[TurnResult]):
        super().__init__(model="fake-model")
        self.turns = list(turns)
        self.calls = 0

    def add_user_message(self, messages, text):
        messages.append({"role": "user", "content": text})

    def add_tool_results(self, messages, results):
        messages.append({"role": "tool_results", "results": results})

    def stream_turn(self, messages, system, tools, ui):
        self.calls += 1
        assert "mini-cursor" in system  # system prompt is passed through
        assert any(t["name"] == "read_file" for t in tools)
        return self.turns.pop(0)


def make_agent(tmp_path, turns):
    config = Config(workspace=tmp_path, yolo=True)
    ui = UI(Console(file=open("/dev/null", "w"), force_terminal=False))
    return Agent(config, ui, FakeBackend(turns))


def test_tool_round_trip(tmp_path):
    (tmp_path / "hello.txt").write_text("hi there\n")
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="read_file", input={"path": "hello.txt"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, turns)
    agent.run_turn("what's in hello.txt?")

    assert agent.backend.calls == 2
    # history: user, tool_results (assistant msgs are appended by real backends)
    tool_msg = agent.messages[1]
    assert tool_msg["role"] == "tool_results"
    result = tool_msg["results"][0]
    assert result.call_id == "tu_1"
    assert "hi there" in result.output
    assert result.is_error is False


def test_tool_error_reported(tmp_path):
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="read_file", input={"path": "missing.txt"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, turns)
    agent.run_turn("read missing.txt")

    result = agent.messages[1]["results"][0]
    assert result.is_error is True
    assert "not found" in result.output


def test_refusal_ends_turn(tmp_path):
    agent = make_agent(tmp_path, [TurnResult("refusal")])
    agent.run_turn("hello")
    assert agent.backend.calls == 1
    assert agent.messages[0]["role"] == "user"
    assert len(agent.messages) == 1


def test_write_declined_when_not_confirmed(tmp_path, monkeypatch):
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="write_file",
                                         input={"path": "a.txt", "content": "data"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, turns)
    agent.config.yolo = False
    monkeypatch.setattr(agent.ui, "confirm", lambda prompt: False)
    monkeypatch.setattr(agent.ui, "show_diff", lambda *a, **k: None)

    agent.run_turn("create a.txt")

    assert not (tmp_path / "a.txt").exists()
    result = agent.messages[1]["results"][0]
    assert result.is_error is True
    assert "declined" in result.output


def test_set_backend_resets_history(tmp_path):
    agent = make_agent(tmp_path, [TurnResult("end")])
    agent.run_turn("hi")
    assert agent.messages
    agent.set_backend(FakeBackend([TurnResult("end")]))
    assert agent.messages == []
