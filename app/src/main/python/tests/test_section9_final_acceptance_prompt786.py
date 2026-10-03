"""Prompt 786 - Section 9 (Web, Automation & Service Connectivity) final acceptance.

Acceptance only: no production module is added or changed by this prompt. The suite drives the PUBLIC APIs of the complete chain

    WebResource -> WebResourceRegistry -> WebRequest -> WebRequestValidator -> WebRequestPlan -> WebRequestExecutor -> WebRequestOutput
    -> WebRequestOutputValidator -> WebRequestMetadataExecutor -> WebRequestDispatcher -> WebRequestPipeline -> WebRequestBatch -> WebRequestBatchSummary

Real network transport is intentionally NOT implemented (the executor reports NOT_IMPLEMENTED); nothing here claims otherwise.
Classes named `TestFrozen*` / `TestPackaging*` are tree pins; every other class is behavioral (the mutation harness relies on that split).
"""
import ast
import contextlib
import copy
import glob
import hashlib
import os
import pickle
import subprocess
import sys
import unittest
from unittest import mock

from web import web_request as wreq
from web import web_request_batch as wb
from web import web_request_batch_summary as ws
from web import web_request_dispatcher as wdisp
from web import web_request_executor as wex
from web import web_request_metadata_executor as wmeta
from web import web_request_output as wo
from web import web_request_output_validator as wov
from web import web_request_pipeline as wp
from web import web_request_plan as wplan
from web import web_request_validator as wval
from web import web_resource as wres
from web import web_resource_registry as wreg
from web.web_request import WebRequest, create_web_request
from web.web_request_batch import WebRequestBatchResult, run_web_request_batch
from web.web_request_batch_summary import WebRequestBatchSummary, create_web_request_batch_summary
from web.web_request_dispatcher import dispatch_web_request
from web.web_request_executor import WebRequestExecutionResult, execute_web_request_plan
from web.web_request_metadata_executor import WebRequestMetadataExecutionResult, execute_web_request_metadata
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_output_validator import WebRequestOutputValidationResult, validate_web_request_output
from web.web_request_pipeline import run_web_request_pipeline
from web.web_request_plan import WebRequestPlan, WebRequestPlanResult, create_web_request_plan
from web.web_request_validator import WebRequestValidationResult, validate_web_request
from web.web_resource import WebResource, create_web_resource
from web.web_resource_registry import WebResourceRegistry, create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_final_acceptance_prompt786.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
NOT_IMPL = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"

# Section 9 production tree as delivered by Prompt 785 (frozen for this acceptance).
FROZEN_WEB_SHA256 = {
    "__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "web_request.py": "32e25f6c0eaec92b56f1b987879044b9e0db5700c30bc7cb05632cfe5096cd54",
    "web_request_batch.py": "b6628d8a9301c0b8cbebbfde8bc150a476f681007efb4aadfb66e2f112e79a7b",
    "web_request_batch_summary.py": "89f0adbba65f93849c94fc07bc6180db92d9696e6a9acee9c7707cf78f6bcc98",
    "web_request_dispatcher.py": "1f05b04ae7510afbee234ea32be54118d4e0936d2108f436493d1486a337e9cf",
    "web_request_executor.py": "ad35d1b9566b77770f4ba85dbd76ab1fdcb73776ecab3b9ac40a65a3d72c0ecf",
    "web_request_metadata_executor.py": "5d6d8a8602d5ccf4ac1da7e242ff3c546f8e6b95df3b6bb68411b9f73acff7b2",
    "web_request_output.py": "b72ccfbe798349d314506433e23f2ea29dea287a09c117515d0a04181445026c",
    "web_request_output_validator.py": "fb72c7593e78a8cdba48f544f91249c0d78a4639c4978b94c6dd2fbc261b9a92",
    "web_request_pipeline.py": "00d755833f8eec374b8686ac55b8d6dad76e2305f43fdcd916fa5b3263e0f5c2",
    "web_request_plan.py": "ca0cdcb907ada87c267982f568dc6bf5aebab9ec09c65dcd27ae3ae3cd4e7a2b",
    "web_request_validator.py": "1a312d38b3ee400f1727457aed52caaa706bc57b84ce978792c2e17781e04a95",
    "web_resource.py": "9f8c0b21624f3e89c7546057d6f296ce781945377d2506f6375a724025cacd81",
    "web_resource_registry.py": "5c1606aa61c0cf01a5db4395558664f1ebc5a393f54c8f2c4385177da58a99dd",
}
FROZEN_NON_WEB_PRODUCTION_DIGEST = "0d238769bc3d44add79eff06b3bc24d3a07478eaccf1f6c3a7bcd076b88c5636"
FROZEN_NON_WEB_PRODUCTION_COUNT = 379
WEB_MODULES = tuple(n[:-3] for n in sorted(FROZEN_WEB_SHA256) if n != "__init__.py")
SECTION9_DOCS = ("section9_final_acceptance_prompt786.md", "section9_web_request_batch_prompt784.md", "section9_web_request_batch_summary_prompt785.md",
                 "section9_web_request_dispatcher_prompt782.md", "section9_web_request_executor_prompt778.md",
                 "section9_web_request_metadata_executor_prompt781.md", "section9_web_request_output_prompt779.md",
                 "section9_web_request_output_validator_prompt780.md", "section9_web_request_pipeline_prompt783.md",
                 "section9_web_request_plan_prompt777.md", "section9_web_request_prompt775.md", "section9_web_request_validator_prompt776.md",
                 "section9_web_resource_prompt773.md", "section9_web_resource_registry_prompt774.md")

DEFAULT = {"request_id": "req_1", "url": "https://example.org/x", "method": "GET", "resource_type": "page", "timeout_ms": 5000}


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def build_registry(types=("page",)):
    resources = []
    for t in types:
        res = create_web_resource({"resource_id": t, "url": "https://example.org/r/" + t, "title": "T " + t, "resource_type": t})
        assert res.ok, res.failures
        resources.append(res.resource)
    reg = create_web_resource_registry(resources)
    assert reg.ok, reg.failures
    return reg.registry


def build_chain(registry=None, **over):
    """Run the real chain from plain data up to the plan; return every intermediate object."""
    data = dict(DEFAULT)
    data.update(over)
    registry = registry if registry is not None else build_registry((data["resource_type"],))
    req = create_web_request(data)
    assert req.ok, req.failures
    validation = validate_web_request(req.request, registry)
    assert validation.ok, validation.codes()
    plan = create_web_request_plan(validation)
    assert plan.ok, plan.codes()
    return {"data": data, "registry": registry, "request": req.request, "validation": validation, "plan": plan.plan}


def make_plan(**over):
    return build_chain(**over)["plan"]


def make_output(status, code, items=None):
    return WebRequestOutput(wo._CREATE_TOKEN, status, code, items)


JUNK = (None, 0, 1, -1, 1.5, float("nan"), True, False, "", "x", b"", b"x", [], [1], (), (1,), {}, {"a": 1}, set(), frozenset(), object(), object,
        len, lambda: None, Exception("e"), ...)


class _Boom(Exception):
    pass


def _boom(*_a, **_k):
    raise _Boom("forbidden call")


