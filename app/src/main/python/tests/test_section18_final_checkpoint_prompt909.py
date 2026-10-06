"""
Prompt 909 - Section 18: final autonomy validation checkpoint (test-only).

End-to-end deterministic validation of the complete Section 18 chain, built only through the
existing public builders and validators:

    902 claude_exit_readiness -> 903 internal_next_stage -> 904 internal_stage_decision
    -> 905 internal_evolution_input -> 906 internal_evolution_result
    -> 907 internal_evolution_result_validation -> 908 final_internal_evolution_gate

No production module is added or changed by this checkpoint.

Run (from app/src/main/python/):
    python -m unittest tests.test_section18_final_checkpoint_prompt909 -v
"""

import ast
import copy
import os
import re
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy import (claude_exit_readiness as m902, final_internal_evolution_gate as m908,
                      internal_evolution_input as m905, internal_evolution_result as m906,
                      internal_evolution_result_validation as m907, internal_next_stage as m903,
                      internal_stage_decision as m904)
from tests.test_claude_exit_readiness_prompt902 import run as run902

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))))
DOC = os.path.join(PROJECT, "docs", "section18_final_checkpoint_prompt909.md")
MODULES = (m902, m903, m904, m905, m906, m907, m908)
MODULE_FILES = ("claude_exit_readiness.py", "internal_next_stage.py", "internal_stage_decision.py",
                "internal_evolution_input.py", "internal_evolution_result.py",
                "internal_evolution_result_validation.py", "final_internal_evolution_gate.py")
IDENTITY = ("request_id", "implementation_request_id", "capability_name", "operation")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")
STAGE = "controlled_internal_evolution"
EXPECTED_STATUSES = {902: "ready_without_claude", 903: "ready_for_internal_stage",
                     904: "stage_ready", 905: "ready", 906: "evaluated", 907: "valid",
                     908: "ready_for_final_autonomy_validation"}

# builders for prompts 903..908; each takes (previous_result, expected_identity=None)
BUILDERS = {902: m903.build_internal_next_stage, 903: m904.build_internal_stage_decision,
            904: m905.build_internal_evolution_input, 905: m906.build_internal_evolution_result,
            906: m907.validate_internal_evolution_result_context,
            907: m908.build_final_internal_evolution_gate}
VALIDATORS = {902: m902.validate_claude_exit_readiness, 903: m903.validate_internal_next_stage,
              904: m904.validate_internal_stage_decision,
              905: m905.validate_internal_evolution_input,
              906: m906.validate_internal_evolution_result}

_CACHE = {}


def chain(op="create"):
    """Fresh copy of {902: ..., 908: ...} results for the valid chain of an operation."""
    if op not in _CACHE:
        results = {902: run902(op)}
        for prompt in range(902, 908):
            results[prompt + 1] = BUILDERS[prompt](results[prompt])
        _CACHE[op] = results
    return copy.deepcopy(_CACHE[op])


def advance(prompt, result, expected=None):
    """Run the builders for prompts after `prompt` on `result`; return the final gate result."""
    current = result
    for step in range(prompt, 908):
        current = BUILDERS[step](current, expected) if step == prompt else BUILDERS[step](current)
    return current


def walk_strings(obj):
    if type(obj) is str:
        yield obj
    elif type(obj) is dict:
        for key, value in obj.items():
            yield from walk_strings(key)
            yield from walk_strings(value)
    elif type(obj) in (list, tuple):
        for value in obj:
            yield from walk_strings(value)


def walk_keys(obj):
    if type(obj) is dict:
        for key, value in obj.items():
            yield key
            yield from walk_keys(value)
    elif type(obj) in (list, tuple):
        for value in obj:
            yield from walk_keys(value)


def assert_not_final(test, out):
    test.assertIs(out["valid"], False)
    test.assertNotEqual(out["status"], EXPECTED_STATUSES[908])
    for key in IDENTITY + ("stage", "gate", "summary"):
        test.assertIsNone(out[key])
    test.assertEqual(out["requirements_met"], [])
    for key in FLAGS:
        test.assertIs(out[key], False)


