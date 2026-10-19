"""Selected saved files reuse live authority and reach whole Context items."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from nous_runtime.context.builder import ContextBudgetError, ContextBuilder
from nous_runtime.context.models import ContextItem
from nous_runtime.context.selected_input import (
    MAX_FILE_BYTES,
    ProviderRecipient,
    SelectedInputError,
    SelectedWorkspaceInput,
    WorkspaceFileReference,
)
from nous_runtime.context.types import BuildRequest
from nous_runtime.governance.permission import PermissionRule
from nous_runtime.workspace.isolation import workspace_read_backend_available
from tests.context.test_guard_admission import admitted_context as context_fixture

base_admission = context_fixture


@pytest.fixture
def admitted_context(base_admission):
    from nous_runtime.governance.store import GovernanceStore

    guard, gate, actor = base_admission
    gate.store = GovernanceStore(Path(guard._workspace) / ".nous")
    return guard, gate, actor


RECIPIENT_A = ProviderRecipient(
    "fake-provider-a", "mock://provider-a/chat", "fake-adapter"
)
RECIPIENT_B = ProviderRecipient(
    "fake-provider-b", "mock://provider-b/chat", "fake-adapter"
)


requires_safe_read = pytest.mark.skipif(
    os.name != "nt" and not workspace_read_backend_available(),
    reason="Host lacks a safe workspace reader; selected source delivery is BLOCKED",
)


def reference(root, path="notes.txt", content=b"exact saved middle constraint\n"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return WorkspaceFileReference(path, hashlib.sha256(content).hexdigest())


def reader(admitted_context, references, *, read=True, transfer=False):
    guard, gate, actor = admitted_context
    if read:
        gate.permission_engine.add(
            PermissionRule(actor.subject_id, "workspace.read", "*")
        )
    value = SelectedWorkspaceInput(
        guard._workspace,
        references,
        authorization_context=actor,
        purpose="inspect selected saved inputs",
        work_id="original-runtime-request-1",
        gate=gate,
    )
    if transfer:
        gate.permission_engine.add(
            PermissionRule(
                actor.subject_id,
                "context.transfer",
                value.transfer_resource(RECIPIENT_A),
            )
        )
    return value


def build(value, **metadata):
    return ContextBuilder(providers=[value]).build_context(
        BuildRequest(intent="inspect", sources=("project",), metadata=metadata)
    )


@requires_safe_read
def test_saved_file_is_whole_context_with_private_content_free_audit(admitted_context):
    guard, gate, _ = admitted_context
    ref = reference(Path(guard._workspace))
    value = reader(admitted_context, [ref])
    snapshot = build(value)
    assert snapshot.item_count == 1
    item = snapshot.items[0]
    assert item.content == "exact saved middle constraint\n"
    assert item.source_version == ref.sha256
    assert item.metadata["selected_input_binding_sha256"] == value.binding_digest(ref)
    assert value.provenance()[0]["status"] == "read"
    assert value.provenance()[0]["was_read"] is True
    serialized = json.dumps(guard.get_audit_log())
    assert "middle constraint" not in serialized
    assert "notes.txt" not in serialized


def test_reference_intent_cannot_grant_workspace_read(admitted_context, monkeypatch):
    guard, _, _ = admitted_context

    ref = reference(Path(guard._workspace))
    value = reader(admitted_context, [ref], read=False)
    opened = []
    monkeypatch.setattr(value, "_read", lambda _: opened.append(True))
    with pytest.raises(SelectedInputError, match="workspace_read_denied"):
        value.collect()
    assert not opened
    assert value.provenance()[0]["status"] == "rejected"
    assert value.provenance()[0]["was_read"] is False


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/notes.txt",
        "../notes.txt",
        "a/../notes.txt",
        "a//notes.txt",
        "./notes.txt",
        "C:/notes.txt",
        "https://host/notes.txt",
        "a\\notes.txt",
        ".nous/notes.txt",
        ".git/notes.txt",
        "private/notes.txt",
        "secrets.txt",
        ".env.json",
        "file.bin",
        "notes.txt\x00",
    ],
)
def test_unsafe_source_selection_refuses_without_read(path):
    with pytest.raises(SelectedInputError):
        WorkspaceFileReference(path, "0" * 64)


@pytest.mark.parametrize("digest", ["", "ABC" * 20, "sha256:" + "a" * 64, 123])
def test_exact_digest_required(digest):
    with pytest.raises(SelectedInputError, match="source_version"):
        WorkspaceFileReference("notes.txt", digest)


def test_unknown_reference_fields_cannot_supply_content_or_permission():
    with pytest.raises(SelectedInputError, match="reference_fields"):
        WorkspaceFileReference.from_mapping(
            {
                "path": "notes.txt",
                "sha256": "0" * 64,
                "permission": "read",
                "content": "untrusted",
            }
        )


def test_absent_permission_engine_and_wrong_workspace_fail_closed(admitted_context):
    guard, gate, actor = admitted_context

    ref = reference(Path(guard._workspace))
    gate.permission_engine = None
    with pytest.raises(SelectedInputError, match="configured_workspace_authority"):
        reader(admitted_context, [ref], read=False)


@pytest.mark.parametrize(
    "content,reason,was_read",
    [
        (b"\x00binary", "binary_source_refused", True),
        (b"bad\xffutf8", "source_unavailable_or_invalid", True),
        (b'{"password":"FAKE_PRIVATE_PASSWORD"}', "secret_source_refused", True),
        (b"password=FAKE_TEST_SECRET_VALUE", "secret_source_refused", True),
        (b"x" * (MAX_FILE_BYTES + 1), "source_byte_bound_or_type", False),
    ],
    ids=["binary", "invalid-utf8", "json-secret", "text-secret", "over-byte-bound"],
)
@requires_safe_read
def test_binary_secret_and_byte_bounds_refused(
    admitted_context, content, reason, was_read
):

    guard, _, _ = admitted_context
    value = reader(
        admitted_context, [reference(Path(guard._workspace), content=content)]
    )
    with pytest.raises(SelectedInputError, match=reason):
        value.collect()
    assert value.provenance()[0]["status"] == "rejected"
    assert value.provenance()[0]["was_read"] is was_read


@requires_safe_read
def test_registered_secret_refused(admitted_context):
    from nous_runtime.core.redaction import register_sensitive_value

    guard, _, _ = admitted_context
    marker = "FAKE_SELECTED_INPUT_TEST_SECRET_ONLY"
    register_sensitive_value(marker)
    value = reader(
        admitted_context, [reference(Path(guard._workspace), content=marker.encode())]
    )
    with pytest.raises(SelectedInputError, match="secret_source_refused"):
        value.collect()


def test_symlink_inside_workspace_refused(admitted_context):

    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    ref = reference(root)
    try:
        (root / "alias.txt").symlink_to(root / ref.path)
    except OSError:
        pytest.skip("host cannot create symlinks")
    value = reader(admitted_context, [WorkspaceFileReference("alias.txt", ref.sha256)])
    with pytest.raises(SelectedInputError):
        value.collect()


@requires_safe_read
@pytest.mark.parametrize("origin", [".nous", ".git", "outside"])
def test_hard_link_cannot_alias_protected_or_external_input(admitted_context, origin):
    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    source = (
        root.parent / "outside-selected-source.txt"
        if origin == "outside"
        else root / origin / "private-selected-source.txt"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    content = b"owned private boundary fixture 42\n"
    source.write_bytes(content)
    alias = root / "review-notes.txt"
    os.link(source, alias)
    assert alias.stat().st_nlink == 2
    value = reader(
        admitted_context,
        [WorkspaceFileReference(alias.name, hashlib.sha256(content).hexdigest())],
    )
    with pytest.raises(SelectedInputError, match="source_link_refused"):
        value.collect()
    assert value.provenance()[0]["status"] == "rejected"
    assert value.provenance()[0]["was_read"] is False


@requires_safe_read
@pytest.mark.skipif(
    os.name == "nt", reason="Windows uses the actual pre-open link fault"
)
def test_link_created_during_read_cannot_publish_context(admitted_context, monkeypatch):
    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    ref = reference(root)
    value = reader(admitted_context, [ref])
    actual_read = os.read
    linked = False

    def read_and_link(descriptor, size):
        nonlocal linked
        data = actual_read(descriptor, size)
        if data and not linked:
            os.link(root / ref.path, root / "late-alias.txt")
            linked = True
        return data

    monkeypatch.setattr(os, "read", read_and_link)
    with pytest.raises(SelectedInputError, match="source_link_refused"):
        value.collect()
    assert linked
    assert value.provenance()[0]["status"] == "rejected"
    assert value.provenance()[0]["was_read"] is True


def test_unsupported_descriptor_host_denies(admitted_context, monkeypatch):
    from nous_runtime.workspace import isolation

    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))])
    if os.name == "nt":

        def unavailable():
            raise isolation.WorkspaceReadUnavailableError("owned missing native API")

        monkeypatch.setattr(isolation, "_windows_read_api", unavailable)
    else:
        monkeypatch.setattr(isolation, "_POSIX_SAFE_OPEN_AVAILABLE", False)
    assert workspace_read_backend_available() is False
    with pytest.raises(SelectedInputError, match="safe_source_read_unavailable"):
        value.collect()
    assert value.provenance()[0]["was_read"] is False
    assert value.provenance()[0]["status"] == "rejected"


@requires_safe_read
def test_provider_recipient_scope_distinct_from_read_permission(admitted_context):

    guard, _, _ = admitted_context
    ref = reference(Path(guard._workspace))
    value = reader(admitted_context, [ref], transfer=True)
    snapshot = build(value)
    value.authorize_transfer(snapshot, RECIPIENT_A)
    assert value.provenance()[0]["status"] == "transfer_admitted"
    with pytest.raises(SelectedInputError, match="provider_transfer_denied"):
        value.authorize_transfer(snapshot, RECIPIENT_B)


@requires_safe_read
def test_read_permission_never_implies_transfer(admitted_context):

    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))])
    snapshot = build(value)
    with pytest.raises(SelectedInputError, match="provider_transfer_denied"):
        value.authorize_transfer(snapshot, RECIPIENT_A)


@pytest.mark.parametrize("change", ["bytes", "permission", "profile"])
@requires_safe_read
def test_revalidation_before_next_provider_attempt(admitted_context, change):
    from nous_runtime.agent.registry import AgentRegistry

    guard, gate, actor = admitted_context
    root = Path(guard._workspace)
    ref = reference(root)
    value = reader(admitted_context, [ref], transfer=True)
    snapshot = build(value)
    value.authorize_transfer(snapshot, RECIPIENT_A)
    if change == "bytes":
        (root / ref.path).write_text("changed after first provider attempt")
    elif change == "permission":
        gate.permission_engine.add(
            PermissionRule(actor.subject_id, "workspace.read", "*", effect="deny")
        )
    else:
        registry = AgentRegistry(root)
        registry.remove(actor.subject_id)
    with pytest.raises(SelectedInputError):
        value.authorize_transfer(snapshot, RECIPIENT_A)


@requires_safe_read
def test_snapshot_content_and_binding_tamper_denies(admitted_context):

    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))], transfer=True)
    snapshot = build(value)
    with pytest.raises(SelectedInputError, match="selected_input_changed"):
        value.authorize_transfer(
            replace(snapshot, items=(replace(snapshot.items[0], content="altered"),)),
            RECIPIENT_A,
        )


@requires_safe_read
def test_budget_omission_never_reads_again_or_requests_transfer(
    admitted_context, monkeypatch
):

    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))])
    snapshot = build(value, max_input_tokens=1)
    assert snapshot.items == ()
    assert snapshot.metadata["truncation_explanation"][0]["included_characters"] == 0
    monkeypatch.setattr(
        value, "_read", lambda _: pytest.fail("omitted source was read again")
    )
    value.authorize_transfer(snapshot, RECIPIENT_A)
    assert value.provenance()[0]["status"] == "budget_limited"


@requires_safe_read
def test_selected_files_cannot_displace_mandatory_governance(admitted_context):

    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))])

    class Mandatory:
        source_type = "project"

        def collect(self, **_):
            return [
                ContextItem(
                    content="required objective entire tail",
                    source_type="project",
                    metadata={"context_class": "active_objective"},
                )
            ]

    snapshot = ContextBuilder(providers=[value, Mandatory()]).build_context(
        BuildRequest(max_items=1)
    )
    assert len(snapshot.items) == 1
    assert snapshot.items[0].content == "required objective entire tail"
    assert snapshot.metadata["truncation_explanation"][0]["included_characters"] == 0
    with pytest.raises(ContextBudgetError):
        ContextBuilder(providers=[value, Mandatory()]).build_context(
            BuildRequest(metadata={"max_input_tokens": 1})
        )


def test_failed_audit_prevents_read(admitted_context, monkeypatch):

    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))])
    monkeypatch.setattr(value._guard._store, "record_audit", lambda **_: False)
    monkeypatch.setattr(
        value, "_read", lambda _: pytest.fail("audit-denied source read")
    )
    with pytest.raises(SelectedInputError):
        value.collect()


@pytest.mark.parametrize(
    "field,value",
    [("endpoint", "mock://changed-endpoint/chat"), ("transport", "changed-transport")],
)
@requires_safe_read
def test_same_provider_alias_changed_endpoint_or_transport_denies(
    admitted_context, field, value
):
    guard, _, _ = admitted_context
    source = reader(
        admitted_context, [reference(Path(guard._workspace))], transfer=True
    )
    snapshot = build(source)
    source.authorize_transfer(snapshot, RECIPIENT_A)
    changed = replace(RECIPIENT_A, **{field: value})
    assert changed.provider_id == RECIPIENT_A.provider_id
    with pytest.raises(SelectedInputError, match="provider_transfer_denied"):
        source.authorize_transfer(snapshot, changed)


@pytest.mark.parametrize(
    "path",
    [
        "src/main.py",
        "app.ts",
        "view.tsx",
        "code.rs",
        "main.c",
        "config.toml",
        "config.yaml",
        "data.csv",
        "notes.log",
    ],
)
@requires_safe_read
def test_existing_code_and_text_suffixes_are_supported(admitted_context, path):
    guard, _, _ = admitted_context
    source = reader(admitted_context, [reference(Path(guard._workspace), path=path)])
    assert len(source.collect()) == 1


@pytest.mark.parametrize(
    "path,content",
    [
        ("data.json", b'{"secret":"FAKE_JSON_SECRET"}'),
        ("data.csv", b"password,value\nFAKE_CSV_SECRET,1\n"),
        ("config.toml", b'password = "test_only_fake_toml_secret"\n'),
    ],
)
@requires_safe_read
def test_structured_secret_fields_are_refused(admitted_context, path, content):
    guard, _, _ = admitted_context
    source = reader(
        admitted_context, [reference(Path(guard._workspace), path, content)]
    )
    with pytest.raises(SelectedInputError, match="secret_source_refused"):
        source.collect()


@requires_safe_read
def test_aggregate_bound_denies_before_reading_excess_bytes(
    admitted_context, monkeypatch
):
    guard, _, _ = admitted_context
    refs = [
        reference(Path(guard._workspace), f"file{index}.txt", b"x" * MAX_FILE_BYTES)
        for index in range(3)
    ]
    source = reader(admitted_context, refs)
    read_bytes = []
    original = os.read

    def record_read(descriptor, count):
        data = original(descriptor, count)
        read_bytes.append(len(data))
        return data

    monkeypatch.setattr(os, "read", record_read)
    with pytest.raises(SelectedInputError):
        source.collect()
    assert sum(read_bytes) == 2 * MAX_FILE_BYTES


@requires_safe_read
def test_revoke_during_read_prevents_context_delivery(admitted_context, monkeypatch):
    guard, gate, actor = admitted_context
    source = reader(admitted_context, [reference(Path(guard._workspace))])
    original = source._read

    def revoke(reference, **kwargs):
        data = original(reference, **kwargs)
        gate.permission_engine.add(
            PermissionRule(actor.subject_id, "workspace.read", "*", effect="deny")
        )
        return data

    monkeypatch.setattr(source, "_read", revoke)
    with pytest.raises(SelectedInputError, match="workspace_read_denied"):
        source.collect()
    assert source.provenance()[0]["was_read"] is True
    assert source.provenance()[0]["status"] == "rejected"


@requires_safe_read
def test_unexplained_omission_or_duplicate_source_denies(admitted_context):
    guard, _, _ = admitted_context
    source = reader(
        admitted_context, [reference(Path(guard._workspace))], transfer=True
    )
    snapshot = build(source)
    for changed in (
        replace(snapshot, items=()),
        replace(snapshot, items=snapshot.items * 2),
    ):
        with pytest.raises(SelectedInputError, match="selected_input_changed"):
            source.authorize_transfer(changed, RECIPIENT_A)


@requires_safe_read
def test_selected_source_enters_existing_model_request_and_estimate(admitted_context):
    from types import SimpleNamespace
    from nous_runtime.events import EventStream
    from nous_runtime.model_runtime.bridges import GatewayChatHandler
    from nous_runtime.model_runtime.facade import GatewayResponse
    from nous_runtime.context.explain import explain_model_input

    guard, _, _ = admitted_context
    source = reader(
        admitted_context, [reference(Path(guard._workspace))], transfer=True
    )
    snapshot = build(source)
    captured = []

    class FakeFacade:
        def try_invoke_sync(self, request):
            # This deterministic seam qualifies message construction only.
            # Root's Gateway hook must perform this for actual retry candidates.
            source.authorize_transfer(snapshot, RECIPIENT_A)
            captured.append(request.to_model_request())
            return GatewayResponse(request_id="fake-answer", content="Ready")

    result = GatewayChatHandler(FakeFacade(), checkpoint_root=guard._workspace)(
        SimpleNamespace(
            request_id="selected-request",
            user_input="Inspect",
            constraints={"agent_mode": "chat", "workspace_path": guard._workspace},
        ),
        {
            "workspace": guard._workspace,
            "context_snapshot": snapshot.to_dict(),
            "event_stream": EventStream(guard._workspace),
        },
    )
    assert result["ok"]
    assert len(captured) == 1
    request = captured[0]
    assert snapshot.items[0].content in request.messages[1]["content"]
    manifest = explain_model_input(request.messages, request.metadata["tools"], {})
    without = explain_model_input(
        (request.messages[0], *request.messages[2:]), request.metadata["tools"], {}
    )
    assert manifest["estimated_input_tokens"] > without["estimated_input_tokens"]
    assert "middle constraint" not in json.dumps(manifest)


@requires_safe_read
def test_exact_path_version_and_work_scope_reuses_permission_context(admitted_context):
    guard, gate, actor = admitted_context
    ref = reference(Path(guard._workspace))
    source = reader(admitted_context, [ref], read=False)
    workspace_resource = (
        "workspace:" + hashlib.sha256(guard._workspace.encode()).hexdigest()
    )
    gate.permission_engine.add(
        PermissionRule(
            actor.subject_id,
            "workspace.read",
            workspace_resource,
            context_equals={
                "relative_path": ref.path,
                "source_version": ref.sha256,
                "work_id": "original-runtime-request-1",
            },
        )
    )
    snapshot = build(source)
    assert snapshot.item_count == 1
    gate.permission_engine.add(
        PermissionRule(
            actor.subject_id,
            "context.transfer",
            source.transfer_resource(RECIPIENT_A),
            context_equals={
                "source_id": ref.source_id,
                "source_version": ref.sha256,
                "work_id": "original-runtime-request-1",
            },
        )
    )
    source.authorize_transfer(snapshot, RECIPIENT_A)
    source._work_id = "different-original-work"
    with pytest.raises(SelectedInputError, match="selected_input_changed"):
        source.authorize_transfer(snapshot, RECIPIENT_A)


@requires_safe_read
def test_source_specific_transfer_cannot_widen_to_second_file(admitted_context):
    guard, gate, actor = admitted_context
    refs = [
        reference(Path(guard._workspace), f"notes{index}.txt") for index in range(2)
    ]
    source = reader(admitted_context, refs)
    snapshot = build(source)
    gate.permission_engine.add(
        PermissionRule(
            actor.subject_id,
            "context.transfer",
            source.transfer_resource(RECIPIENT_A),
            context_equals={"source_id": refs[0].source_id},
        )
    )
    with pytest.raises(SelectedInputError, match="provider_transfer_denied"):
        source.authorize_transfer(snapshot, RECIPIENT_A)


def test_missing_native_api_cannot_fall_back_to_ordinary_read(
    admitted_context, monkeypatch
):
    from nous_runtime.workspace import isolation

    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))])

    def unavailable():
        raise isolation.WorkspaceReadUnavailableError("owned missing native API")

    monkeypatch.setattr(isolation, "_windows_read_api", unavailable)
    monkeypatch.setattr(
        isolation, "_workspace_read_descriptor", isolation._windows_read_descriptor
    )
    with pytest.raises(SelectedInputError, match="safe_source_read_unavailable"):
        value.collect()
    assert value.provenance()[0]["was_read"] is False
    assert value.provenance()[0]["status"] == "rejected"


@pytest.mark.parametrize(
    "missing",
    ["CreateFileW", "CloseHandle", "GetFileInformationByHandle", "open_osfhandle"],
)
def test_missing_native_symbol_is_explicitly_unavailable(monkeypatch, missing):
    import sys
    from types import SimpleNamespace
    from nous_runtime.workspace import isolation

    functions = {
        name: lambda *_, **__: None
        for name in ("CreateFileW", "CloseHandle", "GetFileInformationByHandle")
        if name != missing
    }
    kernel = SimpleNamespace(**functions)
    native = SimpleNamespace()
    if missing != "open_osfhandle":
        native.open_osfhandle = lambda *_, **__: None
    with monkeypatch.context() as patch:
        patch.setitem(
            sys.modules,
            "ctypes",
            SimpleNamespace(WinDLL=lambda *_, **__: kernel, wintypes=SimpleNamespace()),
        )
        patch.setitem(sys.modules, "msvcrt", native)
        patch.setattr(isolation, "os", SimpleNamespace(name="nt", O_BINARY=0x8000))
        with pytest.raises(isolation.WorkspaceReadUnavailableError):
            isolation._windows_read_api()
        assert isolation.workspace_read_backend_available() is False


@pytest.mark.parametrize(
    "canonical", [".ssh/notes.txt", "secrets/notes.txt", "source/credentials.txt"]
)
def test_canonical_location_reapplies_private_source_rules(
    admitted_context, monkeypatch, canonical
):
    from nous_runtime.context import selected_input

    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    value = reader(admitted_context, [reference(root)])
    monkeypatch.setattr(value._paths, "validate_path", lambda _: str(root / canonical))
    monkeypatch.setattr(
        selected_input,
        "read_workspace_bytes",
        lambda *_, **__: pytest.fail("Canonical private source reached byte reading"),
    )
    with pytest.raises(SelectedInputError, match="unsupported_or_private_source"):
        value.collect()
    assert value.provenance()[0]["was_read"] is False
    assert value.provenance()[0]["status"] == "rejected"


@pytest.mark.parametrize(
    "path",
    ["notes~1.txt", "source~1/notes.txt", "source./notes.txt", "source /notes.txt"],
)
def test_windows_reference_alias_spelling_is_refused_before_selection(
    path, monkeypatch
):
    from types import SimpleNamespace
    from nous_runtime.context import selected_input

    monkeypatch.setattr(selected_input, "os", SimpleNamespace(name="nt"))
    with pytest.raises(SelectedInputError, match="windows_source_alias_refused"):
        WorkspaceFileReference(path, "0" * 64)


@pytest.mark.skipif(os.name == "nt", reason="POSIX tilde filename compatibility")
@requires_safe_read
def test_posix_tilde_source_is_still_supported(admitted_context):
    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace), "notes~1.txt")])
    assert value.collect()[0].content == "exact saved middle constraint\n"


@pytest.mark.skipif(
    os.name != "nt", reason="Native Windows selected-file qualification"
)
def test_windows_reader_has_required_backend_apis():
    assert workspace_read_backend_available(), "Windows safe selected reads are BLOCKED"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows pre-open link fault")
def test_windows_link_created_before_open_cannot_publish_context(
    admitted_context, monkeypatch
):
    from contextlib import contextmanager
    from nous_runtime.workspace import isolation

    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    ref = reference(root)
    value = reader(admitted_context, [ref])
    original = isolation._workspace_read_descriptor
    linked = False

    @contextmanager
    def link_before_open(workspace, relative):
        nonlocal linked
        os.link(root / ref.path, root / "late-alias.txt")
        linked = True
        with original(workspace, relative) as descriptor:
            yield descriptor

    monkeypatch.setattr(isolation, "_workspace_read_descriptor", link_before_open)
    with pytest.raises(SelectedInputError, match="source_link_refused"):
        value.collect()
    assert linked
    assert value.provenance()[0]["was_read"] is False
    assert value.provenance()[0]["status"] == "rejected"
    assert value._items == ()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows held source handle")
def test_windows_held_file_blocks_write_and_later_change_denies_transfer(
    admitted_context, monkeypatch
):
    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    ref = reference(root)
    value = reader(admitted_context, [ref], transfer=True)
    original = os.read
    blocked = False

    def attempt_write_during_read(descriptor, size):
        nonlocal blocked
        data = original(descriptor, size)
        if data and not blocked:
            with pytest.raises(PermissionError):
                (root / ref.path).write_bytes(b"must not replace held source")
            blocked = True
        return data

    monkeypatch.setattr(os, "read", attempt_write_during_read)
    snapshot = build(value)
    assert blocked
    assert snapshot.items[0].content == "exact saved middle constraint\n"
    value.authorize_transfer(snapshot, RECIPIENT_A)
    (root / ref.path).write_bytes(b"changed after completed acquisition")
    with pytest.raises(SelectedInputError, match="source_version_changed"):
        value.authorize_transfer(snapshot, RECIPIENT_A)
    assert value.provenance()[0]["status"] == "rejected"


@pytest.mark.skipif(os.name != "nt", reason="Native Windows in-read link behavior")
def test_windows_mid_read_link_is_denied_or_caught_before_context_publication(
    admitted_context, monkeypatch
):
    from nous_runtime.context.models import ContextSnapshot

    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    ref = reference(root)
    target = root / ref.path
    alias = root / "late-alias.txt"
    original_content = target.read_bytes()
    value = reader(admitted_context, [ref])
    original = os.read
    outcome = None

    def attempt_link_during_read(descriptor, size):
        nonlocal outcome
        data = original(descriptor, size)
        if data and outcome is None:
            try:
                os.link(target, alias)
            except PermissionError:
                outcome = "system-denied"
            else:
                outcome = "created"
        return data

    monkeypatch.setattr(os, "read", attempt_link_during_read)
    try:
        items = value.collect()
    except SelectedInputError as error:
        assert outcome == "created"
        assert str(error) == "source_link_refused"
        assert alias.exists() and target.stat().st_nlink == 2
        assert value._items == ()
        assert value.provenance()[0]["status"] == "rejected"
    else:
        assert outcome == "system-denied"
        assert not alias.exists() and target.stat().st_nlink == 1
        assert target.read_bytes() == original_content
        assert items[0].content.encode() == original_content
        # Even a successful protected read supplies no Provider transfer grant.
        with pytest.raises(SelectedInputError, match="provider_transfer_denied"):
            value.authorize_transfer(ContextSnapshot(items=tuple(items)), RECIPIENT_A)
    assert value.provenance()[0]["was_read"] is True
