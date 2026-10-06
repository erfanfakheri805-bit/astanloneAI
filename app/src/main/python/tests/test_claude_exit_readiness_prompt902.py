"""
Prompt 902 - Section 18 (Claude Exit / Autonomy Validation): Claude exit readiness contract.

Deterministic, read-only tests of autonomy/claude_exit_readiness.py. The module only DESCRIBES
whether the validated Section 16 + Section 17 chain carries enough structured context to
continue to the next controlled internal stage without asking Claude to design the missing
architecture. "ready_without_claude" / claude_independent=True is not approval, not
authorization, not implementation permission and not execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_claude_exit_readiness_prompt902 -v
"""

import ast
import copy
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy import claude_exit_readiness as mod
from autonomy.claude_exit_readiness import (
    DIMENSIONS, REQUIREMENTS, RESULT_KEYS, STATUSES,
    build_claude_exit_readiness as build, validate_claude_exit_readiness as validate_result)
from tests.test_approval_scope_context_validation_prompt900 import (
    authority as make_authority, fx as fx900, scope_for)
from tests.test_implementation_permission_policy_prompt894 import (
    base_chain, conflict_chain, derive)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "claude_exit_readiness.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "claude_exit_readiness_prompt902.md")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FALSE_FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started",
               "executed")
(REQUEST, ANALYSIS, SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS, DESIGN, V885, BLUEPRINT, B887,
 CONTRACT, CREPORT, R889, BOUNDARY, IMPL) = range(16)


def run(op="create", **over):
    """Build readiness for a (possibly altered) context. An override may be f(context)->value."""
    auth, scope, chain, vres, policy, approval, avres, decision, dres = fx900(op)
    ctx = {"auth": auth, "scope": scope, "chain": chain, "vres": vres, "policy": policy,
           "approval": approval, "avres": avres, "decision": decision, "dres": dres}
    for key, value in over.items():
        ctx[key] = value(ctx) if callable(value) else value
    return build(ctx["auth"], ctx["scope"], *ctx["chain"], ctx["vres"], ctx["policy"],
                 ctx["approval"], ctx["avres"], ctx["decision"], ctx["dres"])


def chain_edit(index, **fields):
    def edit(ctx):
        chain = list(ctx["chain"])
        chain[index] = dict(chain[index], **fields)
        return chain
    return edit


def chain_none(index):
    return lambda ctx: ctx["chain"][:index] + [None] + ctx["chain"][index + 1:]


def change(key, **fields):
    return lambda ctx: dict(ctx[key], **fields)


def forbidden(*_a, **_k):
    raise AssertionError("forbidden operation attempted")


class ValidPathTests(unittest.TestCase):
    def test_valid_create_chain_is_ready_without_claude(self):
        r = run("create")
        self.assertEqual(r["status"], "ready_without_claude")
        self.assertIs(r["valid"], True)
        self.assertIs(r["claude_independent"], True)
        self.assertEqual(r["operation"], "create")

    def test_valid_improve_chain_is_ready_without_claude(self):
        r = run("improve")
        self.assertEqual(r["status"], "ready_without_claude")
        self.assertIs(r["claude_independent"], True)
        self.assertEqual(r["operation"], "improve")

    def test_missing_requirements_empty_when_ready(self):
        for op in ("create", "improve"):
            self.assertEqual(run(op)["missing_requirements"], [])

    def test_exact_fourteen_keys_in_order_and_integer_version(self):
        self.assertEqual(len(RESULT_KEYS), 14)
        for op in ("create", "improve"):
            self.assertEqual(list(run(op)), list(RESULT_KEYS))
        self.assertIs(type(run()["version"]), int)
        self.assertEqual(run()["version"], 1)

    def test_identity_comes_from_the_trusted_objects(self):
        r = run()
        self.assertEqual({k: r[k] for k in IDENTITY}, {
            "request_id": "evo_001", "implementation_request_id": "ir_001",
            "capability_name": "text_summarizer", "operation": "create"})
        self.assertEqual(r["reason"], "ready_without_claude")

    def test_all_permission_and_execution_flags_false_when_ready(self):
        for op in ("create", "improve"):
            r = run(op)
            for flag in FALSE_FLAGS:
                self.assertIs(r[flag], False, (op, flag))

    def test_ready_for_every_authority_type(self):
        auth0, scope0, chain, vres, policy, approval, avres, decision, dres = fx900("create")
        for authority_type in ("user", "system_policy", "trusted_internal_controller"):
            auth = make_authority(authority_type)
            r = build(auth, scope_for(auth), *chain, vres, policy, approval, avres, decision,
                      dres)
            self.assertEqual(r["status"], "ready_without_claude", authority_type)

    def test_status_vocabulary_is_exact_and_has_no_approval_status(self):
        self.assertEqual(STATUSES, (
            "ready_without_claude", "not_ready", "invalid_context", "context_mismatch",
            "unsupported_operation", "forbidden_execution_state", "validation_error"))
        for status in STATUSES:
            for word in ("approved", "authorized", "authorised", "granted", "permitted"):
                self.assertNotIn(word, status)

    def test_seventeen_dimensions_are_defined(self):
        self.assertEqual(len(DIMENSIONS), 17)
        self.assertEqual(len(set(DIMENSIONS)), 17)
        self.assertEqual(set(REQUIREMENTS) - set(DIMENSIONS),
                         {"context_consistent", "evaluation_completed"})


