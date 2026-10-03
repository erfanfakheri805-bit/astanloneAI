"""
Language Intelligence - Backend Selection Result
====================================================
Prompt 414. `BackendSelection` is the small value `LanguageIntelligenceCore.select_backend()`
returns: which backend answers a request, and - when the local model is not
the one - the structured reason it was not used. It is a plain record, not a
controller: the routing itself is a few lines inside LanguageIntelligenceCore,
and the fallback behavior it selects is Prompt 406's, unchanged.

    local model ready                    -> the local-model backend is selected
    MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE / MODEL_LOAD_FAILED
                                         -> the deterministic fallback backend
                                            is selected; the local model is not
                                            called at all (no request built, no
                                            load, no inference) and the reason
                                            is the same structured failure a
                                            blocked request has returned since
                                            Prompt 409 (`not_ready_response`)
    nothing to choose between (the primary is not a local model, or no
    fallback backend is configured)      -> the primary backend, as before

`selected_backend_kind` is one of backend.py's BACKEND_KIND_* values and is
copied onto the `ResponseGenerationResult` so a response says which backend
was selected for it. It never says the deterministic backend was the local
model: a fallback selection is `deterministic_fallback` with
`local_model_selected` False.
"""

from .backend import BACKEND_KIND_LOCAL_MODEL


class BackendSelection:
    def __init__(self, selected_backend_kind, readiness=None, not_ready_response=None,
                 fallback_selected=False):
        self.selected_backend_kind = selected_backend_kind
        # the ModelReadiness (inference.py) observed for this selection; None if unknown
        self.readiness = readiness
        # the structured model failure explaining why the local model was not
        # used (ResponseGenerationResult); None when it was (or was never the primary)
        self.not_ready_response = not_ready_response
        # True only when the local model was the primary but the fallback backend was chosen
        self.fallback_selected = bool(fallback_selected)

    @property
    def local_model_selected(self):
        return self.selected_backend_kind == BACKEND_KIND_LOCAL_MODEL

    @property
    def reason(self):
        """Short human-readable explanation when the fallback was selected,
        else None."""
        if not self.fallback_selected:
            return None
        response = self.not_ready_response
        status = getattr(self.readiness, "status", None)
        code = getattr(response, "error_code", None) or getattr(self.readiness, "error_code", None)
        return f"local model not used: {status or 'not ready'}" + (f" ({code})" if code else "")

    def __repr__(self):
        return (f"BackendSelection(selected_backend_kind={self.selected_backend_kind!r}, "
                f"fallback_selected={self.fallback_selected})")

    def to_dict(self):
        return {
            "selected_backend_kind": self.selected_backend_kind,
            "local_model_selected": self.local_model_selected,
            "fallback_selected": self.fallback_selected,
            "readiness": self.readiness.to_dict() if hasattr(self.readiness, "to_dict") else None,
            "reason": self.reason,
        }
