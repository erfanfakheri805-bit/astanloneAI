"""
net_tools.permission - the permission gate every network call must pass
=======================================================================
The only way for this package to learn that the user allowed internet access
is a `PermissionGate`. The gate is asked BEFORE any socket is opened; when it
says no, the transport is never called (tests assert this).

`StaticGate` is the simplest gate (a fixed set of granted permission names).
The Brain Hub supplies a gate that reads the user's recorded grant, so the
"network" permission is something the user said yes to inside the app - never
something this package assumes.
"""

from __future__ import annotations

from typing import Callable, Iterable, Protocol, runtime_checkable

__all__ = ["NETWORK", "PermissionGate", "StaticGate", "CallableGate"]

NETWORK = "network"


@runtime_checkable
class PermissionGate(Protocol):
    """Anything with `allowed(permission) -> bool`."""

    def allowed(self, permission: str) -> bool:  # pragma: no cover - protocol
        ...


class StaticGate:
    """A gate with a fixed, immutable set of granted permission names."""

    __slots__ = ("_granted",)

    def __init__(self, granted: Iterable[str] = ()) -> None:
        names = []
        for name in granted:
            if not isinstance(name, str):
                raise ValueError("permission names must be strings")
            names.append(name)
        object.__setattr__(self, "_granted", frozenset(names))

    def __setattr__(self, key, value):  # immutable
        raise AttributeError("StaticGate is immutable")

    def allowed(self, permission: str) -> bool:
        return isinstance(permission, str) and permission in self._granted

    def __repr__(self) -> str:
        return "StaticGate(%s)" % sorted(self._granted)


class CallableGate:
    """Adapts a `(permission) -> bool` callable; any error or non-True result means 'not allowed'."""

    __slots__ = ("_fn",)

    def __init__(self, fn: Callable[[str], bool]) -> None:
        if not callable(fn):
            raise ValueError("fn must be callable")
        object.__setattr__(self, "_fn", fn)

    def __setattr__(self, key, value):
        raise AttributeError("CallableGate is immutable")

    def allowed(self, permission: str) -> bool:
        try:
            return self._fn(permission) is True
        except Exception:  # a broken gate must fail closed
            return False