class NotReadyTests(unittest.TestCase):
    def test_every_missing_chain_stage_is_not_ready(self):
        for index in range(16):
            r = run(chain=chain_none(index))
            self.assertEqual(r["status"], "not_ready", index)
            self.assertIs(r["claude_independent"], False, index)
            self.assertEqual(len(r["missing_requirements"]), 1, index)
            self.assertIn(r["missing_requirements"][0], DIMENSIONS, index)

    def test_missing_stage_names_its_dimension(self):
        expected = {REQUEST: "request_identity_consistent", ANALYSIS: "analysis_valid",
                    SPEC: "specification_valid", PLAN: "definition_readiness_valid",
                    DESIGN: "implementation_design_valid",
                    BLUEPRINT: "implementation_blueprint_valid",
                    CONTRACT: "implementation_contract_valid",
                    BOUNDARY: "implementation_boundary_valid",
                    IMPL: "implementation_request_valid"}
        for index, requirement in expected.items():
            r = run(chain=chain_none(index))
            self.assertEqual(r["missing_requirements"], [requirement], index)

    def test_missing_later_stage_names_its_dimension(self):
        expected = {"vres": "implementation_request_validation_valid",
                    "policy": "controlled_autonomy_policy_valid",
                    "approval": "approval_request_valid", "avres": "approval_request_valid",
                    "decision": "approval_decision_valid", "dres": "approval_decision_valid",
                    "auth": "authority_scope_context_valid",
                    "scope": "authority_scope_context_valid"}
        for key, requirement in expected.items():
            r = run(**{key: None})
            self.assertEqual(r["status"], "not_ready", key)
            self.assertEqual(r["missing_requirements"], [requirement], key)
            self.assertTrue(all(r[k] is None for k in IDENTITY), key)

    def test_no_arguments_is_not_ready(self):
        r = build()
        self.assertEqual(r["status"], "not_ready")
        self.assertIs(r["valid"], False)
        self.assertTrue(validate_result(r)["valid"])


