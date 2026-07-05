"""Agent-level tests for context compaction and checkpoint/undo wiring.

Uses a scripted FakeBackend (no network), same style as test_agent.py, but one
that implements render_round/complete_text/context_window so compaction can
actually be exercised. Checkpoint storage is always pointed at tmp_path so
these tests never touch the real ~/.minicursor directory.
"""

from rich.console import Console

from minicursor.agent import Agent
from minicursor.checkpoints import CheckpointStore
from minicursor.config import Config
from minicursor.providers.base import Backend, ToolCall, TurnResult
from minicursor.ui import UI


class ScriptedBackend(Backend):
    """Backend whose stream_turn results are pre-scripted, and whose
    compaction hooks are simple, inspectable fakes."""

    name = "scripted"

    def __init__(self, turns=None, context_window=32_000, summary="SUMMARY"):
        super().__init__(model="fake-model", context_window=context_window)
        self.turns = list(turns or [])
        self.calls = 0
        self.summary_calls: list[str] = []
        self.summary_text = summary
        self.complete_text_error: Exception | None = None

    def add_user_message(self, messages, text):
        messages.append({"role": "user", "content": text})

    def add_tool_results(self, messages, results):
        messages.append({"role": "tool_results", "results": results})

    def stream_turn(self, messages, system, tools, ui):
        self.calls += 1
        if self.turns:
            return self.turns.pop(0)
        return TurnResult("end")

    def complete_text(self, system, user_text):
        if self.complete_text_error:
            raise self.complete_text_error
        self.summary_calls.append(user_text)
        return self.summary_text


def make_agent(tmp_path, backend, **config_kwargs):
    config = Config(workspace=tmp_path, yolo=True, **config_kwargs)
    ui = UI(Console(file=open("/dev/null", "w"), force_terminal=False))
    store = CheckpointStore(tmp_path, storage_dir=tmp_path / ".checkpoints")
    return Agent(config, ui, backend, checkpoint_store=store)


# -- checkpoints --------------------------------------------------------


def test_write_file_creates_undoable_checkpoint(tmp_path):
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="write_file",
                                          input={"path": "a.txt", "content": "v1"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, ScriptedBackend(turns))
    agent.run_turn("create a.txt")

    assert (tmp_path / "a.txt").read_text() == "v1"
    cps = agent.checkpoints.list()
    assert len(cps) == 1
    assert cps[0].changes[0].existed_before is False

    agent.checkpoints.undo_last()
    assert not (tmp_path / "a.txt").exists()


def test_edit_file_checkpoint_restores_previous_content(tmp_path):
    (tmp_path / "a.txt").write_text("original")
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="edit_file",
                                          input={"path": "a.txt", "old_string": "original",
                                                 "new_string": "changed"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, ScriptedBackend(turns))
    agent.run_turn("change a.txt")

    assert (tmp_path / "a.txt").read_text() == "changed"
    agent.checkpoints.undo_last()
    assert (tmp_path / "a.txt").read_text() == "original"


def test_declined_write_creates_no_checkpoint(tmp_path, monkeypatch):
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="write_file",
                                          input={"path": "a.txt", "content": "v1"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, ScriptedBackend(turns))
    agent.config.yolo = False
    monkeypatch.setattr(agent.ui, "confirm", lambda prompt: False)
    monkeypatch.setattr(agent.ui, "show_diff", lambda *a, **k: None)

    agent.run_turn("create a.txt")

    assert not (tmp_path / "a.txt").exists()
    assert agent.checkpoints.list() == []


def test_read_only_turn_creates_no_checkpoint(tmp_path):
    (tmp_path / "hello.txt").write_text("hi")
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="read_file", input={"path": "hello.txt"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, ScriptedBackend(turns))
    agent.run_turn("what's in hello.txt?")
    assert agent.checkpoints.list() == []


