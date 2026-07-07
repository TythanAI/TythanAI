import os
import sys
import time

import pytest

from tythan.tools import ProposedWrite, ToolError, Workspace


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def main():\n    return 42\n")
    (tmp_path / "readme.md").write_text("hello tythan\n")
    return Workspace(tmp_path)


class TestConfinement:
    def test_relative_inside(self, ws):
        assert ws.resolve("src/app.py").name == "app.py"

    def test_dotdot_escape_rejected(self, ws):
        with pytest.raises(ToolError):
            ws.resolve("../outside.txt")

    def test_absolute_outside_rejected(self, ws):
        with pytest.raises(ToolError):
            ws.resolve("/etc/passwd")

    def test_absolute_inside_allowed(self, ws):
        p = ws.resolve(str(ws.root / "readme.md"))
        assert p == ws.root / "readme.md"

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
    def test_symlink_escape_rejected(self, ws, tmp_path_factory):
        outside = tmp_path_factory.mktemp("outside")
        (outside / "secret.txt").write_text("secret")
        os.symlink(outside, ws.root / "link")
        with pytest.raises(ToolError):
            ws.resolve("link/secret.txt")

    def test_empty_path_rejected(self, ws):
        with pytest.raises(ToolError):
            ws.resolve("  ")

    def test_nonexistent_path_inside_ok(self, ws):
        p = ws.resolve("newdir/newfile.txt")
        assert ws.root in p.parents


class TestReadTools:
    def test_read_numbers_lines(self, ws):
        out = ws.read_file("src/app.py")
        assert "1\tdef main():" in out

    def test_read_offset_limit(self, ws):
        out = ws.read_file("src/app.py", offset=1, limit=1)
        assert "return 42" in out and "def main" not in out

    def test_read_directory_fails(self, ws):
        with pytest.raises(ToolError):
            ws.read_file("src")

    def test_list_dir(self, ws):
        out = ws.list_dir(".")
        assert "src/" in out and "readme.md" in out

    def test_glob(self, ws):
        assert "src/app.py" in ws.glob("**/*.py")
        assert "(no matches)" in ws.glob("*.rs")

    def test_grep(self, ws):
        out = ws.grep("return 42", include="*.py")
        assert "src/app.py:2" in out

    def test_grep_invalid_regex(self, ws):
        with pytest.raises(ToolError):
            ws.grep("(unclosed")


class TestWrites:
    def test_propose_write_new_file(self, ws):
        w = ws.propose_write("new.txt", "content")
        assert w.old_content is None
        Workspace.apply_write(w)
        assert (ws.root / "new.txt").read_text() == "content"

    def test_propose_write_creates_parents(self, ws):
        w = ws.propose_write("a/b/c.txt", "x")
        Workspace.apply_write(w)
        assert (ws.root / "a" / "b" / "c.txt").exists()

    def test_propose_edit_unique(self, ws):
        w = ws.propose_edit("src/app.py", "return 42", "return 43")
        assert "return 43" in w.new_content and "return 42" in w.old_content

    def test_edit_missing_string(self, ws):
        with pytest.raises(ToolError):
            ws.propose_edit("src/app.py", "nope", "x")

    def test_edit_ambiguous_requires_replace_all(self, ws):
        (ws.root / "dup.txt").write_text("a\na\n")
        with pytest.raises(ToolError):
            ws.propose_edit("dup.txt", "a", "b")
        w = ws.propose_edit("dup.txt", "a", "b", replace_all=True)
        assert w.new_content == "b\nb\n"

    def test_edit_identical_strings_rejected(self, ws):
        with pytest.raises(ToolError):
            ws.propose_edit("src/app.py", "return 42", "return 42")


class TestRunCommand:
    def test_captures_output_and_exit_code(self, ws):
        out = ws.run_command("echo hi && exit 3")
        assert "hi" in out and "exit code 3" in out

    def test_runs_in_workspace_root(self, ws):
        out = ws.run_command("pwd")
        assert str(ws.root) in out

    @pytest.mark.skipif(sys.platform == "win32", reason="process groups")
    def test_timeout_kills_process_group(self, ws):
        start = time.time()
        out = ws.run_command("sleep 30 & sleep 30", timeout=1)
        assert "timed out" in out
        assert time.time() - start < 10
