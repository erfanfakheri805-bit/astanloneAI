"""
Prompt 845 - capability discovery/matching foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_matching_prompt845 -v
"""

import ast
import copy
import inspect
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_matching as cm
from capabilities import capability_registry as cr
from capabilities import capability_identity as ci
from capabilities import capability_lifecycle as cl
from capabilities import capability_validation as cv
from capabilities.capability_matching import match_capability as match
from capabilities.capability_registry import CapabilityRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULT_KEYS = ["status", "matched", "candidate_count", "matches", "rejected", "truncated",
               "execution_allowed", "executed"]


def desc(**over):
    d = {"name": "text_summary", "version": 3, "purpose": "Summarise supplied text.",
         "inputs": ["text", "language"], "outputs": ["summary", "keywords"],
         "constraints": [], "enabled": False}
    d.update(over)
    return d


def reg(*descriptors):
    r = CapabilityRegistry()
    for d in descriptors:
        assert r.register(d)["status"] == "registered", d
    return r


def req(**over):
    q = {"name": "text_summary"}
    q.update(over)
    return q


def codes(result, index=0):
    return [(x["code"], x["where"]) for x in result["rejected"][index]["reasons"]]


class StrSub(str):
    pass


class IntSub(int):
    pass


class ExactMatchTests(unittest.TestCase):
    def test_exact_match_shape(self):
        r = match(req(), reg(desc()))
        self.assertEqual(list(r), RESULT_KEYS)
        self.assertEqual(r["status"], "matched")
        self.assertIs(r["matched"], True)
        self.assertEqual(r["candidate_count"], 1)
        self.assertEqual(r["rejected"], [])
        self.assertIs(r["truncated"], False)
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        self.assertEqual(len(r["matches"]), 1)
        m = r["matches"][0]
        self.assertEqual(list(m), ["identity", "version", "descriptor"])
        self.assertEqual(m["identity"], {"name": "text_summary"})
        self.assertEqual(m["version"], 3)
        self.assertEqual(m["descriptor"], desc())

    def test_match_contains_only_registered_information(self):
        r = match(req(minimum_version=1, required_inputs=["text"], expected_outputs=["summary"]),
                  reg(desc()))
        self.assertEqual(r["matches"][0]["descriptor"], desc())
        self.assertNotIn("minimum_version", r["matches"][0])
        self.assertNotIn("required_inputs", r["matches"][0]["descriptor"])

    def test_disabled_descriptor_still_matches_and_is_not_changed(self):
        r = match(req(), reg(desc(enabled=False)))
        self.assertEqual(r["status"], "matched")
        self.assertIs(r["matches"][0]["descriptor"]["enabled"], False)
        r = match(req(), reg(desc(enabled=True)))
        self.assertIs(r["matches"][0]["descriptor"]["enabled"], True)
        self.assertIs(r["executed"], False)
        self.assertIs(r["execution_allowed"], False)

    def test_name_is_exact_only(self):
        r_ = reg(desc(), desc(name="text_summary_pro"), desc(name="summary"))
        for name in ("text", "text_summary_", "summary_text", "ext_summary", "text_summar",
                     "Text_Summary", "TEXT_SUMMARY", "text_summary ", " text_summary",
                     "text-summary", "textsummary"):
            r = match({"name": name}, r_)
            self.assertNotEqual(r["status"], "matched", name)
        self.assertEqual(match({"name": "summary"}, r_)["matches"][0]["identity"], {"name": "summary"})
        self.assertEqual(match({"name": "text_summary_pro"}, r_)["matches"][0]["identity"],
                         {"name": "text_summary_pro"})

    def test_no_alias_or_semantic_matching(self):
        r_ = reg(desc(name="summarize_text", purpose="Summarise supplied text."))
        for name in ("text_summary", "summariser", "summary", "shorten_text", "tl_dr"):
            self.assertEqual(match({"name": name}, r_)["status"], "no_match", name)

    def test_no_inference_from_inputs_or_outputs(self):
        r_ = reg(desc())
        r = match({"name": "summary"}, r_)  # an output name is not a capability name
        self.assertEqual(r["status"], "no_match")
        r = match({"name": "text"}, r_)     # an input name is not a capability name
        self.assertEqual(r["status"], "no_match")


