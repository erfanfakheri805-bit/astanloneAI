"""
Self-Upgrade Lifecycle Health Check (Prompt 385)
=================================================
A small, read-only diagnostic that inspects the EXISTING Self-Upgrade
lifecycle and reports whether its major components are available and
connected to each other. It is not a new Self-Upgrade architecture and
it changes nothing: it follows the same conventions as the existing
`diagnostics/health_system.HealthSystem` (a `check()` that runs cheap,
side-effect-free probes and returns a computed status plus one entry per
component - never a hard-coded "healthy"), but it is a separate class
because `HealthSystem` is the app-wide check (and its skills probe
writes a throwaway file), whereas this one must be strictly read-only.

What "available and connected" means - every check is a real probe:

  STATIC (always run; needs nothing but the code):
    - the component's module imports;
    - the expected function/class exists;
    - a function accepts the parameters the next stage passes it, and a
      class has the methods (and constructor parameters) its neighbours
      call. The seams between stages are therefore checked, e.g. the
      coordinator's `decide`/`advance` must accept every piece of stage
      evidence `build_capability_lifecycle_state` consumes, the resume
      manager must be built from a store and a coordinator, and the
      registration executor must take the approval manager and the
      capability system.
    Nothing is ever *called*: signatures are inspected, not executed.

  LIVE (only for the services you hand in; optional):
    - a supplied service must be an instance of the expected class;
    - a single read-only lookup must work against it (the current
      version, a stored-record miss, a context miss, listing the
      registry);
    - the wiring must be the real wiring: the coordinator must hold the
      same `ApprovalManager` you supplied, and the resume manager the
      same store and coordinator.
    A component with no supplied service is checked statically only and
    its entry says so (`"live": False`).

Statuses (the same words the rest of Self-Upgrade uses):

    HEALTHY   - every check passed.
    DEGRADED  - exactly one check failed: the rest of the lifecycle is
                intact, and the failed component is named, but the
                lifecycle cannot pass that stage until it is repaired.
    FAILED    - two or more checks failed.

Each individual check is HEALTHY or FAILED. The result:

    {
      "status":            HEALTHY | DEGRADED | FAILED,
      "checks":            [{"name", "status", "detail", "problems", "live"}, ...],
      "failed_components": [check names that failed, in check order],
      "checks_run":        int,
      "checks_passed":     int,
      "live_checked":      bool  (True only if any service was supplied),
      "message":           str   (a useful, human-readable summary),
    }

THIS CHECK IS READ-ONLY. It never creates, builds, applies, tests,
registers, enables, or activates a capability; never executes generated
code; never approves, rejects, or creates an approval request; never
writes the capability registry, the version history, an execution
context, or any lifecycle state; never repairs or retries anything;
never starts a Self-Upgrade cycle; never touches the network. A missing
or broken component is reported, never fixed. It never raises: a probe
that blows up is itself reported as a failed check.
"""

import importlib
import inspect

STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_FAILED = "FAILED"
ALL_STATUSES = (STATUS_HEALTHY, STATUS_DEGRADED, STATUS_FAILED)

# Used only as a lookup key for read-only misses; never written anywhere.
_PROBE_ID = "__self_upgrade_health_check__"

# What the lifecycle stages hand to the coordinator / lifecycle tracker.
_LIFECYCLE_EVIDENCE = (
    "capability_name", "build_result", "apply_request", "test_evaluation",
    "human_approval_request", "approval_manager", "approval_request_id",
    "registration_request_id", "registration_plan", "registration_result",
    "verification_result",
)


def _function(module, name, *params):
    return {"module": module, "name": name, "kind": "function", "params": tuple(params)}


def _cls(module, name, members=(), init_params=(), method_params=None):
    return {"module": module, "name": name, "kind": "class", "members": tuple(members),
            "init_params": tuple(init_params),
            "method_params": {k: tuple(v) for k, v in (method_params or {}).items()}}