@contextlib.contextmanager
def forbid_io():
    import http.client
    import shutil
    import socket
    import sqlite3
    import urllib.request
    import builtins
    patches = [mock.patch.object(socket, "socket", _boom), mock.patch.object(socket, "create_connection", _boom),
               mock.patch.object(socket, "getaddrinfo", _boom), mock.patch.object(urllib.request, "urlopen", _boom),
               mock.patch.object(http.client.HTTPConnection, "connect", _boom), mock.patch.object(subprocess, "Popen", _boom),
               mock.patch.object(subprocess, "run", _boom), mock.patch.object(os, "system", _boom), mock.patch.object(sqlite3, "connect", _boom),
               mock.patch.object(builtins, "open", _boom), mock.patch.object(os, "listdir", _boom), mock.patch.object(os, "scandir", _boom),
               mock.patch.object(os, "remove", _boom), mock.patch.object(shutil, "copyfile", _boom)]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


class TestChainComposition(unittest.TestCase):
    def test_01_every_layer_produces_its_exact_public_type(self):
        c = build_chain()
        self.assertIs(type(c["registry"]), WebResourceRegistry)
        self.assertIs(type(c["request"]), WebRequest)
        self.assertIs(type(c["validation"]), WebRequestValidationResult)
        self.assertIs(type(c["plan"]), WebRequestPlan)
        ex = execute_web_request_plan(c["plan"])
        self.assertIs(type(ex), WebRequestExecutionResult)
        out = create_web_request_output(ex)
        self.assertIs(type(out), WebRequestOutput)
        chk = validate_web_request_output(out)
        self.assertIs(type(chk), WebRequestOutputValidationResult)
        meta = execute_web_request_metadata(out)
        self.assertIs(type(meta), WebRequestMetadataExecutionResult)
        disp = dispatch_web_request(c["plan"])
        pipe = run_web_request_pipeline(c["plan"])
        self.assertIs(type(disp), WebRequestOutput)
        self.assertIs(type(pipe), WebRequestOutput)
        batch = run_web_request_batch((c["plan"],))
        self.assertIs(type(batch), WebRequestBatchResult)
        self.assertIs(type(create_web_request_batch_summary(batch)), WebRequestBatchSummary)

    def test_02_values_propagate_unchanged_from_resource_to_plan(self):
        c = build_chain(request_id="r-9", url="https://svc.example/v2?q=1", method="POST", resource_type="api", timeout_ms=1234)
        self.assertEqual(c["registry"].resource_ids, ("api",))
        self.assertIs(c["validation"].request, c["request"])
        self.assertIs(c["validation"].registry, c["registry"])
        for field in ("request_id", "url", "method", "resource_type", "timeout_ms"):
            self.assertEqual(getattr(c["plan"], field), c["data"][field], field)
            self.assertEqual(getattr(c["request"], field), c["data"][field], field)

    def test_03_executor_output_validator_and_metadata_executor_carry_the_five_plan_values(self):
        plan = make_plan(request_id="m1", url="https://a.example/p", method="PUT", resource_type="doc", timeout_ms=77)
        expected = {"request_id": "m1", "url": "https://a.example/p", "method": "PUT", "resource_type": "doc", "timeout_ms": 77}
        ex = execute_web_request_plan(plan)
        self.assertEqual((ex.status, ex.code, ex.ok, ex.executed), ("NOT_IMPLEMENTED", NOT_IMPL, False, False))
        self.assertEqual(ex.metadata, expected)
        out = create_web_request_output(ex)
        self.assertEqual(out.to_dict(), {"status": "NOT_IMPLEMENTED", "code": NOT_IMPL, "metadata": expected})
        chk = validate_web_request_output(out)
        self.assertTrue(chk.ok)
        self.assertIs(chk.output, out)
        meta = execute_web_request_metadata(out)
        self.assertEqual(meta.to_dict(), out.to_dict())
        self.assertEqual(list(meta.metadata), list(expected))     # key order preserved

    def test_04_dispatcher_equals_executor_then_output_factory(self):
        plan = make_plan()
        self.assertEqual(dispatch_web_request(plan), create_web_request_output(execute_web_request_plan(plan)))

    def test_05_pipeline_returns_the_dispatchers_very_object_and_calls_it_once(self):
        plan = make_plan()
        sentinel = make_output("S", "C", (("k", 1),))
        with mock.patch.object(wp, "dispatch_web_request", return_value=sentinel) as m:
            self.assertIs(run_web_request_pipeline(plan), sentinel)
        m.assert_called_once_with(plan)
        self.assertIs(m.call_args.args[0], plan)

    def test_06_pipeline_output_equals_dispatcher_output_and_survives_validator_and_metadata_executor(self):
        plan = make_plan()
        out = run_web_request_pipeline(plan)
        self.assertEqual(out, dispatch_web_request(plan))
        self.assertTrue(validate_web_request_output(out).ok)
        self.assertEqual(execute_web_request_metadata(out).to_dict(), out.to_dict())

    def test_07_batch_outputs_equal_pipeline_outputs_in_order(self):
        plans = tuple(make_plan(request_id="b%d" % i, timeout_ms=100 + i) for i in range(5))
        batch = run_web_request_batch(plans)
        self.assertTrue(batch.ok)
        self.assertEqual(batch.outputs, tuple(run_web_request_pipeline(p) for p in plans))
        self.assertEqual([o.metadata["request_id"] for o in batch.outputs], ["b0", "b1", "b2", "b3", "b4"])

    def test_08_end_to_end_from_plain_data_to_summary(self):
        registry = build_registry(("page", "api", "doc"))
        specs = [dict(request_id="e1", resource_type="page"), dict(request_id="e2", resource_type="api", method="POST", timeout_ms=10),
                 dict(request_id="e3", resource_type="doc", url="https://d.example/")]
        plans = tuple(build_chain(registry=registry, **s)["plan"] for s in specs)
        batch = run_web_request_batch(plans)
        summary = create_web_request_batch_summary(batch)
        self.assertEqual(summary.to_dict(), {"total_count": 3, "output_count": 3, "failure_count": 0, "status_counts": {"NOT_IMPLEMENTED": 3},
                                             "code_counts": {NOT_IMPL: 3}, "success": True, "codes": []})
        self.assertEqual([o.metadata["resource_type"] for o in batch.outputs], ["page", "api", "doc"])

    def test_09_end_to_end_mixed_batch_rejected_then_corrected(self):
        good = make_plan()
        rejected = run_web_request_batch((good, "not a plan"))
        s = create_web_request_batch_summary(rejected)
        self.assertEqual((rejected.ok, rejected.outputs, rejected.codes()), (False, (), ["WEB_REQUEST_BATCH_INVALID_PLAN"]))
        self.assertEqual((s.success, s.total_count, s.output_count, s.failure_count, s.status_counts, s.codes()), (False, 1, 0, 1, {}, []))
        fixed = create_web_request_batch_summary(run_web_request_batch((good,)))
        self.assertEqual((fixed.success, fixed.output_count), (True, 1))

    def test_10_end_to_end_empty_batch(self):
        batch = run_web_request_batch(())
        self.assertEqual((batch.ok, batch.outputs, batch.failures), (True, (), ()))
        self.assertEqual(create_web_request_batch_summary(batch).to_dict(), {"total_count": 0, "output_count": 0, "failure_count": 0, "status_counts": {},
                                                                              "code_counts": {}, "success": True, "codes": []})

    def test_11_end_to_end_resource_type_not_registered_stops_before_a_plan_exists(self):
        reg = build_registry(("page",))
        req = create_web_request(dict(DEFAULT, resource_type="video"))
        self.assertTrue(req.ok)
        val = validate_web_request(req.request, reg)
        self.assertEqual((val.ok, val.codes()), (False, ["WEB_REQUEST_VALIDATION_RESOURCE_NOT_FOUND"]))
        pl = create_web_request_plan(val)
        self.assertEqual((pl.ok, pl.plan, pl.codes()), (False, None, ["WEB_REQUEST_PLAN_VALIDATION_FAILED"]))
        # a failed plan result can never feed the later layers
        self.assertEqual(run_web_request_pipeline(pl.plan).code, "WEB_REQUEST_PIPELINE_INVALID_PLAN")
        self.assertEqual(run_web_request_batch((pl.plan,)).codes(), ["WEB_REQUEST_BATCH_INVALID_PLAN"])

    def test_12_chain_is_the_documented_data_flow(self):
        """Dispatcher/pipeline compose executor+output factory; validator and metadata executor consume the output (side branch of the same flow)."""
        plan = make_plan()
        with mock.patch.object(wdisp, "execute_web_request_plan", wraps=execute_web_request_plan) as e, \
                mock.patch.object(wdisp, "create_web_request_output", wraps=create_web_request_output) as o:
            out = run_web_request_pipeline(plan)
        e.assert_called_once_with(plan)
        o.assert_called_once()
        self.assertIs(type(o.call_args.args[0]), WebRequestExecutionResult)
        self.assertEqual(out.status, "NOT_IMPLEMENTED")