class VersionConstraintTests(unittest.TestCase):
    def test_minimum_version_equal_newer_and_older(self):
        r_ = reg(desc(version=3))
        self.assertEqual(match(req(minimum_version=3), r_)["status"], "matched")
        self.assertEqual(match(req(minimum_version=2), r_)["status"], "matched")
        self.assertEqual(match(req(minimum_version=1), r_)["status"], "matched")
        r = match(req(minimum_version=4), r_)
        self.assertEqual(r["status"], "no_valid_match")
        self.assertIs(r["matched"], False)
        self.assertEqual(r["candidate_count"], 1)
        self.assertEqual(r["matches"], [])
        self.assertEqual(r["rejected"][0]["subject"], "candidate")
        self.assertEqual(r["rejected"][0]["name"], "text_summary")
        self.assertEqual(r["rejected"][0]["version"], 3)
        self.assertEqual(codes(r), [("version_below_minimum", "minimum_version")])

    def test_uses_prompt842_comparison(self):
        calls = []
        original = cm.compare_capability_versions

        def spy(left, right):
            calls.append((left, right))
            return original(left, right)
        cm.compare_capability_versions = spy
        try:
            match(req(minimum_version=2), reg(desc(version=5)))
        finally:
            cm.compare_capability_versions = original
        self.assertEqual(calls, [(5, 2)])

    def test_bounds_of_version(self):
        r_ = reg(desc(version=cr.MAX_VERSION))
        self.assertEqual(match(req(minimum_version=cr.MAX_VERSION), r_)["status"], "matched")
        self.assertEqual(match(req(minimum_version=1), reg(desc(version=1)))["status"], "matched")

    def test_no_minimum_means_any_version(self):
        for v in (1, 2, 1000):
            self.assertEqual(match(req(), reg(desc(version=v)))["status"], "matched")

    def test_malformed_minimum_versions(self):
        for bad in (0, -1, cr.MAX_VERSION + 1, True, False, 1.0, 1.5, "1", "v1", "", None, [1], {"v": 1},
                    IntSub(1), b"1", (1,)):
            r = match(req(minimum_version=bad), reg(desc()))
            self.assertEqual(r["status"], "invalid_requirement", repr(bad))
            self.assertEqual(r["candidate_count"], 0)
            self.assertEqual(r["matches"], [])
            self.assertEqual(r["rejected"][0]["subject"], "requirement")
            self.assertEqual(r["rejected"][0]["reasons"][0]["where"], "minimum_version")
        r = match(req(minimum_version="1"), reg(desc()))
        self.assertEqual(codes(r), [("invalid_version_type", "minimum_version")])
        r = match(req(minimum_version=0), reg(desc()))
        self.assertEqual(codes(r), [("version_out_of_range", "minimum_version")])


class InputOutputRequirementTests(unittest.TestCase):
    def test_required_inputs_subset_matches(self):
        r_ = reg(desc())
        for inputs in ([], ["text"], ["language"], ["language", "text"], ["text", "language"]):
            self.assertEqual(match(req(required_inputs=inputs), r_)["status"], "matched", inputs)

    def test_required_input_missing(self):
        r = match(req(required_inputs=["text", "audio"]), reg(desc()))
        self.assertEqual(r["status"], "no_valid_match")
        self.assertEqual(codes(r), [("required_input_missing", "required_inputs[1]")])

    def test_expected_outputs_subset_matches(self):
        r_ = reg(desc())
        self.assertEqual(match(req(required_inputs=["Text"]), r_)["status"], "invalid_requirement")
        self.assertEqual(match(req(expected_outputs=["Summary"]), r_)["status"], "invalid_requirement")
        for outputs in ([], ["summary"], ["keywords", "summary"]):
            self.assertEqual(match(req(expected_outputs=outputs), r_)["status"], "matched", outputs)

    def test_expected_output_missing(self):
        r = match(req(expected_outputs=["summary", "sentiment", "topic"]), reg(desc()))
        self.assertEqual(r["status"], "no_valid_match")
        self.assertEqual(codes(r), [("expected_output_missing", "expected_outputs[1]"),
                                    ("expected_output_missing", "expected_outputs[2]")])

    def test_inputs_and_outputs_are_not_confused(self):
        r = match(req(required_inputs=["summary"]), reg(desc()))
        self.assertEqual(r["status"], "no_valid_match")
        r = match(req(expected_outputs=["text"]), reg(desc()))
        self.assertEqual(r["status"], "no_valid_match")

    def test_no_substring_or_case_matching_of_identifiers(self):
        r_ = reg(desc())
        for inputs in (["tex"], ["text_"], ["lang"], ["texts"]):
            self.assertEqual(match(req(required_inputs=inputs), r_)["status"], "no_valid_match", inputs)
        for outputs in (["summ"], ["summary_"], ["key"]):
            self.assertEqual(match(req(expected_outputs=outputs), r_)["status"], "no_valid_match", outputs)

    def test_capability_without_inputs(self):
        r_ = reg(desc(inputs=[]))
        self.assertEqual(match(req(required_inputs=[]), r_)["status"], "matched")
        self.assertEqual(match(req(required_inputs=["text"]), r_)["status"], "no_valid_match")

    def test_all_constraints_combined_and_reported_in_order(self):
        r = match(req(minimum_version=9, required_inputs=["x_in"], expected_outputs=["x_out"]), reg(desc()))
        self.assertEqual(codes(r), [("version_below_minimum", "minimum_version"),
                                    ("required_input_missing", "required_inputs[0]"),
                                    ("expected_output_missing", "expected_outputs[0]")])
        ok = match(req(minimum_version=3, required_inputs=["text"], expected_outputs=["keywords"]), reg(desc()))
        self.assertEqual(ok["status"], "matched")


