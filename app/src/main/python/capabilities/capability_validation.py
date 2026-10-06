"""
Capability validation foundation (Prompt 844, Section 13 - Capability System)
=============================================================================
ONE read-only function that composes the existing capability layers into a
single validation result for a capability descriptor. It adds no rules of its
own: descriptor structure comes from Prompt 841, the version check from
Prompt 842 and the optional lifecycle state check from Prompt 843. Nothing is
registered, replaced, enabled, disabled, deprecated, executed or mutated, and
nothing is invented, normalised or inferred.

  validate_capability(descriptor, lifecycle_state=<omitted>) -> validation

Inputs
  descriptor       a capability descriptor (Prompt 841 structure, unchanged)
  lifecycle_state  OPTIONAL explicit lifecycle state (Prompt 843). When the
                   argument is omitted no lifecycle check is made and
                   `lifecycle_valid` is None. An explicitly passed value -
                   including None - is validated: None is an
                   `invalid_state_type`. The state is never inferred from the
                   descriptor (its `enabled` flag, name, version, purpose, ...)
                   and is not cross-checked against it.

Result (always these keys, in this order, JSON-safe, fresh on every call):

  {"valid", "errors", "name", "version", "identity_valid", "version_valid",
   "lifecycle_valid", "truncated", "execution_allowed", "executed"}

  valid            True only when the descriptor is structurally valid
                   (Prompt 841) AND the lifecycle state, if one was supplied,
                   is a lifecycle state (Prompt 843)
  errors           [{"code", "where"}], at most MAX_ERRORS, in this order:
                   the Prompt 841 descriptor errors unchanged (their codes and
                   locations, e.g. missing_field/"name", invalid_version/
                   "version", unexpected_field/"handler"), then the Prompt 843
                   lifecycle error (code invalid_state_type or unknown_state,
                   located at "lifecycle_state"); if the descriptor validator
                   itself failed: validator_error/"descriptor"; the unexpected
                   internal failure of this function: validation_error/
                   "descriptor"
  name             the descriptor name when it is a valid identity name, else
                   None (a malformed name is never echoed)
  version          the descriptor version when it is a valid capability
                   version, else None
  identity_valid   the descriptor name is a valid capability identity (the
                   Prompt 841 name rule; for a fully valid descriptor the
                   Prompt 842 `build_capability_identity` result is used)
  version_valid    `parse_capability_version` (Prompt 842) accepts the
                   descriptor's version (False when absent or not a dict)
  lifecycle_valid  None (omitted), True or False
  truncated        True when more than MAX_ERRORS errors were found
  execution_allowed, executed
                   always False; a valid result, like a lifecycle state,
                   never implies that the capability can execute

The flags are independent: for example a descriptor with a malformed purpose
has identity_valid and version_valid True but valid False. Bounded work (the
Prompt 841 bounds apply), read-only (inputs are never modified or kept),
deterministic, never raises. Pure Python plus the three Prompt 841-843
modules; no Core, Memory, AEL, NLU, reasoning, execution, LLM, network or
filesystem. No registry is used or changed.
"""

from .capability_registry import MAX_ERRORS, validate_capability_descriptor
from .capability_identity import build_capability_identity, parse_capability_version
from .capability_lifecycle import validate_lifecycle_state

VALIDATION_VERSION = 1

ERR_VALIDATION = "validation_error"

_NOT_SUPPLIED = object()


def _result(valid, errors, truncated, name, version, identity_valid, version_valid,
            lifecycle_valid):
    return {"valid": valid, "errors": errors, "name": name, "version": version,
            "identity_valid": identity_valid, "version_valid": version_valid,
            "lifecycle_valid": lifecycle_valid, "truncated": truncated,
            "execution_allowed": False, "executed": False}


def validate_capability(descriptor, lifecycle_state=_NOT_SUPPLIED):
    """Validate a capability descriptor and, optionally, a lifecycle state."""
    try:
        validation = validate_capability_descriptor(descriptor)
        errors = [{"code": e["code"], "where": e["where"]} for e in validation["errors"]]
        truncated = validation["truncated"]
        descriptor_ok = validation["valid"]
        is_dict = type(descriptor) is dict

        # identity: the Prompt 841 name rule (a name error is located at "name")
        name_failed = (not is_dict) or any(e["where"] == "name" for e in errors)
        name = None
        if not name_failed:
            if descriptor_ok:
                identity = build_capability_identity(descriptor)
                name = identity["identity"]["name"] if identity["valid"] else None
                identity_valid = identity["valid"]
            else:
                name = descriptor["name"]
                identity_valid = True
        else:
            identity_valid = False

        # version: the Prompt 842 version rule
        version = None
        version_valid = False
        if is_dict and "version" in descriptor:
            parsed = parse_capability_version(descriptor["version"])
            version_valid = parsed["valid"]
            version = parsed["number"]

        # optional lifecycle state: the Prompt 843 state rule
        lifecycle_valid = None
        if lifecycle_state is not _NOT_SUPPLIED:
            state = validate_lifecycle_state(lifecycle_state)
            lifecycle_valid = state["valid"]
            for e in state["errors"]:
                if len(errors) >= MAX_ERRORS:
                    truncated = True
                else:
                    errors.append({"code": e["code"], "where": "lifecycle_state"})

        valid = descriptor_ok and lifecycle_valid is not False
        return _result(valid, errors, truncated, name, version, identity_valid,
                       version_valid, lifecycle_valid)
    except Exception:
        return _result(False, [{"code": ERR_VALIDATION, "where": "descriptor"}], False,
                       None, None, False, False, None)