class ContextMismatchTests(unittest.TestCase):
    def test_request_id_mismatch_in_decision(self):
        r = run(decision=change("decision", request_id="evo_other"))
        self.assertEqual(r["status"], "context_mismatch")
        self.assertEqual(r["missing_requirements"], ["request_identity_consistent"])

    def test_capability_name_mismatch_in_scope(self):
        r = run(scope=change("scope", capability_name="other_capability"))
        self.assertEqual(r["status"], "context_mismatch")
        self.assertEqual(r["missing_requirements"], ["capability_identity_consistent"])

    def test_operation_mismatch_in_decision(self):
        r = run(decision=change("decision", operation="improve"))
        self.assertEqual(r["status"], "context_mismatch")
        self.assertEqual(r["missing_requirements"], ["operation_supported"])

    def test_authority_scope_authority_id_mismatch(self):
        r = run(scope=change("scope", authority_id="other_auth"))
        self.assertEqual(r["status"], "context_mismatch")
        self.assertEqual(r["missing_requirements"], ["authority_scope_context_valid"])

    def test_forged_individually_valid_request_validation_result(self):
        r = run(vres=change("vres", implementation_request_id="ir_forged"))
        self.assertEqual(r["status"], "context_mismatch")
        self.assertEqual(r["missing_requirements"], ["implementation_request_validation_valid"])

    def test_forged_decision_validation_result(self):
        r = run(dres=change("dres", decision_id="dec_forged"))
        self.assertEqual(r["status"], "context_mismatch")

    def test_mixed_chains_do_not_pass(self):
        create = fx900("create")
        improve = fx900("improve")
        r = build(create[0], create[1], *improve[2], create[3], create[4], create[5],
                  create[6], create[7], create[8])
        self.assertNotEqual(r["status"], "ready_without_claude")
        self.assertIs(r["claude_independent"], False)


class UnsupportedOperationTests(unittest.TestCase):
    def test_improve_or_conflict_chain_is_unsupported_operation(self):
        chain = conflict_chain(base_chain()[3:])
        r = run(chain=chain, vres=derive(chain), decision=fx900()[7])
        self.assertEqual(r["status"], "unsupported_operation")
        self.assertEqual(r["missing_requirements"], ["operation_supported"])
        self.assertIs(r["claude_independent"], False)

    def test_conflict_chain_mixed_with_improve_tail_is_never_ready(self):
        chain = conflict_chain(base_chain("improve")[3:])
        r = run(chain=chain, vres=derive(chain), decision=fx900()[7])
        self.assertIn(r["status"], ("unsupported_operation", "context_mismatch"))
        self.assertIs(r["claude_independent"], False)

    def test_unsupported_result_is_valid_shape_and_flags_false(self):
        chain = conflict_chain(base_chain()[3:])
        r = run(chain=chain, vres=derive(chain), decision=fx900()[7])
        self.assertTrue(validate_result(r)["valid"])
        for flag in FALSE_FLAGS:
            self.assertIs(r[flag], False)


class ForgedUpstreamTests(unittest.TestCase):
    def test_forged_valid_true_on_failed_request_validation_is_rejected(self):
        forged = dict(fx900()[3], status="invalid_boundary", valid=True)
        r = run(vres=forged)
        self.assertNotEqual(r["status"], "ready_without_claude")
        self.assertIs(r["claude_independent"], False)

    def test_forged_boundary_result_is_rejected(self):
        r = run(chain=chain_edit(BOUNDARY, status="ready", reason="forged"))
        self.assertNotEqual(r["status"], "ready_without_claude")

    def test_altered_later_stages_are_rejected(self):
        for over in ({"policy": change("policy", implementation_request_id="ir_forged")},
                     {"approval": change("approval", approval_request_id="apr_forged")},
                     {"decision": change("decision", decision_id="dec_forged")},
                     {"decision": change("decision", approval_status="approved")},
                     {"decision": change("decision", approved=True)}):
            r = run(**over)
            self.assertNotEqual(r["status"], "ready_without_claude", over)
            self.assertIs(r["claude_independent"], False, over)

    def test_altered_stage_content_is_rejected(self):
        for index in (ANALYSIS, SPEC, DESIGN, BLUEPRINT, CONTRACT):
            r = run(chain=chain_edit(index, forged_field="x"))
            self.assertNotEqual(r["status"], "ready_without_claude", index)


