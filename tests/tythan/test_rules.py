from tythan.rules import MAX_RULES_CHARS, load_rules


class TestRules:
    def test_no_rules_file(self, tmp_path):
        assert load_rules(tmp_path) == ""

    def test_tythanrules_wins_over_cursorrules(self, tmp_path):
        (tmp_path / ".tythanrules").write_text("tythan rules")
        (tmp_path / ".cursorrules").write_text("cursor rules")
        out = load_rules(tmp_path)
        assert "tythan rules" in out and "cursor rules" not in out

    def test_cursorrules_and_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("agents md content")
        assert "agents md content" in load_rules(tmp_path)
        (tmp_path / ".cursorrules").write_text("cursor content")
        assert "cursor content" in load_rules(tmp_path)

    def test_empty_file_falls_through(self, tmp_path):
        (tmp_path / ".tythanrules").write_text("   \n")
        (tmp_path / "AGENTS.md").write_text("fallback")
        assert "fallback" in load_rules(tmp_path)

    def test_truncation(self, tmp_path):
        (tmp_path / ".tythanrules").write_text("x" * (MAX_RULES_CHARS + 100))
        out = load_rules(tmp_path)
        assert "truncated" in out
        assert len(out) < MAX_RULES_CHARS + 200