class MultipleCandidatesTests(unittest.TestCase):
    def test_only_exact_name_selected_among_many(self):
        names = ["alpha", "text_summary", "text_summary_v2", "summary", "zeta_tool", "text"]
        r_ = reg(*[desc(name=n, version=i + 1) for i, n in enumerate(names)])
        r = match(req(), r_)
        self.assertEqual(r["status"], "matched")
        self.assertEqual(r["candidate_count"], 1)
        self.assertEqual([m["identity"]["name"] for m in r["matches"]], ["text_summary"])
        self.assertEqual(r["matches"][0]["version"], 2)

    def test_registration_order_does_not_matter(self):
        ds = [desc(name=n, version=i + 1) for i, n in enumerate(["b_cap", "a_cap", "text_summary", "c_cap"])]
        forward = match(req(), reg(*ds))
        backward = match(req(), reg(*reversed(ds)))
        self.assertEqual(forward["matches"][0]["descriptor"]["name"], "text_summary")
        self.assertEqual(forward["matches"][0]["identity"], backward["matches"][0]["identity"])
        self.assertEqual(forward["candidate_count"], backward["candidate_count"])

    def test_registry_with_conflicting_version_keeps_first_registered(self):
        r_ = reg(desc(version=2))
        self.assertEqual(r_.register(desc(version=5))["reason"], "conflict")
        r = match(req(minimum_version=3), r_)
        self.assertEqual(r["status"], "no_valid_match")
        self.assertEqual(r["rejected"][0]["version"], 2)

    def test_multiple_candidates_via_corrupted_registry(self):
        # Two entries share the requested descriptor name (only possible for a
        # registry whose private store was altered); both are candidates.
        r_ = reg(desc())
        r_._entries["alias_key"] = desc(version=7)
        r = match(req(), r_)
        self.assertEqual(r["candidate_count"], 2)
        self.assertEqual(r["status"], "matched")
        self.assertEqual([m["version"] for m in r["matches"]], [3])
        self.assertEqual(codes(r), [("registry_key_mismatch", "registry")])
        self.assertEqual(r["rejected"][0]["version"], 7)

    def test_multiple_valid_matches_are_ordered_and_bounded(self):
        r_ = CapabilityRegistry()
        for i in range(cm.MAX_MATCHES + 4):
            r_._entries["text_summary"] = desc()
            r_._entries["k%03d" % i] = desc()
        # keys other than the exact name are key mismatches -> rejected, bounded
        r = match(req(), r_)
        self.assertEqual(r["candidate_count"], cm.MAX_MATCHES + 5)
        self.assertEqual(len(r["matches"]), 1)
        self.assertEqual(len(r["rejected"]), cm.MAX_REJECTED)
        self.assertIs(r["truncated"], True)

    def test_matches_are_bounded(self):
        original = cm.MAX_MATCHES
        r_ = reg(desc())
        r_._entries["x"] = desc()
        cm.MAX_MATCHES = 0
        try:
            r = match(req(), r_)
        finally:
            cm.MAX_MATCHES = original
        self.assertEqual(r["matches"], [])
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["status"], "no_valid_match")


