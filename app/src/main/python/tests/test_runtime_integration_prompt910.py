"""
Tests for Prompt 910 - Runtime Integration Foundation.

`core/runtime_integration.py` is a read-only bridge that Core's real
`process_input()` path now feeds after every reply. These tests exercise the
real Core (isolated temp database), the real NLU / reasoning / capability
modules and, for the HTTP path, the real server handler. The only test double
is the scripted local-model runtime Prompts 406-413 already use; it is a
double, not a model, and is used only to prove the boundary is wired.

Run directly:
    python -m unittest tests.test_runtime_integration_prompt910 -v
"""

import ast
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from runtime_integration.runtime_core import RuntimeCore
from interface.server import make_handler
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT
from tests.test_local_inference_response_generation import TextRuntime

RESULT_KEYS = ["version", "status", "route", "input", "understood_input", "reasoning",
               "capability", "memory_context", "response", "local_model", "execution", "learning"]
EXECUTION_FALSE_FLAGS = ("allowed", "executed", "capability_executed", "code_modified",
                         "autonomy_chain_executable", "external_service_used")
PYTHON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(PYTHON_ROOT, "runtime_integration", "bridge.py")


class CoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.core = self.new_core("main")

    def new_core(self, name):
        base = os.path.join(self._tmp.name, name)
        os.makedirs(base, exist_ok=True)
        return RuntimeCore(memory_db_path=os.path.join(base, "m.sqlite3"),
                           skill_definitions_dir=os.path.join(base, "skills"))

    def say(self, text, core=None):
        core = core or self.core
        reply = core.process_input(text)
        return reply, core.last_runtime_result


def assert_no_execution(testcase, result):
    execution = result["execution"]
    for flag in EXECUTION_FALSE_FLAGS:
        testcase.assertIs(execution[flag], False, flag)
    testcase.assertIs(result["capability"]["execution_allowed"], False)
    testcase.assertIs(result["capability"]["executed"], False)
    reasoning = result["reasoning"]
    if reasoning.get("available"):
        testcase.assertIs(reasoning["executed"], False)
        testcase.assertIs(reasoning["next_action"]["executed"], False)


# --------------------------------------------------------------------------
class TestNormalUserMessageFlow(CoreCase):
    def test_no_result_before_the_first_message(self):
        self.assertIsNone(self.core.last_runtime_result)
        self.assertIsNone(self.core.get_last_runtime_result())

    def test_result_has_the_fixed_shape_and_is_json_safe(self):
        reply, result = self.say("What is Python?")
        self.assertIsInstance(reply, str)
        self.assertEqual(list(result), RESULT_KEYS)
        self.assertEqual(result["version"], ri.RUNTIME_RESULT_VERSION)
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_ordinary_conversation_is_enriched_and_labelled(self):
        _, result = self.say("What is Python?")
        self.assertEqual(result["status"], ri.STATUS_ENRICHED)
        self.assertEqual(result["route"], ri.ROUTE_CONVERSATION)
        self.assertEqual(result["input"]["normalized_text"], "What is Python?")
        self.assertTrue(result["input"]["valid"])
        self.assertTrue(result["understood_input"]["available"])
        self.assertEqual(result["understood_input"]["source"], "core_runtime_analysis")

    def test_the_bridge_is_refreshed_every_turn(self):
        _, first = self.say("What is Python?")
        _, second = self.say("hello")
        self.assertIsNot(first, second)
        self.assertEqual(second["response"]["source"], ri.SOURCE_SKILL)
        self.assertEqual(first["response"]["source"], ri.SOURCE_FALLBACK)

    def test_response_sources_follow_the_existing_return_points(self):
        cases = [
            ("hello", ri.SOURCE_SKILL),
            ("TEACH sun IS a star", ri.SOURCE_AEL),
            ("help me plan a trip", ri.SOURCE_GOAL),
            ("Python is a language", ri.SOURCE_LEARNED),
            ("من عرفان هستم", ri.SOURCE_PERSIAN_FACT),
            ("What is Python?", ri.SOURCE_REASONING),
            ("qwerty zzznoxyzzz unmapped concept", ri.SOURCE_FALLBACK),
        ]
        for text, source in cases:
            with self.subTest(text=text):
                _, result = self.say(text)
                self.assertEqual(result["response"]["source"], source)
                self.assertIn(source, ri.SOURCES)

    def test_persian_question_is_labelled_as_a_nlu_response(self):
        _, result = self.say("چطوری کار می‌کنی؟")
        self.assertIn(result["response"]["source"],
                      (ri.SOURCE_PERSIAN_RESPONSE, ri.SOURCE_FALLBACK))

    def test_whitespace_is_normalized_in_the_reported_input(self):
        _, result = self.say("  What   is\tPython?  ")
        self.assertEqual(result["input"]["normalized_text"], "What is Python?")

    def test_understood_input_carries_the_nlu_semantic_view(self):
        _, result = self.say("من عرفان هستم")
        understood = result["understood_input"]
        self.assertEqual(understood["intent"]["primary"], "introduce_name")
        self.assertTrue(understood["intent"]["recognized"])
        self.assertTrue(any(s["value"] == "عرفان" for s in understood["slots"]))

    def test_understanding_is_the_cores_own_analysis_not_a_second_run(self):
        calls = []
        real = self.core.persian_nlu.analyze_in_context

        def counting(text, context):
            calls.append(text)
            return real(text, context)

        with mock.patch.object(self.core.persian_nlu, "analyze_in_context", counting):
            self.core.process_input("What is Python?")
        self.assertEqual(calls, ["What is Python?"])
        self.assertEqual(self.core.last_runtime_result["understood_input"]["source"],
                         "core_runtime_analysis")


# --------------------------------------------------------------------------
class TestAELAndLearningInput(CoreCase):
    def test_ael_turn_is_routed_and_the_existing_ael_effect_is_reported(self):
        reply, result = self.say("TEACH sun IS a star")
        self.assertTrue(reply.startswith("[AEL OK]"))
        self.assertEqual(result["route"], ri.ROUTE_AEL)
        self.assertEqual(result["status"], ri.STATUS_LIMITED)
        self.assertEqual(result["response"]["source"], ri.SOURCE_AEL)
        self.assertEqual(result["execution"]["existing_runtime_effects"],
                         ["ael_program_interpreted"])
        self.assertFalse(result["understood_input"]["available"])
        self.assertEqual(result["understood_input"]["reason"], "ael_input_bypasses_nlu")
        self.assertFalse(result["reasoning"]["available"])

    def test_ael_still_does_what_it_did_and_the_bridge_adds_nothing_to_it(self):
        self.core.process_input("TEACH sun IS a star")
        self.assertIsNotNone(self.core.knowledge.get("sun"))
        self.assertEqual(self.core.nlu_context.turn_count, 0)
        assert_no_execution(self, self.core.last_runtime_result)

    def test_conversational_learning_is_reported_as_an_existing_effect(self):
        reply, result = self.say("Python is a language")
        self.assertTrue(reply.startswith("Got it, I'll remember that"))
        self.assertEqual(result["response"]["source"], ri.SOURCE_LEARNED)
        self.assertEqual(result["execution"]["existing_runtime_effects"], ["knowledge_learned"])
        assert_no_execution(self, result)

    def test_goal_creation_is_reported_as_an_existing_effect(self):
        reply, result = self.say("help me plan a trip")
        self.assertTrue(reply.startswith("[GOAL CREATED]"))
        self.assertEqual(result["route"], ri.ROUTE_GOAL)
        self.assertEqual(result["execution"]["existing_runtime_effects"],
                         ["goal_created", "empty_plan_created"])
        self.assertTrue(result["understood_input"]["available"])
        self.assertEqual(result["understood_input"]["source"], "pipeline_read_only")
        assert_no_execution(self, result)

    def test_personal_fact_storage_is_reported_but_a_question_is_not(self):
        _, stored = self.say("من عرفان هستم")
        self.assertEqual(stored["execution"]["existing_runtime_effects"], ["personal_fact_stored"])
        _, asked = self.say("اسم من چیه؟")
        if asked["response"]["source"] == ri.SOURCE_PERSIAN_FACT:
            self.assertEqual(asked["execution"]["existing_runtime_effects"], [])