def test_checkpoints_disabled_via_config(tmp_path):
    turns = [
        TurnResult("tool_use", [ToolCall(id="tu_1", name="write_file",
                                          input={"path": "a.txt", "content": "v1"})]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, ScriptedBackend(turns), checkpoints_enabled=False)
    agent.run_turn("create a.txt")

    assert (tmp_path / "a.txt").read_text() == "v1"
    assert agent.checkpoints.list() == []


def test_multi_file_turn_is_one_checkpoint(tmp_path):
    turns = [
        TurnResult("tool_use", [
            ToolCall(id="tu_1", name="write_file", input={"path": "a.txt", "content": "a"}),
            ToolCall(id="tu_2", name="write_file", input={"path": "b.txt", "content": "b"}),
        ]),
        TurnResult("end"),
    ]
    agent = make_agent(tmp_path, ScriptedBackend(turns))
    agent.run_turn("create both files")

    cps = agent.checkpoints.list()
    assert len(cps) == 1
    assert {c.path for c in cps[0].changes} == {str(tmp_path / "a.txt"), str(tmp_path / "b.txt")}

    agent.checkpoints.undo_last()
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


# -- compaction -----------------------------------------------------------


def test_maybe_compact_noop_when_history_is_small(tmp_path):
    agent = make_agent(tmp_path, ScriptedBackend([]))
    agent.messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert agent.maybe_compact() is False
    assert len(agent.messages) == 2


def test_maybe_compact_forced_summarizes_old_rounds_keeps_recent(tmp_path):
    backend = ScriptedBackend([], summary="the user asked X, we did Y")
    agent = make_agent(tmp_path, backend, compact_keep_rounds=1)
    for i in range(4):
        agent.messages.append({"role": "user", "content": f"turn {i}"})
        agent.messages.append({"role": "assistant", "content": f"reply {i}"})

    compacted = agent.maybe_compact(force=True)

    assert compacted is True
    assert len(backend.summary_calls) == 1
    # only the last round (1 kept) should remain, prefixed with the summary
    assert len(agent.messages) == 2
    assert "the user asked X, we did Y" in agent.messages[0]["content"]
    assert "turn 3" in agent.messages[0]["content"]
    assert agent.messages[1]["content"] == "reply 3"


def test_maybe_compact_never_summarizes_away_the_newest_round(tmp_path):
    backend = ScriptedBackend([], summary="summary")
    agent = make_agent(tmp_path, backend, compact_keep_rounds=2)
    for i in range(3):
        agent.messages.append({"role": "user", "content": f"turn {i}"})
        agent.messages.append({"role": "assistant", "content": f"reply {i}"})

    agent.maybe_compact(force=True)
    # last message is still the newest assistant reply, never dropped
    assert agent.messages[-1]["content"] == "reply 2"


def test_maybe_compact_not_enough_rounds_is_a_noop_even_forced(tmp_path):
    backend = ScriptedBackend([])
    agent = make_agent(tmp_path, backend, compact_keep_rounds=5)
    agent.messages = [
        {"role": "user", "content": "only one round"},
        {"role": "assistant", "content": "reply"},
    ]
    assert agent.maybe_compact(force=True) is False
    assert len(backend.summary_calls) == 0


def test_maybe_compact_auto_triggers_when_over_budget(tmp_path):
    # Tiny context window makes the token budget tiny, so even a short
    # history should cross the compaction threshold automatically.
    backend = ScriptedBackend([], context_window=1200, summary="compacted")
    agent = make_agent(tmp_path, backend, max_tokens=100, compact_keep_rounds=1)
    for i in range(4):
        agent.messages.append({"role": "user", "content": f"turn {i} " + "x" * 2000})
        agent.messages.append({"role": "assistant", "content": f"reply {i}"})

    assert agent.maybe_compact() is True
    assert len(backend.summary_calls) == 1


def test_maybe_compact_uses_real_backend_usage_over_heuristic(tmp_path):
    backend = ScriptedBackend([], context_window=1_000_000, summary="compacted")
    agent = make_agent(tmp_path, backend, compact_keep_rounds=1)
    for i in range(3):  # more rounds than compact_keep_rounds, so there's something to summarize
        agent.messages.append({"role": "user", "content": f"tiny {i}"})
        agent.messages.append({"role": "assistant", "content": f"ok {i}"})
    backend.last_context_tokens = 999_999  # way over budget despite the tiny history
    assert agent.context_tokens_estimate() == 999_999
    assert agent.maybe_compact() is True  # would be False on the heuristic alone


def test_compaction_failure_is_reported_and_does_not_crash(tmp_path):
    backend = ScriptedBackend([])
    backend.complete_text_error = ConnectionError("network down")
    agent = make_agent(tmp_path, backend, compact_keep_rounds=1)
    for i in range(3):
        agent.messages.append({"role": "user", "content": f"turn {i}"})
        agent.messages.append({"role": "assistant", "content": f"reply {i}"})
    before = list(agent.messages)

    result = agent.maybe_compact(force=True)

    assert result is False
    assert agent.messages == before  # history untouched on failure
    assert agent._compaction_unavailable is True


def test_compaction_unavailable_flag_skips_further_attempts_this_turn(tmp_path):
    backend = ScriptedBackend(
        [TurnResult("end"), TurnResult("end")],
        context_window=1200,
    )
    backend.complete_text_error = RuntimeError("boom")
    agent = make_agent(tmp_path, backend, max_tokens=100, compact_keep_rounds=1)
    for i in range(4):
        agent.messages.append({"role": "user", "content": f"turn {i} " + "x" * 2000})
        agent.messages.append({"role": "assistant", "content": f"reply {i}"})

    # First explicit attempt fails and flips the flag.
    assert agent.maybe_compact() is False
    assert agent._compaction_unavailable is True
    # A second attempt in the same turn should short-circuit without calling
    # complete_text again (no exception raised means it didn't try).
    assert agent.maybe_compact() is False


def test_run_turn_resets_compaction_unavailable_flag_each_turn(tmp_path):
    agent = make_agent(tmp_path, ScriptedBackend([TurnResult("end")]))
    agent._compaction_unavailable = True
    agent.run_turn("hello")
    assert agent._compaction_unavailable is False
