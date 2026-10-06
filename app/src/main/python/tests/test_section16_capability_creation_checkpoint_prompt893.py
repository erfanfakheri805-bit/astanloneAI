"""
Prompt 893 - Section 16 (Capability Creation & Improvement) final checkpoint.

Deterministic, read-only verification of the complete public chain of Prompts 876-892:

  request(876) -> analysis(877) -> specification(878) -> validation(879) -> plan(880)
  -> proposal(881) -> candidate(882) -> readiness(883) -> design(884) -> design validation(885)
  -> blueprint(886) -> blueprint validation(887) -> contract(888) -> contract readiness(889)
  -> boundary(890) -> implementation request(891) -> implementation request validation(892)

No production code is added or changed; these tests only compose the existing public
builders and validators. A "ready" state means "validated definition/planning/contract/request
chain" - never permission to implement or execute.

Run (from app/src/main/python/):
    python -m unittest tests.test_section16_capability_creation_checkpoint_prompt893 -v
"""

import ast
import copy
import hashlib
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.capability_definition_candidate import (
    build_capability_definition_candidate as build_candidate,
    validate_capability_definition_candidate as v882)
from capabilities.capability_definition_readiness import (
    evaluate_capability_definition_readiness as evaluate_readiness,
    validate_capability_definition_readiness as v883)
from capabilities.capability_evolution_analysis import (
    analyze_capability_evolution as analyze,
    validate_capability_evolution_analysis as v877)
from capabilities.capability_evolution_plan import (
    build_capability_evolution_plan as build_plan,
    validate_capability_evolution_plan as v880)
from capabilities.capability_evolution_proposal import (
    build_capability_evolution_proposal as build_proposal,
    validate_capability_evolution_proposal as v881)
from capabilities.capability_evolution_request import (
    build_capability_evolution_request as build_request,
    validate_capability_evolution_request as v876)
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec,
    validate_capability_evolution_specification as v878)
from capabilities.capability_evolution_validation import (
    validate_capability_evolution as validate879,
    validate_capability_evolution_result as v879_result)
from capabilities.capability_implementation_blueprint import (
    build_capability_implementation_blueprint as build_blueprint,
    validate_capability_implementation_blueprint as v886)
from capabilities.capability_implementation_blueprint_validation import (
    validate_capability_implementation_blueprint_context as check887,
    validate_capability_implementation_blueprint_validation_result as v887)
from capabilities.capability_implementation_boundary import (
    evaluate_capability_implementation_boundary as evaluate890,
    validate_capability_implementation_boundary_result as v890)
from capabilities.capability_implementation_contract import (
    build_capability_implementation_contract as build_contract,
    validate_capability_implementation_contract as validate_contract)
from capabilities.capability_implementation_contract_readiness import (
    evaluate_capability_implementation_contract_readiness as evaluate889,
    validate_capability_implementation_contract_readiness as v889)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build_design,
    validate_capability_implementation_design as v884)
from capabilities.capability_implementation_design_validation import (
    validate_capability_implementation_design_context as check885,
    validate_capability_implementation_design_validation_result as v885)
from capabilities.capability_implementation_request import (
    build_capability_implementation_request as build_impl_request,
    validate_capability_implementation_request as v891)
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context as check892,
    validate_capability_implementation_request_validation_result as v892)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "section16_final_checkpoint_prompt893.md")

CHAIN_MODULES = (
    "capability_evolution_request", "capability_evolution_analysis",
    "capability_evolution_specification", "capability_evolution_validation",
    "capability_evolution_plan", "capability_evolution_proposal",
    "capability_definition_candidate", "capability_definition_readiness",
    "capability_implementation_design", "capability_implementation_design_validation",
    "capability_implementation_blueprint", "capability_implementation_blueprint_validation",
    "capability_implementation_contract", "capability_implementation_contract_readiness",
    "capability_implementation_boundary", "capability_implementation_request",
    "capability_implementation_request_validation")

NAMES = ["request", "analysis", "spec", "plan", "proposal", "candidate", "readiness", "design",
         "v885", "blueprint", "b887", "contract", "creport", "r889", "boundary", "impl_request"]
(REQUEST, ANALYSIS, SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS, DESIGN, V885, BLUEPRINT, B887,
 CONTRACT, CREPORT, R889, BOUNDARY, IMPL) = range(16)

# index -> public structural validator of that stage's own output (12 is a validator output).
STAGE_VALIDATORS = {
    REQUEST: v876, ANALYSIS: v877, SPEC: v878, PLAN: v880, PROPOSAL: v881, CANDIDATE: v882,
    READINESS: v883, DESIGN: v884, V885: v885, BLUEPRINT: v886, B887: v887,
    CONTRACT: validate_contract, R889: v889, BOUNDARY: v890, IMPL: v891}

# index -> status that check892 must report when that object is missing/invalid.
EXPECTED_INVALID = {
    REQUEST: "invalid_request", ANALYSIS: "invalid_analysis", SPEC: "invalid_specification",
    PLAN: "invalid_plan", PROPOSAL: "invalid_proposal", CANDIDATE: "invalid_candidate",
    READINESS: "invalid_readiness", DESIGN: "invalid_design",
    V885: "invalid_design_validation", BLUEPRINT: "invalid_blueprint",
    B887: "invalid_blueprint_validation", CONTRACT: "invalid_contract",
    CREPORT: "invalid_contract_validation", R889: "invalid_contract_readiness",
    BOUNDARY: "invalid_boundary", IMPL: "invalid_implementation_request"}

RESULT_KEYS = ["version", "status", "valid", "implementation_request_id", "request_id",
               "capability_name", "operation", "analysis_status", "plan_id", "contract_id",
               "boundary_status", "reason"]
PERMISSION_KEYS = ("implementation_allowed", "execution_allowed", "executed",
                   "implementation_started", "implementation_ready")


def req(**over):
    d = {"version": "1", "request_id": "evo_001", "operation": "create",
         "capability_name": "text_summarizer", "goal": "Summarize short documents.",
         "inputs": ["z_input", "a_input"], "outputs": ["z_out", "a_out"],
         "constraints": ["Second.", "First.", "Second."], "requested_by": "developer",
         "execution_allowed": False}
    d.update(over)
    return d


def desc(name="text_summarizer", **over):
    d = {"name": name, "version": 1, "purpose": "Summarize text.", "inputs": ["document_text"],
         "outputs": ["summary_text"], "constraints": ["Pure Python only."], "enabled": True}
    d.update(over)
    return d


