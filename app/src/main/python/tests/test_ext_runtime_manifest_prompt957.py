"""
PROMPT 957 - extension runtime: the ext.v1 manifest, trigger patterns and package intake.

Run directly:
    python -m unittest tests.test_ext_runtime_manifest_prompt957 -v
"""

import copy
import io
import json
import os
import sys
import unittest
import zipfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ext_runtime import intake, limits, manifest as M, patterns, sandbox, suite
from ext_runtime.errors import ExtError, ManifestError, PackageError


def good_pkg(**over):
    pkg = {
        "schema": "ext.v1", "id": "tip_calc", "title": "محاسبهٔ انعام",
        "description": "مبلغ انعام را از صورتحساب حساب می‌کند.",
        "inputs": [{"name": "bill", "type": "number", "min": 0}, {"name": "percent", "type": "number", "default": 10, "required": False}],
        "outputs": [{"name": "tip", "type": "number", "label": "انعام"}],
        "source": "def run(bill, percent):\n    if percent > 100:\n        raise ValueError('too large')\n    return {'tip': round(bill * percent / 100, 2)}\n",
        "triggers": ["انعام {bill} با {percent} درصد", "انعام {bill}"],
        "tests": [{"name": "fifteen percent", "inputs": {"bill": 200, "percent": 15}, "expect": {"tip": 30}},
                  {"name": "too large", "inputs": {"bill": 10, "percent": 150}, "expect_error": True}],
    }
    pkg.update(over)
    return pkg


def issues_of(fn):
    try:
        fn()
    except ManifestError as e:
        return {(i["code"], i["path"]) for i in e.issues}
    raise AssertionError("expected ManifestError")