# --------------------------------------------------------------------------
class TestReasoningAndPlanningIntegration(CoreCase):
    def test_ready_request_flows_through_request_plan_decision_and_boundary(self):
        _, result = self.say("من عرفان هستم")
        reasoning = result["reasoning"]
        self.assertTrue(reasoning["available"])
        self.assertEqual(reasoning["reasoning_input_status"], "ready")
        self.assertEqual(reasoning["request_status"], "ready")
        self.assertEqual(reasoning["goal"]["intent"], "introduce_name")
        self.assertEqual(reasoning["plan_status"], "ready")
        kinds = [s["kind"] for s in reasoning["plan_steps"]]
        self.assertEqual(kinds[-1], "address_goal")
        self.assertEqual(reasoning["plan_step_count"], len(reasoning["plan_steps"]))
        self.assertEqual(reasoning["decision"], "ready")
        self.assertEqual(reasoning["decision_reason"], "ready")
        self.assertEqual(reasoning["next_step"]["kind"], kinds[0])
        boundary = reasoning["capability_boundary"]
        self.assertEqual(boundary["decision_state"], "ready")
        self.assertEqual(boundary["capability_classification"], "spec_missing")
        self.assertEqual(boundary["next_stage"], "capability_definition")
        self.assertFalse(boundary["contract_valid"])

    def test_unknown_goal_asks_for_information_and_never_plans_the_goal(self):
        _, result = self.say("What is Python?")
        reasoning = result["reasoning"]
        self.assertEqual(reasoning["request_status"], "unknown")
        self.assertEqual(reasoning["decision"], "needs_information")
        self.assertEqual(reasoning["decision_reason"], "intent_unknown")
        self.assertIn("intent_unknown", reasoning["missing"])
        self.assertNotIn("address_goal", [s["kind"] for s in reasoning["plan_steps"]])
        self.assertEqual(reasoning["capability_boundary"]["next_stage"], "request_information")

    def test_reasoning_matches_calling_the_existing_modules_directly(self):
        from reasoning.reasoning_foundation import build_reasoning_request
        from reasoning.reasoning_decision import decide_reasoning
        _, result = self.say("من عرفان هستم")
        analysis = self.core.last_nlu_analysis
        request = build_reasoning_request(analysis.reasoning_input(self.core.nlu_context))
        decision = decide_reasoning(request)
        self.assertEqual(result["reasoning"]["decision"], decision["decision"])
        self.assertEqual(result["reasoning"]["request_status"], request["status"])

    def test_no_capability_contract_is_invented_from_reasoning(self):
        for text in ("من عرفان هستم", "What is Python?", "can you do code analysis?"):
            _, result = self.say(text)
            boundary = result["reasoning"]["capability_boundary"]
            self.assertFalse(boundary["contract_valid"])
            self.assertNotEqual(boundary["next_stage"], "capability_system")

    def test_nothing_is_executed_by_reasoning(self):
        for text in ("من عرفان هستم", "What is Python?"):
            _, result = self.say(text)
            assert_no_execution(self, result)

    def test_reasoning_is_unavailable_when_no_analysis_exists(self):
        _, result = self.say("TEACH sun IS a star")
        self.assertEqual(result["reasoning"],
                         {"available": False, "reason": "no_nlu_analysis_for_this_turn"})


# --------------------------------------------------------------------------
class TestMemoryAndContextPropagation(CoreCase):
    def test_turn_count_grows_and_resets_with_the_context(self):
        counts = []
        for text in ("one thing", "another thing", "a third thing"):
            _, result = self.say(text)
            counts.append(result["memory_context"]["turns_available_before"])
        self.assertEqual(counts, [0, 1, 2])
        self.core.reset_context()
        _, result = self.say("after reset")
        self.assertEqual(result["memory_context"]["turns_available_before"], 0)

    def test_relevant_turns_reported_are_the_ones_core_selected(self):
        self.say("Python is a language")
        _, result = self.say("tell me about Python")
        memory = result["memory_context"]
        self.assertTrue(memory["relevance_computed"])
        self.assertEqual(memory["relevant_turn_count"], 1)
        self.assertEqual(memory["relevant_turn_indexes"], [0])

    def test_memory_availability_and_use_are_reported_honestly(self):
        first_reply, first = self.say("zebra crossing")
        mem = first["memory_context"]
        self.assertEqual((mem["memory_available"], mem["memory_used"], mem["memory_state"]),
                         (False, False, "no_memory_available"))
        _, second = self.say("Python is a language")
        mem = second["memory_context"]  # earlier turn exists but nothing relevant
        self.assertEqual((mem["memory_available"], mem["memory_used"], mem["memory_state"]),
                         (True, False, "available_not_used"))
        _, third = self.say("tell me about Python")
        mem = third["memory_context"]
        self.assertEqual((mem["memory_available"], mem["memory_used"], mem["memory_state"]),
                         (True, True, "available_and_used"))
        self.assertEqual(mem["relevant_turn_count"], 1)
        json.dumps(third)
        for flag in EXECUTION_FALSE_FLAGS:
            self.assertIs(third["execution"][flag], False)

    def test_malformed_memory_is_handled_safely(self):
        for bad in ("junk", 5, ["x"], {"turns_available_before": "many"}):
            result = ri.build_runtime_result(
                {"raw_input": "x", "text": "hello", "route": "conversation", "memory": bad})
            mem = result["memory_context"]
            self.assertEqual((mem["memory_available"], mem["memory_used"], mem["memory_state"]),
                             (False, False, "unavailable_malformed_memory"))
            self.assertEqual(mem["turns_available_before"], 0)
        err = ri.error_runtime_result()["memory_context"]
        self.assertEqual((err["memory_available"], err["memory_used"], err["memory_state"]),
                         (False, False, "no_memory_available"))

    def test_unrelated_message_selects_no_context(self):
        self.say("Python is a language")
        _, result = self.say("zebra crossing")
        self.assertEqual(result["memory_context"]["relevant_turn_count"], 0)

    def test_reference_and_topic_are_forwarded_from_core(self):
        self.say("Python is a language")
        _, result = self.say("what about it")
        reference = result["memory_context"]["reference"]
        self.assertIsNotNone(reference)
        self.assertTrue(reference["has_reference"])
        self.assertIsInstance(result["memory_context"]["active_topic"], (str, type(None)))

    def test_relevance_is_computed_once_and_not_recomputed_by_the_bridge(self):
        self.say("Python is a language")
        calls = []
        real = self.core.get_relevant_context

        def counting(text):
            calls.append(text)
            return real(text)

        with mock.patch.object(self.core, "get_relevant_context", counting):
            self.core.process_input("tell me about Python")
        self.assertEqual(len(calls), 1)

    def test_nlu_context_turns_match_core_and_the_bridge_records_none(self):
        _, result = self.say("What is Python?")
        self.assertEqual(result["memory_context"]["nlu_turns_recorded"], 1)
        self.assertEqual(self.core.nlu_context.turn_count, 1)
        # a skill turn never reaches Core's NLU step: the bridge's read-only
        # analysis must not record it either
        _, skill = self.say("hello")
        self.assertEqual(skill["response"]["source"], ri.SOURCE_SKILL)
        self.assertEqual(skill["understood_input"]["source"], "pipeline_read_only")
        self.assertEqual(self.core.nlu_context.turn_count, 1)

    def test_bridge_leaves_memory_and_context_exactly_as_without_it(self):
        script = ["hello", "Python is a language", "tell me about Python", "TEACH sun IS a star",
                  "help me plan a trip", "من عرفان هستم", "qwerty zzznoxyzzz unmapped concept"]
        with_bridge = self.new_core("with")
        for text in script:
            with_bridge.process_input(text)
        without = self.new_core("without")
        with mock.patch.object(ri, "build_runtime_result", side_effect=RuntimeError("off")):
            for text in script:
                without.process_input(text)
        self.assertEqual(with_bridge.memory.counts(), without.memory.counts())
        self.assertEqual(with_bridge.get_recent_turns(), without.get_recent_turns())
        self.assertEqual(with_bridge.nlu_context.turn_count, without.nlu_context.turn_count)
        self.assertEqual(
            [(m["role"], m["content"]) for m in with_bridge.recent_messages(50)],
            [(m["role"], m["content"]) for m in without.recent_messages(50)])


