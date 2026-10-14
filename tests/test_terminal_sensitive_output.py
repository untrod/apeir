"""Protected terminal material never becomes conversation or CLI output."""

import json
import uuid

import pytest

from nous_runtime.cli.terminal_session import TerminalSession, stream_chunks
from nous_runtime.core.redaction import REDACTED, register_sensitive_value


def _protected_value():
    value = f"test-terminal-protected-{uuid.uuid4().hex}"
    register_sensitive_value(value)
    return value


@pytest.mark.parametrize("fails", [False, True])
def test_terminal_redacts_executor_result_and_exception_before_persistence(
    tmp_path, fails
):
    value = _protected_value()
    session = TerminalSession(tmp_path, active_window=1)

    def execute(_text, _cancel):
        output = f"bounded diagnostic: {value}"
        if fails:
            raise RuntimeError(output)
        return output

    result = session.execute("run approved diagnostic", execute)
    assert result.status == ("failed" if fails else "completed")
    assert result.content == f"bounded diagnostic: {REDACTED}"
    assert value not in "".join(stream_chunks(result.content))
    reconnected = TerminalSession(tmp_path, conversation_id=session.conversation_id)
    assert reconnected.search(value)["messages"] == []
    assert value not in json.dumps(reconnected.history_page())
    assert value not in json.dumps(reconnected.context_snapshot())
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert value.encode() not in path.read_bytes(), path


def test_terminal_refuses_protected_input_before_executor_and_message_write(tmp_path):
    value = _protected_value()
    session = TerminalSession(tmp_path)
    calls = []
    with pytest.raises(ValueError, match="protected material"):
        session.execute(f"analyze {value}", lambda text, cancel: calls.append(text))
    assert calls == []
    assert session.store.history(session.conversation_id) == []


def test_terminal_keeps_nonsensitive_diagnostics_and_original_status(tmp_path):
    session = TerminalSession(tmp_path)

    def failed(_text, _cancel):
        raise ValueError("line 12: invalid integer")

    result = session.execute("validate input", failed)
    assert result.status == "failed"
    assert result.content == "line 12: invalid integer"
    assert session.search("invalid integer")["messages"][0]["content"] == result.content


def test_terminal_cancellation_does_not_publish_protected_late_output(tmp_path):
    value = _protected_value()
    session = TerminalSession(tmp_path)

    def cancelled(_text, cancel):
        cancel.set()
        return value

    result = session.execute("cancel approved diagnostic", cancelled)
    assert result.status == "cancelled"
    assert result.content == ""
    assert session.search(value)["messages"] == []
