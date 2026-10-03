"""Prompt 718 - Section 6 Agent Loop / process_input wiring decision & seam audit (read-only decision stage).

Pins docs/section6_agent_loop_wiring_decision_prompt718.md against the CURRENT implementation. Nothing here wires or implements anything in
production: behavioural tests use existing public APIs on test-owned objects, and the small `prototype_routed_step()` below is TEST-OWNED code
that only proves the documented future sequence is expressible with the existing APIs and needs no change to any existing module.
Decisions: (1) one additive AgentLoop method, caller-owned declaration; (2) process_input is not a seam; (3) routing contract unchanged;
(4) payload ownership; (5) ToolRequest caller-side, after dispatch, Section 6 route only; (6) mapping stays adapter-side; (7) mixed plans
rejected; (8) Section 4 states only on the tool route; (9) plain-dict result envelope.
"""
import ast
import glob
import hashlib
import inspect
import os
import unittest

from agent import agent_loop as agent_loop_mod
from agent.agent_loop import AgentLoop
from planning import tool_step_agent_adapter as adapter_mod
from planning.plan import Plan, PlanStep
from planning.tool_step_agent_adapter import (ADAPTER_EXECUTION_NOT_AUTHORIZED, ADAPTER_INVALID_MAPPING_ARGUMENTS,
                                              ADAPTER_INVALID_PLAN_OBJECT, ADAPTER_LEGACY_STEP_STATE,
                                              ADAPTER_MALFORMED_CAPABILITY_MAPPING, STATUS_ADAPTER_COMPLETED,
                                              STATUS_ADAPTER_FAILED, STATUS_ADAPTER_REJECTED, SOURCE_PRE_START,
                                              SOURCE_TOOL_EXECUTION, execute_agent_tool_step)
from planning.tool_step_dispatch import (DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID,
                                         DISPATCH_KIND_LEGACY, DISPATCH_KIND_SECTION6_TOOL, PAYLOAD_SOURCE_LEGACY_INPUT,
                                         PAYLOAD_SOURCE_TOOL_INPUT, resolve_tool_step_dispatch)
from planning.tool_step_route import (ROUTE_CODE_EXPLICIT_LEGACY, ROUTE_CODE_EXPLICIT_SECTION6, ROUTE_CODE_FALLBACK_ABSENT,
                                      ROUTE_CODE_FALLBACK_MALFORMED, ROUTE_CODE_FALLBACK_UNKNOWN, ROUTE_LEGACY_CAPABILITY,
                                      ROUTE_SECTION6_TOOL, resolve_execution_route)
from tests.test_section6_agent_loop_handover_decision_prompt713 import (FROZEN_LEGACY_DIGEST, FROZEN_SECTION6_DIGEST, SECTION6,
                                                                        digest, legacy_plan)
from tests.test_section6_final_acceptance_prompt712 import FROZEN_SECTION45_DIGEST
from tests.test_section6_tool_step_executor_prompt708 import make_registry, req, snapshot
from tests.test_section6_tool_step_preflight_prompt709 import registry_state
from tools.tool_request import ToolRequest, create_tool_request

from tests.section6_agent_loop_baseline_prompt719c import file_bytes as _baseline_file_bytes, read_text as _baseline_read_text   # Prompt 719-C: exact-path exemption for agent/agent_loop.py, see that helper
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs",
                   "section6_agent_loop_wiring_decision_prompt718.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FROZEN_AGENT_LOOP_SHA256 = "b69e217564345cad5ae30b76fe6af97c0d6d263098ad4344954d5946b7631157"
FROZEN_CORE_SHA256 = "d5e8755b5c20b2806eabc5e0152a87db74f478c15b9139edb51e85fa5e32b841"
FROZEN_PLAN_MANAGER_SHA256 = "885b8835a48ce53e86a9a65d9d0d873d41821c8547d8c1606e6021521b686dc3"
FROZEN_ROUTE_SHA256 = "59cbce01caa0af163e7c6d3e8ec935b24ee3957b961e2bc3cd04fde5fab6d12c"
FROZEN_DISPATCH_SHA256 = "ec671db777000f96f8b5bd12df27028689f6fc24b99320dacc0c16e730230972"
FROZEN_ADAPTER_SHA256 = "e739477f9b6fe7cd71f20b6a9879a70f8ec15e0ea4fa653fcc54367b72d88216"
FROZEN_PRODUCTION_TREE = ("bf3e7ff18199e741c5f83afb9ff8746f92851715071e4be008a21f3429d0b746", 294)   # every non-test .py, sorted
S6, LEG = "section6_tool", "legacy_capability"
NAN, INF = float("nan"), float("inf")


def read(path):
    return _baseline_read_text(path)          # Prompt 719-C: agent/agent_loop.py is read without the sanctioned additions


def rel_read(rel):
    return read(os.path.join(PY_ROOT, rel))


def sha(rel):
    return hashlib.sha256(_baseline_file_bytes(rel)).hexdigest()         # Prompt 719-C: agent_loop.py read without the sanctioned additions


def production_files():
    skip = os.sep + "tests" + os.sep
    return sorted(os.path.relpath(p, PY_ROOT).replace(os.sep, "/")
                  for p in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True) if skip not in p)