class NoMatchTests(unittest.TestCase):
    def test_empty_registry(self):
        r = match(req(), CapabilityRegistry())
        self.assertEqual(r, {"status": "no_match", "matched": False, "candidate_count": 0,
                             "matches": [], "rejected": [], "truncated": False,
                             "execution_allowed": False, "executed": False})

    def test_unknown_name(self):
        r = match({"name": "unknown_cap"}, reg(desc()))
        self.assertEqual(r["status"], "no_match")
        self.assertEqual(r["candidate_count"], 0)
        self.assertEqual(r["matches"], [])

    def test_nothing_is_invented(self):
        r_ = reg(desc())
        r = match({"name": "never_registered", "minimum_version": 1, "required_inputs": ["text"],
                   "expected_outputs": ["summary"]}, r_)
        self.assertEqual(r["status"], "no_match")
        self.assertEqual(r["matches"], [])
        self.assertEqual(len(r_), 1)
        self.assertEqual(r_.lookup("never_registered")["found"], False)

    def test_statuses_are_known(self):
        self.assertEqual(cm.STATUSES, ("matched", "no_match", "no_valid_match", "invalid_requirement",
                                       "invalid_registry", "matching_error"))
        cases = [match(req(), reg(desc())), match(req(), CapabilityRegistry()),
                 match(req(minimum_version=99), reg(desc())), match(None, None), match(req(), None)]
        for r in cases:
            self.assertIn(r["status"], cm.STATUSES)
            self.assertIs(r["matched"], r["status"] == "matched")


class MalformedRequirementTests(unittest.TestCase):
    def assert_invalid(self, requirement, where=None, code=None):
        r = match(requirement, reg(desc()))
        self.assertEqual(r["status"], "invalid_requirement", repr(requirement))
        self.assertIs(r["matched"], False)
        self.assertEqual(r["candidate_count"], 0)
        self.assertEqual(r["matches"], [])
        self.assertEqual(len(r["rejected"]), 1)
        self.assertEqual(r["rejected"][0]["subject"], "requirement")
        self.assertIsNone(r["rejected"][0]["name"])
        if where is not None:
            self.assertIn((code, where), codes(r))
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)
        json.dumps(r)
        return r

    def test_not_a_dict(self):
        for bad in (None, 1, "text_summary", ["text_summary"], ("name", "text_summary"), True, 1.5,
                    object(), set(), b"x"):
            self.assert_invalid(bad, "requirement", "requirement_not_dict")

    def test_dict_subclass_rejected(self):
        class D(dict):
            pass
        self.assert_invalid(D(name="text_summary"), "requirement", "requirement_not_dict")

    def test_missing_name(self):
        self.assert_invalid({}, "name", "missing_field")
        self.assert_invalid({"minimum_version": 1}, "name", "missing_field")

    def test_invalid_names(self):
        for bad in ("", " ", "Text", "text summary", "1text", "text-summary", "x" * 65, None, 1, True,
                    StrSub("text_summary"), ["text_summary"], b"text_summary", "_x"):
            self.assert_invalid(req(name=bad), "name", "invalid_name")

    def test_trailing_newline_name_never_matches_plain_name(self):
        # The Prompt 841 identifier rule (unchanged) accepts a trailing newline; matching is by exact
        # string equality, so such a name can never select the plain name (or vice versa).
        r = match(req(name="text_summary\n"), reg(desc()))
        self.assertEqual(r["status"], "no_match")
        r = match(req(), reg(desc(name="text_summary\n")))
        self.assertEqual(r["status"], "no_match")
        r = match(req(name="text_summary\n"), reg(desc(name="text_summary\n")))
        self.assertEqual(r["status"], "matched")

    def test_unexpected_fields(self):
        for key in ("handler", "alias", "aliases", "version", "capability", "execute", "inputs", "outputs"):
            self.assert_invalid(req(**{key: 1}), key, "unexpected_field")
        r = self.assert_invalid(req(**{"x" * 100: 1}), "<field>", "unexpected_field")
        self.assertNotIn("x" * 100, json.dumps(r))

    def test_malformed_lists(self):
        for bad in (None, "text", ("text",), {"text"}, {"text": 1}, 1, True):
            self.assert_invalid(req(required_inputs=bad), "required_inputs", "invalid_required_inputs")
            self.assert_invalid(req(expected_outputs=bad), "expected_outputs", "invalid_expected_outputs")

    def test_malformed_list_items(self):
        for bad in ("", "Text", "text input", 1, None, True, ["text"], StrSub("text"), "x" * 65):
            self.assert_invalid(req(required_inputs=["text", bad]), "required_inputs[1]", "invalid_item")
            self.assert_invalid(req(expected_outputs=[bad]), "expected_outputs[0]", "invalid_item")

    def test_duplicate_list_items(self):
        self.assert_invalid(req(required_inputs=["text", "text"]), "required_inputs[1]", "duplicate_item")
        self.assert_invalid(req(expected_outputs=["a", "b", "a"]), "expected_outputs[2]", "duplicate_item")

    def test_too_many_items(self):
        many = ["i%d" % n for n in range(cr.MAX_ITEMS + 1)]
        self.assert_invalid(req(required_inputs=many), "required_inputs", "too_many_items")
        self.assert_invalid(req(expected_outputs=many), "expected_outputs", "too_many_items")
        ok = ["i%d" % n for n in range(cr.MAX_ITEMS)]
        self.assertEqual(match(req(required_inputs=ok), reg(desc())).get("status"), "no_valid_match")

    def test_huge_inputs_are_bounded(self):
        big = ["i%d" % n for n in range(100000)]
        r = match(req(required_inputs=big, expected_outputs=big), reg(desc()))
        self.assertEqual(r["status"], "invalid_requirement")
        self.assertLessEqual(len(r["rejected"][0]["reasons"]), cr.MAX_ERRORS)
        wide = {"k%d" % n: n for n in range(100000)}
        wide["name"] = "text_summary"
        r = match(wide, reg(desc()))
        self.assertEqual(r["status"], "invalid_requirement")
        self.assertLessEqual(len(r["rejected"][0]["reasons"]), cr.MAX_ERRORS)

    def test_many_errors_truncated(self):
        bad = {"name": 1, "minimum_version": "x", "required_inputs": [1] * 16, "expected_outputs": [None] * 16,
               "extra1": 1, "extra2": 2}
        r = match(bad, reg(desc()))
        self.assertEqual(r["status"], "invalid_requirement")
        self.assertLessEqual(len(r["rejected"][0]["reasons"]), cr.MAX_ERRORS)
        self.assertIs(r["truncated"], True)

    def test_empty_lists_are_valid(self):
        r = match(req(required_inputs=[], expected_outputs=[]), reg(desc()))
        self.assertEqual(r["status"], "matched")

    def test_requirement_not_modified(self):
        q = {"name": "text_summary", "minimum_version": 2, "required_inputs": ["text"],
             "expected_outputs": ["summary"]}
        snap = copy.deepcopy(q)
        match(q, reg(desc()))
        self.assertEqual(q, snap)


