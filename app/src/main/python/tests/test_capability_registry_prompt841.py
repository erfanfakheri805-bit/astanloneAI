"""
Prompt 841 - capability registry foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_registry_prompt841 -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_registry as cr
from capabilities.capability_registry import (
    CapabilityRegistry, validate_capability_descriptor as validate,
)


def desc(**over):
    d = {"name": "text_summary", "version": 1, "purpose": "Summarise supplied text.",
         "inputs": ["text"], "outputs": ["summary"], "constraints": ["No network access."],
         "enabled": False}
    d.update(over)
    return d


def codes(result):
    return [e["code"] for e in result["errors"]]


class StrSub(str):
    pass


class IntSub(int):
    pass


class ListSub(list):
    pass


class DictSub(dict):
    pass


class ValidationTests(unittest.TestCase):
    def test_valid_descriptor(self):
        r = validate(desc())
        self.assertTrue(r["valid"])
        self.assertEqual(r["errors"], [])
        self.assertEqual(list(r), ["version", "valid", "error_count", "errors", "truncated"])

    def test_valid_minimal_and_enabled(self):
        self.assertTrue(validate(desc(inputs=[], constraints=[], enabled=True))["valid"])

    def test_not_dict(self):
        for bad in (None, 1, "x", [], (), set(), DictSub(desc())):
            self.assertEqual(codes(validate(bad)), [cr.ERR_NOT_DICT], repr(bad))

    def test_missing_fields(self):
        for field in cr.DESCRIPTOR_FIELDS:
            d = desc()
            del d[field]
            self.assertEqual(codes(validate(d)), [cr.ERR_MISSING_FIELD], field)
        self.assertEqual(len(validate({})["errors"]), len(cr.DESCRIPTOR_FIELDS))

    def test_unexpected_fields_rejected(self):
        for key in ("handler", "tool", "module", "code", "url", "execution_allowed"):
            r = validate(desc(**{key: "x"}))
            self.assertEqual(codes(r), [cr.ERR_UNEXPECTED_FIELD], key)
        d = desc()
        d[5] = 1
        self.assertEqual(codes(validate(d)), [cr.ERR_UNEXPECTED_FIELD])

    def test_bad_names(self):
        for bad in ("", "Text", "text-summary", " text", "text ", "1abc", "a b", "_a",
                    "a" * 65, None, 5, StrSub("ok_name"), "tëxt"):
            self.assertEqual(codes(validate(desc(name=bad))), [cr.ERR_INVALID_NAME], repr(bad))
        self.assertTrue(validate(desc(name="a" * 64))["valid"])

    def test_bad_versions(self):
        for bad in (0, -1, True, False, 1.0, "1", None, IntSub(1), cr.MAX_VERSION + 1):
            self.assertEqual(codes(validate(desc(version=bad))), [cr.ERR_INVALID_VERSION], repr(bad))
        self.assertTrue(validate(desc(version=cr.MAX_VERSION))["valid"])

    def test_bad_purpose(self):
        for bad in ("", " x", "x ", "a\nb", "a\x00b", "x" * 201, None, 3, StrSub("ok")):
            self.assertEqual(codes(validate(desc(purpose=bad))), [cr.ERR_INVALID_PURPOSE], repr(bad))
        self.assertTrue(validate(desc(purpose="x" * 200))["valid"])

    def test_bad_lists(self):
        for field, code in (("inputs", cr.ERR_INVALID_INPUTS), ("outputs", cr.ERR_INVALID_OUTPUTS),
                            ("constraints", cr.ERR_INVALID_CONSTRAINTS)):
            for bad in (None, "x", ("a",), {"a"}, ListSub(["a"])):
                self.assertEqual(codes(validate(desc(**{field: bad}))), [code], (field, bad))

    def test_item_rules(self):
        self.assertEqual(codes(validate(desc(inputs=["Bad"]))), [cr.ERR_INVALID_ITEM])
        self.assertEqual(codes(validate(desc(inputs=[1]))), [cr.ERR_INVALID_ITEM])
        self.assertEqual(codes(validate(desc(inputs=["a", "a"]))), [cr.ERR_DUPLICATE_ITEM])
        self.assertEqual(codes(validate(desc(outputs=["a", "a"]))), [cr.ERR_DUPLICATE_ITEM])
        self.assertEqual(codes(validate(desc(constraints=["x", "x"]))), [cr.ERR_DUPLICATE_ITEM])
        self.assertEqual(codes(validate(desc(constraints=[" x"]))), [cr.ERR_INVALID_ITEM])
        self.assertEqual(codes(validate(desc(constraints=["x" * 121]))), [cr.ERR_INVALID_ITEM])
        self.assertTrue(validate(desc(constraints=["x" * 120]))["valid"])

    def test_outputs_required(self):
        self.assertEqual(codes(validate(desc(outputs=[]))), [cr.ERR_NO_OUTPUTS])

    def test_too_many_items(self):
        many = ["i%d" % n for n in range(cr.MAX_ITEMS + 1)]
        self.assertEqual(codes(validate(desc(inputs=many))), [cr.ERR_TOO_MANY_ITEMS])
        self.assertTrue(validate(desc(inputs=many[:cr.MAX_ITEMS]))["valid"])

    def test_bad_enabled(self):
        for bad in (0, 1, "true", None, [], IntSub(1)):
            self.assertEqual(codes(validate(desc(enabled=bad))), [cr.ERR_INVALID_ENABLED], repr(bad))

    def test_errors_bounded(self):
        r = validate(desc(inputs=[1] * 16, outputs=[1] * 16, constraints=[1] * 16))
        self.assertLessEqual(len(r["errors"]), cr.MAX_ERRORS)
        self.assertTrue(r["truncated"])

    def test_huge_input_bounded(self):
        d = desc(inputs=["a%d" % n for n in range(100000)])
        self.assertEqual(codes(validate(d)), [cr.ERR_TOO_MANY_ITEMS])
        big = {("k%d" % n): n for n in range(100000)}
        r = validate(big)
        self.assertLessEqual(len(r["errors"]), cr.MAX_ERRORS)

    def test_validation_does_not_modify_and_is_deterministic(self):
        d = desc()
        before = copy.deepcopy(d)
        a, b = validate(d), validate(d)
        self.assertEqual(d, before)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_hostile_object_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")
        r = validate(Boom())
        self.assertFalse(r["valid"])
        d = desc()
        d["purpose"] = object()
        self.assertFalse(validate(d)["valid"])


class RegistrationTests(unittest.TestCase):
    def test_register_valid(self):
        reg = CapabilityRegistry()
        r = reg.register(desc())
        self.assertEqual(r, {"version": 1, "status": "registered", "reason": "registered",
                             "name": "text_summary", "errors": [], "executed": False})
        self.assertEqual(list(r), ["version", "status", "reason", "name", "errors", "executed"])
        self.assertEqual(len(reg), 1)
        json.dumps(r)

    def test_malformed_rejected_registry_unchanged(self):
        reg = CapabilityRegistry()
        for bad in (None, {}, [], desc(name="Bad"), desc(version=0), desc(handler="x"),
                    desc(outputs=[]), desc(enabled="yes")):
            r = reg.register(bad)
            self.assertEqual((r["status"], r["reason"]), ("rejected", "malformed"), repr(bad))
            self.assertTrue(r["errors"])
            self.assertFalse(r["executed"])
        self.assertEqual(len(reg), 0)
        self.assertEqual(reg.list_capabilities()["count"], 0)

    def test_malformed_result_name(self):
        reg = CapabilityRegistry()
        self.assertEqual(reg.register(desc(version=0))["name"], "text_summary")
        self.assertIsNone(reg.register(desc(name="Bad", version=0))["name"])
        self.assertIsNone(reg.register("x")["name"])

    def test_duplicate_identical_rejected(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        r = reg.register(desc())
        self.assertEqual((r["status"], r["reason"]), ("rejected", "duplicate"))
        self.assertEqual(len(reg), 1)

    def test_conflicts_rejected(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        for change in ({"version": 2}, {"purpose": "Other."}, {"inputs": []},
                       {"outputs": ["other"]}, {"constraints": []}, {"enabled": True}):
            r = reg.register(desc(**change))
            self.assertEqual((r["status"], r["reason"]), ("rejected", "conflict"), change)
        self.assertEqual(reg.lookup("text_summary")["descriptor"], desc())
        self.assertEqual(len(reg), 1)

    def test_no_case_folding_in_identity(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        self.assertEqual(reg.register(desc(name="text_Summary"))["reason"], "malformed")
        self.assertEqual(reg.register(desc(name="text_summary2"))["status"], "registered")

    def test_no_replacement_or_removal_api(self):
        reg = CapabilityRegistry()
        for attr in ("unregister", "remove", "delete", "update", "replace", "clear", "execute",
                     "run", "call", "load"):
            self.assertFalse(hasattr(reg, attr), attr)

    def test_registry_full(self):
        reg = CapabilityRegistry()
        for n in range(cr.MAX_CAPABILITIES):
            self.assertEqual(reg.register(desc(name="cap_%d" % n))["status"], "registered")
        r = reg.register(desc(name="one_more"))
        self.assertEqual((r["status"], r["reason"]), ("rejected", "registry_full"))
        self.assertEqual(len(reg), cr.MAX_CAPABILITIES)
        # duplicates are still reported as duplicates when full
        self.assertEqual(reg.register(desc(name="cap_0"))["reason"], "duplicate")

    def test_registration_deterministic(self):
        a, b = CapabilityRegistry(), CapabilityRegistry()
        for r in (a, b):
            self.assertEqual(r.register(desc())["status"], "registered")
        self.assertEqual(a.register(desc(version=2)), b.register(desc(version=2)))

    def test_input_not_modified_and_not_aliased(self):
        reg = CapabilityRegistry()
        d = desc()
        before = copy.deepcopy(d)
        reg.register(d)
        self.assertEqual(d, before)
        d["inputs"].append("late")
        d["purpose"] = "changed"
        d["enabled"] = True
        self.assertEqual(reg.lookup("text_summary")["descriptor"], desc())

    def test_hostile_descriptor_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")
        reg = CapabilityRegistry()
        self.assertEqual(reg.register(Boom())["status"], "rejected")
        self.assertEqual(len(reg), 0)

    def test_stored_descriptor_has_fixed_key_order(self):
        reg = CapabilityRegistry()
        d = dict(reversed(list(desc().items())))
        reg.register(d)
        self.assertEqual(list(reg.lookup("text_summary")["descriptor"]), list(cr.DESCRIPTOR_FIELDS))


class LookupTests(unittest.TestCase):
    def setUp(self):
        self.reg = CapabilityRegistry()
        self.reg.register(desc())
        self.reg.register(desc(name="file_reader", purpose="Read a named file."))

    def test_found(self):
        r = self.reg.lookup("file_reader")
        self.assertEqual(r["found"], True)
        self.assertEqual(r["reason"], "found")
        self.assertEqual(r["descriptor"]["purpose"], "Read a named file.")
        self.assertEqual(list(r), ["version", "found", "reason", "descriptor", "executed"])
        self.assertFalse(r["executed"])

    def test_not_found(self):
        for name in ("missing", "text", "text_summar", "text_summary_"):
            r = self.reg.lookup(name)
            self.assertEqual((r["found"], r["reason"], r["descriptor"]), (False, "not_found", None))

    def test_exact_only(self):
        for name in ("TEXT_SUMMARY", " text_summary", "text_summary ", "text_summary\n", "text*"):
            r = self.reg.lookup(name)
            self.assertFalse(r["found"], repr(name))
            self.assertIsNone(r["descriptor"])

    def test_invalid_names(self):
        for bad in (None, 1, b"text_summary", ["text_summary"], StrSub("text_summary"), "", "a" * 65):
            r = self.reg.lookup(bad)
            self.assertEqual((r["found"], r["reason"]), (False, "invalid_name"), repr(bad))

    def test_empty_registry(self):
        r = CapabilityRegistry().lookup("text_summary")
        self.assertEqual((r["found"], r["reason"]), (False, "not_found"))

    def test_lookup_deterministic(self):
        self.assertEqual(self.reg.lookup("text_summary"), self.reg.lookup("text_summary"))

    def test_json_safe(self):
        json.dumps(self.reg.lookup("text_summary"))
        json.dumps(self.reg.lookup("nope"))


class ListingTests(unittest.TestCase):
    NAMES = ["zeta", "alpha", "mid_one", "beta", "mid", "a1"]

    def test_empty(self):
        r = CapabilityRegistry().list_capabilities()
        self.assertEqual(r, {"version": 1, "count": 0, "capabilities": [], "executed": False})
        self.assertEqual(list(r), ["version", "count", "capabilities", "executed"])

    def test_sorted_regardless_of_registration_order(self):
        for order in (self.NAMES, list(reversed(self.NAMES)), sorted(self.NAMES)):
            reg = CapabilityRegistry()
            for n in order:
                reg.register(desc(name=n))
            listing = reg.list_capabilities()
            self.assertEqual([c["name"] for c in listing["capabilities"]], sorted(self.NAMES))
            self.assertEqual(listing["count"], len(self.NAMES))

    def test_rejected_not_listed(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        reg.register(desc(version=9))
        reg.register(desc(name="Bad"))
        self.assertEqual(reg.list_capabilities()["count"], 1)

    def test_json_safe_and_deterministic(self):
        reg = CapabilityRegistry()
        for n in self.NAMES:
            reg.register(desc(name=n))
        a, b = reg.list_capabilities(), reg.list_capabilities()
        self.assertEqual(a, b)
        self.assertEqual(json.loads(json.dumps(a)), a)


class IsolationTests(unittest.TestCase):
    def test_lookup_result_mutation_does_not_leak(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        r = reg.lookup("text_summary")
        r["descriptor"]["inputs"].append("x")
        r["descriptor"]["name"] = "hacked"
        r["found"] = False
        self.assertEqual(reg.lookup("text_summary")["descriptor"], desc())
        self.assertFalse(reg.lookup("hacked")["found"])

    def test_listing_mutation_does_not_leak(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        listing = reg.list_capabilities()
        listing["capabilities"][0]["outputs"].append("x")
        listing["capabilities"].clear()
        self.assertEqual(reg.list_capabilities()["capabilities"], [desc()])

    def test_fresh_objects_each_call(self):
        reg = CapabilityRegistry()
        reg.register(desc())
        a, b = reg.lookup("text_summary"), reg.lookup("text_summary")
        self.assertIsNot(a, b)
        self.assertIsNot(a["descriptor"], b["descriptor"])
        self.assertIsNot(a["descriptor"]["inputs"], b["descriptor"]["inputs"])
        la, lb = reg.list_capabilities(), reg.list_capabilities()
        self.assertIsNot(la["capabilities"], lb["capabilities"])
        self.assertIsNot(la["capabilities"][0], lb["capabilities"][0])

    def test_registration_result_mutation_does_not_leak(self):
        reg = CapabilityRegistry()
        r = reg.register(desc(version=0))
        r["errors"].clear()
        self.assertTrue(reg.register(desc(version=0))["errors"])

    def test_registries_are_independent(self):
        a, b = CapabilityRegistry(), CapabilityRegistry()
        a.register(desc())
        self.assertEqual(len(b), 0)
        self.assertFalse(b.lookup("text_summary")["found"])
        self.assertEqual(b.register(desc())["status"], "registered")

    def test_no_module_level_registry(self):
        for name in dir(cr):
            self.assertNotIsInstance(getattr(cr, name), CapabilityRegistry, name)


class BoundaryTests(unittest.TestCase):
    def test_no_execution_or_loading_machinery(self):
        import inspect
        src = inspect.getsource(cr)
        body = src.split('"""', 2)[2]
        for banned in ("import importlib", "__import__", "exec(", "eval(", "subprocess", "socket",
                       "urllib", "requests", "open(", "os.", "sys.", "from core", "from memory",
                       "from ael", "import core", "import memory", "import ael"):
            self.assertNotIn(banned, body, banned)

    def test_only_stdlib_imports(self):
        import inspect
        imports = [l.strip() for l in inspect.getsource(cr).splitlines()
                   if l.startswith(("import ", "from "))]
        self.assertEqual(imports, ["import copy", "import itertools", "import re"])

    def test_executed_always_false(self):
        reg = CapabilityRegistry()
        for r in (reg.register(desc(enabled=True)), reg.register(desc(enabled=True)),
                  reg.register(None), reg.lookup("text_summary"), reg.lookup("x"),
                  reg.list_capabilities()):
            self.assertFalse(r["executed"])

    def test_enabled_is_only_a_flag(self):
        reg = CapabilityRegistry()
        reg.register(desc(enabled=True))
        self.assertIs(reg.lookup("text_summary")["descriptor"]["enabled"], True)

    def test_not_connected_to_core_memory_or_ael(self):
        loaded_before = set(sys.modules)
        import importlib
        importlib.reload(cr)
        newly = set(sys.modules) - loaded_before
        for name in newly:
            self.assertFalse(name.split(".")[0] in ("core", "memory", "ael"), name)


