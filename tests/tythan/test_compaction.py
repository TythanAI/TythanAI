from tythan.compaction import (
    compact,
    estimate_tokens,
    needs_compaction,
    split_rounds,
    transcript_for_summary,
)


def user(text):
    return {"role": "user", "content": text}


def assistant(text, calls=None):
    return {"role": "assistant", "content": text, "tool_calls": calls or []}


class TestSplitRounds:
    def test_basic(self):
        h = [user("a"), assistant("x"), user("b"), assistant("y")]
        rounds = split_rounds(h)
        assert len(rounds) == 2
        assert rounds[0][0]["content"] == "a"

    def test_tool_messages_stay_in_round(self):
        h = [user("a"), assistant("", [{"id": "1", "name": "t", "arguments": {}}]),
             {"role": "tool", "tool_call_id": "1", "content": "out"},
             assistant("done"), user("b")]
        rounds = split_rounds(h)
        assert len(rounds) == 2 and len(rounds[0]) == 4

    def test_leading_summary_is_own_round(self):
        h = [assistant("summary"), user("a"), assistant("x")]
        assert len(split_rounds(h)) == 2

    def test_empty(self):
        assert split_rounds([]) == []


class TestEstimateAndTrigger:
    def test_estimate_counts_tool_calls(self):
        h = [assistant("", [{"id": "1", "name": "grep", "arguments": {"pattern": "x" * 400}}])]
        assert estimate_tokens(h) > 100

    def test_needs_compaction_thresholds(self):
        small = [user("hi")]
        assert not needs_compaction(small, 8000, 1000)
        big = [user("x" * 40_000)]
        assert needs_compaction(big, 8000, 1000)


class TestCompact:
    def test_keeps_recent_rounds(self):
        h = []
        for i in range(5):
            h += [user(f"q{i}"), assistant(f"a{i}")]
        out = compact(h, "SUMMARY TEXT", keep_rounds=2)
        assert "SUMMARY TEXT" in out[0]["content"]
        contents = [m.get("content") for m in out]
        assert "q3" in contents and "q4" in contents and "q0" not in contents

    def test_noop_when_few_rounds(self):
        h = [user("a"), assistant("x")]
        assert compact(h, "s", keep_rounds=2) is h

    def test_transcript_capped_from_front(self):
        rounds = [[user("OLD " + "x" * 100)], [user("NEW tail")]]
        text = transcript_for_summary(rounds, cap_chars=40)
        assert "NEW tail" in text and text.startswith("…(older context omitted)")
