"""Extension runtime - error types."""


class ExtError(Exception):
    """A refusal or failure with a stable machine-readable code (the text is for logs, the code is for logic)."""
    code = "E_EXT"

    def __init__(self, message="", code=None, issues=None):
        super().__init__(message)
        if code:
            self.code = code
        self.issues = list(issues or [])


class ManifestError(ExtError):
    code = "E_EXT_MANIFEST"


class SourceRejected(ExtError):
    code = "E_EXT_SOURCE"


class PackageError(ExtError):
    code = "E_EXT_PACKAGE"


class LimitExceeded(BaseException):
    """A resource limit (work, time, size). It derives from BaseException on purpose: extension code can only catch the
    builtin exception names the validator allows, and none of them is a base of this class, so a limit can never be swallowed."""

    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind = kind