def imports_of(rel):
    found = []
    for node in ast.walk(ast.parse(rel_read(rel))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


def call_names(rel):
    names = []
    for node in ast.walk(ast.parse(rel_read(rel))):
        if isinstance(node, ast.Call):
            f = node.func
            names.append(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "")
    return names


def code_strings(rel):
    """Every str constant in the module EXCLUDING docstrings (so prose that merely mentions a name does not count as use)."""
    tree = ast.parse(rel_read(rel))
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                doc_ids.add(id(first.value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids]


class Tripwire:
    """Any attribute access, comparison, hashing, repr or iteration raises: proves a payload was never inspected."""
    def __getattribute__(self, name):
        raise AssertionError("tripwire touched: " + name)

    def __eq__(self, other):
        raise AssertionError("tripwire compared")

    def __hash__(self):
        raise AssertionError("tripwire hashed")

    def __repr__(self):
        raise AssertionError("tripwire repr")


# --- the documented structured tool intent (schema from the decision doc), enforced by TEST-OWNED code only -------------------------------
INTENT_KEYS = {"plan_id", "step_id", "tool_request", "max_attempts", "required_capabilities", "capability_mapping"}
REQUEST_KEYS = {"name", "tool_input", "granted_permissions", "granted_capabilities", "confirmed"}


def check_intent(p):
    """Returns None or a stable rejection code. Exact keys, no defaults; mirrors doc section 6."""
    if type(p) is not dict or set(p) != INTENT_KEYS:
        return "INTENT_KEYS"
    if type(p["plan_id"]) is not str or not p["plan_id"] or type(p["step_id"]) is not str or not p["step_id"]:
        return "INTENT_IDS"
    tr = p["tool_request"]
    if type(tr) is not dict or set(tr) != REQUEST_KEYS:
        return "INTENT_TOOL_REQUEST_KEYS"
    if type(p["max_attempts"]) is not int:
        return "INTENT_MAX_ATTEMPTS"
    rc, cm = p["required_capabilities"], p["capability_mapping"]
    if (rc is None) != (cm is None) or (rc is not None and (type(rc) is not list or type(cm) is not list)):
        return "INTENT_MAPPING_PAIR"
    return None


def intent(plan_id, step_id="s", name="echo", tool_input=None, perms=None, caps=None, confirmed=False, max_attempts=1, rc=None, cm=None):
    return {"plan_id": plan_id, "step_id": step_id,
            "tool_request": {"name": name, "tool_input": {} if tool_input is None else tool_input,
                             "granted_permissions": [] if perms is None else perms,
                             "granted_capabilities": [] if caps is None else caps, "confirmed": confirmed},
            "max_attempts": max_attempts, "required_capabilities": rc, "capability_mapping": cm}


def prototype_routed_step(pm, registry, log, declaration=None, legacy_input=None, tool_input=None):
    """TEST-OWNED prototype of the documented Section 6 / legacy sequences (doc section 3). Not production code."""
    d = resolve_tool_step_dispatch(declaration, legacy_input, tool_input)               # once
    env = {"route": d.route, "explicit": d.explicit, "fallback": d.fallback, "dispatch_code": d.dispatch_code,
           "stage": None, "status": None, "error_code": None, "legacy_result": None, "tool_result": None}
    if d.is_rejected:
        env.update(stage="dispatch", status="rejected", error_code=d.dispatch_code)
        return env
    payload = d.payload
    if d.is_legacy_capability:
        log.append("legacy_execute_next_step")
        env.update(stage="execution", status="executed", legacy_result={"plan_id": payload["plan_id"]})
        return env
    code = check_intent(payload)
    if code:
        env.update(stage="payload", status="rejected", error_code=code)
        return env
    tr = payload["tool_request"]
    res = create_tool_request(tr["name"], tr["tool_input"], tr["granted_permissions"], tr["granted_capabilities"], tr["confirmed"])
    if not res.ok:
        env.update(stage="request", status="rejected", error_code=res.codes()[0])
        return env
    log.append("adapter")
    out = execute_agent_tool_step(pm.get_plan(payload["plan_id"]), payload["step_id"], res.request, registry, payload["max_attempts"],
                                  payload["required_capabilities"], payload["capability_mapping"])
    env.update(stage="execution", status=out.status, error_code=out.failure_code, tool_result=out.to_dict())
    return env


class TestDecisionDocument(unittest.TestCase):
    def setUp(self):
        self.text = read(DOC)

    def test_document_records_every_decision_and_required_sections(self):
        for marker in ("DECISION-1: CHOSEN ARCHITECTURE", "DECISION-2: `process_input` is NOT a seam", "DECISION-3: routing contract",
                       "DECISION-4: payload ownership", "DECISION-5: `ToolRequest` construction", "DECISION-6: capability mapping",
                       "DECISION-7: mixed-plan policy", "DECISION-8: ready/blocked and authorization", "DECISION-9: result propagation",
                       "Exact future call sequences", "`AgentLoop` seam (exact)", "`process_input` seam (exact)", "Failure propagation",
                       "Minimal production files for Prompt 719", "Non-goals of Prompt 718", "Remaining Section 6 work",
                       "Isolation points"):
            self.assertIn(marker, self.text, marker)
        self.assertIn("Nothing is implemented, nothing is wired", self.text)

    def test_document_names_existing_apis_and_each_exists(self):
        for name, obj in (("resolve_tool_step_dispatch", resolve_tool_step_dispatch), ("resolve_execution_route", resolve_execution_route),
                          ("execute_agent_tool_step", execute_agent_tool_step), ("create_tool_request", create_tool_request)):
            self.assertIn(name, self.text)
            self.assertTrue(callable(obj))
        for code in ("ADAPTER_LEGACY_STEP_STATE", "ADAPTER_INVALID_PLAN_OBJECT", "ADAPTER_EXECUTION_NOT_AUTHORIZED",
                     "ADAPTER_INVALID_MAPPING_ARGUMENTS", "ADAPTER_MALFORMED_CAPABILITY_MAPPING", "REJECTED_PAYLOAD_ABSENT",
                     "REJECTED_PAYLOAD_INVALID"):
            self.assertIn(code, self.text)
        for attr in ("ADAPTER_LEGACY_STEP_STATE", "ADAPTER_INVALID_PLAN_OBJECT", "ADAPTER_EXECUTION_NOT_AUTHORIZED",
                     "ADAPTER_INVALID_MAPPING_ARGUMENTS", "ADAPTER_MALFORMED_CAPABILITY_MAPPING"):
            self.assertTrue(hasattr(adapter_mod, attr), attr)

    def test_document_states_the_chosen_seams_and_the_two_prompt_719_files(self):
        self.assertIn("AgentLoop.execute_routed_step(declaration=None, legacy_input=None, tool_input=None, capability_system=None, tool_registry=None)",
                      self.text)
        self.assertIn("(option D: narrowly defined", self.text)
        self.assertIn("`agent/agent_loop.py`", self.text)
        self.assertIn("`agent/tool_step_intent.py`", self.text)
        self.assertIn("`core/core.py` is **not** in the Prompt 719 file list", self.text)
        section8 = self.text.split("## 8. Minimal production files for Prompt 719")[1].split("## 9.")[0]
        self.assertEqual(section8.count("\n1. **"), 1)
        self.assertEqual(section8.count("\n2. **"), 1)
        self.assertNotIn("\n3. **", section8)

    def test_document_states_ownership_and_isolation_rules(self):
        for phrase in ("caller-owned", "never inferred from tool names, capability", "natural-language wording", "presence of a registry",
                       "pure structural mapper", "An omitted key is a rejection", "call the mapping module",
                       "must not call `refresh_plan_step_statuses`", "legacy `retry_step`", "MIXED_PLAN_ROUTE_CONFLICT",
                       "ever reaches the legacy path", "byte-identical", "G1", "G6"):
            self.assertIn(phrase, self.text, phrase)

    def test_document_failure_table_covers_every_required_case(self):
        for case in ("malformed / unknown / absent declaration", "missing tool payload", "malformed tool payload",
                     "`ToolRequest` construction failure", "capability mapping failure", "preflight rejection", "tool execution failure",
                     "retry exhaustion", "invalid plan state", "legacy execution failure", "mixed-plan conflict"):
            self.assertIn(case, self.text, case)


class TestLegacyFallbackIsTheDefault(unittest.TestCase):
    def test_no_arguments_at_all_is_the_legacy_fallback(self):
        d = resolve_tool_step_dispatch()
        self.assertEqual((d.route, d.explicit, d.fallback, d.route_code), (ROUTE_LEGACY_CAPABILITY, False, True, ROUTE_CODE_FALLBACK_ABSENT))
        self.assertFalse(d.is_section6_tool)
        self.assertEqual(d.dispatch_kind, DISPATCH_KIND_LEGACY)

    def test_every_non_exact_declaration_falls_back_to_legacy_never_to_section6(self):
        values = [None, "", " ", "section6_tool ", " section6_tool", "Section6_Tool", "SECTION6_TOOL", "section6", "tool", "section6-tool",
                  "section6_tool\n", "legacy", "Legacy_Capability", "echo", "execute_agent_tool_step", 0, 1, True, False, 1.5, b"section6_tool",
                  ["section6_tool"], ("section6_tool",), {"section6_tool"}, {"route": "section6_tool"}, object(), print,
                  type("S", (str,), {})("section6_tool"), req("echo")]
        for value in values:
            r = resolve_execution_route(value)
            self.assertEqual(r.route, ROUTE_LEGACY_CAPABILITY, repr(type(value)))
            self.assertTrue(r.fallback and not r.explicit and not r.declaration_valid)
            d = resolve_tool_step_dispatch(value, {"plan_id": "p"}, {"plan_id": "p"})
            self.assertEqual((d.route, d.payload_source), (ROUTE_LEGACY_CAPABILITY, PAYLOAD_SOURCE_LEGACY_INPUT))

    def test_explicit_legacy_declaration_is_legacy_and_not_a_fallback(self):
        d = resolve_tool_step_dispatch(LEG, {"plan_id": "p"}, None)
        self.assertEqual((d.route, d.explicit, d.fallback, d.route_code, d.is_ready), (LEG, True, False, ROUTE_CODE_EXPLICIT_LEGACY, True))
        self.assertEqual(d.payload, {"plan_id": "p"})

    def test_fallback_without_legacy_input_is_rejected_on_the_legacy_route_not_rerouted(self):
        d = resolve_tool_step_dispatch(None, None, {"plan_id": "p", "step_id": "s"})
        self.assertEqual((d.route, d.dispatch_code, d.payload), (LEG, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT, None))
        self.assertEqual(d.dispatch_kind, DISPATCH_KIND_LEGACY)


class TestExplicitSection6IsTheOnlyWayIntoTheToolPath(unittest.TestCase):
    def test_exactly_one_string_selects_section6(self):
        d = resolve_tool_step_dispatch(S6, None, {"plan_id": "p"})
        self.assertEqual((d.route, d.explicit, d.fallback, d.route_code), (S6, True, False, ROUTE_CODE_EXPLICIT_SECTION6))
        self.assertEqual((d.dispatch_kind, d.payload_source, d.is_ready), (DISPATCH_KIND_SECTION6_TOOL, PAYLOAD_SOURCE_TOOL_INPUT, True))

    def test_route_is_section6_iff_declaration_is_exactly_the_string(self):
        for value in (S6, LEG, None, "x", 1, [S6], "", S6.upper(), S6 + " "):
            self.assertEqual(resolve_execution_route(value).is_section6_tool, value == S6 and type(value) is str)

    def test_section6_route_never_downgrades_to_legacy_whatever_the_payloads_are(self):
        good_legacy = {"plan_id": "p"}
        for tool_input in (None, {"plan_id": "p", "step_id": "s"}, (1, 2), {1: 2}, {"x": NAN}, {"x": INF}, object(), lambda: 1, {"k": {1, 2}},
                           b"bytes", set(), req("echo")):
            d = resolve_tool_step_dispatch(S6, good_legacy, tool_input)
            self.assertEqual(d.route, S6, repr(type(tool_input)))
            self.assertTrue(d.is_section6_tool and not d.is_legacy_capability)
            self.assertEqual(d.dispatch_kind, DISPATCH_KIND_SECTION6_TOOL)
            self.assertEqual(d.payload_source, PAYLOAD_SOURCE_TOOL_INPUT)

    def test_no_route_argument_exists_on_the_adapter_or_on_the_legacy_agent_loop_entry_points(self):
        self.assertEqual(list(inspect.signature(execute_agent_tool_step).parameters),
                         ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities", "capability_mapping", "attempt_log"])
        self.assertEqual(list(inspect.signature(AgentLoop.run).parameters), ["self", "goal_id", "plan_id", "max_iterations"])
        self.assertEqual(list(inspect.signature(AgentLoop.execute_next_step).parameters), ["self", "plan_id", "capability_system"])


class TestRouteCannotBeInferred(unittest.TestCase):
    def test_tool_like_payload_without_declaration_does_not_reach_the_tool_route(self):
        tool_like = intent("p", "s", "echo")
        d = resolve_tool_step_dispatch(None, None, tool_like)
        self.assertEqual((d.route, d.dispatch_kind, d.dispatch_code), (LEG, DISPATCH_KIND_LEGACY, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT))
        self.assertIsNone(d.payload)

    def test_tool_like_payload_passed_as_legacy_input_is_only_a_legacy_payload(self):
        for declaration in (None, LEG):
            d = resolve_tool_step_dispatch(declaration, intent("p", "s", "echo"), None)
            self.assertEqual((d.route, d.payload_source), (LEG, PAYLOAD_SOURCE_LEGACY_INPUT))
            self.assertFalse(d.is_section6_tool)

    def test_tool_name_capability_name_and_permission_words_never_select_a_route(self):
        for word in ("echo", "net", "network", "cap_a", "needs_cap", "user_confirmation", "tool", "execute_agent_tool_step", "ToolRequest"):
            self.assertEqual(resolve_execution_route(word).route, LEG, word)
            self.assertEqual(resolve_tool_step_dispatch(word, None, intent("p")).route, LEG, word)

    def test_a_toolrequest_object_or_registry_is_never_a_route_and_never_a_valid_payload(self):
        reg, _ = make_registry()
        for obj in (req("echo"), reg):
            self.assertEqual(resolve_execution_route(obj).code, ROUTE_CODE_FALLBACK_MALFORMED)
            d = resolve_tool_step_dispatch(S6, None, obj)
            self.assertEqual((d.route, d.dispatch_code), (S6, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID))

    def test_plan_contents_and_natural_language_are_never_consulted(self):
        pm, plan, a, _ = legacy_plan()
        text_like = "please run the echo tool on step " + a + " using section6_tool"
        for declaration in (text_like, plan, plan.steps[0], {"plan": plan.plan_id}):
            self.assertEqual(resolve_execution_route(declaration).route, LEG)
        self.assertEqual(resolve_tool_step_dispatch(None, None, None).route, LEG)

    def test_unknown_and_malformed_codes_are_distinct_but_both_legacy(self):
        self.assertEqual(resolve_execution_route("nope").code, ROUTE_CODE_FALLBACK_UNKNOWN)
        self.assertEqual(resolve_execution_route(5).code, ROUTE_CODE_FALLBACK_MALFORMED)


class TestLegacyPayloadCannotActivateSection6(unittest.TestCase):
    def test_a_valid_legacy_payload_never_turns_into_a_section6_dispatch(self):
        legacy_payload = {"plan_id": "p"}
        for declaration in (None, LEG, "x", 7):
            d = resolve_tool_step_dispatch(declaration, legacy_payload, None)
            self.assertEqual(d.route, LEG)
            self.assertFalse(d.is_section6_tool)
        d = resolve_tool_step_dispatch(S6, legacy_payload, None)
        self.assertEqual((d.route, d.dispatch_code, d.payload), (S6, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT, None))

    def test_a_section6_dispatch_never_returns_or_copies_the_legacy_payload(self):
        d = resolve_tool_step_dispatch(S6, {"plan_id": "LEGACY-ONLY"}, {"plan_id": "p"})
        self.assertNotIn("LEGACY-ONLY", repr(d.payload))
        self.assertNotIn("LEGACY-ONLY", repr(d.as_dict()))

    def test_legacy_route_never_inspects_the_tool_payload_and_section6_never_inspects_the_legacy_payload(self):
        self.assertTrue(resolve_tool_step_dispatch(LEG, {"plan_id": "p"}, Tripwire()).is_ready)
        self.assertTrue(resolve_tool_step_dispatch(None, {"plan_id": "p"}, Tripwire()).is_ready)
        self.assertTrue(resolve_tool_step_dispatch(S6, Tripwire(), {"plan_id": "p"}).is_ready)


class TestMalformedToolPayloadCannotCauseFallback(unittest.TestCase):
    def test_absent_and_non_json_safe_tool_payloads_are_rejected_on_the_section6_route(self):
        expectations = ((None, DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT), ((1,), DISPATCH_CODE_REJECTED_PAYLOAD_INVALID),
                        ({"a": NAN}, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID), ({1: "x"}, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID),
                        (object(), DISPATCH_CODE_REJECTED_PAYLOAD_INVALID), ({"a": {"b": {1}}}, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID))
        for bad, code in expectations:
            d = resolve_tool_step_dispatch(S6, {"plan_id": "p"}, bad)
            self.assertEqual((d.route, d.dispatch_code, d.is_rejected, d.payload), (S6, code, True, None))

    def test_non_finite_numbers_are_rejected_at_dispatch_for_the_tool_route_never_sanitised(self):
        for bad in (NAN, INF, -INF):
            d = resolve_tool_step_dispatch(S6, None, intent("p", tool_input={"x": bad}))
            self.assertEqual((d.route, d.dispatch_code), (S6, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID))

    def test_json_safe_but_wrong_shaped_intents_are_rejected_by_the_documented_schema_not_defaulted(self):
        good = intent("p", "s")
        self.assertIsNone(check_intent(good))
        broken = []
        for key in INTENT_KEYS:
            bad = dict(good)
            del bad[key]
            broken.append(bad)
        broken.append(dict(good, extra=1))
        for key in REQUEST_KEYS:
            bad = dict(good, tool_request=dict(good["tool_request"]))
            del bad["tool_request"][key]
            broken.append(bad)
        broken += [dict(good, plan_id=""), dict(good, step_id=5), dict(good, max_attempts="1"), dict(good, required_capabilities=["a"]),
                   dict(good, capability_mapping=[]), dict(good, tool_request="echo"), [], {}, "x"]
        for bad in broken:
            d = resolve_tool_step_dispatch(S6, None, bad)
            if d.is_ready:
                self.assertIsNotNone(check_intent(d.payload), bad)
            self.assertEqual(d.route, S6)

    def test_every_malformed_intent_stops_before_any_request_or_adapter_call(self):
        pm, plan, a, _ = legacy_plan()
        reg, handlers = make_registry()
        for bad in (None, {}, {"plan_id": plan.plan_id}, dict(intent(plan.plan_id, a), extra=1), {"x": NAN}):
            log = []
            env = prototype_routed_step(pm, reg, log, S6, {"plan_id": plan.plan_id}, bad)
            self.assertEqual((env["route"], env["status"]), (S6, "rejected"))
            self.assertIn(env["stage"], ("dispatch", "payload"))
            self.assertEqual(log, [])                                        # neither the legacy branch nor the adapter was reached
        self.assertEqual((handlers["echo"].count, reg.invocation_count()), (0, 0))


class TestLegacyPathIsIsolated(unittest.TestCase):
    def test_agent_loop_has_no_tool_or_dispatch_awareness(self):
        text = rel_read("agent/agent_loop.py")
        for token in ("tool_step", "tool_capability_mapping", "resolve_tool_step_dispatch", "resolve_execution_route", "execute_agent_tool_step",
                      "create_tool_request", "ToolRequest", "section6_tool", "legacy_capability", "InProcessToolRegistry", "execute_routed_step"):
            self.assertNotIn(token, text, token)
        for mod in imports_of("agent/agent_loop.py"):
            self.assertNotEqual(mod.split(".")[0], "tools", mod)
            self.assertNotIn("tool_step", mod)

    def test_no_agent_package_module_imports_tools_or_section6_today(self):
        for path in glob.glob(os.path.join(PY_ROOT, "agent", "*.py")):
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            for mod in imports_of(rel):
                if rel == "agent/tool_step_intent.py":      # Prompt 719-A: the one sanctioned caller-side adapter; it may import ONLY the request factory
                    self.assertIn(mod, ("math", "tools.tool_request"), rel)
                    continue
                if rel == "agent/tool_step_runner.py":      # Prompt 719-B: the caller-side runner may import ONLY the intent result type and the 711 retry layer
                    self.assertIn(mod, ("agent.tool_step_intent", "planning.tool_step_retry"), rel)
                    continue
                self.assertNotEqual(mod.split(".")[0], "tools", rel)
                self.assertNotIn("tool_step", mod, rel)
                self.assertNotIn("tool_capability_mapping", mod, rel)

    def test_execution_stack_is_untouched_and_unaware(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")))
        files.append("agent/agent_loop.py")
        self.assertEqual((digest(files), len(files)), (FROZEN_LEGACY_DIGEST, 27))
        for rel in files:
            for token in ("tool_step", "section6", "resolve_execution_route", "DispatchResolutionResult"):
                self.assertNotIn(token, rel_read(rel), (rel, token))

    def test_legacy_plan_flow_is_unchanged_by_the_existence_of_the_dispatch_layer(self):
        # the legacy PlanManager rewrite to ready/blocked is exactly what it always was; the dispatch layer plays no part in it
        pm, plan, a, b = legacy_plan()
        self.assertEqual([s.status for s in plan.steps], ["pending", "pending"])
        resolve_tool_step_dispatch(S6, None, intent(plan.plan_id, a))
        self.assertEqual([s.status for s in plan.steps], ["pending", "pending"])
        pm.refresh_plan_step_statuses(plan.plan_id, None)
        self.assertEqual([s.status for s in plan.steps], ["ready", "blocked"])

    def test_legacy_retry_step_is_not_part_of_any_section6_module(self):
        for rel in ("planning/tool_step_retry.py", "planning/tool_step_agent_adapter.py", "planning/tool_step_dispatch.py",
                    "planning/tool_step_route.py", "planning/tool_step_executor.py", "planning/tool_step_bridge.py"):
            self.assertNotIn("retry_step", rel_read(rel), rel)

    def test_legacy_path_never_constructs_a_toolrequest(self):
        for rel in ("agent/agent_loop.py", "core/core.py"):
            self.assertNotIn("create_tool_request", call_names(rel), rel)
            self.assertNotIn("ToolRequest", call_names(rel), rel)


class TestToolRequestRemainsCallerSide(unittest.TestCase):
    def test_only_the_intended_modules_contain_a_create_tool_request_call_today(self):
        callers = [rel for rel in production_files() if "create_tool_request" in call_names(rel)]
        self.assertEqual(callers, ["agent/tool_step_intent.py"])          # Prompt 719-A: only the caller-side intent adapter builds a ToolRequest (tests and docs do too)

    def test_route_dispatch_adapter_agent_loop_and_core_never_build_a_toolrequest(self):
        for rel in ("planning/tool_step_route.py", "planning/tool_step_dispatch.py", "planning/tool_step_agent_adapter.py",
                    "agent/agent_loop.py", "core/core.py"):
            names = call_names(rel)
            self.assertNotIn("create_tool_request", names, rel)
            self.assertNotIn("ToolRequest", names, rel)

    def test_dispatch_returns_plain_data_never_a_toolrequest(self):
        d = resolve_tool_step_dispatch(S6, None, intent("p", "s"))
        self.assertIs(type(d.payload), dict)
        self.assertIs(type(d.payload["tool_request"]), dict)
        self.assertNotIsInstance(d.payload["tool_request"], ToolRequest)
        self.assertNotIn("ToolRequest", repr(d))

    def test_direct_toolrequest_construction_is_refused_so_the_factory_is_the_only_builder(self):
        with self.assertRaises(TypeError):
            ToolRequest("echo", {}, (), (), False)

    def test_create_tool_request_defaults_are_why_the_builder_must_require_all_five_fields(self):
        res = create_tool_request("echo", {})
        self.assertTrue(res.ok)
        args = res.request.to_registry_arguments()
        self.assertEqual((list(args["granted_permissions"]), list(args["granted_capabilities"]), args["confirmed"]), ([], [], False))
        # omitting a field silently yields "no grants / not confirmed": the documented builder therefore rejects an omitted key instead
        partial = intent("p")
        del partial["tool_request"]["granted_permissions"]
        self.assertEqual(check_intent(partial), "INTENT_TOOL_REQUEST_KEYS")

    def test_the_adapter_rejects_a_non_toolrequest_and_never_builds_one(self):
        pm, plan, a, _ = legacy_plan()
        reg, handlers = make_registry()
        before = snapshot(plan)
        out = execute_agent_tool_step(plan, a, {"name": "echo", "tool_input": {}}, reg, 1)
        self.assertEqual((out.status, out.execution_started, snapshot(plan)), (STATUS_ADAPTER_REJECTED, False, before))
        self.assertEqual((handlers["echo"].count, reg.invocation_count()), (0, 0))

    def test_permissions_capabilities_and_confirmation_come_only_from_the_payload_fields(self):
        pm, plan, a, _ = legacy_plan()
        reg, handlers = make_registry()
        # nothing supplied -> Section 5 refuses; the routing layer grants nothing on its own, even for a tool that "needs" a permission
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a, "net"))
        self.assertEqual(env["status"], STATUS_ADAPTER_REJECTED)
        self.assertEqual(env["tool_result"]["failure_source"], SOURCE_PRE_START)
        self.assertEqual(handlers["net"].count, 0)
        # the caller supplies the grant explicitly -> it runs
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a, "net", perms=["network"]))
        self.assertEqual(env["status"], STATUS_ADAPTER_COMPLETED)
        self.assertEqual(handlers["net"].count, 1)


