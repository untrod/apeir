"""State APIs must retain the configured project before its state exists."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from nous_runtime.api import routes
from nous_runtime.agent.models import AgentIdentity, AgentManifest
from nous_runtime.agent.registry import AgentRegistry
from nous_runtime.context.builder import BuildRequest, ContextBuilder
from nous_runtime.context.exceptions import ContextStoreError
from nous_runtime.context.models import ContextSnapshot
from nous_runtime.context.snapshot import create_snapshot
from nous_runtime.context.store import ContextStore
from nous_runtime.evaluation.exceptions import EvaluationError
from nous_runtime.evaluation.history import EvaluationHistory
from nous_runtime.evaluation.models import EvaluationRecord
from nous_runtime.experience.exceptions import ExperienceStoreError
from nous_runtime.experience.models import ExperienceRecord
from nous_runtime.experience.store import ExperienceStore
from nous_runtime.project.workspace import find_workspace


def _seed(state: Path, label: str) -> None:
    ContextStore(state).save(
        ContextSnapshot(id=f"snapshot-{label}", metadata={"intent": label})
    )
    assert EvaluationHistory(state).save(
        EvaluationRecord(id=f"evaluation-{label}", target_id=label)
    )
    assert ExperienceStore(state).save(
        ExperienceRecord(
            id=f"experience-{label}",
            task_type=label,
            task_summary="general task",
            action=label,
            success=True,
            lessons=(label,),
        )
    )


@pytest.fixture
def selected_workspace(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    _seed(outside / ".nous", "outside")
    selected = tmp_path / "selected"
    selected.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(selected))
    return selected, outside


READ_HANDLERS = (
    (routes.handle_context_history, "CONTEXT_HISTORY_ERROR"),
    (routes.handle_context_timeline, "CONTEXT_TIMELINE_ERROR"),
    (routes.handle_evaluation_history, "EVAL_HISTORY_ERROR"),
    (routes.handle_experience_list, "EXP_LIST_ERROR"),
    (routes.handle_experience_search, "EXP_SEARCH_ERROR"),
    (routes.handle_experience_recommend, "EXP_RECOMMEND_ERROR"),
    (routes.handle_phase5_experience_stats, "EXP_STATS_ERROR"),
)


@pytest.mark.parametrize("handler,error_code", READ_HANDLERS)
def test_empty_selected_state_never_reads_cwd_records(
    selected_workspace, handler, error_code
):
    selected, outside = selected_workspace
    before = {path.name: path.read_bytes() for path in (outside / ".nous").iterdir()}
    result = handler()
    assert result["ok"] is True, result
    if handler is routes.handle_phase5_experience_stats:
        assert result["data"]["total_experiences"] == 0
    else:
        assert result["data"] == []
    _seed(selected / ".nous", "selected")
    result = handler()
    assert result["ok"] is True, result
    assert "selected" in str(result["data"])
    assert "outside" not in str(result["data"])
    assert before == {
        path.name: path.read_bytes() for path in (outside / ".nous").iterdir()
    }


def test_snapshot_creation_and_restore_stay_in_selected_state(selected_workspace):
    selected, outside = selected_workspace
    result = routes.handle_context_snapshot({"intent": "selected-checkpoint"})
    assert result["ok"] is True, result
    snapshot_id = result["data"]["id"]
    assert ContextStore(selected / ".nous").get(snapshot_id) is not None
    assert ContextStore(outside / ".nous").get(snapshot_id) is None
    result = routes.handle_context_restore({"snapshot_id": "snapshot-outside"})
    assert result["ok"] is True
    assert result["data"]["success"] is False
    assert ContextStore(outside / ".nous").get("snapshot-outside").status == "active"


@pytest.mark.parametrize(
    "kind", ["file", "missing", "nul", "linked-state", "state-file"]
)
@pytest.mark.parametrize("handler,error_code", READ_HANDLERS)
def test_invalid_selected_state_fails_closed(
    selected_workspace, monkeypatch, kind, handler, error_code
):
    selected, outside = selected_workspace
    root = selected
    if kind == "file":
        root = selected / "file"
        root.write_text("not a root", encoding="utf-8")
    elif kind == "missing":
        root = selected / "missing"
    elif kind == "nul":
        root = "bad\0root"
    elif kind == "linked-state":
        (selected / ".nous").symlink_to(outside / ".nous", target_is_directory=True)
    elif kind == "state-file":
        (selected / ".nous").write_text("not state", encoding="utf-8")
    if kind == "nul":
        # The OS rejects NUL environment values; inject a malformed resolver
        # input without attempting to install it in the process environment.
        monkeypatch.setattr(
            "nous_runtime.project.workspace._os",
            SimpleNamespace(environ={"NOUS_WORKSPACE_ROOT": str(root)}),
        )
    else:
        monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(root))
    before = {path.name: path.read_bytes() for path in (outside / ".nous").iterdir()}
    result = handler()
    assert result["ok"] is False, result
    assert result["error"]["code"] == error_code
    assert "outside" not in str(result)
    assert before == {
        path.name: path.read_bytes() for path in (outside / ".nous").iterdir()
    }


@pytest.mark.parametrize("handler,error_code", READ_HANDLERS)
def test_resolution_failure_keeps_existing_handler_error(
    selected_workspace, monkeypatch, handler, error_code
):
    def fail(*args, **kwargs):
        raise OSError("workspace resolution unavailable")

    monkeypatch.setattr("nous_runtime.project.workspace.find_workspace", fail)
    result = handler()
    assert result["ok"] is False, result
    assert result["error"]["code"] == error_code
    assert "outside" not in str(result)


def test_default_builder_binds_agent_reader_before_state_exists(selected_workspace):
    selected, outside = selected_workspace
    AgentRegistry(outside / ".nous").register(
        AgentManifest(AgentIdentity("agent.outside", "outside"))
    )
    builder = ContextBuilder()
    assert builder.build_context(BuildRequest(sources=("agent",))).items == ()
    AgentRegistry(selected / ".nous").register(
        AgentManifest(AgentIdentity("agent.selected", "selected"))
    )
    items = builder.build_context(BuildRequest(sources=("agent",))).items
    assert {item.source_id for item in items} == {"agent.selected"}


def test_default_builder_resolution_error_is_not_empty_context(
    selected_workspace, monkeypatch
):
    def fail(*args, **kwargs):
        raise OSError("workspace resolution unavailable")

    monkeypatch.setattr("nous_runtime.project.workspace.find_workspace", fail)
    with pytest.raises(OSError, match="workspace resolution unavailable"):
        ContextBuilder()


def test_initialized_discovery_default_is_compatible(selected_workspace, monkeypatch):
    selected, outside = selected_workspace
    assert find_workspace() is None
    assert find_workspace(allow_uninitialized=True) == selected / ".nous"
    assert not (selected / ".nous").exists()
    assert find_workspace(outside) == outside / ".nous"
    monkeypatch.delenv("NOUS_WORKSPACE_ROOT")
    nested = outside / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert find_workspace() == outside / ".nous"
    assert find_workspace(allow_uninitialized=True) == outside / ".nous"
    assert routes.handle_context_history()["data"][0]["id"] == "snapshot-outside"
    assert routes.handle_evaluation_history()["data"][0]["id"] == "evaluation-outside"
    assert routes.handle_experience_list()["data"][0]["id"] == "experience-outside"


@pytest.mark.parametrize(
    "store_type,record",
    [
        (ContextStore, ContextSnapshot(id="direct-selected")),
        (
            EvaluationHistory,
            EvaluationRecord(id="direct-selected", target_id="selected"),
        ),
        (ExperienceStore, ExperienceRecord(id="direct-selected", action="selected")),
    ],
)
def test_default_store_save_reload_and_explicit_path_compatibility(
    selected_workspace, store_type, record
):
    selected, outside = selected_workspace
    before = {path.name: path.read_bytes() for path in (outside / ".nous").iterdir()}
    store = store_type()
    assert Path(store.db_path).parent == selected / ".nous"
    assert store.list() == []
    assert store.save(record)
    assert store_type().get(record.id).id == record.id
    assert before == {
        path.name: path.read_bytes() for path in (outside / ".nous").iterdir()
    }
    assert store_type(outside / ".nous").get(record.id) is None


def test_default_snapshot_reads_and_persists_same_selected_project(selected_workspace):
    selected, outside = selected_workspace
    AgentRegistry(outside / ".nous").register(
        AgentManifest(AgentIdentity("agent.outside", "outside"))
    )
    snapshot = create_snapshot(intent="direct-checkpoint")
    assert not any(item.source_id == "agent.outside" for item in snapshot.items)
    assert ContextStore(selected / ".nous").get(snapshot.id) is not None
    assert ContextStore(outside / ".nous").get(snapshot.id) is None
    assert ContextStore().get(snapshot.id).metadata["intent"] == "direct-checkpoint"


@pytest.mark.parametrize(
    "store_type", [ContextStore, EvaluationHistory, ExperienceStore]
)
@pytest.mark.parametrize(
    "kind",
    ["file", "missing", "linked-state", "state-file", "resolver-error", "unresolved"],
)
def test_default_store_invalid_selection_never_opens_cwd_state(
    selected_workspace, monkeypatch, store_type, kind
):
    selected, outside = selected_workspace
    if kind == "file":
        selected.rmdir()
        selected.write_text("not a project", encoding="utf-8")
    elif kind == "missing":
        selected.rmdir()
    elif kind == "linked-state":
        (selected / ".nous").symlink_to(outside / ".nous", target_is_directory=True)
    elif kind == "state-file":
        (selected / ".nous").write_text("not state", encoding="utf-8")
    elif kind == "resolver-error":

        def fail(*args, **kwargs):
            raise OSError("workspace resolution unavailable")

        monkeypatch.setattr("nous_runtime.project.workspace.find_workspace", fail)
    elif kind == "unresolved":
        monkeypatch.setattr(
            "nous_runtime.project.workspace.find_workspace", lambda **kwargs: None
        )
    before = {path.name: path.read_bytes() for path in (outside / ".nous").iterdir()}
    with pytest.raises((OSError, ValueError)):
        store_type()
    assert before == {
        path.name: path.read_bytes() for path in (outside / ".nous").iterdir()
    }


@pytest.mark.parametrize(
    "store_type", [ContextStore, EvaluationHistory, ExperienceStore]
)
def test_unconfigured_default_stores_keep_cwd_paths(
    selected_workspace, monkeypatch, store_type
):
    _, outside = selected_workspace
    monkeypatch.delenv("NOUS_WORKSPACE_ROOT")
    nested = outside / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    assert Path(store_type().db_path).parent == nested / ".nous"


PRIVATE_STATE_ERRORS = (
    ContextStoreError,
    EvaluationError,
    ExperienceStoreError,
    PermissionError,
)


PRIVATE_STORES = (
    (ContextStore, ContextSnapshot(id="saved-selected"), "context.db"),
    (EvaluationHistory, EvaluationRecord(id="saved-selected"), "evaluation.db"),
    (
        ExperienceStore,
        ExperienceRecord(id="saved-selected", task_type="coding", action="test"),
        "experience.db",
    ),
)


@pytest.mark.parametrize("store_type,record,name", PRIVATE_STORES)
@pytest.mark.parametrize(
    "kind", ["linked", "broken-linked", "hard-linked", "directory"]
)
def test_private_database_constructor_rejects_nonregular_files(
    selected_workspace, store_type, record, name, kind
):
    selected, outside = selected_workspace
    state = selected / ".nous"
    state.mkdir()
    path = state / name
    if kind == "directory":
        path.mkdir()
    else:
        target = outside / ".nous" / name
        if kind == "broken-linked":
            target = outside / ".nous" / "missing.db"
        if kind == "hard-linked":
            path.hardlink_to(target)
        else:
            path.symlink_to(target)
    before = (outside / ".nous" / name).read_bytes()
    with pytest.raises(PRIVATE_STATE_ERRORS):
        store_type()
    assert before == (outside / ".nous" / name).read_bytes()


@pytest.mark.parametrize("store_type,record,name", PRIVATE_STORES)
@pytest.mark.parametrize("action", ["read", "write", "restart"])
def test_private_database_replacement_cannot_cross_workspace(
    selected_workspace, store_type, record, name, action
):
    selected, outside = selected_workspace
    store = store_type()
    assert store.save(record) is True
    path = Path(store.db_path)
    path.unlink()
    path.symlink_to(outside / ".nous" / name)
    before = (outside / ".nous" / name).read_bytes()
    if action == "write":
        try:
            assert store.save(record) is False
        except PRIVATE_STATE_ERRORS:
            pass
    else:
        with pytest.raises(PRIVATE_STATE_ERRORS):
            if action == "restart":
                store_type()
            else:
                store.list()
    assert before == (outside / ".nous" / name).read_bytes()
    assert not any(r.id == record.id for r in store_type(outside / ".nous").list())


@pytest.mark.parametrize("handler,error_code", READ_HANDLERS)
def test_linked_private_database_preserves_api_error(
    selected_workspace, handler, error_code
):
    selected, outside = selected_workspace
    state = selected / ".nous"
    state.mkdir()
    for name in ("context.db", "evaluation.db", "experience.db"):
        (state / name).symlink_to(outside / ".nous" / name)
    result = handler()
    assert result["ok"] is False, result
    assert result["error"]["code"] == error_code
    assert "outside" not in str(result)


def test_corrupt_evaluation_is_not_successful_empty_history(selected_workspace):
    selected, outside = selected_workspace
    state = selected / ".nous"
    state.mkdir()
    (state / "evaluation.db").write_bytes(b"owned fake invalid SQLite")
    result = routes.handle_evaluation_history()
    assert result["ok"] is False, result
    assert result["error"]["code"] == "EVAL_HISTORY_ERROR"


@pytest.mark.parametrize(
    "store_type,table",
    [(EvaluationHistory, "evaluation_records"), (ExperienceStore, "experiences")],
)
@pytest.mark.parametrize("action", ["list", "stats"])
def test_private_history_read_error_is_not_empty_data(
    tmp_path, store_type, table, action
):
    import sqlite3

    store = store_type(tmp_path / ".nous")
    with sqlite3.connect(store.db_path) as db:
        db.execute(f"DROP TABLE {table}")
    with pytest.raises((EvaluationError, ExperienceStoreError)):
        getattr(store, action)()


@pytest.mark.parametrize("store_type,record,name", PRIVATE_STORES)
def test_private_database_replaced_parent_is_rejected(
    selected_workspace, store_type, record, name
):
    selected, outside = selected_workspace
    store = store_type()
    state = selected / ".nous"
    state.rename(selected / "original-state")
    state.symlink_to(outside / ".nous", target_is_directory=True)
    with pytest.raises(PRIVATE_STATE_ERRORS):
        store.list()


@pytest.mark.parametrize("store_type,record,name", PRIVATE_STORES)
@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_private_database_linked_sidecar_is_rejected(
    selected_workspace, store_type, record, name, suffix
):
    selected, outside = selected_workspace
    store = store_type()
    target = outside / "owned-fake-sidecar"
    target.write_bytes(b"owned fake unchanged sidecar")
    sidecar = Path(store.db_path + suffix)
    sidecar.unlink(missing_ok=True)
    sidecar.symlink_to(target)
    with pytest.raises(PRIVATE_STATE_ERRORS):
        store.list()
    assert target.read_bytes() == b"owned fake unchanged sidecar"


@pytest.mark.parametrize("store_type,record,name", PRIVATE_STORES)
@pytest.mark.parametrize("suffix", ["#chosen", "?chosen", "%23chosen", " space-π"])
def test_readonly_database_uri_keeps_exact_selected_file(
    selected_workspace, monkeypatch, store_type, record, name, suffix
):
    import os
    import shutil

    if os.name == "nt" and "?" in suffix:
        pytest.skip("Question marks are not legal Windows filename characters")
    selected, outside = selected_workspace
    prefix = selected / f"shadow-{name}"
    shutil.copyfile(outside / ".nous" / name, prefix)
    root = selected / f"{prefix.name}{suffix}"
    root.mkdir()
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(root))
    store = store_type()
    before = prefix.read_bytes()
    assert store.list() == []
    assert store.save(record) is True
    assert [item.id for item in store.list()] == [record.id]
    assert store.get(record.id).id == record.id
    handler = {
        "context.db": routes.handle_context_history,
        "evaluation.db": routes.handle_evaluation_history,
        "experience.db": routes.handle_experience_list,
    }[name]
    result = handler()
    assert result["ok"] is True, result
    assert [item["id"] for item in result["data"]] == [record.id]
    assert "outside" not in str(result)
    assert before == prefix.read_bytes()
