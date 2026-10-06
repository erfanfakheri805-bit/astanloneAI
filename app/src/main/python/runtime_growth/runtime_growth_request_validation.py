"""
Runtime growth - Runtime Growth Request Validation (Prompt 940)
================================================================
`validate_runtime_growth_request(request)` is a pure, deterministic check that a
value is exactly the request `create_runtime_growth_request()` (Prompt 939)
produces. It returns a fresh dict with only available, status, valid,
error_count and errors:

  - "valid"       a dict with exactly the eight request fields, supported
                  version, supported kind, already-normalized non-empty goal /
                  target / source, string reason, status "requested", and a
                  `request_id` equal to the id Prompt 939 derives from that
                  content (a hand-written or forged id is rejected);
  - "invalid"     a dict that fails any of those checks; `errors` lists stable
                  codes in a fixed order;
  - "unavailable" the input cannot be meaningfully validated (not a dict, or
                  reading it raised): available False, no errors.

Nothing is executed, generated randomly, written or read from disk / memory.db /
network, the request is never mutated and nothing raises. It is not wired into
Core, RuntimeCore, AEL, Android, capabilities, upgrades or Section 18.
"""

from runtime_growth import runtime_growth_request as _request

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_UNAVAILABLE = "unavailable"

ERR_INVALID_VERSION = "invalid_version"
ERR_INVALID_REQUEST_ID = "invalid_request_id"
ERR_REQUEST_ID_MISMATCH = "request_id_mismatch"
ERR_UNSUPPORTED_KIND = "unsupported_kind"
ERR_INVALID_GOAL = "invalid_goal"
ERR_INVALID_TARGET = "invalid_target"
ERR_INVALID_REASON = "invalid_reason"
ERR_INVALID_SOURCE = "invalid_source"
ERR_INVALID_STATUS = "invalid_status"
ERR_UNEXPECTED_FIELD = "unexpected_field"
ERR_MISSING_PREFIX = "missing_"


def _result(status, errors):
    return {"available": status != STATUS_UNAVAILABLE, "status": status,
            "valid": status == STATUS_VALID, "error_count": len(errors), "errors": list(errors)}


def _clean_text(value, allow_empty=False):
    """True for a string that is already exactly what Prompt 939 would produce."""
    return (isinstance(value, str) and value == _request._normalize_text(value)
            and (allow_empty or value != ""))


def validate_runtime_growth_request(request):
    """See the module docstring. Always returns a fresh dict; never raises."""
    try:
        if not isinstance(request, dict):
            return _result(STATUS_UNAVAILABLE, [])
        errors = [ERR_MISSING_PREFIX + name for name in _request.FIELDS if name not in request]
        if any(key not in _request.FIELDS for key in request):
            errors.append(ERR_UNEXPECTED_FIELD)
        present = {name: request[name] for name in _request.FIELDS if name in request}

        def has(name):
            return name in present

        if has("version") and not (isinstance(present["version"], str)
                                   and present["version"] == _request.REQUEST_VERSION):
            errors.append(ERR_INVALID_VERSION)
        request_id = present.get("request_id")
        id_ok = has("request_id") and isinstance(request_id, str) and request_id != ""
        if has("request_id") and not id_ok:
            errors.append(ERR_INVALID_REQUEST_ID)
        kind_ok = has("kind") and isinstance(present["kind"], str) \
            and present["kind"] in _request.REQUEST_KINDS
        if has("kind") and not kind_ok:
            errors.append(ERR_UNSUPPORTED_KIND)
        goal_ok = has("goal") and _clean_text(present["goal"])
        if has("goal") and not goal_ok:
            errors.append(ERR_INVALID_GOAL)
        target_ok = has("target") and _clean_text(present["target"])
        if has("target") and not target_ok:
            errors.append(ERR_INVALID_TARGET)
        reason_ok = has("reason") and _clean_text(present["reason"], allow_empty=True)
        if has("reason") and not reason_ok:
            errors.append(ERR_INVALID_REASON)
        source_ok = has("source") and _clean_text(present["source"])
        if has("source") and not source_ok:
            errors.append(ERR_INVALID_SOURCE)
        if has("status") and not (isinstance(present["status"], str)
                                  and present["status"] == _request.STATUS_REQUESTED):
            errors.append(ERR_INVALID_STATUS)
        # The id can only be checked against content that is itself valid.
        if id_ok and kind_ok and goal_ok and target_ok and reason_ok and source_ok:
            expected = _request.derive_runtime_growth_request_id(
                present["kind"], present["goal"], present["target"], present["reason"],
                present["source"])
            if request_id != expected:
                errors.append(ERR_REQUEST_ID_MISMATCH)
        return _result(STATUS_INVALID if errors else STATUS_VALID, errors)
    except Exception:  # noqa: BLE001 - the validator never raises
        return _result(STATUS_UNAVAILABLE, [])