class ValidCreatePathTests(unittest.TestCase):
    def test_create_chain_statuses(self):
        results = chain("create")
        for prompt, status in EXPECTED_STATUSES.items():
            self.assertEqual(results[prompt]["status"], status, prompt)
            self.assertIs(results[prompt]["valid"], True, prompt)

    def test_improve_chain_statuses(self):
        results = chain("improve")
        for prompt, status in EXPECTED_STATUSES.items():
            self.assertEqual(results[prompt]["status"], status, prompt)
            self.assertIs(results[prompt]["valid"], True, prompt)

    def test_final_gate_create(self):
        gate = chain("create")[908]
        self.assertIs(gate["valid"], True)
        self.assertEqual(gate["gate"], "final_internal_evolution_gate")
        self.assertEqual(gate["stage"], STAGE)
        for key in FLAGS:
            self.assertIs(gate[key], False)

    def test_final_gate_improve(self):
        gate = chain("improve")[908]
        self.assertIs(gate["valid"], True)
        self.assertEqual(gate["gate"], "final_internal_evolution_gate")
        self.assertEqual(gate["stage"], STAGE)
        for key in FLAGS:
            self.assertIs(gate[key], False)

    def test_final_gate_shape_and_requirements(self):
        for op in ("create", "improve"):
            gate = chain(op)[908]
            self.assertEqual(tuple(gate), m908.OUTPUT_KEYS)
            self.assertEqual(gate["requirements_met"], list(m908.REQUIREMENTS_MET))
            self.assertEqual(gate["requirements_missing"],
                             ["implementation_permission", "execution_permission",
                              "final_autonomy_validation"])

    def test_operations_are_the_two_supported_paths(self):
        self.assertEqual(chain("create")[908]["operation"], "create")
        self.assertEqual(chain("improve")[908]["operation"], "improve")
        self.assertEqual(m902.SUPPORTED_OPERATIONS, ("create", "improve"))

    def test_public_validators_accept_every_valid_stage(self):
        for op in ("create", "improve"):
            results = chain(op)
            for prompt, validator in VALIDATORS.items():
                self.assertIs(validator(results[prompt])["valid"], True, (op, prompt))

    def test_prompt907_and_908_independently_revalidate(self):
        for op in ("create", "improve"):
            results = chain(op)
            again = m907.validate_internal_evolution_result_context(results[906])
            self.assertEqual(again, results[907])
            self.assertEqual(m908.build_final_internal_evolution_gate(results[907]), results[908])

    def test_stage_and_next_stage_continuity(self):
        for op in ("create", "improve"):
            r = chain(op)
            self.assertEqual(r[903]["next_stage"], STAGE)
            self.assertEqual(r[904]["next_stage"], STAGE)
            for prompt in (905, 906, 907, 908):
                self.assertEqual(r[prompt]["stage"], STAGE, prompt)

    def test_chain_is_deterministic(self):
        for op in ("create", "improve"):
            first = run902(op)
            second = run902(op)
            self.assertEqual(first, second)
            self.assertEqual(advance(902, first), advance(902, second))
            self.assertEqual(advance(902, first), chain(op)[908])

    def test_builders_do_not_mutate_their_inputs(self):
        for op in ("create", "improve"):
            results = chain(op)
            for prompt in range(902, 908):
                before = copy.deepcopy(results[prompt])
                BUILDERS[prompt](results[prompt])
                self.assertEqual(results[prompt], before, prompt)

    def test_outputs_are_fresh_dicts(self):
        results = chain("create")
        gate = advance(906, results[906])
        gate["requirements_met"].append("tampered")
        gate["executed"] = True
        self.assertEqual(advance(906, results[906]), chain("create")[908])

    def test_create_and_improve_differ_only_by_operation(self):
        create, improve = chain("create")[908], chain("improve")[908]
        diff = {k for k in create if create[k] != improve[k]}
        self.assertTrue(diff <= {"operation", "request_id", "implementation_request_id",
                                 "capability_name"})
        self.assertIn("operation", diff)