class InvalidRegistryTests(unittest.TestCase):
    def test_not_a_registry(self):
        class Fake:
            _entries = {"text_summary": desc()}

        class Sub(CapabilityRegistry):
            pass
        for bad in (None, 1, "registry", {}, {"text_summary": desc()}, [desc()], Fake(), Sub(), object(),
                    CapabilityRegistry):
            r = match(req(), bad)
            self.assertEqual(r["status"], "invalid_registry", repr(bad))
            self.assertIs(r["matched"], False)
            self.assertEqual(r["candidate_count"], 0)
            self.assertEqual(r["matches"], [])
            self.assertEqual(r["rejected"][0]["subject"], "registry")
            self.assertEqual(codes(r), [("registry_not_capability_registry", "registry")])

    def test_registry_with_broken_store(self):
        for bad in (None, [], "x", 1, set()):
            r_ = CapabilityRegistry()
            r_._entries = bad
            r = match(req(), r_)
            self.assertEqual(r["status"], "invalid_registry")
            self.assertEqual(codes(r), [("registry_entries_invalid", "registry")])

    def test_registry_missing_store(self):
        r_ = CapabilityRegistry()
        del r_._entries
        self.assertEqual(match(req(), r_)["status"], "invalid_registry")

    def test_requirement_checked_before_registry(self):
        self.assertEqual(match(None, None)["status"], "invalid_requirement")
        self.assertEqual(match({"name": "Bad"}, None)["status"], "invalid_requirement")

    def test_invalid_entries_are_rejected_not_matched(self):
        bad_entries = {
            "missing_purpose": {k: v for k, v in desc().items() if k != "purpose"},
            "bad_version": desc(version="3"),
            "bool_version": desc(version=True),
            "unexpected": dict(desc(), handler="x"),
            "no_outputs": desc(outputs=[]),
            "bad_enabled": desc(enabled="yes"),
            "dup_inputs": desc(inputs=["text", "text"]),
            "not_dict": ["text_summary"],
        }
        for label, entry in bad_entries.items():
            r_ = CapabilityRegistry()
            r_._entries["text_summary"] = entry
            r = match(req(), r_)
            if label == "not_dict":
                # a non-dict entry stored under the exact key is still a candidate
                self.assertEqual(r["candidate_count"], 1, label)
            self.assertEqual(r["status"], "no_valid_match", label)
            self.assertEqual(r["matches"], [], label)
            self.assertEqual(r["rejected"][0]["subject"], "candidate", label)
            self.assertTrue(r["rejected"][0]["reasons"], label)
            self.assertIs(r["executed"], False)
            json.dumps(r)

    def test_invalid_entry_errors_come_from_prompt844(self):
        r_ = CapabilityRegistry()
        entry = desc(version="3")
        r_._entries["text_summary"] = entry
        r = match(req(), r_)
        self.assertEqual(r["rejected"][0]["reasons"], cv.validate_capability(entry)["errors"])
        self.assertIsNone(r["rejected"][0]["version"])

    def test_invalid_entry_version_not_echoed(self):
        r_ = CapabilityRegistry()
        r_._entries["text_summary"] = desc(version="secret")
        r = match(req(), r_)
        self.assertNotIn("secret", json.dumps(r))

    def test_invalid_entry_does_not_hide_valid_one(self):
        r_ = reg(desc())
        r_._entries["zzz"] = desc(version="x")      # not a candidate by key, but by name
        r_._entries["aaa"] = 12345                   # garbage, not a candidate
        r_._entries[7] = {"name": "other"}           # non-str key, not a candidate
        r = match(req(), r_)
        self.assertEqual(r["status"], "matched")
        self.assertEqual(r["candidate_count"], 2)
        self.assertEqual(len(r["matches"]), 1)
        self.assertEqual(len(r["rejected"]), 1)

    def test_invalid_entries_for_other_names_are_ignored(self):
        r_ = reg(desc())
        r_._entries["other_cap"] = desc(version="bad", name="other_cap")
        r = match(req(), r_)
        self.assertEqual(r["status"], "matched")
        self.assertEqual(r["candidate_count"], 1)
        self.assertEqual(r["rejected"], [])

    def test_key_mismatch_is_rejected(self):
        r_ = CapabilityRegistry()
        r_._entries["other_key"] = desc()
        r = match(req(), r_)
        self.assertEqual(r["status"], "no_valid_match")
        self.assertEqual(codes(r), [("registry_key_mismatch", "registry")])

    def test_exact_key_with_different_inner_name(self):
        r_ = CapabilityRegistry()
        r_._entries["text_summary"] = desc(name="other_cap")
        r = match(req(), r_)
        self.assertEqual(r["status"], "no_valid_match")
        self.assertEqual(r["candidate_count"], 1)
        self.assertEqual(r["matches"], [])
        self.assertEqual(codes(r), [("descriptor_name_mismatch", "name")])

    def test_exception_in_validation_is_contained(self):
        class Evil(dict):
            def get(self, *a, **k):
                raise RuntimeError("boom")
        r_ = CapabilityRegistry()
        r_._entries["text_summary"] = Evil(desc())
        r = match(req(), r_)
        self.assertIn(r["status"], cm.STATUSES)
        self.assertIs(r["executed"], False)
        json.dumps(r)

    def test_scan_is_bounded(self):
        r_ = reg(desc(name="zzz_last"))
        for i in range(cm.MAX_SCAN + 10):
            r_._entries["e%05d" % i] = desc(name="e%05d" % i)
        r = match({"name": "zzz_last"}, r_)
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["status"], "matched")      # first MAX_SCAN insertion entries include it
        r = match({"name": "e%05d" % (cm.MAX_SCAN + 5)}, r_)
        self.assertIs(r["truncated"], True)
        self.assertEqual(r["status"], "no_match")     # beyond the scan bound: never claimed
        self.assertEqual(r["candidate_count"], 0)

    def test_full_registry_not_truncated(self):
        r_ = CapabilityRegistry()
        for i in range(cr.MAX_CAPABILITIES):
            self.assertEqual(r_.register(desc(name="c%03d" % i))["status"], "registered")
        r = match({"name": "c255"}, r_)
        self.assertEqual(r["status"], "matched")
        self.assertIs(r["truncated"], False)
        self.assertEqual(r["candidate_count"], 1)

    def test_rejected_reasons_bounded(self):
        r_ = CapabilityRegistry()
        r_._entries["text_summary"] = desc(inputs=[1] * 16, outputs=[None] * 16, constraints=[2] * 16)
        r = match(req(), r_)
        self.assertLessEqual(len(r["rejected"][0]["reasons"]), cr.MAX_ERRORS)
        self.assertIs(r["truncated"], True)


