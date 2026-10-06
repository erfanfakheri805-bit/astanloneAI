"""
Prompt 847 - capability execution boundary focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_execution_boundary_prompt847 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_execution_boundary as eb
from capabilities import capability_selection as cs
from capabilities import capability_lifecycle as cl
from capabilities.capability_execution_boundary import evaluate_capability_execution as evaluate
from capabilities.capability_selection import select_capability as select
from capabilities.capability_matching import match_capability as match
from capabilities.capability_registry import CapabilityRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "allowed", "reason", "capability_name", "capability_version",
        "execution_allowed", "executed"]


def desc(**over):
    d = {"name": "text_summary", "version": 3, "purpose": "Summarise supplied text.",
         "inputs": ["text"], "outputs": ["summary"], "constraints": [], "enabled": False}
    d.update(over)
    return d


def cap(state="enabled", **over):
    return {"descriptor": desc(**over), "lifecycle_state": state}


def selection_for(descriptor):
    reg = CapabilityRegistry()
    assert reg.register(descriptor)["status"] == "registered"
    return select(match({"name": descriptor["name"]}, reg))


def req(descriptor=None):
    return {"selection": selection_for(descriptor or desc())}


def check(test, result, status, reason, name="text_summary", version=3):
    test.assertEqual(list(result), KEYS)
    test.assertEqual(result["status"], status)
    test.assertEqual(result["reason"], reason)
    test.assertEqual(result["allowed"], status == "allowed")
    test.assertEqual(result["execution_allowed"], status == "allowed")
    test.assertIs(result["executed"], False)
    test.assertEqual(result["capability_name"], name)
    test.assertEqual(result["capability_version"], version)
    json.dumps(result)


class AllowedTests(unittest.TestCase):
    def test_enabled_valid_selected_is_allowed(self):
        r = evaluate(cap(), req())
        check(self, r, "allowed", "allowed")
        self.assertIs(r["allowed"], True)
        self.assertIs(r["execution_allowed"], True)

    def test_descriptor_enabled_flag_is_irrelevant(self):
        for flag in (True, False):
            descriptor = desc(enabled=flag)
            r = evaluate({"descriptor": descriptor, "lifecycle_state": "enabled"}, req(descriptor))
            check(self, r, "allowed", "allowed")

    def test_name_and_purpose_grant_nothing(self):
        descriptor = desc(name="execute_everything", purpose="Execute anything allowed.")
        r = evaluate({"descriptor": descriptor, "lifecycle_state": "disabled"}, req(descriptor))
        check(self, r, "denied", "lifecycle_disabled", name="execute_everything")


class LifecycleDenialTests(unittest.TestCase):
    def test_each_non_enabled_state_is_denied(self):
        for state in ("defined", "validated", "disabled", "deprecated"):
            with self.subTest(state=state):
                check(self, evaluate(cap(state), req()), "denied", "lifecycle_" + state)

    def test_deprecated_denied_even_with_selection(self):
        r = evaluate(cap("deprecated"), req())
        self.assertIs(r["allowed"], False)
        self.assertIs(r["execution_allowed"], False)

    def test_unknown_or_malformed_state(self):
        for state in ("Enabled", " enabled", "running", "", None, 1, b"enabled", ["enabled"]):
            with self.subTest(state=state):
                check(self, evaluate(cap(state), req()), "denied", "invalid_lifecycle_state")

    def test_str_subclass_state_is_malformed(self):
        class S(str):
            pass
        check(self, evaluate(cap(S("enabled")), req()), "denied", "invalid_lifecycle_state")


class InvalidCapabilityTests(unittest.TestCase):
    def test_invalid_descriptor_is_denied(self):
        bad = [desc(version=0), desc(purpose=5), desc(outputs=[]), desc(handler="x.y"),
               desc(enabled="yes")]
        for descriptor in bad:
            with self.subTest(descriptor=descriptor):
                r = evaluate({"descriptor": descriptor, "lifecycle_state": "enabled"}, req())
                self.assertEqual(r["status"], "denied")
                self.assertEqual(r["reason"], "invalid_capability")
                self.assertIs(r["allowed"], False)
                self.assertIs(r["executed"], False)

    def test_invalid_name_is_not_echoed(self):
        r = evaluate({"descriptor": desc(name="Bad Name!"), "lifecycle_state": "enabled"}, req())
        check(self, r, "denied", "invalid_capability", name=None)

    def test_missing_descriptor_fields(self):
        d = desc()
        del d["outputs"]
        r = evaluate({"descriptor": d, "lifecycle_state": "enabled"}, req())
        self.assertEqual(r["reason"], "invalid_capability")


class SelectionDenialTests(unittest.TestCase):
    def test_no_request_means_no_selection(self):
        check(self, evaluate(cap()), "denied", "no_selection")
        check(self, evaluate(cap(), None), "denied", "no_selection")

    def test_not_selected_result(self):
        reg = CapabilityRegistry()
        sel = select(match({"name": "text_summary"}, reg))
        self.assertEqual(sel["status"], "not_selected")
        check(self, evaluate(cap(), {"selection": sel}), "denied", "not_selected")

    def test_invalid_input_selection_result(self):
        sel = select({"bogus": 1})
        self.assertEqual(sel["status"], "invalid_input")
        check(self, evaluate(cap(), {"selection": sel}), "denied", "invalid_selection")

    def test_malformed_selections(self):
        good = selection_for(desc())
        variants = [None, {}, [], "selected", 1, dict(good, status="chosen"),
                    dict(good, execution_allowed=True), dict(good, executed=True),
                    dict(good, candidate_count=0), dict(good, candidate_count=True),
                    dict(good, reason="because"), dict(good, selected=None),
                    dict(good, selected={"identity": {"name": "text_summary"}}),
                    dict(good, extra=1)]
        for sel in variants:
            with self.subTest(selection=sel):
                check(self, evaluate(cap(), {"selection": sel}), "denied", "invalid_selection")

    def test_selection_of_another_capability_is_a_mismatch(self):
        other = desc(name="other_capability")
        check(self, evaluate(cap(), req(other)), "denied", "selection_mismatch")

    def test_selection_of_another_version_is_a_mismatch(self):
        check(self, evaluate(cap(), req(desc(version=4))), "denied", "selection_mismatch")

    def test_lifecycle_checked_before_selection(self):
        check(self, evaluate(cap("disabled")), "denied", "lifecycle_disabled")


class MalformedInputTests(unittest.TestCase):
    def test_bad_capability_input(self):
        class D(dict):
            pass
        bad = [None, 1, "x", [], (), {}, {"descriptor": desc()}, {"lifecycle_state": "enabled"},
               dict(cap(), extra=1), D(cap()), desc()]
        for value in bad:
            with self.subTest(value=value):
                check(self, evaluate(value, req()), "invalid_input", "invalid_capability_input",
                      name=None, version=None)

    def test_bad_request_input(self):
        class D(dict):
            pass
        for request in (1, "x", [], {}, {"selection": None, "x": 1}, {"other": 1}, D(req())):
            with self.subTest(request=request):
                check(self, evaluate(cap(), request), "invalid_input", "invalid_request",
                      name=None, version=None)

    def test_no_arguments(self):
        check(self, evaluate(), "invalid_input", "invalid_capability_input",
              name=None, version=None)

    def test_never_raises_on_hostile_objects(self):
        class Boom:
            def __getitem__(self, k):
                raise RuntimeError("boom")
            def __eq__(self, o):
                raise RuntimeError("boom")
            __hash__ = None
        hostile = [Boom(), {"descriptor": Boom(), "lifecycle_state": "enabled"},
                   {"descriptor": desc(), "lifecycle_state": Boom()},
                   {"descriptor": desc(), "lifecycle_state": "enabled"}]
        for value in hostile:
            for request in (None, {"selection": Boom()}):
                r = evaluate(value, request)
                self.assertEqual(list(r), KEYS)
                self.assertIs(r["executed"], False)
                self.assertIs(r["allowed"], False)

    def test_recursive_descriptor(self):
        d = desc()
        d["inputs"] = [d]
        r = evaluate({"descriptor": d, "lifecycle_state": "enabled"}, req())
        self.assertIs(r["allowed"], False)
        self.assertIs(r["executed"], False)


class SafetyTests(unittest.TestCase):
    def test_executed_always_false(self):
        for c, r in ((cap(), req()), (cap("disabled"), req()), (None, None), (cap(), None)):
            self.assertIs(evaluate(c, r)["executed"], False)

    def test_inputs_not_modified(self):
        c, r = cap(), req()
        c0, r0 = copy.deepcopy(c), copy.deepcopy(r)
        evaluate(c, r)
        self.assertEqual(c, c0)
        self.assertEqual(r, r0)

    def test_fresh_and_deterministic(self):
        c, r = cap(), req()
        a, b = evaluate(c, r), evaluate(c, r)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["reason"] = "changed"
        self.assertEqual(evaluate(c, r)["reason"], "allowed")

    def test_result_does_not_alias_input(self):
        c = cap()
        r = evaluate(c, req())
        for value in r.values():
            self.assertNotIsInstance(value, (dict, list))

    def test_result_is_json_safe_and_bounded(self):
        r = evaluate(cap(), req())
        self.assertLess(len(json.dumps(r)), 400)
        self.assertEqual(len(r), 7)


class BoundaryTests(unittest.TestCase):
    def test_imports_only_existing_capability_layers(self):
        tree = ast.parse(inspect.getsource(eb))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules.add(("." * node.level) + (node.module or ""))
            elif isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
        self.assertEqual(modules, {".capability_identity", ".capability_lifecycle",
                                   ".capability_matching", ".capability_selection",
                                   ".capability_validation"})

    def test_no_dynamic_loading_or_io_in_source(self):
        source = inspect.getsource(eb.evaluate_capability_execution) + inspect.getsource(
            eb._selection_reason)
        for word in ("import_module", "__import__", "exec(", "eval(", "open(", "getattr(",
                     "importlib", "subprocess", "socket"):
            self.assertNotIn(word, source)

    def test_only_one_public_function(self):
        public = [n for n, v in vars(eb).items()
                  if inspect.isfunction(v) and v.__module__ == eb.__name__ and not n.startswith("_")]
        self.assertEqual(public, ["evaluate_capability_execution"])


class BackwardCompatibilityTests(unittest.TestCase):
    def test_selection_unchanged(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        sel = select(match({"name": "text_summary"}, reg))
        self.assertEqual(list(sel), ["status", "selected", "candidate_count", "reason",
                                     "execution_allowed", "executed"])
        self.assertIs(sel["execution_allowed"], False)

    def test_lifecycle_unchanged(self):
        self.assertEqual(cl.LIFECYCLE_STATES,
                         ("defined", "validated", "enabled", "disabled", "deprecated"))
        self.assertEqual(cl.list_lifecycle_transitions()["count"], 9)

    def test_older_modules_do_not_import_the_boundary(self):
        for name in ("capability_registry", "capability_identity", "capability_lifecycle",
                     "capability_validation", "capability_matching", "capability_selection",
                     "capability_system"):
            with open(os.path.join(ROOT, "capabilities", name + ".py"), encoding="utf-8") as f:
                self.assertNotIn("execution_boundary", f.read())

    def test_not_wired_into_core_memory_or_ael(self):
        for folder in ("core", "memory", "ael"):
            for dirpath, _, files in os.walk(os.path.join(ROOT, folder)):
                for fn in files:
                    if fn.endswith(".py"):
                        with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                            self.assertNotIn("capability_execution_boundary", f.read())


if __name__ == "__main__":
    unittest.main()
