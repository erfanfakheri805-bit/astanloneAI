"""
Prompt 875 - Section 15 (Autonomous Research & Learning) final checkpoint.

End-to-end contract validation of the existing public chain (Prompts 863-874):

  research_request -> research_source -> source_matching -> source_selection
  -> source_trust -> evidence -> evidence_context_validation -> evidence_set
  -> synthesis -> learning_record -> learning_boundary -> learning_acceptance

No production code is added or changed; these tests only compose the public APIs.

Run (from app/src/main/python/):
    python -m unittest tests.test_section15_research_learning_checkpoint_prompt875 -v
"""

import ast
import builtins
import copy
import hashlib
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from research.research_evidence import build_research_evidence, validate_research_evidence
from research.research_evidence_set import build_research_evidence_set, validate_research_evidence_set
from research.research_evidence_validation import (validate_research_evidence_context_result,
                                                   validate_research_evidence_for_context)
from research.research_learning_acceptance import (build_research_learning_acceptance,
                                                   validate_research_learning_acceptance)
from research.research_learning_boundary import (evaluate_research_learning_boundary,
                                                 validate_research_learning_boundary_result)
from research.research_learning_record import (build_research_learning_record,
                                               validate_research_learning_record)
from research.research_request import build_research_request, validate_research_request
from research.research_source import build_research_source, validate_research_source
from research.research_source_matching import match_research_sources, validate_research_source_match
from research.research_source_selection import (select_research_source,
                                                validate_research_source_selection)
from research.research_source_trust import evaluate_research_source_trust, validate_research_source_trust
from research.research_synthesis import build_research_synthesis, validate_research_synthesis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAIN_MODULES = ("research_request", "research_source", "research_source_matching",
                 "research_source_selection", "research_source_trust", "research_evidence",
                 "research_evidence_validation", "research_evidence_set", "research_synthesis",
                 "research_learning_record", "research_learning_boundary",
                 "research_learning_acceptance")
# Packages that must stay untouched by the chain (Memory, AEL, capabilities) plus the chain itself.
WATCHED_DIRS = ("research", "memory", "ael", "capabilities")
FORBIDDEN_ROOTS = {"core", "memory", "ael", "capabilities", "execution", "agent", "learning",
                   "knowledge", "tools", "web", "planning", "os", "sys", "subprocess", "socket",
                   "urllib", "http", "requests", "json", "importlib", "builtins"}

KEYS = {
    "request": ["version", "request_id", "goal", "topics", "constraints", "requested_by",
                "execution_allowed"],
    "source": ["version", "source_id", "source_type", "location", "trust_level", "constraints",
               "enabled", "execution_allowed"],
    "evidence": ["version", "evidence_id", "source_id", "claim", "evidence_type", "confidence",
                 "constraints", "execution_allowed"],
    "evidence_set": ["version", "request_id", "source_id", "evidence", "count", "execution_allowed"],
    "synthesis": ["version", "synthesis_id", "request_id", "source_id", "evidence_ids",
                  "evidence_count", "claims", "execution_allowed"],
    "learning_record": ["version", "learning_record_id", "request_id", "synthesis_id", "source_id",
                        "claims", "evidence_count", "status", "execution_allowed"],
    "boundary": ["status", "ready", "learning_record_id", "request_id", "reason",
                 "execution_allowed", "executed"],
    "acceptance": ["version", "acceptance_id", "learning_record_id", "request_id", "synthesis_id",
                   "source_id", "claims", "evidence_count", "status", "execution_allowed"],
}

CLAIMS = ["Zeta claim stays first.", "alpha claim, lower case.", "Same claim.", "Same claim."]
EVIDENCE_IDS = ["ev_z", "ev_a", "ev_s1", "ev_s2"]  # deliberately not sorted


def _forbidden(*args, **kwargs):
    raise AssertionError("forbidden call")


def source_record(sid, stype="local_file", trust="standard", enabled=True):
    r = build_research_source({"source_id": sid, "source_type": stype, "location": "loc/" + sid,
                               "trust_level": trust, "constraints": [], "enabled": enabled})
    assert r["valid"], r["errors"]
    return r["source"]


