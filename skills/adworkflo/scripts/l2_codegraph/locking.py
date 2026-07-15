from __future__ import annotations

import errno
import math
import os
import sys
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal


LockKind = Literal["build", "publish"]
DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0
LOCK_TIMEOUT_ENV = "ADWORKFLO_GRAPH_LOCK_TIMEOUT_SECONDS"


class GraphLockTimeout(TimeoutError):
    retryable = True

    def __init__(self, database: Path, kind: str, mode: str, timeout: float) -> None:
        self.database = database.resolve()
        self.kind = kind
        self.mode = mode
        self.timeout = timeout
        super().__init__(
            f"graph-lock-timeout: {kind} {mode} lock for {self.database} exceeded {timeout:.3f}s"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": "graph-lock-timeout",
            "message": str(self),
            "database": str(self.database),
            "kind": self.kind,
            "mode": self.mode,
            "timeout_seconds": self.timeout,
            "retryable": self.retryable,
        }


def lock_path(database: Path, kind: str) -> Path:
    if kind not in {"build", "publish"}:
        raise ValueError(f"unsupported graph lock kind: {kind}")
    resolved = database.resolve()
    return resolved.with_name(f"{resolved.name}.{kind}.lock")


def lock_timeout(value: float | None) -> float:
    if value is None:
        raw = os.environ.get(LOCK_TIMEOUT_ENV, str(DEFAULT_LOCK_TIMEOUT_SECONDS))
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError(f"{LOCK_TIMEOUT_ENV} must be a number, got {raw!r}") from error
    if value < 0 or not math.isfinite(value):
        raise ValueError("graph lock timeout must be a finite non-negative number")
    return value


if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
    LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    LOCK_CONFLICT_ERRORS = {32, 33, 158, 997}

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_size_t),
            ("InternalHigh", ctypes.c_size_t),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    _kernel32.LockFileEx.restype = wintypes.BOOL
    _kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(OVERLAPPED),
    ]
    _kernel32.UnlockFileEx.restype = wintypes.BOOL

    def _try_lock(fd: int, shared: bool) -> tuple[bool, OVERLAPPED]:
        overlapped = OVERLAPPED()
        flags = LOCKFILE_FAIL_IMMEDIATELY
        if not shared:
            flags |= LOCKFILE_EXCLUSIVE_LOCK
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
        if _kernel32.LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped)):
            return True, overlapped
        code = ctypes.get_last_error()
        if code in LOCK_CONFLICT_ERRORS:
            return False, overlapped
        raise OSError(code, ctypes.FormatError(code))

    def _unlock(fd: int, state: OVERLAPPED) -> None:
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
        if not _kernel32.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(state)):
            code = ctypes.get_last_error()
            raise OSError(code, ctypes.FormatError(code))

else:
    import fcntl

    def _try_lock(fd: int, shared: bool) -> tuple[bool, None]:
        operation = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(fd, operation | fcntl.LOCK_NB)
        except BlockingIOError:
            return False, None
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                return False, None
            raise
        return True, None

    def _unlock(fd: int, state: None) -> None:
        del state
        fcntl.flock(fd, fcntl.LOCK_UN)


@dataclass
class GraphLockLease:
    database: Path
    path: Path
    kind: str
    mode: str
    fd: int
    backend_state: Any
    _released: bool = field(default=False, init=False, repr=False)

    def release(self) -> None:
        if self._released:
            return
        try:
            _unlock(self.fd, self.backend_state)
        finally:
            os.close(self.fd)
            self._released = True

    def __enter__(self) -> GraphLockLease:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        self.release()
        return False


def acquire_graph_lock(
    database: Path,
    kind: LockKind,
    *,
    shared: bool = False,
    timeout: float | None = None,
) -> GraphLockLease:
    if kind == "build" and shared:
        raise ValueError("build locks are exclusive")
    database = database.resolve()
    path = lock_path(database, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_value = lock_timeout(timeout)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    deadline = time.monotonic() + timeout_value
    delay = 0.005
    try:
        while True:
            acquired, state = _try_lock(fd, shared)
            if acquired:
                return GraphLockLease(
                    database=database,
                    path=path,
                    kind=kind,
                    mode="shared" if shared else "exclusive",
                    fd=fd,
                    backend_state=state,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GraphLockTimeout(
                    database, kind, "shared" if shared else "exclusive", timeout_value,
                )
            time.sleep(min(delay, remaining))
            delay = min(delay * 1.5, 0.05)
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def graph_lock(
    database: Path,
    kind: LockKind,
    *,
    shared: bool = False,
    timeout: float | None = None,
) -> Iterator[GraphLockLease]:
    lease = acquire_graph_lock(database, kind, shared=shared, timeout=timeout)
    try:
        yield lease
    finally:
        lease.release()


@contextmanager
def graph_locks(
    databases: list[Path] | tuple[Path, ...] | set[Path],
    kind: LockKind,
    *,
    shared: bool = False,
    timeout: float | None = None,
) -> Iterator[list[GraphLockLease]]:
    ordered = sorted(
        {path.resolve() for path in databases},
        key=lambda path: (str(path).casefold(), str(path)),
    )
    with ExitStack() as stack:
        leases = [
            stack.enter_context(graph_lock(path, kind, shared=shared, timeout=timeout))
            for path in ordered
        ]
        yield leases
