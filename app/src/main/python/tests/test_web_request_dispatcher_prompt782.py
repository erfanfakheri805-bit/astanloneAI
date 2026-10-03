"""Prompt 782 - Section 9 web request dispatcher (`web.web_request_dispatcher`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
import weakref
from unittest import mock

from web import web_request_dispatcher as wd
from web import web_request_executor as we
from web import web_request_output as wo
from web.web_request import create_web_request
from web.web_request_dispatcher import dispatch_web_request
from web.web_request_executor import WebRequestExecutionResult, execute_web_request_plan
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_plan import WebRequestPlan, create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_dispatcher_prompt782.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_dispatcher.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "WEB_REQUEST_DISPATCHER_INVALID_PLAN"
NOT_IMPL = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"
FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")
DEFAULT = {"request_id": "req_1", "url": "https://example.org/x", "method": "GET", "resource_type": "page", "timeout_ms": 5000}


def make_plan(**over):
    data = dict(DEFAULT)
    data.update(over)
    req = create_web_request(data)
    assert req.ok, req.failures
    res = create_web_resource({"resource_id": data["resource_type"], "url": "https://example.org/r", "title": "T", "resource_type": "page"})
    assert res.ok, res.failures
    reg = create_web_resource_registry([res.resource])
    assert reg.ok, reg.failures
    plan = create_web_request_plan(validate_web_request(req.request, reg.registry))
    assert plan.ok, plan.codes()
    return plan.plan


class Lookalike:
    request_id, url, method, resource_type, timeout_ms = "req_1", "https://example.org/x", "GET", "page", 5000

    def to_dict(self):
        return dict(DEFAULT)


class TestValidDispatch(unittest.TestCase):
    def test_1_valid_plan_dispatches_to_a_web_request_output(self):
        out = dispatch_web_request(make_plan())
        self.assertIs(type(out), WebRequestOutput)

    def test_2_result_is_the_not_implemented_output(self):
        out = dispatch_web_request(make_plan())
        self.assertEqual(out.status, "NOT_IMPLEMENTED")
        self.assertEqual(out.code, NOT_IMPL)
        self.assertEqual(out.metadata, DEFAULT)

    def test_3_status_code_and_metadata_are_preserved_exactly(self):
        plan = make_plan(request_id="r-9", url="https://svc.example/v1?a=1", method="POST", resource_type="api", timeout_ms=250)
        out = dispatch_web_request(plan)
        self.assertEqual(out.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": plan.to_dict()})
        self.assertEqual(list(out.metadata), list(FIELDS))
        meta = out.metadata
        for field in FIELDS:
            self.assertIs(meta[field], getattr(plan, field), field)
        self.assertIs(type(meta["timeout_ms"]), int)

    def test_4_output_equals_the_manual_executor_then_factory_chain(self):
        plan = make_plan()
        self.assertEqual(dispatch_web_request(plan), create_web_request_output(execute_web_request_plan(plan)))
        self.assertEqual(hash(dispatch_web_request(plan)), hash(create_web_request_output(execute_web_request_plan(plan))))

    def test_5_unusual_but_valid_values_pass_through_unchanged(self):
        plan = make_plan(request_id="  r 1  ", url="HTTPS://Example.ORG/X ", method="get", timeout_ms=1)
        out = dispatch_web_request(plan)
        self.assertEqual(out.metadata, plan.to_dict())
        self.assertEqual(out.code, NOT_IMPL)


class TestInvalidInput(unittest.TestCase):
    INPUTS = (None, {}, DEFAULT, "plan", 1, 1.5, True, [], (), object(), Lookalike(), WebRequestPlan, type(None),
              b"x", set(), lambda: None)

    def test_6_invalid_input_returns_the_deterministic_rejected_output(self):
        for item in self.INPUTS:
            out = dispatch_web_request(item)
            self.assertIs(type(out), WebRequestOutput, item)
            self.assertEqual(out.status, "REJECTED")
            self.assertEqual(out.code, INVALID)
            self.assertIsNone(out.metadata)
            self.assertEqual(out.to_dict(), {"status": "REJECTED", "code": INVALID, "metadata": None})

    def test_7_all_invalid_inputs_give_equal_outputs(self):
        outs = [dispatch_web_request(i) for i in self.INPUTS]
        self.assertEqual(len(set(outs)), 1)

    def test_8_execution_results_outputs_and_result_objects_are_not_plans(self):
        plan = make_plan()
        for item in (execute_web_request_plan(plan), dispatch_web_request(plan), create_web_request_output(execute_web_request_plan(plan))):
            self.assertEqual(dispatch_web_request(item).code, INVALID)

    def test_9_plan_subclasses_cannot_exist(self):
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestPlan,), {})

    def test_10_invalid_input_does_not_call_executor_or_factory(self):
        boom = mock.Mock(side_effect=AssertionError("must not be called"))
        with mock.patch.object(wd, "execute_web_request_plan", boom), mock.patch.object(wd, "create_web_request_output", boom):
            for item in self.INPUTS:
                self.assertEqual(dispatch_web_request(item).code, INVALID)
        boom.assert_not_called()

    def test_11_invalid_input_is_never_read(self):
        class Spy:
            def __getattribute__(self, name):
                raise AssertionError("input must not be read: " + name)
        self.assertEqual(dispatch_web_request(Spy()).code, INVALID)

    def test_12_invalid_output_differs_from_the_factory_invalid_output(self):
        factory_invalid = create_web_request_output(None)
        self.assertEqual(factory_invalid.code, "WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT")
        self.assertNotEqual(dispatch_web_request(None), factory_invalid)


class TestChainInvocation(unittest.TestCase):
    def test_13_valid_plan_invokes_the_executor_exactly_once_with_the_same_plan(self):
        plan = make_plan()
        spy = mock.Mock(wraps=execute_web_request_plan)
        with mock.patch.object(wd, "execute_web_request_plan", spy):
            out = dispatch_web_request(plan)
        spy.assert_called_once()
        self.assertEqual(len(spy.call_args.args), 1)
        self.assertIs(spy.call_args.args[0], plan)
        self.assertEqual(spy.call_args.kwargs, {})
        self.assertEqual(out.code, NOT_IMPL)

    def test_14_output_factory_receives_the_executor_result_exactly_once(self):
        plan = make_plan()
        sentinel = execute_web_request_plan(plan)
        factory = mock.Mock(wraps=create_web_request_output)
        with mock.patch.object(wd, "execute_web_request_plan", mock.Mock(return_value=sentinel)), \
                mock.patch.object(wd, "create_web_request_output", factory):
            out = dispatch_web_request(plan)
        factory.assert_called_once()
        self.assertIs(factory.call_args.args[0], sentinel)
        self.assertEqual(factory.call_args.kwargs, {})
        self.assertIs(type(out), WebRequestOutput)

    def test_15_the_factory_output_is_returned_unchanged(self):
        plan = make_plan()
        made = create_web_request_output(execute_web_request_plan(plan))
        with mock.patch.object(wd, "create_web_request_output", mock.Mock(return_value=made)):
            self.assertIs(dispatch_web_request(plan), made)

    def test_16_executor_not_implemented_result_is_what_gets_converted(self):
        plan = make_plan()
        seen = []
        real = create_web_request_output

        def capture(result):
            seen.append(result)
            return real(result)
        with mock.patch.object(wd, "create_web_request_output", capture):
            dispatch_web_request(plan)
        self.assertEqual(len(seen), 1)
        self.assertIs(type(seen[0]), WebRequestExecutionResult)
        self.assertEqual((seen[0].status, seen[0].code, seen[0].executed, seen[0].ok), ("NOT_IMPLEMENTED", NOT_IMPL, False, False))

    def test_17_executor_status_code_and_metadata_come_from_the_executor_not_the_dispatcher(self):
        plan = make_plan()
        other = make_plan(request_id="other", method="PUT", timeout_ms=7)
        with mock.patch.object(wd, "execute_web_request_plan", mock.Mock(return_value=execute_web_request_plan(other))):
            out = dispatch_web_request(plan)
        self.assertEqual(out.metadata, other.to_dict())

    def test_18_a_rejected_executor_result_is_converted_not_recoded(self):
        rejected = execute_web_request_plan(None)
        with mock.patch.object(wd, "execute_web_request_plan", mock.Mock(return_value=rejected)):
            out = dispatch_web_request(make_plan())
        self.assertEqual(out.to_dict(), {"status": "REJECTED", "code": "WEB_REQUEST_EXECUTOR_INVALID_PLAN", "metadata": None})

    def test_19_dispatcher_uses_the_public_executor_and_factory_objects(self):
        self.assertIs(wd.execute_web_request_plan, we.execute_web_request_plan)
        self.assertIs(wd.create_web_request_output, wo.create_web_request_output)
        self.assertIs(wd.WebRequestOutput, wo.WebRequestOutput)
        self.assertIs(wd.WebRequestPlan, WebRequestPlan)


class TestOutputCreation(unittest.TestCase):
    def test_20_valid_output_is_created_by_the_existing_factory_not_directly(self):
        spy = mock.Mock(wraps=wd.create_web_request_output)
        with mock.patch.object(wd, "create_web_request_output", spy), \
                mock.patch.object(wd, "WebRequestOutput", mock.Mock(side_effect=AssertionError("direct construction on the valid path"))):
            out = dispatch_web_request(make_plan())
        spy.assert_called_once()
        self.assertEqual(out.code, NOT_IMPL)

    def test_21_rejected_output_is_a_real_web_request_output_with_the_module_token(self):
        out = dispatch_web_request(None)
        self.assertIs(type(out), WebRequestOutput)
        self.assertEqual(sorted(type(out).__slots__), ["_code", "_items", "_status"])
        self.assertIsNone(out._items)
        with self.assertRaises(TypeError):
            WebRequestOutput(object(), "REJECTED", INVALID, None)

    def test_22_outputs_contain_exactly_the_three_output_fields(self):
        for out in (dispatch_web_request(make_plan()), dispatch_web_request(None)):
            self.assertEqual(list(out.to_dict()), ["status", "code", "metadata"])


class TestNoRetention(unittest.TestCase):
    @staticmethod
    def _live(cls):
        gc.collect()
        return [o for o in gc.get_objects() if type(o) is cls]

    def test_23_plan_is_not_retained_by_the_output(self):
        plan = make_plan()
        self.assertTrue(any(o is plan for o in self._live(WebRequestPlan)))   # sanity: the scan can see plans
        out = dispatch_web_request(plan)
        for holder in (out, vars(wd)):
            self.assertFalse(any(r is plan for r in gc.get_referents(holder)))
        self.assertFalse(any(r is plan for r in gc.get_referrers(plan) if r is out or r is vars(wd)))
        del plan
        self.assertEqual(self._live(WebRequestPlan), [])
        self.assertEqual(out.metadata, DEFAULT)

    def test_24_execution_result_is_not_retained(self):
        held = execute_web_request_plan(make_plan())
        self.assertEqual(len(self._live(WebRequestExecutionResult)), 1)       # sanity: the scan can see results
        del held
        self.assertEqual(self._live(WebRequestExecutionResult), [])
        out = dispatch_web_request(make_plan())
        self.assertEqual(self._live(WebRequestExecutionResult), [])
        self.assertEqual(out.code, NOT_IMPL)
        self.assertEqual(self._live(WebRequestPlan), [])

    def test_25_output_holds_no_reference_to_plan_or_result_objects(self):
        out = dispatch_web_request(make_plan())
        for item in (out._status, out._code, out._items):
            self.assertNotIsInstance(item, (WebRequestPlan, WebRequestExecutionResult))
        self.assertIsInstance(out._items, tuple)
        for key, value in out._items:
            self.assertIs(type(key), str)
            self.assertIn(type(value), (str, int))

    def test_26_dispatcher_has_no_module_level_state_that_could_hold_objects(self):
        before = {k: v for k, v in vars(wd).items()}
        plan = make_plan()
        for item in (plan, None, 1):
            dispatch_web_request(item)
        after = vars(wd)
        self.assertEqual(set(after), set(before))
        for name, value in after.items():
            self.assertIs(value, before[name], name)
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, WebRequestPlan, WebRequestExecutionResult, WebRequestOutput), name)

    def test_27_plan_is_not_changed_by_dispatch(self):
        plan = make_plan()
        before = (plan.to_dict(), plan, hash(plan))
        dispatch_web_request(plan)
        self.assertEqual((plan.to_dict(), plan, hash(plan)), before)


class TestDeterminismAndImmutability(unittest.TestCase):
    def test_28_repeated_calls_are_deterministic(self):
        plan = make_plan()
        outs = [dispatch_web_request(plan) for _ in range(5)]
        for o in outs[1:]:
            self.assertEqual(o, outs[0])
            self.assertEqual(hash(o), hash(outs[0]))
            self.assertEqual(o.to_dict(), outs[0].to_dict())
        self.assertEqual(len({dispatch_web_request(None) for _ in range(3)}), 1)
        self.assertEqual(dispatch_web_request(make_plan()), dispatch_web_request(make_plan()))

    def test_29_different_plans_give_different_outputs(self):
        self.assertNotEqual(dispatch_web_request(make_plan()), dispatch_web_request(make_plan(request_id="other")))
        self.assertNotEqual(dispatch_web_request(make_plan()), dispatch_web_request(None))

    def test_30_returned_output_is_immutable(self):
        for out in (dispatch_web_request(make_plan()), dispatch_web_request(None)):
            for attr in ("status", "code", "metadata", "_status", "_code", "_items", "extra"):
                with self.assertRaises(AttributeError, msg=attr):
                    setattr(out, attr, "x")
            for attr in ("status", "_code"):
                with self.assertRaises(AttributeError, msg=attr):
                    delattr(out, attr)
            with self.assertRaises(AttributeError):
                out.__dict__

    def test_31_metadata_and_to_dict_are_fresh_copies(self):
        out = dispatch_web_request(make_plan())
        meta = out.metadata
        meta["url"] = "changed"
        meta["extra"] = 1
        d = out.to_dict()
        d["metadata"]["method"] = "DELETE"
        d["status"] = "OK"
        self.assertEqual(out.metadata, DEFAULT)
        self.assertEqual(out.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": DEFAULT})
        self.assertIsNot(out.metadata, out.metadata)

    def test_32_copy_deepcopy_and_pickle(self):
        for out in (dispatch_web_request(make_plan()), dispatch_web_request(None)):
            self.assertIs(copy.copy(out), out)
            self.assertIs(copy.deepcopy(out), out)
            with self.assertRaises(TypeError):
                pickle.dumps(out)

    def test_33_cannot_subclass_output_type(self):
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestOutput,), {})


class TestNoSideEffects(unittest.TestCase):
    def test_34_no_side_effects_filesystem_environment_or_modules(self):
        plan = make_plan()
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (plan, None, 1, Lookalike()):
                dispatch_web_request(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_35_no_network_filesystem_subprocess_or_database_access(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        plan = make_plan()
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(dispatch_web_request(plan).code, NOT_IMPL)
            self.assertEqual(dispatch_web_request(None).code, INVALID)

    def test_36_no_network_module_is_loaded_by_the_dispatcher(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl", "sqlite3", "subprocess", "os", "sys", "shutil"):
            self.assertNotIn(name, vars(wd))


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_37_module_imports_only_the_existing_public_web_request_modules(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(sorted(imports), sorted([
            ("web_request_executor", 1, ["execute_web_request_plan"]),
            ("web_request_output", 1, ["_CREATE_TOKEN"]),
            ("web_request_output", 1, ["WebRequestOutput", "create_web_request_output"]),
            ("web_request_plan", 1, ["WebRequestPlan"])]))

    def test_38_module_is_pure_and_does_not_duplicate_chain_logic(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "isinstance"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "anthropic", "openai", "multimedia", "game_creation", "core", "agent", "planning", "WebRequestExecutionResult",
                     "WebRequestValidationResult", "WebResourceRegistry", "validate_web_request", "create_web_request_plan", "to_dict", "metadata",
                     "request_id", "url", "method", "resource_type", "timeout_ms"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ImportFrom))
        self.assertEqual([n.name for n in self._tree().body if isinstance(n, ast.FunctionDef)], ["dispatch_web_request"])

    def test_39_earlier_web_modules_are_unaware_of_the_dispatcher(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py",
                     "web_request_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_metadata_executor.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_dispatcher", "dispatch_web_request"):
                self.assertNotIn(token, text, (name, token))

    def test_40_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_dispatcher", "dispatch_web_request")
        skip = {"web", "tests", "__pycache__", "data"}
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in skip) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in tokens:
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_41_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py", "web_request_metadata_executor.py",
                          "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py",
                          "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_42_end_to_end_through_public_apis_only(self):
        plan = make_plan(request_id="e2e", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250)
        out = dispatch_web_request(plan)
        self.assertEqual(out, create_web_request_output(execute_web_request_plan(plan)))
        self.assertEqual(out.metadata, plan.to_dict())
        self.assertEqual((out.status, out.code), ("NOT_IMPLEMENTED", NOT_IMPL))

    def test_43_documentation_exists_and_names_the_public_api(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for token in ("Prompt 782", "dispatch_web_request", INVALID, "WebRequestOutput", "execute_web_request_plan", "create_web_request_output", "NOT_IMPLEMENTED"):
            self.assertIn(token, text, token)


if __name__ == "__main__":
    unittest.main()