class TestDocumentedSequenceIsExpressibleWithExistingApis(unittest.TestCase):
    """Proves (with test-owned glue) that the doc's Section 6 and legacy sequences need no change to any existing module."""

    def test_section6_route_success_end_to_end(self):
        pm, plan, a, b = legacy_plan()
        reg, handlers = make_registry()
        log = []
        env = prototype_routed_step(pm, reg, log, S6, None, intent(plan.plan_id, a, "echo", {"k": [1, 2]}, max_attempts=2))
        self.assertEqual((env["route"], env["explicit"], env["fallback"], env["stage"], env["status"]), (S6, True, False, "execution", "completed"))
        self.assertEqual(log, ["adapter"])
        self.assertIsNone(env["legacy_result"])
        self.assertEqual(env["tool_result"]["final_step_state"], "completed")
        self.assertEqual(handlers["echo"].count, 1)
        self.assertEqual(reg.invocation_count(), 1)

    def test_legacy_route_reaches_only_the_legacy_branch(self):
        pm, plan, a, _ = legacy_plan()
        reg, handlers = make_registry()
        for declaration in (None, LEG, "bogus", 3):
            log = []
            env = prototype_routed_step(pm, reg, log, declaration, {"plan_id": plan.plan_id}, intent(plan.plan_id, a))
            self.assertEqual((env["route"], env["stage"], env["status"]), (LEG, "execution", "executed"))
            self.assertEqual(log, ["legacy_execute_next_step"])
            self.assertIsNone(env["tool_result"])
        self.assertEqual((handlers["echo"].count, reg.invocation_count()), (0, 0))
        self.assertEqual([s.status for s in plan.steps], ["pending", "pending"])

    def test_dispatch_is_called_exactly_once_per_routed_call(self):
        import planning.tool_step_dispatch as dispatch_mod
        calls = []
        original = dispatch_mod.resolve_execution_route
        dispatch_mod.resolve_execution_route = lambda declaration=None: (calls.append(declaration), original(declaration))[1]
        try:
            resolve_tool_step_dispatch(S6, None, {"a": 1})
            resolve_tool_step_dispatch(None, {"a": 1}, None)
        finally:
            dispatch_mod.resolve_execution_route = original
        self.assertEqual(calls, [S6, None])

    def test_capability_mapping_is_applied_inside_the_adapter_from_payload_fields_only(self):
        pm, plan, a, _ = legacy_plan()
        reg, handlers = make_registry()
        mapping = [{"capability": "file_reader", "grants": ["cap_a"]}]
        ok = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a, "needs_cap", caps=["cap_a"], rc=["file_reader"], cm=mapping))
        self.assertEqual(ok["status"], STATUS_ADAPTER_COMPLETED)
        self.assertEqual(handlers["needs_cap"].count, 1)