class DeterminismAndSafetyTests(unittest.TestCase):
    def test_deterministic(self):
        r_ = reg(desc(), desc(name="other_cap"))
        q = req(minimum_version=2, required_inputs=["text"])
        first = match(q, r_)
        for _ in range(5):
            self.assertEqual(match(q, r_), first)

    def test_fresh_results(self):
        r_ = reg(desc())
        a = match(req(), r_)
        b = match(req(), r_)
        self.assertIsNot(a, b)
        self.assertIsNot(a["matches"], b["matches"])
        self.assertIsNot(a["matches"][0]["descriptor"], b["matches"][0]["descriptor"])
        self.assertIsNot(a["matches"][0]["descriptor"]["inputs"], b["matches"][0]["descriptor"]["inputs"])
        a["matches"][0]["descriptor"]["inputs"].append("zzz")
        a["matches"][0]["descriptor"]["name"] = "changed"
        c = match(req(), r_)
        self.assertEqual(c["matches"][0]["descriptor"], desc())
        self.assertEqual(r_.lookup("text_summary")["descriptor"], desc())

    def test_mutating_original_descriptor_after_registration_has_no_effect(self):
        d = desc()
        r_ = reg(d)
        d["inputs"].append("zzz")
        d["name"] = "other_cap"
        self.assertEqual(match(req(), r_)["matches"][0]["descriptor"], desc())

    def test_json_safe_for_all_statuses(self):
        results = [match(req(), reg(desc())), match(req(), CapabilityRegistry()),
                   match(req(minimum_version=9), reg(desc())), match(None, None), match(req(), None)]
        for r in results:
            self.assertEqual(json.loads(json.dumps(r)), r)
            self.assertEqual(list(r), RESULT_KEYS)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_never_raises(self):
        weird = [None, 0, "x", [], {}, object(), float("nan"), b"\xff", type, lambda: 1, StrSub("a"),
                 {"name": object()}, {"name": "ok_name", "minimum_version": object()},
                 {"name": "ok_name", "required_inputs": [object()]}]
        for q in weird:
            for g in weird + [CapabilityRegistry(), reg(desc())]:
                r = match(q, g)
                self.assertEqual(list(r), RESULT_KEYS)
                self.assertIs(r["executed"], False)

    def test_defaults_do_not_raise(self):
        self.assertEqual(match()["status"], "invalid_requirement")
        self.assertEqual(match(req())["status"], "invalid_registry")

    def test_registry_is_not_changed(self):
        r_ = reg(desc(), desc(name="other_cap", version=2))
        before = r_.list_capabilities()
        entries_before = {k: copy.deepcopy(v) for k, v in r_._entries.items()}
        for q in (req(), req(minimum_version=99), {"name": "nothing_here"}, None, {"name": "Bad"}):
            match(q, r_)
        self.assertEqual(r_.list_capabilities(), before)
        self.assertEqual(r_._entries, entries_before)
        self.assertEqual(len(r_), 2)

    def test_no_global_state_between_registries(self):
        a, b = reg(desc()), CapabilityRegistry()
        self.assertEqual(match(req(), a)["status"], "matched")
        self.assertEqual(match(req(), b)["status"], "no_match")
        self.assertEqual(match(req(), a)["status"], "matched")