class TestInvalidInputsAreRejectedDeterministically(unittest.TestCase):
    def test_20_resource_rejections(self):
        base = {"resource_id": "a", "url": "u", "title": "", "resource_type": "page"}
        cases = [(None, ["WEB_RESOURCE_INVALID_INPUT"]), ([], ["WEB_RESOURCE_INVALID_INPUT"]),
                 ({}, ["WEB_RESOURCE_MISSING_FIELD"] * 4),
                 (dict(base, extra=1), ["WEB_RESOURCE_UNEXPECTED_FIELD"]),
                 (dict(base, resource_id=""), ["WEB_RESOURCE_INVALID_RESOURCE_ID"]), (dict(base, url=""), ["WEB_RESOURCE_INVALID_URL"]),
                 (dict(base, resource_type=""), ["WEB_RESOURCE_INVALID_RESOURCE_TYPE"]), (dict(base, title=5), ["WEB_RESOURCE_INVALID_TITLE"]),
                 (dict(base, url=b"u"), ["WEB_RESOURCE_INVALID_URL"]), ({1: "x", **base}, ["WEB_RESOURCE_UNEXPECTED_FIELD"])]
        for data, codes in cases:
            r1, r2 = create_web_resource(data), create_web_resource(data)
            self.assertEqual((r1.ok, r1.resource, r1.codes()), (False, None, codes), data)
            self.assertEqual(r1.to_dict(), r2.to_dict())
        self.assertTrue(create_web_resource(base).ok)          # an empty title is the one allowed empty field

    def test_21_registry_rejections(self):
        res = create_web_resource({"resource_id": "a", "url": "u", "title": "", "resource_type": "page"}).resource
        self.assertEqual(create_web_resource_registry(None).codes(), ["WEB_RESOURCE_REGISTRY_INVALID_COLLECTION"])
        self.assertEqual(create_web_resource_registry({res}).codes(), ["WEB_RESOURCE_REGISTRY_INVALID_COLLECTION"])
        self.assertEqual(create_web_resource_registry([res, "x", None]).codes(), ["WEB_RESOURCE_REGISTRY_INVALID_RESOURCE"] * 2)
        self.assertEqual(create_web_resource_registry([res, res]).codes(), ["WEB_RESOURCE_REGISTRY_DUPLICATE_RESOURCE_ID"])
        self.assertEqual(create_web_resource_registry([{"resource_id": "a"}]).codes(), ["WEB_RESOURCE_REGISTRY_INVALID_RESOURCE"])
        reg = create_web_resource_registry([res]).registry
        self.assertEqual(reg.lookup("zzz").codes(), ["WEB_RESOURCE_REGISTRY_RESOURCE_NOT_FOUND"])
        self.assertEqual(reg.lookup(5).codes(), ["WEB_RESOURCE_REGISTRY_INVALID_RESOURCE_ID"])
        self.assertTrue(reg.lookup("a").found)

    def test_22_request_rejections(self):
        base = dict(DEFAULT)
        cases = [(None, ["WEB_REQUEST_INVALID_INPUT"]), ([], ["WEB_REQUEST_INVALID_INPUT"]), ({}, ["WEB_REQUEST_MISSING_FIELD"] * 5),
                 (dict(base, extra=1), ["WEB_REQUEST_UNEXPECTED_FIELD"]), (dict(base, request_id=""), ["WEB_REQUEST_INVALID_REQUEST_ID"]),
                 (dict(base, url=3), ["WEB_REQUEST_INVALID_URL"]), (dict(base, method=""), ["WEB_REQUEST_INVALID_METHOD"]),
                 (dict(base, resource_type=None), ["WEB_REQUEST_INVALID_RESOURCE_TYPE"]),
                 (dict(base, timeout_ms=0), ["WEB_REQUEST_INVALID_TIMEOUT_MS"]), (dict(base, timeout_ms=-5), ["WEB_REQUEST_INVALID_TIMEOUT_MS"]),
                 (dict(base, timeout_ms=True), ["WEB_REQUEST_INVALID_TIMEOUT_MS"]), (dict(base, timeout_ms=1.5), ["WEB_REQUEST_INVALID_TIMEOUT_MS"]),
                 (dict(base, timeout_ms="5"), ["WEB_REQUEST_INVALID_TIMEOUT_MS"])]
        for data, codes in cases:
            r = create_web_request(data)
            self.assertEqual((r.ok, r.request, r.codes()), (False, None, codes), data)
            self.assertEqual(r.to_dict(), create_web_request(data).to_dict())
        self.assertTrue(create_web_request(dict(base, timeout_ms=1)).ok)

    def test_23_validator_rejections(self):
        reg, req = build_registry(), create_web_request(DEFAULT).request
        self.assertEqual(validate_web_request(None, reg).codes(), ["WEB_REQUEST_VALIDATION_INVALID_REQUEST"])
        self.assertEqual(validate_web_request(req, None).codes(), ["WEB_REQUEST_VALIDATION_INVALID_REGISTRY"])
        self.assertEqual(validate_web_request({}, []).codes(), ["WEB_REQUEST_VALIDATION_INVALID_REQUEST", "WEB_REQUEST_VALIDATION_INVALID_REGISTRY"])
        self.assertEqual(validate_web_request(req, build_registry(("api",))).codes(), ["WEB_REQUEST_VALIDATION_RESOURCE_NOT_FOUND"])
        self.assertEqual(validate_web_request(req, create_web_resource_registry(()).registry).codes(), ["WEB_REQUEST_VALIDATION_RESOURCE_NOT_FOUND"])
        self.assertTrue(validate_web_request(req, reg).ok)

    def test_24_plan_rejections(self):
        self.assertEqual(create_web_request_plan(None).codes(), ["WEB_REQUEST_PLAN_INVALID_VALIDATION_RESULT"])
        self.assertEqual(create_web_request_plan({"ok": True}).codes(), ["WEB_REQUEST_PLAN_INVALID_VALIDATION_RESULT"])
        bad = validate_web_request(None, None)
        r = create_web_request_plan(bad)
        self.assertEqual((r.ok, r.plan, r.codes()), (False, None, ["WEB_REQUEST_PLAN_VALIDATION_FAILED"]))
        self.assertIn("WEB_REQUEST_VALIDATION_INVALID_REQUEST", r.failures[0]["message"])

    def test_25_executor_output_validator_and_metadata_executor_rejections(self):
        for bad in JUNK:
            ex = execute_web_request_plan(bad)
            self.assertEqual((ex.status, ex.code, ex.metadata, ex.ok, ex.executed), ("REJECTED", "WEB_REQUEST_EXECUTOR_INVALID_PLAN", None, False, False))
            out = create_web_request_output(bad)
            self.assertEqual(out.to_dict(), {"status": "REJECTED", "code": "WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT", "metadata": None})
            self.assertEqual(validate_web_request_output(bad).codes(), ["WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_OUTPUT"])
            self.assertEqual(execute_web_request_metadata(bad).to_dict(),
                             {"status": "REJECTED", "code": "WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT", "metadata": None})

    def test_26_output_validator_catches_malformed_exact_outputs(self):
        self.assertEqual(validate_web_request_output(make_output(5, "c", None)).codes(), ["WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_STATUS"])
        self.assertEqual(validate_web_request_output(make_output("s", b"c", None)).codes(), ["WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_CODE"])
        self.assertEqual(validate_web_request_output(make_output(None, None, None)).codes(),
                         ["WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_STATUS", "WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_CODE"])
        self.assertEqual(execute_web_request_metadata(make_output(5, "c")).code, "WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT")
        self.assertTrue(validate_web_request_output(make_output("s", "c", (("k", 1),))).ok)

    def test_27_dispatcher_and_pipeline_reject_non_plans_without_calling_anything_below(self):
        for bad in JUNK:
            with mock.patch.object(wdisp, "execute_web_request_plan", _boom), mock.patch.object(wdisp, "create_web_request_output", _boom):
                d = dispatch_web_request(bad)
            self.assertEqual(d.to_dict(), {"status": "REJECTED", "code": "WEB_REQUEST_DISPATCHER_INVALID_PLAN", "metadata": None})
            with mock.patch.object(wp, "dispatch_web_request", _boom):
                p = run_web_request_pipeline(bad)
            self.assertEqual(p.to_dict(), {"status": "REJECTED", "code": "WEB_REQUEST_PIPELINE_INVALID_PLAN", "metadata": None})

    def test_28_chain_outputs_are_not_accepted_as_plans_by_later_layers(self):
        c = build_chain()
        not_plans = (c["request"], c["validation"], c["registry"], execute_web_request_plan(c["plan"]), run_web_request_pipeline(c["plan"]),
                     c["plan"].to_dict())
        for bad in not_plans:
            self.assertEqual(execute_web_request_plan(bad).code, "WEB_REQUEST_EXECUTOR_INVALID_PLAN")
            self.assertEqual(dispatch_web_request(bad).code, "WEB_REQUEST_DISPATCHER_INVALID_PLAN")
            self.assertEqual(run_web_request_pipeline(bad).code, "WEB_REQUEST_PIPELINE_INVALID_PLAN")
            self.assertEqual(run_web_request_batch((bad,)).codes(), ["WEB_REQUEST_BATCH_INVALID_PLAN"])

    def test_29_batch_rejections_report_every_bad_item_and_run_nothing(self):
        plan = make_plan()
        for bad in (None, [plan], {plan}, {"a": plan}, "abc", 5, (p for p in (plan,)), iter((plan,))):
            with mock.patch.object(wb, "run_web_request_pipeline", _boom):
                r = run_web_request_batch(bad)
            self.assertEqual((r.ok, r.outputs, r.codes(), r.failures[0]["field"]), (False, (), ["WEB_REQUEST_BATCH_INVALID_COLLECTION"], "plans"))
        import collections
        Named = collections.namedtuple("Named", "a b")
        with mock.patch.object(wb, "run_web_request_pipeline", _boom):
            self.assertEqual(run_web_request_batch(Named(plan, plan)).codes(), ["WEB_REQUEST_BATCH_INVALID_COLLECTION"])
            r = run_web_request_batch((plan, None, plan, "x", 3))
        self.assertEqual((r.ok, r.outputs, r.codes()), (False, (), ["WEB_REQUEST_BATCH_INVALID_PLAN"] * 3))
        self.assertEqual([f["field"] for f in r.failures], ["plans[1]", "plans[3]", "plans[4]"])
        self.assertEqual(r.to_dict(), run_web_request_batch((plan, None, plan, "x", 3)).to_dict())

    def test_30_summary_rejections(self):
        for bad in JUNK + (make_plan(), run_web_request_pipeline(make_plan())):
            s = create_web_request_batch_summary(bad)
            self.assertEqual(s.to_dict(), {"total_count": 0, "output_count": 0, "failure_count": 0, "status_counts": {}, "code_counts": {},
                                           "success": False, "codes": ["WEB_REQUEST_BATCH_SUMMARY_INVALID_RESULT"]})
        o = run_web_request_pipeline(make_plan())
        forged = [WebRequestBatchResult(wb._CREATE_TOKEN, (o, "x"), ()), WebRequestBatchResult(wb._CREATE_TOKEN, (make_output(1, "c"),), ()),
                  WebRequestBatchResult(wb._CREATE_TOKEN, (make_output("s", None),), ()),
                  WebRequestBatchResult(wb._CREATE_TOKEN, (o,), [("c", "f", "m")])]
        for batch in forged:
            s = create_web_request_batch_summary(batch)
            self.assertEqual((s.success, s.total_count, s.codes(), s.status_counts, s.code_counts),
                             (False, 0, ["WEB_REQUEST_BATCH_SUMMARY_MALFORMED_RESULT"], {}, {}), batch)

    def test_31_no_public_entry_point_raises_on_junk(self):
        entries = (create_web_resource, create_web_resource_registry, create_web_request, create_web_request_plan, execute_web_request_plan,
                   create_web_request_output, validate_web_request_output, execute_web_request_metadata, dispatch_web_request, run_web_request_pipeline,
                   run_web_request_batch, create_web_request_batch_summary)
        for fn in entries:
            for junk in JUNK:
                a, b = fn(junk), fn(junk)
                self.assertEqual(a.to_dict(), b.to_dict(), (fn.__name__, junk))
        for junk in JUNK:
            for other in JUNK:
                self.assertEqual(validate_web_request(junk, other).to_dict(), validate_web_request(junk, other).to_dict())