# --------------------------------------------------------------------------
class TestCapabilityIdentificationWithoutExecution(CoreCase):
    def test_exact_name_is_suggested_through_matching_and_selection(self):
        _, result = self.say("can you do code analysis for me?")
        capability = result["capability"]
        self.assertTrue(capability["identified"])
        self.assertEqual(capability["status"], "suggested")
        self.assertEqual(capability["name"], "code_analysis")
        self.assertEqual(capability["version"], 1)
        self.assertTrue(capability["core_enabled"])
        self.assertEqual(capability["core_status"], "active")
        self.assertEqual(capability["selection"]["match_status"], "matched")
        self.assertEqual(capability["selection"]["status"], "selected")
        self.assertEqual(capability["selection"]["reason"], "unique_match")

    def test_suggestion_never_executes_and_never_allows_execution(self):
        _, result = self.say("please run code analysis on this")
        assert_no_execution(self, result)
        self.assertEqual(result["capability"]["execution_boundary"],
                         "not_evaluated_no_explicit_lifecycle_state")

    def test_a_suggested_capability_changes_neither_the_reply_nor_stored_state(self):
        before_rows = [dict(r) for r in self.core.capabilities.all()]
        before_counts = self.core.memory.counts()
        reply, _ = self.say("code analysis")
        control = self.new_core("control")
        with mock.patch.object(ri, "build_runtime_result", side_effect=RuntimeError("off")):
            control_reply = control.process_input("code analysis")
        self.assertEqual(reply, control_reply)
        self.assertEqual([dict(r) for r in self.core.capabilities.all()], before_rows)
        after_counts = self.core.memory.counts()
        self.assertEqual({k: v for k, v in after_counts.items() if k != "messages"},
                         {k: v for k, v in before_counts.items() if k != "messages"})

    def test_none_of_the_capability_entry_points_is_called(self):
        guarded = ["prepare_first_step", "execute_first_step", "prepare_execution_handoff"]
        patches = [mock.patch.object(self.core, name, side_effect=AssertionError(name))
                   for name in guarded]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with mock.patch.object(self.core.capabilities, "set_enabled",
                               side_effect=AssertionError("set_enabled")), \
             mock.patch.object(self.core.capabilities, "register",
                               side_effect=AssertionError("register")):
            _, result = self.say("please use code analysis")
        self.assertEqual(result["capability"]["status"], "suggested")

    def test_spelling_variants_of_the_exact_name_are_found(self):
        for text in ("code_analysis", "CODE ANALYSIS please", "use code-analysis now"):
            with self.subTest(text=text):
                _, result = self.say(text)
                self.assertEqual(result["capability"]["name"], "code_analysis")

    def test_a_disabled_capability_is_still_only_a_suggestion(self):
        _, result = self.say("I want code generation")
        capability = result["capability"]
        self.assertEqual(capability["status"], "suggested")
        self.assertEqual(capability["name"], "code_generation")
        self.assertFalse(capability["core_enabled"])
        self.assertEqual(capability["core_status"], "planned")
        assert_no_execution(self, result)

    def test_two_named_capabilities_are_ambiguous_and_nothing_is_selected(self):
        _, result = self.say("code analysis and image input")
        capability = result["capability"]
        self.assertEqual(capability["status"], "ambiguous")
        self.assertFalse(capability["identified"])
        self.assertIsNone(capability["name"])
        self.assertEqual(capability["candidates"], ["code_analysis", "image_input"])
        self.assertIsNone(capability["selection"])

    def test_no_guessing_from_partial_or_similar_words(self):
        for text in ("analysis of code", "codeanalysis", "analyze my code", "code", "images",
                     "what is Python?"):
            with self.subTest(text=text):
                _, result = self.say(text)
                self.assertEqual(result["capability"]["status"], "none")
                self.assertFalse(result["capability"]["identified"])
                self.assertIsNone(result["capability"]["name"])

    def test_no_capabilities_registered_gives_none(self):
        result = ri.build_runtime_result({"text": "code analysis", "route": "conversation",
                                          "capability_rows": []})
        self.assertEqual(result["capability"]["status"], "none")
        self.assertEqual(result["capability"]["reason"], "no_capabilities_registered")

    def test_a_row_the_registry_rejects_is_unresolved_not_selected(self):
        rows = [{"name": "bad_one", "description": "  padded  ", "enabled": 1, "status": "active"}]
        result = ri.build_runtime_result({"text": "use bad one", "route": "conversation",
                                          "capability_rows": rows})
        self.assertEqual(result["capability"]["status"], "unresolved")
        self.assertFalse(result["capability"]["identified"])
        self.assertIsNone(result["capability"]["name"])

    def test_module_has_no_path_to_run_a_capability(self):
        tree = ast.parse(open(MODULE_PATH, encoding="utf-8").read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        self.assertEqual(
            sorted(imported),
            ["capabilities.capability_matching", "capabilities.capability_registry",
             "capabilities.capability_selection", "re", "reasoning.capability_boundary",
             "reasoning.reasoning_decision", "reasoning.reasoning_foundation",
             "reasoning.reasoning_plan"])


# --------------------------------------------------------------------------
class TestFallbackCompatibility(CoreCase):
    SCRIPT = ["hello", "What is Python?", "Python is a language", "What is Python?",
              "tell me about Python", "TEACH sun IS a star", "help me plan a trip",
              "من عرفان هستم", "اسم من چیه؟", "qwerty zzznoxyzzz unmapped concept",
              "what about it", "can you do code analysis for me?", "", "   ", None]

    def replies(self, core):
        return [core.process_input(text) for text in self.SCRIPT]

    def test_every_reply_is_identical_with_and_without_the_bridge(self):
        with_bridge = self.replies(self.new_core("a"))
        control = self.new_core("b")
        with mock.patch.object(ri, "build_runtime_result", side_effect=RuntimeError("off")):
            without = self.replies(control)
        self.assertEqual(with_bridge, without)

    def test_the_deterministic_fallback_text_is_unchanged(self):
        reply, result = self.say("qwerty zzznoxyzzz unmapped concept")
        self.assertTrue(reply.startswith("I don't have enough information to answer that"))
        self.assertTrue(result["response"]["deterministic_fallback"])
        self.assertEqual(result["response"]["source"], ri.SOURCE_FALLBACK)

    def test_a_bridge_failure_never_reaches_the_reply_or_the_context(self):
        control = self.new_core("c")
        expected = control.process_input("What is Python?")
        with mock.patch.object(ri, "build_runtime_result", side_effect=RuntimeError("boom")):
            reply = self.core.process_input("What is Python?")
        self.assertEqual(reply, expected)
        self.assertEqual(self.core.last_runtime_result["status"], ri.STATUS_BRIDGE_ERROR)
        self.assertEqual(len(self.core.get_recent_turns()), 1)

    def test_a_failing_core_input_collaborator_is_contained_to_the_bridge(self):
        with mock.patch.object(self.core.capabilities, "all", side_effect=RuntimeError("db")):
            reply = self.core.process_input("What is Python?")
        self.assertTrue(reply.startswith("I don't have enough information"))
        self.assertEqual(self.core.last_runtime_result["status"], ri.STATUS_BRIDGE_ERROR)

    def test_direct_handler_calls_without_a_turn_still_work(self):
        # callers that bypass process_input() leave no turn in progress
        core = self.new_core("d")
        self.assertIsNone(core._turn_state)
        self.assertTrue(core._handle_conversation("hello").startswith("Hello"))
        self.assertTrue(core._handle_goal_or_conversation(
            "help me plan a trip", "help me plan a trip").startswith("[GOAL CREATED]"))
        self.assertIsNone(core.last_runtime_result)

    def test_results_are_deterministic_across_fresh_cores(self):
        first, second = self.new_core("x"), self.new_core("y")
        for text in self.SCRIPT:
            first.process_input(text)
            second.process_input(text)
            self.assertEqual(first.last_runtime_result, second.last_runtime_result)


# --------------------------------------------------------------------------
class TestPlainCoreAndEntryPoints(CoreCase):
    SCRIPT = TestFallbackCompatibility.SCRIPT

    def plain_core(self, name):
        base = os.path.join(self._tmp.name, name)
        os.makedirs(base, exist_ok=True)
        return Core(memory_db_path=os.path.join(base, "m.sqlite3"),
                    skill_definitions_dir=os.path.join(base, "skills"))

    def test_runtime_core_replies_equal_plain_core_replies(self):
        plain, runtime = self.plain_core("plain"), self.new_core("runtime")
        for text in self.SCRIPT:
            self.assertEqual(plain.process_input(text), runtime.process_input(text), text)
        self.assertEqual(plain.memory.counts(), runtime.memory.counts())
        self.assertEqual(plain.get_recent_turns(), runtime.get_recent_turns())

    def test_a_plain_core_is_untouched_by_the_bridge(self):
        plain = self.plain_core("plain2")
        plain.process_input("What is Python?")
        self.assertIsNone(plain._turn_state)
        self.assertFalse(hasattr(plain, "last_runtime_result"))
        self.assertFalse(hasattr(plain, "get_last_runtime_result"))

    def test_runtime_core_is_a_core_and_clears_its_turn_scratch(self):
        self.assertIsInstance(self.core, Core)
        self.core.process_input("hello")
        self.assertIsNone(self.core._turn_state)

    def test_core_process_input_and_goal_handler_were_not_edited(self):
        tree = ast.parse(open(os.path.join(PYTHON_ROOT, "core", "core.py"), encoding="utf-8").read())

        def calls(name):
            fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name][0]
            return {n.func.attr for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}

        self.assertEqual(calls("process_input"),
                         {"normalize", "log_message", "parse", "_handle_ael",
                          "_handle_goal_or_conversation", "add_turn"})
        self.assertEqual(calls("_handle_goal_or_conversation"),
                         {"create_goal", "_format_goal_created_reply", "_handle_conversation"})

    def test_the_real_entry_points_build_runtime_core(self):
        for rel, scope in (("android_entry.py", "start"), (os.path.join("interface", "server.py"), "run")):
            tree = ast.parse(open(os.path.join(PYTHON_ROOT, rel), encoding="utf-8").read())
            fn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == scope][0]
            built = {n.func.id for n in ast.walk(fn)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            self.assertIn("RuntimeCore", built, rel)
            self.assertNotIn("Core", built, rel)

    def test_the_bridge_lives_outside_the_layers_that_must_not_know_the_capability_stack(self):
        for folder in ("core", "reasoning", "understanding", "memory", "ael", "planning"):
            self.assertFalse(os.path.exists(os.path.join(PYTHON_ROOT, folder, "bridge.py")))
            self.assertFalse(os.path.exists(
                os.path.join(PYTHON_ROOT, folder, "runtime_integration.py")))
        self.assertTrue(os.path.isfile(MODULE_PATH))


# --------------------------------------------------------------------------
class TestMalformedInput(CoreCase):
    def test_empty_and_none_are_invalid_input_with_the_original_reply(self):
        for raw in ("", "   ", "\n\t", None):
            with self.subTest(raw=raw):
                reply, result = self.say(raw)
                self.assertEqual(reply, "Say something and I'll try to respond.")
                self.assertEqual(result["status"], ri.STATUS_INVALID_INPUT)
                self.assertEqual(result["route"], ri.ROUTE_EMPTY)
                self.assertFalse(result["input"]["valid"])
                self.assertEqual(result["input"]["normalized_text"], "")
                self.assertEqual(result["response"]["source"], ri.SOURCE_EMPTY_INPUT)
                self.assertFalse(result["understood_input"]["available"])
                self.assertFalse(result["reasoning"]["available"])
                self.assertEqual(result["capability"]["status"], "none")
                assert_no_execution(self, result)

    def test_empty_input_does_not_touch_context_or_messages(self):
        self.say("")
        self.assertEqual(self.core.get_recent_turns(), [])
        self.assertEqual(self.core.recent_messages(10), [])

    def test_non_string_input_is_stringified_like_before(self):
        reply, result = self.say(12345)
        self.assertIsInstance(reply, str)
        self.assertEqual(result["input"]["raw_type"], "int")
        self.assertEqual(result["input"]["normalized_text"], "12345")

    def test_very_long_input_is_clipped_in_the_report_only(self):
        text = "word " * 5000
        reply, result = self.say(text)
        self.assertIsInstance(reply, str)
        self.assertEqual(result["input"]["length"], len(" ".join(text.split())))
        self.assertLessEqual(len(result["input"]["normalized_text"]), ri.MAX_TEXT_CHARS)

    def test_odd_characters_do_not_break_the_bridge(self):
        for text in ("\x00\x01\x02", "💥🔥", "'; DROP TABLE capabilities; --", "<script>x</script>",
                     "ـــ", "a" * 70000):
            with self.subTest(text=text[:12]):
                _, result = self.say(text)
                self.assertIn(result["status"], (ri.STATUS_ENRICHED, ri.STATUS_LIMITED))
                json.dumps(result)
                assert_no_execution(self, result)

    def test_build_runtime_result_never_raises_on_garbage(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError(name)

        garbage = [None, 0, "text", [], {}, {"text": None}, {"text": 5}, {"route": object()},
                   {"text": "x", "analysis": object()},
                   {"text": "x", "analysis": Boom()},
                   {"text": "x", "route": "conversation", "read_only_analyzer": lambda t: 1 / 0},
                   {"text": "x", "route": "conversation", "read_only_analyzer": "nope"},
                   {"text": "x", "capability_rows": [None, 5, {"name": 3}, {"name": ""}]},
                   {"text": "x", "memory": {"relevant_context": object(),
                                            "resolved_reference": object(),
                                            "active_topic": object()}},
                   {"text": "x", "model_readiness": object(), "backend_kind": 7},
                   {"text": "x", "response_source": "made_up", "route": "made_up"}]
        for turn in garbage:
            with self.subTest(turn=repr(turn)[:40]):
                result = ri.build_runtime_result(turn)
                self.assertEqual(list(result), RESULT_KEYS)
                self.assertIn(result["status"], (ri.STATUS_ENRICHED, ri.STATUS_LIMITED,
                                                 ri.STATUS_INVALID_INPUT, ri.STATUS_BRIDGE_ERROR))
                self.assertIn(result["response"]["source"], ri.SOURCES)
                self.assertIn(result["route"], ri.ROUTES)
                json.dumps(result)
                assert_no_execution(self, result)

    def test_a_failing_section_only_shrinks_that_section(self):
        with mock.patch.object(ri, "build_reasoning_request", side_effect=RuntimeError("x")):
            result = ri.build_runtime_result({
                "text": "من عرفان هستم", "route": "conversation",
                "analysis": self.core.persian_nlu.analyze_in_context("من عرفان هستم", None)})
        self.assertEqual(result["reasoning"], {"available": False, "reason": "section_error"})
        self.assertTrue(result["understood_input"]["available"])
        self.assertEqual(result["status"], ri.STATUS_LIMITED)

    def test_the_input_turn_is_never_modified(self):
        turn = {"raw_input": "x", "text": "code analysis", "route": "conversation",
                "capability_rows": [{"name": "code_analysis", "description": "Analyze code.",
                                     "enabled": 1, "status": "active"}],
                "memory": {"turns_available_before": 3}}
        snapshot = copy.deepcopy(turn)
        ri.build_runtime_result(turn)
        self.assertEqual(turn, snapshot)


# --------------------------------------------------------------------------
class TestExecutionFlagsStaySafe(CoreCase):
    MESSAGES = ["hello", "What is Python?", "Python is a language", "TEACH sun IS a star",
                "help me plan a trip", "من عرفان هستم", "please run code analysis",
                "execute code generation now", "upgrade yourself automatically",
                "modify your own code", "approve implementation of the capability",
                "run the autonomy chain", "", None]

    def test_flags_are_constant_false_for_every_kind_of_message(self):
        for text in self.MESSAGES:
            with self.subTest(text=text):
                _, result = self.say(text)
                assert_no_execution(self, result)
                self.assertIs(result["execution"]["model_invoked"], False)

    def test_flags_stay_false_even_for_forged_input_claims(self):
        turn = {"text": "x", "route": "conversation", "response_source": "skill",
                "execution_allowed": True, "executed": True, "allowed": True,
                "capability": {"execution_allowed": True, "executed": True}}
        assert_no_execution(self, ri.build_runtime_result(turn))
        assert_no_execution(self, ri.error_runtime_result())

    def test_the_bridge_never_touches_files_network_or_processes(self):
        import builtins
        import socket
        import subprocess

        def forbidden(*a, **k):
            raise AssertionError("forbidden primitive used")

        analysis = self.core.persian_nlu.analyze_in_context("code analysis", None)
        rows = [dict(r) for r in self.core.capabilities.all()]
        turn = {"text": "code analysis", "route": "conversation", "analysis": analysis,
                "capability_rows": rows}
        with mock.patch.object(builtins, "open", forbidden), \
             mock.patch.object(socket, "socket", forbidden), \
             mock.patch.object(socket, "create_connection", forbidden), \
             mock.patch.object(subprocess, "Popen", forbidden), \
             mock.patch.object(os, "system", forbidden):
            result = ri.build_runtime_result(turn)
        self.assertEqual(result["capability"]["name"], "code_analysis")

    def test_static_scan_of_the_bridge_finds_no_forbidden_constructs(self):
        source = open(MODULE_PATH, encoding="utf-8").read()
        tree = ast.parse(source)
        forbidden_calls = {"open", "exec", "eval", "compile", "__import__", "system", "popen",
                           "Popen", "urlopen", "connect", "setattr", "delattr", "getenv"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None)
                is_regex_compile = (
                    isinstance(func, ast.Attribute) and name == "compile"
                    and isinstance(func.value, ast.Name) and func.value.id == "re")
                if not is_regex_compile:  # re.compile is a pattern, not code compilation
                    self.assertNotIn(name, forbidden_calls)
            self.assertNotIsInstance(node, ast.Global)
        for banned in ("urllib", "socket", "subprocess", "requests", "http", "autonomy",
                       "self_upgrade", "upgrade", "execution", "ael", "memory", "os.environ",
                       "api_key", "API_KEY"):
            code_lines = [l for l in source.splitlines()
                          if l.lstrip().startswith(("import ", "from "))]
            self.assertFalse(any(banned in l.split("#")[0] for l in code_lines), banned)

    def test_core_makes_no_autonomy_or_upgrade_call_for_a_turn(self):
        with mock.patch.object(self.core.upgrades, "history", side_effect=AssertionError("up")):
            self.say("upgrade yourself automatically")
        counts = self.core.memory.counts()
        self.say("modify your own code")
        self.assertEqual(
            {k: v for k, v in self.core.memory.counts().items() if k != "messages"},
            {k: v for k, v in counts.items() if k != "messages"})


# --------------------------------------------------------------------------
class TestLocalModelBoundary(GuardCase):
    def make_core(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return RuntimeCore(memory_db_path=os.path.join(tmp.name, "m.sqlite3"),
                           skill_definitions_dir=os.path.join(tmp.name, "skills"))

    def test_default_core_reports_no_local_model_and_a_clean_boundary(self):
        core = self.make_core()
        core.process_input(MESSAGE)
        model = core.last_runtime_result["local_model"]
        self.assertEqual(model["backend_kind"], "deterministic_fallback")
        self.assertEqual(model["readiness_status"], "MODEL_NOT_CONFIGURED")
        self.assertFalse(model["real_backend_connected"])
        self.assertFalse(model["generated_this_turn"])
        self.assertEqual(model["boundary"], "Core.use_local_language_model")
        self.assertFalse(core.last_runtime_result["response"]["generated_by_local_model"])
        self.assertFalse(core.last_runtime_result["execution"]["model_invoked"])

    def test_default_runtime_local_model_state_fields(self):
        core = self.make_core()
        reply = core.process_input(MESSAGE)
        control = self.make_core().process_input(MESSAGE)
        self.assertEqual(reply, control)  # response behavior unchanged
        model = core.last_runtime_result["local_model"]
        self.assertIs(model["available"], False)
        self.assertEqual(model["state"], "unavailable_no_local_model_running")
        self.assertIs(model["generated_by_local_model"], False)
        self.assertIs(model["model_invoked"], False)
        self.assertIs(core.last_runtime_result["execution"]["model_invoked"], False)
        for flag in EXECUTION_FALSE_FLAGS:
            self.assertIs(core.last_runtime_result["execution"][flag], False)
        json.dumps(core.last_runtime_result)
        err = ri.error_runtime_result()["local_model"]
        self.assertEqual((err["available"], err["state"], err["model_invoked"]),
                         (False, "unavailable_no_local_model_running", False))

    def test_the_bridge_reports_exactly_what_core_reports(self):
        core = self.make_core()
        core.process_input(MESSAGE)
        readiness = core.get_local_model_readiness()
        model = core.last_runtime_result["local_model"]
        self.assertEqual(model["readiness_status"], readiness.status)
        self.assertEqual(model["real_backend_connected"], readiness.ready)

    def test_opting_in_without_a_runtime_stays_unavailable_and_falls_back(self):
        control = self.make_core()
        expected = control.process_input(MESSAGE)
        core = self.make_core()
        core.use_local_language_model()
        reply = core.process_input(MESSAGE)
        self.assertEqual(reply, expected)
        model = core.last_runtime_result["local_model"]
        self.assertFalse(model["real_backend_connected"])
        self.assertEqual(model["readiness_status"], "MODEL_NOT_CONFIGURED")
        self.assertEqual(core.last_runtime_result["response"]["source"], ri.SOURCE_FALLBACK)
        self.assertTrue(core.last_runtime_result["response"]["deterministic_fallback"])

    def test_the_bridge_never_loads_or_runs_a_model(self):
        core = self.make_core()
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        # run a turn the model does NOT answer (a keyword skill answers first)
        core.process_input("hello")
        self.assertEqual((runtime.load_calls, runtime.generate_calls, runtime.inferences),
                         (0, 0, 0))
        self.assertTrue(core.last_runtime_result["local_model"]["real_backend_connected"])
        self.assertFalse(core.last_runtime_result["execution"]["model_invoked"])

    def test_a_scripted_runtime_double_marks_the_boundary_as_used(self):
        """TEST DOUBLE ONLY (not a model): proves a future backend plugs into the
        boundary and is reported as the response source with no other change."""
        core = self.make_core()
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        reply = core.process_input(MESSAGE)
        self.assertEqual(reply, MODEL_TEXT)
        result = core.last_runtime_result
        self.assertEqual(result["response"]["source"], ri.SOURCE_LOCAL_MODEL)
        self.assertTrue(result["response"]["generated_by_local_model"])
        self.assertTrue(result["local_model"]["generated_this_turn"])
        self.assertTrue(result["execution"]["model_invoked"])
        # still no capability / code / autonomy execution of any kind
        for flag in ("allowed", "executed", "capability_executed", "code_modified",
                     "autonomy_chain_executable", "external_service_used"):
            self.assertIs(result["execution"][flag], False)
        self.assertEqual(runtime.generate_calls, 1)

    def test_no_model_text_is_ever_produced_by_the_bridge_itself(self):
        core = self.make_core()
        reply = core.process_input(MESSAGE)
        self.assertNotEqual(reply, MODEL_TEXT)
        self.assertNotIn("response_text", json.dumps(core.last_runtime_result))


# --------------------------------------------------------------------------
class TestRealServerPath(CoreCase):
    def request(self, port, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if payload is not None else "GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def test_http_message_reaches_the_bridge_and_the_endpoint_reports_it(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.core))
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(self.request(port, "/api/runtime-result"), {"runtime_result": None})
            body = self.request(port, "/api/message", {"text": "can you do code analysis?"})
            self.assertEqual(sorted(body), ["reply", "status"])  # message contract unchanged
            self.assertIsInstance(body["reply"], str)
            result = self.request(port, "/api/runtime-result")["runtime_result"]
            self.assertEqual(list(result), RESULT_KEYS)
            self.assertEqual(result["capability"]["name"], "code_analysis")
            self.assertEqual(result["response"]["source"], ri.SOURCE_FALLBACK)
            assert_no_execution(self, result)
            self.assertEqual(result, json.loads(json.dumps(self.core.last_runtime_result)))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_malformed_http_bodies_still_get_the_old_error_answers(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.core))
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body = self.request(port, "/api/message", {"text": None})
            self.assertEqual(body["reply"], "Say something and I'll try to respond.")
            self.assertEqual(self.request(port, "/api/runtime-result")
                             ["runtime_result"]["status"], ri.STATUS_INVALID_INPUT)
            body = self.request(port, "/api/message", ["not", "an", "object"])
            self.assertEqual(body["reply"], "Say something and I'll try to respond.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


# --------------------------------------------------------------------------
class TestLearningObservation(CoreCase):
    def test_ordinary_message_is_not_a_learning_request(self):
        _, result = self.say("hello there")
        learning = result["learning"]
        self.assertEqual((learning["learning_available"], learning["learning_requested"],
                          learning["learning_state"]), (True, False, "no_learning_request"))
        self.assertIs(learning["learning_executed_by_bridge"], False)
        self.assertIs(learning["learning_performed_by_existing_runtime"], False)

    def test_explicit_teach_input_is_detected_but_not_claimed_as_learned(self):
        reply, result = self.say("TEACH python IS language")
        learning = result["learning"]
        self.assertEqual((learning["learning_requested"], learning["learning_state"],
                          learning["request_kind"]),
                         (True, "explicit_learning_request_detected", "ael_teach"))
        self.assertIs(learning["learning_executed_by_bridge"], False)
        # Prompt 914: Core's own AEL path really ran TEACH, so this is now reported.
        self.assertIs(learning["learning_performed_by_existing_runtime"], True)
        control = self.new_core("control").process_input("TEACH python IS language")
        self.assertEqual(reply, control)  # reply text unchanged
        assert_no_execution(self, result)
        json.dumps(result)

    def test_malformed_and_unavailable_learning_input_is_safe(self):
        bad = ri.build_runtime_result({"raw_input": 5, "text": 5, "route": "conversation"})
        self.assertEqual(bad["learning"]["learning_state"], "unavailable_malformed_learning_input")
        self.assertIs(bad["learning"]["learning_requested"], False)
        noscope = ri.build_runtime_result({"raw_input": "x", "text": "TEACH a IS b", "route": "ael"})
        self.assertEqual(noscope["learning"]["learning_state"], "learning_request_unavailable")
        self.assertEqual(ri.error_runtime_result()["learning"]["learning_state"],
                         "no_learning_request")

    def test_memory_fields_and_no_external_or_self_modification(self):
        _, result = self.say("hello there")
        self.assertEqual(result["memory_context"]["memory_state"], "no_memory_available")
        execution = result["execution"]
        self.assertIs(execution["code_modified"], False)
        self.assertIs(execution["external_service_used"], False)
        self.assertIs(execution["autonomy_chain_executable"], False)
        source = open(os.path.join(PYTHON_ROOT, "runtime_integration", "bridge.py")).read()
        for banned in ("import requests", "urllib", "socket", "subprocess", "open(", "exec(", "eval("):
            self.assertNotIn(banned, source)


# --------------------------------------------------------------------------
# Prompt 914 - the learning section reports what the existing runtime really did.
class TestAelLearningState(CoreCase):
    def knowledge_names(self, core):
        return [k["name"] for k in core.knowledge.all()] if hasattr(core.knowledge, "all") else []

    def test_teach_is_really_persisted_and_reported(self):
        reply, result = self.say("TEACH python IS language")
        learning = result["learning"]
        self.assertIn("[AEL OK]", reply)
        self.assertEqual((learning["learning_outcome"], learning["request_kind"]),
                         ("performed_by_existing_runtime", "ael_teach"))
        self.assertIs(learning["learning_performed_by_existing_runtime"], True)
        self.assertIs(learning["learning_executed_by_bridge"], False)
        self.assertEqual(learning["ael_learning_instructions_performed"], 1)
        self.assertIsNotNone(self.core.knowledge.get("python"))  # really stored
        assert_no_execution(self, result)

    def test_relate_is_really_persisted_and_reported(self):
        self.say("TEACH python IS language")
        self.say("TEACH code IS text")
        reply, result = self.say("RELATE python TO code AS related_to")
        learning = result["learning"]
        self.assertIn("[AEL OK]", reply)
        self.assertEqual((learning["learning_outcome"], learning["request_kind"]),
                         ("performed_by_existing_runtime", "ael_relate"))
        self.assertIs(learning["learning_performed_by_existing_runtime"], True)
        info = self.core.learning.recall("python")
        self.assertTrue(any(r["to_name"].lower() == "code"
                            for r in info["relationships"]["outgoing"]))

    def test_interpreted_without_persistence_is_not_reported_as_learning(self):
        # parsed as a TEACH, but the existing learning system fails to store it
        with mock.patch.object(self.core.learning, "teach", side_effect=RuntimeError("boom")):
            reply, result = self.say("TEACH python IS language")
        learning = result["learning"]
        self.assertIn("[AEL ERROR]", reply)
        self.assertEqual(result["execution"]["existing_runtime_effects"], ["ael_program_interpreted"])
        self.assertEqual(learning["learning_outcome"], "interpreted_not_performed")
        self.assertIs(learning["learning_requested"], True)
        self.assertIs(learning["learning_performed_by_existing_runtime"], False)
        self.assertIsNone(self.core.knowledge.get("python"))
        # a syntax error is not even interpreted
        reply, bad = self.say("TEACH python")
        self.assertIn("[AEL ERROR]", reply)
        self.assertEqual(bad["learning"]["learning_outcome"], "malformed_or_unparsed")
        self.assertIs(bad["learning"]["learning_performed_by_existing_runtime"], False)
        # an AEL line that is not teaching is never learning
        _, ask = self.say("ASK python")
        self.assertIs(ask["learning"]["learning_requested"], False)
        self.assertIs(ask["learning"]["learning_performed_by_existing_runtime"], False)
        # no per-instruction results supplied: only interpretation can be claimed
        bare = ri.build_runtime_result({"raw_input": "x", "text": "TEACH a IS b", "route": "ael",
                                        "learning_available": True})
        self.assertEqual(bare["learning"]["learning_outcome"], "interpreted_not_performed")
        self.assertIs(bare["learning"]["learning_performed_by_existing_runtime"], False)

    def test_unavailable_and_malformed_states(self):
        turn = {"raw_input": "x", "text": "TEACH a IS b", "route": "ael",
                "ael_results": [{"kind": "TEACH", "success": True}]}
        self.assertEqual(ri.build_runtime_result(turn)["learning"]["learning_outcome"],
                         "learning_unavailable")
        syntax = dict(turn, learning_available=True, ael_results=[{"kind": None, "success": False}])
        self.assertEqual(ri.build_runtime_result(syntax)["learning"]["learning_outcome"],
                         "malformed_or_unparsed")
        bad = ri.build_runtime_result({"raw_input": 5, "text": 5, "route": "conversation"})
        self.assertEqual(bad["learning"]["learning_outcome"], "malformed_or_unparsed")
        junk = dict(turn, learning_available=True, ael_results="nonsense")
        self.assertIs(ri.build_runtime_result(junk)["learning"]
                      ["learning_performed_by_existing_runtime"], False)

    def test_ordinary_messages_stay_non_learning_and_replies_unchanged(self):
        for text in ("hello there", "What is Python?", "Python is a language"):
            _, result = self.say(text)
            self.assertIs(result["learning"]["learning_requested"], False, text)
            self.assertEqual(result["learning"]["request_kind"], None)
        for text in ("TEACH python IS language", "TEACH x", "ASK python"):
            reply, _ = self.say(text)
            self.assertEqual(reply, self.new_core("control914").process_input(text))
        self.assertNotIn("run", self.core.ael.__dict__)  # temporary watcher removed

    def test_no_capability_external_service_or_self_modification(self):
        _, result = self.say("TEACH python IS language")
        assert_no_execution(self, result)
        self.assertIs(result["execution"]["external_service_used"], False)
        self.assertIs(result["execution"]["code_modified"], False)
        for name in ("bridge.py", "runtime_core.py"):
            source = open(os.path.join(PYTHON_ROOT, "runtime_integration", name)).read()
            for banned in ("import requests", "urllib", "socket", "subprocess", "exec(", "eval(",
                           "open(", "anthropic", "openai"):
                self.assertNotIn(banned, source)
        self.assertEqual(list(result), RESULT_KEYS)


# --------------------------------------------------------------------------
# Prompt 915 - RELATE: a newly created relationship vs one that already existed.
RELATE_KEYS = ("relate_requested", "relate_instructions_requested", "relate_instructions_executed",
               "relate_instructions_failed", "relationships_created",
               "relationships_already_existed", "relate_persistence")


class TestRelatePersistenceResult(CoreCase):
    def setUp(self):
        super().setUp()
        self.say("TEACH python IS language")
        self.say("TEACH code IS text")

    def relation_rows(self, core=None):
        info = (core or self.core).learning.recall("python")
        return [r for r in info["relationships"]["outgoing"] if r["to_name"].lower() == "code"]

    def test_new_relate_reports_a_created_relationship(self):
        self.assertEqual(self.relation_rows(), [])
        reply, result = self.say("RELATE python TO code AS related_to")
        learning = result["learning"]
        self.assertIn("[AEL OK]", reply)
        self.assertEqual(len(self.relation_rows()), 1)  # really stored
        self.assertEqual((learning["relate_requested"], learning["relate_persistence"]),
                         (True, "new_relationship_created"))
        self.assertEqual((learning["relate_instructions_requested"],
                          learning["relate_instructions_executed"],
                          learning["relate_instructions_failed"],
                          learning["relationships_created"],
                          learning["relationships_already_existed"]), (1, 1, 0, 1, 0))
        self.assertEqual(learning["request_kind"], "ael_relate")
        self.assertIs(learning["learning_executed_by_bridge"], False)
        assert_no_execution(self, result)
        json.dumps(result)

    def test_repeated_relate_reports_no_new_relationship(self):
        self.say("RELATE python TO code AS related_to")
        reply, result = self.say("RELATE python TO code AS related_to")
        learning = result["learning"]
        self.assertIn("[AEL OK]", reply)
        self.assertIn("Already known", reply)
        self.assertEqual(len(self.relation_rows()), 1)  # no duplicate stored
        self.assertEqual(learning["relate_persistence"], "relationship_already_existed")
        self.assertEqual((learning["relate_instructions_executed"], learning["relationships_created"],
                          learning["relationships_already_existed"]), (1, 0, 1))
        self.assertIs(learning["relate_requested"], True)

    def test_successful_instruction_alone_is_not_newly_persisted(self):
        base = {"raw_input": "x", "text": "RELATE a TO b AS r", "route": "ael",
                "learning_available": True,
                "ael_results": [{"kind": "RELATE", "success": True}]}
        # no evidence from LearningSystem.relate(): nothing is claimed as created
        for outcomes in (None, "junk", [None], [True, False], []):
            learning = ri.build_runtime_result(dict(base, relate_outcomes=outcomes))["learning"]
            self.assertEqual(learning["relate_persistence"], "executed_persistence_unconfirmed",
                             outcomes)
            self.assertEqual((learning["relationships_created"],
                              learning["relationships_already_existed"],
                              learning["relate_instructions_executed"]), (0, 0, 1))
        learning = ri.build_runtime_result(dict(base))["learning"]
        self.assertEqual(learning["relate_persistence"], "executed_persistence_unconfirmed")
        # evidence present: the flag, and only the flag, decides
        self.assertEqual(ri.build_runtime_result(dict(base, relate_outcomes=[True]))["learning"]
                         ["relate_persistence"], "new_relationship_created")
        self.assertEqual(ri.build_runtime_result(dict(base, relate_outcomes=[False]))["learning"]
                         ["relate_persistence"], "relationship_already_existed")
        # learning unavailable: never claims a stored relationship
        off = dict(base, relate_outcomes=[True], learning_available=False)
        learning = ri.build_runtime_result(off)["learning"]
        self.assertEqual((learning["relate_persistence"], learning["relationships_created"]),
                         ("executed_persistence_unconfirmed", 0))

    def test_failed_and_malformed_relate(self):
        reply, bad = self.say("RELATE python TO")
        self.assertIn("[AEL ERROR]", reply)
        learning = bad["learning"]
        self.assertEqual((learning["relate_requested"], learning["relate_persistence"],
                          learning["relationships_created"]), (True, "relate_failed_or_malformed", 0))
        self.assertEqual((learning["relate_instructions_executed"],
                          learning["relate_instructions_failed"]), (0, 1))
        self.assertEqual(self.relation_rows(), [])
        # the existing learning system raising: instruction fails, nothing created
        with mock.patch.object(self.core.learning, "relate", side_effect=RuntimeError("boom")):
            reply, failed = self.say("RELATE python TO code AS related_to")
        self.assertIn("[AEL ERROR]", reply)
        learning = failed["learning"]
        self.assertEqual((learning["relate_persistence"], learning["relate_instructions_executed"],
                          learning["relate_instructions_failed"], learning["relationships_created"]),
                         ("relate_failed_or_malformed", 0, 1, 0))
        self.assertEqual(self.relation_rows(), [])
        self.assertNotIn("relate", self.core.learning.__dict__)  # patch and watcher both gone
        # a malformed result row from the interpreter is never a created relationship
        junk = ri.build_runtime_result({"raw_input": "x", "text": "RELATE a", "route": "ael",
                                        "learning_available": True,
                                        "ael_results": [{"kind": None, "success": False}],
                                        "relate_outcomes": []})["learning"]
        self.assertEqual((junk["relate_persistence"], junk["relationships_created"]),
                         ("relate_failed_or_malformed", 0))

    def test_teach_and_ordinary_messages_have_no_relate_claims(self):
        reply, teach = self.say("TEACH ruby IS language")
        learning = teach["learning"]
        self.assertEqual((learning["learning_outcome"], learning["request_kind"],
                          learning["ael_learning_instructions_performed"]),
                         ("performed_by_existing_runtime", "ael_teach", 1))
        self.assertIs(learning["learning_performed_by_existing_runtime"], True)
        self.assertEqual((learning["relate_requested"], learning["relate_persistence"],
                          learning["relationships_created"]), (False, "not_a_relate_request", 0))
        self.assertEqual(reply, self.new_core("ctl_teach").process_input("TEACH ruby IS language"))
        for text in ("hello there", "What is Python?", "Python is a language", "ASK python"):
            _, result = self.say(text)
            learning = result["learning"]
            self.assertIs(learning["learning_requested"], False, text)
            self.assertEqual(learning["relate_persistence"], "not_a_relate_request", text)
            self.assertEqual(learning["relationships_created"], 0, text)
        self.assertEqual(list(ri.error_runtime_result()["learning"])[-7:], list(RELATE_KEYS))
        self.assertEqual(ri.error_runtime_result()["learning"]["relate_persistence"],
                         "not_a_relate_request")

    def test_user_facing_replies_and_relate_semantics_unchanged(self):
        control = Core(memory_db_path=os.path.join(self._tmp.name, "plain.sqlite3"),
                       skill_definitions_dir=os.path.join(self._tmp.name, "plain_skills"))
        for text in ("TEACH python IS language", "TEACH code IS text"):
            control.process_input(text)
        for text in ("RELATE python TO code AS related_to",   # new
                     "RELATE python TO code AS related_to",   # repeat
                     "RELATE python TO", "ASK python"):
            self.assertEqual(self.core.process_input(text), control.process_input(text), text)
        self.assertEqual(len(self.relation_rows()), len(self.relation_rows(control)))
        # the watcher passes LearningSystem.relate()'s own return value through untouched
        self.assertNotIn("relate", self.core.learning.__dict__)
        self.assertEqual(self.core.learning.relate("python", "code", "related_to"),
                         {"created": False, "contradiction": None})
        self.assertEqual(self.core.learning.relate("code", "python", "inverse_of")["created"], True)

    def test_still_read_only_and_safe(self):
        _, result = self.say("RELATE python TO code AS related_to")
        self.assertEqual(list(result), RESULT_KEYS)
        assert_no_execution(self, result)
        for name in ("bridge.py", "runtime_core.py"):
            source = open(os.path.join(PYTHON_ROOT, "runtime_integration", name)).read()
            for banned in ("import requests", "urllib", "socket", "subprocess", "exec(", "eval(",
                           "open(", "anthropic", "openai", "sqlite3"):
                self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