class IdentityContinuityTests(unittest.TestCase):
    def test_identity_constant_from_902_to_908_create(self):
        r = chain("create")
        for key in IDENTITY:
            self.assertEqual({r[p][key] for p in range(902, 909)}, {r[902][key]}, key)

    def test_identity_constant_from_902_to_908_improve(self):
        r = chain("improve")
        for key in IDENTITY:
            self.assertEqual({r[p][key] for p in range(902, 909)}, {r[902][key]}, key)

    def test_identity_values_are_nonempty_strings(self):
        for op in ("create", "improve"):
            for prompt, result in chain(op).items():
                for key in IDENTITY:
                    self.assertIs(type(result[key]), str)
                    self.assertTrue(result[key].strip())

    def test_expected_identity_accepted_at_every_builder(self):
        for op in ("create", "improve"):
            r = chain(op)
            expected = {key: r[902][key] for key in IDENTITY}
            for prompt in range(902, 908):
                out = BUILDERS[prompt](r[prompt], expected)
                self.assertIs(out["valid"], True, (op, prompt))
                self.assertEqual(out["status"], EXPECTED_STATUSES[prompt + 1])

    def test_expected_identity_mismatch_rejected_at_every_builder(self):
        for op in ("create", "improve"):
            r = chain(op)
            for prompt in range(902, 908):
                for key in IDENTITY:
                    wrong = {key: r[902][key] + "_other"}
                    out = BUILDERS[prompt](r[prompt], wrong)
                    self.assertIs(out["valid"], False, (op, prompt, key))
                    self.assertEqual(out["status"], "context_mismatch", (op, prompt, key))

    def test_mismatch_cannot_reach_the_final_gate(self):
        r = chain("create")
        for prompt in range(902, 908):
            bad = BUILDERS[prompt](r[prompt], {"operation": "improve"})
            assert_not_final(self, advance(prompt + 1, bad) if prompt < 907 else bad)

    def test_malformed_expected_identity_is_rejected(self):
        r = chain("create")
        for expected in ("x", [], 5, {"unknown": "x"}, {"request_id": 7}):
            out = m908.build_final_internal_evolution_gate(r[907], expected)
            self.assertEqual(out["status"], "context_mismatch")
            self.assertIs(out["valid"], False)

    def test_identity_rewrite_between_stages_is_detected(self):
        r = chain("create")
        for key in IDENTITY:
            forged = dict(r[906], **{key: r[906][key] + "_x"})
            out = m908.build_final_internal_evolution_gate(
                m907.validate_internal_evolution_result_context(
                    forged, {k: r[902][k] for k in IDENTITY}))
            assert_not_final(self, out)