def _typed_instances():
    c = build_chain()
    plan = c["plan"]
    out = run_web_request_pipeline(plan)
    batch = run_web_request_batch((plan,))
    return [(WebResource, c["registry"].resources[0]), (WebResourceRegistry, c["registry"]), (WebRequest, c["request"]),
            (WebRequestValidationResult, c["validation"]), (WebRequestPlanResult, create_web_request_plan(c["validation"])), (WebRequestPlan, plan),
            (WebRequestExecutionResult, execute_web_request_plan(plan)), (WebRequestOutput, out),
            (WebRequestOutputValidationResult, validate_web_request_output(out)), (WebRequestMetadataExecutionResult, execute_web_request_metadata(out)),
            (WebRequestBatchResult, batch), (WebRequestBatchSummary, create_web_request_batch_summary(batch))]


class TestExactTypeAndImmutabilityContracts(unittest.TestCase):
    def test_40_cannot_be_subclassed(self):
        for cls, _inst in _typed_instances():
            with self.assertRaises(TypeError, msg=cls.__name__):
                type("Sub", (cls,), {})

    def test_41_cannot_be_built_directly(self):
        for cls, _inst in _typed_instances():
            with self.assertRaises(TypeError, msg=cls.__name__):
                cls()
            with self.assertRaises(TypeError, msg=cls.__name__):
                cls(object(), *([None] * 6))

    def test_42_assignment_and_deletion_are_refused(self):
        for cls, inst in _typed_instances():
            names = [n for n in dir(inst) if not n.startswith("__")]
            self.assertTrue(names)
            with self.assertRaises(AttributeError, msg=cls.__name__):
                inst.brand_new = 1
            with self.assertRaises(AttributeError, msg=cls.__name__):
                setattr(inst, names[0], 1)
            with self.assertRaises(AttributeError, msg=cls.__name__):
                delattr(inst, names[0])
            self.assertFalse(hasattr(inst, "__dict__"), cls.__name__)

    def test_43_copy_is_identity_and_pickle_is_refused(self):
        for cls, inst in _typed_instances():
            self.assertIs(copy.copy(inst), inst, cls.__name__)
            self.assertIs(copy.deepcopy(inst), inst, cls.__name__)
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError, msg=cls.__name__):
                    pickle.dumps(inst, proto)

    def test_44_equality_and_hash_are_by_value_and_exact_type_only(self):
        a, b = _typed_instances(), _typed_instances()
        for (cls, x), (_c, y) in zip(a, b):
            self.assertEqual(x, y, cls.__name__)
            self.assertEqual(hash(x), hash(y), cls.__name__)
            self.assertFalse(x == object(), cls.__name__)
            self.assertFalse(x == x.to_dict(), cls.__name__)
        out = make_output("S", "C")
        self.assertNotEqual(out, make_output("S", "D"))
        self.assertNotEqual(execute_web_request_metadata(out), out)       # same data, different type

    def test_45_lookalikes_are_never_accepted(self):
        plan = make_plan()

        class Fake:
            request_id, url, method, resource_type, timeout_ms = "a", "u", "GET", "page", 5

            def to_dict(self):
                return {}
        fake_out = type("WebRequestOutput", (), {"status": "s", "code": "c", "metadata": None})()
        for fake in (Fake(), mock.Mock(spec=WebRequestPlan), type("WebRequestPlan", (), {})()):
            self.assertEqual(execute_web_request_plan(fake).code, "WEB_REQUEST_EXECUTOR_INVALID_PLAN")
            self.assertEqual(run_web_request_pipeline(fake).code, "WEB_REQUEST_PIPELINE_INVALID_PLAN")
            self.assertEqual(run_web_request_batch((plan, fake)).codes(), ["WEB_REQUEST_BATCH_INVALID_PLAN"])
        self.assertEqual(validate_web_request_output(fake_out).codes(), ["WEB_REQUEST_OUTPUT_VALIDATOR_INVALID_OUTPUT"])
        self.assertEqual(execute_web_request_metadata(fake_out).code, "WEB_REQUEST_METADATA_EXECUTOR_INVALID_OUTPUT")
        self.assertEqual(create_web_request_batch_summary(mock.Mock(spec=WebRequestBatchResult)).codes(), ["WEB_REQUEST_BATCH_SUMMARY_INVALID_RESULT"])
        self.assertEqual(validate_web_request(mock.Mock(spec=WebRequest), mock.Mock(spec=WebResourceRegistry)).codes(),
                         ["WEB_REQUEST_VALIDATION_INVALID_REQUEST", "WEB_REQUEST_VALIDATION_INVALID_REGISTRY"])

    def test_46_returned_containers_are_fresh_on_every_call(self):
        plan = make_plan()
        out = run_web_request_pipeline(plan)
        out.metadata["request_id"] = "tampered"
        out.to_dict()["metadata"]["url"] = "tampered"
        self.assertEqual(out.metadata["request_id"], "req_1")
        ex = execute_web_request_plan(plan)
        ex.metadata["url"] = "tampered"
        self.assertEqual(ex.metadata["url"], DEFAULT["url"])
        meta = execute_web_request_metadata(out)
        meta.metadata.clear()
        self.assertEqual(len(meta.metadata), 5)
        batch = run_web_request_batch((plan,))
        batch.to_dict()["outputs"].clear()
        batch.failures
        self.assertEqual(len(batch.outputs), 1)
        bad = run_web_request_batch((None,))
        bad.failures[0]["code"] = "tampered"
        bad.to_dict()["failures"].clear()
        self.assertEqual(bad.codes(), ["WEB_REQUEST_BATCH_INVALID_PLAN"])
        s = create_web_request_batch_summary(batch)
        s.status_counts["X"] = 9
        s.code_counts.clear()
        s.codes().append("x")
        s.to_dict()["status_counts"].clear()
        self.assertEqual((s.status_counts, s.codes()), ({"NOT_IMPLEMENTED": 1}, []))
        reg = build_registry(("a", "b"))
        reg.to_dict()["resources"].clear()
        self.assertEqual(reg.resource_ids, ("a", "b"))
        self.assertIs(type(reg.resources), tuple)

    def test_47_factory_result_carriers_are_the_only_mutable_objects_and_cannot_affect_the_chain(self):
        """Intentional Section 9 limitation: WebResourceResult / WebResourceRegistryResult / WebRequestResult are plain mutable carriers
        (Prompts 773-775). The immutable domain objects they carry are unaffected by any change to a carrier."""
        res = create_web_resource({"resource_id": "page", "url": "u", "title": "", "resource_type": "page"})
        reg_res = create_web_resource_registry([res.resource])
        req_res = create_web_request(DEFAULT)
        before = (res.resource, reg_res.registry, req_res.request)
        for carrier in (res, reg_res, req_res):
            carrier.failures = ["tampered"]
        res.resource = req_res.request = reg_res.registry = None
        reg, req = before[1], before[2]
        self.assertTrue(validate_web_request(req, reg).ok)
        self.assertEqual(before[0].to_dict()["resource_type"], "page")
        self.assertEqual(run_web_request_pipeline(create_web_request_plan(validate_web_request(req, reg)).plan).status, "NOT_IMPLEMENTED")

    def test_48_inputs_are_not_retained_or_modified(self):
        data = dict(DEFAULT)
        req = create_web_request(data).request
        data["url"] = "https://tampered"
        self.assertEqual(req.url, DEFAULT["url"])
        rdata = {"resource_id": "page", "url": "u", "title": "t", "resource_type": "page"}
        snapshot = dict(rdata)
        res = create_web_resource(rdata).resource
        self.assertEqual(rdata, snapshot)
        resources = [res]
        reg = create_web_resource_registry(resources).registry
        resources.append("junk")
        resources.clear()
        self.assertEqual(reg.resource_ids, ("page",))
        plans = (make_plan(),)
        plan_before = plans[0].to_dict()
        run_web_request_batch(plans)
        self.assertEqual(plans[0].to_dict(), plan_before)
        self.assertIs(type(plans), tuple)