# The checks, in lifecycle order. Each check lists the real entry points
# it depends on and the seams (parameters / methods) it must expose.
SELF_UPGRADE_COMPONENTS = (
    ("analysis", (
        _cls("self_upgrade.self_upgrade_request", "SelfUpgradeRequest",
             members=("is_valid", "to_dict"),
             init_params=("request_id", "goal", "requested_capability", "reason")),
        _cls("planning.adaptive_plan_analyzer", "AdaptivePlanAnalyzer",
             members=("analyze_self_upgrade_request",),
             init_params=("goal_manager", "plan_manager", "capability_system", "capability_handlers")),
    )),
    ("capability_planning", (
        _function("self_upgrade.capability_creation_plan", "build_capability_creation_plan", "analysis"),
        _function("self_upgrade.capability_implementation_spec",
                  "build_capability_implementation_spec", "plan", "capability_handlers"),
        _function("self_upgrade.capability_build_spec", "build_capability_build_spec", "spec"),
    )),
    ("capability_building", (
        _function("self_upgrade.capability_builder", "build_capability", "spec"),
        _function("code_generation.local_function_generator", "generate_function", "spec"),
    )),
    ("validation", (
        _function("code_generation.generated_code_validator", "validate_generated_code", "result"),
        _function("self_upgrade.capability_apply_request",
                  "build_capability_apply_request", "builder_result"),
    )),
    ("testing", (
        _function("self_upgrade.capability_file_apply", "apply_capability",
                  "request", "output_root", "allowed_dirs"),
        _function("self_upgrade.capability_test_execution", "run_capability_tests",
                  "apply_result", "project_dir", "test_target", "allowed_dirs"),
        _function("self_upgrade.capability_evaluation", "evaluate_capability_test_result", "test_result"),
    )),
    ("versioning", (
        _cls("self_upgrade.version_system", "VersionSystem",
             members=("create_version", "current_version", "history", "rollback_to"),
             init_params=("memory",)),
    )),
    ("human_approval", (
        _function("self_upgrade.capability_first_pass_verification",
                  "verify_capability_first_pass", "test_result"),
        _function("self_upgrade.capability_human_approval", "request_capability_human_approval",
                  "verification_result", "versions", "allowed_dirs"),
        _cls("self_upgrade.capability_approval_manager", "ApprovalManager",
             members=("create_request", "approve", "reject", "get_request", "get_status",
                      "get_stored_record"),
             init_params=("memory",)),
        _function("self_upgrade.capability_approval_gate", "evaluate_self_upgrade_approval_gate",
                  "human_approval_request", "approval_manager"),
    )),
    ("registration_preparation", (
        _function("self_upgrade.capability_registration_preparation",
                  "prepare_capability_registration",
                  "human_approval_request", "approval_manager", "build_spec"),
        _function("self_upgrade.capability_registration_plan", "build_capability_registration_plan",
                  "registration_preparation", "approval_manager"),
    )),
    ("registration_approval", (
        _function("self_upgrade.capability_registration_approval",
                  "request_capability_registration_approval", "registration_plan"),
        _function("self_upgrade.capability_registration_decision", "resolve_registration_decision",
                  "request_id", "approval_manager"),
    )),
    ("registration", (
        _function("self_upgrade.capability_registration_executor", "register_approved_capability",
                  "request_id", "approval_manager", "capability_system"),
    )),
    ("registration_verification", (
        _function("self_upgrade.capability_registration_verifier", "verify_registered_capability",
                  "registration_result", "approval_manager", "capability_system"),
    )),
    ("lifecycle_tracking", (
        _function("self_upgrade.capability_lifecycle", "build_capability_lifecycle_state",
                  *_LIFECYCLE_EVIDENCE),
    )),
    ("execution_context_persistence", (
        _cls("self_upgrade.self_upgrade_execution_context", "SelfUpgradeExecutionContextStore",
             members=("get_or_create", "load", "save"), init_params=("memory",)),
        _function("self_upgrade.self_upgrade_execution_context", "validate_execution_context", "context"),
    )),
    ("resume_support", (
        _cls("self_upgrade.self_upgrade_resume_manager", "SelfUpgradeResumeManager",
             members=("resume",), init_params=("store", "coordinator"),
             method_params={"resume": ("upgrade_request_id",)}),
    )),
    ("lifecycle_coordinator", (
        _cls("self_upgrade.self_upgrade_lifecycle_coordinator", "SelfUpgradeLifecycleCoordinator",
             members=("decide", "advance", "resume"), init_params=("approval_manager",),
             method_params={"decide": _LIFECYCLE_EVIDENCE,
                            "advance": ("context",) + _LIFECYCLE_EVIDENCE,
                            "resume": ("context",)}),
    )),
)