class SafetyPropertyTests(unittest.TestCase):
    def test_flags_false_at_every_stage(self):
        for op in ("create", "improve"):
            for prompt, result in chain(op).items():
                for key in FLAGS:
                    self.assertIs(result[key], False, (op, prompt, key))

    def test_no_approval_or_permission_fields_anywhere(self):
        banned = {"approved", "approval_granted", "authorized", "authorization_granted",
                  "permission_granted", "implementation_approved", "execution_approved"}
        for op in ("create", "improve"):
            for prompt, result in chain(op).items():
                self.assertEqual(set(walk_keys(result)) & banned, set(), (op, prompt))

    def test_no_code_patch_command_or_file_fields(self):
        banned = {"code", "source", "source_code", "patch", "diff", "command", "commands", "cmd",
                  "script", "path", "paths", "file", "files", "api_key", "token", "url", "urls"}
        for op in ("create", "improve"):
            for prompt, result in chain(op).items():
                self.assertEqual(set(walk_keys(result)) & banned, set(), (op, prompt))

    def test_no_executable_or_service_text_in_any_stage(self):
        for op in ("create", "improve"):
            for prompt, result in chain(op).items():
                for text in walk_strings(result):
                    low = text.lower()
                    fixed_prose = text in (m906.SUMMARY, m908.SUMMARY)  # fixed sentences use ";"
                    for marker in () if fixed_prose else m908._CODE_MARKERS:
                        self.assertNotIn(marker, low, (op, prompt, text))
                    if text in (m902.STATUS_READY, "claude_independent"):  # Prompt 902 contract labels naming the Claude exit
                        continue
                    words = set(re.split(r"[^a-z0-9]+", low))
                    self.assertEqual(words & m908._EXTERNAL_WORDS, set(), (op, prompt, text))

    def test_only_primitive_values_in_every_stage(self):
        def check(value):
            if type(value) in (str, int, bool, type(None)):
                return
            self.assertIn(type(value), (list, dict))
            for item in (value.values() if type(value) is dict else value):
                check(item)
        for prompt, result in chain("create").items():
            check(result)

    def test_no_implementation_or_execution_reported(self):
        for op in ("create", "improve"):
            for prompt, result in chain(op).items():
                self.assertIs(result["implementation_started"], False)
                self.assertIs(result["executed"], False)
                self.assertIs(result["implementation_allowed"], False)
                self.assertIs(result["execution_allowed"], False)

    def test_outstanding_permissions_remain_missing(self):
        for op in ("create", "improve"):
            gate = chain(op)[908]
            self.assertIn("implementation_permission", gate["requirements_missing"])
            self.assertIn("execution_permission", gate["requirements_missing"])
            self.assertIn("final_autonomy_validation", gate["requirements_missing"])

    def test_chain_runs_without_io_network_or_processes(self):
        results = chain("create")

        def boom(*args, **kwargs):
            raise AssertionError("side effect attempted")

        import subprocess
        import urllib.request
        with mock.patch("builtins.open", boom), mock.patch("socket.socket", boom), \
                mock.patch("subprocess.Popen", boom), mock.patch("subprocess.run", boom), \
                mock.patch("os.system", boom), mock.patch("os.remove", boom), \
                mock.patch("os.rename", boom), mock.patch("os.mkdir", boom), \
                mock.patch("urllib.request.urlopen", boom):
            final = advance(902, results[902])
        self.assertEqual(final, chain("create")[908])
        self.assertTrue(subprocess and urllib.request)

    def test_chain_does_not_touch_the_filesystem(self):
        def snapshot():
            out = {}
            for folder in (os.path.join(ROOT, "autonomy"), os.path.join(PROJECT, "docs")):
                for name in sorted(os.listdir(folder)):
                    path = os.path.join(folder, name)
                    if os.path.isfile(path):
                        stat = os.stat(path)
                        out[path] = (stat.st_size, stat.st_mtime_ns)
            return out
        before = snapshot()
        advance(902, run902("improve"))
        self.assertEqual(snapshot(), before)

    def test_no_environment_or_api_key_dependency(self):
        for module in MODULES:
            with open(module.__file__.replace(".pyc", ".py"), encoding="utf-8") as handle:
                source = handle.read()
            for word in ("environ", "getenv", "dotenv", "ANTHROPIC", "OPENAI"):
                self.assertNotIn(word, source, module.__name__)

    def test_no_self_modification_or_upgrade_hooks(self):
        for module in MODULES:
            public = [n for n in dir(module) if not n.startswith("_") and callable(getattr(module, n))
                      and getattr(getattr(module, n), "__module__", "") == module.__name__]
            for name in public:
                for word in ("upgrade", "patch", "install", "apply", "commit", "execute_", "run_",
                             "write", "save", "generate"):
                    self.assertNotIn(word, name, (module.__name__, name))


class StaticChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = {}
        cls.sources = {}
        for name in MODULE_FILES:
            with open(os.path.join(ROOT, "autonomy", name), encoding="utf-8") as handle:
                cls.sources[name] = handle.read()
            cls.trees[name] = ast.parse(cls.sources[name])

    def test_all_seven_modules_exist(self):
        self.assertEqual(len(MODULE_FILES), 7)
        for name in MODULE_FILES:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "autonomy", name)), name)

    def test_each_prompt_has_a_doc(self):
        docs = ("claude_exit_readiness_prompt902.md", "internal_next_stage_prompt903.md",
                "internal_stage_decision_prompt904.md", "internal_evolution_input_prompt905.md",
                "internal_evolution_result_prompt906.md",
                "internal_evolution_result_validation_prompt907.md",
                "final_internal_evolution_gate_prompt908.md")
        for name in docs:
            self.assertTrue(os.path.isfile(os.path.join(PROJECT, "docs", name)), name)

    def test_no_forbidden_imports(self):
        forbidden = {"subprocess", "socket", "urllib", "requests", "http", "anthropic", "openai",
                     "pathlib", "os", "sys", "threading", "shutil", "tempfile", "importlib",
                     "ctypes", "multiprocessing", "asyncio", "ssl", "sqlite3"}
        for name, tree in self.trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    roots = {(node.module or "").split(".")[0]}
                else:
                    continue
                self.assertEqual(roots & forbidden, set(), name)

    def test_no_forbidden_calls(self):
        forbidden = {"open", "exec", "eval", "compile", "__import__", "input", "print", "setattr",
                     "delattr", "globals", "system", "popen", "Popen", "socket", "urlopen",
                     "write", "remove", "rename", "mkdir"}
        for name, tree in self.trees.items():
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            self.assertEqual((names | attrs) & forbidden, set(), name)

    def test_no_global_state_or_async(self):
        for name, tree in self.trees.items():
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef,
                                                ast.Await, ast.Yield), name)

    def test_section18_modules_import_only_inside_the_chain(self):
        allowed = {"re", "autonomy", "capabilities"}  # 902 re-uses the capability validators
        for name, tree in self.trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    roots = {(node.module or "").split(".")[0]}
                else:
                    continue
                self.assertTrue(roots <= allowed, (name, roots))

    def test_version_constants_are_one(self):
        for module in MODULES[:-1]:
            self.assertEqual(module.RESULT_VERSION, 1, module.__name__)
        self.assertEqual(m908.GATE_VERSION, 1)

    def test_final_module_has_exactly_one_public_function(self):
        public = [n.name for n in self.trees["final_internal_evolution_gate.py"].body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, ["build_final_internal_evolution_gate"])

    def test_checkpoint_is_test_only(self):
        autonomy = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                          if n.endswith(".py"))
        self.assertFalse([n for n in autonomy if "909" in n or "section18" in n])
        self.assertFalse([n for n in autonomy if "checkpoint" in n])