class TestDeterminismOrderAndNoDuplicateExecution(unittest.TestCase):
    def test_50_repeated_runs_are_equal_at_every_layer(self):
        for _ in range(3):
            c1, c2 = build_chain(), build_chain()
            self.assertEqual(c1["plan"], c2["plan"])
            self.assertEqual(c1["validation"], c2["validation"])
            self.assertEqual(execute_web_request_plan(c1["plan"]), execute_web_request_plan(c2["plan"]))
            self.assertEqual(run_web_request_pipeline(c1["plan"]), run_web_request_pipeline(c2["plan"]))
            b1, b2 = run_web_request_batch((c1["plan"],) * 2), run_web_request_batch((c2["plan"],) * 2)
            self.assertEqual(b1, b2)
            self.assertEqual(create_web_request_batch_summary(b1), create_web_request_batch_summary(b2))
            self.assertEqual(hash(create_web_request_batch_summary(b1)), hash(create_web_request_batch_summary(b2)))

    def test_51_batch_preserves_order_for_every_permutation(self):
        import itertools
        plans = [make_plan(request_id="p%d" % i, timeout_ms=10 + i) for i in range(4)]
        for perm in itertools.permutations(range(4)):
            batch = run_web_request_batch(tuple(plans[i] for i in perm))
            self.assertEqual([o.metadata["request_id"] for o in batch.outputs], ["p%d" % i for i in perm])

    def test_52_batch_calls_the_pipeline_exactly_once_per_item_in_order_with_the_same_objects(self):
        plans = tuple(make_plan(request_id="c%d" % i) for i in range(6))
        plans = plans + (plans[0], plans[2])            # the same plan object twice is two items
        with mock.patch.object(wb, "run_web_request_pipeline", wraps=run_web_request_pipeline) as m:
            batch = run_web_request_batch(plans)
        self.assertEqual(m.call_count, len(plans))
        for call, plan in zip(m.call_args_list, plans):
            self.assertEqual(len(call.args), 1)
            self.assertEqual(call.kwargs, {})
            self.assertIs(call.args[0], plan)
        self.assertEqual(len(batch.outputs), len(plans))

    def test_53_no_layer_executes_a_plan_more_than_once_per_item(self):
        plans = tuple(make_plan(request_id="d%d" % i) for i in range(5))
        with mock.patch.object(wdisp, "execute_web_request_plan", wraps=execute_web_request_plan) as ex, \
                mock.patch.object(wdisp, "create_web_request_output", wraps=create_web_request_output) as out, \
                mock.patch.object(wp, "dispatch_web_request", wraps=dispatch_web_request) as dsp:
            run_web_request_batch(plans)
        self.assertEqual((ex.call_count, out.call_count, dsp.call_count), (5, 5, 5))
        self.assertEqual([c.args[0].request_id for c in ex.call_args_list], ["d0", "d1", "d2", "d3", "d4"])

    def test_54_empty_and_rejected_batches_execute_nothing(self):
        with mock.patch.object(wdisp, "execute_web_request_plan", _boom), mock.patch.object(wp, "dispatch_web_request", _boom), \
                mock.patch.object(wb, "run_web_request_pipeline", _boom):
            self.assertTrue(run_web_request_batch(()).ok)
            self.assertFalse(run_web_request_batch((None,)).ok)
            self.assertFalse(run_web_request_batch([]).ok)

    def test_55_batch_stores_the_pipeline_outputs_by_identity(self):
        plans = tuple(make_plan(request_id="i%d" % i) for i in range(3))
        returned = [make_output("S%d" % i, "C%d" % i) for i in range(3)]
        with mock.patch.object(wb, "run_web_request_pipeline", side_effect=returned):
            batch = run_web_request_batch(plans)
        for stored, original in zip(batch.outputs, returned):
            self.assertIs(stored, original)

    def test_56_large_batch_is_complete_and_ordered(self):
        plans = tuple(make_plan(request_id="L%03d" % i) for i in range(200))
        batch = run_web_request_batch(plans)
        self.assertEqual([o.metadata["request_id"] for o in batch.outputs], ["L%03d" % i for i in range(200)])
        s = create_web_request_batch_summary(batch)
        self.assertEqual((s.total_count, s.output_count, s.status_counts, s.code_counts), (200, 200, {"NOT_IMPLEMENTED": 200}, {NOT_IMPL: 200}))