CHECK_NAMES = tuple(name for name, _ in SELF_UPGRADE_COMPONENTS)


def _params_missing(obj, wanted):
    try:
        available = set(inspect.signature(obj).parameters)
    except (TypeError, ValueError):
        return list(wanted)
    return [p for p in wanted if p not in available]


def _static_problems(entry):
    """Problems (strings) with one entry point. Only inspects; never calls."""
    label = f"{entry['module']}.{entry['name']}"
    try:
        module = importlib.import_module(entry["module"])
    except Exception as exc:
        return [f"{entry['module']} could not be imported ({type(exc).__name__}: {exc})"]
    obj = getattr(module, entry["name"], None)
    if obj is None:
        return [f"{label} is missing"]

    if entry["kind"] == "function":
        if not callable(obj) or inspect.isclass(obj):
            return [f"{label} is not a function"]
        missing = _params_missing(obj, entry["params"])
        return [f"{label} does not accept {', '.join(missing)}"] if missing else []

    if not inspect.isclass(obj):
        return [f"{label} is not a class"]
    problems = []
    for member in entry["members"]:
        if not callable(getattr(obj, member, None)):
            problems.append(f"{label} has no method {member}")
    missing = _params_missing(obj.__init__, entry["init_params"])
    if missing:
        problems.append(f"{label} constructor does not accept {', '.join(missing)}")
    for method, wanted in entry["method_params"].items():
        method_obj = getattr(obj, method, None)
        if callable(method_obj):
            missing = _params_missing(method_obj, wanted)
            if missing:
                problems.append(f"{label}.{method} does not accept {', '.join(missing)}")
    return problems


def _class_named(module_name, class_name):
    try:
        return getattr(importlib.import_module(module_name), class_name)
    except Exception:
        return None


