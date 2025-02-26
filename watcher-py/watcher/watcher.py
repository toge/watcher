"""
Filesystem watcher. Simple, efficient and friendly.
"""

from __future__ import annotations
import ctypes
import os
import sys
from typing import Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

_LIB: ctypes.CDLL | None = None


# pylint: disable=too-few-public-methods
class _CEvent(ctypes.Structure):
    _fields_ = [
        ("path_name", ctypes.c_char_p),
        ("effect_type", ctypes.c_int8),
        ("path_type", ctypes.c_int8),
        ("effect_time", ctypes.c_int64),
        ("associated_path_name", ctypes.c_char_p),
    ]


_CCallback = ctypes.CFUNCTYPE(None, _CEvent, ctypes.c_void_p)


def _lazy_static_solib_handle() -> ctypes.CDLL:
    def native_solib_file_ending():
        sysname = os.uname().sysname
        if sysname == "Darwin":
            return "dylib"
        if sysname == "Windows":
            return "dll"
        return "so"

    def libwatcher_c_lib_path():
        version = "0.12.0"  # hook: tool/release
        heredir = os.path.dirname(os.path.abspath(__file__))
        dir_path = os.path.join(heredir, ".watcher.mesonpy.libs")
        lib_name = f"libwatcher-c-{version}.{native_solib_file_ending()}"
        lib_path = os.path.join(dir_path, lib_name)
        if not os.path.exists(lib_path):
            raise RuntimeError(f"Library does not exist: '{lib_path}'")
        return lib_path

    # Resource is necessarily dynamic, mutable and bound to the lifetime of the program.
    # pylint: disable=global-statement
    global _LIB
    if _LIB is None:
        _LIB = ctypes.CDLL(libwatcher_c_lib_path())
        _LIB.wtr_watcher_open.argtypes = [ctypes.c_char_p, _CCallback, ctypes.c_void_p]
        _LIB.wtr_watcher_open.restype = ctypes.c_void_p
        _LIB.wtr_watcher_close.argtypes = [ctypes.c_void_p]
        _LIB.wtr_watcher_close.restype = ctypes.c_bool
    return _LIB


def _as_utf8(s: str | bytes | memoryview | None) -> str:
    if s is None:
        return ""
    if isinstance(s, str):
        return s
    if isinstance(s, memoryview):
        return s.tobytes().decode("utf-8")
    if isinstance(s, bytes):
        return s.decode("utf-8")
    raise TypeError()


def _c_event_to_event(c_event: _CEvent) -> Event:
    path_name = _as_utf8(c_event.path_name)
    associated_path_name = _as_utf8(c_event.associated_path_name)
    effect_type = EffectType(c_event.effect_type)
    path_type = PathType(c_event.path_type)
    effect_time = datetime.fromtimestamp(c_event.effect_time / 1e9)
    return Event(path_name, effect_type, path_type, effect_time, associated_path_name)


class EffectType(Enum):
    """
    The effect observed on a path.
    """

    RENAME = 0
    MODIFY = 1
    CREATE = 2
    DESTROY = 3
    OWNER = 4
    OTHER = 5


class PathType(Enum):
    """
    The type of a path as it was observed when the effect happened.
    The `watcher` case is special. Commonly used to report errors,
    warnings and important status updated (like when the watcher
    first begins watching and when it stops).
    """

    DIR = 0
    FILE = 1
    HARD_LINK = 2
    SYM_LINK = 3
    WATCHER = 4
    OTHER = 5


@dataclass
class Event:
    """
    Represents an event witnessed on the filesystem.
    """

    path_name: str
    effect_type: EffectType
    path_type: PathType
    effect_time: datetime
    associated_path_name: str


class Watch:
    """
    Filesystem watcher.
    Begins watching when constructed.
    Stops when the context manager exits (preferred to use it this way).
    Or when `close`, del or deinit happens, but you don't need to do that.
    Example usage:
    ```python
        with watcher.Watch(os.path.expanduser("~"), print):
            input()
    ```
    """

    def __init__(self, path: str, callback: Callable[[Event], None]):
        """
        - `path`: The path to watch.
        - `callback`: Called when events happen.
        """

        def callback_bridge(c_event: _CEvent, _) -> None:
            py_event = _c_event_to_event(c_event)
            callback(py_event)

        self._lib = _lazy_static_solib_handle()
        self._path = path.encode("utf-8")
        self._c_callback = _CCallback(callback_bridge)
        self._watcher = self._lib.wtr_watcher_open(self._path, self._c_callback, None)
        if not self._watcher:
            raise RuntimeError("Failed to open a watcher")

    def close(self):
        """
        You can call this manually (not required) to close the watcher.
        Preferred to use a context manager, like in the example.
        """
        if self._watcher:
            self._lib.wtr_watcher_close(self._watcher)
            self._watcher = None

    def __del__(self):
        self.close()

    def __deinit__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


if __name__ == "__main__":
    events_at = sys.argv[1] if len(sys.argv) > 1 else "."
    with Watch(events_at, print):
        input()