class TestBatchSummaryIsDeterministicAndDoesNotReinterpret(unittest.TestCase):
    def _batch(self, outputs, failures=()):
        return WebRequestBatchResult(wb._CREATE_TOKEN, tuple(outputs), list(failures))

    def test_60_counts_are_exact_and_sorted_by_key_regardless_of_output_order(self):
        outs = [make_output("Z", "c2"), make_output("A", "c1"), make_output("Z", "c2"), make_output("M", "c3"), make_output("A", "c1"), make_output("Z", "c1")]
        s = create_web_request_batch_summary(self._batch(outs))
        self.assertEqual(list(s.status_counts.items()), [("A", 2), ("M", 1), ("Z", 3)])
        self.assertEqual(list(s.code_counts.items()), [("c1", 3), ("c2", 2), ("c3", 1)])
        self.assertEqual(sum(s.status_counts.values()), s.output_count)
        self.assertEqual(sum(s.code_counts.values()), s.output_count)
        for rot in range(len(outs)):
            self.assertEqual(create_web_request_batch_summary(self._batch(outs[rot:] + outs[:rot])), s)
        self.assertEqual(create_web_request_batch_summary(self._batch(list(reversed(outs)))).to_dict(), s.to_dict())

    def test_61_keys_are_exact_strings_with_no_folding_or_trimming(self):
        outs = [make_output("ok", "c"), make_output("OK", "c"), make_output("ok ", "c"), make_output("", "")]
        s = create_web_request_batch_summary(self._batch(outs))
        self.assertEqual(s.status_counts, {"": 1, "OK": 1, "ok": 1, "ok ": 1})
        self.assertEqual(s.code_counts, {"": 1, "c": 3})

    def test_62_status_text_is_not_interpreted_and_ok_is_not_a_function_of_output_status(self):
        outs = [make_output("SUCCESS", "x"), make_output("FAILED", "y"), make_output("NOT_IMPLEMENTED", NOT_IMPL)]
        s = create_web_request_batch_summary(self._batch(outs))
        self.assertTrue(s.success)
        self.assertEqual((s.output_count, s.failure_count, s.total_count), (3, 0, 3))
        rejected_only = create_web_request_batch_summary(self._batch([make_output("REJECTED", "R")]))
        self.assertTrue(rejected_only.success)                 # `success` mirrors batch.ok only
        self.assertFalse(create_web_request_batch_summary(run_web_request_batch((None,))).success)

    def test_63_metadata_and_failure_messages_are_never_read(self):
        o = make_output("S", "C", (("k", 1),))
        batch = self._batch([o])
        with mock.patch.object(WebRequestOutput, "metadata", property(_boom)), mock.patch.object(WebRequestOutput, "to_dict", _boom):
            s = create_web_request_batch_summary(batch)
        self.assertEqual((s.status_counts, s.output_count), ({"S": 1}, 1))
        rejected = run_web_request_batch((None, 5))
        with mock.patch.object(WebRequestBatchResult, "codes", _boom), mock.patch.object(WebRequestBatchResult, "to_dict", _boom):
            self.assertEqual(create_web_request_batch_summary(rejected).failure_count, 2)

    def test_64_summary_executes_and_calls_nothing(self):
        batch = run_web_request_batch((make_plan(),))
        with mock.patch.object(wdisp, "execute_web_request_plan", _boom), mock.patch.object(wp, "dispatch_web_request", _boom), \
                mock.patch.object(wb, "run_web_request_pipeline", _boom), mock.patch.object(wo, "create_web_request_output", _boom), \
                mock.patch.object(wex, "execute_web_request_plan", _boom), mock.patch.object(wov, "validate_web_request_output", _boom):
            self.assertEqual(create_web_request_batch_summary(batch).output_count, 1)

    def test_65_rejected_batch_counts_failures_not_the_callers_tuple(self):
        plan = make_plan()
        s = create_web_request_batch_summary(run_web_request_batch((plan, None, plan, 7, plan)))
        self.assertEqual((s.total_count, s.output_count, s.failure_count, s.success, s.codes()), (2, 0, 2, False, []))
        s2 = create_web_request_batch_summary(run_web_request_batch("nope"))
        self.assertEqual((s2.total_count, s2.failure_count), (1, 1))

    def test_66_summary_holds_only_plain_values(self):
        s = create_web_request_batch_summary(run_web_request_batch((make_plan(),)))
        for name in s.__slots__:
            value = getattr(s, name)
            self.assertIn(type(value), (int, bool, tuple), name)
            if type(value) is tuple:
                for pair in value:
                    for item in (pair if type(pair) is tuple else (pair,)):
                        self.assertIn(type(item), (int, str), name)


