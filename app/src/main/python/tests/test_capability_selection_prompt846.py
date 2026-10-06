"""
Prompt 846 - capability selection focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_selection_prompt846 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_selection as cs
from capabilities import capability_matching as cm
from capabilities import capability_registry as cr
from capabilities import capability_identity as ci
from capabilities import capability_lifecycle as cl
from capabilities import capability_validation as cv
from capabilities.capability_selection import select_capability as select
from capabilities.capability_matching import match_capability as match
from capabilities.capability_registry import CapabilityRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["status", "selected", "candidate_count", "reason", "execution_allowed", "executed"]


def desc(**over):
    d = {"name": "text_summary", "version": 3, "purpose": "Summarise supplied text.",
         "inputs": ["text"], "outputs": ["summary"], "constraints": [], "enabled": False}
    d.update(over)
    return d


def entry(**over):
    d = desc(**over)
    return {"identity": {"name": d["name"]}, "version": d["version"], "descriptor": d}


def result(*entries, **over):
    """A well-formed Prompt 845 result holding the given matches."""
    r = {"status": "matched", "matched": True, "candidate_count": len(entries),
         "matches": list(entries), "rejected": [], "truncated": False,
         "execution_allowed": False, "executed": False}
    r.update(over)
    return r


def real_match(*descriptors, name="text_summary", **req):
    reg = CapabilityRegistry()
    for d in descriptors:
        assert reg.register(d)["status"] == "registered"
    return match(dict({"name": name}, **req), reg)


class IntSub(int):
    pass


class UniqueMatchTests(unittest.TestCase):
    def test_unique_match_from_real_matching(self):
        r = select(real_match(desc()))
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["status"], "selected")
        self.assertEqual(r["reason"], "unique_match")
        self.assertEqual(r["candidate_count"], 1)
        self.assertEqual(r["selected"], {"identity": {"name": "text_summary"}, "version": 3,
                                         "descriptor": desc()})
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)

    def test_selected_holds_only_the_matched_entry(self):
        m = real_match(desc(), minimum_version=1, required_inputs=["text"])
        r = select(m)
        self.assertEqual(r["selected"], m["matches"][0])
        self.assertEqual(list(r["selected"]), ["identity", "version", "descriptor"])

    def test_disabled_and_enabled_flags_are_untouched(self):
        for flag in (False, True):
            self.assertIs(select(real_match(desc(enabled=flag)))["selected"]["descriptor"]["enabled"], flag)

    def test_end_to_end_with_requirements(self):
        m = real_match(desc(version=4), minimum_version=4, expected_outputs=["summary"])
        self.assertEqual(select(m)["selected"]["version"], 4)


class MultipleVersionTests(unittest.TestCase):
    def test_highest_version_wins_in_any_order(self):
        for order in ([1, 5, 3], [5, 3, 1], [3, 1, 5], [1, 3, 5]):
            r = select(result(*[entry(version=v) for v in order]))
            self.assertEqual(r["status"], "selected", order)
            self.assertEqual(r["selected"]["version"], 5, order)
            self.assertEqual(r["reason"], "highest_version", order)
            self.assertEqual(r["candidate_count"], 3)

    def test_version_beats_name_order(self):
        r = select(result(entry(name="aaa_cap", version=1), entry(name="zzz_cap", version=2)))
        self.assertEqual(r["selected"]["identity"], {"name": "zzz_cap"})
        self.assertEqual(r["reason"], "highest_version")

    def test_numeric_not_textual_version_order(self):
        r = select(result(entry(version=9), entry(version=10)))
        self.assertEqual(r["selected"]["version"], 10)
        r = select(result(entry(version=cr.MAX_VERSION), entry(version=cr.MAX_VERSION - 1), entry(version=1)))
        self.assertEqual(r["selected"]["version"], cr.MAX_VERSION)

    def test_uses_prompt842_comparison(self):
        calls = []
        original = cs.compare_capability_versions

        def spy(left, right):
            calls.append((left, right))
            return original(left, right)
        cs.compare_capability_versions = spy
        try:
            select(result(entry(version=2), entry(version=7)))
        finally:
            cs.compare_capability_versions = original
        self.assertEqual(calls, [(7, 2)])

    def test_unique_match_does_not_compare(self):
        calls = []
        original = cs.compare_capability_versions
        cs.compare_capability_versions = lambda a, b: calls.append((a, b))
        try:
            select(real_match(desc()))
        finally:
            cs.compare_capability_versions = original
        self.assertEqual(calls, [])


class TieBreakingTests(unittest.TestCase):
    def test_equal_versions_choose_stable_name_order(self):
        names = ["m_cap", "b_cap", "z_cap", "a_cap"]
        for rot in range(len(names)):
            order = names[rot:] + names[:rot]
            r = select(result(*[entry(name=n, version=2) for n in order]))
            self.assertEqual(r["selected"]["identity"], {"name": "a_cap"}, order)
            self.assertEqual(r["reason"], "name_order")
            self.assertEqual(r["candidate_count"], 4)

    def test_name_order_is_code_point_order(self):
        r = select(result(entry(name="a_b", version=1), entry(name="a1", version=1), entry(name="a_", version=1)))
        self.assertEqual(r["selected"]["identity"], {"name": "a1"})  # '1' < '_'
        r = select(result(entry(name="ab", version=1), entry(name="a", version=1)))
        self.assertEqual(r["selected"]["identity"], {"name": "a"})   # shorter prefix first

    def test_only_top_version_takes_part_in_name_order(self):
        r = select(result(entry(name="a_cap", version=1), entry(name="c_cap", version=4),
                          entry(name="b_cap", version=4)))
        self.assertEqual(r["selected"]["identity"], {"name": "b_cap"})
        self.assertEqual(r["reason"], "name_order")

    def test_identical_ties_keep_supplied_order(self):
        first = entry(version=2, purpose="First descriptor.")
        second = entry(version=2, purpose="Second descriptor.")
        self.assertEqual(select(result(first, second))["selected"]["descriptor"]["purpose"], "First descriptor.")
        self.assertEqual(select(result(second, first))["selected"]["descriptor"]["purpose"], "Second descriptor.")

    def test_identity_is_exact_not_similar(self):
        # a descriptor whose identity differs from its descriptor name is never selected
        bad = entry(name="a_cap", version=9)
        bad["identity"] = {"name": "A_cap"}
        r = select(result(bad, entry(name="b_cap", version=1)))
        self.assertEqual(r["status"], "invalid_input")
        self.assertIsNone(r["selected"])

    def test_deterministic_across_calls(self):
        m = result(entry(name="b_cap"), entry(name="a_cap"), entry(name="c_cap", version=1))
        first = select(m)
        for _ in range(5):
            self.assertEqual(select(m), first)


class NoMatchTests(unittest.TestCase):
    def check_not_selected(self, m, reason):
        r = select(m)
        self.assertEqual(r, {"status": "not_selected", "selected": None, "candidate_count": 0,
                             "reason": reason, "execution_allowed": False, "executed": False})

    def test_no_match(self):
        self.check_not_selected(real_match(desc(), name="other_cap"), "no_match")
        self.check_not_selected(match({"name": "x_cap"}, CapabilityRegistry()), "no_match")

    def test_no_valid_match(self):
        self.check_not_selected(real_match(desc(), minimum_version=9), "no_valid_match")
        self.check_not_selected(real_match(desc(), required_inputs=["missing"]), "no_valid_match")

    def test_invalid_requirement_and_registry_results(self):
        self.check_not_selected(match(None, CapabilityRegistry()), "invalid_requirement")
        self.check_not_selected(match({"name": "x_cap"}, None), "invalid_registry")

    def test_matching_error_result(self):
        self.check_not_selected(result(status="matching_error", matched=False, candidate_count=0, matches=[]),
                                "matching_error")

    def test_nothing_is_invented(self):
        r = select(real_match(desc(), name="never_registered"))
        self.assertIsNone(r["selected"])
        self.assertEqual(r["candidate_count"], 0)


class MalformedInputTests(unittest.TestCase):
    def check_invalid(self, value):
        r = select(value)
        self.assertEqual(r, {"status": "invalid_input", "selected": None, "candidate_count": 0,
                             "reason": "invalid_match_result", "execution_allowed": False,
                             "executed": False}, repr(value)[:80])
        json.dumps(r)

    def test_not_a_result(self):
        class D(dict):
            pass
        for bad in (None, 1, "matched", [], (), True, object(), b"x", set(), {}, D(result(entry()))):
            self.check_invalid(bad)

    def test_default_argument(self):
        self.assertEqual(select()["status"], "invalid_input")

    def test_wrong_keys(self):
        r = result(entry())
        for key in list(r):
            broken = dict(r)
            del broken[key]
            self.check_invalid(broken)
        self.check_invalid(dict(r, extra=1))

    def test_bad_status_and_matched_flag(self):
        for bad in ("selected", "MATCHED", "", None, 1, ["matched"], "matched "):
            self.check_invalid(result(entry(), status=bad))
        self.check_invalid(result(entry(), matched=False))
        self.check_invalid(result(entry(), matched=1))
        self.check_invalid(result(status="no_match", matched=True, matches=[]))

    def test_bad_counts_and_flags(self):
        for bad in (-1, 1.0, "1", None, True, IntSub(1)):
            self.check_invalid(result(entry(), candidate_count=bad))
        self.check_invalid(result(entry(), truncated="no"))
        self.check_invalid(result(entry(), rejected=None))

    def test_execution_flags_must_be_false(self):
        for key in ("execution_allowed", "executed"):
            for bad in (True, 1, None, "False", 0):
                self.check_invalid(result(entry(), **{key: bad}))

    def test_matched_without_matches_or_unmatched_with_matches(self):
        self.check_invalid(result())
        self.check_invalid(result(entry(), status="no_match", matched=False))

    def test_matches_not_a_list_or_too_many(self):
        self.check_invalid(result(matches=(entry(),)))
        self.check_invalid(result(matches=None))
        self.check_invalid(result(*[entry(name="c%02d" % i) for i in range(cm.MAX_MATCHES + 1)]))
        ok = select(result(*[entry(name="c%02d" % i) for i in range(cm.MAX_MATCHES)]))
        self.assertEqual(ok["selected"]["identity"], {"name": "c00"})

    def test_malformed_match_entries(self):
        good = entry()
        bad_entries = [None, 1, "x", [], {}, dict(good, extra=1),
                       {k: v for k, v in good.items() if k != "version"},
                       dict(good, identity=None), dict(good, identity={}),
                       dict(good, identity={"name": "other_cap"}),
                       dict(good, identity={"name": "text_summary", "x": 1}),
                       dict(good, version=4),                      # differs from descriptor
                       dict(good, version="3"), dict(good, version=True), dict(good, version=0),
                       dict(good, descriptor=None), dict(good, descriptor={}),
                       dict(good, descriptor=dict(desc(), handler="x")),
                       dict(good, descriptor=desc(version="3"), version=3),
                       dict(good, descriptor=desc(outputs=[])),
                       dict(good, descriptor=desc(name="Bad Name"), identity={"name": "Bad Name"})]
        for bad in bad_entries:
            self.check_invalid(result(good, bad))   # one bad match spoils the whole input
            self.check_invalid(result(bad))

    def test_never_raises(self):
        class Evil(dict):
            def __iter__(self):
                raise RuntimeError("boom")
        for bad in (Evil(result(entry())), result(Evil(entry())), float("nan"), type, lambda: 1):
            r = select(bad)
            self.assertEqual(list(r), KEYS)
            self.assertIs(r["executed"], False)

    def test_input_never_modified(self):
        m = result(entry(version=1), entry(name="a_cap", version=2), entry(name="b_cap", version=2))
        snapshot = copy.deepcopy(m)
        select(m)
        select(real_match(desc()))
        self.assertEqual(m, snapshot)


class FreshnessAndSafetyTests(unittest.TestCase):
    def test_results_are_fresh_and_isolated(self):
        m = real_match(desc())
        a, b = select(m), select(m)
        self.assertIsNot(a, b)
        self.assertIsNot(a["selected"], b["selected"])
        self.assertIsNot(a["selected"], m["matches"][0])
        self.assertIsNot(a["selected"]["descriptor"]["inputs"], m["matches"][0]["descriptor"]["inputs"])
        a["selected"]["descriptor"]["inputs"].append("zzz")
        a["selected"]["identity"]["name"] = "changed"
        self.assertEqual(m["matches"][0]["descriptor"]["inputs"], ["text"])
        self.assertEqual(select(m)["selected"], m["matches"][0])

    def test_json_safe(self):
        for r in (select(real_match(desc())), select(real_match(desc(), name="x_cap")), select(None),
                  select(result(entry(version=1), entry(version=2)))):
            self.assertEqual(json.loads(json.dumps(r)), r)
            self.assertEqual(list(r), KEYS)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_registry_is_not_involved_or_changed(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        before = reg.list_capabilities()
        m = match({"name": "text_summary"}, reg)
        select(m)
        self.assertEqual(reg.list_capabilities(), before)
        self.assertEqual(len(reg), 1)

    def test_statuses_and_reasons_are_the_documented_ones(self):
        outcomes = [select(real_match(desc())), select(result(entry(version=1), entry(version=2))),
                    select(result(entry(name="a_cap"), entry(name="b_cap"))),
                    select(real_match(desc(), name="x_cap")), select(real_match(desc(), minimum_version=9)),
                    select(None)]
        self.assertEqual([(o["status"], o["reason"]) for o in outcomes],
                         [("selected", "unique_match"), ("selected", "highest_version"),
                          ("selected", "name_order"), ("not_selected", "no_match"),
                          ("not_selected", "no_valid_match"), ("invalid_input", "invalid_match_result")])


class BoundaryTests(unittest.TestCase):
    def test_imports_only_existing_capability_layers(self):
        tree = ast.parse(inspect.getsource(cs))
        imports = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                imports.append((node.module, node.level, tuple(sorted(a.name for a in node.names))))
            elif isinstance(node, ast.Import):
                imports.extend((a.name, 0, ()) for a in node.names)
        self.assertEqual(sorted(imports), [
            ("capability_identity", 1, ("REL_EQUAL", "REL_NEWER", "build_capability_identity",
                                        "compare_capability_versions", "parse_capability_version")),
            ("capability_matching", 1, ("MAX_MATCHES", "STATUSES", "STATUS_MATCHED")),
            ("capability_validation", 1, ("validate_capability",)),
            ("copy", 0, ())])

    def test_no_matching_logic_registry_or_io(self):
        body = inspect.getsource(cs).split('"""', 2)[2]
        for banned in ("importlib", "__import__", "exec(", "eval(", "subprocess", "socket", "urllib",
                       "requests", "open(", "os.", "sys.", "random", "time.", "datetime", "CapabilityRegistry",
                       ".register(", "lookup(", "list_capabilities(", "match_capability", "global ",
                       "difflib", ".lower(", ".upper(", ".strip(", "startswith", "endswith", "casefold",
                       "sorted(", "_entries"):
            self.assertNotIn(banned, body, banned)

    def test_other_layers_do_not_reference_selection(self):
        for folder in ("core", "memory", "ael", "reasoning", "understanding", "planning", "agent",
                       "execution", "learning", "language_intelligence", "tools", "self_upgrade"):
            for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                            self.assertNotIn("capability_selection", fh.read(), f)
        for module in (cr, ci, cl, cv, cm):
            self.assertNotIn("capability_selection", inspect.getsource(module))