def full(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
         candidate_id="cand_001", design_id="design_001", blueprint_id="bp_001",
         contract_id="ct_001", iid="ir_001", **req_over):
    """The 16 chain objects: request .. boundary (890), implementation request (891)."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = build_request(req(operation=op, **req_over))["evolution_request"]
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, plan_id)["plan"]
    proposal = build_proposal(request, analysis, spec, plan, proposal_id)["proposal"]
    candidate = build_candidate(request, analysis, spec, plan, proposal, candidate_id)["candidate"]
    readiness = evaluate_readiness(request, analysis, spec, plan, proposal, candidate)
    design = build_design(request, analysis, spec, plan, proposal, candidate, readiness,
                          design_id)["design"]
    chain = [request, analysis, spec, plan, proposal, candidate, readiness, design]
    vresult = check885(*chain)
    blueprint = build_blueprint(*chain, vresult, blueprint_id)["blueprint"]
    bresult = check887(*chain, vresult, blueprint)
    contract = build_contract(*chain, vresult, blueprint, bresult, contract_id)["contract"]
    creport = validate_contract(contract)
    r889 = evaluate889(*chain, vresult, blueprint, bresult, contract, creport)
    base = chain + [vresult, blueprint, bresult, contract, creport, r889]
    boundary = evaluate890(*base)
    base = base + [boundary]
    return base + [build_impl_request(*base, iid)["request"]]


def run(chain):
    return check892(*chain)


def ok(op="create"):
    return run(full(op))


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


_BASE = {}


def base_chain(op="create"):
    if op not in _BASE:
        _BASE[op] = full(op)
    return copy.deepcopy(_BASE[op])


def with_obj(index, op="create", **changes):
    chain = base_chain(op)
    chain[index] = dict(chain[index], **changes)
    return chain


def codes(result):
    return [e["code"] for e in result["errors"]]


def normalized(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def walk(value):
    """Yield every (key, value) pair and every scalar inside a nested structure."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            for pair in walk(v):
                yield pair
    elif isinstance(value, (list, tuple)):
        for v in value:
            for pair in walk(v):
                yield pair


def module_path(name):
    return os.path.join(ROOT, "capabilities", name + ".py")


def fs_fingerprint():
    entries = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(base, name)
            stat = os.stat(path)
            entries.append((os.path.relpath(path, ROOT), stat.st_size, stat.st_mtime_ns))
    return entries


def source_fingerprint():
    digest = hashlib.sha256()
    for name in CHAIN_MODULES:
        with open(module_path(name), "rb") as handle:
            digest.update(handle.read())
    return digest.hexdigest()


def module_state():
    """repr of every mutable module-level container in the capabilities package."""
    state = {}
    for mod_name, mod in sorted(sys.modules.items()):
        if not mod_name.startswith("capabilities.") or mod is None:
            continue
        for key, value in sorted(vars(mod).items()):
            if isinstance(value, (list, dict, set, bytearray)) and not key.startswith("__"):
                state[(mod_name, key)] = repr(value)
    return state


def blocked(*_args, **_kwargs):
    raise AssertionError("forbidden operation attempted during the checkpoint")


class ChainStructureTests(unittest.TestCase):
    def _all_seventeen_modules_exist(self):
        for name in CHAIN_MODULES:
            self.assertTrue(os.path.isfile(module_path(name)), name)
        self.assertEqual(len(CHAIN_MODULES), 17)

    def _chain_has_sixteen_objects(self):
        for op in ("create", "improve"):
            self.assertEqual(len(full(op)), 16)
            self.assertEqual(len(NAMES), 16)

    def _every_stage_is_structurally_valid(self):
        for op in ("create", "improve"):
            chain = full(op)
            for index, validator in STAGE_VALIDATORS.items():
                result = validator(chain[index])
                self.assertIs(result["valid"], True, (op, NAMES[index], result))
            self.assertIs(chain[CREPORT]["valid"], True)

    def _876_build_matches_validator(self):
        for op in ("create", "improve"):
            built = build_request(req(operation=op))
            self.assertTrue(built["valid"])
            self.assertTrue(v876(built["evolution_request"])["valid"])

    def test_879_evolution_validation_is_ready(self):
        for op in ("create", "improve"):
            chain = full(op)
            result = validate879(chain[REQUEST], chain[ANALYSIS], chain[SPEC])
            self.assertEqual(result["status"], "ready")
            self.assertIs(result["ready"], True)
            self.assertTrue(v879_result(result)["valid"])
            self.assertIs(result["execution_allowed"], False)
            self.assertIs(result["executed"], False)

    def _final_892_validation_is_valid(self):
        for op in ("create", "improve"):
            result = ok(op)
            self.assertEqual(result["status"], "valid")
            self.assertIs(result["valid"], True)
            self.assertEqual(result["reason"], "valid")
            self.assertEqual(result["operation"], op)

    def _final_892_result_validates_and_has_exact_keys(self):
        for op in ("create", "improve"):
            result = ok(op)
            self.assertEqual(list(result), RESULT_KEYS)
            verdict = v892(result)
            self.assertTrue(verdict["valid"], verdict)
            self.assertIs(verdict["execution_allowed"], False)
            self.assertIs(verdict["executed"], False)

    def _analysis_statuses(self):
        self.assertEqual(full("create")[ANALYSIS]["status"], "create_required")
        self.assertEqual(full("improve")[ANALYSIS]["status"], "improve_required")

    def test_valid_only_when_every_object_is_valid(self):
        base = full()
        self.assertEqual(run(base)["status"], "valid")
        for i in range(16):
            for bad in (None, {}, [], "x"):
                broken = list(base)
                broken[i] = bad
                result = run(broken)
                self.assertEqual(result["status"], EXPECTED_INVALID[i], (NAMES[i], bad))
                self.assertIs(result["valid"], False)
                self.assertTrue(v892(result)["valid"], (NAMES[i], v892(result)))
    def test_modules_and_chain_size_are_complete(self):
        self._all_seventeen_modules_exist()
        self._chain_has_sixteen_objects()

    def test_every_stage_structurally_valid_and_876_build_matches(self):
        self._every_stage_is_structurally_valid()
        self._876_build_matches_validator()

    def test_final_892_validation_valid_exact_and_self_validating(self):
        self._final_892_validation_is_valid()
        self._final_892_result_validates_and_has_exact_keys()
        self._analysis_statuses()