class BackwardCompatibilityTests(unittest.TestCase):
    def test_existing_capability_system_unchanged(self):
        from capabilities import capability_system as cs
        self.assertTrue(hasattr(cs, "CapabilitySystem"))
        self.assertTrue(hasattr(cs, "PLANNED_CAPABILITIES"))
        self.assertEqual(len(cs.PLANNED_CAPABILITIES), 8)

    def test_package_init_unchanged(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "capabilities", "__init__.py")
        with open(path, "rb") as fh:
            self.assertEqual(fh.read().strip(), b"")

    def test_reasoning_apis_preserved(self):
        from reasoning.capability_contract import (
            build_capability_contract, validate_capability_contract)
        from reasoning.capability_integration import (
            integrate_capability_contract, classify_capability_result)
        from reasoning.capability_boundary import evaluate_reasoning_capability_boundary
        from reasoning.reasoning_decision import decide_reasoning
        from understanding.nlu_pipeline import default_pipeline
        for fn in (build_capability_contract, validate_capability_contract,
                   integrate_capability_contract, classify_capability_result,
                   evaluate_reasoning_capability_boundary, decide_reasoning, default_pipeline):
            self.assertTrue(callable(fn))

    def test_boundary_result_unchanged_by_registry(self):
        from reasoning.capability_boundary import evaluate_reasoning_capability_boundary as b
        r = b(None)
        self.assertEqual(list(r), ["version", "decision_state", "capability_classification",
                                   "contract_valid", "execution_allowed", "next_stage",
                                   "reason", "executed"])
        self.assertFalse(r["execution_allowed"])
        self.assertFalse(r["executed"])

    def test_core_does_not_reference_registry(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for rel in ("core/core.py",):
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                self.assertNotIn("capability_registry", fh.read(), rel)
        for folder in ("memory", "ael"):
            for dirpath, _dirs, files in os.walk(os.path.join(root, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                            self.assertNotIn("capability_registry", fh.read(), f)


if __name__ == "__main__":
    unittest.main()
