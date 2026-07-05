"""CheckpointStore tests. Every store here is pointed at tmp_path via
storage_dir= so nothing ever touches the real ~/.minicursor directory."""

from minicursor.checkpoints import CheckpointStore, FileChange


def make_store(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store_dir = tmp_path / "checkpoint_storage"
    return CheckpointStore(workspace, storage_dir=store_dir), workspace, store_dir


def test_no_directory_created_until_a_change_is_committed(tmp_path):
    store, workspace, store_dir = make_store(tmp_path)
    assert not store_dir.exists()
    store.begin_turn("did nothing")
    assert store.commit_turn() is None
    assert not store_dir.exists()


def test_record_and_commit_creates_checkpoint(tmp_path):
    store, workspace, store_dir = make_store(tmp_path)
    target = workspace / "a.txt"
    target.write_text("v1")

    store.begin_turn("edit a.txt")
    store.record_before(target)
    target.write_text("v2")
    cp = store.commit_turn()

    assert cp is not None
    assert cp.label == "edit a.txt"
    assert len(cp.changes) == 1
    assert cp.changes[0].path == str(target)
    assert cp.changes[0].existed_before is True
    assert cp.changes[0].before_content == "v1"
    assert store_dir.exists()


def test_record_before_new_file_marks_existed_before_false(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "new.txt"

    store.begin_turn("create new.txt")
    store.record_before(target)  # file doesn't exist yet
    target.write_text("content")
    cp = store.commit_turn()

    assert cp.changes[0].existed_before is False
    assert cp.changes[0].before_content is None


def test_record_before_keeps_first_state_when_touched_twice(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "a.txt"
    target.write_text("v1")

    store.begin_turn("double edit")
    store.record_before(target)
    target.write_text("v2")
    store.record_before(target)  # same path again — should be ignored
    target.write_text("v3")
    cp = store.commit_turn()

    assert len(cp.changes) == 1
    assert cp.changes[0].before_content == "v1"


def test_record_before_without_begin_turn_is_a_noop(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "a.txt"
    target.write_text("v1")
    store.record_before(target)  # no begin_turn() called
    assert store.commit_turn() is None


def test_large_file_is_skipped_but_noted(tmp_path, monkeypatch):
    import minicursor.checkpoints as checkpoints_mod

    monkeypatch.setattr(checkpoints_mod, "MAX_CHECKPOINT_FILE_BYTES", 10)
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "big.txt"
    target.write_text("x" * 100)

    store.begin_turn("touch big file")
    store.record_before(target)
    cp_none = store.commit_turn()
    # nothing else changed, and the big file was skipped rather than recorded
    assert cp_none is None


def test_large_file_skip_reported_alongside_other_changes(tmp_path, monkeypatch):
    import minicursor.checkpoints as checkpoints_mod

    monkeypatch.setattr(checkpoints_mod, "MAX_CHECKPOINT_FILE_BYTES", 10)
    store, workspace, _ = make_store(tmp_path)
    big = workspace / "big.txt"
    big.write_text("x" * 100)
    small = workspace / "small.txt"
    small.write_text("v1")

    store.begin_turn("touch both")
    store.record_before(big)
    store.record_before(small)
    cp = store.commit_turn()

    assert len(cp.changes) == 1
    assert cp.changes[0].path == str(small)
    assert cp.skipped_large == [str(big)]


def test_undo_last_restores_modified_file(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "a.txt"
    target.write_text("v1")

    store.begin_turn("edit")
    store.record_before(target)
    target.write_text("v2")
    store.commit_turn()

    restored = store.undo_last()
    assert restored is not None
    assert target.read_text() == "v1"


def test_undo_last_deletes_file_created_this_turn(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "new.txt"

    store.begin_turn("create")
    store.record_before(target)
    target.write_text("content")
    store.commit_turn()

    store.undo_last()
    assert not target.exists()


def test_undo_last_on_empty_store_returns_none(tmp_path):
    store, _, _ = make_store(tmp_path)
    assert store.undo_last() is None


def test_undo_pops_one_checkpoint_at_a_time(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "a.txt"
    target.write_text("v1")

    store.begin_turn("first edit")
    store.record_before(target)
    target.write_text("v2")
    store.commit_turn()

    store.begin_turn("second edit")
    store.record_before(target)
    target.write_text("v3")
    store.commit_turn()

    assert target.read_text() == "v3"
    store.undo_last()
    assert target.read_text() == "v2"
    store.undo_last()
    assert target.read_text() == "v1"
    assert store.undo_last() is None  # nothing left


def test_undo_refuses_paths_outside_its_own_workspace(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("safe")

    # Simulate a corrupted/tampered checkpoint file pointing outside the workspace.
    store.begin_turn("malicious")
    store._current.changes.append(
        FileChange(path=str(outside), existed_before=True, before_content="HACKED")
    )
    store.commit_turn()

    store.undo_last()
    assert outside.read_text() == "safe"  # untouched


def test_list_returns_most_recent_first(tmp_path):
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "a.txt"
    target.write_text("v1")

    for i in range(3):
        store.begin_turn(f"edit {i}")
        store.record_before(target)
        target.write_text(f"v{i + 2}")
        store.commit_turn()

    labels = [cp.label for cp in store.list()]
    assert labels == ["edit 2", "edit 1", "edit 0"]


def test_retention_prunes_oldest_checkpoints(tmp_path, monkeypatch):
    import minicursor.checkpoints as checkpoints_mod

    monkeypatch.setattr(checkpoints_mod, "MAX_CHECKPOINTS_PER_WORKSPACE", 3)
    store, workspace, _ = make_store(tmp_path)
    target = workspace / "a.txt"
    target.write_text("v0")

    for i in range(5):
        store.begin_turn(f"edit {i}")
        store.record_before(target)
        target.write_text(f"v{i + 1}")
        store.commit_turn()

    assert len(store._files()) == 3
    labels = [cp.label for cp in store.list(limit=10)]
    assert labels == ["edit 4", "edit 3", "edit 2"]


def test_persists_across_store_instances(tmp_path):
    """/undo must survive restarting mini-cursor — checkpoints are files on disk."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store_dir = tmp_path / "checkpoint_storage"

    store1 = CheckpointStore(workspace, storage_dir=store_dir)
    target = workspace / "a.txt"
    target.write_text("v1")
    store1.begin_turn("edit")
    store1.record_before(target)
    target.write_text("v2")
    store1.commit_turn()

    # Fresh instance, same storage_dir — simulates a new process starting up.
    store2 = CheckpointStore(workspace, storage_dir=store_dir)
    restored = store2.undo_last()
    assert restored is not None
    assert target.read_text() == "v1"