class IdentityConsistencyTests(unittest.TestCase):
    def _request_id_preserved_everywhere(self):
        for op in ("create", "improve"):
            chain = full(op)
            for i, obj in enumerate(chain):
                if "request_id" in obj:
                    self.assertEqual(obj["request_id"], "evo_001", (op, NAMES[i]))
            self.assertEqual(ok(op)["request_id"], "evo_001")

    def _capability_name_preserved_everywhere(self):
        for op in ("create", "improve"):
            chain = full(op)
            for i, obj in enumerate(chain):
                if "capability_name" in obj:
                    self.assertEqual(obj["capability_name"], "text_summarizer", (op, NAMES[i]))
            self.assertEqual(ok(op)["capability_name"], "text_summarizer")

    def _operation_preserved_everywhere(self):
        for op in ("create", "improve"):
            chain = full(op)
            for i, obj in enumerate(chain):
                if "operation" in obj:
                    self.assertEqual(obj["operation"], op, (op, NAMES[i]))
            self.assertEqual(ok(op)["operation"], op)

    def _plan_id_preserved_everywhere(self):
        for op in ("create", "improve"):
            chain = full(op)
            self.assertEqual(chain[PLAN]["plan_id"], "plan_001")
            for i, obj in enumerate(chain):
                if "plan_id" in obj:
                    self.assertEqual(obj["plan_id"], "plan_001", (op, NAMES[i]))
            self.assertEqual(ok(op)["plan_id"], "plan_001")

    def test_stage_ids_link_in_order(self):
        for op in ("create", "improve"):
            c = full(op)
            self.assertEqual(c[PROPOSAL]["plan_id"], c[PLAN]["plan_id"])
            self.assertEqual(c[CANDIDATE]["proposal_id"], c[PROPOSAL]["proposal_id"])
            self.assertEqual(c[DESIGN]["candidate_id"], c[CANDIDATE]["candidate_id"])
            self.assertEqual(c[V885]["design_id"], c[DESIGN]["design_id"])
            self.assertEqual(c[BLUEPRINT]["design_id"], c[DESIGN]["design_id"])
            self.assertEqual(c[B887]["blueprint_id"], c[BLUEPRINT]["blueprint_id"])
            self.assertEqual(c[CONTRACT]["blueprint_id"], c[BLUEPRINT]["blueprint_id"])
            self.assertEqual(c[R889]["contract_id"], c[CONTRACT]["contract_id"])
            self.assertEqual(c[BOUNDARY]["contract_id"], c[CONTRACT]["contract_id"])
            self.assertEqual(c[IMPL]["contract_id"], c[CONTRACT]["contract_id"])

    def _contract_id_preserved_to_final_result(self):
        for op in ("create", "improve"):
            self.assertEqual(ok(op)["contract_id"], "ct_001")

    def test_implementation_request_id_bound_to_request(self):
        for iid in ("ir_001", "my.request-7", "x" * 64):
            chain = full(iid=iid)
            self.assertEqual(chain[IMPL]["implementation_request_id"], iid)
            result = run(chain)
            self.assertEqual(result["status"], "valid")
            self.assertEqual(result["implementation_request_id"], iid)

    def _goal_preserved_as_purpose(self):
        for op in ("create", "improve"):
            c = full(op)
            for i in (SPEC, PLAN, PROPOSAL):
                self.assertEqual(c[i]["goal"], "Summarize short documents.", NAMES[i])
            for i in (CANDIDATE, DESIGN, BLUEPRINT, CONTRACT, IMPL):
                self.assertEqual(c[i]["purpose"], "Summarize short documents.", NAMES[i])

    def _inputs_outputs_constraints_preserved_exactly(self):
        for op in ("create", "improve"):
            c = full(op)
            for i in (SPEC, PLAN, PROPOSAL, CANDIDATE, DESIGN, BLUEPRINT, CONTRACT, IMPL):
                self.assertEqual(c[i]["inputs"], ["z_input", "a_input"], NAMES[i])
                self.assertEqual(c[i]["outputs"], ["z_out", "a_out"], NAMES[i])
                self.assertEqual(c[i]["constraints"], ["Second.", "First.", "Second."], NAMES[i])

    def test_existing_capability_carried_for_improve_only(self):
        c = full("improve")
        for i in (SPEC, PLAN, PROPOSAL, CANDIDATE, DESIGN, BLUEPRINT, CONTRACT, IMPL):
            self.assertEqual(c[i]["existing_capability"], desc(), NAMES[i])
        c = full("create")
        for i in (SPEC, PLAN, PROPOSAL, CANDIDATE, DESIGN, BLUEPRINT, CONTRACT, IMPL):
            self.assertIsNone(c[i]["existing_capability"], NAMES[i])

    def _final_result_matches_implementation_request(self):
        for op in ("create", "improve"):
            c = full(op)
            result = run(c)
            self.assertEqual(result["implementation_request_id"],
                             c[IMPL]["implementation_request_id"])
            self.assertEqual(result["boundary_status"], c[IMPL]["boundary_status"])
            self.assertEqual(result["analysis_status"], c[IMPL]["analysis_status"])

    def _no_stage_silently_changes_trusted_input(self):
        caps = [desc()]
        request = build_request(req(operation="improve"))["evolution_request"]
        before_request, before_caps = copy.deepcopy(request), copy.deepcopy(caps)
        analysis = analyze(request, caps)
        spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
        plan = build_plan(request, analysis, spec, "plan_001")["plan"]
        build_proposal(request, analysis, spec, plan, "prop_001")
        self.assertEqual(request, before_request)
        self.assertEqual(caps, before_caps)

    def _built_objects_do_not_alias_the_request(self):
        request = build_request(req())["evolution_request"]
        analysis = analyze(request, [])
        spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
        request["inputs"].append("mutated")
        request["constraints"].append("mutated")
        self.assertEqual(spec["inputs"], ["z_input", "a_input"])
        self.assertEqual(spec["constraints"], ["Second.", "First.", "Second."])
    def test_core_identity_preserved_everywhere(self):
        self._request_id_preserved_everywhere()
        self._capability_name_preserved_everywhere()
        self._operation_preserved_everywhere()
        self._plan_id_preserved_everywhere()

    def test_goal_inputs_outputs_constraints_preserved(self):
        self._goal_preserved_as_purpose()
        self._inputs_outputs_constraints_preserved_exactly()

    def test_final_result_matches_request_and_contract(self):
        self._contract_id_preserved_to_final_result()
        self._final_result_matches_implementation_request()

    def test_trusted_inputs_unchanged_and_not_aliased(self):
        self._no_stage_silently_changes_trusted_input()
        self._built_objects_do_not_alias_the_request()