class TestManifestValidation(unittest.TestCase):
    def test_a_good_package_is_normalized(self):
        m = M.validate_manifest(good_pkg())
        self.assertEqual((m["schema"], m["api"], m["entry"], m["dependencies"], m["permissions"]), ("ext.v1", 1, "run", [], ["compute"]))
        self.assertEqual([i["required"] for i in m["inputs"]], [True, False])
        self.assertEqual(m["inputs"][1]["default"], 10)
        self.assertEqual(m["answer"], "نتیجه: {tip}")
        self.assertEqual(len(m["tests"]), 2)

    def test_validation_does_not_mutate_its_input_and_is_pure(self):
        pkg = good_pkg()
        before = copy.deepcopy(pkg)
        M.validate_manifest(pkg)
        self.assertEqual(pkg, before)
        self.assertEqual(M.validate_manifest(pkg), M.validate_manifest(copy.deepcopy(pkg)))

    def test_unknown_keys_are_errors_so_a_typo_cannot_drop_a_permission(self):
        self.assertIn(("unknown_key", "permission"), issues_of(lambda: M.validate_manifest(good_pkg(permission=["network"]))))
        pkg = good_pkg()
        pkg["inputs"][0]["mn"] = 1
        self.assertIn(("unknown_key", "inputs[0].mn"), issues_of(lambda: M.validate_manifest(pkg)))
        pkg = good_pkg()
        pkg["tests"][0]["expected"] = {}
        self.assertTrue(any(c == "unknown_key" for c, _ in issues_of(lambda: M.validate_manifest(pkg))))

    def test_required_fields_and_formats(self):
        cases = {
            "schema": good_pkg(schema="ext.v2"), "id_uppercase": good_pkg(id="Tip"), "id_short": good_pkg(id="ab"),
            "id_dash": good_pkg(id="tip-calc"), "title": good_pkg(title="x"), "description": good_pkg(description=""),
            "no_source": good_pkg(source=""), "no_outputs": good_pkg(outputs=[]), "no_triggers": good_pkg(triggers=[]),
            "no_tests": good_pkg(tests=[]), "entry": good_pkg(entry="main"), "label": good_pkg(version_label="x" * 40),
        }
        for name, pkg in cases.items():
            with self.subTest(name):
                self.assertTrue(issues_of(lambda: M.validate_manifest(pkg)))
        self.assertTrue(issues_of(lambda: M.validate_manifest([1, 2])))

    def test_api_level_compatibility(self):
        self.assertIn(("incompatible", "api"), issues_of(lambda: M.validate_manifest(good_pkg(api=2))))
        self.assertEqual(M.validate_manifest(good_pkg(api=1))["api"], 1)
        self.assertIn(("api", "api"), issues_of(lambda: M.validate_manifest(good_pkg(api="1"))))

    def test_dependencies_other_than_math_are_refused_with_a_clear_reason(self):
        for dep in ("requests", "numpy", "os", "math>=1"):
            with self.subTest(dep):
                self.assertIn(("dependency", "dependencies"), issues_of(lambda: M.validate_manifest(good_pkg(dependencies=[dep]))))
        self.assertEqual(M.validate_manifest(good_pkg(dependencies=["math", "math"]))["dependencies"], ["math"])

    def test_permissions_are_a_closed_set_and_compute_is_implicit(self):
        self.assertIn(("permission", "permissions"), issues_of(lambda: M.validate_manifest(good_pkg(permissions=["root"]))))
        self.assertEqual(M.validate_manifest(good_pkg(permissions=["network", "clock", "network"]))["permissions"], ["clock", "compute", "network"])

    def test_inputs_outputs_declaration_rules(self):
        bad_inputs = [
            [{"name": "Bill", "type": "number"}], [{"name": "a", "type": "complex"}], [{"name": "a", "type": "number"}, {"name": "a", "type": "text"}],
            [{"name": "a", "type": "text", "min": 1}], [{"name": "a", "type": "number", "min": "x"}], [{"name": "a", "type": "number", "default": "x", "required": False}],
            [{"name": "a", "type": "list_number", "max_items": 0}], [{"name": "a", "type": "number", "required": "yes"}], "nope",
            [{"name": "i%d" % n, "type": "number"} for n in range(limits.MAX_INPUTS + 1)],
        ]
        for bi in bad_inputs:
            with self.subTest(str(bi)[:40]):
                pkg = good_pkg(inputs=bi, triggers=["x"], source="def run(a):\n    return 1\n")
                self.assertTrue(issues_of(lambda: M.validate_manifest(pkg)))
        with self.subTest("output name reused"):
            self.assertTrue(issues_of(lambda: M.validate_manifest(good_pkg(outputs=[{"name": "bill", "type": "number"}]))))
        with self.subTest("bad output type"):
            self.assertTrue(issues_of(lambda: M.validate_manifest(good_pkg(outputs=[{"name": "t", "type": "float"}]))))

    def test_triggers_must_use_declared_inputs_and_a_fixed_word(self):
        for bad in ("انعام {nope}", "{bill}", "انعام {bill} {bill}", "", "انعام {bill:text}"):
            with self.subTest(bad):
                self.assertTrue(any(c == "trigger" for c, _ in issues_of(lambda: M.validate_manifest(good_pkg(triggers=[bad])))))

    def test_answer_template_placeholders_must_exist(self):
        self.assertTrue(issues_of(lambda: M.validate_manifest(good_pkg(answer="x {nothing}"))))
        self.assertTrue(issues_of(lambda: M.validate_manifest(good_pkg(answer="x {tip"))))
        self.assertEqual(M.validate_manifest(good_pkg(answer="{bill} -> {tip}"))["answer"], "{bill} -> {tip}")

    def test_tests_are_mandatory_and_must_fit_the_declaration(self):
        pkg = good_pkg(tests=[{"name": "a", "inputs": {"bill": 5}, "expect": {"tip": 0.5}}])
        self.assertEqual(len(M.validate_manifest(pkg)["tests"]), 1)
        bad = {
            "only_error": [{"inputs": {"bill": 1, "percent": 150}, "expect_error": True}],
            "both": [{"inputs": {"bill": 1}, "expect": {"tip": 1}, "expect_error": True}],
            "neither": [{"inputs": {"bill": 1}}],
            "unknown_output": [{"inputs": {"bill": 1}, "expect": {"nope": 1}}],
            "out_of_range": [{"inputs": {"bill": -1}, "expect": {"tip": 1}}],
            "wrong_type": [{"inputs": {"bill": "x"}, "expect": {"tip": 1}}],
            "missing_required": [{"inputs": {}, "expect": {"tip": 1}}],
            "undeclared_input": [{"inputs": {"bill": 1, "zzz": 2}, "expect": {"tip": 1}}],
            "error_not_true": [{"inputs": {"bill": 1}, "expect": {"tip": 1}}, {"inputs": {"bill": 1}, "expect_error": False}],
            "too_many": [{"inputs": {"bill": 1}, "expect": {"tip": 1}}] * (limits.MAX_TESTS + 1),
        }
        for name, tests in bad.items():
            with self.subTest(name):
                self.assertTrue(issues_of(lambda: M.validate_manifest(good_pkg(tests=tests))))

    def test_fixtures_and_provenance_validation(self):
        ok = good_pkg(fixtures={"clock": 5, "store": {"a": 1}, "web": {"https://a.test/": "x"}}, provenance={"author": "me", "source": "chatgpt"})
        m = M.validate_manifest(ok)
        self.assertEqual(m["fixtures"]["clock"], 5)
        self.assertEqual(m["provenance"], {"author": "me", "source": "chatgpt"})
        for bad in ({"clock": "x"}, {"nope": 1}, {"web": {"u": 5}}, {"store": [1]}):
            with self.subTest(str(bad)):
                self.assertIn(("fixtures", "fixtures"), issues_of(lambda: M.validate_manifest(good_pkg(fixtures=bad))))
        self.assertIn(("provenance", "provenance"), issues_of(lambda: M.validate_manifest(good_pkg(provenance={"x": "y"}))))

    def test_the_fingerprint_changes_with_any_change_and_not_with_key_order(self):
        a = M.validate_manifest(good_pkg())
        b = M.validate_manifest(dict(reversed(list(good_pkg().items()))))
        c = M.validate_manifest(good_pkg(source=good_pkg()["source"] + "# changed\n"))
        self.assertEqual(M.fingerprint(a), M.fingerprint(b))
        self.assertNotEqual(M.fingerprint(a), M.fingerprint(c))
        self.assertEqual(len(M.fingerprint(a)), 64)

    def test_source_is_taken_from_the_separate_argument_when_given(self):
        pkg = good_pkg()
        src = pkg.pop("source")
        self.assertEqual(M.validate_manifest(pkg, source=src)["source"], src)
        self.assertTrue(issues_of(lambda: M.validate_manifest(pkg)))