class BackwardCompatibilityTests(unittest.TestCase):
    def test_matching_unchanged(self):
        self.assertEqual(cm.STATUSES, ("matched", "no_match", "no_valid_match", "invalid_requirement",
                                       "invalid_registry", "matching_error"))
        self.assertEqual(list(real_match(desc())), ["status", "matched", "candidate_count", "matches",
                                                    "rejected", "truncated", "execution_allowed", "executed"])
        self.assertEqual(real_match(desc(), minimum_version=4)["status"], "no_valid_match")
        self.assertEqual(real_match(desc(), name="text")["status"], "no_match")
        self.assertEqual((cm.MAX_SCAN, cm.MAX_MATCHES, cm.MAX_REJECTED), (256, 16, 16))

    def test_registry_unchanged(self):
        self.assertEqual([n for n in dir(cr.CapabilityRegistry) if not n.startswith("_")],
                         ["list_capabilities", "lookup", "register"])
        reg = CapabilityRegistry()
        self.assertEqual(reg.register(desc())["status"], "registered")
        self.assertEqual(reg.register(desc())["reason"], "duplicate")
        self.assertEqual(reg.register(desc(version=4))["reason"], "conflict")
        self.assertEqual(reg.lookup("text_summary")["descriptor"], desc())

    def test_identity_lifecycle_validation_unchanged(self):
        self.assertEqual(ci.build_capability_identity(desc())["identity"], {"name": "text_summary"})
        self.assertEqual(ci.compare_capability_versions(3, 2)["relation"], "newer")
        self.assertEqual(cl.list_lifecycle_transitions()["count"], 9)
        v = cv.validate_capability(desc())
        self.assertTrue(v["valid"])
        self.assertIsNone(v["lifecycle_valid"])

    def test_earlier_tests_present(self):
        for name in ("test_capability_registry_prompt841.py", "test_capability_identity_prompt842.py",
                     "test_capability_lifecycle_prompt843.py", "test_capability_validation_prompt844.py",
                     "test_capability_matching_prompt845.py", "test_capability_boundary_prompt840.py"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "tests", name)), name)

    def test_older_capability_modules_preserved(self):
        from capabilities import capability_system as csys
        self.assertEqual(len(csys.PLANNED_CAPABILITIES), 8)
        with open(os.path.join(ROOT, "capabilities", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read().strip(), b"")


if __name__ == "__main__":
    unittest.main()