class DeterminismTests(unittest.TestCase):
    def test_create_chain_is_deterministic(self):
        runs = [full("create") for _ in range(3)]
        self.assertEqual(normalized(runs[0]), normalized(runs[1]))
        self.assertEqual(normalized(runs[1]), normalized(runs[2]))
        self.assertEqual(normalized([run(c) for c in runs[:2]][0]),
                         normalized(run(runs[1])))

    def test_improve_chain_is_deterministic(self):
        runs = [full("improve") for _ in range(3)]
        self.assertEqual(normalized(runs[0]), normalized(runs[1]))
        self.assertEqual(normalized(runs[1]), normalized(runs[2]))
        self.assertEqual(normalized(run(runs[0])), normalized(run(runs[2])))

    def _repeated_final_validation_is_equal_and_fresh(self):
        for op in ("create", "improve"):
            chain = full(op)
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
            self.assertIsNot(results[0], results[1])

    def _rejections_are_deterministic(self):
        bad = with_obj(PLAN, plan_id="plan_zzz")
        results = [run(bad) for _ in range(3)]
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(results[0]["status"], "context_mismatch")

    def _equivalent_inputs_give_equivalent_normalized_outputs(self):
        for op in ("create", "improve"):
            a, b = full(op), full(op, caps=[desc()] if op == "improve" else [])
            self.assertEqual(normalized(a), normalized(b))
            self.assertEqual(normalized(run(a)), normalized(run(b)))

    def _different_ids_give_different_but_stable_outputs(self):
        a, b = full(plan_id="plan_001"), full(plan_id="plan_002")
        self.assertNotEqual(normalized(a), normalized(b))
        self.assertEqual(run(b)["plan_id"], "plan_002")
        self.assertEqual(normalized(run(b)), normalized(run(full(plan_id="plan_002"))))

    def test_checkpoint_has_no_clock_random_or_uuid_use(self):
        with open(__file__.replace(".pyc", ".py"), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        banned = {"time", "datetime", "random", "uuid", "secrets", "socket", "subprocess"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                self.assertNotIn((node.module or "").split(".")[0], banned)
    def test_repeated_validation_and_rejections_are_deterministic(self):
        self._repeated_final_validation_is_equal_and_fresh()
        self._rejections_are_deterministic()

    def test_equivalent_and_distinct_inputs_normalize_stably(self):
        self._equivalent_inputs_give_equivalent_normalized_outputs()
        self._different_ids_give_different_but_stable_outputs()


class SafetyInvariantTests(unittest.TestCase):
    def _permission_flags_false_on_every_stage(self):
        for op in ("create", "improve"):
            chain = full(op)
            for i, obj in enumerate(chain):
                for key in PERMISSION_KEYS:
                    if key in obj and key != "ready":
                        self.assertIs(obj[key], False, (op, NAMES[i], key))
            self.assertIs(chain[CREPORT]["execution_allowed"], False)
            self.assertIs(chain[CREPORT]["executed"], False)

    def _boundary_flags(self):
        for op in ("create", "improve"):
            boundary = full(op)[BOUNDARY]
            self.assertEqual(boundary["status"], "ready")
            self.assertIs(boundary["ready"], True)
            self.assertIs(boundary["implementation_allowed"], False)
            self.assertIs(boundary["implementation_started"], False)
            self.assertIs(boundary["execution_allowed"], False)
            self.assertIs(boundary["executed"], False)

    def _implementation_request_flags(self):
        for op in ("create", "improve"):
            impl = full(op)[IMPL]
            self.assertIs(impl["implementation_allowed"], False)
            self.assertIs(impl["execution_allowed"], False)
            self.assertNotIn("implementation_started", impl)

    def _implementation_ready_false_where_applicable(self):
        for op in ("create", "improve"):
            chain = full(op)
            self.assertIs(chain[CANDIDATE]["implementation_ready"], False)
            self.assertIs(chain[DESIGN]["implementation_ready"], False)

    def test_final_result_exposes_no_permission_fields(self):
        for op in ("create", "improve"):
            result = ok(op)
            for key in PERMISSION_KEYS:
                self.assertNotIn(key, result)

    def test_ready_means_validated_chain_not_permission(self):
        for op in ("create", "improve"):
            c = full(op)
            self.assertIs(c[READINESS]["ready"], True)
            self.assertIs(c[R889]["ready"], True)
            self.assertIs(c[BOUNDARY]["ready"], True)
            self.assertEqual(ok(op)["boundary_status"], "ready")
            self.assertEqual(ok(op)["status"], "valid")
            self.assertIs(c[READINESS]["execution_allowed"], False)
            self.assertIs(c[R889]["execution_allowed"], False)
            self.assertIs(c[BOUNDARY]["implementation_allowed"], False)
            self.assertIs(c[BOUNDARY]["implementation_started"], False)
            self.assertIs(c[IMPL]["implementation_allowed"], False)
            self.assertIs(c[IMPL]["execution_allowed"], False)

    def _no_source_code_generated(self):
        code_like = re.compile(r"(^|\s)(def |class |import |from \S+ import )|```|#!/|;\s*$")
        banned_keys = {"code", "source", "source_code", "script", "module_source", "body"}
        for op in ("create", "improve"):
            for i, obj in enumerate(full(op) + [ok(op)]):
                for key, value in walk(obj):
                    self.assertNotIn(key, banned_keys, (op, i, key))
                    if isinstance(value, str):
                        self.assertIsNone(code_like.search(value), (op, i, key, value))

    def _no_patch_or_change_set_generated(self):
        banned_keys = {"patch", "diff", "change_set", "changes", "changeset", "files",
                       "file_changes", "commands", "command", "shell"}
        patch_like = re.compile(r"^(--- |\+\+\+ |@@ |diff --git)", re.M)
        for op in ("create", "improve"):
            for i, obj in enumerate(full(op) + [ok(op)]):
                for key, value in walk(obj):
                    self.assertNotIn(key, banned_keys, (op, i, key))
                    if isinstance(value, str):
                        self.assertIsNone(patch_like.search(value), (op, i, key))

    def _no_filesystem_modification(self):
        before = fs_fingerprint()
        sources = source_fingerprint()
        for op in ("create", "improve"):
            run(full(op))
        self.assertEqual(fs_fingerprint(), before)
        self.assertEqual(source_fingerprint(), sources)

    def _no_filesystem_access_at_all_while_chain_runs(self):
        with mock.patch("builtins.open", side_effect=blocked), \
                mock.patch("os.remove", side_effect=blocked), \
                mock.patch("os.rename", side_effect=blocked), \
                mock.patch("os.mkdir", side_effect=blocked), \
                mock.patch("os.makedirs", side_effect=blocked), \
                mock.patch("shutil.rmtree", side_effect=blocked), \
                mock.patch("os.listdir", side_effect=blocked):
            for op in ("create", "improve"):
                self.assertEqual(run(full(op))["status"], "valid", op)

    def test_no_registry_or_module_state_mutation(self):
        caps = [desc()]
        snapshot = copy.deepcopy(caps)
        state = module_state()
        request = build_request(req(operation="improve"))["evolution_request"]
        analyze(request, caps)
        for op in ("create", "improve"):
            run(full(op))
        self.assertEqual(caps, snapshot)
        self.assertEqual(module_state(), state)

    def test_no_memory_or_ael_access(self):
        before = set(sys.modules)
        for op in ("create", "improve"):
            run(full(op))
        new = set(sys.modules) - before
        for name in new:
            root = name.split(".")[0]
            self.assertNotIn(root, {"memory", "ael", "research", "core", "learning",
                                    "knowledge", "agent", "execution", "tools"}, name)

    def _no_network_api_or_model_access(self):
        with mock.patch("socket.socket", side_effect=blocked), \
                mock.patch("socket.create_connection", side_effect=blocked), \
                mock.patch("socket.getaddrinfo", side_effect=blocked), \
                mock.patch("urllib.request.urlopen", side_effect=blocked):
            for op in ("create", "improve"):
                self.assertEqual(run(full(op))["status"], "valid", op)

    def _no_subprocess_use(self):
        with mock.patch("subprocess.Popen", side_effect=blocked), \
                mock.patch("subprocess.run", side_effect=blocked), \
                mock.patch("os.system", side_effect=blocked), \
                mock.patch("os.popen", side_effect=blocked):
            for op in ("create", "improve"):
                self.assertEqual(run(full(op))["status"], "valid", op)

    def _no_exec_eval_or_compile_at_runtime(self):
        with mock.patch("builtins.exec", side_effect=blocked), \
                mock.patch("builtins.eval", side_effect=blocked), \
                mock.patch("builtins.compile", side_effect=blocked):
            for op in ("create", "improve"):
                self.assertEqual(run(full(op))["status"], "valid", op)

    def test_no_automatic_execution_implementation_or_self_modification_api(self):
        verbs = re.compile(r"(execute|run|apply|implement|generate|write|patch|install|register|"
                           r"modify|upgrade|deploy|commit|save|delete|remove|start)", re.I)
        allowed_prefixes = ("build_", "validate_", "evaluate_", "analyze_")
        for name in CHAIN_MODULES:
            with open(module_path(name), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and not node.name.startswith("_"):
                    self.assertTrue(node.name.startswith(allowed_prefixes), (name, node.name))
                    self.assertIsNone(verbs.search(node.name.split("_", 1)[0]), (name, node.name))
                self.assertNotIsInstance(node, (ast.ClassDef, ast.AsyncFunctionDef), name)

    def _results_always_report_not_executed(self):
        for op in ("create", "improve"):
            c = full(op)
            for i in (ANALYSIS, R889, BOUNDARY):
                self.assertIs(c[i]["executed"], False, NAMES[i])
            for check in (v892(ok(op)), v885(c[V885]), v887(c[B887])):
                self.assertIs(check["execution_allowed"], False)
                self.assertIs(check["executed"], False)
    def test_permission_flags_false_everywhere(self):
        self._permission_flags_false_on_every_stage()
        self._implementation_ready_false_where_applicable()
        self._results_always_report_not_executed()

    def test_boundary_and_request_flags(self):
        self._boundary_flags()
        self._implementation_request_flags()

    def test_no_source_code_or_patch_generated(self):
        self._no_source_code_generated()
        self._no_patch_or_change_set_generated()

    def test_no_filesystem_modification_or_access(self):
        self._no_filesystem_modification()
        self._no_filesystem_access_at_all_while_chain_runs()

    def test_no_network_subprocess_or_dynamic_execution(self):
        self._no_network_api_or_model_access()
        self._no_subprocess_use()
        self._no_exec_eval_or_compile_at_runtime()


class ForgedObjectTests(unittest.TestCase):
    """Every forged or inconsistent object must fail, deterministically and validly."""

    def assert_rejected(self, chain, label=""):
        first = run(chain)
        self.assertNotEqual(first["status"], "valid", label)
        self.assertIs(first["valid"], False, label)
        self.assertEqual(first, run(chain), label)
        verdict = v892(first)
        self.assertTrue(verdict["valid"], (label, verdict))
        self.assertIs(first["valid"], False)
        return first

    def forged_from_other_chain(self, index, op="create", **kw):
        base = full(op)
        other = full(op, **kw)
        forged = swap(base, other, index)
        return self.assert_rejected(forged, (NAMES[index], op, kw))

    def test_forged_analysis(self):
        for op, status in (("create", "improve_required"), ("improve", "create_required")):
            chain = with_obj(ANALYSIS, op, status=status)
            self.assert_rejected(chain, op)
        chain = with_obj(ANALYSIS, "create", capability_name="other_cap")
        self.assert_rejected(chain)
        chain = with_obj(ANALYSIS, "create", operation="improve")
        self.assert_rejected(chain)

    def test_forged_specification(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(SPEC, op, request_id="evo_002")
            self.assert_rejected(with_obj(SPEC, op, goal="Another goal."), op)

    def test_forged_plan(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(PLAN, op, plan_id="plan_002")
            self.forged_from_other_chain(PLAN, op, request_id="evo_002")
            self.assert_rejected(with_obj(PLAN, op, plan_id="plan_zzz"), op)

    def test_forged_proposal(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(PROPOSAL, op, proposal_id="prop_002")
            self.assert_rejected(with_obj(PROPOSAL, op, plan_id="plan_zzz"), op)

    def test_forged_candidate(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(CANDIDATE, op, candidate_id="cand_002")
            self.assert_rejected(with_obj(CANDIDATE, op, proposal_id="prop_zzz"), op)

    def test_forged_readiness(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(READINESS, op, request_id="evo_002")
            self.assert_rejected(with_obj(READINESS, op, plan_id="plan_zzz"), op)
            self.assert_rejected(with_obj(READINESS, op, ready=False), op)

    def test_forged_implementation_design(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(DESIGN, op, design_id="design_002")
            self.assert_rejected(with_obj(DESIGN, op, candidate_id="cand_zzz"), op)

    def test_forged_design_validation(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(V885, op, design_id="design_002")
            self.assert_rejected(with_obj(V885, op, design_id="design_zzz"), op)
            self.assert_rejected(with_obj(V885, op, valid=False), op)

    def test_forged_blueprint(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(BLUEPRINT, op, blueprint_id="bp_002")
            self.assert_rejected(with_obj(BLUEPRINT, op, design_id="design_zzz"), op)

    def test_forged_blueprint_validation(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(B887, op, blueprint_id="bp_002")
            self.assert_rejected(with_obj(B887, op, blueprint_id="bp_zzz"), op)
            self.assert_rejected(with_obj(B887, op, valid=False), op)

    def test_forged_contract(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(CONTRACT, op, contract_id="ct_002")
            self.assert_rejected(with_obj(CONTRACT, op, blueprint_id="bp_zzz"), op)

    def test_forged_contract_validation(self):
        forged = {"valid": True, "errors": [], "execution_allowed": True, "executed": False}
        for op in ("create", "improve"):
            chain = full(op)
            chain[CREPORT] = forged
            self.assertEqual(self.assert_rejected(chain)["status"],
                             "invalid_contract_validation")
            chain[CREPORT] = {"valid": True, "errors": [], "execution_allowed": False,
                              "executed": True}
            self.assertEqual(self.assert_rejected(chain)["status"],
                             "invalid_contract_validation")
            chain[CREPORT] = {"valid": False, "errors": [], "execution_allowed": False,
                              "executed": False}
            self.assert_rejected(chain)

    def test_forged_contract_readiness(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(R889, op, contract_id="ct_002")
            self.assert_rejected(with_obj(R889, op, contract_id="ct_zzz"), op)
            self.assert_rejected(with_obj(R889, op, ready=False), op)

    def test_forged_boundary(self):
        for op in ("create", "improve"):
            self.forged_from_other_chain(BOUNDARY, op, contract_id="ct_002")
            self.forged_from_other_chain(BOUNDARY, op, plan_id="plan_002")
            self.assert_rejected(with_obj(BOUNDARY, op, plan_id="plan_zzz"), op)
            self.assert_rejected(with_obj(BOUNDARY, op, ready=False), op)

    def test_forged_implementation_request(self):
        for op in ("create", "improve"):
            for kw in (dict(request_id="evo_002"), dict(plan_id="plan_002"),
                       dict(contract_id="ct_002"), dict(goal="Other goal."),
                       dict(inputs=["q"]), dict(outputs=["q"]), dict(constraints=["Other."])):
                forged = full(op, **kw)[IMPL]
                self.assertTrue(v891(forged)["valid"], kw)
                chain = swap(full(op), [None] * 15 + [forged], IMPL)
                self.assertEqual(self.assert_rejected(chain, kw)["status"], "context_mismatch")

    def _forged_892_validation_result(self):
        for op in ("create", "improve"):
            genuine = ok(op)
            forged_variants = [
                dict(genuine, status="invalid_plan"),
                dict(genuine, valid=False),
                dict(genuine, reason="forged"),
                dict(genuine, plan_id=None),
                dict(genuine, contract_id=""),
                dict(genuine, boundary_status="not_ready"),
                dict(genuine, operation="delete"),
                dict(genuine, analysis_status="improve_or_conflict"),
                dict(genuine, implementation_allowed=True),
                dict(genuine, execution_allowed=True),
                dict(genuine, implementation_started=True),
                dict(genuine, version=2),
            ]
            for forged in forged_variants:
                verdict = v892(forged)
                self.assertFalse(verdict["valid"], forged)
                self.assertEqual(verdict, v892(forged))
            invalid = run(with_obj(PLAN, op, plan_id="plan_zzz"))
            self.assertFalse(v892(dict(invalid, valid=True))["valid"])
            self.assertFalse(v892(dict(invalid, status="valid"))["valid"])

    def _forged_892_result_differs_from_recomputation(self):
        genuine = ok("create")
        forged = dict(genuine, plan_id="plan_zzz")
        self.assertNotEqual(forged, run(full("create")))
        self.assertEqual(genuine, run(full("create")))

    def _swapped_objects_from_other_request(self):
        base, other = full(), full(request_id="evo_002")
        for i, name in enumerate(NAMES):
            if name in ("creport", "analysis"):
                continue  # carry no request id: identical in both chains
            self.assertEqual(self.assert_rejected(swap(base, other, i), name)["status"],
                             "context_mismatch", name)

    def _swapped_objects_from_other_operation(self):
        base, other = full("create"), full("improve")
        for i, name in enumerate(NAMES):
            if name == "creport":
                continue
            self.assert_rejected(swap(base, other, i), name)

    def test_trusted_id_mismatch_in_every_stage(self):
        base = full()
        for key in ("plan_id", "proposal_id", "candidate_id", "design_id", "blueprint_id",
                    "contract_id"):
            other = full(**{key: key[:-3] + "_002"})
            statuses = {run(swap(base, other, i))["status"] for i in range(16)}
            self.assertEqual(statuses - {"valid"}, {"context_mismatch"}, key)
    def test_swapped_objects_from_other_request_or_operation(self):
        self._swapped_objects_from_other_request()
        self._swapped_objects_from_other_operation()

    def test_forged_892_validation_result_and_recomputation(self):
        self._forged_892_validation_result()
        self._forged_892_result_differs_from_recomputation()


class MismatchTests(unittest.TestCase):
    def test_request_id_mismatch(self):
        for i in (REQUEST, SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS, DESIGN, V885, BLUEPRINT,
                  B887, CONTRACT, R889, BOUNDARY, IMPL):
            result = run(with_obj(i, request_id="evo_zzz"))
            self.assertNotEqual(result["status"], "valid", NAMES[i])
            self.assertIs(result["valid"], False)

    def test_capability_name_mismatch(self):
        for op in ("create", "improve"):
            for i in (SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS, DESIGN, V885, BLUEPRINT, B887,
                      CONTRACT, R889, BOUNDARY, IMPL):
                result = run(with_obj(i, op, capability_name="zzz_other"))
                self.assertNotEqual(result["status"], "valid", (op, NAMES[i]))

    def test_operation_mismatch(self):
        for op, other in (("create", "improve"), ("improve", "create")):
            for i in (REQUEST, SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS, DESIGN, V885,
                      BLUEPRINT, B887, CONTRACT, R889, BOUNDARY, IMPL):
                result = run(with_obj(i, op, operation=other))
                self.assertNotEqual(result["status"], "valid", (op, NAMES[i]))

    def test_plan_id_mismatch(self):
        for i in (PLAN, PROPOSAL, CANDIDATE, READINESS, R889, BOUNDARY, IMPL):
            result = run(with_obj(i, plan_id="plan_zzz"))
            self.assertNotEqual(result["status"], "valid", NAMES[i])

    def test_contract_id_mismatch(self):
        for i in (CONTRACT, R889, BOUNDARY, IMPL):
            result = run(with_obj(i, contract_id="ct_zzz"))
            self.assertNotEqual(result["status"], "valid", NAMES[i])

    def test_implementation_request_id_mismatch_and_invalid_ids(self):
        for bad in (None, "", 5, True, "x" * 65, "\n", " ir_001"):
            result = run(with_obj(IMPL, implementation_request_id=bad))
            self.assertEqual(result["status"], "invalid_implementation_request", repr(bad))
            self.assertIsNone(result["implementation_request_id"])
        genuine = ok("create")
        self.assertEqual(genuine["implementation_request_id"], "ir_001")
        renamed = run(with_obj(IMPL, implementation_request_id="ir_other"))
        if renamed["status"] == "valid":  # a caller-chosen id is reported, never silently reset
            self.assertEqual(renamed["implementation_request_id"], "ir_other")

    def _edited_implementation_request_fields_are_context_mismatch(self):
        edits = (("request_id", "evo_zzz"), ("capability_name", "zzz"), ("plan_id", "plan_zzz"),
                 ("contract_id", "ct_zzz"), ("purpose", "Another purpose."),
                 ("inputs", ["other"]), ("outputs", ["other"]), ("constraints", ["other"]))
        for key, value in edits:
            result = run(with_obj(IMPL, "create", **{key: value}))
            self.assertEqual(result["status"], "context_mismatch", key)
            self.assertTrue(v892(result)["valid"], key)

    def _input_and_constraint_order_is_strict(self):
        self.assertEqual(run(with_obj(IMPL, inputs=["a_input", "z_input"]))["status"],
                         "context_mismatch")
        self.assertEqual(run(with_obj(IMPL, constraints=["First.", "Second.", "Second."]))[
            "status"], "context_mismatch")

    def _existing_capability_mismatch(self):
        for changed in (desc(purpose="Changed purpose."), desc(version=2)):
            result = run(with_obj(IMPL, "improve", existing_capability=changed))
            self.assertEqual(result["status"], "context_mismatch")
    def test_implementation_request_field_edits_are_rejected(self):
        self._edited_implementation_request_fields_are_context_mismatch()
        self._input_and_constraint_order_is_strict()
        self._existing_capability_mismatch()


class PermissionEscalationTests(unittest.TestCase):
    def test_implementation_allowed_true_rejected_everywhere(self):
        for op in ("create", "improve"):
            for i in (BOUNDARY, IMPL):
                for bad in (True, 1, None, "False", 0):
                    result = run(with_obj(i, op, implementation_allowed=bad))
                    self.assertNotEqual(result["status"], "valid", (op, NAMES[i], bad))
                    self.assertIs(result["valid"], False)

    def test_execution_allowed_true_rejected_everywhere(self):
        for op in ("create", "improve"):
            base = full(op)
            for i, obj in enumerate(base):
                if "execution_allowed" not in obj:
                    continue
                for bad in (True, 1, None, "False"):
                    chain = list(base)
                    chain[i] = dict(obj, execution_allowed=bad)
                    result = run(chain)
                    self.assertNotEqual(result["status"], "valid", (op, NAMES[i], bad))
                    self.assertIs(result["valid"], False)

    def _executed_true_rejected_everywhere(self):
        for op in ("create", "improve"):
            base = full(op)
            for i, obj in enumerate(base):
                if "executed" not in obj:
                    continue
                chain = list(base)
                chain[i] = dict(obj, executed=True)
                self.assertNotEqual(run(chain)["status"], "valid", (op, NAMES[i]))

    def test_implementation_started_true_rejected(self):
        for op in ("create", "improve"):
            for bad in (True, 1, None, "False"):
                result = run(with_obj(BOUNDARY, op, implementation_started=bad))
                self.assertNotEqual(result["status"], "valid", (op, bad))
                self.assertEqual(result["status"], "invalid_boundary")

    def _implementation_ready_true_rejected(self):
        for i in (CANDIDATE, DESIGN):
            for bad in (True, 1, None):
                result = run(with_obj(i, implementation_ready=bad))
                self.assertNotEqual(result["status"], "valid", (NAMES[i], bad))

    def _boundary_not_ready_is_not_valid(self):
        for status in ("not_ready", "context_mismatch", "invalid_plan", ""):
            result = run(with_obj(BOUNDARY, status=status, ready=False))
            self.assertEqual(result["status"], "invalid_boundary", status)
    def test_executed_ready_and_not_ready_states_rejected(self):
        self._executed_true_rejected_everywhere()
        self._implementation_ready_true_rejected()
        self._boundary_not_ready_is_not_valid()


class ImproveOrConflictTests(unittest.TestCase):
    def conflict_chain(self, tail):
        request = build_request(req(operation="create"))["evolution_request"]
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
        return [request, analysis, spec] + tail

    def test_improve_or_conflict_is_unsupported(self):
        for tail in (full()[3:], full("improve")[3:], [None] * 13):
            result = run(self.conflict_chain(tail))
            self.assertEqual(result["status"], "unsupported_status")
            self.assertIs(result["valid"], False)
            self.assertEqual(result["analysis_status"], "improve_or_conflict")
            for key in ("implementation_request_id", "plan_id", "contract_id",
                        "boundary_status"):
                self.assertIsNone(result[key])
            self.assertTrue(v892(result)["valid"])

    def _conflict_is_deterministic_and_never_valid(self):
        chain = self.conflict_chain([None] * 13)
        self.assertEqual(run(chain), run(chain))
        self.assertNotEqual(run(chain)["status"], "valid")

    def _conflict_analysis_cannot_be_forged_into_a_valid_chain(self):
        chain = full("create")
        chain[ANALYSIS] = analyze(chain[REQUEST], [desc()])
        self.assertNotEqual(run(chain)["status"], "valid")
    def test_conflict_is_deterministic_and_cannot_be_forged(self):
        self._conflict_is_deterministic_and_never_valid()
        self._conflict_analysis_cannot_be_forged_into_a_valid_chain()


class MalformedObjectTests(unittest.TestCase):
    def test_missing_keys_rejected_at_every_stage(self):
        for op in ("create", "improve"):
            base = full(op)
            for i, obj in enumerate(base):
                for key in list(obj):
                    chain = list(base)
                    reduced = dict(obj)
                    del reduced[key]
                    chain[i] = reduced
                    result = run(chain)
                    self.assertNotEqual(result["status"], "valid", (op, NAMES[i], key))

    def test_extra_keys_rejected_at_every_stage(self):
        for op in ("create", "improve"):
            base = full(op)
            for i in range(16):
                for extra in ("code", "patch", "executed_extra"):
                    chain = list(base)
                    chain[i] = dict(base[i], **{extra: True})
                    self.assertNotEqual(run(chain)["status"], "valid", (op, NAMES[i], extra))

    def _wrong_container_types_rejected(self):
        base = full()
        for i in range(16):
            for bad in (None, [], (), "x", 1, set(), b"x"):
                chain = list(base)
                chain[i] = bad
                self.assertEqual(run(chain)["status"], EXPECTED_INVALID[i], (NAMES[i], bad))

    def _dict_subclass_rejected(self):
        class Forged(dict):
            pass
        base = full()
        for i in range(16):
            chain = list(base)
            chain[i] = Forged(base[i])
            self.assertNotEqual(run(chain)["status"], "valid", NAMES[i])

    def test_wrong_field_types_rejected(self):
        for key, bad in (("inputs", ("z_input",)), ("outputs", "x"), ("constraints", None),
                         ("purpose", 5), ("boundary_status", True), ("request_id", 7)):
            result = run(with_obj(IMPL, **{key: bad}))
            self.assertEqual(result["status"], "invalid_implementation_request", key)

    def test_wrong_result_version_types_rejected(self):
        for bad in ("1", 1.0, True, None, 2, 0, [1], b"1"):
            result = ok()
            result["version"] = bad
            verdict = v892(result)
            self.assertFalse(verdict["valid"], repr(bad))
            self.assertIn("invalid_version", codes(verdict))

    def test_wrong_stage_version_types_rejected(self):
        string_versions = (REQUEST, SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS)
        int_versions = (DESIGN, V885, BLUEPRINT, B887, CONTRACT, R889, BOUNDARY, IMPL)
        for i in string_versions:
            self.assertEqual(full()[i]["version"], "1", NAMES[i])
            for bad in (1, 1.0, True, None, "2", ["1"]):
                self.assertNotEqual(run(with_obj(i, version=bad))["status"], "valid",
                                    (NAMES[i], bad))
        for i in int_versions:
            self.assertIs(type(full()[i]["version"]), int, NAMES[i])
            for bad in ("1", 1.0, True, None, 2, 0, [1]):
                self.assertNotEqual(run(with_obj(i, version=bad))["status"], "valid",
                                    (NAMES[i], bad))

    def _result_validator_rejects_missing_and_extra_keys(self):
        for key in RESULT_KEYS:
            result = ok()
            del result[key]
            verdict = v892(result)
            self.assertFalse(verdict["valid"], key)
            self.assertEqual(codes(verdict), ["missing_key"])
        for extra in ("implementation_allowed", "execution_allowed", "executed", "x"):
            result = ok()
            result[extra] = False
            self.assertIn("unexpected_key", codes(v892(result)))

    def _result_validator_rejects_non_dicts(self):
        for bad in (None, [], "x", 1, ()):
            self.assertEqual(codes(v892(bad)), ["result_not_dict"])

    def _missing_arguments_are_invalid_not_exceptions(self):
        self.assertEqual(check892()["status"], "invalid_request")
        self.assertEqual(check892(None, None)["status"], "invalid_request")
        self.assertIs(check892()["valid"], False)
    def test_wrong_containers_subclasses_and_missing_arguments(self):
        self._wrong_container_types_rejected()
        self._dict_subclass_rejected()
        self._missing_arguments_are_invalid_not_exceptions()

    def test_result_validator_rejects_malformed_results(self):
        self._result_validator_rejects_missing_and_extra_keys()
        self._result_validator_rejects_non_dicts()


class MutationResistanceTests(unittest.TestCase):
    def _validation_does_not_mutate_inputs(self):
        for op in ("create", "improve"):
            chain = full(op)
            snapshot = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snapshot)
        bad = with_obj(PLAN, plan_id="plan_zzz")
        snapshot = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snapshot)

    def _result_validator_does_not_mutate(self):
        result = ok()
        snapshot = copy.deepcopy(result)
        v892(result)
        self.assertEqual(result, snapshot)

    def test_mutating_a_result_does_not_affect_later_runs(self):
        chain = full()
        first = run(chain)
        pristine = copy.deepcopy(first)
        first["plan_id"] = "tampered"
        first["status"] = "forged"
        self.assertEqual(run(chain), pristine)

    def test_mutating_a_chain_object_after_validation_is_detected(self):
        chain = full()
        self.assertEqual(run(chain)["status"], "valid")
        chain[PLAN]["plan_id"] = "plan_tampered"
        self.assertNotEqual(run(chain)["status"], "valid")
        chain = full()
        chain[IMPL]["inputs"].append("late_addition")
        self.assertEqual(run(chain)["status"], "context_mismatch")
        chain = full()
        chain[BOUNDARY]["implementation_allowed"] = True
        self.assertEqual(run(chain)["status"], "invalid_boundary")

    def _mutating_builder_output_does_not_affect_other_stages(self):
        chain = full()
        chain[SPEC]["inputs"].append("late")
        self.assertEqual(chain[PLAN]["inputs"], ["z_input", "a_input"])
        self.assertEqual(chain[IMPL]["inputs"], ["z_input", "a_input"])

    def _builder_outputs_are_fresh_each_call(self):
        a, b = full(), full()
        for i in range(16):
            self.assertIsNot(a[i], b[i], NAMES[i])
            self.assertEqual(a[i], b[i], NAMES[i])
        a[IMPL]["outputs"].append("x")
        self.assertEqual(b[IMPL]["outputs"], ["z_out", "a_out"])
    def test_validation_does_not_mutate_inputs_or_results(self):
        self._validation_does_not_mutate_inputs()
        self._result_validator_does_not_mutate()

    def test_builder_outputs_fresh_and_independent(self):
        self._mutating_builder_output_does_not_affect_other_stages()
        self._builder_outputs_are_fresh_each_call()


class ForbiddenUsageTests(unittest.TestCase):
    BANNED_IMPORTS = {"os", "sys", "socket", "http", "urllib", "requests", "subprocess",
                      "shutil", "pathlib", "importlib", "sqlite3", "pickle", "json", "random",
                      "time", "datetime", "threading", "ctypes", "builtins", "ael", "memory",
                      "research", "uuid", "secrets", "tempfile", "glob", "asyncio", "multiprocessing"}
    BANNED_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint",
                    "globals", "locals", "setattr", "delattr", "vars"}
    BANNED_ATTRS = {"system", "popen", "Popen", "urlopen", "remove", "unlink", "rmtree",
                    "write", "write_text", "write_bytes", "mkdir", "makedirs", "rename",
                    "connect", "fetch", "request", "execute", "executescript"}

    def trees(self):
        for name in CHAIN_MODULES:
            with open(module_path(name), encoding="utf-8") as handle:
                yield name, ast.parse(handle.read())

    def _imports_are_limited_to_copy_and_sibling_capability_modules(self):
        for name, tree in self.trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertEqual(alias.name, "copy", name)
                elif isinstance(node, ast.ImportFrom):
                    self.assertEqual(node.level, 1, (name, node.module))
                    self.assertTrue(node.module.startswith("capability_"), (name, node.module))
                    self.assertNotIn(node.module.split(".")[0], self.BANNED_IMPORTS)

    def _no_forbidden_import_names(self):
        for name, tree in self.trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], self.BANNED_IMPORTS, name)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertNotIn((node.module or "").split(".")[0], self.BANNED_IMPORTS, name)

    def test_no_exec_eval_compile_open_or_dynamic_import(self):
        for name, tree in self.trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, self.BANNED_CALLS, (name, node.lineno))

    def test_no_io_process_or_network_attribute_calls(self):
        for name, tree in self.trees():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, self.BANNED_ATTRS, (name, node.lineno))

    def _no_global_statements_or_module_level_side_effects(self):
        for name, tree in self.trees():
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal), name)
            for node in tree.body:
                if isinstance(node, ast.Expr):  # only docstrings may be bare expressions
                    self.assertIsInstance(node.value, ast.Constant, name)

    def _modules_carry_no_embedded_secrets_or_urls(self):
        pattern = re.compile(r"https?://|api[_-]?key|BEGIN [A-Z ]*PRIVATE KEY", re.I)
        for name in CHAIN_MODULES:
            with open(module_path(name), encoding="utf-8") as handle:
                self.assertIsNone(pattern.search(handle.read()), name)

    def test_chain_modules_are_unmodified_by_a_run(self):
        before = source_fingerprint()
        for op in ("create", "improve"):
            run(full(op))
        self.assertEqual(source_fingerprint(), before)
    def test_imports_limited_and_no_forbidden_names(self):
        self._imports_are_limited_to_copy_and_sibling_capability_modules()
        self._no_forbidden_import_names()

    def test_no_globals_or_embedded_secrets(self):
        self._no_global_statements_or_module_level_side_effects()
        self._modules_carry_no_embedded_secrets_or_urls()


class DocumentationTests(unittest.TestCase):
    SECTIONS = ("Purpose of Section 16", "Prompt 876-892 chain",
                "What each stage contributes", "Final boundary meaning",
                "Final implementation-request meaning", "Final validation meaning",
                "Safety invariants", "What the system can do", "What the system cannot do",
                "Why implementation remains disabled", "Test coverage",
                "Intentionally deferred")

    def read(self):
        with open(DOC, encoding="utf-8") as handle:
            return handle.read()

    def _document_exists(self):
        self.assertTrue(os.path.isfile(DOC), DOC)

    def _document_has_required_sections(self):
        text = self.read()
        for section in self.SECTIONS:
            self.assertIn(section.lower(), text.lower(), section)

    def _document_lists_every_prompt_in_the_chain(self):
        text = self.read()
        for number in range(876, 893):
            self.assertIn(str(number), text, number)

    def _document_states_the_architectural_boundary(self):
        text = self.read()
        for phrase in ("deterministic capability creation/improvement planning pipeline",
                       "autonomous code generation", "autonomous implementation",
                       "autonomous execution", "unrestricted self-modification",
                       "implementation_allowed=False", "execution_allowed=False",
                       "implementation_started=False"):
            self.assertIn(phrase, text, phrase)

    def _document_states_what_ready_means(self):
        text = self.read()
        self.assertIn("validated definition/planning/contract/request chain", text)
        self.assertIn("permission to implement or execute", text)
    def test_document_exists_with_sections_and_every_prompt(self):
        self._document_exists()
        self._document_has_required_sections()
        self._document_lists_every_prompt_in_the_chain()

    def test_document_states_boundary_and_ready_meaning(self):
        self._document_states_the_architectural_boundary()
        self._document_states_what_ready_means()


if __name__ == "__main__":
    unittest.main()