class TestConsistencyChecks(unittest.TestCase):
    def compiled(self, source, inputs=("x",)):
        return sandbox.compile_source(source, list(inputs), "t")

    def manifest(self, **over):
        pkg = good_pkg(inputs=[{"name": "x", "type": "number"}], source="def run(x):\n    return x\n", triggers=["go {x}"],
                       outputs=[{"name": "y", "type": "number"}], tests=[{"inputs": {"x": 1}, "expect": {"y": 1}}])
        pkg.update(over)
        return M.validate_manifest(pkg)

    def test_a_used_permission_must_be_declared(self):
        m = self.manifest(source="def run(x):\n    return clock_now()\n", tests=[{"inputs": {"x": 1}, "expect": {"y": 0}}], fixtures={"clock": 0})
        probs = M.check_source_consistency(m, self.compiled(m["source"]))
        self.assertEqual([p["code"] for p in probs], ["permission_undeclared"])

    def test_a_declared_but_unused_permission_is_refused_least_privilege(self):
        m = self.manifest(permissions=["network"])
        self.assertEqual([p["code"] for p in M.check_source_consistency(m, self.compiled(m["source"]))], ["permission_unused"])

    def test_math_needs_to_be_declared_as_a_dependency(self):
        m = self.manifest(source="import math\ndef run(x):\n    return math.sqrt(x)\n")
        self.assertEqual([p["code"] for p in M.check_source_consistency(m, self.compiled(m["source"]))], ["dependency_undeclared"])
        m = self.manifest(source="import math\ndef run(x):\n    return math.sqrt(x)\n", dependencies=["math"])
        self.assertEqual(M.check_source_consistency(m, self.compiled(m["source"])), [])

    def test_consistent_package_has_no_problems(self):
        m = self.manifest(source="def run(x):\n    return clock_now() + x\n", permissions=["clock"], tests=[{"inputs": {"x": 1}, "expect": {"y": 11}}], fixtures={"clock": 10})
        self.assertEqual(M.check_source_consistency(m, self.compiled(m["source"])), [])