class SelfUpgradeHealthCheck:
    """`SelfUpgradeHealthCheck(...).check()` - see the module docstring.
    Every constructor argument is optional; supply the live services you
    want inspected (their read-only probes and wiring are then checked
    too)."""

    def __init__(self, version_system=None, approval_manager=None, capability_system=None,
                 context_store=None, coordinator=None, resume_manager=None):
        self.version_system = version_system
        self.approval_manager = approval_manager
        self.capability_system = capability_system
        self.context_store = context_store
        self.coordinator = coordinator
        self.resume_manager = resume_manager

    # ---- public --------------------------------------------------------
    def check(self):
        checks = [self._run_check(name, entries) for name, entries in SELF_UPGRADE_COMPONENTS]
        failed = [c["name"] for c in checks if c["status"] == STATUS_FAILED]
        if not failed:
            status = STATUS_HEALTHY
        elif len(failed) == 1:
            status = STATUS_DEGRADED
        else:
            status = STATUS_FAILED
        return {
            "status": status,
            "checks": checks,
            "failed_components": failed,
            "checks_run": len(checks),
            "checks_passed": len(checks) - len(failed),
            "live_checked": any(c["live"] for c in checks),
            "message": self._message(status, checks, failed),
        }

    # ---- internals -----------------------------------------------------
    def _run_check(self, name, entries):
        problems, live = [], False
        try:
            for entry in entries:
                problems.extend(_static_problems(entry))
            live_problems, live = self._live_problems(name)
            problems.extend(live_problems)
        except Exception as exc:  # a probe that blows up is a failed check
            problems.append(f"health probe raised {type(exc).__name__}: {exc}")
        if problems:
            return {"name": name, "status": STATUS_FAILED, "detail": "; ".join(problems),
                    "problems": problems, "live": live}
        detail = "Available and connected." if live else "Available (static checks only; no live service supplied)."
        return {"name": name, "status": STATUS_HEALTHY, "detail": detail, "problems": [], "live": live}

    def _expect(self, service, module_name, class_name, label):
        cls = _class_named(module_name, class_name)
        if cls is None or not isinstance(service, cls):
            return [f"the supplied {label} is not a {class_name}"]
        return []

    def _live_problems(self, name):
        """(problems, live) for the live service(s) behind check `name`.
        Read-only lookups only."""
        if name == "versioning" and self.version_system is not None:
            problems = self._expect(self.version_system, "self_upgrade.version_system",
                                    "VersionSystem", "version system")
            if not problems and not self.version_system.current_version():
                problems.append("the version system has no active version recorded")
            return problems, True

        if name in ("human_approval", "registration_approval") and self.approval_manager is not None:
            problems = self._expect(self.approval_manager, "self_upgrade.capability_approval_manager",
                                    "ApprovalManager", "approval manager")
            if not problems and self.approval_manager.get_stored_record(_PROBE_ID) is not None:
                problems.append("the approval manager returned a record for a probe id that must not exist")
            return problems, True

        if name in ("registration", "registration_verification") and self.capability_system is not None:
            problems = self._expect(self.capability_system, "capabilities.capability_system",
                                    "CapabilitySystem", "capability system")
            if not problems and not isinstance(self.capability_system.all(), list):
                problems.append("the capability system did not list its registry")
            return problems, True

        if name == "execution_context_persistence" and self.context_store is not None:
            problems = self._expect(self.context_store, "self_upgrade.self_upgrade_execution_context",
                                    "SelfUpgradeExecutionContextStore", "execution context store")
            if not problems and self.context_store.load(_PROBE_ID) is not None:
                problems.append("the context store returned a context for a probe id that must not exist")
            return problems, True

        if name == "lifecycle_coordinator" and self.coordinator is not None:
            problems = self._expect(self.coordinator, "self_upgrade.self_upgrade_lifecycle_coordinator",
                                    "SelfUpgradeLifecycleCoordinator", "coordinator")
            if (not problems and self.approval_manager is not None
                    and getattr(self.coordinator, "approval_manager", None) is not self.approval_manager):
                problems.append("the coordinator is wired to a different ApprovalManager")
            return problems, True

        if name == "resume_support" and self.resume_manager is not None:
            problems = self._expect(self.resume_manager, "self_upgrade.self_upgrade_resume_manager",
                                    "SelfUpgradeResumeManager", "resume manager")
            if not problems and self.coordinator is not None \
                    and getattr(self.resume_manager, "coordinator", None) is not self.coordinator:
                problems.append("the resume manager is wired to a different coordinator")
            if not problems and self.context_store is not None \
                    and getattr(self.resume_manager, "store", None) is not self.context_store:
                problems.append("the resume manager is wired to a different context store")
            return problems, True

        return [], False

    @staticmethod
    def _message(status, checks, failed):
        total = len(checks)
        if status == STATUS_HEALTHY:
            live = sum(1 for c in checks if c["live"])
            scope = "static and live checks" if live else "static checks only, no live services supplied"
            return (f"All {total} Self-Upgrade components are available and connected ({scope}). "
                    "Nothing was created, changed, approved, registered, or activated.")
        by_name = {c["name"]: c for c in checks}
        parts = [f"{name} ({by_name[name]['detail']})" for name in failed]
        if status == STATUS_DEGRADED:
            lead = f"1 of {total} Self-Upgrade components failed its check"
        else:
            lead = f"{len(failed)} of {total} Self-Upgrade components failed their checks"
        return (f"{lead}: " + "; ".join(parts) + ". The lifecycle cannot pass the affected stage(s) "
                "until repaired. Read-only: nothing was repaired, retried, or changed.")
