"""
Self-Builder - the controlled build pipeline
============================================
One request, one auditable run through fixed stages:

  request -> analyze -> check_capabilities -> identify_gap -> plan
          -> generate -> validate -> test
          -> [analyze_failure -> repair -> retest]*            (bounded)
          -> checkpoint -> apply -> persist -> register -> version -> audit

Guarantees
----------
* Only files allowed by `policy` are created, only inside the Self-Builder
  root, only through `Workspace`; generated code is template-instantiated from
  a validated spec, AST-validated, loaded under the sandbox rules and must pass
  its differential test suite BEFORE anything is promoted.
* The registry/database commit is the single point of activation. A build that
  fails at any earlier point leaves the previous version active (nothing is
  promoted, staged files are removed, the failure is logged with its stages,
  attempts and error code). Files that were promoted but not registered
  (crash) are quarantined by the next reconciliation.
* A new version never overwrites an old one: every version keeps its own
  module/test/spec files, so `rollback()` can restore the previous healthy
  version after verifying it (hashes, validation, its own tests).
* Every run - applied, no-op, needs-confirmation, failed, rollback - has an
  `upgrade_log` row and hash-chained audit entries; every applied version
  records its request, plan, changes, validation, tests, parent version and
  checkpoint.

The builder returns plain dicts; wording for the user lives in the Persian
conversation layer, which maps the stable status/error codes below.
"""

import json
import threading
import time

from . import loader, policy, repair, request_parser, sandbox, spec as spec_mod, templates
from . import validator
from . import expr as expr_mod
from . import fa_text
from .errors import ApplyError, ExprError, SelfBuilderError, SpecError, ValidationError
from .policy import Policy
from .registry import (CAP_ACTIVE, CAP_DISABLED, Registry, VER_ACTIVE, VER_BROKEN, VER_ROLLED_BACK,
                       VER_SUPERSEDED)
from .store import dumps, now_iso

ST_APPLIED = "applied"
ST_NOOP = "noop_identical"
ST_CONFIRM = "needs_confirmation"
ST_FAILED = "failed"

DEVIATION_CONFIRM_THRESHOLD = 1e-3   # relative; a user factor further from the unit table than this is confirmed first


def _final_names(capability_id, version):
    return {"module": f"{capability_id}_v{int(version)}.py",
            "tests": f"{capability_id}_v{int(version)}.json",
            "spec": f"{capability_id}_v{int(version)}.json"}


def _staged_names(capability_id, version):
    base = f"stg_{capability_id}_v{int(version)}"
    return {"module": base + ".py", "tests": base + "_tests.json", "spec": base + "_spec.json"}


def _safe_slots(slots):
    out = {}
    for k, v in (slots or {}).items():
        out[k] = v[:200] if isinstance(v, str) else v
    return out


def _diff(prev_spec, spec):
    """Behaviour fields that differ between two specs of the same capability."""
    if not prev_spec:
        return []
    kind = spec["kind"]
    if kind == policy.ARCHETYPE_UNIT_CONVERSION:
        pairs = [("scale", prev_spec.get("scale"), spec["scale"]), ("shift", prev_spec.get("shift"), spec["shift"])]
    elif kind == policy.ARCHETYPE_FORMULA:
        pairs = [("expression", prev_spec.get("expression"), spec["expression"]),
                 ("variables", [v["name"] for v in prev_spec.get("variables", [])],
                  [v["name"] for v in spec["variables"]])]
    else:
        pairs = [("ops", prev_spec.get("ops"), spec["ops"])]
    return [{"field": f, "old": old, "new": new} for f, old, new in pairs if old != new]


class _Ctx:
    """Everything one build run records (and finally persists)."""

    def __init__(self, request_text, request, confirmed):
        self.request_text = (request_text or "")[:policy.MAX_REQUEST_CHARS]
        self.request = request
        self.confirmed = bool(confirmed)
        self.stages = []
        self.attempts = []
        self.repairs = []
        self.guess_repairs = []
        self.upgrade_id = None
        self.plan = None
        self.spec = None
        self.started = time.perf_counter()
        self.formula_examples = None  # the examples as first built (positional ones may be re-ordered)

    def stage(self, name, ok=True, **detail):
        self.stages.append({"stage": name, "ok": bool(ok), "detail": detail})

    def duration_ms(self):
        return round((time.perf_counter() - self.started) * 1000, 3)