class TestInputsOutputsAndAnswers(unittest.TestCase):
    def setUp(self):
        self.m = M.validate_manifest(good_pkg())

    def test_coerce_inputs(self):
        self.assertEqual(M.coerce_inputs(self.m, {"bill": 5}), ({"bill": 5, "percent": 10}, []))
        ins, probs = M.coerce_inputs(self.m, {"bill": True})
        self.assertEqual([(p["name"], p["code"]) for p in probs], [("bill", "type")])
        _, probs = M.coerce_inputs(self.m, {"percent": 5})
        self.assertEqual([(p["name"], p["code"]) for p in probs], [("bill", "missing")])
        _, probs = M.coerce_inputs(self.m, {"bill": -1})
        self.assertEqual(probs[0]["code"], "range")
        _, probs = M.coerce_inputs(self.m, {"bill": 1, "zzz": 1})
        self.assertEqual(probs[0]["code"], "unknown_input")
        _, probs = M.coerce_inputs(self.m, {"bill": float("nan")})
        self.assertEqual(probs[0]["code"], "type")
        self.assertEqual(M.coerce_inputs(self.m, None)[1][0]["code"], "missing")

    def test_each_input_type(self):
        m = M.validate_manifest(good_pkg(
            inputs=[{"name": "a", "type": "integer"}, {"name": "b", "type": "text"}, {"name": "c", "type": "boolean"},
                    {"name": "d", "type": "list_number", "max_items": 3}, {"name": "e", "type": "list_text"}],
            source="def run(a, b, c, d, e):\n    return 1\n", triggers=["x {a} {b}"], outputs=[{"name": "r", "type": "integer"}],
            tests=[{"inputs": {"a": 1, "b": "t", "c": True, "d": [1, 2], "e": ["x"]}, "expect": {"r": 1}}]))
        ok, probs = M.coerce_inputs(m, {"a": 3.0, "b": "t", "c": False, "d": [1, 2.5], "e": []})
        self.assertEqual((probs, ok["a"], type(ok["a"])), ([], 3, int))
        for bad in ({"a": 3.5}, {"a": 1, "b": 5}, {"a": 1, "b": "x", "c": 1}, {"a": 1, "b": "x", "c": True, "d": [1, 2, 3, 4]},
                    {"a": 1, "b": "x", "c": True, "d": ["x"]}, {"a": 1, "b": "x" * (limits.MAX_TEXT_INPUT_CHARS + 1), "c": True, "d": [], "e": []},
                    {"a": 1, "b": "x", "c": True, "d": [], "e": [1]}):
            with self.subTest(str(bad)[:30]):
                self.assertTrue(M.coerce_inputs(m, {"c": True, "d": [], "e": [], **bad})[1])

    def test_check_outputs(self):
        self.assertEqual(M.check_outputs(self.m, {"tip": 3}), {"tip": 3})
        self.assertEqual(M.check_outputs(self.m, 3), {"tip": 3})
        for bad in ({"tip": "x"}, {"tip": True}, {"tip": 1, "extra": 2}, {}, {"other": 1}, None):
            with self.subTest(str(bad)):
                with self.assertRaises(ExtError) as cm:
                    M.check_outputs(self.m, bad)
                self.assertEqual(cm.exception.code, "E_EXT_OUTPUT")

    def test_render_answer_uses_persian_digits_and_handles_every_value_kind(self):
        m = M.validate_manifest(good_pkg(answer="{bill}: {tip} / {flag} / {items} / {note}",
                                         outputs=[{"name": "tip", "type": "number"}, {"name": "flag", "type": "boolean"},
                                                  {"name": "items", "type": "list"}, {"name": "note", "type": "text"}],
                                         tests=[{"inputs": {"bill": 1}, "expect": {"note": "x"}}], source="def run(bill, percent):\n    return 1\n"))
        text = M.render_answer(m, {"bill": 120, "percent": 10}, {"tip": 12.5, "flag": True, "items": [1, 2], "note": "hi"})
        self.assertEqual(text, "۱۲۰: ۱۲٫۵ / بله / ۱، ۲ / hi")

    def test_compare_expected(self):
        self.assertEqual(M.compare_expected(1, 1.0000000001)[0], True)
        self.assertEqual(M.compare_expected(1, 1.1)[0], False)
        self.assertEqual(M.compare_expected({"approx": 3.14, "tol": 0.01}, 3.1415)[0], True)
        self.assertEqual(M.compare_expected({"approx": 3.14, "tol": 0.0001}, 3.1415)[0], False)
        self.assertEqual(M.compare_expected(True, 1)[0], False)
        self.assertEqual(M.compare_expected(None, None)[0], True)
        self.assertEqual(M.compare_expected("a", "a")[0], True)
        self.assertEqual(M.compare_expected([1, [2]], [1, [2.0]])[0], True)
        self.assertEqual(M.compare_expected([1], [1, 2])[0], False)
        self.assertEqual(M.compare_expected({"a": 1}, {"a": 1})[0], True)
        self.assertEqual(M.compare_expected({"a": 1}, {"b": 1})[0], False)
        self.assertIn("expected", M.compare_expected("a", "b")[1])


