"""
Runtime integration - Final Runtime Assessment (Prompt 938)
===========================================================
`build_final_runtime_assessment(boundary_validation, runtime_readiness,
controlled_reasoning_snapshot=None)` is a pure, descriptive assessment over the
Prompt 937 boundary validation and the Prompt 935/936 readiness result. It keeps
five things apart and never claims more than the evidence supports:

  architecture existing        -> boundary areas "exists"
  runtime integration existing -> `structurally_integrated` (all areas connected)
  runtime capability usable    -> `runtime_usable` (stricter)
  APK release readiness        -> `apk_ready` (stricter than runtime_usable)
  Claude independence          -> `claude_independent` (strictest gate)

Nothing is executed, invoked, modified, granted or enabled. Inputs are never
mutated and never trusted: the boundary validation is re-derived from its own
per-area flags with the existing Prompt 937 helper and must match exactly.
Evidence this function has no channel for (Android device validation, production
release evidence, an executable growth workflow, Claude being out of the
implementation chain) stays False, so `apk_ready` and `claude_independent` cannot
become True from architecture alone. The result is a fresh dict; it never raises.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runtime_integration import bridge

ASSESSMENT_VERSION = 1

STATUS_ASSESSED = "assessed"
STATUS_NOT_VERIFIED = "not_verified"

RUNTIME_INTEGRATED = "integrated"
RUNTIME_PARTIALLY_INTEGRATED = "partially_integrated"
RUNTIME_NOT_INTEGRATED = "not_integrated"
RUNTIME_NOT_VERIFIED = "not_verified"

APK_NOT_READY = "not_ready"
APK_READY = "ready"
EXIT_NOT_INDEPENDENT = "not_independent"
EXIT_INDEPENDENT = "independent"

# Deliberately outside the current baby-assistant milestone: never blockers.
DEFERRED_AREAS = (
    "advanced_multimodal_generation", "image_video_generation",
    "advanced_voice_transformation", "broad_device_automation",
    "advanced_web_research", "full_jarvis_level_autonomy")

_AREAS = bridge.BOUNDARY_AREAS
_READINESS_STATUSES = ("runtime_ready", "runtime_not_ready", "integration_ready",
                       "integration_not_ready")
_AREA_FLAGS = ("exists", "connected_to_runtime_core", "activated_in_runtime_path",
               "execution_capable")


def _evidence_from_boundary(boundary):
    """Evidence dict that must reproduce the boundary's own `areas` through the
    Prompt 937 helper, or None. Areas the helper reported as unusable evidence are
    rebuilt as the kind of evidence that yields exactly that report."""
    areas = boundary.get("areas")
    if not isinstance(areas, dict) or list(areas) != list(_AREAS):
        return None
    evidence = {}
    for name in _AREAS:
        area = areas[name]
        if not isinstance(area, dict):
            return None
        reason = area.get("reason")
        if reason == "missing_evidence":
            continue
        if reason == "malformed_evidence":
            evidence[name] = "malformed"
        elif reason == "contradictory_evidence":
            evidence[name] = {"exists": False, "connected_to_runtime_core": True,
                              "activated_in_runtime_path": False, "execution_capable": False}
        else:
            evidence[name] = {k: area.get(k) for k in _AREA_FLAGS}
    return evidence


def _verified_boundary(boundary):
    """The boundary validation iff it equals what the Prompt 937 helper derives
    from its own area flags (so claimed flags are never trusted); else None."""
    if not isinstance(boundary, dict) or boundary.get("available") is not True:
        return None
    evidence = _evidence_from_boundary(boundary)
    if evidence is None or bridge.final_runtime_integration_boundary_validation(evidence) != boundary:
        return None
    return boundary


def _descriptive_state_ok(value, statuses=None):
    return (isinstance(value, dict) and isinstance(value.get("available"), bool)
            and isinstance(value.get("status"), str)
            and (statuses is None or value["status"] in statuses)
            and value.get("actionable") is False and value.get("executed") is False
            and value.get("descriptive_only") is True)


def _reasoning_usable(readiness, snapshot):
    """(usable, consistent). `readiness` must be a well-formed descriptive state;
    a given snapshot must be well-formed, and a Prompt 935 readiness must equal
    what the existing helper derives from it."""
    if not _descriptive_state_ok(readiness, _READINESS_STATUSES) \
            or not isinstance(readiness.get("ready"), bool):
        return False, False
    if snapshot is not None:
        if not _descriptive_state_ok(snapshot):
            return False, False
        if (readiness["status"].startswith("runtime_")
                and bridge.controlled_reasoning_runtime_ready(snapshot) != readiness):
            return False, False
    return readiness["available"] is True and readiness["ready"] is True, True


def _result(runtime_state, structural, usable, apk, exit_, blocking):
    return {
        "version": ASSESSMENT_VERSION,
        "available": runtime_state != RUNTIME_NOT_VERIFIED,
        "status": STATUS_NOT_VERIFIED if runtime_state == RUNTIME_NOT_VERIFIED else STATUS_ASSESSED,
        "runtime_state": runtime_state,
        "apk_state": apk,
        "claude_exit_state": exit_,
        "blocking_areas": blocking,
        "deferred_areas": list(DEFERRED_AREAS),
        "structurally_integrated": structural,
        "runtime_usable": usable,
        "apk_ready": apk["status"] == APK_READY,
        "claude_independent": exit_["status"] == EXIT_INDEPENDENT,
        "actionable": False,
        "executed": False,
        "descriptive_only": True,
    }


def _gate(ready_status, not_ready_status, requirements):
    return {"status": ready_status if all(requirements.values()) else not_ready_status,
            "requirements": requirements,
            "missing": [k for k, v in requirements.items() if not v]}


def _unverified():
    """Nothing could be verified: the two evidence-free blockers still stand."""
    apk = _gate(APK_READY, APK_NOT_READY, {
        "android_integration": False, "usable_runtime_path": False, "memory_runtime": False,
        "AEL_learning_runtime": False, "local_ai_runtime": False, "capability_runtime": False,
        "reasoning_runtime": False, "android_device_validation": False,
        "production_release_evidence": False})
    exit_ = _gate(EXIT_INDEPENDENT, EXIT_NOT_INDEPENDENT, {
        "runtime_usable": False, "apk_ready": False, "upgrade_runtime": False,
        "runtime_growth_path": False, "claude_outside_implementation_chain": False})
    return _result(RUNTIME_NOT_VERIFIED, False, False, apk, exit_,
                   ["android_device_validation", "runtime_growth_path"])


def build_final_runtime_assessment(boundary_validation, runtime_readiness,
                                   controlled_reasoning_snapshot=None):
    """Prompt 938: see the module docstring. Returns a fresh dict with exactly the
    keys version, available, status, runtime_state, apk_state, claude_exit_state,
    blocking_areas, deferred_areas, structurally_integrated, runtime_usable,
    apk_ready, claude_independent, actionable, executed, descriptive_only.
    `runtime_state` is "not_verified" (and `available` False) when an input is
    missing, malformed, untrustworthy or inconsistent. Never raises."""
    try:
        boundary = _verified_boundary(boundary_validation)
        reasoning_ok, consistent = _reasoning_usable(
            runtime_readiness, controlled_reasoning_snapshot)
        if boundary is None or not consistent:
            return _unverified()
        areas = boundary["areas"]

        def structural(name):
            return areas[name]["status"] == bridge.BOUNDARY_STRUCTURALLY_INTEGRATED

        def capable(name):
            return areas[name]["execution_capable"] is True

        all_structural = all(structural(n) for n in _AREAS)
        if all_structural and reasoning_ok:
            runtime_state = RUNTIME_INTEGRATED
        elif all_structural or any(
                areas[n]["status"] != bridge.BOUNDARY_NOT_INTEGRATED for n in _AREAS):
            runtime_state = RUNTIME_PARTIALLY_INTEGRATED
        else:
            runtime_state = RUNTIME_NOT_INTEGRATED
        structurally_integrated = runtime_state == RUNTIME_INTEGRATED

        usable_parts = {
            "reasoning_runtime": reasoning_ok,
            "memory_runtime": capable("memory_runtime"),
            "AEL_learning_runtime": capable("AEL_learning_runtime"),
            "local_ai_runtime": capable("local_model_runtime"),
            "capability_runtime": capable("capability_runtime"),
        }
        runtime_usable = structurally_integrated and all(usable_parts.values())

        apk = _gate(APK_READY, APK_NOT_READY, {
            "android_integration": structural("android_runtime_bridge")
            and areas["android_runtime_bridge"]["activated_in_runtime_path"] is True,
            "usable_runtime_path": runtime_usable,
            "memory_runtime": usable_parts["memory_runtime"],
            "AEL_learning_runtime": usable_parts["AEL_learning_runtime"],
            "local_ai_runtime": usable_parts["local_ai_runtime"],
            "capability_runtime": usable_parts["capability_runtime"],
            "reasoning_runtime": usable_parts["reasoning_runtime"],
            # No evidence channel exists for these yet; they stay False.
            "android_device_validation": False,
            "production_release_evidence": False,
        })
        exit_ = _gate(EXIT_INDEPENDENT, EXIT_NOT_INDEPENDENT, {
            "runtime_usable": runtime_usable,
            "apk_ready": apk["status"] == APK_READY,
            "upgrade_runtime": capable("upgrade_runtime"),
            # No evidence channel exists for these yet; they stay False.
            "runtime_growth_path": False,
            "claude_outside_implementation_chain": False,
        })

        blocking = [n for n in _AREAS if not structural(n)]
        for name in ("local_model_runtime", "capability_runtime", "upgrade_runtime"):
            if structural(name) and not capable(name) and name not in blocking:
                blocking.append(name)
        blocking.sort(key=_AREAS.index)
        blocking += ["android_device_validation", "runtime_growth_path"]
        return _result(runtime_state, structurally_integrated, runtime_usable, apk, exit_,
                       blocking)
    except Exception:  # noqa: BLE001 - assessment must never raise
        return _unverified()