class Builder:
    def __init__(self, workspace, store, registry=None):
        self.ws = workspace
        self.store = store
        self.registry = registry or Registry(store)
        self._lock = threading.RLock()

    # ================================================================ logging
    def _log_start(self, kind, capability_id, request_text):
        with self.store.transaction():
            cur = self.store.execute(
                "INSERT INTO upgrade_log(kind, capability_id, request_text, plan_json, changes_json, attempts_json, "
                "validation_json, test_json, result, version, rollback_json, error_code, error_detail, created_at, "
                "finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (kind, capability_id, request_text, "{}", "{}", "[]", "{}", "{}", "started", None, None, None, None,
                 now_iso(), None))
            upgrade_id = cur.lastrowid
            self.store.audit("upgrade_started", capability_id, None, upgrade_id, {"kind": kind})
        return upgrade_id

    def _write_upgrade_row(self, ctx, result, version=None, capability_id=None, changes=None, validation=None,
                           tests=None, rollback=None, error=None):
        with self.store.transaction():
            self.store.execute(
                "UPDATE upgrade_log SET capability_id = COALESCE(?, capability_id), plan_json = ?, changes_json = ?, "
                "attempts_json = ?, validation_json = ?, test_json = ?, result = ?, version = ?, rollback_json = ?, "
                "error_code = ?, error_detail = ?, finished_at = ? WHERE upgrade_id = ?",
                (capability_id, dumps(ctx.plan or {}), dumps(changes or {}),
                 dumps({"stages": ctx.stages, "attempts": ctx.attempts, "repairs": ctx.repairs}),
                 dumps(validation or {}), dumps(tests or {}), result, version,
                 dumps(rollback) if rollback is not None else None,
                 error.get("code") if error else None, (error.get("detail") or "")[:500] if error else None,
                 now_iso(), ctx.upgrade_id))

    def _note_repair(self, ctx, outcome):
        entry = outcome.to_dict()
        ctx.repairs.append(entry)
        if outcome.risk == "guess":
            ctx.guess_repairs.append(entry)
        ctx.attempts.append({"attempt": len(ctx.attempts) + 1, "stage": "repair", "ok": True,
                             "repair": outcome.repair_id, "risk": outcome.risk})
        ctx.stage("repair", repair=outcome.repair_id, risk=outcome.risk, before=outcome.before[:120],
                  after=outcome.after[:120], note=outcome.note_fa)

    # ================================================================== build
    def build(self, request_text, request, confirmed=False):
        """Run one build request (a READY `request_parser.BuildRequest`).

        The whole run holds the workspace lock (lock.py): no other build,
        rollback or start-up clean-up - in this process or another - touches
        the staging directory or the registry meanwhile."""
        with self._lock:
            try:
                with self.ws.lock.held():
                    return self._build_attempts(request_text, request, confirmed)
            except SelfBuilderError as e:          # only "the lock stayed busy" can get out of the loop below
                return self._fail(_Ctx(request_text, request, confirmed), e)

    def _build_attempts(self, request_text, request, confirmed):
        for attempt in (1, 2):
            ctx = _Ctx(request_text, request, confirmed)
            try:
                return self._build_locked(ctx)
            except SelfBuilderError as e:
                failed = self._fail(ctx, e)
                # the capability changed under a build that did not hold the lock: look again, once
                if e.code == "E_BUILD_CONFLICT" and attempt == 1:
                    continue
                return failed
            except Exception as e:  # never let an unexpected fault escape half-applied
                return self._fail(ctx, ApplyError(type(e).__name__, code="E_BUILD_INTERNAL"))

    def _build_locked(self, ctx):
        req = ctx.request
        ctx.upgrade_id = self._log_start("build", None, ctx.request_text)
        ctx.stage("request", text=ctx.request_text[:160], status=req.status, kind=req.kind,
                  confirmed=ctx.confirmed)
        if req.status != request_parser.STATUS_READY:
            raise SpecError("the request is incomplete", code="E_BUILD_NOT_READY", missing=list(req.missing))
        Policy.check_archetype(req.kind)
        ctx.stage("analyze", kind=req.kind, slots=_safe_slots(req.slots))

        spec = self._spec_from_request(ctx)
        ctx.spec = spec
        cid = spec["capability_id"]
        existing = self.registry.get(cid)
        active_row = self.registry.active_version_row(cid) if existing else None
        fingerprint = spec_mod.spec_fingerprint(spec)

        if active_row is not None and existing["status"] == CAP_ACTIVE and active_row["fingerprint"] == fingerprint:
            ctx.stage("check_capabilities", exists=True, identical=True, version=active_row["version"])
            return self._finish_noop(ctx, spec, active_row)
        ctx.stage("check_capabilities", exists=existing is not None, identical=False,
                  active_version=active_row["version"] if active_row else None)

        if existing is None and self.registry.count() >= policy.MAX_CAPABILITIES:
            raise ApplyError("capability limit reached", code="E_BUILD_LIMIT_CAPABILITIES",
                             limit=policy.MAX_CAPABILITIES)
        if existing is not None and existing["latest_version"] >= policy.MAX_VERSIONS_PER_CAPABILITY:
            raise ApplyError("version limit reached", code="E_BUILD_LIMIT_VERSIONS",
                             limit=policy.MAX_VERSIONS_PER_CAPABILITY)

        deviation = self._factor_deviation(spec)
        if deviation is not None and deviation["relative"] > DEVIATION_CONFIRM_THRESHOLD and not ctx.confirmed:
            return self._finish_confirm(ctx, spec, "factor_deviation", deviation)

        action = "improve" if existing is not None and active_row is not None else "create"
        version = (existing["latest_version"] if existing else 0) + 1
        previous_version = active_row["version"] if active_row else None
        changes = _diff(active_row["spec"] if active_row else None, spec)
        ctx.stage("identify_gap", missing=active_row is None,
                  reason=("no active capability with this identity" if active_row is None
                          else "the active version behaves differently from the request"),
                  capability=spec["title"])
        final = _final_names(cid, version)
        ctx.plan = {
            "action": action, "capability_id": cid, "kind": spec["kind"], "title": spec["title"],
            "from_version": previous_version, "to_version": version, "changes": changes,
            "files": [{"role": "module", "dir": policy.SUBDIR_MODULES, "name": final["module"]},
                      {"role": "tests", "dir": policy.SUBDIR_TESTS, "name": final["tests"]},
                      {"role": "spec", "dir": policy.SUBDIR_SPECS, "name": final["spec"]}],
            "registry": {"register": cid, "activate": version, "supersede": previous_version},
            "validation": ["spec", "ast_allowlist", "sandbox_load", "differential_tests"],
            "rollback": {"restore_version": previous_version, "checkpoint": True},
        }
        ctx.stage("plan", action=action, capability_id=cid, from_version=previous_version, to_version=version,
                  files=[f["name"] for f in ctx.plan["files"]])
        with self.store.transaction():
            self.store.execute("UPDATE upgrade_log SET capability_id = ?, plan_json = ? WHERE upgrade_id = ?",
                               (cid, dumps(ctx.plan), ctx.upgrade_id))

        spec, artefacts, validation, tests = self._generate_validate_test(ctx, spec, version)
        ctx.spec = spec

        # a reorder repair may have turned the request into exactly the active behaviour
        if active_row is not None and active_row["fingerprint"] == spec_mod.spec_fingerprint(spec) \
                and existing["status"] == CAP_ACTIVE:
            self.ws.clear_staging()
            return self._finish_noop(ctx, spec, active_row)

        if ctx.guess_repairs and not ctx.confirmed:
            verified = any(c.get("source") == "user" for c in artefacts["suite"]["cases"]) and tests["ok"]
            if not verified:
                self.ws.clear_staging()
                return self._finish_confirm(ctx, spec, "guess_repair", {
                    "interpretation": spec["expression"] if spec["kind"] == policy.ARCHETYPE_FORMULA else None,
                    "repairs": list(ctx.guess_repairs)})

        return self._apply(ctx, spec, version, artefacts, validation, tests, existing, active_row, action, changes)

    # ----------------------------------------------------------------- specs
    def _factor_deviation(self, spec):
        if spec["kind"] != policy.ARCHETYPE_UNIT_CONVERSION or spec.get("standard") or not spec.get("reference"):
            return None
        ref = spec["reference"]["scale"]
        rel = abs(spec["scale"] - ref) / abs(ref)
        return {"table_scale": ref, "user_scale": spec["scale"], "relative": rel}

    def _spec_from_request(self, ctx):
        req = ctx.request
        kw = request_parser.assemble_spec_inputs(req)
        if req.kind == policy.ARCHETYPE_UNIT_CONVERSION:
            spec = spec_mod.unit_conversion_spec(kw["from_unit"], kw["to_unit"], kw["from_name"], kw["to_name"],
                                                 kw["factor"], kw["examples"])
        elif req.kind == policy.ARCHETYPE_TEXT_TOOL:
            spec = spec_mod.text_tool_spec(kw["ops"])
        else:
            spec = self._formula_spec(ctx, kw)
        ctx.stage("spec", ok=True, spec_kind=spec["kind"], capability_id=spec["capability_id"],
                  title=spec["title"], fingerprint=spec_mod.spec_fingerprint(spec)[:16])
        return spec

    def _formula_spec(self, ctx, kw):
        """Strict parse with bounded, classified repair of the user's notation."""
        title = kw["title"]
        text = kw["expression"]
        labels = {}
        applied = []
        while True:
            try:
                tree = expr_mod.parse(text)
                break
            except ExprError as e:
                ctx.attempts.append({"attempt": len(ctx.attempts) + 1, "stage": "parse", "ok": False,
                                     "error": e.code, "text": text[:160]})
                ctx.stage("analyze_failure", ok=False, source="parse", code=e.code, text=text[:120])
                if len(applied) >= policy.MAX_REPAIR_ATTEMPTS:
                    raise
                outcome = repair.next_expression_repair(e.code, text, labels, applied)
                if outcome is None:
                    raise
                applied.append(outcome.repair_id)
                self._note_repair(ctx, outcome)
                text, labels = outcome.after, dict(outcome.labels or {})
        names = expr_mod.variables(tree)
        aliases = {n: [k for k in (fa_text.key(labels.get(n, n)), fa_text.key(n)) if k] for n in names}
        examples = []
        example = request_parser.parse_formula_example(kw.get("example_text"), names, aliases)
        if example is not None:
            item = {"expected": example["expected"], "tolerance": example["tolerance"]}
            if example["inputs"] is not None:
                item["inputs"] = example["inputs"]
            else:
                item["inputs"] = {}
                item["positional"] = example["positional"]
            examples.append(item)
        ctx.formula_examples = examples
        return spec_mod.formula_spec(title, text, labels, examples)

    def _repair_reorder(self, ctx, spec):
        """Test-driven repair: a user example given positionally only fits a
        different variable order. Verified by the example itself."""
        examples = ctx.formula_examples or []
        positional = [e for e in examples if e.get("positional") is not None]
        names = [v["name"] for v in spec["variables"]]
        if len(names) < 2 or not positional:
            return None
        labels = {v["name"]: v["label"] for v in spec["variables"]}
        for perm in repair.reorder_candidates(len(names)):
            order = [names[i] for i in perm]
            try:
                candidate = spec_mod.formula_spec(spec["title"], spec["expression"], labels, examples,
                                                  variable_order=order)
            except SelfBuilderError:
                continue
            fits = True
            for ex in candidate["examples"]:
                ref = templates.reference_result(candidate, ex["inputs"])
                tol = float(ex.get("tolerance") or 1e-9)
                ok, _ = templates.check_expectation({"value": float(ex["expected"]), "abs_tol": tol},
                                                    ref.get("value"), ref.get("error"))
                if not ok:
                    fits = False
                    break
            if fits:
                outcome = repair.RepairOutcome(
                    "reorder_variables", "guess", ", ".join(names), ", ".join(order),
                    labels, repair.repair_note_reorder([labels.get(n, n) for n in order]))
                self._note_repair(ctx, outcome)
                ctx.guess_repairs.pop()  # verified by the user's own example: not an unverified guess
                return candidate
        return None

    # ------------------------------------------------- generate / validate / test
    def _generate_validate_test(self, ctx, spec, version):
        reordered = False
        for round_no in range(policy.MAX_REPAIR_ATTEMPTS + 1):
            artefacts = self._stage_files(ctx, spec, version)
            validation = self._validate(ctx, spec, version, artefacts)
            stage_name = "retest" if round_no else "test"
            tests = self._run_tests(ctx, spec, version, artefacts, stage_name)
            ctx.attempts.append({"attempt": len(ctx.attempts) + 1, "stage": stage_name, "ok": tests["ok"],
                                 "total": tests["total"], "passed": tests["passed"]})
            if tests["ok"]:
                return spec, artefacts, validation, tests
            cls = repair.classify_test_failures(tests)
            ctx.stage("analyze_failure", ok=False, source="tests", failure_class=cls["class"],
                      failed=cls["names"][:10])
            candidate = None
            if cls["class"] == "example_mismatch" and spec["kind"] == policy.ARCHETYPE_FORMULA and not reordered:
                candidate = self._repair_reorder(ctx, spec)
                reordered = True
            if candidate is None:
                raise ValidationError("the generated capability failed its tests", code="E_BUILD_TESTS_FAILED",
                                      failure_class=cls["class"], failed=cls["names"][:10],
                                      cases=[{"name": f["name"], "reason": f["reason"], "inputs": f["inputs"],
                                              "source": f["source"]} for f in tests["failed"][:5]])
            spec = candidate
        raise ValidationError("repair attempts exhausted", code="E_BUILD_TESTS_FAILED", failure_class="exhausted")

    def _stage_files(self, ctx, spec, version):
        cid = spec["capability_id"]
        Policy.check_operation(policy.OP_STAGE)
        source = templates.generate_module(spec, version)
        suite = templates.generate_test_suite(spec, version)
        suite_text = json.dumps(suite, ensure_ascii=False, sort_keys=True, indent=1)
        spec_text = spec_mod.canonical_json(spec)
        names = _staged_names(cid, version)
        self.ws.write(policy.SUBDIR_STAGING, names["module"], source, policy.OP_STAGE)
        self.ws.write(policy.SUBDIR_STAGING, names["tests"], suite_text, policy.OP_STAGE)
        self.ws.write(policy.SUBDIR_STAGING, names["spec"], spec_text, policy.OP_STAGE)
        ctx.stage("generate", files=list(names.values()), module_bytes=len(source), test_cases=len(suite["cases"]))
        return {"source": source, "suite": suite, "suite_text": suite_text, "spec_text": spec_text,
                "staged": names, "source_sha256": sandbox.sha256_bytes(source.encode("ascii"))}

    def _validate(self, ctx, spec, version, art):
        spec_mod.validate_spec(spec)
        report = validator.check_source(art["source"], spec["kind"], spec["capability_id"], version)
        ctx.stage("validate", ok=report.ok, violations=len(report.violations), nodes=report.stats.get("nodes"))
        if not report.ok:
            raise ValidationError("the generated module was rejected by the validator", code="E_BUILD_VALIDATION",
                                  violations=report.violations[:10])
        return {"ok": True, "validator": "ast-allowlist", "violations": [], "stats": report.stats,
                "source_sha256": art["source_sha256"], "spec_valid": True, "checked_at": now_iso()}

    def _run_tests(self, ctx, spec, version, art, stage_name):
        cid = spec["capability_id"]
        loaded = sandbox.load_module(self.ws.root, policy.SUBDIR_STAGING, art["staged"]["module"], spec["kind"],
                                     cid, version, expected_sha256=art["source_sha256"])
        suite = json.loads(self.ws.read(policy.SUBDIR_STAGING, art["staged"]["tests"]).decode("utf-8"))
        result = sandbox.run_suite(loaded, suite)
        result["suite_sha256"] = sandbox.sha256_bytes(art["suite_text"].encode("utf-8"))
        ctx.stage(stage_name, ok=result["ok"], total=result["total"], passed=result["passed"],
                  failed=[f["name"] for f in result["failed"]][:10])
        return result

    # ----------------------------------------------------------- apply & persist
    def _checkpoint(self, ctx, spec, version, existing, active_row):
        Policy.check_operation(policy.OP_SNAPSHOT)
        cid = spec["capability_id"]
        files = []
        if active_row is not None:
            for role, sub, name_key, sha_key in (("module", policy.SUBDIR_MODULES, "module_file", "module_sha256"),
                                                 ("tests", policy.SUBDIR_TESTS, "tests_file", "tests_sha256"),
                                                 ("spec", policy.SUBDIR_SPECS, "spec_file", "spec_sha256")):
                files.append({"role": role, "dir": sub, "name": active_row[name_key], "sha256": active_row[sha_key]})
        registry_before = {
            "capability": None if existing is None else {
                "id": existing["id"], "status": existing["status"], "active_version": existing["version"],
                "latest_version": existing["latest_version"]},
            "versions": [] if existing is None else existing["versions"],
        }
        with self.store.transaction():
            cur = self.store.execute(
                "INSERT INTO checkpoints(upgrade_id, capability_id, from_version, to_version, files_json, "
                "registry_json, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (ctx.upgrade_id, cid, active_row["version"] if active_row else None, version, dumps(files),
                 dumps(registry_before), "pending", now_iso()))
            ck_id = cur.lastrowid
            self.store.audit("checkpoint_created", cid, version, ctx.upgrade_id,
                             {"checkpoint_id": ck_id, "from_version": active_row["version"] if active_row else None})
        self.ws.write(policy.SUBDIR_CHECKPOINTS, f"ck_{ck_id}.json",
                      json.dumps({"checkpoint_id": ck_id, "upgrade_id": ctx.upgrade_id, "capability_id": cid,
                                  "from_version": active_row["version"] if active_row else None,
                                  "to_version": version, "files": files, "registry": registry_before},
                                 ensure_ascii=False, sort_keys=True, indent=1), policy.OP_SNAPSHOT)
        ctx.stage("checkpoint", checkpoint_id=ck_id, from_version=active_row["version"] if active_row else None,
                  files=len(files))
        return ck_id

    def _promote(self, role, staged_name, final_name, promoted):
        sub = {"module": policy.SUBDIR_MODULES, "tests": policy.SUBDIR_TESTS, "spec": policy.SUBDIR_SPECS}[role]
        op = {"module": policy.OP_CREATE_MODULE, "tests": policy.OP_CREATE_TESTS, "spec": policy.OP_CREATE_SPEC}[role]
        if self.ws.exists(sub, final_name):
            # the registry says this version does not exist: whatever is there is an unregistered leftover
            self.ws.quarantine(sub, final_name, "stale")
        self.ws.move(policy.SUBDIR_STAGING, staged_name, sub, final_name, op)
        promoted.append((sub, final_name))

    def _apply(self, ctx, spec, version, art, validation, tests, existing, active_row, action, changes):
        cid = spec["capability_id"]
        ck_id = self._checkpoint(ctx, spec, version, existing, active_row)
        final = _final_names(cid, version)
        promoted = []
        try:
            # The database write lock is taken BEFORE any file moves: a second process that builds the same
            # capability waits here, then notices the version number it planned is gone and starts over.
            with self.store.transaction():
                latest = self.store.query_one("SELECT latest_version FROM capabilities WHERE capability_id = ?", (cid,))
                if (latest["latest_version"] if latest else 0) != version - 1:
                    raise ApplyError("the capability changed while this build was running", code="E_BUILD_CONFLICT",
                                     planned_version=version)
                for role in ("module", "tests", "spec"):
                    self._promote(role, art["staged"][role], final[role], promoted)
                # verify the promoted files exactly as a later restart would
                row_probe = {"capability_id": cid, "version": version, "module_file": final["module"],
                             "module_sha256": art["source_sha256"], "tests_file": final["tests"],
                             "tests_sha256": sandbox.sha256_bytes(art["suite_text"].encode("utf-8")),
                             "spec_file": final["spec"], "spec_sha256": sandbox.sha256_bytes(art["spec_text"].encode("utf-8")),
                             "fingerprint": spec_mod.spec_fingerprint(spec)}
                ok, info = loader.verify_version(self.ws, row_probe)
                ctx.stage("apply", ok=ok, promoted=[n for _, n in promoted], verified=ok)
                if not ok:
                    raise ApplyError("the promoted files failed verification", code="E_BUILD_APPLY_VERIFY",
                                     verify=info)
                Policy.check_operation(policy.OP_REGISTER)
                ts = now_iso()
                with self.store.transaction():
                    self.store.execute(
                        "INSERT INTO capability_versions(capability_id, version, fingerprint, spec_json, spec_file, "
                        "spec_sha256, module_file, module_sha256, tests_file, tests_sha256, inputs_json, outputs_json, "
                        "dependencies_json, permissions_json, validation_json, test_report_json, status, parent_version, "
                        "upgrade_id, checkpoint_id, rollback_json, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (cid, version, row_probe["fingerprint"], art["spec_text"], final["spec"], row_probe["spec_sha256"],
                         final["module"], row_probe["module_sha256"], final["tests"], row_probe["tests_sha256"],
                         dumps(spec["inputs"]), dumps(spec["outputs"]), dumps(spec["dependencies"]),
                         dumps(spec["permissions"]), dumps(validation), dumps(tests), VER_ACTIVE,
                         active_row["version"] if active_row else None, ctx.upgrade_id, ck_id,
                         dumps({"previous_version": active_row["version"] if active_row else None,
                                "checkpoint_id": ck_id, "restore": "previous version files are kept"}), ts))
                    ctx.stage("persist", ok=True, version=version, tables=["capability_versions"])
                    if existing is None:
                        self.store.execute(
                            "INSERT INTO capabilities(capability_id, kind, title, description, status, active_version, "
                            "latest_version, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                            (cid, spec["kind"], spec["title"], spec["description"], CAP_ACTIVE, version, version, ts, ts))
                    else:
                        self.store.execute(
                            "UPDATE capabilities SET title = ?, description = ?, status = ?, active_version = ?, "
                            "latest_version = ?, updated_at = ? WHERE capability_id = ?",
                            (spec["title"], spec["description"], CAP_ACTIVE, version, version, ts, cid))
                        if active_row is not None:
                            self.store.execute(
                                "UPDATE capability_versions SET status = ? WHERE capability_id = ? AND version = ?",
                                (VER_SUPERSEDED, cid, active_row["version"]))
                    ctx.stage("register", ok=True, capability_id=cid, status=CAP_ACTIVE, active_version=version)
                    ctx.stage("version", ok=True, version=version, parent_version=active_row["version"] if active_row else None)
                    self.store.execute("UPDATE checkpoints SET status = 'applied' WHERE checkpoint_id = ?", (ck_id,))
                    self.store.audit("capability_registered" if action == "create" else "capability_upgraded", cid,
                                     version, ctx.upgrade_id,
                                     {"kind": spec["kind"], "title": spec["title"], "action": action,
                                      "previous_version": active_row["version"] if active_row else None,
                                      "module_sha256": row_probe["module_sha256"], "tests": f"{tests['passed']}/{tests['total']}"})
                    ctx.stage("audit", ok=True, events=["upgrade_applied", "capability_registered" if action == "create"
                                                        else "capability_upgraded"])
                    self._write_upgrade_row(
                        ctx, "applied", version=version, capability_id=cid, changes={
                            "action": action, "created_files": [final["module"], final["tests"], final["spec"]],
                            "fields": changes, "checkpoint_id": ck_id},
                        validation=validation, tests=tests,
                        rollback={"previous_version": active_row["version"] if active_row else None,
                                  "checkpoint_id": ck_id})
                    self.store.audit("upgrade_applied", cid, version, ctx.upgrade_id,
                                     {"action": action, "duration_ms": ctx.duration_ms()})
        except BaseException:
            for sub, name in promoted:
                try:
                    self.ws.quarantine(sub, name, "unregistered")
                except Exception:
                    pass
            try:
                with self.store.transaction():
                    self.store.execute("UPDATE checkpoints SET status = 'abandoned' WHERE checkpoint_id = ?",
                                       (ck_id,))
            except Exception:
                pass
            raise
        self.ws.clear_staging()
        loader.write_manifest(self.ws, self.store, self.registry)
        return self._result(ctx, ST_APPLIED, spec, version=version, action=action,
                            previous_version=active_row["version"] if active_row else None,
                            tests=tests, validation=validation, changes=changes, checkpoint_id=ck_id)

    # ----------------------------------------------------------------- results
    def _result(self, ctx, status, spec=None, **extra):
        spec = spec or ctx.spec or {}
        result = {
            "status": status,
            "capability_id": spec.get("capability_id"), "kind": spec.get("kind"), "title": spec.get("title"),
            "upgrade_id": ctx.upgrade_id, "request_text": ctx.request_text,
            "stages": ctx.stages, "attempts": ctx.attempts, "repairs": ctx.repairs,
            "duration_ms": ctx.duration_ms(), "error": None, "confirmation": None,
        }
        result.update(extra)
        return result

    def _finish_noop(self, ctx, spec, active_row):
        ctx.stage("identify_gap", missing=False, reason="an identical capability is already active",
                  capability=spec["title"])
        with self.store.transaction():
            self.store.audit("noop_identical", spec["capability_id"], active_row["version"], ctx.upgrade_id, {})
        self._write_upgrade_row(ctx, "noop", version=active_row["version"], capability_id=spec["capability_id"])
        return self._result(ctx, ST_NOOP, spec, version=active_row["version"], action="noop",
                            previous_version=active_row["version"])

    def _finish_confirm(self, ctx, spec, reason, details):
        ctx.stage("check_capabilities", ok=True, needs_confirmation=reason)
        with self.store.transaction():
            self.store.audit("needs_confirmation", spec["capability_id"], None, ctx.upgrade_id, {"reason": reason})
        self._write_upgrade_row(ctx, "needs_confirmation", capability_id=spec["capability_id"],
                                error={"code": "E_BUILD_CONFIRM_" + reason.upper(), "detail": reason})
        return self._result(ctx, ST_CONFIRM, spec, confirmation={"reason": reason, "details": details})

    def _fail(self, ctx, error):
        """Nothing was activated: clear staging (only while this thread holds the workspace lock - the
        staging directory may belong to a build that is running elsewhere), log the failure, report it."""
        try:
            if self.ws.lock.held_here():
                self.ws.clear_staging()
        except Exception:
            pass
        cid = (ctx.spec or {}).get("capability_id")
        err = {"code": error.code, "detail": error.detail, "info": _json_safe(error.info)}
        try:
            if ctx.upgrade_id is None:
                ctx.upgrade_id = self._log_start("build", cid, ctx.request_text)
            ctx.stage("audit", ok=False, event="upgrade_failed", code=error.code)
            with self.store.transaction():
                self.store.audit("upgrade_failed", cid, None, ctx.upgrade_id,
                                 {"code": error.code, "detail": (error.detail or "")[:200]})
            self._write_upgrade_row(ctx, "failed", capability_id=cid, error=err)
        except Exception:
            pass
        active = self.registry.active_version_row(cid) if cid else None
        res = self._result(ctx, ST_FAILED, ctx.spec, error=err,
                           active_version=active["version"] if active else None)
        return res

    # =================================================================== rollback
    def rollback(self, capability_id, to_version=None, reason="user_request", current_status=VER_ROLLED_BACK):
        """Restore the newest healthy older version (or `to_version`) after
        verifying it. Returns a result dict (status applied | failed).
        `current_status`: what the version being left is marked as
        (`rolled_back`; `broken` after an integrity failure)."""
        with self._lock:
            ctx = _Ctx(f"rollback {capability_id}", None, True)
            try:
                with self.ws.lock.held():
                    ctx.upgrade_id = self._log_start("rollback", capability_id, ctx.request_text)
                    try:
                        return self._rollback_locked(ctx, capability_id, to_version, reason, current_status)
                    except SelfBuilderError as e:
                        return self._fail_rollback(ctx, capability_id, e)
                    except Exception as e:
                        return self._fail_rollback(ctx, capability_id,
                                                   ApplyError(type(e).__name__, code="E_ROLLBACK_INTERNAL"))
            except SelfBuilderError as e:                 # the workspace lock stayed busy
                return self._fail_rollback(ctx, capability_id, e)

    def _rollback_locked(self, ctx, cid, to_version, reason, current_status=VER_ROLLED_BACK):
        Policy.check_capability_id(cid)
        ctx.stage("request", kind="rollback", capability_id=cid, to_version=to_version, reason=reason)
        cap = self.registry.get(cid)
        if cap is None:
            raise ApplyError("unknown capability", code="E_ROLLBACK_UNKNOWN", capability_id=cid)
        if cap["version"] is None:
            raise ApplyError("capability has no active version", code="E_ROLLBACK_NOT_ACTIVE")
        current = cap["version"]
        ctx.stage("check_capabilities", exists=True, active_version=current,
                  versions=[(v["version"], v["status"]) for v in cap["versions"]])
        if to_version is not None:
            candidates = [v for v in self.registry.versions(cid) if v["version"] == int(to_version)]
            if not candidates or candidates[0]["status"] not in (VER_SUPERSEDED, VER_ACTIVE, VER_ROLLED_BACK) \
                    or candidates[0]["version"] == current:
                raise ApplyError("that version cannot be restored", code="E_ROLLBACK_BAD_TARGET",
                                 version=to_version)
        else:
            candidates = sorted((v for v in self.registry.versions(cid)
                                 if v["version"] < current and v["status"] in (VER_SUPERSEDED, VER_ACTIVE)),
                                key=lambda v: -v["version"])
        Policy.check_operation(policy.OP_RESTORE)
        target = None
        checks = []
        for cand in candidates:
            ok, info = loader.verify_version(self.ws, cand)
            checks.append({"version": cand["version"], "ok": ok, "error": None if ok else info.get("error"),
                           "tests": info.get("tests")})
            if ok:
                target = cand
                break
        ctx.stage("test", ok=target is not None, verify=checks, source="rollback_target")
        if target is None:
            raise ApplyError("there is no healthy earlier version to restore", code="E_ROLLBACK_NO_TARGET",
                             checks=checks, can_disable=True)
        ctx.plan = {"action": "rollback", "capability_id": cid, "from_version": current,
                    "to_version": target["version"], "reason": reason}
        left_status = current_status
        if current_status == VER_ROLLED_BACK and target["version"] > current:
            # going FORWARD again: the version that is left is merely older - it was never judged bad, so it
            # stays a valid target for "the previous version" (and for the start-up fallback)
            left_status = VER_SUPERSEDED
        with self.store.transaction():
            ts = now_iso()
            self.store.execute("UPDATE capability_versions SET status = ? WHERE capability_id = ? AND version = ?",
                               (left_status, cid, current))
            self.store.execute("UPDATE capability_versions SET status = ? WHERE capability_id = ? AND version = ?",
                               (VER_ACTIVE, cid, target["version"]))
            self.store.execute("UPDATE capabilities SET active_version = ?, status = ?, title = ?, description = ?, "
                               "updated_at = ? WHERE capability_id = ?",
                               (target["version"], CAP_ACTIVE, target["spec"].get("title", cap["title"]),
                                target["spec"].get("description", cap["description"]), ts, cid))
            ctx.stage("register", ok=True, capability_id=cid, active_version=target["version"])
            ctx.stage("audit", ok=True, event="rolled_back")
            self.store.audit("rolled_back", cid, target["version"], ctx.upgrade_id,
                             {"from_version": current, "to_version": target["version"], "reason": reason,
                              "verified_tests": target and checks[-1].get("tests")})
            self._write_upgrade_row(ctx, "applied", version=target["version"], capability_id=cid,
                                    changes={"action": "rollback", "from_version": current,
                                             "to_version": target["version"]},
                                    tests=checks[-1].get("tests") or {},
                                    rollback={"from_version": current, "to_version": target["version"],
                                              "verified": checks, "reason": reason})
        loader.write_manifest(self.ws, self.store, self.registry)
        return {"status": ST_APPLIED, "action": "rollback", "capability_id": cid, "title": cap["title"],
                "kind": cap["kind"], "version": target["version"], "from_version": current,
                "upgrade_id": ctx.upgrade_id, "stages": ctx.stages, "verified": checks, "error": None,
                "duration_ms": ctx.duration_ms()}

    def _fail_rollback(self, ctx, cid, error):
        err = {"code": error.code, "detail": error.detail, "info": _json_safe(error.info)}
        try:
            if ctx.upgrade_id is None:
                ctx.upgrade_id = self._log_start("rollback", cid, ctx.request_text)
            ctx.stage("audit", ok=False, event="rollback_failed", code=error.code)
            with self.store.transaction():
                self.store.audit("rollback_failed", cid, None, ctx.upgrade_id, {"code": error.code})
            self._write_upgrade_row(ctx, "failed", capability_id=cid, error=err)
        except Exception:
            pass
        cap = self.registry.get(cid) if cid else None
        return {"status": ST_FAILED, "action": "rollback", "capability_id": cid, "error": err,
                "upgrade_id": ctx.upgrade_id, "stages": ctx.stages,
                "active_version": cap["version"] if cap else None}

    def repair_integrity(self, capability_id, error_code):
        """The ACTIVE version failed verification at run time (file missing,
        modified, no longer valid). Evidence is quarantined, the version is
        marked `broken`, and the newest healthy older version is restored
        (or the capability is disabled when there is none)."""
        with self._lock:
            try:
                with self.ws.lock.held():
                    return self._repair_integrity_locked(capability_id, error_code)
            except SelfBuilderError as e:                 # the workspace lock stayed busy
                return self._busy_failure("repair", capability_id, e)

    def _busy_failure(self, action, capability_id, error):
        return {"status": ST_FAILED, "action": action, "capability_id": capability_id,
                "error": {"code": error.code, "detail": error.detail, "info": _json_safe(error.info)}}

    def _repair_integrity_locked(self, capability_id, error_code):
        cap = self.registry.get(capability_id)
        if cap is None or cap["version"] is None:
            return {"status": ST_FAILED, "action": "repair", "capability_id": capability_id,
                    "error": {"code": "E_REPAIR_NOT_ACTIVE", "detail": "no active version", "info": {}}}
        row = self.registry.version_row(capability_id, cap["version"])
        if error_code in ("E_VERIFY_MODULE_HASH", "E_VERIFY_LOAD", "E_SANDBOX_HASH", "E_VALIDATION"):
            try:
                self.ws.quarantine(policy.SUBDIR_MODULES, row["module_file"], "integrity")
            except Exception:
                pass
        with self.store.transaction():
            self.store.execute("UPDATE capability_versions SET status = ? WHERE capability_id = ? AND version = ?",
                               (VER_BROKEN, capability_id, row["version"]))
            self.store.audit("version_broken", capability_id, row["version"], None, {"error": error_code})
        result = self.rollback(capability_id, reason="integrity_failure:" + str(error_code),
                               current_status=VER_BROKEN)
        if result["status"] != ST_APPLIED:
            disabled = self.disable(capability_id, reason="integrity_failure:" + str(error_code))
            disabled["broken_version"] = row["version"]
            return disabled
        result["broken_version"] = row["version"]
        return result

    def disable(self, capability_id, reason="user_request"):
        """Deactivate a capability (its files and versions stay for a later re-build)."""
        with self._lock:
            Policy.check_capability_id(capability_id)
            try:
                with self.ws.lock.held():
                    return self._disable_locked(capability_id, reason)
            except SelfBuilderError as e:                 # the workspace lock stayed busy
                return self._busy_failure("disable", capability_id, e)

    def _disable_locked(self, capability_id, reason):
        cap = self.registry.get(capability_id)
        if cap is None or cap["version"] is None:
            return {"status": ST_FAILED, "action": "disable", "capability_id": capability_id,
                    "error": {"code": "E_DISABLE_NOT_ACTIVE", "detail": "no active version", "info": {}}}
        ctx = _Ctx(f"disable {capability_id}", None, True)
        ctx.upgrade_id = self._log_start("disable", capability_id, ctx.request_text)
        with self.store.transaction():
            ts = now_iso()
            self.store.execute("UPDATE capability_versions SET status = CASE WHEN status = ? THEN status ELSE ? END "
                               "WHERE capability_id = ? AND version = ?",
                               (VER_BROKEN, VER_ROLLED_BACK, capability_id, cap["version"]))
            self.store.execute("UPDATE capabilities SET active_version = NULL, status = ?, updated_at = ? "
                               "WHERE capability_id = ?", (CAP_DISABLED, ts, capability_id))
            ctx.stage("register", ok=True, capability_id=capability_id, status=CAP_DISABLED)
            self.store.audit("capability_disabled", capability_id, cap["version"], ctx.upgrade_id,
                             {"reason": reason})
            self._write_upgrade_row(ctx, "applied", version=cap["version"], capability_id=capability_id,
                                    changes={"action": "disable", "version": cap["version"]},
                                    rollback={"restore": "re-build the capability"})
        loader.write_manifest(self.ws, self.store, self.registry)
        return {"status": ST_APPLIED, "action": "disable", "capability_id": capability_id,
                "title": cap["title"], "version": cap["version"], "upgrade_id": ctx.upgrade_id,
                "stages": ctx.stages, "error": None}

    # ------------------------------------------------------------- introspection
    def history(self, capability_id=None, limit=20):
        if capability_id:
            rows = self.store.query("SELECT * FROM upgrade_log WHERE capability_id = ? ORDER BY upgrade_id DESC LIMIT ?",
                                    (capability_id, int(limit)))
        else:
            rows = self.store.query("SELECT * FROM upgrade_log ORDER BY upgrade_id DESC LIMIT ?", (int(limit),))
        out = []
        for r in rows:
            d = dict(r)
            for key in ("plan_json", "changes_json", "attempts_json", "validation_json", "test_json", "rollback_json"):
                d[key[:-5]] = json.loads(d.pop(key)) if d.get(key) else None
            out.append(d)
        return out


def _json_safe(obj):
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return json.loads(json.dumps(obj, default=str))


__all__ = ["Builder", "ST_APPLIED", "ST_NOOP", "ST_CONFIRM", "ST_FAILED"]
