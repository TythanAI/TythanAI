import os
import sys

import pytest

from tythan.checkpoints import CheckpointStore


class TestCheckpoints:
    def test_undo_restores_previous_content(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("before")
        store = CheckpointStore()
        store.begin_turn("edit a")
        store.record(f)
        f.write_text("after")
        store.commit_turn()
        restored, problems = store.undo_last()
        assert f.read_text() == "before"
        assert str(f) in restored and problems == []

    def test_undo_deletes_created_file(self, tmp_path):
        f = tmp_path / "new.txt"
        store = CheckpointStore()
        store.begin_turn("create")
        store.record(f)
        f.write_text("created")
        store.commit_turn()
        store.undo_last()
        assert not f.exists()

    def test_undo_with_nothing_recorded(self):
        store = CheckpointStore()
        restored, problems = store.undo_last()
        assert restored == [] and problems == ["nothing to undo"]

    def test_empty_turn_not_kept(self, tmp_path):
        store = CheckpointStore()
        store.begin_turn("noop")
        store.commit_turn()
        assert store.list() == []

    def test_non_utf8_skipped(self, tmp_path):
        f = tmp_path / "bin.dat"
        f.write_bytes(b"\xff\xfe\x00binary")
        store = CheckpointStore()
        store.begin_turn("touch binary")
        store.record(f)
        f.write_bytes(b"changed")
        store.commit_turn()
        restored, problems = store.undo_last()
        assert restored == []
        assert any("not valid UTF-8" in p for p in problems)
        assert f.read_bytes() == b"changed"  # never "restored" corrupt

    def test_oversize_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tythan.checkpoints.MAX_CHECKPOINT_FILE_BYTES", 10)
        f = tmp_path / "big.txt"
        f.write_text("x" * 100)
        store = CheckpointStore()
        store.begin_turn("big")
        store.record(f)
        store.commit_turn()
        _, problems = store.undo_last()
        assert any("over" in p for p in problems)

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
    def test_symlink_introduced_after_checkpoint_not_followed(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("before")
        target = tmp_path / "target.txt"
        target.write_text("victim")
        store = CheckpointStore()
        store.begin_turn("edit")
        store.record(f)
        f.unlink()
        os.symlink(target, f)
        store.commit_turn()
        restored, problems = store.undo_last()
        assert target.read_text() == "victim"
        assert any("symlink" in p for p in problems)

    def test_disabled_store_records_nothing(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        store = CheckpointStore(enabled=False)
        store.begin_turn("t")
        store.record(f)
        store.commit_turn()
        assert store.list() == []

    def test_retention_prunes_old(self, tmp_path, monkeypatch):
        monkeypatch.setattr("tythan.checkpoints.MAX_CHECKPOINTS", 2)
        store = CheckpointStore()
        f = tmp_path / "a.txt"
        f.write_text("0")
        for i in range(4):
            store.begin_turn(f"turn{i}")
            store.record(f)
            f.write_text(str(i + 1))
            store.commit_turn()
        assert len(store.list()) == 2