class TestFailurePropagation(unittest.TestCase):
    def setUp(self):
        self.pm, self.plan, self.a, self.b = legacy_plan()
        self.reg, self.handlers = make_registry()
        self.before = snapshot(self.plan)
        self.reg_before = registry_state(self.reg)

    def assert_nothing_started(self, env):
        self.assertEqual(env["status"], STATUS_ADAPTER_REJECTED)
        self.assertEqual(snapshot(self.plan), self.before)
        self.assertEqual(registry_state(self.reg), self.reg_before)
        self.assertEqual(sum(h.count for h in self.handlers.values()), 0)

    def test_missing_tool_payload_is_rejected_on_the_section6_route_and_never_runs_legacy(self):
        log = []
        env = prototype_routed_step(self.pm, self.reg, log, S6, {"plan_id": self.plan.plan_id}, None)
        self.assertEqual((env["route"], env["stage"], env["error_code"]), (S6, "dispatch", DISPATCH_CODE_REJECTED_PAYLOAD_ABSENT))
        self.assertEqual(log, [])
        self.assert_nothing_started(env)

    def test_malformed_tool_payload_is_rejected_on_the_section6_route_and_never_runs_legacy(self):
        log = []
        env = prototype_routed_step(self.pm, self.reg, log, S6, {"plan_id": self.plan.plan_id}, {"plan_id": self.plan.plan_id})
        self.assertEqual((env["route"], env["stage"], env["error_code"]), (S6, "payload", "INTENT_KEYS"))
        self.assertEqual(log, [])
        self.assert_nothing_started(env)

    def test_toolrequest_construction_failure_never_reaches_the_adapter(self):
        for kwargs in ({"name": "Bad Name"}, {"perms": ["not_a_permission"]}, {"caps": ["Bad Cap"]}, {"confirmed": "yes"},
                       {"tool_input": {"a": 1}, "name": ""}):
            log = []
            env = prototype_routed_step(self.pm, self.reg, log, S6, None, intent(self.plan.plan_id, self.a, **kwargs))
            self.assertEqual((env["route"], env["stage"]), (S6, "request"), kwargs)
            self.assertTrue(env["error_code"].startswith("INVALID_TOOL_REQUEST_"), kwargs)
            self.assertEqual(log, [])
            self.assert_nothing_started(env)

    def test_capability_mapping_failures_are_reported_by_the_adapter_before_any_start(self):
        cases = ((dict(rc=["x"], cm=None), ADAPTER_INVALID_MAPPING_ARGUMENTS), (dict(rc=["x"], cm=[{"capability": "x"}]),
                                                                              ADAPTER_MALFORMED_CAPABILITY_MAPPING))
        for kwargs, code in cases:
            if (kwargs["rc"] is None) != (kwargs["cm"] is None):
                self.assertEqual(check_intent(intent(self.plan.plan_id, self.a, "echo", **kwargs)), "INTENT_MAPPING_PAIR")   # schema layer first
            out = execute_agent_tool_step(self.plan, self.a, create_tool_request("echo", {}).request, self.reg, 1, kwargs["rc"], kwargs["cm"])
            self.assertEqual((out.status, out.failure_code, out.execution_started), (STATUS_ADAPTER_REJECTED, code, False))
            self.assertEqual(snapshot(self.plan), self.before)
        self.assertEqual(registry_state(self.reg), self.reg_before)

    def test_unmapped_capability_is_a_pre_start_rejection_and_nothing_is_inferred(self):
        env = prototype_routed_step(self.pm, self.reg, [], S6, None, intent(self.plan.plan_id, self.a, "needs_cap", caps=["cap_a"], rc=["unknown_cap"],
                                                                            cm=[{"capability": "file_reader", "grants": ["cap_a"]}]))
        self.assertEqual(env["status"], STATUS_ADAPTER_REJECTED)
        self.assertEqual(env["tool_result"]["failure_source"], SOURCE_PRE_START)
        self.assertFalse(env["tool_result"]["execution_started"])
        self.assertEqual(self.handlers["needs_cap"].count, 0)

    def test_preflight_rejection_is_pre_start_and_leaves_the_step_pending(self):
        for name in ("net", "confirm", "needs_cap", "off"):
            env = prototype_routed_step(self.pm, self.reg, [], S6, None, intent(self.plan.plan_id, self.a, name))
            self.assertEqual((env["status"], env["tool_result"]["failure_source"], env["tool_result"]["execution_started"]),
                             (STATUS_ADAPTER_REJECTED, SOURCE_PRE_START, False), name)
            self.assertEqual(self.handlers[name].count, 0)
        self.assertEqual([s.status for s in self.plan.steps], ["pending", "pending"])

    def test_retry_exhaustion_is_bounded_by_the_callers_max_attempts_and_never_uses_legacy_retry(self):
        env = prototype_routed_step(self.pm, self.reg, [], S6, None, intent(self.plan.plan_id, self.a, "net", max_attempts=3))
        self.assertEqual(env["status"], STATUS_ADAPTER_REJECTED)
        self.assertLessEqual(env["tool_result"]["attempt_count"], 3)
        self.assertIsNotNone(env["tool_result"]["retry_stop_reason"])
        self.assertEqual([s.status for s in self.plan.steps], ["pending", "pending"])

    def test_tool_execution_failure_is_terminal_and_not_retried(self):
        env = prototype_routed_step(self.pm, self.reg, [], S6, None, intent(self.plan.plan_id, self.a, "boom", max_attempts=5))
        self.assertEqual((env["status"], env["tool_result"]["failure_source"], env["tool_result"]["execution_started"],
                          env["tool_result"]["final_step_state"], env["tool_result"]["attempt_count"]),
                         (STATUS_ADAPTER_FAILED, SOURCE_TOOL_EXECUTION, True, "failed", 1))
        self.assertEqual(self.handlers["boom"].count, 1)
        again = prototype_routed_step(self.pm, self.reg, [], S6, None, intent(self.plan.plan_id, self.a, "echo"))
        self.assertEqual(again["status"], STATUS_ADAPTER_REJECTED)          # a failed step is terminal; the adapter never re-runs it
        self.assertEqual(self.handlers["echo"].count, 0)

    def test_invalid_plan_state_unknown_plan_and_missing_authorization_are_adapter_rejections(self):
        env = prototype_routed_step(self.pm, self.reg, [], S6, None, intent("no-such-plan", self.a))
        self.assertEqual((env["status"], env["error_code"]), (STATUS_ADAPTER_REJECTED, ADAPTER_INVALID_PLAN_OBJECT))
        self.plan.metadata["execution_authorized"] = False
        env = prototype_routed_step(self.pm, self.reg, [], S6, None, intent(self.plan.plan_id, self.a))
        self.assertEqual((env["status"], env["error_code"]), (STATUS_ADAPTER_REJECTED, ADAPTER_EXECUTION_NOT_AUTHORIZED))
        self.assertEqual(sum(h.count for h in self.handlers.values()), 0)

    def test_failures_after_an_explicit_section6_selection_never_invoke_the_legacy_branch(self):
        payloads = (None, {}, intent(self.plan.plan_id, self.a, "Bad Name"), intent(self.plan.plan_id, self.a, "boom"),
                    intent(self.plan.plan_id, self.a, "net"), intent("nope", self.a))
        for payload in payloads:
            log = []
            env = prototype_routed_step(self.pm, self.reg, log, S6, {"plan_id": self.plan.plan_id}, payload)
            self.assertEqual(env["route"], S6)
            self.assertNotIn("legacy_execute_next_step", log)
            self.assertIsNone(env["legacy_result"])


