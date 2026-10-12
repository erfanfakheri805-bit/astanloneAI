"""
Self-Builder - error types
==========================
Every failure the Self-Builder can report carries a stable machine-readable
`code` (used by the failure analyzer in repair.py, by the audit log and by
tests) and a human-readable English `detail`. Persian wording for the user is
produced by the conversation layer (persian_brain) from the code, never
parsed back out of the detail text.
"""


class SelfBuilderError(Exception):
    """Base class. `code` is stable; `detail` is for logs/diagnostics."""

    code = "E_SELF_BUILDER"

    def __init__(self, detail="", code=None, **info):
        super().__init__(detail or self.code)
        if code is not None:
            self.code = code
        self.detail = detail or self.code
        self.info = info

    def to_dict(self):
        out = {"code": self.code, "detail": self.detail}
        if self.info:
            out["info"] = dict(self.info)
        return out


class PolicyViolation(SelfBuilderError):
    """An operation, path or file type outside the Self-Builder's allowlists."""

    code = "E_POLICY"


class SpecError(SelfBuilderError):
    """A capability spec / build request that cannot be turned into a valid spec."""

    code = "E_SPEC"


class ExprError(SelfBuilderError):
    """The arithmetic expression grammar rejected an expression."""

    code = "E_EXPR"


class ValidationError(SelfBuilderError):
    """Generated source violated the AST allowlist (or size/structure limits)."""

    code = "E_VALIDATION"


class SandboxError(SelfBuilderError):
    """Loading or running generated code inside the sandbox failed."""

    code = "E_SANDBOX"


class StoreError(SelfBuilderError):
    """Persistent store problem (schema, integrity, audit chain)."""

    code = "E_STORE"


class ApplyError(SelfBuilderError):
    """The apply/persist/register step failed and was rolled back."""

    code = "E_APPLY"