class ForbiddenExecutionStateTests(unittest.TestCase):
    def test_implementation_allowed_true_is_forbidden(self):
        r = run(chain=chain_edit(IMPL, implementation_allowed=True))
        self.assertEqual(r["status"], "forbidden_execution_state")
        self.assertEqual(r["missing_requirements"], ["no_forbidden_execution_state"])

    def test_execution_allowed_true_is_forbidden(self):
        r = run(chain=chain_edit(IMPL, execution_allowed=True))
        self.assertEqual(r["status"], "forbidden_execution_state")

    def test_implementation_started_true_is_forbidden(self):
        r = run(decision=change("decision", implementation_started=True))
        self.assertEqual(r["status"], "forbidden_execution_state")

    def test_executed_true_is_forbidden(self):
        r = run(chain=chain_edit(BOUNDARY, executed=True))
        self.assertEqual(r["status"], "forbidden_execution_state")

    def test_every_flag_in_every_supplied_object_is_forbidden(self):
        for flag in FALSE_FLAGS:
            for key in ("auth", "scope", "vres", "policy", "approval", "avres", "decision",
                        "dres"):
                r = run(**{key: change(key, **{flag: True})})
                self.assertEqual(r["status"], "forbidden_execution_state", (flag, key))
            for index in range(16):
                r = run(chain=chain_edit(index, **{flag: True}))
                self.assertEqual(r["status"], "forbidden_execution_state", (flag, index))

    def test_truthy_non_bool_flag_is_forbidden(self):
        r = run(decision=change("decision", executed=1))
        self.assertEqual(r["status"], "forbidden_execution_state")

    def test_nested_flag_is_forbidden(self):
        r = run(chain=chain_edit(DESIGN, nested={"deep": [{"executed": True}]}))
        self.assertEqual(r["status"], "forbidden_execution_state")

    def test_forbidden_takes_precedence_over_missing_stages(self):
        r = run(policy=None, decision=None, chain=chain_edit(IMPL, execution_allowed=True))
        self.assertEqual(r["status"], "forbidden_execution_state")

    def test_forbidden_result_keeps_all_flags_false_and_no_identity(self):
        r = run(chain=chain_edit(IMPL, execution_allowed=True))
        for flag in FALSE_FLAGS:
            self.assertIs(r[flag], False)
        self.assertIs(r["claude_independent"], False)
        self.assertTrue(all(r[k] is None for k in IDENTITY))
        self.assertTrue(validate_result(r)["valid"])