class TestMixedPlanPolicy(unittest.TestCase):
    def test_a_plan_the_legacy_stack_rewrote_is_rejected_by_the_adapter_before_any_start(self):
        pm, plan, a, b = legacy_plan()
        reg, handlers = make_registry()
        pm.refresh_plan_step_statuses(plan.plan_id, None)
        before, reg_before = snapshot(plan), registry_state(reg)
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a))
        self.assertEqual((env["status"], env["error_code"]), (STATUS_ADAPTER_REJECTED, ADAPTER_LEGACY_STEP_STATE))
        self.assertEqual((snapshot(plan), registry_state(reg), handlers["echo"].count), (before, reg_before, 0))

    def test_a_tool_completed_step_followed_by_a_legacy_refresh_is_silently_converted_which_is_why_a_guard_is_needed(self):
        pm, plan, a, b = legacy_plan()
        reg, handlers = make_registry()
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a))
        self.assertEqual(env["status"], STATUS_ADAPTER_COMPLETED)
        self.assertEqual([s.status for s in plan.steps], ["completed", "pending"])
        pm.refresh_plan_step_statuses(plan.plan_id, None)                 # what the legacy stack would do to this plan
        self.assertEqual([s.status for s in plan.steps], ["completed", "ready"])
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, b))
        self.assertEqual((env["status"], env["error_code"]), (STATUS_ADAPTER_REJECTED, ADAPTER_LEGACY_STEP_STATE))
        self.assertEqual(handlers["echo"].count, 1)                       # only the first, genuine tool step ever ran

    def test_no_per_step_or_per_plan_route_marker_exists_so_the_guard_cannot_be_stateless(self):
        self.assertEqual(PlanStep.__slots__, ("step_id", "description", "dependencies", "required_capabilities", "expected_output", "status",
                                              "input_data", "output_data"))
        pm, plan, a, _ = legacy_plan()
        reg, _ = make_registry()
        prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a))
        for key in plan.metadata:
            self.assertNotIn("route", key.lower())
        self.assertFalse(any("route" in s.lower() for s in Plan.__slots__) if hasattr(Plan, "__slots__") else False)

    def test_direct_agent_loop_entry_points_have_no_guard_today_which_is_the_documented_residual_gap(self):
        self.assertTrue(hasattr(AgentLoop, "execute_routed_step"))      # Prompt 719-C: the one sanctioned additive method now exists (exact name; see test_section6_agent_loop_routed_step_prompt719c)
        self.assertNotIn("_plan_routes", inspect.getsource(AgentLoop))  # still true: no route pin / mixed-plan guard exists (documented residual gap G1)

    def test_the_route_guard_design_is_expressible_and_rejects_before_any_start(self):
        """Test-owned model of the documented in-memory `plan_id -> route` pin: written only when a step starts."""
        pins = {}

        def guarded(route, plan_id, started):
            if pins.get(plan_id, route) != route:
                return "MIXED_PLAN_ROUTE_CONFLICT"
            if started:
                pins[plan_id] = route
            return None
        self.assertIsNone(guarded(S6, "p", False))          # a rejected/unstarted call pins nothing
        self.assertIsNone(guarded(LEG, "p", True))          # legacy actually started
        self.assertEqual(guarded(S6, "p", True), "MIXED_PLAN_ROUTE_CONFLICT")
        self.assertIsNone(guarded(S6, "other", True))       # a different plan is independent
        self.assertIsNone(guarded(LEG, "p", True))          # same route again is fine

    def test_section6_and_legacy_never_share_a_plan_state_vocabulary(self):
        text = rel_read("planning/tool_step_agent_adapter.py")
        self.assertIn('LEGACY_STEP_STATES = ("ready", "blocked")', text)
        self.assertEqual(adapter_mod.LEGACY_STEP_STATES, ("ready", "blocked"))