class BoundaryTests(unittest.TestCase):
    def test_module_imports_only_existing_capability_layers(self):
        tree = ast.parse(inspect.getsource(cm))
        imports = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                imports.append((node.module, node.level))
            elif isinstance(node, ast.Import):
                imports.extend((a.name, 0) for a in node.names)
        self.assertEqual(sorted(imports), [
            ("capability_identity", 1), ("capability_registry", 1), ("capability_validation", 1),
            ("copy", 0), ("itertools", 0)])

    def test_no_execution_loading_io_or_mutation(self):
        body = inspect.getsource(cm).split('"""', 2)[2]
        for banned in ("importlib", "__import__", "exec(", "eval(", "subprocess", "socket", "urllib",
                       "requests", "open(", "os.", "sys.", "random", "time.", "datetime", ".register(",
                       "global ", "difflib", ".lower(", ".upper(", ".strip(", " in name", "startswith",
                       "endswith", "casefold", "lookup(", "list_capabilities(", "del ", ".pop(", "_entries["):
            self.assertNotIn(banned, body, banned)

    def test_no_connection_to_core_memory_ael(self):
        text = inspect.getsource(cm)
        for needle in ("core", "memory", "ael", "reasoning", "understanding", "agent", "planning"):
            for line in text.splitlines():
                if line.startswith(("import ", "from ")):
                    self.assertNotIn(needle, line)

    def test_other_layers_do_not_reference_matching(self):
        for folder in ("core", "memory", "ael", "reasoning", "understanding", "planning", "agent",
                       "execution", "learning", "language_intelligence", "tools", "self_upgrade"):
            for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                            text = fh.read()
                        self.assertNotIn("capability_matching", text, f)
        for module in (cr, ci, cl, cv):
            self.assertNotIn("capability_matching", inspect.getsource(module))

    def test_constants(self):
        self.assertEqual(cm.MAX_SCAN, cr.MAX_CAPABILITIES)
        self.assertEqual(cm.MAX_MATCHES, 16)
        self.assertEqual(cm.MAX_REJECTED, 16)
        self.assertEqual(cm.REQUIREMENT_FIELDS,
                         ("name", "minimum_version", "required_inputs", "expected_outputs"))