class TestScopeHonestyNetworkTransportIsNotImplemented(unittest.TestCase):
    def test_70_every_valid_plan_is_not_implemented_and_never_executed(self):
        for method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "weird"):
            plan = make_plan(method=method)
            ex = execute_web_request_plan(plan)
            self.assertEqual((ex.status, ex.code, ex.ok, ex.executed), ("NOT_IMPLEMENTED", NOT_IMPL, False, False))
            self.assertEqual(run_web_request_pipeline(plan).status, "NOT_IMPLEMENTED")
            self.assertEqual(execute_web_request_metadata(run_web_request_pipeline(plan)).status, "NOT_IMPLEMENTED")
        self.assertEqual(wex.STATUSES, ("REJECTED", "NOT_IMPLEMENTED"))
        self.assertEqual(wex.CODES, ("WEB_REQUEST_EXECUTOR_INVALID_PLAN", NOT_IMPL))

    def test_71_no_response_data_exists_anywhere_in_the_chain(self):
        out = run_web_request_pipeline(make_plan())
        self.assertEqual(sorted(out.metadata), ["method", "request_id", "resource_type", "timeout_ms", "url"])
        for forbidden in ("body", "headers", "status_code", "response", "content", "elapsed"):
            self.assertFalse(hasattr(out, forbidden), forbidden)
        self.assertFalse(hasattr(execute_web_request_plan(make_plan()), "response"))

    def test_72_no_transport_function_is_defined_by_any_section9_module(self):
        words = ("fetch", "download", "connect", "send", "http", "socket", "transport", "urlopen", "request_url", "post", "retry", "schedule")
        for name in WEB_MODULES:
            mod = sys.modules["web." + name]
            tree = ast.parse(read_text(mod.__file__))
            defined = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
            for d in defined:
                self.assertFalse(any(w in d.lower() for w in words), (name, d))

    def test_73_batch_ok_and_summary_success_do_not_claim_execution(self):
        batch = run_web_request_batch((make_plan(),))
        self.assertTrue(batch.ok)
        self.assertEqual(batch.outputs[0].status, "NOT_IMPLEMENTED")
        s = create_web_request_batch_summary(batch)
        self.assertTrue(s.success)
        self.assertEqual(s.status_counts, {"NOT_IMPLEMENTED": 1})


class TestNoAccidentalExternalAccessAndNoRetainedState(unittest.TestCase):
    def _run_everything(self):
        c = build_chain()
        plan = c["plan"]
        out = run_web_request_pipeline(plan)
        execute_web_request_metadata(out)
        validate_web_request_output(out)
        batch = run_web_request_batch((plan, plan))
        create_web_request_batch_summary(batch)
        run_web_request_batch((None,))
        create_web_request_batch_summary(None)
        dispatch_web_request(None)
        return batch

    def test_80_whole_chain_performs_no_network_filesystem_subprocess_or_database_access(self):
        with forbid_io():
            batch = self._run_everything()
        self.assertEqual(len(batch.outputs), 2)

    def test_81_importing_the_chain_loads_no_io_modules(self):
        probe = "import sys; before=set(sys.modules); import web.web_request_batch_summary, web.web_request_metadata_executor; " \
                "print(sorted(m for m in set(sys.modules)-before if not m.startswith('web')))"
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        new = subprocess.run([sys.executable, "-c", probe], cwd=PY_ROOT, env=env, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(new, "[]")

    def test_82_static_import_and_call_audit_of_every_production_web_module(self):
        banned_calls = {"open", "eval", "exec", "compile", "__import__", "input", "print", "globals", "locals", "setattr", "delattr"}
        for name in WEB_MODULES + ("__init__",):
            path = os.path.join(PY_ROOT, "web", name + ".py")
            tree = ast.parse(read_text(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.fail("%s: plain import %r" % (name, [a.name for a in node.names]))
                if isinstance(node, ast.ImportFrom):
                    self.assertEqual((node.level, node.module is not None and node.module.startswith("web_")), (1, True), (name, node.module))
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, banned_calls, name)
                if isinstance(node, (ast.Global, ast.Nonlocal, ast.Await, ast.AsyncFunctionDef, ast.Yield, ast.YieldFrom)):
                    self.fail("%s: %s" % (name, type(node).__name__))

    def test_83_no_module_level_mutable_state_in_any_production_web_module(self):
        for name in WEB_MODULES:
            path = os.path.join(PY_ROOT, "web", name + ".py")
            tree = ast.parse(read_text(path))
            for node in tree.body:
                if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
                    continue
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                    continue
                self.assertIsInstance(node, ast.Assign, (name, ast.dump(node)[:60]))
                value = node.value
                ok = isinstance(value, ast.Constant) or (isinstance(value, ast.Tuple) and all(isinstance(e, (ast.Name, ast.Constant)) for e in value.elts)) \
                    or (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "object" and not value.args) \
                    or (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)) or isinstance(value, ast.Name)
                self.assertTrue(ok, (name, ast.dump(value)[:80]))
                self.assertNotIsInstance(value, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp), name)
            for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                for stmt in cls.body:
                    if isinstance(stmt, ast.Assign):
                        self.assertIsInstance(stmt.value, (ast.Tuple, ast.Constant), (name, cls.name))

    def test_84_module_attributes_are_unchanged_after_running_everything(self):
        def snapshot():
            return {n: {k: repr(v) for k, v in vars(sys.modules["web." + n]).items() if not k.startswith("__") and not callable(v)} for n in WEB_MODULES}
        before = snapshot()
        self._run_everything()
        self.assertEqual(snapshot(), before)

    def test_85_each_call_builds_fresh_objects_with_no_cache(self):
        plan = make_plan()
        a, b = run_web_request_pipeline(plan), run_web_request_pipeline(plan)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a.metadata, b.metadata)
        r1, r2 = run_web_request_batch((plan,)), run_web_request_batch((plan,))
        self.assertEqual(r1, r2)
        self.assertIsNot(r1, r2)

    def test_86_plans_are_unchanged_by_the_whole_downstream_chain(self):
        plan = make_plan(request_id="keep", timeout_ms=9)
        before = plan.to_dict()
        for _ in range(3):
            execute_web_request_plan(plan)
            dispatch_web_request(plan)
            run_web_request_pipeline(plan)
            create_web_request_batch_summary(run_web_request_batch((plan, plan)))
        self.assertEqual(plan.to_dict(), before)