class TestReadyBlockedAndAuthorizationBoundary(unittest.TestCase):
    def test_execution_authorized_is_read_only_by_the_adapter_layer_among_routing_modules(self):
        for rel in ("planning/tool_step_route.py", "planning/tool_step_dispatch.py"):
            self.assertNotIn("execution_authorized", code_strings(rel), rel)          # docstring prose may name it; code never reads it
            self.assertNotIn("execution_authorized", [n.attr for n in ast.walk(ast.parse(rel_read(rel))) if isinstance(n, ast.Attribute)], rel)
        self.assertIn("execution_authorized", code_strings("planning/tool_step_agent_adapter.py"))
        self.assertNotIn("execution_authorized", rel_read("agent/agent_loop.py"))

    def test_execution_authorization_is_explicit_and_caller_owned(self):
        pm, plan, a, _ = legacy_plan()
        reg, handlers = make_registry()
        plan.metadata["execution_authorized"] = False
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a))
        self.assertEqual(env["error_code"], ADAPTER_EXECUTION_NOT_AUTHORIZED)
        plan.metadata["execution_authorized"] = 1                          # truthy is not True: rejected (by plan validation or stage d)
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a))
        self.assertEqual(env["status"], STATUS_ADAPTER_REJECTED)
        self.assertIn(env["error_code"], (ADAPTER_EXECUTION_NOT_AUTHORIZED, "ADAPTER_INCONSISTENT_STEP_STATE", "ADAPTER_INVALID_PLAN"))
        self.assertEqual(handlers["echo"].count, 0)

    def test_ready_and_blocked_labels_are_rejected_never_converted_or_repaired(self):
        pm, plan, a, b = legacy_plan()
        reg, handlers = make_registry()
        pm.refresh_plan_step_statuses(plan.plan_id, None)
        self.assertEqual([s.status for s in plan.steps], ["ready", "blocked"])
        for step_id in (a, b):
            env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, step_id))
            self.assertEqual(env["error_code"], ADAPTER_LEGACY_STEP_STATE)
        self.assertEqual([s.status for s in plan.steps], ["ready", "blocked"])      # untouched: not converted, not repaired
        self.assertEqual((handlers["echo"].count, reg.invocation_count()), (0, 0))

    def test_section6_tool_path_uses_section4_states_pending_in_progress_completed_failed_only(self):
        pm, plan, a, b = legacy_plan()
        reg, _ = make_registry()
        self.assertEqual({s.status for s in plan.steps}, {"pending"})
        prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, a))
        self.assertEqual([s.status for s in plan.steps], ["completed", "pending"])
        prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, b, "boom"))
        self.assertEqual([s.status for s in plan.steps], ["completed", "failed"])

    def test_no_section6_module_calls_any_plan_manager_refresh_or_legacy_coordinator(self):
        for rel in ("planning/tool_step_route.py", "planning/tool_step_dispatch.py", "planning/tool_step_agent_adapter.py",
                    "planning/tool_step_retry.py", "planning/tool_step_executor.py", "planning/tool_step_bridge.py"):
            names = set(call_names(rel))
            for forbidden in ("refresh_plan_step_statuses", "refresh_step_status", "refresh_after_step_change", "get_next_ready_step",
                              "_identify_next_step", "execute_next_step", "execute_plan", "retry_step"):
                self.assertNotIn(forbidden, names, (rel, forbidden))

    def test_unknown_step_and_step_selection_is_explicit_never_automatic(self):
        pm, plan, a, b = legacy_plan()
        reg, handlers = make_registry()
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, "no-such-step"))
        self.assertEqual(env["status"], STATUS_ADAPTER_REJECTED)
        self.assertEqual([s.status for s in plan.steps], ["pending", "pending"])
        env = prototype_routed_step(pm, reg, [], S6, None, intent(plan.plan_id, b))    # explicit later step with an unmet dependency
        self.assertEqual(env["status"], STATUS_ADAPTER_REJECTED)
        self.assertEqual(handlers["echo"].count, 0)


