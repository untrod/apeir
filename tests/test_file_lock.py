"""Windows contention must preserve exclusion without CRT's coarse retry queue."""

import errno
import sys
from types import SimpleNamespace

import pytest

import nous_runtime.locking as locking


def windows_lock(monkeypatch, operation):
    clock = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(locking, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        locking, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)
    )
    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=0, locking=operation),
    )
    return clock, sleeps


def test_windows_contention_acquires_before_entering_and_releases_on_body_error(
    tmp_path, monkeypatch
):
    calls = []

    def operation(fd, mode, size):
        calls.append((mode, size))
        if mode == 1:
            raise OSError(errno.EDEADLK, "CRT blocking retry limit exhausted")
        if mode == 2 and len(calls) <= 2:
            raise OSError(errno.EACCES, "Another writer owns this byte")

    clock, sleeps = windows_lock(monkeypatch, operation)
    with pytest.raises(ValueError, match="original body failure"):
        with locking.file_lock(tmp_path / "index.json.lock"):
            assert calls == [(2, 1), (2, 1), (2, 1)]
            raise ValueError("original body failure")
    assert calls[-1] == (0, 1)
    assert sleeps and clock[0] < 1


@pytest.mark.parametrize("failure", [errno.EACCES, errno.EAGAIN, errno.EDEADLK])
def test_windows_contention_deadline_never_enters_or_unlocks_unowned_region(
    tmp_path, monkeypatch, failure
):
    calls = []

    def operation(fd, mode, size):
        calls.append((mode, size))
        raise OSError(failure, "Still owned by another process")

    clock, sleeps = windows_lock(monkeypatch, operation)
    with pytest.raises(OSError) as caught:
        with locking.file_lock(tmp_path / "index.json.lock"):
            pytest.fail("Contended lock must never admit the body")
    assert caught.value.errno == failure
    assert clock[0] <= 10
    assert sleeps and max(sleeps) <= 0.05
    assert all(mode == 2 and size == 1 for mode, size in calls)


def test_windows_unrelated_lock_error_is_not_retried(tmp_path, monkeypatch):
    calls = []

    def operation(fd, mode, size):
        calls.append((mode, size))
        raise OSError(errno.EBADF, "Invalid handle")

    clock, sleeps = windows_lock(monkeypatch, operation)
    with pytest.raises(OSError) as caught:
        with locking.file_lock(tmp_path / "index.json.lock"):
            pytest.fail("Invalid handles must fail closed")
    assert caught.value.errno == errno.EBADF
    assert calls == [(2, 1)]
    assert clock[0] == 0 and sleeps == []