class BackwardCompatibilityTests(unittest.TestCase):
    def test_registry_unchanged(self):
        self.assertEqual(cr.DESCRIPTOR_FIELDS, ("name", "version", "purpose", "inputs", "outputs",
                                                "constraints", "enabled"))
        self.assertEqual([n for n in dir(cr.CapabilityRegistry) if not n.startswith("_")],
                         ["list_capabilities", "lookup", "register"])
        r_ = CapabilityRegistry()
        self.assertEqual(r_.register(desc())["status"], "registered")
        self.assertEqual(r_.register(desc())["reason"], "duplicate")
        self.assertEqual(r_.register(desc(version=4))["reason"], "conflict")
        self.assertEqual(r_.register(desc(version="2"))["reason"], "malformed")
        self.assertEqual(r_.lookup("text_summary")["descriptor"], desc())
        self.assertEqual(r_.list_capabilities()["count"], 1)

    def test_matching_after_registry_use_does_not_alter_registry_apis(self):
        r_ = reg(desc())
        match(req(), r_)
        self.assertEqual(r_.lookup("text_summary")["found"], True)
        self.assertEqual(r_.list_capabilities()["capabilities"], [desc()])
        self.assertEqual(r_.register(desc())["reason"], "duplicate")

    def test_identity_and_version_unchanged(self):
        self.assertEqual(ci.build_capability_identity(desc())["identity"], {"name": "text_summary"})
        self.assertEqual(ci.parse_capability_version(2)["number"], 2)
        self.assertFalse(ci.parse_capability_version("2")["valid"])
        self.assertEqual(ci.compare_capability_versions(3, 2)["relation"], "newer")
        self.assertEqual(ci.classify_capability_descriptors(desc(), desc(version=4))["classification"],
                         "newer_version")

    def test_lifecycle_unchanged(self):
        self.assertEqual(cl.list_lifecycle_states()["states"],
                         ["defined", "validated", "enabled", "disabled", "deprecated"])
        self.assertEqual(cl.list_lifecycle_transitions()["count"], 9)
        self.assertTrue(cl.evaluate_lifecycle_transition("defined", "validated")["allowed"])

    def test_validation_unchanged(self):
        v = cv.validate_capability(desc())
        self.assertEqual(list(v), ["valid", "errors", "name", "version", "identity_valid", "version_valid",
                                   "lifecycle_valid", "truncated", "execution_allowed", "executed"])
        self.assertTrue(v["valid"])
        self.assertIsNone(v["lifecycle_valid"])
        self.assertFalse(cv.validate_capability(desc(version="1"))["valid"])

    def test_earlier_tests_present(self):
        for name in ("test_capability_registry_prompt841.py", "test_capability_identity_prompt842.py",
                     "test_capability_lifecycle_prompt843.py", "test_capability_validation_prompt844.py",
                     "test_capability_boundary_prompt840.py"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "tests", name)), name)

    def test_older_capability_modules_preserved(self):
        from capabilities import capability_system as cs
        self.assertEqual(len(cs.PLANNED_CAPABILITIES), 8)
        with open(os.path.join(ROOT, "capabilities", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read().strip(), b"")

    def test_reasoning_apis_preserved(self):
        from reasoning.capability_contract import build_capability_contract, validate_capability_contract
        from reasoning.capability_boundary import evaluate_reasoning_capability_boundary as b
        for fn in (build_capability_contract, validate_capability_contract, b):
            self.assertTrue(callable(fn))
        self.assertFalse(b(None)["executed"])


if __name__ == "__main__":
    unittest.main()
