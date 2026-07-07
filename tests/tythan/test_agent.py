import pytest

from tythan.agent import Agent, YoloApprover
from tythan.config import Config
from tythan.providers import BackendError, ToolCall, TurnResult
from tythan.tools import Workspace


class FakeBackend:
    """Replays a scripted list of TurnResults."""
    name = "fake"

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []          # (system, history_copy, tools)
        self.summaries = []

    def run_turn(self, system, history, tools, on_text):
        self.requests.append((system, [dict(m) for m in history], tools))
        if not self.turns:
            return TurnResult(text="(fake: out of turns)", stop_reason="end_turn")
        result = self.turns.pop(0)
        if result.text:
            on_text(result.text)
        return result

    def summarize(self, prompt):
        self.summaries.append(prompt)
        return "fake summary of earlier conversation"


class ScriptedApprover:
    def __init__(self, write_answers=(), command_answers=()):
        self.write_answers = list(write_answers)
        self.command_answers = list(command_answers)
        self.seen_writes = []

    def approve_write(self, write, findings):
        self.seen_writes.append((write, findings))
        return self.write_answers.pop(0) if self.write_answers else True

    def approve_command(self, command):
        return self.command_answers.pop(0) if self.command_answers else True


def make_agent(tmp_path, turns, approver=None, **cfg):
    cfg.setdefault("provider", "ollama")   # no API key needed
    config = Config(**cfg)
    ws = Workspace(tmp_path)
    backend = FakeBackend(turns)
    agent = Agent(config, ws, backend, approver or ScriptedApprover())
    return agent, backend


def tc(name, **arguments):
    tc.count = getattr(tc, "count", 0) + 1
    return ToolCall(id=f"call_{tc.count}", name=name, arguments=arguments)


class TestToolLoop:
    def test_plain_answer(self, tmp_path):
        agent, backend = make_agent(tmp_path, [TurnResult(text="hello")])
        out = []
        stats = agent.run_user_turn("hi", out.append)
        assert "".join(out) == "hello"
        assert stats.rounds == 1
        assert [m["role"] for m in agent.history] == ["user", "assistant"]

    def test_tool_round_trip(self, tmp_path):
        (tmp_path / "f.txt").write_text("data42\n")
        agent, backend = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("read_file", path="f.txt")], stop_reason="tool_use"),
            TurnResult(text="done"),
        ])
        agent.run_user_turn("read it", lambda s: None)
        tool_msgs = [m for m in agent.history if m["role"] == "tool"]
        assert len(tool_msgs) == 1 and "data42" in tool_msgs[0]["content"]
        # second request must include the tool result
        assert any(m["role"] == "tool" for m in backend.requests[1][1])

    def test_every_tool_use_gets_result_on_crash(self, tmp_path):
        call = tc("read_file", path="f.txt")
        boom = tc("glob", pattern="*")

        class ExplodingBackend(FakeBackend):
            pass

        agent, backend = make_agent(tmp_path, [
            TurnResult(tool_calls=[call, boom], stop_reason="tool_use"),
        ])

        def exploding_execute(t):
            if t is boom:
                raise KeyboardInterrupt
            return "ok", False, None
        agent._execute = exploding_execute
        with pytest.raises(KeyboardInterrupt):
            agent.run_user_turn("go", lambda s: None)
        tool_ids = [m["tool_call_id"] for m in agent.history if m["role"] == "tool"]
        assert set(tool_ids) == {call.id, boom.id}

    def test_max_turns_cap(self, tmp_path):
        turns = [TurnResult(tool_calls=[tc("list_dir")], stop_reason="tool_use")
                 for _ in range(10)]
        agent, _ = make_agent(tmp_path, turns, max_turns=3)
        stats = agent.run_user_turn("loop", lambda s: None)
        assert stats.rounds == 3

    def test_unknown_tool_reports_error(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("format_disk")], stop_reason="tool_use"),
            TurnResult(text="ok"),
        ])
        agent.run_user_turn("x", lambda s: None)
        err = [m for m in agent.history if m["role"] == "tool"][0]
        assert err.get("is_error") and "unknown tool" in err["content"]


class TestWritesAndApproval:
    def test_approved_write_lands_and_checkpoints(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("write_file", path="a.py", content="x = 1\n")],
                       stop_reason="tool_use"),
            TurnResult(text="done"),
        ], approver=ScriptedApprover(write_answers=[True]))
        stats = agent.run_user_turn("write", lambda s: None)
        assert (tmp_path / "a.py").read_text() == "x = 1\n"
        assert stats.files_changed == ["a.py"]
        restored, _ = agent.undo_last()
        assert not (tmp_path / "a.py").exists() and restored

    def test_denied_write_does_not_land(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("write_file", path="a.py", content="x = 1\n")],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], approver=ScriptedApprover(write_answers=[False]))
        agent.run_user_turn("write", lambda s: None)
        assert not (tmp_path / "a.py").exists()
        err = [m for m in agent.history if m["role"] == "tool"][0]
        assert err.get("is_error") and "rejected" in err["content"]

    def test_yolo_skips_approval(self, tmp_path):
        approver = ScriptedApprover(write_answers=[False])  # would deny if asked
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("write_file", path="a.py", content="x = 1\n")],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], approver=approver, yolo=True)
        agent.run_user_turn("write", lambda s: None)
        assert (tmp_path / "a.py").exists()
        assert approver.seen_writes == []

    def test_denied_command(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("run_command", command="echo hi")],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], approver=ScriptedApprover(command_answers=[False]))
        agent.run_user_turn("run", lambda s: None)
        err = [m for m in agent.history if m["role"] == "tool"][0]
        assert err.get("is_error") and "denied" in err["content"]