class RobustnessTests(unittest.TestCase):
    def test_malformed_input_never_raises(self):
        junk = (None, 1, 1.5, True, "x", b"x", [], (), {}, [1, 2], {"a": 1}, object(),
                float("nan"))
        for value in junk:
            for count in (0, 1, 5, 24):
                r = build(*([value] * count))
                self.assertIn(r["status"], STATUSES)
                self.assertTrue(validate_result(r)["valid"], (value, count))
                self.assertIsNot(r["status"], "ready_without_claude")

    def test_self_referencing_and_deep_inputs_do_not_raise(self):
        cyclic = {}
        cyclic["self"] = cyclic
        deep = {}
        node = deep
        for _ in range(500):
            node["n"] = {}
            node = node["n"]
        for value in (cyclic, deep, [cyclic] * 10):
            r = build(*([value] * 24))
            self.assertIn(r["status"], STATUSES)
            self.assertTrue(validate_result(r)["valid"])

    def test_hostile_objects_do_not_raise(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError(name)

            def __bool__(self):
                raise RuntimeError("bool")

        class BadDict(dict):
            def get(self, *a, **k):
                raise RuntimeError("get")

        for value in (Boom(), BadDict(a=1), {"executed": Boom()}):
            r = build(*([value] * 24))
            self.assertIn(r["status"], STATUSES)

    def test_internal_failure_becomes_validation_error(self):
        with mock.patch.object(mod, "validate_capability_implementation_request_context",
                               side_effect=RuntimeError("boom")):
            r = run()
        self.assertEqual(r["status"], "validation_error")
        self.assertEqual(r["missing_requirements"], ["evaluation_completed"])
        self.assertTrue(validate_result(r)["valid"])


class DeterminismTests(unittest.TestCase):
    def test_repeated_results_are_equal(self):
        for op in ("create", "improve"):
            first = run(op)
            for _ in range(5):
                self.assertEqual(run(op), first)

    def test_results_are_fresh_dicts_and_lists(self):
        a, b = run(), run()
        self.assertIsNot(a, b)
        self.assertIsNot(a["missing_requirements"], b["missing_requirements"])
        a["status"] = "changed"
        a["missing_requirements"].append("x")
        self.assertEqual(run()["status"], "ready_without_claude")
        self.assertEqual(run()["missing_requirements"], [])

    def test_inputs_are_not_modified(self):
        for op in ("create", "improve"):
            ctx = fx900(op)
            before = copy.deepcopy(ctx)
            auth, scope, chain, vres, policy, approval, avres, decision, dres = ctx
            build(auth, scope, *chain, vres, policy, approval, avres, decision, dres)
            self.assertEqual(ctx, before)


class ResultValidatorTests(unittest.TestCase):
    def good(self):
        return run()

    def test_accepts_every_status_produced_by_the_builder(self):
        chain = conflict_chain(base_chain()[3:])
        results = [run(), run("improve"), run(policy=None),
                   run(decision=change("decision", request_id="x")),
                   run(chain=chain, vres=derive(chain), decision=fx900()[7]),
                   run(chain=chain_edit(IMPL, executed=True)), build()]
        self.assertGreaterEqual(len({r["status"] for r in results}), 5)
        for r in results:
            self.assertTrue(validate_result(r)["valid"], r)

    def test_rejects_non_dict_and_bad_shape(self):
        for value in (None, 1, "x", [], (), [self.good()]):
            self.assertFalse(validate_result(value)["valid"])
        self.assertFalse(validate_result({})["valid"])
        for key in RESULT_KEYS:
            r = self.good()
            del r[key]
            self.assertFalse(validate_result(r)["valid"], key)
        self.assertFalse(validate_result(dict(self.good(), extra=1))["valid"])
        self.assertFalse(validate_result(dict(self.good(), approved=True))["valid"])

    def test_rejects_altered_version_status_and_booleans(self):
        good = self.good()
        for bad in (dict(good, version=True), dict(good, version="1"), dict(good, version=2),
                    dict(good, status="approved"), dict(good, status="authorized"),
                    dict(good, status=None), dict(good, valid=False),
                    dict(good, valid=1), dict(good, claude_independent=False),
                    dict(good, claude_independent=1), dict(good, reason="other")):
            self.assertFalse(validate_result(bad)["valid"], bad)

    def test_rejects_independence_without_validity(self):
        r = run(policy=None)
        self.assertFalse(validate_result(dict(r, claude_independent=True))["valid"])
        self.assertFalse(validate_result(dict(r, valid=True))["valid"])
        self.assertFalse(validate_result(dict(r, status="ready_without_claude"))["valid"])

    def test_rejects_every_true_permission_or_execution_flag(self):
        for flag in FALSE_FLAGS:
            for value in (True, 1, "False", None):
                self.assertFalse(validate_result(dict(self.good(), **{flag: value}))["valid"],
                                 (flag, value))

    def test_rejects_altered_missing_requirements(self):
        good, bad = self.good(), run(policy=None)
        for r in (dict(good, missing_requirements=["analysis_valid"]),
                  dict(good, missing_requirements=None),
                  dict(bad, missing_requirements=[]),
                  dict(bad, missing_requirements=["not_a_requirement"]),
                  dict(bad, missing_requirements=["analysis_valid", "approval_request_valid"]),
                  dict(bad, missing_requirements=("analysis_valid",)),
                  dict(bad, missing_requirements=[1])):
            self.assertFalse(validate_result(r)["valid"], r)

    def test_rejects_altered_identity(self):
        good = self.good()
        for bad in (dict(good, operation="delete"), dict(good, operation="improve_or_conflict"),
                    dict(good, request_id=None), dict(good, capability_name=""),
                    dict(good, implementation_request_id=5),
                    dict(run(policy=None), request_id="evo_001")):
            self.assertFalse(validate_result(bad)["valid"], bad)

    def test_validator_report_shape_and_flags(self):
        for value in (self.good(), None, {}):
            report = validate_result(value)
            self.assertEqual(sorted(report), sorted(["errors", "execution_allowed", "executed", "valid"]))
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)

    def test_validator_never_raises_and_does_not_modify(self):
        good = self.good()
        before = copy.deepcopy(good)
        validate_result(good)
        self.assertEqual(good, before)
        for value in (object(), float("nan"), {"status": object()}, {k: object() for k in RESULT_KEYS}):
            self.assertFalse(validate_result(value)["valid"])


class StaticSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def imported(self):
        names = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.append((node.module or "").split(".")[0])
        return names

    def test_only_project_packages_are_imported(self):
        self.assertTrue(set(self.imported()) <= {"autonomy", "capabilities"},
                        set(self.imported()))

    def test_no_forbidden_modules_are_imported(self):
        banned = {"os", "sys", "io", "socket", "subprocess", "importlib", "urllib", "http",
                  "requests", "ctypes", "pickle", "shutil", "pathlib", "tempfile", "glob",
                  "sqlite3", "json", "threading", "multiprocessing", "asyncio", "ssl",
                  "anthropic", "openai", "builtins", "types", "inspect", "ast"}
        self.assertFalse(banned & set(self.imported()))

    def test_no_dangerous_calls(self):
        banned = {"exec", "eval", "open", "compile", "__import__", "getattr", "setattr",
                  "delattr", "globals", "locals", "vars", "input", "breakpoint"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, banned, node.func.id)

    def test_no_dangerous_attributes(self):
        banned = {"system", "popen", "Popen", "run", "call", "write", "read", "remove",
                  "unlink", "mkdir", "makedirs", "rename", "connect", "urlopen", "load",
                  "loads", "dump", "dumps", "__dict__", "__class__", "__globals__",
                  "__builtins__", "write_text", "read_text", "environ", "getenv"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, banned, node.attr)

    def test_builder_runs_without_io_network_or_subprocess(self):
        import builtins
        patches = [mock.patch.object(builtins, "open", side_effect=forbidden),
                   mock.patch.object(socket, "socket", side_effect=forbidden),
                   mock.patch.object(socket, "create_connection", side_effect=forbidden),
                   mock.patch.object(subprocess, "Popen", side_effect=forbidden),
                   mock.patch.object(subprocess, "run", side_effect=forbidden),
                   mock.patch.object(os, "system", side_effect=forbidden),
                   mock.patch.object(os, "listdir", side_effect=forbidden),
                   mock.patch.object(builtins, "exec", side_effect=forbidden),
                   mock.patch.object(builtins, "eval", side_effect=forbidden)]
        ctx = fx900()
        for p in patches:
            p.start()
        try:
            r = build(ctx[0], ctx[1], *ctx[2], *ctx[3:])
            validate_result(r)
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertEqual(r["status"], "ready_without_claude")

    def test_module_defines_only_the_two_public_functions(self):
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(sorted(public),
                         ["build_claude_exit_readiness", "validate_claude_exit_readiness"])


class NoClaudeDependencyTests(unittest.TestCase):
    def test_no_claude_or_external_ai_dependency_in_code(self):
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id.lower())
            elif isinstance(node, ast.Attribute):
                names.add(node.attr.lower())
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.update(node.value.lower().split())
        for word in ("anthropic", "openai", "gemini", "api_key", "apikey", "requests",
                     "http", "https", "claude_api", "messages.create"):
            self.assertNotIn(word, names)

    def test_no_production_module_references_the_new_module(self):
        for package in ("capabilities", "agent", "core", "execution", "planning", "tools"):
            folder = os.path.join(ROOT, package)
            if not os.path.isdir(folder):
                continue
            for fname in sorted(os.listdir(folder)):
                if fname.endswith(".py"):
                    with open(os.path.join(folder, fname), encoding="utf-8") as handle:
                        self.assertNotIn("claude_exit_readiness", handle.read(), fname)

    def test_documentation_exists_and_states_descriptive_only(self):
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read().lower()
        for phrase in ("claude_independent", "descriptive", "implementation_allowed",
                       "ready_without_claude", "section 18"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