class TestFrozenProductionTreeAndPristineBaselines(unittest.TestCase):
    def test_90_each_section9_production_file_is_byte_frozen(self):
        for name, expected in FROZEN_WEB_SHA256.items():
            with open(os.path.join(PY_ROOT, "web", name), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), expected, name)

    def test_91_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web"))), sorted(FROZEN_WEB_SHA256))

    def test_92_sections_1_to_8_and_all_other_production_modules_are_byte_frozen(self):
        files = []
        for folder, dirs, names in os.walk(PY_ROOT):
            rel = os.path.relpath(folder, PY_ROOT).replace(os.sep, "/")
            top = rel.split("/")[0]
            if top in ("tests", "data", "web"):
                dirs[:] = []
                continue
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            files.extend(((rel + "/" if rel != "." else "") + n) for n in sorted(names) if n.endswith(".py"))
        files.sort()
        digest = hashlib.sha256()
        for rel in files:
            with open(os.path.join(PY_ROOT, rel), "rb") as fh:
                digest.update(rel.encode() + b"\0" + hashlib.sha256(fh.read()).hexdigest().encode() + b"\n")
        self.assertEqual(len(files), FROZEN_NON_WEB_PRODUCTION_COUNT)
        self.assertEqual(digest.hexdigest(), FROZEN_NON_WEB_PRODUCTION_DIGEST)

    def test_93_no_production_module_outside_web_imports_section9(self):
        checked = 0
        for folder, dirs, names in os.walk(PY_ROOT):
            rel = os.path.relpath(folder, PY_ROOT).split(os.sep)[0]
            if rel in ("web", "tests", "data"):
                dirs[:] = []
                continue
            for n in names:
                if n.endswith(".py"):
                    tree = ast.parse(read_text(os.path.join(folder, n)))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            self.assertFalse((node.module or "").split(".")[0] == "web" or (node.level == 0 and node.module == "web"), (folder, n))
                        if isinstance(node, ast.Import):
                            self.assertNotIn("web", [a.name.split(".")[0] for a in node.names], (folder, n))
                    checked += 1
        self.assertGreater(checked, 300)

    def test_94_project_database_is_the_pristine_baseline(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_95_running_the_chain_does_not_touch_the_database_or_the_tree(self):
        def tree():
            return sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT))
        before, stat = tree(), os.stat(PROJECT_DB)
        for _ in range(3):
            run_web_request_batch((make_plan(),))
        self.assertEqual(tree(), before)
        after = os.stat(PROJECT_DB)
        self.assertEqual((after.st_size, after.st_mtime_ns), (stat.st_size, stat.st_mtime_ns))

    def test_96_no_bytecode_artifacts_anywhere_in_the_project(self):
        offenders = []
        for folder, dirs, names in os.walk(REPO_ROOT):
            if "__pycache__" in dirs or "__pycache__" in os.path.basename(folder):
                offenders.append(folder)
            offenders.extend(os.path.join(folder, n) for n in names if n.endswith((".pyc", ".pyo")))
        self.assertEqual(offenders, [])

    def test_97_section9_documents_are_exactly_the_expected_set(self):
        found = sorted(n for n in os.listdir(os.path.join(REPO_ROOT, "docs")) if n.startswith("section9_"))
        self.assertEqual(found, sorted(SECTION9_DOCS))

    def test_98_the_718_guard_exempts_exactly_the_section9_paths_and_nothing_broader(self):
        """The Prompt 718 guard excludes post-718 modules from its byte-identical check by an EXACT path tuple. For Section 9 that tuple must
        name exactly the 14 web files (no wildcard, no directory prefix), and those files stay in the guard's production listing."""
        from tests import test_section6_agent_loop_wiring_decision_prompt718 as g
        listing = g.production_files()
        for name in FROZEN_WEB_SHA256:
            self.assertIn("web/" + name, listing)
        tuples = []
        for node in ast.walk(ast.parse(read_text(g.__file__))):
            if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.NotIn) and isinstance(node.comparators[0], ast.Tuple):
                consts = [e.value for e in node.comparators[0].elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if any(c.startswith("web/") for c in consts):
                    tuples.append(consts)
        self.assertEqual(len(tuples), 1)
        web_entries = sorted(c for c in tuples[0] if c.startswith("web"))
        self.assertEqual(web_entries, sorted("web/" + n for n in FROZEN_WEB_SHA256))
        for entry in tuples[0]:
            self.assertTrue(entry.endswith(".py"), entry)
            self.assertNotIn("*", entry)
            self.assertIn(entry, listing)         # every exempted path really exists (no stale or wildcard-like entry)

    def test_99_production_web_code_has_no_test_only_branches(self):
        for name in WEB_MODULES:
            text = read_text(os.path.join(PY_ROOT, "web", name + ".py"))
            for token in ("unittest", "pytest", "mock", "environ", "getenv", "__main__", "TESTING", "sys.argv", "PYTHON"):
                self.assertNotIn(token, text.split('"""')[2] if text.count('"""') >= 2 else text, (name, token))
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    self.assertNotIn(node.value.id, ("os", "sys", "environ"), name)


class TestPackagingAndDocumentation(unittest.TestCase):
    def test_100_acceptance_document_states_the_scope_distinctions(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for phrase in ("Implemented Web architecture and contracts", "Implemented deterministic metadata, pipeline and batch behavior",
                       "Intentionally unimplemented real network transport", "Other intentional Section 9 limitations", "NOT_IMPLEMENTED",
                       "no production change", "Prompt 787", "Section 10"):
            self.assertIn(phrase, text, phrase)
        self.assertNotIn("real web execution is implemented", text.lower())

    def test_101_this_prompt_adds_no_production_file_to_the_web_package(self):
        self.assertEqual(sorted(os.listdir(os.path.join(PY_ROOT, "web"))), sorted(FROZEN_WEB_SHA256))
        self.assertEqual(len(glob.glob(os.path.join(PY_ROOT, "web", "*.py"))), 14)


if __name__ == "__main__":
    unittest.main()