class TestSecurityGate:
    CRITICAL_CODE = 'cur.execute(f"SELECT * FROM u WHERE id = {uid}")\n'

    def test_critical_write_blocked(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("write_file", path="db.py",
                                      content=self.CRITICAL_CODE)],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], approver=ScriptedApprover(write_answers=[True]))
        agent.run_user_turn("write", lambda s: None)
        assert not (tmp_path / "db.py").exists()
        err = [m for m in agent.history if m["role"] == "tool"][0]
        assert "BLOCKED" in err["content"] and "PY-SQL-FSTRING" in err["content"]

    def test_critical_blocked_even_in_yolo(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("write_file", path="db.py",
                                      content=self.CRITICAL_CODE)],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], yolo=True)
        agent.run_user_turn("write", lambda s: None)
        assert not (tmp_path / "db.py").exists()

    def test_allow_critical_flag(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("write_file", path="db.py",
                                      content=self.CRITICAL_CODE)],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], yolo=True, block_critical=False)
        agent.run_user_turn("write", lambda s: None)
        assert (tmp_path / "db.py").exists()

    def test_high_finding_reported_not_blocked(self, tmp_path):
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("write_file", path="r.py",
                                      content="requests.get(u, verify=False)\n")],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], yolo=True)
        agent.run_user_turn("write", lambda s: None)
        assert (tmp_path / "r.py").exists()
        note = [m for m in agent.history if m["role"] == "tool"][0]["content"]
        assert "PY-VERIFY-FALSE" in note

    def test_gate_only_scans_introduced_lines(self, tmp_path):
        (tmp_path / "l.py").write_text("subprocess.run(c, shell=True)\nx = 1\n")
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("edit_file", path="l.py",
                                      old_string="x = 1", new_string="x = 2")],
                       stop_reason="tool_use"),
            TurnResult(text="ok"),
        ], yolo=True)
        agent.run_user_turn("edit", lambda s: None)
        note = [m for m in agent.history if m["role"] == "tool"][0]["content"]
        assert "shell" not in note.lower()
        assert (tmp_path / "l.py").read_text().endswith("x = 2\n")

    def test_security_scan_tool(self, tmp_path):
        (tmp_path / "bad.py").write_text("eval(x())\n")
        agent, _ = make_agent(tmp_path, [
            TurnResult(tool_calls=[tc("security_scan")], stop_reason="tool_use"),
            TurnResult(text="ok"),
        ])
        agent.run_user_turn("scan", lambda s: None)
        out = [m for m in agent.history if m["role"] == "tool"][0]["content"]
        assert "PY-EVAL" in out


class TestRulesAndCompaction:
    def test_rules_file_in_system_prompt(self, tmp_path):
        (tmp_path / ".cursorrules").write_text("Always answer in haiku.")
        agent, backend = make_agent(tmp_path, [TurnResult(text="ok")])
        agent.run_user_turn("hi", lambda s: None)
        assert "Always answer in haiku." in backend.requests[0][0]

    def test_compaction_triggered_by_small_window(self, tmp_path):
        agent, backend = make_agent(
            tmp_path,
            [TurnResult(text="a" * 4000) for _ in range(6)],
            context_window=2000, max_output_tokens=100,
        )
        for i in range(6):
            agent.run_user_turn(f"msg {i} " + "y" * 1000, lambda s: None)
        assert backend.summaries, "compaction should have summarized"
        assert any("fake summary" in str(m.get("content")) for m in agent.history)

    def test_compaction_failure_is_not_fatal(self, tmp_path):
        agent, backend = make_agent(
            tmp_path, [TurnResult(text="x")],
            context_window=2000, max_output_tokens=100,
        )
        agent.history = [{"role": "user", "content": "q" * 9000},
                         {"role": "assistant", "content": "a"},
                         {"role": "user", "content": "q2"},
                         {"role": "assistant", "content": "a2"},
                         {"role": "user", "content": "q3"},
                         {"role": "assistant", "content": "a3"}]

        def failing_summarize(prompt):
            raise BackendError("offline")
        backend.summarize = failing_summarize
        agent.run_user_turn("continue", lambda s: None)   # must not raise
        assert agent.history[-1]["role"] == "assistant"