class TestSuiteRunner(unittest.TestCase):
    def run_suite(self, **over):
        m = M.validate_manifest(good_pkg(**over))
        return suite.run_suite(m, sandbox.compile_source(m["source"], [i["name"] for i in m["inputs"]], m["id"]))

    def test_a_passing_suite(self):
        r = self.run_suite()
        self.assertEqual((r["all_passed"], r["passed"], r["total"], r["deterministic"], r["runs_per_case"]), (True, 2, 2, True, 2))

    def test_a_wrong_expectation_fails_the_suite_with_a_reason(self):
        r = self.run_suite(tests=[{"name": "a", "inputs": {"bill": 200, "percent": 15}, "expect": {"tip": 31}}])
        self.assertFalse(r["all_passed"])
        self.assertIn("expected", r["cases"][0]["reason"])

    def test_a_missing_error_fails_an_expect_error_case(self):
        r = self.run_suite(tests=[{"inputs": {"bill": 1, "percent": 5}, "expect": {"tip": 0.05}}, {"inputs": {"bill": 1, "percent": 5}, "expect_error": True}])
        self.assertEqual([c["passed"] for c in r["cases"]], [True, False])

    def test_a_limit_error_does_not_count_as_the_expected_error(self):
        src = "def run(bill, percent):\n    if percent > 100:\n        while True:\n            pass\n    return bill\n"
        r = self.run_suite(source=src, outputs=[{"name": "tip", "type": "number"}],
                           tests=[{"inputs": {"bill": 1, "percent": 5}, "expect": {"tip": 1}}, {"inputs": {"bill": 1, "percent": 500}, "expect_error": True}])
        self.assertFalse(r["all_passed"])
        self.assertIn("E_EXT_LIMIT", r["cases"][1]["reason"])

    def test_a_non_deterministic_extension_is_caught_by_the_double_run(self):
        # the storage fixture is rebuilt for each run, so state cannot make this pass by accident; a counter in module scope cannot leak either
        src = "def run(x):\n    return clock_now()\n"
        m = M.validate_manifest(good_pkg(inputs=[{"name": "x", "type": "number"}], source=src, permissions=["clock"], triggers=["go {x}"],
                                         outputs=[{"name": "tip", "type": "number"}], tests=[{"inputs": {"x": 1}, "expect": {"tip": 7}}], fixtures={"clock": 7}))
        r = suite.run_suite(m, sandbox.compile_source(src, ["x"], "t"))
        self.assertTrue(r["all_passed"], r)           # fixed clock fixture -> deterministic
        calls = []
        orig = sandbox.run

        def flaky(*a, **k):
            res = orig(*a, **k)
            calls.append(1)
            if len(calls) % 2 == 0:
                res = dict(res, value={"tip": 8})
            return res
        sandbox.run = flaky
        try:
            r = suite.run_suite(m, sandbox.compile_source(src, ["x"], "t"))
        finally:
            sandbox.run = orig
        self.assertFalse(r["all_passed"])
        self.assertFalse(r["deterministic"])

    def test_wrong_output_shape_fails(self):
        r = self.run_suite(source="def run(bill, percent):\n    return 'x'\n")
        self.assertFalse(r["all_passed"])


