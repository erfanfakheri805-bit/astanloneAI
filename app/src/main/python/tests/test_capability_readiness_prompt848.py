"""
Prompt 848 - capability readiness boundary focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_readiness_prompt848 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_readiness as cr_
from capabilities.capability_readiness import evaluate_capability_readiness as evaluate
from capabilities.capability_selection import select_capability as select
from capabilities.capability_matching import match_capability as match
from capabilities.capability_registry import CapabilityRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "ready", "reason", "capability_name", "capability_version",
        "execution_allowed", "executed"]


def desc(**over):
    d = {"name": "text_summary", "version": 3, "purpose": "Summarise supplied text.",
         "inputs": ["text"], "outputs": ["summary"], "constraints": [], "enabled": False}
    d.update(over)
    return d


def cap(state="enabled", **over):
    return {"descriptor": desc(**over), "lifecycle_state": state}


def real(descriptor=None, name="text_summary"):
    """A real Prompt 845 match result and the Prompt 846 selection made from it."""
    reg = CapabilityRegistry()
    descriptor = descriptor or desc()
    assert reg.register(descriptor)["status"] == "registered"
    m = match({"name": name}, reg)
    return m, select(m)


def check(test, r, status, reason, name="text_summary", version=3):
    test.assertEqual(list(r), KEYS)
    test.assertEqual((r["status"], r["reason"]), (status, reason))
    test.assertIs(r["ready"], status == "ready")
    test.assertIs(r["execution_allowed"], status == "ready")
    test.assertIs(r["executed"], False)
    test.assertEqual((r["capability_name"], r["capability_version"]), (name, version))
    json.dumps(r)


class ReadyTests(unittest.TestCase):
    def test_fully_ready_capability(self):
        m, s = real()
        r = evaluate(cap(), m, s)
        check(self, r, "ready", "ready")
        self.assertIs(r["ready"], True)
        self.assertIs(r["execution_allowed"], True)

    def test_descriptor_enabled_flag_is_irrelevant(self):
        d = desc(enabled=True)
        m, s = real(d)
        check(self, evaluate({"descriptor": d, "lifecycle_state": "enabled"}, m, s),
              "ready", "ready")


class InvalidCapabilityTests(unittest.TestCase):
    def test_invalid_descriptor(self):
        m, s = real()
        for d in (desc(version=0), desc(outputs=[]), desc(handler="x.y"), desc(purpose=1)):
            with self.subTest(d=d):
                r = evaluate({"descriptor": d, "lifecycle_state": "enabled"}, m, s)
                self.assertEqual((r["status"], r["reason"]), ("not_ready", "invalid_capability"))
                self.assertIs(r["ready"], False)

    def test_invalid_name_not_echoed(self):
        m, s = real()
        r = evaluate({"descriptor": desc(name="Bad Name"), "lifecycle_state": "enabled"}, m, s)
        check(self, r, "not_ready", "invalid_capability", name=None)

    def test_malformed_capability_input(self):
        m, s = real()
        for bad in (None, 1, "x", [], {}, desc(), dict(cap(), extra=1), {"descriptor": desc()}):
            with self.subTest(bad=bad):
                check(self, evaluate(bad, m, s), "invalid_input", "invalid_capability_input",
                      name=None, version=None)


class LifecycleTests(unittest.TestCase):
    def test_non_enabled_states(self):
        m, s = real()
        for state in ("defined", "validated", "disabled", "deprecated"):
            with self.subTest(state=state):
                check(self, evaluate(cap(state), m, s), "not_ready", "lifecycle_" + state)

    def test_unknown_states(self):
        m, s = real()
        for state in ("Enabled", "", None, 1, b"enabled"):
            with self.subTest(state=state):
                check(self, evaluate(cap(state), m, s), "not_ready", "invalid_lifecycle_state")


class MatchResultTests(unittest.TestCase):
    def test_missing_match_result(self):
        _, s = real()
        check(self, evaluate(cap(), None, s), "not_ready", "missing_match_result")
        check(self, evaluate(cap()), "not_ready", "missing_match_result")

    def test_malformed_match_results(self):
        m, s = real()
        bad = [{}, [], "matched", 1, dict(m, extra=1), dict(m, status="bogus"),
               dict(m, matched=False), dict(m, executed=True), dict(m, execution_allowed=True),
               dict(m, matches=[]), dict(m, matches=[{"identity": {"name": "x"}}])]
        for b in bad:
            with self.subTest(b=b):
                check(self, evaluate(cap(), b, s), "invalid_input", "invalid_match_result")

    def test_no_match_result(self):
        m = match({"name": "text_summary"}, CapabilityRegistry())
        self.assertEqual(m["status"], "no_match")
        _, s = real()
        check(self, evaluate(cap(), m, s), "not_ready", "match_not_matched")


class SelectionResultTests(unittest.TestCase):
    def test_missing_selection_result(self):
        m, _ = real()
        check(self, evaluate(cap(), m, None), "not_ready", "missing_selection_result")
        check(self, evaluate(cap(), m), "not_ready", "missing_selection_result")

    def test_malformed_selection_results(self):
        m, s = real()
        bad = [{}, [], "selected", 1, dict(s, status="chosen"), dict(s, executed=True),
               dict(s, execution_allowed=True), dict(s, reason="because"), dict(s, extra=1),
               dict(s, candidate_count=0), select({"bogus": 1})]
        for b in bad:
            with self.subTest(b=b):
                check(self, evaluate(cap(), m, b), "invalid_input", "invalid_selection_result")

    def test_not_selected(self):
        m, _ = real()
        s = select(match({"name": "text_summary"}, CapabilityRegistry()))
        self.assertEqual(s["status"], "not_selected")
        check(self, evaluate(cap(), m, s), "not_ready", "not_selected")

    def test_selection_not_unique(self):
        a, b = desc(version=3), desc(version=4)
        entries = [{"identity": {"name": "text_summary"}, "version": d["version"], "descriptor": d}
                   for d in (a, b)]
        m = {"status": "matched", "matched": True, "candidate_count": 2, "matches": entries,
             "rejected": [], "truncated": False, "execution_allowed": False, "executed": False}
        s = select(m)
        self.assertEqual(s["reason"], "highest_version")
        check(self, evaluate({"descriptor": b, "lifecycle_state": "enabled"}, m, s),
              "not_ready", "selection_not_unique", version=4)


class MismatchTests(unittest.TestCase):
    def test_selection_of_other_capability(self):
        m, s = real(desc(name="other_capability"), name="other_capability")
        check(self, evaluate(cap(), m, s), "not_ready", "selection_mismatch")

    def test_selection_of_other_version(self):
        m, s = real(desc(version=4))
        check(self, evaluate(cap(), m, s), "not_ready", "selection_mismatch")

    def test_selection_from_a_different_match_result(self):
        m, s = real()
        m2, _ = real(desc(purpose="Another purpose."))
        check(self, evaluate(cap(), m2, s), "not_ready", "match_selection_inconsistent")

    def test_match_with_several_entries_is_inconsistent(self):
        m, s = real()
        extra = copy.deepcopy(m["matches"][0])
        m2 = dict(m, matches=[m["matches"][0], extra], candidate_count=2)
        check(self, evaluate(cap(), m2, s), "not_ready", "match_selection_inconsistent")


class ExecutionBoundaryDenialTests(unittest.TestCase):
    def test_boundary_denial_is_never_ready(self):
        from capabilities import capability_readiness as mod
        m, s = real()
        original = mod.evaluate_capability_execution
        try:
            def deny(capability, request=None):
                r = original(capability, request)
                if request is not None:
                    r = dict(r, status="denied", allowed=False, execution_allowed=False)
                return r
            mod.evaluate_capability_execution = deny
            check(self, evaluate(cap(), m, s), "not_ready", "execution_not_allowed")
        finally:
            mod.evaluate_capability_execution = original

    def test_agrees_with_the_real_boundary(self):
        from capabilities.capability_execution_boundary import evaluate_capability_execution as ev
        m, s = real()
        for state in ("enabled", "disabled", "deprecated", "defined", "validated"):
            ready = evaluate(cap(state), m, s)["ready"]
            self.assertIs(ready, ev(cap(state), {"selection": s})["allowed"])


class SafetyTests(unittest.TestCase):
    def test_never_ready_unless_all_conditions_hold(self):
        m, s = real()
        for args in ((cap("disabled"), m, s), (cap(), None, s), (cap(), m, None),
                     (None, m, s), (cap(), {}, s), (cap(), m, {})):
            r = evaluate(*args)
            self.assertIs(r["ready"], False)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_inputs_not_modified_and_result_fresh(self):
        c, (m, s) = cap(), real()
        before = copy.deepcopy((c, m, s))
        a, b = evaluate(c, m, s), evaluate(c, m, s)
        self.assertEqual((c, m, s), before)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_never_raises_on_hostile_objects(self):
        class Boom:
            def __getitem__(self, k):
                raise RuntimeError("boom")
            def __eq__(self, o):
                raise RuntimeError("boom")
            __hash__ = None
        m, s = real()
        for args in ((Boom(), m, s), (cap(), Boom(), s), (cap(), m, Boom()),
                     ({"descriptor": Boom(), "lifecycle_state": "enabled"}, m, s)):
            r = evaluate(*args)
            self.assertEqual(list(r), KEYS)
            self.assertIs(r["ready"], False)
            self.assertIs(r["executed"], False)


class BoundaryTests(unittest.TestCase):
    def test_imports_only_existing_capability_layers(self):
        tree = ast.parse(inspect.getsource(cr_))
        modules = {("." * n.level) + (n.module or "") for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom)}
        modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual(modules, {".capability_execution_boundary", ".capability_matching",
                                   ".capability_selection"})

    def test_does_not_match_or_select_internally(self):
        src = inspect.getsource(cr_.evaluate_capability_readiness)
        for word in ("match_capability(", "select_capability(", "register(", "exec(", "eval(",
                     "__import__", "import_module", "open("):
            self.assertNotIn(word, src)

    def test_older_layers_do_not_import_readiness_and_core_is_not_wired(self):
        for name in os.listdir(os.path.join(ROOT, "capabilities")):
            if name.endswith(".py") and name != "capability_readiness.py":
                with open(os.path.join(ROOT, "capabilities", name), encoding="utf-8") as f:
                    self.assertNotIn("capability_readiness", f.read())
        for folder in ("core", "memory", "ael"):
            for d, _, files in os.walk(os.path.join(ROOT, folder)):
                for fn in files:
                    if fn.endswith(".py"):
                        with open(os.path.join(d, fn), encoding="utf-8") as f:
                            self.assertNotIn("capability_readiness", f.read())


if __name__ == "__main__":
    unittest.main()