def evidence_record(eid, claim, sid):
    r = build_research_evidence({"evidence_id": eid, "source_id": sid, "claim": claim,
                                 "evidence_type": "fact", "confidence": 0.5, "constraints": []})
    assert r["valid"], r["errors"]
    return r["evidence"]


def run_chain():
    """Run every stage on a deterministic fixture; return every stage output by name."""
    s = {}
    s["request_result"] = build_research_request({
        "request_id": "req_875", "goal": "Understand retrieval-augmented generation.",
        "topics": ["rag basics", "retrieval"],
        "constraints": ["source_type:local_file", "min_trust:standard"],
        "requested_by": "developer"})
    s["request"] = s["request_result"]["research_request"]
    s["sources"] = [source_record("src_std"), source_record("src_top", trust="trusted"),
                    source_record("src_web", stype="web", trust="trusted"),
                    source_record("src_off", trust="trusted", enabled=False)]
    s["match"] = match_research_sources(s["request"], s["sources"])
    s["selection"] = select_research_source(s["match"])
    s["source"] = s["selection"]["selected"]
    s["trust"] = evaluate_research_source_trust(s["request"], s["source"])
    sid = s["source"]["source_id"]
    s["evidence"] = [evidence_record(e, c, sid) for e, c in zip(EVIDENCE_IDS, CLAIMS)]
    s["contexts"] = [validate_research_evidence_for_context(s["request"], s["source"], e)
                     for e in s["evidence"]]
    s["evidence_set_result"] = build_research_evidence_set(s["request"], s["source"], s["evidence"])
    s["evidence_set"] = s["evidence_set_result"]["evidence_set"]
    s["synthesis_result"] = build_research_synthesis(s["request"], s["evidence_set"], "syn_875")
    s["synthesis"] = s["synthesis_result"]["synthesis"]
    s["record_result"] = build_research_learning_record(s["request"], s["synthesis"], "lr_875")
    s["record"] = s["record_result"]["learning_record"]
    s["boundary"] = evaluate_research_learning_boundary(s["request"], s["record"])
    s["acceptance_result"] = build_research_learning_acceptance(
        s["request"], s["record"], s["boundary"], "acc_875")
    s["acceptance"] = s["acceptance_result"]["acceptance"]
    return s


def tree_fingerprint():
    digest = hashlib.sha256()
    for sub in WATCHED_DIRS:
        for base, dirs, files in os.walk(os.path.join(ROOT, sub)):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(files):
                if name.endswith(".py"):
                    path = os.path.join(base, name)
                    with open(path, "rb") as fh:
                        digest.update(path.encode() + fh.read())
    return digest.hexdigest()


def codes(result):
    return [e["code"] for e in result["errors"]]