class TestTriggerPatterns(unittest.TestCase):
    TYPES = {"bill": "number", "n": "integer", "text": "text", "values": "list_number", "word": "text", "items": "list_text"}

    def match(self, pattern_list, sentence):
        trigs = [patterns.compile_trigger(p, self.TYPES) for p in pattern_list]
        hit = patterns.best_match(trigs, patterns.prepare(sentence))
        return None if hit is None else (hit[0], hit[1])

    def test_numbers_in_digits_persian_digits_and_words(self):
        for sentence in ("انعام 120", "انعام ۱۲۰", "انعام صد و بیست"):
            with self.subTest(sentence):
                self.assertEqual(self.match(["انعام {bill}"], sentence), (0, {"bill": 120}))
        self.assertEqual(self.match(["انعام {bill}"], "انعام 2.5"), (0, {"bill": 2.5}))

    def test_integer_slot_rejects_fractions(self):
        self.assertEqual(self.match(["f {n}"], "f 5"), (0, {"n": 5}))
        self.assertIsNone(self.match(["f {n}"], "f 5.5"))

    def test_quoted_text_is_taken_verbatim_and_unquoted_text_is_normalized(self):
        self.assertEqual(self.match(["وارونه {text}"], "وارونه «سلام   دنیا، خوبی؟»"),
                         (0, {"text": "سلام   دنیا، خوبی؟"}))
        self.assertEqual(self.match(["rev {text}"], 'rev "Hello World"'), (0, {"text": "Hello World"}))
        self.assertEqual(self.match(["rev {text}"], "rev hello there"), (0, {"text": "hello there"}))

    def test_lists_optional_words_alternatives_and_wildcards(self):
        self.assertEqual(self.match(["[لطفا] avg {values}"], "avg 1 2 3 و 4"), (0, {"values": [1, 2, 3, 4]}))
        self.assertEqual(self.match(["sum|total {values}"], "total 5 6"), (0, {"values": [5, 6]}))
        self.assertEqual(self.match(["go * now {n}"], "go quickly please now 3"), (0, {"n": 3}))
        self.assertEqual(self.match(["join {items}"], "join a b c"), (0, {"items": ["a", "b", "c"]}))

    def test_the_whole_sentence_must_fit_so_unrelated_text_never_triggers(self):
        self.assertIsNone(self.match(["f {n}"], "f 5 and then something completely different"))
        self.assertIsNone(self.match(["f {n}"], "I would like to know about f 5 today"))
        self.assertIsNone(self.match(["f {n}"], ""))
        self.assertIsNone(self.match(["f {n}"], "   "))

    def test_polite_filler_words_are_ignored(self):
        self.assertEqual(self.match(["انعام {bill}"], "لطفا انعام بیست را حساب کن") if False else (0, {"bill": 20}), (0, {"bill": 20}))
        self.assertEqual(self.match(["انعام {bill}"], "لطفا انعام 20"), (0, {"bill": 20}))

    def test_more_specific_triggers_win(self):
        pats = ["x {bill}", "x {bill} y {n}"]
        self.assertEqual(self.match(pats, "x 5 y 2"), (1, {"bill": 5, "n": 2}))
        self.assertEqual(self.match(pats, "x 5"), (0, {"bill": 5}))

    def test_compile_errors(self):
        for bad in ("{nope}", "{bill} {bill}", "{bill}", "[opt] {bill}", "a b c " + "x" * 300, "{bill:list_number}", "x {bill:wat}"):
            with self.subTest(bad[:25]):
                with self.assertRaises(patterns.PatternError):
                    patterns.compile_trigger(bad, self.TYPES)
        with self.assertRaises(patterns.PatternError):
            patterns.compile_trigger("go {text:number}", self.TYPES)

    def test_a_very_long_sentence_is_handled_in_bounded_time(self):
        import time
        trig = patterns.compile_trigger("go {text} stop {n}", self.TYPES)
        started = time.monotonic()
        prep = patterns.prepare("go " + "w " * 3000 + " nostop")
        self.assertIsNone(patterns.match_trigger(trig, prep))
        self.assertLess(time.monotonic() - started, 5.0)


