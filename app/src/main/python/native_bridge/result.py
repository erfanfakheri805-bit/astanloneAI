"""
native_bridge.result - what every door answers
==============================================
A door never raises into the caller and never pretends: it answers with a `DoorResult` whose `code` says exactly what
happened ("ok", "unavailable_platform", "native_feature_missing", "permission_denied", "not_installed", "no_handler",
"not_allowed", "not_enabled", "rate_limited", "bad_arguments", "too_large", "timeout", "empty", "java_error").
`needs` names what the user (or the next build) must supply first - an Android permission, a native feature of the APK.
"""

from dataclasses import dataclass
from typing import Any

__all__ = ["DoorResult", "DoorPermissionError", "ok", "fail"]


class DoorPermissionError(PermissionError):
    """A pack used a door whose permission its manifest did not declare."""


@dataclass(frozen=True)
class DoorResult:
    ok: bool
    code: str
    detail_fa: str = ""
    data: Any = None
    needs: str = ""

    def to_dict(self):
        return {"ok": self.ok, "code": self.code, "detail_fa": self.detail_fa, "data": self.data, "needs": self.needs}

    def __bool__(self):
        return self.ok


def ok(data=None, detail_fa=""):
    return DoorResult(True, "ok", detail_fa, data)


def fail(code, detail_fa="", needs="", data=None):
    return DoorResult(False, str(code), detail_fa, data, needs)