class NegativePathTests(unittest.TestCase):
    def test_non_dict_inputs_at_the_final_gate(self):
        for bad in (None, [], (), "valid", 7, True, object(), [chain("create")[907]]):
            assert_not_final(self, m908.build_final_internal_evolution_gate(bad))

    def test_every_earlier_stage_result_is_not_a_valid_final_input(self):
        r = chain("create")
        for prompt in (902, 903, 904, 905, 906, 908):
            assert_not_final(self, m908.build_final_internal_evolution_gate(r[prompt]))

    def test_missing_key_at_every_stage(self):
        r = chain("create")
        for prompt in range(902, 908):
            for key in list(r[prompt]):
                broken = dict(r[prompt])
                del broken[key]
                assert_not_final(self, advance(prompt, broken))

    def test_unexpected_key_at_every_stage(self):
        r = chain("create")
        for prompt in range(902, 908):
            assert_not_final(self, advance(prompt, dict(r[prompt], extra="x")))

    def test_forged_valid_true_on_a_not_ready_stage(self):
        r = chain("create")
        for prompt, status in ((902, "not_ready"), (903, "not_ready"), (904, "not_ready"),
                               (905, "not_ready"), (906, "not_ready"),
                               (907, "invalid_result")):
            assert_not_final(self, advance(prompt, dict(r[prompt], status=status, valid=True)))

    def test_valid_false_on_a_good_stage_result(self):
        r = chain("improve")
        for prompt in range(902, 908):
            assert_not_final(self, advance(prompt, dict(r[prompt], valid=False)))

    def test_wrong_status_at_every_stage(self):
        r = chain("create")
        for prompt in range(902, 908):
            for status in ("bogus", "", None, "evaluated_x", "VALID"):
                assert_not_final(self, advance(prompt, dict(r[prompt], status=status)))

    def test_wrong_stage_at_stages_that_carry_one(self):
        r = chain("create")
        for prompt in (905, 906, 907):
            for stage in ("capability_evolution", "claude_exit", "", None, 3):
                assert_not_final(self, advance(prompt, dict(r[prompt], stage=stage)))

    def test_wrong_next_stage_at_stages_that_carry_one(self):
        r = chain("create")
        for prompt in (903, 904):
            for stage in ("somewhere_else", "", None):
                assert_not_final(self, advance(prompt, dict(r[prompt], next_stage=stage)))

    def test_wrong_result_type(self):
        r = chain("create")
        for kind in ("executable_result", "implementation", "", None):
            assert_not_final(self, advance(906, dict(r[906], result_type=kind)))
            assert_not_final(self, advance(907, dict(r[907], result_type=kind)))

    def test_wrong_decision_and_goal_labels(self):
        r = chain("create")
        assert_not_final(self, advance(904, dict(r[904], decision="proceed_and_execute")))
        assert_not_final(self, advance(905, dict(r[905], goal="implement_capability")))

    def test_requirement_tampering(self):
        r = chain("create")
        assert_not_final(self, advance(906, dict(r[906], requirements_met=["x"])))
        assert_not_final(self, advance(906, dict(r[906], requirements_missing=[])))
        assert_not_final(self, advance(902, dict(r[902], missing_requirements=["x"])))
        gate_in = dict(r[907], errors=[{"code": "x", "where": "y"}])
        assert_not_final(self, advance(907, gate_in))

    def test_each_forbidden_flag_true_at_every_stage(self):
        r = chain("create")
        for prompt in range(902, 908):
            for key in FLAGS:
                assert_not_final(self, advance(prompt, dict(r[prompt], **{key: True})))

    def test_truthy_non_bool_and_nested_forbidden_state(self):
        r = chain("create")
        for prompt in range(902, 908):
            assert_not_final(self, advance(prompt, dict(r[prompt], executed=1)))
            assert_not_final(self, advance(prompt, dict(r[prompt],
                                                         extra=[{"execution_allowed": True}])))

    def test_approval_and_permission_states_cannot_pass(self):
        r = chain("create")
        for prompt in range(902, 908):
            for key in ("approved", "approval_granted", "authorized", "authorization_granted",
                        "permission_granted", "implementation_approved", "execution_approved"):
                assert_not_final(self, advance(prompt, dict(r[prompt], **{key: True})))

    def test_forbidden_state_gets_the_forbidden_status_at_the_gate(self):
        r = chain("create")
        for key in FLAGS:
            out = m908.build_final_internal_evolution_gate(dict(r[907], **{key: True}))
            self.assertEqual(out["status"], "forbidden_execution_state")

    def test_code_like_identity_cannot_pass(self):
        r = chain("create")
        for text in ("def run():", "import os", "rm -rf x", "a;b", "a&&b", "$(x)", "{x}",
                     "a\nb", "x://y", "diff --git"):
            for key in IDENTITY:
                assert_not_final(self, advance(906, dict(r[906], **{key: text})))
                assert_not_final(self, advance(907, dict(r[907], **{key: text})))

    def test_external_service_identity_cannot_pass(self):
        r = chain("create")
        for text in ("openai", "claude", "anthropic", "gpt", "llm", "api", "network", "cloud",
                     "server", "service", "endpoint", "webhook", "remote", "url", "internet"):
            for key in IDENTITY:
                assert_not_final(self, advance(906, dict(r[906], **{key: text})))
                assert_not_final(self, advance(907, dict(r[907], **{key: text})))

    def test_malformed_identity_values_cannot_pass(self):
        r = chain("create")
        for key in IDENTITY:
            for value in ("", None, 5, " ", "x" * 500, ["a"]):
                assert_not_final(self, advance(906, dict(r[906], **{key: value})))
                assert_not_final(self, advance(907, dict(r[907], **{key: value})))

    def test_not_ready_902_cannot_reach_the_final_gate(self):
        for override in ({"status": "not_ready", "valid": False, "claude_independent": False},
                         {"claude_independent": False},
                         {"status": "invalid_context", "valid": False}):
            assert_not_final(self, advance(902, dict(run902("create"), **override)))

    def test_not_ready_902_context_cannot_reach_the_final_gate(self):
        from tests.test_claude_exit_readiness_prompt902 import chain_none
        broken = run902("create", chain=chain_none(0))
        self.assertIs(broken["valid"], False)
        assert_not_final(self, advance(902, broken))

    def test_unsupported_operation_cannot_reach_the_final_gate(self):
        r = chain("create")
        assert_not_final(self, advance(902, dict(r[902], operation="delete")))
        assert_not_final(self, advance(907, dict(r[907], operation="delete")))

    def test_final_gate_output_is_not_a_valid_input_to_itself(self):
        gate = chain("create")[908]
        assert_not_final(self, m908.build_final_internal_evolution_gate(gate))
        assert_not_final(self, m908.build_final_internal_evolution_gate(dict(gate, valid=True)))

    def test_invalid_beats_context_and_forbidden_beats_all_at_the_gate(self):
        r = chain("create")
        out = m908.build_final_internal_evolution_gate(dict(r[907], stage="x"),
                                                       {"operation": "other"})
        self.assertEqual(out["status"], "invalid_validation_result")
        out = m908.build_final_internal_evolution_gate(
            dict(r[907], executed=True, stage="x"), {"operation": "other"})
        self.assertEqual(out["status"], "forbidden_execution_state")

    def test_builders_never_raise_on_garbage(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        for prompt in range(902, 908):
            for bad in (None, [], "x", 5, {1: 2}, Boom(), {"a": object()}):
                out = BUILDERS[prompt](bad)
                self.assertIs(out["valid"], False, (prompt, bad))
                for key in FLAGS:
                    self.assertIs(out[key], False)


class DocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DOC, encoding="utf-8") as handle:
            cls.text = handle.read()

    def test_doc_states_checkpoint_and_readiness(self):
        self.assertIn("final core architecture checkpoint", self.text)
        self.assertIn("Claude-independent readiness", self.text)

    def test_doc_states_not_a_fully_autonomous_jarvis(self):
        self.assertIn("does NOT mean", self.text)
        self.assertIn("fully autonomous Jarvis", self.text)
        self.assertIn("baby assistant", self.text)

    def test_doc_states_future_work_and_non_executing(self):
        text = " ".join(self.text.split())
        for phrase in ("integration", "Android/APK work", "device testing", "release preparation",
                       "controlled real-world capability activation", "non-executing"):
            self.assertIn(phrase, text)

    def test_doc_lists_every_prompt_in_the_chain(self):
        for prompt in range(902, 909):
            self.assertIn(str(prompt), self.text)
        for status in EXPECTED_STATUSES.values():
            self.assertIn(status, self.text)


if __name__ == "__main__":
    unittest.main()