class TestProcessInputIsNotASeam(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(rel_read("core/core.py"))
        self.fn = [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == "process_input"]

    def test_process_input_takes_exactly_one_text_argument(self):
        self.assertEqual(len(self.fn), 1)
        self.assertEqual([a.arg for a in self.fn[0].args.args], ["self", "raw_text"])
        self.assertEqual((self.fn[0].args.vararg, self.fn[0].args.kwarg, self.fn[0].args.defaults, self.fn[0].args.kwonlyargs), (None, None, [], []))

    def test_core_imports_nothing_from_agent_or_section6_and_never_names_agent_loop(self):
        for mod in imports_of("core/core.py"):
            self.assertNotEqual(mod.split(".")[0], "agent", mod)
            self.assertNotEqual(mod.split(".")[0], "tools", mod)
            self.assertNotIn("tool_step", mod)
        text = rel_read("core/core.py")
        for token in ("AgentLoop", "agent_loop", "section6", "resolve_tool_step_dispatch", "execute_agent_tool_step", "declaration"):
            self.assertNotIn(token, text, token)

    def test_process_input_body_only_normalises_logs_parses_and_delegates_to_goal_or_ael(self):
        body_calls = {n.func.attr for n in ast.walk(self.fn[0]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertEqual(body_calls, {"normalize", "log_message", "parse", "_handle_ael", "_handle_goal_or_conversation", "add_turn"})

    def test_goal_creation_is_the_only_plan_related_thing_the_input_path_does(self):
        handler = [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == "_handle_goal_or_conversation"][0]
        calls = {n.func.attr for n in ast.walk(handler) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertEqual(calls, {"create_goal", "_format_goal_created_reply", "_handle_conversation"})
        create_goal = [n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == "create_goal"][0]
        inner = {n.func.attr for n in ast.walk(create_goal) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertEqual(inner, {"create_goal", "create_plan"})            # a Goal and an empty Plan; no step, no execution

    def test_production_code_never_instantiates_agent_loop(self):
        for rel in production_files():
            for node in ast.walk(ast.parse(rel_read(rel))):
                if isinstance(node, ast.Call):
                    f = node.func
                    self.assertNotEqual(f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else "", "AgentLoop", rel)

    def test_core_holds_its_own_step_controller_not_an_agent_loop(self):
        text = rel_read("core/core.py")
        self.assertIn("self.step_controller = StepExecutionController(", text)
        self.assertIn("def execute_first_step(", text)


class TestPayloadsAreDataAndCollaboratorsAreOutOfBand(unittest.TestCase):
    def test_objects_cannot_travel_inside_a_dispatch_payload(self):
        pm, plan, a, _ = legacy_plan()
        reg, _ = make_registry()
        for obj in (plan, plan.steps[0], pm, reg, req("echo"), lambda: 1, print, type("X", (), {})()):
            self.assertEqual(resolve_tool_step_dispatch(S6, None, {"k": obj}).dispatch_code, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)
            self.assertEqual(resolve_tool_step_dispatch(LEG, {"k": obj}, None).dispatch_code, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)

    def test_the_documented_legacy_and_tool_payload_shapes_pass_dispatch_unchanged(self):
        legacy = {"plan_id": "p"}
        tool = intent("p", "s", "echo", {"a": [1, 2.5, None, True, "x"]}, ["network"], ["cap_a"], True, 3, ["c"], [{"capability": "c", "grants": ["cap_a"]}])
        self.assertEqual(resolve_tool_step_dispatch(LEG, legacy, None).payload, legacy)
        self.assertEqual(resolve_tool_step_dispatch(S6, None, tool).payload, tool)
        self.assertIsNone(check_intent(tool))

    def test_tuples_and_sets_are_rejected_so_grants_and_mappings_must_be_lists_in_the_payload(self):
        for grants in (("network",), {"network"}, frozenset({"network"})):
            d = resolve_tool_step_dispatch(S6, None, intent("p", perms=grants))
            self.assertEqual(d.dispatch_code, DISPATCH_CODE_REJECTED_PAYLOAD_INVALID)

    def test_payload_copies_isolate_caller_data(self):
        tool = intent("p", "s")
        d = resolve_tool_step_dispatch(S6, None, tool)
        tool["tool_request"]["name"] = "mutated"
        self.assertEqual(d.payload["tool_request"]["name"], "echo")
        d.payload["tool_request"]["name"] = "changed"
        self.assertEqual(d.payload["tool_request"]["name"], "echo")


class TestNothingIsImplementedOrModifiedByThisPrompt(unittest.TestCase):
    def test_agent_loop_and_process_input_are_byte_identical_to_the_frozen_baseline(self):
        self.assertEqual(sha("agent/agent_loop.py"), FROZEN_AGENT_LOOP_SHA256)
        self.assertEqual(sha("core/core.py"), FROZEN_CORE_SHA256)
        self.assertNotIn("execute_routed_step", rel_read("agent/agent_loop.py"))
        self.assertEqual(sum(1 for n in ast.walk(ast.parse(rel_read("core/core.py"))) if isinstance(n, ast.FunctionDef) and n.name == "process_input"), 1)

    def test_execution_planning_section5_and_section6_modules_are_untouched(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")))
        files.append("agent/agent_loop.py")
        self.assertEqual((digest(files), len(files)), (FROZEN_LEGACY_DIGEST, 27))
        s45 = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
                     for f in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")) + glob.glob(os.path.join(PY_ROOT, "tools", "*.py"))
                     if not any(k in f for k in ("tool_step_", "tool_capability_mapping")))
        self.assertEqual((digest(s45), len(s45)), (FROZEN_SECTION45_DIGEST, 31))
        self.assertEqual(digest(sorted(SECTION6)), FROZEN_SECTION6_DIGEST)
        self.assertEqual(sha("planning/plan_manager.py"), FROZEN_PLAN_MANAGER_SHA256)

    def test_prompt_716_resolver_717_dispatch_and_714_adapter_are_unchanged(self):
        self.assertEqual(sha("planning/tool_step_route.py"), FROZEN_ROUTE_SHA256)
        self.assertEqual(sha("planning/tool_step_dispatch.py"), FROZEN_DISPATCH_SHA256)
        self.assertEqual(sha("planning/tool_step_agent_adapter.py"), FROZEN_ADAPTER_SHA256)

    def test_the_whole_production_tree_is_unchanged_and_no_new_production_module_exists(self):
        files = production_files()
        self.assertIn("agent/tool_step_intent.py", files)      # Prompt 719-A adds exactly this one new production module
        self.assertEqual([f for f in files if "intent" in os.path.basename(f) and f.startswith("agent/")], ["agent/tool_step_intent.py"])
        self.assertIn("agent/tool_step_runner.py", files)      # Prompt 719-B adds exactly this one further production module
        self.assertIn("voice/voice_verification_request.py", files)      # Prompt 798 (Section 10): one further exact-path exemption in the same package
        self.assertIn("voice/voice_enrollment_executor.py", files)      # Prompt 793 (Section 10): one further exact-path exemption in the same package
        self.assertIn("voice/voice_enrollment_plan.py", files)      # Prompt 792 (Section 10): one further exact-path exemption in the same package
        self.assertIn("voice/voice_enrollment_result_validator.py", files)      # Prompt 791 (Section 10): one further exact-path exemption in the same package
        self.assertIn("voice/voice_enrollment_result.py", files)      # Prompt 790 (Section 10): one further exact-path exemption in the same package
        self.assertIn("voice/voice_enrollment_request.py", files)      # Prompt 789 (Section 10): one further exact-path exemption in the same package
        self.assertIn("voice/voice_identity_profile_registry.py", files)      # Prompt 788 (Section 10): one further exact-path exemption in the same package
        self.assertIn("voice/voice_identity_profile.py", files)      # Prompt 787 (Section 10): exact-path exemption for the new, separate voice package (two files)
        self.assertIn("web/web_request_batch_summary.py", files)      # Prompt 785 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_batch.py", files)      # Prompt 784 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_pipeline.py", files)      # Prompt 783 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_dispatcher.py", files)      # Prompt 782 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_executor.py", files)      # Prompt 778 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_metadata_executor.py", files)      # Prompt 781 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_output.py", files)      # Prompt 779 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_output_validator.py", files)      # Prompt 780 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_plan.py", files)      # Prompt 777 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request_validator.py", files)      # Prompt 776 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_request.py", files)      # Prompt 775 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_resource_registry.py", files)      # Prompt 774 (Section 9): one further exact-path exemption in the same package
        self.assertIn("web/web_resource.py", files)      # Prompt 773 (Section 9): exact-path exemption for the new, separate web package (two files)
        self.assertIn("web/__init__.py", files)
        self.assertIn("multimedia/audio_asset_registry.py", files)      # Prompt 760 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/audio_asset.py", files)      # Prompt 759 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_batch_summary.py", files)      # Prompt 758 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_batch.py", files)      # Prompt 757 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_pipeline.py", files)      # Prompt 756 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_dispatcher.py", files)      # Prompt 755 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_metadata_executor.py", files)      # Prompt 754 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_output_validator.py", files)      # Prompt 753 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_output.py", files)      # Prompt 752 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_executor.py", files)      # Prompt 751 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_plan.py", files)      # Prompt 750 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_validator.py", files)      # Prompt 749 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_operation_request.py", files)      # Prompt 748 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_asset_registry.py", files)      # Prompt 747 (Section 8): one further exact-path exemption in the same package
        self.assertIn("multimedia/image_asset.py", files)      # Prompt 746 (Section 8): exact-path exemption for the new, separate multimedia package (two files)
        self.assertIn("game_creation/game_structure_registries_from_request.py", files)      # Prompt 745 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_structure_request_bridge.py", files)      # Prompt 744 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_structure_request.py", files)      # Prompt 743 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_definition_from_request.py", files)      # Prompt 742 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_structure_from_request.py", files)      # Prompt 741 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_creation_request_bridge.py", files)      # Prompt 740 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_creation_request.py", files)      # Prompt 739 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_definition_counts.py", files)      # Prompt 738 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_definition_summary.py", files)      # Prompt 737 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_definition_query_helpers.py", files)      # Prompt 736 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_definition_queries.py", files)      # Prompt 735 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_definition.py", files)      # Prompt 734 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_scene_bundle_registry.py", files)      # Prompt 733 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_scene_bundle.py", files)      # Prompt 732 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_scene_composition_registry.py", files)      # Prompt 731 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_scene_composition_validator.py", files)      # Prompt 730 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_scene_composition.py", files)      # Prompt 729 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_project_validator.py", files)      # Prompt 728 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_asset_registry.py", files)      # Prompt 727 (Section 7): two further exact-path exemptions (asset model and asset registry) in the same package
        self.assertIn("game_creation/game_asset.py", files)
        self.assertIn("game_creation/gameplay_system_registry.py", files)      # Prompt 726 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_scene_registry.py", files)      # Prompt 725 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_character_registry.py", files)      # Prompt 724 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_character.py", files)      # Prompt 723 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_scene.py", files)      # Prompt 722 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_project_structure.py", files)      # Prompt 721 (Section 7): one further exact-path exemption in the same package
        self.assertIn("game_creation/game_project.py", files)      # Prompt 720 (Section 7): exact-path exemption for the new, separate game_creation package (two files)
        files = [f for f in files if f not in ("agent/tool_step_intent.py", "agent/tool_step_runner.py", "web/__init__.py", "web/web_request.py", "web/web_request_batch.py", "web/web_request_batch_summary.py", "web/web_request_dispatcher.py", "web/web_request_executor.py", "web/web_request_metadata_executor.py", "web/web_request_output.py", "web/web_request_output_validator.py", "web/web_request_pipeline.py", "web/web_request_plan.py", "web/web_request_validator.py", "web/web_resource.py", "web/web_resource_registry.py", "multimedia/__init__.py", "multimedia/audio_asset.py", "multimedia/audio_asset_registry.py", "multimedia/audio_operation_batch.py", "multimedia/audio_operation_batch_summary.py", "multimedia/audio_operation_dispatcher.py", "multimedia/audio_operation_executor.py", "multimedia/audio_operation_metadata_executor.py", "multimedia/audio_operation_output.py", "multimedia/audio_operation_output_validator.py", "multimedia/audio_operation_pipeline.py", "multimedia/audio_operation_plan.py", "multimedia/audio_operation_request.py", "multimedia/audio_operation_validator.py", "multimedia/image_asset.py", "multimedia/image_asset_registry.py", "multimedia/image_operation_request.py", "multimedia/image_operation_validator.py", "multimedia/image_operation_plan.py", "multimedia/image_operation_executor.py", "multimedia/image_operation_output.py", "multimedia/image_operation_output_validator.py", "multimedia/image_operation_metadata_executor.py", "multimedia/image_operation_dispatcher.py", "multimedia/image_operation_pipeline.py", "multimedia/image_operation_batch.py", "multimedia/image_operation_batch_summary.py", "game_creation/__init__.py", "game_creation/game_project.py", "game_creation/game_project_structure.py", "game_creation/game_scene.py", "game_creation/game_character.py", "game_creation/game_character_registry.py", "game_creation/game_creation_request.py", "game_creation/game_creation_request_bridge.py", "game_creation/game_structure_from_request.py", "game_creation/game_structure_request.py", "game_creation/game_structure_registries_from_request.py", "game_creation/game_structure_request_bridge.py", "game_creation/game_definition_from_request.py", "game_creation/game_scene_registry.py", "game_creation/gameplay_system_registry.py", "game_creation/game_asset.py", "game_creation/game_asset_registry.py", "game_creation/game_project_validator.py", "game_creation/game_scene_bundle.py", "game_creation/game_scene_bundle_registry.py", "game_creation/game_definition.py", "game_creation/game_definition_counts.py", "game_creation/game_definition_queries.py", "game_creation/game_definition_query_helpers.py", "game_creation/game_definition_summary.py", "game_creation/game_scene_composition.py", "game_creation/game_scene_composition_registry.py", "game_creation/game_scene_composition_validator.py", "voice/__init__.py", "voice/voice_enrollment_batch.py", "voice/voice_enrollment_batch_summary.py", "voice/voice_enrollment_dispatcher.py", "voice/voice_enrollment_executor.py", "voice/voice_enrollment_pipeline.py", "voice/voice_enrollment_plan.py", "voice/voice_enrollment_request.py", "voice/voice_enrollment_result.py", "voice/voice_enrollment_result_validator.py", "voice/voice_identity_profile.py", "voice/voice_identity_profile_registry.py", "voice/voice_verification_request.py", "voice/voice_verification_request_validator.py", "voice/voice_verification_plan.py", "voice/voice_verification_profile_resolver.py", "voice/voice_verification_registry.py", "voice/voice_verification_result.py", "voice/voice_verification_executor.py", "voice/voice_verification_handoff.py", "voice/voice_verification_authorization.py", "voice/voice_verification_execution.py", "voice/voice_verification_execution_request.py", "voice/voice_verification_dispatcher.py", "voice/voice_verification_pipeline.py", "voice/voice_verification_batch.py", "voice/voice_verification_batch_summary.py", "voice/voice_verification_decision.py")]      # everything else must still be byte-identical to the Prompt 718 tree
        h = hashlib.sha256()
        for rel in files:
            h.update(rel.encode() + b"\0" + bytes.fromhex(sha(rel)))
        self.assertEqual((h.hexdigest(), len(files)), FROZEN_PRODUCTION_TREE)

    def test_only_the_two_sanctioned_modules_reference_route_or_dispatch_vocabulary(self):
        tokens = ("tool_step_dispatch", "resolve_tool_step_dispatch", "tool_step_route", "resolve_execution_route", "DispatchResolutionResult")
        self.assertEqual(sorted(rel for rel in production_files() if any(t in rel_read(rel) for t in tokens)),
                         ["planning/tool_step_dispatch.py", "planning/tool_step_route.py"])

    def test_no_package_export_or_module_level_routing_registry(self):
        for rel in ("planning/__init__.py", "agent/__init__.py", "core/__init__.py"):
            text = rel_read(rel).lower()
            self.assertNotIn("dispatch", text)
            self.assertNotIn("route", text)

    def test_prompt_718_adds_only_the_document_and_this_test_module(self):
        self.assertTrue(os.path.isfile(DOC))
        self.assertTrue(os.path.isfile(os.path.join(PY_ROOT, "tests", "test_section6_agent_loop_wiring_decision_prompt718.py")))

    def test_pristine_database_hash(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_no_pycache_or_pyc_files_in_the_project(self):
        found = []
        for root, dirs, files in os.walk(PY_ROOT):
            found += [os.path.join(root, d) for d in dirs if d == "__pycache__"]
            found += [os.path.join(root, f) for f in files if f.endswith(".pyc")]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
