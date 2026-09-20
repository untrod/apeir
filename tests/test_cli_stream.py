from nous_runtime.cli.stream import Spinner, TraceDisplay, status_bar


def test_terminal_markers_are_portable_ascii():
    assert Spinner.FRAMES == ["|", "/", "-", "\\"]
    assert all(frame.isascii() for frame in Spinner.FRAMES)


def test_trace_display_uses_ascii_status_markers():
    trace = TraceDisplay()
    completed = trace.add("Prepare", "done", "Ready")
    failed = trace.add("Run", "failed")
    completed.duration_ms = 12
    failed.duration_ms = 13

    rendered = trace.render()

    assert "[OK] Prepare" in rendered
    assert "[FAIL] Run" in rendered
    assert rendered.isascii()


def test_status_bar_is_ascii_and_explicit():
    assert status_bar(running=True, providers=1).startswith("online Runtime")
    assert status_bar(running=False).startswith("offline Runtime")