def flags_false(test, value, where):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("execution_allowed", "executed"):
                test.assertIs(item, False, (where, key))
            flags_false(test, item, where + "." + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            flags_false(test, item, "%s[%d]" % (where, index))


class SuccessChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = run_chain()

    def test_request_source_and_matching_stages(self):
        s = self.s
        self.assertTrue(s["request_result"]["valid"])
        self.assertTrue(validate_research_request(s["request"])["valid"])
        for src in s["sources"]:
            self.assertTrue(validate_research_source(src)["valid"])
        self.assertEqual((s["match"]["status"], s["match"]["matched"]), ("matched", True))
        self.assertEqual([m["source_id"] for m in s["match"]["matches"]], ["src_std", "src_top"])
        self.assertTrue(validate_research_source_match(s["match"])["valid"])

    def test_selection_and_trust_stages(self):
        s = self.s
        self.assertEqual(s["selection"]["status"], "selected")
        self.assertTrue(validate_research_source_selection(s["selection"])["valid"])
        self.assertEqual(s["source"]["source_id"], "src_top")  # highest trust wins, nothing guessed
        self.assertEqual((s["trust"]["status"], s["trust"]["trusted"]), ("trusted", True))
        self.assertTrue(validate_research_source_trust(s["trust"])["valid"])

    def test_evidence_and_context_stages(self):
        s = self.s
        for ev, ctx in zip(s["evidence"], s["contexts"]):
            self.assertTrue(validate_research_evidence(ev)["valid"])
            self.assertEqual((ctx["status"], ctx["valid"]), ("valid", True))
            self.assertTrue(validate_research_evidence_context_result(ctx)["valid"])
            self.assertEqual((ctx["evidence_id"], ctx["source_id"]),
                             (ev["evidence_id"], "src_top"))

    def test_evidence_set_stage(self):
        s = self.s
        self.assertTrue(s["evidence_set_result"]["valid"])
        self.assertTrue(validate_research_evidence_set(s["evidence_set"])["valid"])
        self.assertEqual(s["evidence_set"]["count"], 4)

    def test_synthesis_stage(self):
        s = self.s
        self.assertTrue(s["synthesis_result"]["valid"])
        self.assertTrue(validate_research_synthesis(s["synthesis"])["valid"])

    def test_learning_record_stage(self):
        s = self.s
        self.assertTrue(s["record_result"]["valid"])
        self.assertTrue(validate_research_learning_record(s["record"])["valid"])
        self.assertEqual(s["record"]["status"], "candidate")

    def test_boundary_stage_is_ready(self):
        b = self.s["boundary"]
        self.assertEqual((b["status"], b["ready"]), ("ready", True))
        self.assertTrue(validate_research_learning_boundary_result(b)["valid"])

    def test_acceptance_stage(self):
        s = self.s
        self.assertTrue(s["acceptance_result"]["valid"])
        self.assertEqual(s["acceptance_result"]["errors"], [])
        self.assertTrue(validate_research_learning_acceptance(s["acceptance"])["valid"])
        self.assertEqual(s["acceptance"]["status"], "accepted")

    def test_identities_flow_through_the_chain(self):
        s = self.s
        for obj in (s["evidence_set"], s["synthesis"], s["record"], s["acceptance"],
                    s["boundary"]):
            self.assertEqual(obj["request_id"], "req_875")
        self.assertEqual(s["request"]["request_id"], "req_875")
        for obj in (s["source"], s["trust"], s["evidence_set"], s["synthesis"], s["record"],
                    s["acceptance"]):
            self.assertEqual(obj["source_id"], "src_top")
        for ev in s["evidence"]:
            self.assertEqual(ev["source_id"], "src_top")
        self.assertEqual(s["synthesis"]["synthesis_id"], "syn_875")
        self.assertEqual((s["record"]["synthesis_id"], s["acceptance"]["synthesis_id"]),
                         ("syn_875", "syn_875"))
        self.assertEqual((s["record"]["learning_record_id"], s["boundary"]["learning_record_id"],
                          s["acceptance"]["learning_record_id"]), ("lr_875",) * 3)
        self.assertEqual(s["acceptance"]["acceptance_id"], "acc_875")

    def test_evidence_ids_preserved_and_ordered(self):
        s = self.s
        self.assertEqual([e["evidence_id"] for e in s["evidence_set"]["evidence"]], EVIDENCE_IDS)
        self.assertEqual(s["synthesis"]["evidence_ids"], EVIDENCE_IDS)

    def test_claims_identical_ordered_and_not_rewritten(self):
        s = self.s
        self.assertEqual([e["claim"] for e in s["evidence_set"]["evidence"]], CLAIMS)
        for obj in (s["synthesis"], s["record"], s["acceptance"]):
            self.assertEqual(obj["claims"], CLAIMS)  # duplicates, case and order kept
            for got, want in zip(obj["claims"], CLAIMS):
                self.assertEqual(got.encode("utf-8"), want.encode("utf-8"))

    def test_evidence_count_unchanged(self):
        s = self.s
        self.assertEqual((s["evidence_set"]["count"], s["synthesis"]["evidence_count"],
                          s["record"]["evidence_count"], s["acceptance"]["evidence_count"]),
                         (4, 4, 4, 4))

    def test_exact_keys_on_every_normalized_structure(self):
        s = self.s
        for name, obj in (("request", s["request"]), ("source", s["source"]),
                          ("evidence", s["evidence"][0]), ("evidence_set", s["evidence_set"]),
                          ("synthesis", s["synthesis"]), ("learning_record", s["record"]),
                          ("boundary", s["boundary"]), ("acceptance", s["acceptance"])):
            self.assertEqual(list(obj), KEYS[name], name)

    def test_execution_flags_false_everywhere(self):
        for name, stage in self.s.items():
            flags_false(self, stage, name)
        for key in ("request_result", "evidence_set_result", "synthesis_result",
                    "record_result", "acceptance_result"):
            self.assertIs(self.s[key]["executed"], False, key)
        self.assertIs(self.s["acceptance"]["execution_allowed"], False)
        self.assertNotIn("executed", self.s["acceptance"])
        self.assertNotIn("executed", self.s["record"])

    def test_chain_is_deterministic(self):
        self.assertEqual(run_chain(), self.s)

    def test_later_stages_do_not_alter_earlier_outputs(self):
        s = self.s
        fresh = run_chain()
        for key in ("request", "source", "evidence", "evidence_set", "synthesis", "record",
                    "boundary"):
            self.assertEqual(s[key], fresh[key], key)
        self.assertIsNot(s["acceptance"]["claims"], s["record"]["claims"])
        self.assertIsNot(s["record"]["claims"], s["synthesis"]["claims"])


class RejectionPathTests(unittest.TestCase):
    def setUp(self):
        self.s = run_chain()
        self.before = copy.deepcopy(self.s)

    def tearDown(self):
        self.assertEqual(self.s, self.before)  # failures never mutate upstream inputs

    def test_invalid_request(self):
        s = self.s
        bad = dict(s["request"], goal="")
        self.assertEqual(match_research_sources(bad, s["sources"])["status"], "invalid_request")
        self.assertEqual(evaluate_research_source_trust(bad, s["source"])["status"],
                         "invalid_request")
        self.assertEqual(validate_research_evidence_for_context(bad, s["source"],
                                                                s["evidence"][0])["status"],
                         "invalid_request")
        self.assertEqual(codes(build_research_evidence_set(bad, s["source"], s["evidence"])),
                         ["invalid_request"])
        self.assertEqual(codes(build_research_synthesis(bad, s["evidence_set"], "x")),
                         ["invalid_request"])
        self.assertEqual(codes(build_research_learning_record(bad, s["synthesis"], "x")),
                         ["invalid_request"])
        self.assertEqual(evaluate_research_learning_boundary(bad, s["record"])["status"],
                         "invalid_request")
        self.assertEqual(codes(build_research_learning_acceptance(
            bad, s["record"], s["boundary"], "x")), ["invalid_request"])

    def test_invalid_source(self):
        s = self.s
        bad = dict(s["source"], trust_level="very_high")
        self.assertEqual(match_research_sources(s["request"], [bad])["status"], "invalid_sources")
        self.assertEqual(evaluate_research_source_trust(s["request"], bad)["status"],
                         "invalid_source")
        self.assertEqual(validate_research_evidence_for_context(s["request"], bad,
                                                                s["evidence"][0])["status"],
                         "invalid_source")
        self.assertEqual(codes(build_research_evidence_set(s["request"], bad, s["evidence"])),
                         ["invalid_source"])
        no_match = match_research_sources(s["request"], [])
        self.assertEqual(select_research_source(no_match)["status"], "not_selected")
        self.assertEqual(select_research_source({})["status"], "invalid_input")

    def test_invalid_evidence(self):
        s = self.s
        bad = dict(s["evidence"][0], confidence=7)
        self.assertEqual(validate_research_evidence_for_context(s["request"], s["source"],
                                                                bad)["status"],
                         "invalid_evidence")
        r = build_research_evidence_set(s["request"], s["source"], [s["evidence"][0], bad])
        self.assertEqual(r["errors"], [{"code": "invalid_evidence", "where": "evidence_items[1]"}])
        self.assertEqual(codes(build_research_evidence_set(s["request"], s["source"], [])),
                         ["invalid_evidence_set"])

    def test_evidence_source_mismatch(self):
        s = self.s
        other = evidence_record("ev_other", "Other claim.", "src_std")
        self.assertEqual(validate_research_evidence_for_context(s["request"], s["source"],
                                                                other)["status"],
                         "context_mismatch")
        r = build_research_evidence_set(s["request"], s["source"], s["evidence"] + [other])
        self.assertFalse(r["valid"])
        self.assertIsNone(r["evidence_set"])

    def test_request_evidence_set_mismatch(self):
        s = self.s
        other = build_research_request({
            "request_id": "req_other", "goal": "g", "topics": ["t"], "constraints": [],
            "requested_by": "developer"})["research_request"]
        self.assertEqual(codes(build_research_synthesis(other, s["evidence_set"], "x")),
                         ["request_mismatch"])

    def test_request_learning_record_mismatch(self):
        s = self.s
        other = build_research_request({
            "request_id": "req_other", "goal": "g", "topics": ["t"], "constraints": [],
            "requested_by": "developer"})["research_request"]
        self.assertEqual(codes(build_research_learning_record(other, s["synthesis"], "x")),
                         ["request_mismatch"])
        self.assertEqual(evaluate_research_learning_boundary(other, s["record"])["status"],
                         "context_mismatch")
        self.assertEqual(codes(build_research_learning_acceptance(
            other, s["record"], s["boundary"], "x")), ["request_mismatch"])

    def test_invalid_learning_record(self):
        s = self.s
        for bad in (dict(s["record"], evidence_count=9), dict(s["record"], claims=[]),
                    dict(s["record"], status="approved"), dict(s["record"], extra=1)):
            self.assertEqual(evaluate_research_learning_boundary(s["request"], bad)["status"],
                             "invalid_learning_record")
            self.assertEqual(codes(build_research_learning_acceptance(
                s["request"], bad, s["boundary"], "x")), ["invalid_learning_record"])

    def test_invalid_learning_boundary(self):
        s = self.s
        for bad in (None, {}, dict(s["boundary"], ready=False), dict(s["boundary"], extra=1),
                    dict(s["boundary"], executed=True)):
            self.assertEqual(codes(build_research_learning_acceptance(
                s["request"], s["record"], bad, "x")), ["invalid_boundary_result"])

    def test_boundary_not_ready(self):
        s = self.s
        rec = dict(s["record"], status="approved")
        with mock.patch("research.research_learning_boundary.validate_research_learning_record",
                        return_value={"valid": True}):
            boundary = evaluate_research_learning_boundary(s["request"], rec)
        self.assertEqual((boundary["status"], boundary["ready"]), ("not_ready", False))
        self.assertTrue(validate_research_learning_boundary_result(boundary)["valid"])
        self.assertEqual(codes(build_research_learning_acceptance(
            s["request"], s["record"], boundary, "x")), ["boundary_not_ready"])

    def test_learning_record_acceptance_mismatch(self):
        s = self.s
        other_record = dict(s["record"], learning_record_id="lr_other")
        other_boundary = evaluate_research_learning_boundary(s["request"], other_record)
        self.assertEqual(other_boundary["status"], "ready")
        r = build_research_learning_acceptance(s["request"], s["record"], other_boundary, "x")
        self.assertEqual(r["errors"], [{"code": "learning_record_mismatch",
                                        "where": "boundary_result"}])
        self.assertIsNone(r["acceptance"])

    def test_missing_and_invalid_acceptance_id(self):
        s = self.s
        self.assertEqual(codes(build_research_learning_acceptance(
            s["request"], s["record"], s["boundary"])), ["missing_acceptance_id"])
        self.assertEqual(codes(build_research_learning_acceptance(
            s["request"], s["record"], s["boundary"], " ")), ["invalid_acceptance_id"])

    def test_invalid_acceptance(self):
        a = self.s["acceptance"]
        for bad in (None, {}, dict(a, status="candidate"), dict(a, execution_allowed=True),
                    dict(a, evidence_count=1), dict(a, claims=a["claims"][:-1]),
                    dict(a, claims=[]), dict(a, extra=1), dict(a, version="2")):
            self.assertFalse(validate_research_learning_acceptance(bad)["valid"])
        missing = dict(a); del missing["source_id"]
        self.assertEqual(codes(validate_research_learning_acceptance(missing)), ["missing_field"])

    def test_failure_outputs_keep_flags_false(self):
        s = self.s
        failures = [match_research_sources({}, []), select_research_source({}),
                    evaluate_research_source_trust({}, {}),
                    validate_research_evidence_for_context({}, {}, {}),
                    build_research_evidence_set({}, {}, []), build_research_synthesis({}, {}),
                    build_research_learning_record({}, {}), evaluate_research_learning_boundary({}, {}),
                    build_research_learning_acceptance({}, {}, {}),
                    validate_research_learning_acceptance({})]
        for index, out in enumerate(failures):
            flags_false(self, out, "failure%d" % index)


class SafetyTests(unittest.TestCase):
    def test_chain_causes_no_io_subprocess_directory_or_network_activity(self):
        before = tree_fingerprint()
        with mock.patch.object(builtins, "open", _forbidden), \
                mock.patch.object(subprocess, "Popen", _forbidden), \
                mock.patch.object(os, "system", _forbidden), \
                mock.patch.object(os, "remove", _forbidden), \
                mock.patch.object(os, "rename", _forbidden), \
                mock.patch.object(os, "mkdir", _forbidden), \
                mock.patch.object(os, "makedirs", _forbidden), \
                mock.patch.object(os, "stat", _forbidden), \
                mock.patch.object(socket, "socket", _forbidden), \
                mock.patch.object(socket, "create_connection", _forbidden), \
                mock.patch.object(socket, "getaddrinfo", _forbidden):
            s = run_chain()
            build_research_learning_acceptance()
        self.assertEqual(s["acceptance"]["status"], "accepted")
        self.assertEqual(tree_fingerprint(), before)  # research/memory/ael/capabilities unchanged

    def test_chain_modules_import_only_research_and_copy(self):
        allowed = {"research", "copy"}
        for name in CHAIN_MODULES:
            with open(os.path.join(ROOT, "research", name + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    roots = {(node.module or "").split(".")[0]}
                else:
                    continue
                self.assertTrue(roots <= allowed, (name, roots - allowed))
                self.assertFalse(roots & FORBIDDEN_ROOTS, (name, roots))

    def test_chain_modules_use_no_io_or_dynamic_execution_calls(self):
        banned = {"open", "exec", "eval", "compile", "__import__", "input", "print", "getattr",
                  "setattr", "globals", "vars"}
        for name in CHAIN_MODULES:
            with open(os.path.join(ROOT, "research", name + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, banned, name)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {"write", "system", "popen", "connect",
                                                      "urlopen", "request", "mkdir", "makedirs"},
                                     name)

    def test_chain_does_not_link_to_core_memory_ael_or_capabilities(self):
        run_chain()
        for module in list(sys.modules):
            if module.startswith("research."):
                for attr in vars(sys.modules[module]).values():
                    origin = getattr(attr, "__module__", "") or ""
                    self.assertNotIn(origin.split(".")[0],
                                     {"core", "memory", "ael", "capabilities", "execution",
                                      "agent", "learning", "knowledge", "tools", "web"},
                                     (module, origin))

    def test_no_external_api_model_or_automatic_execution_markers(self):
        for name in CHAIN_MODULES:
            with open(os.path.join(ROOT, "research", name + ".py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            body = [n for n in tree.body if not (isinstance(n, ast.Expr)
                                                 and isinstance(n.value, ast.Constant))]
            code = ast.dump(ast.Module(body=body, type_ignores=[]))
            for token in ("anthropic", "openai", "urllib", "requests", "http", "socket",
                          "subprocess", "memory_system", "capability_system"):
                self.assertNotIn(token, code, (name, token))

    def test_no_stage_ever_allows_or_reports_execution(self):
        s = run_chain()
        for key in ("request", "source", "evidence_set", "synthesis", "record", "acceptance"):
            self.assertIs(s[key]["execution_allowed"], False)
        self.assertIs(s["boundary"]["execution_allowed"], False)
        self.assertIs(s["boundary"]["executed"], False)
        self.assertIs(s["selection"]["executed"], False)
        self.assertIs(s["trust"]["executed"], False)


if __name__ == "__main__":
    unittest.main()