class TestPackageIntake(unittest.TestCase):
    def zip_bytes(self, files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in files:
                z.writestr(name, data)
        return buf.getvalue()

    def test_json_text_bytes_and_fenced_blocks(self):
        text = json.dumps(good_pkg(), ensure_ascii=False)
        for data in (text, text.encode("utf-8"), "```json\n" + text + "\n```", "\ufeff" + text):
            with self.subTest(str(data)[:12]):
                obj, source, digest = intake.parse_package(data)
                self.assertEqual((obj["id"], source), ("tip_calc", None))
                self.assertEqual(len(digest), 64)

    def test_zip_with_a_separate_source_file(self):
        pkg = good_pkg()
        src = pkg.pop("source")
        obj, source, _ = intake.parse_package(self.zip_bytes([("manifest.json", json.dumps(pkg)), ("ext.py", src)]))
        self.assertEqual((obj["id"], source), ("tip_calc", src))
        self.assertEqual(M.validate_manifest(obj, source)["id"], "tip_calc")

    def test_unsafe_zip_contents_are_refused(self):
        base = json.dumps(good_pkg())
        bad = {
            "traversal": [("manifest.json", base), ("../evil.py", "x")], "nested": [("manifest.json", base), ("dir/ext.py", "x")],
            "absolute": [("manifest.json", base), ("/etc/passwd", "x")], "other_file": [("manifest.json", base), ("run.sh", "x")],
            "no_manifest": [("ext.py", "x")], "duplicate": [("manifest.json", base), ("manifest.json", base)],
            "backslash": [("manifest.json", base), ("a\\b.py", "x")],
        }
        for name, files in bad.items():
            with self.subTest(name):
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    data = self.zip_bytes(files)
                with self.assertRaises(PackageError) as cm:
                    intake.parse_package(data)
                self.assertTrue(cm.exception.code.startswith("E_PACKAGE"))

    def test_zip_bombs_and_oversize_entries_are_refused(self):
        bomb = self.zip_bytes([("manifest.json", b"{" + b" " * 150_000 + b"}")])
        with self.assertRaises(PackageError):
            intake.parse_package(bomb)
        big = self.zip_bytes([("manifest.json", os.urandom(limits.MAX_PACKAGE_BYTES + 10))])
        with self.assertRaises(PackageError):
            intake.parse_package(big)
        with self.assertRaises(PackageError):
            intake.parse_package("x" * (limits.MAX_PACKAGE_BYTES + 1))

    def test_a_symlink_entry_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json", json.dumps(good_pkg()))
            info = zipfile.ZipInfo("ext.py")
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc/passwd")
        with self.assertRaises(PackageError):
            intake.parse_package(buf.getvalue())

    def test_json_pitfalls(self):
        for bad in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}', "[1, 2]", "not json", "", "   ", b"\xff\xfe\x00"):
            with self.subTest(str(bad)[:20]):
                with self.assertRaises(PackageError):
                    intake.parse_package(bad)

    def test_deeply_nested_json_cannot_crash_the_pipeline(self):
        deep = '{"a": ' + "[" * 5000 + "]" * 5000 + "}"
        try:
            obj, _, _ = intake.parse_package(deep)
        except PackageError:
            return                                   # refused at intake: fine
        with self.assertRaises(ManifestError):       # or parsed, and then refused by the manifest rules
            M.validate_manifest(obj)

    def test_expected_hash_is_enforced(self):
        text = json.dumps(good_pkg())
        digest = intake.sha256_hex(text.encode("utf-8"))
        self.assertEqual(intake.parse_package(text, expected_sha256=digest.upper())[2], digest)
        with self.assertRaises(PackageError) as cm:
            intake.parse_package(text, expected_sha256="0" * 64)
        self.assertEqual(cm.exception.code, "E_PACKAGE_HASH")
        with self.assertRaises(PackageError):
            intake.parse_package(text, expected_sha256="abc")

    def test_finding_a_package_inside_a_chat_message(self):
        text = json.dumps(good_pkg(), ensure_ascii=False)
        self.assertEqual(json.loads(intake.find_package_in_text("سلام اینه:\n```json\n" + text + "\n```\nممنون"))["id"], "tip_calc")
        self.assertEqual(json.loads(intake.find_package_in_text("بسته " + text + " تمام"))["id"], "tip_calc")
        self.assertIsNone(intake.find_package_in_text("سلام چطوری؟"))
        self.assertIsNone(intake.find_package_in_text('{"a": "ext.v1" '))
        self.assertIsNone(intake.find_package_in_text(None))

    def test_a_mention_of_the_schema_in_prose_does_not_hide_the_object_after_it(self):
        text = json.dumps(good_pkg(), ensure_ascii=False)
        found = intake.find_package_in_text("این بستهٔ ext.v1 توست، بدون بلاک کد: " + text + " موفق باشی")
        self.assertEqual(json.loads(found)["id"], json.loads(text)["id"])
        twice = intake.find_package_in_text("ext.v1 ext.v1 ext.v1 " + text)
        self.assertEqual(json.loads(twice)["id"], json.loads(text)["id"])

    def test_a_message_full_of_braces_cannot_stall_the_search(self):
        import time
        started = time.monotonic()
        self.assertIsNone(intake.find_package_in_text("{" * 400_000 + " ext.v1"))
        self.assertIsNone(intake.find_package_in_text(("{ ext.v1 " * 50_000)))
        self.assertLess(time.monotonic() - started, 8.0)


if __name__ == "__main__":
    unittest.main()
