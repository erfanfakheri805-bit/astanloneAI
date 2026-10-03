"""
Core
=====
The central orchestrator. Core does not implement intelligence itself -
it wires together the Input, Parser, Memory, Knowledge, Concept,
Reasoning, Rule Registry, Learning, Skill, Capability, Code Intelligence,
AEL, Self-Upgrade, Health, and (Prompt 397) Language Intelligence
systems, and defines the single request/response flow:
process_input(text) -> reply text.

Language Intelligence Core integration (Prompt 397, connected in
Prompt 402): `self.language_intelligence` (see language_intelligence/)
is an additional step inside `_handle_conversation` - it produces a
structured `LanguageUnderstandingResult` (recorded as
`self.last_language_understanding`) from the same context/reference/
topic pieces `_handle_conversation` already computes for itself, using
today's deterministic fallback backend (which itself just wraps the
existing Understanding Engine - no new intelligence; Prompt 419: it is
also given this Core's own `self.meaning_resolver`, so that result's
`learned_meanings` reflects whatever the Learned Meaning Resolution
system - Prompt 418 - already knows about the message's candidate
expressions). That structured
understanding is then handed, unchanged, to the same core's
`generate_response()` (see that method's own step "1d" below), which
routes it to whichever backend/provider/runtime is actually configured
(today, always the deterministic fallback - see core/config.py/__init__
below - so its result is always STATUS_DEFERRED and nothing about
which branch `_handle_conversation` takes, or what reply text is
ultimately returned, changes). Only if a real backend were configured
and returned STATUS_GENERATED with real `response_text` would that
text become the reply directly, through the existing
`process_input()` response path - no second reply pipeline, no
duplicated message/context storage. See that method's own step "1d"
below, and language_intelligence/language_intelligence_core.py's
module docstring for the full architecture this is the foundation for.

Nothing about the application's actual behavior lives here beyond
routing; every real capability lives in its own module so future stages
can add or replace systems without rewriting Core.

`memory_db_path` and `skill_definitions_dir` are optional overrides used
by the test suite (see tests/) to run a fully isolated Core instance
against a temporary database and skill directory instead of the real
data/ folder - production code (interface/server.py) never passes them,
so default behavior is unchanged.

`context_max_turns` (optional) sets how many recent turns the short-term
conversational context keeps (see context/conversation_context.py);
omitted, it uses that module's DEFAULT_CONTEXT_SIZE.
"""

import os
import sys

# Make sibling top-level packages importable when run as a script.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.memory_system import MemorySystem
from knowledge.knowledge_system import KnowledgeSystem
from concepts.concept_system import ConceptSystem
from reasoning.reasoning_engine import ReasoningEngine
from reasoning.rule_registry import RuleRegistry
from learning.learning_system import LearningSystem
from skills.skill_system import SkillSystem
from capabilities.capability_system import CapabilitySystem
from code_intelligence.python_inspector import inspect_source
from ael.interpreter import AELInterpreter
from self_upgrade.upgrade_system import UpgradeSystem
from input_system.input_system import InputSystem
from parser.parser import Parser
from diagnostics.health_system import HealthSystem
from understanding.term_extraction import extract_candidate_terms
from understanding.engine import UnderstandingEngine
from understanding.sentence_analysis import SENTENCE_QUESTION, SENTENCE_STATEMENT, SENTENCE_COMMAND
from context.conversation_context import ConversationContext, DEFAULT_CONTEXT_SIZE
from context.relevance import select_relevant_turns
from context.message_reference_resolution import resolve_conversational_reference
from context.active_topic import ActiveTopicTracker
from context.conversation_state import ConversationState
from context.topic_awareness import assess_topic_awareness
from reasoning.reasoning_result import STATUS_ANSWERED
from reasoning.relation_phrasing import phrase as phrase_relation
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.planner import Planner
from planning.goal_detection import is_goal_oriented
from planning.request_context import build_request_context
from planning.plan_validation import validate_plan as _validate_plan
from planning.plan_builder import build_plan_from_context as _build_plan_from_context
from planning.execution_handoff import prepare_execution_handoff as _prepare_execution_handoff
from execution.step_execution_preparation import StepExecutionPreparation
from execution.step_execution_controller import StepExecutionController
from learning.execution_learning import ExecutionLearning
from learning.learning_record_store import LearningRecordStore
from platform_layer import get_platform
from language_intelligence.language_intelligence_core import LanguageIntelligenceCore
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend
from language_intelligence.local_model_backend import LocalLanguageModelBackend
from language_intelligence.language_learning_store import LanguageLearningStore
from language_intelligence.language_relationships import LanguageRelationshipStore
from language_intelligence.learned_expression_variation_matcher import (
    LearnedExpressionVariationMatcher,
)
from language_intelligence.meaning_resolution import MeaningResolver
from language_intelligence.learned_meaning_disambiguation import LearnedMeaningDisambiguator
from language_intelligence.learned_pattern_matching import LearnedPatternMatcher
from language_intelligence.learned_sentence_structure import LearnedSentenceStructureExtractor
from language_intelligence.learned_pattern_teaching import LearnedPatternTeacher
from language_intelligence.learned_pattern_meaning import LearnedPatternMeaningBinder
from language_intelligence.response_planning import ResponsePlanner
from language_intelligence.learned_knowledge_context import select_learned_knowledge
from language_intelligence.correction_understanding import STATUS_RESOLVED as CORRECTION_STATUS_RESOLVED
from language_intelligence.correction_understanding import (
    CorrectionUnderstandingResult as _CorrectionUnderstanding,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    map_correction_understanding_result_to_feedback_record,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.correction_learning_handoff_result import (
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_retrieval_trigger import (
    build_correction_retrieval_trigger,
)
from language_intelligence.correction_retrieval_understanding_adapter import (
    retrieve_and_attach_correction_application_candidate,
)
from language_intelligence.correction_application_request import (
    CorrectionApplicationRequest, REQUEST_KIND_APPLY_CORRECTION,
)
from language_intelligence.correction_application_guarded import (
    apply_correction_request_with_validation,
)
from language_intelligence.correction_application_result import STATUS_APPLIED as CORRECTION_APPLIED
from language_intelligence.correction_application_candidate_operation import (
    apply_correction_application_candidate,
)
from learning.learned_knowledge_gate import (
    evaluate_learned_knowledge_gate, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics, LearnedKnowledgeDiagnosticSnapshotHistory,
)

APP_VERSION = "0.2.0-foundation"


class Core:
    # Prompt 502: the learned-knowledge gate verdict for the latest message (see
    # _attach_learned_knowledge); None until a selected entry has been gated.
    last_learned_knowledge_gate = None
    # Prompt 503: the structured decision trace for that same verdict - internal-
    # only, built from `last_learned_knowledge_gate` and never used in response
    # generation. None whenever `last_learned_knowledge_gate` is None.
    last_learned_knowledge_gate_trace = None

    def __init__(self, memory_db_path=None, skill_definitions_dir=None, context_max_turns=None):
        self.memory = MemorySystem(memory_db_path) if memory_db_path else MemorySystem()
        self.knowledge = KnowledgeSystem(self.memory)
        self.concepts = ConceptSystem(self.knowledge)
        # Stage 6: rules are now first-class, persisted, validated objects
        # (see reasoning/rule_registry.py) instead of only an in-memory
        # RuleEngine - the Reasoning Engine evaluates registry.engine
        # directly, so enabling/disabling/registering a rule takes effect
        # immediately without reconstructing anything.
        self.rule_registry = RuleRegistry(self.memory)
        self.reasoning = ReasoningEngine(self.knowledge, rule_registry=self.rule_registry)
        self.learning = LearningSystem(
            self.concepts, self.knowledge, memory=self.memory, reasoning_engine=self.reasoning
        )
        # Prompt 504: diagnostic-only running counts over the Prompt 503 decision
        # traces (see _attach_learned_knowledge below) - how many learned-knowledge
        # evaluations happened, how many were accepted/rejected/had no candidate,
        # and why. Never read by response generation and never influences it.
        self.learned_knowledge_decision_statistics = LearnedKnowledgeDecisionStatistics()
        # Prompt 508: bounded, diagnostic-only history of snapshots of the
        # Prompt 505-507 diagnostics. Starts empty, is only written when a
        # caller explicitly records a snapshot, and is never read by response
        # generation, the gate, or learning.
        self.learned_knowledge_diagnostic_snapshot_history = (
            LearnedKnowledgeDiagnosticSnapshotHistory()
        )
        self.skills = (
            SkillSystem(self.memory, definitions_dir=skill_definitions_dir)
            if skill_definitions_dir else SkillSystem(self.memory)
        )
        self.capabilities = CapabilitySystem(self.memory)
        self.upgrades = UpgradeSystem(self.memory)
        self.ael = AELInterpreter(
            self.learning, self.skills, upgrade_system=self.upgrades,
            reasoning_engine=self.reasoning, memory=self.memory,
            rule_registry=self.rule_registry,
        )
        self.input_system = InputSystem()
        self.parser = Parser()
        self.understanding = UnderstandingEngine()
        # Short-term conversational context (see context/). Deliberately
        # separate from self.memory - it is process-RAM only, bounded,
        # and reset() on it can never touch persistent storage. It holds
        # two bounded things: understanding entries (written by
        # understand()/learn_from_text(), which _handle_conversation
        # calls) and the last few user/assistant turns (written by
        # process_input() for every handled message, AEL and goal
        # requests included). It is passed to the Reasoning Engine
        # (see _handle_conversation), which therefore has the turns
        # before the current message available to it. AEL execution
        # itself never reads it.
        self.context = ConversationContext(
            max_size=DEFAULT_CONTEXT_SIZE if context_max_turns is None else context_max_turns
        )
        # Active Conversation Topic (Prompt 393, context/active_topic.py):
        # one short, deterministic "what is being discussed right now"
        # string plus the result of its last update. In-memory only,
        # same isolation pattern as self.context above - not a memory
        # system, cleared by reset_context(). Only _handle_conversation
        # updates it.
        self.topic_tracker = ActiveTopicTracker(window=self.context.max_size)
        # Lightweight Conversation State (Prompt 405,
        # context/conversation_state.py): the few things worth keeping
        # from a long conversation that the two structures above do not
        # (earlier topics, explicit preferences, unresolved references),
        # bounded by the same context limit. In-memory only, cleared by
        # reset_context(); fed by _handle_conversation from the results
        # it already computed - never a second history.
        self.conversation_state = ConversationState(max_age=self.context.max_size)
        # The separate inputs the most recent Response Construction
        # call was built from (see _construct_fallback_reply) - kept
        # side by side, never merged into one another.
        self.last_response_context = None
        # Foundation for the future Planning Engine (see planning/).
        # In-memory only, same isolation pattern as self.context above.
        # Never written to by AEL. Only written to by process_input()
        # when the input is clearly goal-oriented (see
        # _handle_goal_or_conversation/planning/goal_detection.py) -
        # every other conversational input still leaves this untouched,
        # so today's behaviour for ordinary questions/statements/
        # unknown input is unaffected by its presence. Otherwise only
        # the explicit create_goal()/get_goal()/describe_goal() entry
        # points below touch it.
        self.goals = GoalManager()
        # Foundation for the future Planning Engine (see planning/plan.py).
        # In-memory only, same isolation pattern as self.goals above.
        # Never written to by AEL. Only written to by process_input()
        # exactly when self.goals above is (create_goal() below starts
        # one empty Plan alongside every Goal it creates) - so, same as
        # self.goals, ordinary questions/statements/unknown input never
        # touch this either. Otherwise only the explicit
        # create_plan()/add_plan_step()/get_plan()/describe_plan()
        # entry points below touch it. Wired to self.goals so a Plan
        # can only ever be created for a Goal that actually exists.
        self.plans = PlanManager(self.goals)
        # Minimal, deterministic Goal -> first PlanStep bridge (see
        # planning/planner.py). In-memory only, same isolation pattern
        # as self.goals/self.plans above - never written to by
        # process_input()/AEL, so today's behaviour is unchanged by
        # its presence. Only the explicit plan_first_step() entry
        # point below touches it. Wired to self.goals/self.plans so it
        # can never bypass either manager's own validation.
        self.planner = Planner(self.goals, self.plans)
        # Read-only execution-readiness checkpoint (see
        # execution/step_execution_preparation.py). Wired to this same
        # self.plans (never a second, possibly-disagreeing PlanManager)
        # so a prepared/failed answer always reflects the exact same
        # Plan/PlanStep state everything else on Core already sees.
        # Constructed with no capability_handlers/executable_capabilities
        # of its own (StepExecutionPreparation's own defaults) - this
        # stage only connects the existing Goal -> Plan -> first
        # PlanStep -> preparation checkpoint path; it does not stand up
        # a registry of real, callable capability handlers, and it
        # never executes anything (see prepare_first_step below).
        self.step_preparation = StepExecutionPreparation(self.plans)
        # Read-write, single-step run controller (see
        # execution/step_execution_controller.py). Reuses this exact
        # self.step_preparation instance (never a second, possibly-
        # disagreeing StepExecutionPreparation) and, through the
        # capability_handlers/executable_capabilities passed below,
        # the exact same (currently empty) registries that instance
        # already checks against - so a step this controller's own
        # ExecutionEngine goes on to run is always checked against the
        # same handler registry StepExecutionPreparation already
        # gated it through. No handlers are registered here; this
        # stage only connects the existing goal_id -> Plan -> first
        # PlanStep path to this existing controller (see
        # execute_first_step below) - it does not add any real,
        # callable capability of its own.
        self.step_controller = StepExecutionController(
            self.plans,
            preparation=self.step_preparation,
            capability_handlers=self.step_preparation.capability_handlers,
            executable_capabilities=self.step_preparation.executable_capabilities,
        )
        # Execution -> Learning connection (see
        # learning/execution_learning.py / learning/learning_record_store.py).
        # ExecutionLearning is stateless (holds nothing between calls);
        # self.learning_records is the one, existing LearningRecordStore
        # instance execute_first_step below adds every learning record
        # into - never a second, disagreeing store. Deliberately
        # separate from self.learning (LearningSystem, the natural-
        # language learning pipeline above) - this is a distinct,
        # execution-outcome-only stream of records (requirement: "do
        # not add new learning algorithms yet"; ExecutionLearning
        # itself is reused completely unchanged).
        self.execution_learning = ExecutionLearning()
        self.learning_records = LearningRecordStore()
        self.health = HealthSystem(self.memory, self.skills, self.upgrades.versions)

        # Language Learning Foundation (Prompt 416, see
        # language_intelligence/language_learning_store.py). Reuses this
        # Core's own MemorySystem (self.memory) for storage - no second,
        # parallel memory system - and is independent of which
        # LanguageIntelligenceCore backend is configured today
        # (deterministic fallback) or later (a local model): a future
        # learning module records structured words/phrases/sentence
        # patterns here through learn_language_item() below, one
        # language/locale at a time, without this class or anything else
        # needing to change.
        self.language_learning = LanguageLearningStore(self.memory)

        # Learned Language Relationships (Prompt 417, see
        # language_intelligence/language_relationships.py): structured
        # links between the learned items above (and, optionally, a
        # concept in self.knowledge). Composes the SAME self.memory,
        # self.language_learning and self.knowledge - no second
        # relationship database - and is reached only through
        # relate_language_items() / get_language_relationships() below.
        self.language_relationships = LanguageRelationshipStore(
            self.memory, language_learning=self.language_learning, knowledge=self.knowledge,
        )

        # Learned Expression Variation Matching (Prompt 438, see
        # language_intelligence/learned_expression_variation_matcher.py):
        # a small, deterministic, READ-ONLY layer that connects an
        # expression to a learned one via an EXPLICIT, already-stored
        # relationship (Prompt 417) - never a fuzzy or invented match.
        # Composes the SAME self.language_learning and
        # self.language_relationships above - no second store, no second
        # matching scheme. Constructed before self.meaning_resolver and
        # self.pattern_matcher (just below) so both can be given this
        # SAME instance as an optional fallback - never a second,
        # disagreeing matcher. Reached directly through
        # match_learned_expression_variation() below.
        self.expression_variation_matcher = LearnedExpressionVariationMatcher(
            self.language_learning, self.language_relationships,
        )

        # Learned Meaning Resolution (Prompt 418, see
        # language_intelligence/meaning_resolution.py): a deterministic,
        # bounded, READ-ONLY lookup of what the two stores above (and the
        # concepts in self.knowledge) have learned an expression to mean.
        # Owns no storage and is reached only through
        # resolve_language_meaning() below. Constructed before
        # self.language_intelligence (just below) so that Core's
        # DeterministicFallbackBackend can be given this SAME instance
        # (Prompt 419) - never a second, disagreeing resolver. Given the
        # SAME self.expression_variation_matcher above (Prompt 438) as an
        # optional fallback for an expression that matches no learned
        # item directly.
        self.meaning_resolver = MeaningResolver(
            self.language_learning, self.language_relationships, knowledge=self.knowledge,
            variation_matcher=self.expression_variation_matcher,
        )

        # Learned Meaning Disambiguation (Prompt 420, see
        # language_intelligence/learned_meaning_disambiguation.py): a
        # small, deterministic, READ-ONLY layer over the resolver above -
        # it decides, using only language/topic/context information this
        # Core already computes elsewhere, whether several learned
        # meanings for one expression can be narrowed to one, or must be
        # reported as genuinely ambiguous. Owns no storage of its own and
        # is reached only through DeterministicFallbackBackend's optional
        # `meaning_disambiguator` (just below) and
        # disambiguate_learned_meaning() below.
        self.meaning_disambiguator = LearnedMeaningDisambiguator()

        # Learned Sentence Pattern Matching (Prompt 421, see
        # language_intelligence/learned_pattern_matching.py): a small,
        # deterministic, READ-ONLY matcher over the SAME
        # self.language_learning store above (item_type=
        # ITEM_TYPE_PATTERN) - no second pattern database. Owns no
        # storage of its own and is reached only through
        # DeterministicFallbackBackend's optional `pattern_matcher`
        # (just below) and match_learned_pattern() below.
        self.pattern_matcher = LearnedPatternMatcher(
            self.language_learning, variation_matcher=self.expression_variation_matcher,
        )

        # Learned Sentence Structure Extraction (Prompt 422, see
        # language_intelligence/learned_sentence_structure.py): reports
        # the ordered fixed/variable components of a message that matches
        # a learned pattern. Composes self.pattern_matcher above (no
        # second matcher, no storage of its own) and is reached only
        # through DeterministicFallbackBackend's optional
        # `structure_extractor` (just below) and
        # extract_sentence_structure() below.
        self.sentence_structure_extractor = LearnedSentenceStructureExtractor(
            self.pattern_matcher)

        # Learned Sentence Pattern Teaching (Prompt 423, see
        # language_intelligence/learned_pattern_teaching.py): the one
        # explicit operation for teaching a sentence pattern. Composes the
        # SAME self.language_learning store above - a taught pattern is an
        # ordinary item_type=pattern item that self.pattern_matcher and
        # self.sentence_structure_extractor already read. No second store,
        # matcher or pattern model; reached only through
        # teach_sentence_pattern() below.
        self.pattern_teacher = LearnedPatternTeacher(self.language_learning)

        # Learned Pattern Meaning Binding (Prompt 424, see
        # language_intelligence/learned_pattern_meaning.py): the one
        # explicit operation for binding a taught meaning/intention to a
        # learned sentence pattern, and the read-only retrieval of it for
        # a recognized message. Composes the SAME self.language_learning
        # and self.language_relationships stores above (a meaning is an
        # item_type="meaning" item, the binding a Prompt 417
        # relationship - no second store) and the SAME
        # self.meaning_disambiguator (Prompt 420) for several bound
        # meanings. Reached through DeterministicFallbackBackend's
        # optional `pattern_meaning_binder` (below) and
        # bind_pattern_meaning() / resolve_pattern_meaning() below.
        self.pattern_meaning_binder = LearnedPatternMeaningBinder(
            self.language_learning, self.language_relationships,
            disambiguator=self.meaning_disambiguator)

        # Structured Response Planning (Prompt 425, see
        # language_intelligence/response_planning.py): the stateless,
        # dependency-free planner that turns a LanguageUnderstandingResult
        # into a ResponsePlan (what a response must contain - never
        # response text). It reads no store and writes nothing. Handed to
        # the LanguageIntelligenceCore below, which plans every
        # understanding it returns; reached explicitly through
        # plan_language_response() / get_last_response_plan() below.
        self.response_planner = ResponsePlanner()

        # Language Intelligence Core (Prompt 397, see language_intelligence/).
        # Built on this Core's own, already-existing self.understanding
        # (never a second UnderstandingEngine instance) via
        # DeterministicFallbackBackend - today's only backend, and
        # exactly as capable/limited as self.understanding already is.
        # Also given this Core's own self.meaning_resolver (Prompt 419)
        # so understand() can attach learned meanings for this message's
        # candidate expressions - see deterministic_fallback_backend.py.
        # self.last_language_understanding is the most recent
        # LanguageUnderstandingResult produced through the
        # conversation path (see _handle_conversation) - None until
        # the first ordinary conversational message is processed;
        # never populated for AEL input or a goal-oriented message
        # (see process_input/_handle_goal_or_conversation), same scope
        # as self.last_response_context above.
        self.language_intelligence = LanguageIntelligenceCore(
            backend=DeterministicFallbackBackend(
                self.understanding, meaning_resolver=self.meaning_resolver,
                meaning_disambiguator=self.meaning_disambiguator,
                pattern_matcher=self.pattern_matcher,
                structure_extractor=self.sentence_structure_extractor,
                pattern_meaning_binder=self.pattern_meaning_binder),
            response_planner=self.response_planner,
        )
        self.last_language_understanding = None
        # The most recent ResponseGenerationResult produced through the
        # real conversation path (see _handle_conversation's "1d",
        # Prompt 402) - the smallest compatible addition needed so a
        # caller/test can see what the configured backend/provider/
        # runtime actually returned, same lifecycle/scope as
        # self.last_language_understanding above (None until the first
        # ordinary conversational message is processed; never set for
        # AEL or goal-oriented input).
        self.last_language_response = None
        # Prompt 579: the most recent ConversationResponse (language_
        # intelligence/conversation_response.py, Prompt 431) produced
        # through the real conversation path (see _handle_conversation's
        # "1d") - same lifecycle/scope as self.last_language_response
        # above (None until the first ordinary conversational message is
        # processed; never set for AEL or goal-oriented input). Read
        # straight off this same call's LanguageIntelligenceCore.get_last_
        # conversation_response() immediately after generate_response()
        # returns - never rebuilt or recomputed here. This is what makes
        # `correction_application_result_usable` (Prompt 578, itself
        # forwarded unchanged from ResponseGenerationOutcome/Prompt 577)
        # visible at this Core boundary - the final conversation-handling
        # layer immediately before process_input() returns the reply to
        # its caller/UI - without recomputing it a second time.
        self.last_conversation_response = None
        # Prompt 615: this Core's own boundary onto the same
        # ResponseGenerationOutcome (Prompt 428) that LanguageIntelligenceCore
        # already builds and caches as its own get_last_response_generation_
        # result() for the SAME generate_response() call that produces
        # self.last_conversation_response above - never a second
        # computation, never rebuilt. Same lifecycle/scope as
        # self.last_conversation_response (None until the first ordinary
        # conversational message is processed; never set for AEL or
        # goal-oriented input; left untouched by reset_context(), exactly
        # like last_conversation_response/last_language_response). See
        # get_last_response_generation_result().
        self.last_response_generation_result = None
        # Prompt 580: the smallest backward-compatible response-handling
        # state that consumes `self.last_conversation_response.
        # correction_application_result_usable` at this same Core
        # boundary - never a second computation, never re-applies/re-
        # retrieves/re-selects a correction. Same lifecycle/scope as
        # self.last_conversation_response above (None until the first
        # ordinary conversational message is processed; never set for
        # AEL or goal-oriented input). Kept in sync with
        # self.last_conversation_response by
        # _refresh_last_response_correction_usable() below, at every
        # existing call site that already caches that response. See
        # get_last_response_correction_usable().
        self.last_response_correction_usable = None
        # Prompt 613: the smallest backward-compatible response-handling
        # state that consumes `self.last_conversation_response.
        # normalized_input` at this same Core boundary - never a second
        # computation, never re-normalizes the text. Same lifecycle/scope
        # as self.last_conversation_response above (None until the first
        # ordinary conversational message is processed; never set for
        # AEL or goal-oriented input). Kept in sync with
        # self.last_conversation_response by
        # _refresh_last_response_normalized_input() below, at every
        # existing call site that already caches that response. See
        # get_last_response_normalized_input().
        self.last_response_normalized_input = None
        # The most recent CorrectionLearningHandoffResult produced by
        # the correction-learning storage handoff added in Prompt 562
        # (see _store_resolved_correction_learning below) - None until
        # the first RESOLVED correction is processed; never set for any
        # other message (ordinary conversation, AEL, goal-oriented,
        # AMBIGUOUS/UNRESOLVED correction). Same "expose the most
        # recent structured result for inspection/testing" convention
        # as self.last_language_understanding/self.last_language_response
        # above - read-only from a caller's perspective, only ever
        # written by _store_resolved_correction_learning.
        self.last_correction_learning_handoff_result = None

        self._first_time_setup()
        # Best-effort only (see PlatformAdapter.log docstring) - never
        # allowed to affect startup even if the platform's logging sink
        # is unavailable.
        get_platform().log("core", f"Core initialized (version {APP_VERSION})")

    def _first_time_setup(self):
        # Always keep the recorded app_version current - it reflects
        # which build of the software is running, not a one-time stamp.
        self.memory.set_config("app_version", APP_VERSION)
        self.skills.seed_default_skills()
        self.capabilities.seed_planned_capabilities()
        # code_analysis now has a real implementation (AST-based, see
        # code_intelligence/python_inspector.py) - flip it from the
        # default "planned" placeholder to genuinely active. Safe to
        # call every startup: set_enabled is a plain idempotent UPDATE.
        self.capabilities.set_enabled("code_analysis", True, status="active")

    # ------------------------------------------------------------------
    # Main conversational entry point
    # ------------------------------------------------------------------
    def process_input(self, raw_text):
        text = self.input_system.normalize(raw_text)
        if not text:
            return "Say something and I'll try to respond."

        self.memory.log_message("user", text)
        parsed = self.parser.parse(text)

        if parsed.kind == "ael":
            reply = self._handle_ael(parsed.text)
        else:
            reply = self._handle_goal_or_conversation(parsed.text, raw_text)

        self.memory.log_message("assistant", reply)
        # Recorded only once the reply exists, so while the message above
        # is being handled the context holds the turns *before* it.
        self.context.add_turn(text, reply)
        return reply

    def _handle_ael(self, text):
        results = self.ael.run(text)
        lines = []
        for r in results:
            prefix = "OK" if r.success else "ERROR"
            lines.append(f"[AEL {prefix}] {r.message}")
        return "\n".join(lines)

    def _handle_goal_or_conversation(self, text, raw_text):
        """Deterministic, safe first check ahead of the existing
        conversation flow: if `text` clearly reads as a goal-oriented
        request (see planning/goal_detection.is_goal_oriented - a
        fixed, hand-picked prefix lexicon, never inferred/scored/
        randomized), create exactly one Goal for it through this
        Core's own create_goal() - which also starts an empty Plan
        for it (see create_goal below) - and return a clear,
        structured reply describing what was created, instead of
        falling through to _handle_conversation.

        Everything else (ordinary questions, statements, and unknown
        input - anything is_goal_oriented() doesn't recognize) is
        handled exactly as before, by _handle_conversation(text) -
        this method changes nothing about that existing behaviour; it
        only decides, once, up front, whether to intercept the
        request before reaching it.

        `raw_text` (the original, un-normalized argument
        process_input() received) - rather than `text`, which has
        already been through InputSystem.normalize()'s own whitespace
        collapsing - is what's stored as the Goal's own original_text,
        so the Goal keeps the user's exact original wording (see
        planning/goal.py's own module docstring on why original_text
        exists) rather than an already-once-normalized copy of it.

        Only ever calls create_goal() once per call to this method -
        this is what "no duplicate Goal objects for the same request"
        means: nothing here loops, retries, or calls it a second time
        for the same input."""
        if is_goal_oriented(text):
            goal = self.create_goal(raw_text)
            return self._format_goal_created_reply(goal)
        return self._handle_conversation(text)

    def _format_goal_created_reply(self, goal):
        """The one place that shapes a "Goal created" reply, so every
        goal-oriented request handled by _handle_goal_or_conversation
        gets exactly the same clear, structured (labeled-field) text
        back - same "one place shapes this" convention as
        PlanManager._propagation_result. Still a plain string (not a
        dict) - process_input()'s own contract, and every existing
        caller's `assertIsInstance(reply, str)` check, is unchanged by
        this stage's presence."""
        return (
            "[GOAL CREATED]\n"
            f"goal_id: {goal.goal_id}\n"
            f"goal_type: {goal.goal_type}\n"
            f"status: {goal.status}\n"
            f"confidence: {goal.confidence:.2f}\n"
            f"original_text: {goal.original_text}"
        )

    def _format_correction_acknowledged_reply(self, correction_understanding):
        """The one place that shapes a "correction acknowledged" reply
        (Prompt 560) - same "one place shapes this" convention as
        `_format_goal_created_reply` and `PlanManager._propagation_
        result`. Only ever called with an already-RESOLVED
        `correction_understanding` dict (see the caller in
        `_handle_conversation`'s step 1e); never called with None,
        AMBIGUOUS, or UNRESOLVED. Reports exactly the fields already
        present on that dict - never a fabricated or inferred one - so
        when `corrected_expression` is absent (the correction was
        supplied as a `corrected_meaning` instead), that line is simply
        omitted rather than printed as a guess."""
        lines = [
            "[CORRECTION ACKNOWLEDGED]",
            f"original_expression: {correction_understanding['original_expression']}",
        ]
        if correction_understanding.get("corrected_expression") is not None:
            lines.append(f"corrected_expression: {correction_understanding['corrected_expression']}")
        if correction_understanding.get("corrected_meaning") is not None:
            lines.append(f"corrected_meaning: {correction_understanding['corrected_meaning']}")
        if correction_understanding.get("language") is not None:
            lines.append(f"language: {correction_understanding['language']}")
        return "\n".join(lines)

    def _store_resolved_correction_learning(self, correction_understanding):
        """Prompt 562. Connects the EXISTING correction-learning storage
        handoff (Prompt 458's `handoff_correction_learning_input_with_
        result()`, itself an unmodified thin wrapper over Prompt 457's
        `handoff_correction_learning_input()` -> Prompt 416's
        `LanguageLearningStore.learn_item()`) to Core's request path, for
        the exact `correction_understanding` dict step 1e below already
        has for a RESOLVED correction. Only a call site is added here -
        see docs/section2_correction_learning_storage_audit_prompt561.md
        for why nothing else was missing.

        Reconstruction: `correction_understanding` is the `.to_dict()`
        output of a real `language_intelligence.correction_understanding.
        CorrectionUnderstandingResult` (Prompt 439) - flattened one step
        upstream, in `DeterministicFallbackBackend._build_correction_
        understanding()`, before Core ever saw it (the Prompt 561
        finding). That `to_dict()`'s keys (`status`, `original_expression`,
        `corrected_expression`, `corrected_meaning`, `language`, `locale`,
        `source_text`, `confidence`) are exactly that same class's own
        constructor keyword arguments, so `_CorrectionUnderstanding(
        **correction_understanding)` is a direct, lossless reconstruction
        of the original object - not new logic, not a guess at missing
        fields, not a second correction-understanding structure.

        That reconstructed object is then passed through the EXISTING,
        already-tested adapter chain, unmodified, in its existing order:

            map_correction_understanding_to_result()          (Prompt 442)
            -> map_correction_understanding_result_to_feedback_record()
                                                                (Prompt 449)
            -> convert_correction_feedback_to_learning_input() (Prompt 455)
            -> handoff_correction_learning_input_with_result() (Prompt 458)

        `convert_correction_feedback_to_learning_input()` returns `None`
        for a feedback record with `is_valid_feedback` not True; this
        method never calls the handoff for a `None` learning input, so a
        malformed reconstruction never reaches the learning layer. (In
        practice the caller below only invokes this for STATUS_RESOLVED,
        which `map_correction_understanding_result_to_feedback_record()`
        always marks `is_valid_feedback=True`, but this method does not
        assume that - it checks the actual value produced.)

        Exactly-once guarantee: this method calls
        `handoff_correction_learning_input_with_result()` exactly one
        time, and only that one existing entry point - never followed by
        `store_accepted_correction_learning_input()` for the same data
        (the Prompt 561 audit's duplicate-write finding: that second
        function would call `store.learn_item()` again for identical
        data). `_handle_conversation()` calls this method at most once
        per `process_input()` call (step 1e runs once, and only when
        `correction_understanding["status"] == CORRECTION_STATUS_
        RESOLVED`), so one eligible correction produces exactly one
        `learn_item()` write via this path.

        Uses Core's own real, SQLite-backed `self.language_learning`
        (Prompt 416) - the one store the Prompt 561 audit confirmed the
        storage/retrieval layer already writes to and reads from
        correctly. No new database, table, or memory system is created
        or touched.

        Stores the outcome on `self.last_correction_learning_handoff_
        result` for inspection/testing (same convention as `self.last_
        language_understanding`/`self.last_language_response`) and also
        returns it. Never raises: `handoff_correction_learning_input_
        with_result()` already converts the learning layer's own
        `ValueError`/`TypeError` into a `STATUS_FAILED` result rather
        than propagating (see correction_learning_handoff_result.py);
        this method adds no additional error handling of its own because
        none is needed.
        """
        reconstructed = _CorrectionUnderstanding(**correction_understanding)
        mapped_result = map_correction_understanding_to_result(reconstructed)
        feedback_record = map_correction_understanding_result_to_feedback_record(mapped_result)
        learning_input = convert_correction_feedback_to_learning_input(feedback_record)
        if learning_input is None:
            self.last_correction_learning_handoff_result = None
            return None
        handoff_result = handoff_correction_learning_input_with_result(
            learning_input, self.language_learning)
        self.last_correction_learning_handoff_result = handoff_result
        return handoff_result

    def _apply_resolved_correction_to_knowledge(self, correction_understanding):
        """Prompt 634. Connects a RESOLVED explicit correction (the
        existing "not X, I mean Y" marker, already detected and
        structured by Section 2 - never re-parsed here) to the
        Prompt 633 `LearningSystem.correct()` path.

        The marker names the wrong text (`original_expression`) and its
        replacement, so it is matched EXACTLY (the existing Prompt
        473-477 guarded application check, reused unchanged) against
        the stored knowledge descriptions. Only when exactly ONE
        knowledge record's description contains the original text is
        that record corrected in place; no match (the marker was about
        something that is not stored knowledge, e.g. a misspelling) or
        several matches (ambiguous) write nothing at all - no knowledge
        row, no learning event. Returns the corrected record or None.
        Ordinary statements never reach this: only STATUS_RESOLVED
        corrections do, and nothing is created for an unknown target.
        """
        original = correction_understanding.get("original_expression")
        corrected = correction_understanding.get("corrected_expression")
        if corrected is None:
            corrected = correction_understanding.get("corrected_meaning")
        if not isinstance(original, str) or not isinstance(corrected, str):
            return None

        request = CorrectionApplicationRequest(
            is_valid=True, kind=REQUEST_KIND_APPLY_CORRECTION,
            original_expression=original, corrected_expression_or_meaning=corrected,
            language=correction_understanding.get("language"),
        )
        applied = []
        for record in self.knowledge.all():
            # Prompt 665: this scan picks the target IMPLICITLY (by description
            # text), and correct() writes "active". An explicitly inactive record
            # must not be silently reactivated by a target the user never named,
            # so it is not a candidate here. Explicit LearningSystem.correct(name)
            # still reactivates (unchanged).
            if record.get("status") == "inactive":
                continue
            description = record.get("description")
            if not isinstance(description, str):
                continue
            outcome = apply_correction_request_with_validation(request, description)
            if outcome.status == CORRECTION_APPLIED:
                applied.append((record, outcome.corrected_text))
        if len(applied) != 1:
            return None

        record, corrected_description = applied[0]
        try:
            return self.learning.correct(
                record["name"], corrected_description, source="user_correction",
                source_text=correction_understanding.get("source_text"),
                learning_method="explicit_correction",
            )
        except ValueError:
            return None  # invalid correction: correct() wrote nothing

    def _handle_conversation(self, text):
        """The real conversation pipeline (Prompt 388):

            text -> Input Understanding -> Context Retrieval
                 -> Relevance Selection -> Response Construction
                 -> (store useful info) -> reply

        (Relevance Selection over *recent conversation turns* - see
        _recall_from_relevant_context - is consulted last, at the
        fallback, where its result is handed to Response Construction
        via _construct_fallback_reply - see that method, Prompt 391.)

        Every stage below reuses an existing system - nothing here is a
        second, competing parser/learner/reasoner. See core/core.py's
        module docstring and the individual systems (understanding/,
        learning/, reasoning/) for what each one actually does.
        """
        # 1. Check learned skills first (keyword-triggered responses) -
        # unchanged priority from before this stage.
        skill = self.skills.find_matching_skill(text)
        if skill:
            return skill["response"]

        # 1b. Active Conversation Topic (Prompt 393). Read-only
        # Relevance Selection + Reference Resolution (Prompts 390/392)
        # are computed once here, from the turns *before* this message,
        # and reused by the fallback at step 5 - nothing is selected
        # twice. Keyword-matched skill replies (greetings and the like)
        # return above and deliberately do not move the topic.
        relevant_context = self.get_relevant_context(text)
        resolved_reference = self.resolve_reference(text, relevant_context)
        active_topic = self.topic_tracker.update(text, relevant_context, resolved_reference)
        self.conversation_state.update(
            text, active_topic, self.topic_tracker.thread, resolved_reference)

        # 1c. Language Intelligence Core (Prompt 397). Reuses the exact
        # relevant_context/resolved_reference/active_topic already
        # computed just above (never a second, competing computation of
        # any of them) to produce a structured LanguageUnderstandingResult,
        # recorded for inspection/use by step 1d immediately below. Does
        # not itself affect which branch this method takes, nor the
        # reply text ultimately returned - see core/core.py's own module
        # docstring and language_intelligence/language_intelligence_core.py
        # for why.
        self.last_language_understanding = self.language_intelligence.understand(
            text, context=self.context, relevant_context=relevant_context,
            resolved_reference=resolved_reference, active_topic=active_topic,
        )
        self._attach_conversation_state(self.last_language_understanding)
        # Prompt 501: when exactly one already-taught knowledge entry is
        # directly relevant to this message, make it available to the
        # response-generation path (via the understanding); otherwise
        # nothing is attached and everything below is exactly as before.
        self._attach_learned_knowledge(self.last_language_understanding, text)
        # Prompt 567: connects the existing Prompt 566 trigger to the
        # existing Prompt 565 retrieval adapter at this same "optional,
        # best-effort attachment" point - see
        # _attach_correction_application_candidate's own docstring.
        # Never affects which branch this method takes below (including
        # the Prompt 560 correction-acknowledgement check at step 1e,
        # which still reads only correction_understanding, unchanged).
        self._attach_correction_application_candidate(self.last_language_understanding)
        # Prompt 572: connects the existing Prompt 570 application
        # operation to the candidate just attached above - see
        # _attach_correction_application_result's own docstring. Runs
        # exactly once per understand() call, immediately after the
        # candidate attachment it depends on; never retrieves or
        # selects a candidate again.
        self._attach_correction_application_result(self.last_language_understanding)
        # (Prompt 425: that result already carries `response_plan` - the
        # structured requirements of a response, planned by the same
        # LanguageIntelligenceCore from this understanding alone. It is
        # never response text and does not affect the branch taken
        # below; see get_last_response_plan().)

        # 1d. Language Intelligence Core response generation (Prompt
        # 402 - this is the connection this stage adds). Hands the
        # exact LanguageUnderstandingResult just produced above to this
        # same core's generate_response(), which routes it to whichever
        # backend/provider/runtime is actually configured (see
        # language_intelligence/language_intelligence_core.py). With
        # today's only configured backend (DeterministicFallbackBackend,
        # see __init__ above) this always reports STATUS_DEFERRED - an
        # explicit, structured way of saying "this backend does not
        # generate text; fall through to the existing pipeline below" -
        # so ordinary conversation is completely unaffected by this
        # step's presence, exactly as before Prompt 402. Only a
        # genuinely configured backend/provider/runtime that returns
        # STATUS_GENERATED with real `response_text` (never fabricated
        # here) short-circuits the rest of this method, and does so
        # through this same, single process_input() response path -
        # message/context storage still happen exactly once, in
        # process_input(), after this method returns.
        self.last_language_response = self.language_intelligence.generate_response(
            self.last_language_understanding, context=self.context
        )
        # Prompt 579: the SAME generate_response() call just above already
        # built and cached its own ConversationResponse (Prompt 431) on
        # this same LanguageIntelligenceCore - read it here, once, via the
        # existing get_last_conversation_response() getter and cache it on
        # this Core exactly like last_language_response just above. Never
        # rebuilt, never recomputed: this is a straight forward of the
        # already-produced object (and, on it, the already-produced
        # correction_application_result_usable) to this Core boundary.
        self.last_conversation_response = self.language_intelligence.get_last_conversation_response()
        # Prompt 615: same straight forward as last_conversation_response
        # just above, for the SAME call's ResponseGenerationOutcome - see
        # get_last_response_generation_result()'s own docstring.
        self.last_response_generation_result = (
            self.language_intelligence.get_last_response_generation_result())
        # Prompt 580: consume that same cached ConversationResponse's
        # correction_application_result_usable at this Core boundary -
        # see _refresh_last_response_correction_usable()'s own docstring.
        self._refresh_last_response_correction_usable()
        # Prompt 613: same Core-boundary refresh for normalized_input -
        # see _refresh_last_response_normalized_input()'s own docstring.
        self._refresh_last_response_normalized_input()
        # Prompt 413: `is_generated` = real model output (STATUS_GENERATED
        # with text) - returned exactly as produced (not rewritten, not
        # duplicated). Anything else - deferred, or a model failure
        # (`needs_fallback`, with its structured inference_status /
        # error_code kept on last_language_response) - falls through to the
        # existing deterministic pipeline below; no text is invented.
        if self.last_language_response.is_generated:
            return self.last_language_response.response_text

        # 1e. Explicit Correction Acknowledgement (Prompt 560). Reuses
        # the exact `correction_understanding` already computed above as
        # part of `self.last_language_understanding` (Prompt 439/440's
        # existing, deterministic `build_correction_understanding()` -
        # see language_intelligence/correction_understanding.py - never
        # re-detected or re-parsed here). Before Prompt 560, this field
        # was computed on every message but never read by anything else
        # in this method, so an explicit "not X, I mean Y" message fell
        # all the way through steps 2-5 to the same generic fallback as
        # any other unrecognized phrase (see
        # docs/section2_language_intelligence_prompt560_integration.md
        # for the confirmed before/after behavior).
        #
        # Only STATUS_RESOLVED (both an original expression and a
        # corrected expression/meaning were present) short-circuits the
        # reply here - AMBIGUOUS, UNRESOLVED, and "no correction data at
        # all" (None) all fall through to step 2 exactly as before this
        # stage existed. Nothing is stored, learned, looked up, or
        # applied anywhere else: this step only turns an already-built,
        # already-structured result into an honest acknowledgement of
        # what was understood, the same "structure, don't fabricate"
        # posture correction_understanding.py's own module docstring
        # already documents. It never invents a corrected_expression or
        # corrected_meaning that is not already present on the result.
        #
        # Prompt 562: a RESOLVED correction is now ALSO handed to the
        # existing correction-learning storage handoff (see
        # _store_resolved_correction_learning above) before the same
        # acknowledgement reply is returned - one call, exactly once,
        # through the existing already-tested adapter/storage chain.
        # AMBIGUOUS, UNRESOLVED, and "no correction data at all" (None)
        # still never reach the storage handoff, exactly as they never
        # reached the acknowledgement reply above.
        correction_understanding = self.last_language_understanding.correction_understanding
        if correction_understanding is not None and correction_understanding["status"] == CORRECTION_STATUS_RESOLVED:
            self._store_resolved_correction_learning(correction_understanding)
            self._apply_resolved_correction_to_knowledge(correction_understanding)
            return self._format_correction_acknowledged_reply(correction_understanding)

        # 2. Input Understanding + (conditional) Learning. Reuses the
        # existing learn_from_text() entry point end to end: raw text
        # -> UnderstandingEngine.understand() (context-aware - this is
        # also what lets the Reasoning Engine below resolve "it"/"this"
        # against what was just said) -> LearningSystem.learn_from_-
        # understanding(), which only ever persists a candidate the
        # (existing, deterministic) Learning Decision step approves -
        # see learning/learning_decision.py. Relation extraction only
        # ever fires for sentence_type == "statement"
        # (understanding/relation_extraction.py), so calling this for a
        # question or an unrecognized phrase is a safe no-op: nothing
        # is learned, but the message is still recorded into short-term
        # conversational context for the Reasoning stage below to use.
        learning_result = self.learn_from_text(text, auto_commit=True, use_context=True)
        if learning_result.learned_items:
            # Something new (or updated) was actually just taught in
            # plain conversation - acknowledge it honestly instead of
            # falling through to a lookup of the very thing we just
            # stored (Stage: "store useful conversational information
            # when appropriate").
            return self._format_learned_reply(learning_result)

        # 3. Context Retrieval + Reasoning. The Reasoning Engine's own
        # reason() pipeline (reasoning/reasoning_engine.py, Stage 5) is
        # query parsing -> context resolution -> knowledge retrieval ->
        # reasoning, ending in a structured ReasoningResult whose status
        # is always one of ANSWERED/UNKNOWN/AMBIGUOUS/CONTRADICTION/
        # LIMIT_REACHED - never a fabricated guess. `self.context` is
        # passed through so a follow-up like "What does it use?" can
        # resolve "it" against the previous turn.
        reasoning_result = self.reasoning.reason(text, context=self.context)
        if reasoning_result.status == STATUS_ANSWERED and reasoning_result.answer:
            return reasoning_result.answer

        # 4. Relevance Selection fallback - the original direct/
        # substring concept lookup, kept for free-text phrasings
        # reason()'s explicit query patterns don't recognize (e.g.
        # "Tell me about Python" has no "what is"/"does X use"
        # structure for parse_query() to key off, but still names a
        # known concept by word). KnowledgeSystem.search() underneath
        # this now ranks by deterministic keyword overlap rather than
        # recency alone, so the most relevant of several matches wins.
        best = self._find_best_known_concept(text)
        if best:
            if best.get("description"):
                return f"Here's what I know about '{best['name']}': {best['description']}"

            # No description yet, but the Reasoning Engine may still know
            # something about it purely through relationships (e.g. it
            # was auto-created as a stub by a RELATE). Use that instead
            # of falling all the way through to the generic fallback.
            rel_summary = self.reasoning.summarize_relationships(best["name"])
            if rel_summary:
                return (
                    f"I don't have a description for '{best['name']}' yet, but here's "
                    f"what I've learned through relationships: {rel_summary}"
                )

        # 5. Response Construction (Prompt 391): the fallback is where
        # Response Construction actually receives the output of
        # Relevance Selection (context/relevance.py, Prompt 390) as its
        # own explicit input, rather than looking it up itself. Context
        # Retrieval + Relevance Selection happen here, once, via the
        # same get_relevant_context() Prompt 390 already exposed - nothing
        # new is computed, nothing new is stored - and the resulting
        # RelevantContextResult is handed to _construct_fallback_reply()
        # as a value distinct from `text` (the current user input), so
        # that method never has to re-select anything to use it. If the
        # user themselves said something earlier in this conversation
        # that covers the question, it is quoted back, verbatim and
        # labelled as theirs - never as an answer.
        return self._construct_fallback_reply(
            text, relevant_context, resolved_reference, active_topic, thread=self.topic_tracker.thread
        )

    def _construct_fallback_reply(self, current_input, relevant_context, resolved_reference=None,
                                  active_topic=None, thread=None):
        """Response Construction step for the honest-fallback branch of
        _handle_conversation (see its step 5 above). Takes the things a
        reply is built from as separate, explicit arguments -
        `current_input` (the original user message, kept verbatim and
        never replaced), `relevant_context` (the RelevantContextResult
        already selected for it by context/relevance.py, Prompt 390),
        and `resolved_reference` (the ResolvedReference already
        produced for it by
        context/message_reference_resolution.py, Prompt 392) - instead
        of re-deriving any of them from `current_input` itself. This is
        the one place that shapes the fallback reply text, same "one
        place shapes this" convention as _format_goal_created_reply/
        _format_learned_reply above.

        `resolved_reference` is optional (defaulting to None) purely so
        any older/other caller that only ever passed the first two
        arguments keeps working unchanged - see resolve_reference()
        below, which this falls back to computing exactly the same way
        _recall_from_relevant_context already falls back to computing
        `relevant_context` itself when it isn't supplied.

        Never invents information. Beyond the fixed fallback copy, this
        can add at most one of two things, in this order:
          1. A verbatim quote of something `relevant_context` already
             selected - see _recall_from_relevant_context below for the
             (deliberately strict) rule for picking that quote. This is
             unchanged from Prompt 391.
          2. Failing that - and only for a message that itself reads as
             a command (understanding/sentence_analysis.py:
             SENTENCE_COMMAND, e.g. "Give me three ideas for it.") - if
             `resolved_reference` reports a confident, unambiguous
             resolution (Prompt 392), a verbatim quote of *that* turn
             instead, labelled by the reference word it resolves.
             Restricted to commands deliberately: a *question*'s own
             fallback behavior (quote only when the turn covers every
             meaningful word of the question, or say nothing) is
             already fully owned by _recall_from_relevant_context
             above, and a plain *statement* is never "answered" from
             context at all (see test_a_statement_is_never_answered_-
             from_recent_context) - Prompt 392 only adds a new
             fallback path for the sentence kind neither of those
             already covers.
        When none of the above applies, this returns exactly the same
        text Core returned before Prompt 390/391/392 existed.

        `thread` (Prompt 395, a ConversationThreadState from
        context/active_topic.py) is the fifth, separate input, recorded
        as `thread` in `self.last_response_context`: which conversation
        thread the message belongs to and whether it is a new_topic, a
        follow_up, isolated or ambiguous. Optional (defaulting to the
        tracker's current thread) like the others.

        `active_topic` (Prompt 393, an ActiveTopicResult from
        context/active_topic.py) is the fourth, separate input. Since
        Prompt 394 it takes part in the reply: context/topic_awareness.py
        decides whether the message is clearly a continuation of the
        topic (recorded as `topic_awareness` in
        `self.last_response_context`) and, if so, _topic_context_text
        adds a short topic-aware passage before the AEL hint - never
        invented facts about the topic. It is skipped when the
        existing strict recall already quoted the user (the reply
        already carries the context) and for a verbatim repeat. Optional (defaulting to the tracker's current result) so
        older callers keep working unchanged."""
        if active_topic is None:
            active_topic = self.topic_tracker.current
        if thread is None:
            thread = self.topic_tracker.thread
        topic_awareness = assess_topic_awareness(
            current_input, relevant_context, resolved_reference, active_topic
        )
        self.last_response_context = {
            "current_input": current_input,
            "relevant_context": relevant_context,
            "resolved_reference": resolved_reference,
            "active_topic": active_topic,
            "topic_awareness": topic_awareness,
            "thread": thread,
        }
        reply = "I don't have enough information to answer that yet. "
        recalled = self._recall_from_relevant_context(current_input, relevant_context)
        if recalled:
            reply += f'Earlier in this conversation you said: "{recalled}" '
        elif self.understanding.understand(current_input).sentence_type == SENTENCE_COMMAND:
            if resolved_reference is None:
                resolved_reference = self.resolve_reference(current_input, relevant_context)
            if (resolved_reference.has_reference and not resolved_reference.ambiguous
                    and resolved_reference.resolved_context):
                reply += (
                    f'I think "{resolved_reference.reference_text}" refers to what you '
                    f'said earlier: "{resolved_reference.resolved_context}" '
                )
        if not recalled:
            reply += self._topic_context_text(topic_awareness, reply)
        return reply + (
            "You can teach me using AEL, for example:\n"
            "TEACH sun IS a star at the center of the solar system\n"
            "or ask what I already know with: ASK sun"
        )

    def _topic_context_text(self, topic_awareness, reply_so_far):
        """Prompt 394: the topic-aware part of the fallback reply - empty
        unless `topic_awareness.topic_aware`, so every message that is
        not a clear continuation of the active topic gets exactly the
        reply it got before. Says only what is known: that the message
        is being treated as a follow-up about the topic, the user's own
        verbatim statement backing it (skipped if the reply already
        quotes it), and - explicitly - that nothing further is known
        about the topic. The topic is context, never knowledge."""
        if not topic_awareness.topic_aware:
            return ""
        text = f'I\'m treating this as a follow-up about "{topic_awareness.topic}". '
        support = topic_awareness.supporting_context
        if support and f'"{support}"' not in reply_so_far:
            text += f'What you told me about it: "{support}" '
        text += "I don't know more about it than what you've told me, so I can't suggest specifics yet. "
        return text

    def _recall_from_relevant_context(self, text, relevant_context=None):
        """Consumer of the relevance selection (context/relevance.py):
        for a *question* nothing else could answer, return the user's own
        most relevant earlier *statement* - or None.

        `relevant_context` is the RelevantContextResult Response
        Construction already selected for `text` (see
        _construct_fallback_reply above) - passed in, not recomputed,
        so this never selects a second, possibly-different context for
        the same message. Kept optional (defaulting to
        self.get_relevant_context(text), exactly what earlier stages
        used to do here) purely so any other/older caller of this
        method keeps working unchanged; _handle_conversation itself
        always supplies it now.

        Deliberately strict, so it can only ever repeat something the
        user really said and that really bears on the question:
        the selected turn must contain every meaningful word of the
        question (a lone shared word like "called" isn't enough - "What
        is my dog called?" must not surface a statement about a game),
        and the turn's user text must itself be a statement (not a
        question or an AEL command). Among those, the highest-ranked
        turn wins. An empty/irrelevant selection (nothing scored above
        zero for `text`) always yields None here, same as before
        Prompt 390/391 - this stage adds nothing when there is nothing
        relevant to add."""
        if self.understanding.understand(text).sentence_type != SENTENCE_QUESTION:
            return None
        if relevant_context is None:
            relevant_context = self.get_relevant_context(text)
        for item in sorted(relevant_context.selected, key=lambda i: i["rank"]):
            user_text = item["turn"]["user"]
            if (item["covers_message_terms"]
                    and self.understanding.understand(user_text).sentence_type == SENTENCE_STATEMENT):
                return user_text
        return None

    def _format_learned_reply(self, learning_result):
        """The one place that turns a just-committed LearningResult into
        a readable acknowledgement, reusing the same relation-phrasing
        helper (reasoning/relation_phrasing.py) the Reasoning Engine
        uses to answer questions - so a fact is described the same way
        whether it's being taught or being recalled. Only ever called
        with a non-empty learning_result.learned_items (see caller)."""
        sentences = [
            phrase_relation(item["subject"], item["relation"], item["object"])
            for item in learning_result.learned_items
        ]
        return "Got it, I'll remember that: " + " ".join(sentences)

    def _find_best_known_concept(self, text):
        """Understanding/Analysis step: try precise, case-insensitive
        matches against individual meaningful words from the message
        first (see understanding/term_extraction.py) - this is what lets
        "tell me about indentation" find a concept named "indentation"
        even though that phrase never appears verbatim in storage. Falls
        back to the broader whole-text substring search (handles literal
        phrase matches) if no candidate term matches anything known."""
        # Prompt 667: this result is presented as CURRENT knowledge in the conversational
        # fallback, so explicitly inactive records (Prompt 663) are not candidates - neither
        # by name nor by search. Raw retrieval APIs are unchanged; only this use boundary filters.
        ambiguous_names = set()
        for term in extract_candidate_terms(text):
            resolution = self.knowledge.resolve_current_name(term)
            if resolution["record"]:
                return resolution["record"]
            if resolution["status"] == "ambiguous":
                ambiguous_names.update(resolution["candidates"])

        # Prompt 672: the search fallback must not silently choose ONE of several CURRENT records
        # that differ only by case (Prompt 637 ambiguity): such a group is skipped, unless the
        # message literally contains exactly one variant's exact-case name (exact case wins).
        current = [m for m in self.knowledge.search(text, limit=None) if m.get("status") != "inactive"]
        variants = {}
        for match in current:
            variants.setdefault((match.get("name") or "").lower(), []).append(match)
        for match in current:
            name = match.get("name")
            if name in ambiguous_names:
                continue
            group = variants[(name or "").lower()]
            if len(group) > 1 and [v for v in group if v.get("name") and v["name"] in text] != [match]:
                continue
            return match
        return None

    # ------------------------------------------------------------------
    # Understanding Engine (purely analytical - never writes to memory/
    # knowledge; not wired into the main conversational flow above, so
    # existing AEL/conversation handling in process_input() is
    # completely unaffected by either method below)
    # ------------------------------------------------------------------
    def understand(self, raw_text, use_context=True):
        """Run the Understanding Engine over `raw_text` and return an
        UnderstandingResult. Still writes nothing to memory/knowledge -
        see test_understand_is_available_and_side_effect_free.

        With `use_context=True` (the default), this call is
        context-aware both ways: recent conversational context (see
        context/) is used to resolve simple references ("it", "this",
        "the language", ...) in `raw_text`, and the resulting
        UnderstandingResult is itself appended to that same context
        afterward, so the *next* call can refer back to this one. Pass
        `use_context=False` for a one-off analysis that should neither
        read nor extend short-term context."""
        context = self.context if use_context else None
        result = self.understanding.understand(raw_text, context=context)
        if use_context:
            self.context.add_understanding(result, source="understand")
        return result

    def learn_from_text(self, raw_text, auto_commit=True, use_context=True):
        """Run the full natural-language learning pipeline:

            raw_text -> understand() -> UnderstandingResult
                     -> learning.learn_from_understanding() -> LearningResult

        This is the "USER TEXT -> UNDERSTANDING ENGINE -> ... ->
        PERSISTENT KNOWLEDGE" pipeline as a single call. With
        auto_commit=True (the default) any candidate the Learning
        Decision step approves is actually written to storage and is
        immediately queryable via recall()/search() afterward. Like
        understand(), this is a separate, explicit entry point - it is
        never triggered implicitly by process_input().

        With `use_context=True` (the default) this is also how
        context-aware learning happens end to end: e.g. "Python is a
        programming language." followed by "It uses indentation." (two
        separate calls) learns Python -> USES -> indentation, not
        it -> USES -> indentation - see context/reference_resolution.py."""
        result = self.understand(raw_text, use_context=use_context)
        learning_result = self.learning.learn_from_understanding(result, auto_commit=auto_commit)
        if use_context:
            self.context.annotate_last({
                "learned_items": len(learning_result.learned_items),
                "created_concepts": list(learning_result.created_concepts),
            })
        return learning_result

    # ------------------------------------------------------------------
    # Reasoning Engine (see reasoning/) - a separate, explicit entry
    # point, same pattern as understand()/learn_from_text() above: never
    # triggered implicitly by process_input(), so today's AEL/
    # conversation routing is completely unaffected by its presence.
    # ------------------------------------------------------------------
    def reason(self, query, use_context=True):
        """Run the Reasoning Engine over `query` (a natural-language
        question, or a bare entity name) and return a ReasoningResult.
        With `use_context=True` (the default), a reference word ("it",
        "this") in `query` can be resolved against the same short-term
        conversational context understand()/learn_from_text() populate -
        see context/reference_resolution.py. This call never writes to
        that context itself (a question isn't something to remember as
        if it were a new statement)."""
        context = self.context if use_context else None
        # Prompt 631: this explicit entry point (unlike process_input's
        # own reasoning call) also understands request-form questions
        # ("Tell me about X", "Explain X", a leading "please").
        return self.reasoning.reason(query, context=context, request_forms=True)

    # ------------------------------------------------------------------
    # Language Intelligence Core (see language_intelligence/, Prompt 397)
    # - a separate, explicit entry point, same pattern as
    # understand()/reason() above: never triggered implicitly by
    # process_input() beyond the purely-observational step already
    # described in _handle_conversation (see that method's own "1c").
    # Read-only: never writes to memory/knowledge/context/topic state.
    # ------------------------------------------------------------------
    def understand_language(self, raw_text, use_context=True):
        """Run the Language Intelligence Core over `raw_text` and
        return a LanguageUnderstandingResult (see language_intelligence/
        language_understanding_result.py). With `use_context=True`
        (the default), this computes the same relevant-context/
        resolved-reference/active-topic pieces `_handle_conversation`
        computes for a real conversational turn (via the existing
        get_relevant_context/resolve_reference/get_active_topic - never
        a second, competing computation of any of them) and passes them
        through, so a caller (a test, a future UI/API endpoint) can see
        exactly the structured understanding a real message would
        produce, without that message ever being logged, learned from,
        or replied to. With `use_context=False`, all four are None -
        a one-off analysis exactly like `understand(use_context=False)`
        above."""
        context = self.context if use_context else None
        relevant_context = self.get_relevant_context(raw_text) if use_context else None
        resolved_reference = (
            self.resolve_reference(raw_text, relevant_context) if use_context else None
        )
        active_topic = self.get_active_topic() if use_context else None
        understanding = self.language_intelligence.understand(
            raw_text, context=context, relevant_context=relevant_context,
            resolved_reference=resolved_reference, active_topic=active_topic,
        )
        if use_context:
            self._attach_conversation_state(understanding)
        self._attach_learned_knowledge(understanding, raw_text)
        # Prompt 567: same attachment as the real conversation path (see
        # _attach_correction_application_candidate), so this explicit
        # entry point sees identical structured understanding.
        self._attach_correction_application_candidate(understanding)
        # Prompt 572: same attachment as the real conversation path (see
        # _attach_correction_application_result), so this explicit entry
        # point sees identical structured understanding.
        self._attach_correction_application_result(understanding)
        return understanding

    def _attach_conversation_state(self, understanding):
        """Prompt 405: hand the current compact conversation state to a
        LanguageUnderstandingResult so the existing inference-request
        path (local_model_mapping.build_inference_request) can select
        the relevant part of it. A snapshot copy - read-only, never
        written back from here."""
        if understanding is not None:
            understanding.conversation_state = self.conversation_state.to_dict()

    def select_learned_knowledge(self, message):
        """Prompt 501: the deterministic relevance decision over what the
        user has already taught this Core (its own `self.knowledge`) -
        is exactly one stored knowledge entry directly relevant to
        `message`? Returns a LearnedKnowledgeSelection (status SELECTED /
        NOT_FOUND / AMBIGUOUS / FAILED; see language_intelligence/
        learned_knowledge_context.py). Reuses the existing term
        extraction (`extract_candidate_terms`, as `_find_best_known_
        concept` does) and the existing KnowledgeSystem lookups.
        Read-only: writes nothing, never raises, generates no text."""
        try:
            terms = extract_candidate_terms(message)
        except Exception:  # noqa: BLE001 - a failing term extraction is just "no terms"
            terms = []
        return select_learned_knowledge(message, self.knowledge, candidate_terms=terms)

    def _attach_learned_knowledge(self, understanding, message):
        """Prompt 501: put the selected learned knowledge on
        `understanding.learned_knowledge_context` - only when exactly one
        entry is directly relevant. NOT_FOUND / AMBIGUOUS / FAILED (or any
        error) attach nothing, so response generation behaves exactly as
        it did before this stage. Never raises, never writes.

        Prompt 502: a selected entry must also pass the relevance +
        reliability gate (learning/learned_knowledge_gate.py, built on the
        existing LearningAnalyzer) before it is attached. A rejected entry
        is simply not attached - nothing is injected or invented in its
        place and the message is untouched. The gate's verdict for the
        latest message is kept as `last_learned_knowledge_gate` (None when
        nothing was selected).

        Prompt 503: whenever a verdict is computed, a structured
        `LearnedKnowledgeGateTrace` for it is also kept as
        `last_learned_knowledge_gate_trace` - purely for later internal
        analysis. It is built from the verdict after the accept/reject
        decision is already made, so it cannot influence that decision,
        and it is never attached to `understanding` or otherwise surfaced
        in the response.

        Prompt 504: that same trace is also handed to
        `self.learned_knowledge_decision_statistics.record()`, a running,
        diagnostic-only counter (learning/learned_knowledge_statistics.py)
        of how many evaluations happened and how they were decided. Purely
        additive bookkeeping after the decision above - it cannot change
        it, and it is not surfaced in the response either."""
        self.last_learned_knowledge_gate = None
        self.last_learned_knowledge_gate_trace = None
        if understanding is None:
            return
        try:
            selection = self.select_learned_knowledge(message)
            if not selection.selected:
                return
            gate = evaluate_learned_knowledge_gate(selection, message=message)
            self.last_learned_knowledge_gate = gate
            trace = build_learned_knowledge_gate_trace(gate)
            self.last_learned_knowledge_gate_trace = trace
            self.learned_knowledge_decision_statistics.record(trace)
            if not gate.passed:
                return
            context = selection.to_context()
        except Exception:  # noqa: BLE001 - never breaks the conversation path
            return
        if context is not None:
            understanding.learned_knowledge_context = context

    def _attach_correction_application_candidate(self, understanding):
        """Prompt 567. Connects the EXISTING Prompt 566 conservative
        trigger (`correction_retrieval_trigger.build_correction_
        retrieval_trigger()`) to the EXISTING Prompt 565 retrieval
        adapter (`correction_retrieval_understanding_adapter.retrieve_
        and_attach_correction_application_candidate()`) at the smallest
        safe runtime point: right after `understanding.correction_
        understanding` has already been computed by this same
        `understand()` call, in the SAME place `_attach_conversation_
        state`/`_attach_learned_knowledge` already attach their own
        optional, best-effort information onto the result (see the two
        call sites of this method, in `_handle_conversation`'s step 1c
        and in `understand_language()`).

        Exactly-once per call: the trigger is evaluated once (pure,
        no I/O), and - only when it says `should_attempt=True` -
        `retrieve_and_attach_correction_application_candidate()` is
        called exactly once, which itself performs exactly one store
        lookup, exactly one selection, and attaches at most one
        candidate (see that function's own docstring). When the
        trigger says `should_attempt=False`, no retrieval, lookup, or
        selection happens at all - `understanding.correction_
        application_candidate` is left exactly as the backend produced
        it (`None` for every ordinary message, per Prompt 564).

        Uses Core's own real `self.language_learning` store - the SAME
        store `_store_resolved_correction_learning` writes to and the
        Prompt 565 adapter already expects - no second store, no new
        storage layer.

        Never raises and never breaks the conversation path: a failure
        anywhere in the trigger or retrieval leaves `understanding.
        correction_application_candidate` at whatever it already was
        (typically `None`), exactly like `_attach_learned_knowledge`'s
        own posture.

        No automatic correction application: this only ever populates
        the informational `correction_application_candidate` field for
        a later, separately-scoped reasoning/application stage (Prompt
        567 section 5) - it never rewrites `understanding`, the user's
        message, or any stored memory, and it never changes which
        branch `_handle_conversation` takes (the existing Prompt 560
        correction-acknowledgement check at step 1e still reads only
        `understanding.correction_understanding`, unchanged)."""
        if understanding is None:
            return
        try:
            correction_understanding = understanding.correction_understanding
            trigger = build_correction_retrieval_trigger(correction_understanding)
            if not trigger.should_attempt:
                return
            retrieve_and_attach_correction_application_candidate(
                understanding, self.language_learning,
                trigger.original_expression, language=trigger.language,
            )
        except Exception:  # noqa: BLE001 - never breaks the conversation path
            return

    def _attach_correction_application_result(self, understanding):
        """Prompt 572. Connects the EXISTING Prompt 570 candidate-level
        application operation (`correction_application_candidate_
        operation.apply_correction_application_candidate()`) to the
        `correction_application_candidate` this same `understand()` call
        already attached (via `_attach_correction_application_candidate`
        just above, its own call site immediately before this one in
        both `_handle_conversation` and `understand_language()`).

        Exactly-once per call, and only when there is something to
        apply:

            1. Read `understanding.correction_application_candidate` -
               never retrieved or selected again here; whatever
               `_attach_correction_application_candidate` already put
               there (typically `None` for an ordinary message, per
               Prompt 564/567) is used as-is, unmodified.
            2. `None` (the common case) -> `understanding.
               correction_application_result = None` and return. No
               `CorrectionApplicationResult` is constructed at all, so
               an ordinary message never gets a meaningless `FAILED`
               result.
            3. A candidate exists -> call the existing, unmodified
               `apply_correction_application_candidate(candidate,
               target_text)` (Prompt 570) exactly once - which itself
               already does the eligibility check (Prompt 569),
               request-building (Prompt 473), validation, application,
               and verification (Prompts 475-477/482) - and store its
               returned `CorrectionApplicationResult` as `understanding.
               correction_application_result` (Prompt 571).

        `target_text` is `understanding.original_input` - the SAME
        verbatim message text this whole `understand()` call was built
        from (see LanguageUnderstandingResult's own docstring:
        `original_input` is `raw_text`, untouched), and the SAME kind of
        value every existing `apply_correction_application_candidate()`
        caller/test already passes as `target_text` - never a new or
        re-derived source of text.

        Never raises and never breaks the conversation path: on any
        failure, `understanding.correction_application_result` is left
        as `None` (its Prompt 571 default), exactly like
        `_attach_correction_application_candidate`'s own posture. Never
        mutates `candidate` or `target_text`; never runs a second
        detector, selector, or application pipeline; never touches
        storage; never changes `understanding.correction_application_
        candidate` itself, the user's message, or which branch
        `_handle_conversation` takes (the Prompt 560 correction-
        acknowledgement check still reads only `correction_
        understanding`, unchanged)."""
        if understanding is None:
            return
        candidate = getattr(understanding, "correction_application_candidate", None)
        if candidate is None:
            understanding.correction_application_result = None
            return
        try:
            target_text = understanding.original_input
            understanding.correction_application_result = (
                apply_correction_application_candidate(candidate, target_text)
            )
        except Exception:  # noqa: BLE001 - never breaks the conversation path
            understanding.correction_application_result = None

    def _refresh_last_response_correction_usable(self):
        """Prompt 580: set `self.last_response_correction_usable` straight
        from `self.last_conversation_response.correction_application_
        result_usable` - the smallest existing response-handling decision
        point that can consume that already-produced value. Called once,
        immediately after each existing site that caches `self.last_
        conversation_response` (see `_handle_conversation`'s "1d" and
        `generate_language_response` below); never applies, retrieves,
        selects, or recomputes correction usability itself.

        Backward-compatible by construction: `self.last_conversation_
        response` being None (no ordinary conversational message yet, or
        AEL/goal-oriented input) and a legacy ConversationResponse built
        before Prompt 578 (no `correction_application_result_usable`
        attribute) both fall back to False via `getattr`'s default -
        exactly the previous, unaffected behavior."""
        self.last_response_correction_usable = bool(
            getattr(
                self.last_conversation_response,
                "correction_application_result_usable",
                False,
            )
        )

    def _refresh_last_response_normalized_input(self):
        """Prompt 613: set `self.last_response_normalized_input` straight
        from `self.last_conversation_response.normalized_input` - the
        smallest existing response-handling state that can consume that
        already-produced value. Called once, immediately after each
        existing site that caches `self.last_conversation_response` (see
        `_handle_conversation`'s "1d" and `generate_language_response`
        below); never re-normalizes, recomputes, or falls back to a
        previous response's value.

        Backward-compatible by construction: `self.last_conversation_
        response` being None (no ordinary conversational message yet, or
        AEL/goal-oriented input) and a legacy ConversationResponse built
        before Prompt 612 (no `normalized_input` attribute) both fall
        back to None via `getattr`'s default."""
        self.last_response_normalized_input = getattr(
            self.last_conversation_response,
            "normalized_input",
            None,
        )

    def generate_language_response(self, understanding, cancellation_token=None):
        """Run the Language Intelligence Core's `generate_response` for
        an already-produced LanguageUnderstandingResult (typically from
        `understand_language()` above or from
        `self.last_language_understanding`) and return a
        ResponseGenerationResult (see language_intelligence/
        response_generation.py). With today's deterministic fallback
        backend this always reports STATUS_DEFERRED - see that
        module's own docstring for why reply text is not produced
        here. `cancellation_token` (Prompt 411, optional) is the runtime's
        CancellationToken; cancelling it stops the model inference.

        Prompt 579: like `understand_language()`'s existing correction-
        application attachments above, this explicit entry point also
        caches the SAME call's ConversationResponse (see
        get_last_conversation_response()) - a straight forward of what
        `generate_response()` already built, never a second computation."""
        response = self.language_intelligence.generate_response(
            understanding, context=self.context, cancellation_token=cancellation_token)
        self.last_conversation_response = self.language_intelligence.get_last_conversation_response()
        # Prompt 615: same straight forward as last_conversation_response
        # just above, for the SAME call's ResponseGenerationOutcome - see
        # get_last_response_generation_result()'s own docstring.
        self.last_response_generation_result = (
            self.language_intelligence.get_last_response_generation_result())
        # Prompt 580: same Core-boundary state refresh as
        # _handle_conversation's "1d" - see
        # _refresh_last_response_correction_usable()'s own docstring.
        self._refresh_last_response_correction_usable()
        # Prompt 613: same Core-boundary refresh for normalized_input -
        # see _refresh_last_response_normalized_input()'s own docstring.
        self._refresh_last_response_normalized_input()
        return response

    def get_last_language_understanding(self):
        """The most recent LanguageUnderstandingResult produced through
        the real conversation path (see _handle_conversation's "1c"),
        or None if no ordinary conversational message has been
        processed yet this session."""
        return self.last_language_understanding

    def get_last_language_response(self):
        """The most recent ResponseGenerationResult produced through the
        real conversation path (see _handle_conversation's "1d", Prompt
        402), or None if no ordinary conversational message has been
        processed yet this session. With today's deterministic fallback
        backend this is always STATUS_DEFERRED."""
        return self.last_language_response

    def get_last_conversation_response(self):
        """Prompt 579: the most recent ConversationResponse (language_
        intelligence/conversation_response.py, Prompt 431) produced
        through the real conversation path (see _handle_conversation's
        "1d"), or None if no ordinary conversational message has been
        processed yet this session - same scope/lifecycle as
        get_last_language_response() above. This is this Core's own
        final conversation-handling boundary onto the same
        ConversationResponse LanguageIntelligenceCore already built and
        cached for that call; nothing is rebuilt or recomputed here.

        Exposes `correction_application_result_usable` (Prompt 578) at
        this Core boundary, forwarded unchanged all the way from
        `CorrectionApplicationResult` (Prompt 571) through `ResponsePlan`
        (574), `ResponseGenerationContext` (575), `LearnedResponseDecision`
        (576) and `ResponseGenerationOutcome` (577) - False for an
        ordinary message, a not-applied/unusable correction, or before the
        first ordinary conversational message of this session."""
        return self.last_conversation_response

    def get_last_response_generation_result(self):
        """Prompt 615: the most recent `ResponseGenerationOutcome`
        (language_intelligence/response_generation_outcome.py, Prompt 428)
        produced through the real conversation path (see
        `_handle_conversation`'s "1d" and `generate_language_response()`),
        or None if no ordinary conversational message has been processed
        yet this session - same scope/lifecycle as
        `get_last_conversation_response()` above. This is this Core's own
        boundary onto the same outcome object `LanguageIntelligenceCore.
        get_last_response_generation_result()` already built and cached
        for that same call; nothing is rebuilt or recomputed here, and it
        is exactly `get_last_conversation_response()`'s own source object
        (`ConversationResponse` is itself built from this outcome - see
        `build_conversation_response()`), so
        `get_last_response_generation_result().normalized_input` always
        agrees with `get_last_conversation_response().normalized_input`
        for the same call.

        Left untouched by `reset_context()`, exactly like
        `get_last_conversation_response()`/`get_last_language_response()`
        - no correction retrieval, selection, application, generation, or
        routing behavior is invoked or changed here."""
        return self.last_response_generation_result

    def get_last_response_correction_usable(self):
        """Prompt 580: the smallest existing response-handling decision
        state consuming `get_last_conversation_response().correction_
        application_result_usable` at this Core boundary - see
        `_refresh_last_response_correction_usable()`'s own docstring.
        This is the stable, single public read path for that state - no
        other module reads `self.last_response_correction_usable`
        directly (Prompt 582 confirms this by inspection: prefer this
        getter over the raw attribute for any future caller).

        Returns `None` before the first ordinary conversational message
        of this session, for AEL/goal-oriented input (same scope as
        `get_last_conversation_response()`), and after `reset_context()`
        (Prompt 581) it is the explicit `False` that reset leaves behind
        - `None` and post-reset `False` are both falsy but distinguish
        "never populated" from "explicitly cleared" for a caller that
        cares. Once an ordinary conversational message has been
        processed, always a plain bool: False for an ordinary message, a
        not-applied/unusable correction, or a legacy ConversationResponse
        built before Prompt 578 - the exact same cases
        get_last_conversation_response() itself documents as False/None.
        Never a second computation: refreshed only from the same cached
        ConversationResponse get_last_conversation_response() already
        returns, and reading it repeatedly never re-applies, re-
        retrieves, re-selects, or otherwise mutates anything."""
        return self.last_response_correction_usable

    def get_last_response_normalized_input(self):
        """Prompt 613: the smallest existing response-handling state
        consuming `get_last_conversation_response().normalized_input` at
        this Core boundary - see
        `_refresh_last_response_normalized_input()`'s own docstring.
        This is the stable, single public read path for that state.

        Returns `None` before the first ordinary conversational message
        of this session, for AEL/goal-oriented input (same scope as
        `get_last_conversation_response()`), for a legacy
        ConversationResponse built before Prompt 612, and after
        `reset_context()`. Once an ordinary conversational message has
        been processed, this is exactly `get_last_conversation_response
        ().normalized_input` - never recomputed or re-normalized here,
        and never falls back to a previous response's value. Reading it
        repeatedly never re-normalizes or otherwise mutates anything."""
        return self.last_response_normalized_input

    def plan_language_response(self, understanding):
        """Prompt 425: the ResponsePlan (language_intelligence/
        response_planning.py) for an already-produced
        LanguageUnderstandingResult (typically from `understand_language()`
        above or `self.last_language_understanding`) - what a response
        must contain: status RESOLVED / AMBIGUOUS / UNRESOLVED, the
        resolved meaning or every undecided candidate, the matched
        pattern and variables, the response action, and what is still
        unresolved. Deterministic and read-only: it uses only what the
        understanding already carries - nothing is looked up, retrieved
        or invented, and it never contains response text. Does not touch
        ResponseGeneration; see `generate_language_response()`."""
        return self.language_intelligence.plan_response(understanding)

    def get_last_response_plan(self):
        """Prompt 425: the `response_plan` (a ResponsePlan.to_dict()) of
        the most recent LanguageUnderstandingResult produced through the
        real conversation path (see _handle_conversation), or None if no
        ordinary conversational message has been processed yet this
        session or planning failed for it. Like the understanding it was
        made from, never set for AEL or goal-oriented input."""
        understanding = self.last_language_understanding
        return getattr(understanding, "response_plan", None) if understanding else None

    def use_local_language_model(self, runtime=None, provider=None, **backend_options):
        """Prompt 413: opt in to local-model response generation. Builds a
        `LocalLanguageModelBackend` from `runtime` (or `provider`; see that
        class) and makes it the primary backend of this Core's
        LanguageIntelligenceCore, with this Core's own deterministic
        backend as the Prompt 406 fallback. Understanding stays
        deterministic (it always falls back), and every model failure -
        not configured, unavailable, load failure, resource limit,
        timeout, cancellation, ... - is answered by the existing
        pipeline exactly as before. Nothing is downloaded, loaded or run
        here; calling it never changes the conversation, context, topic
        or memory state. Returns the backend. Core does NOT call this by
        itself: the default stays the deterministic backend."""
        backend = LocalLanguageModelBackend(runtime=runtime, provider=provider, **backend_options)
        self.language_intelligence = LanguageIntelligenceCore(
            backend=backend,
            fallback_backend=DeterministicFallbackBackend(
                self.understanding, meaning_resolver=self.meaning_resolver,
                meaning_disambiguator=self.meaning_disambiguator,
                pattern_matcher=self.pattern_matcher,
                structure_extractor=self.sentence_structure_extractor,
                pattern_meaning_binder=self.pattern_meaning_binder),
            response_planner=self.response_planner)
        return backend

    def get_local_model_readiness(self):
        """Prompt 408: "is the local language model currently ready?" -
        the ModelReadiness (language_intelligence/inference.py:
        MODEL_READY / MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE /
        MODEL_LOAD_FAILED) that this Core's LanguageIntelligenceCore
        reports for its configured backend (Prompt 407). Read-only: no
        inference, no model load, and no conversation, context, memory or
        last-response state is touched. With today's default
        (deterministic) backend there is no local model, so this is
        MODEL_NOT_CONFIGURED."""
        return self.language_intelligence.check_model_readiness()

    # ------------------------------------------------------------------
    # Language Learning Foundation (see language_intelligence/
    # language_learning_store.py, Prompt 416)
    # ------------------------------------------------------------------
    def learn_language_item(self, language, item_type, key, **kwargs):
        """Record (or update) one structured language item - a word,
        phrase, or sentence pattern - for `language`. Thin passthrough to
        this Core's own `self.language_learning`
        (LanguageLearningStore), which persists through the same
        MemorySystem every other structured system on this Core already
        uses. See LanguageLearningStore.learn_item() for the full,
        optional keyword arguments (meaning, examples, relationships,
        confidence, source, source_context, learning_method).

        Deterministic: re-learning the same (language, item_type, key)
        updates the existing record instead of creating a duplicate.
        Never touches conversation, context, or knowledge/concept
        state - this is an entirely separate table."""
        return self.language_learning.learn_item(language, item_type, key, **kwargs)

    def get_language_item(self, language, item_type, key):
        """Retrieve a previously learned structured language item (see
        learn_language_item() above), or None. Read-only passthrough to
        self.language_learning."""
        return self.language_learning.get_item(language, item_type, key)

    # ------------------------------------------------------------------
    # Learned Language Relationships (see language_intelligence/
    # language_relationships.py, Prompt 417)
    # ------------------------------------------------------------------
    def relate_language_items(self, from_ref, to_ref, relation_type, **kwargs):
        """Record (or refresh) a structured relationship between two
        already-learned language items - or between an item and an
        existing concept. Thin passthrough to this Core's own
        `self.language_relationships` (LanguageRelationshipStore), which
        persists through the same MemorySystem as everything else.
        `from_ref` / `to_ref` are item_ref(language, item_type, key) or
        concept_ref(name) dicts (an item returned by
        learn_language_item() works as-is). Optional keyword arguments:
        symmetric, metadata, confidence, source, source_context,
        learning_method.

        Never creates an endpoint (raises ValueError for one that does
        not exist) and never creates a duplicate: restating a
        relationship refreshes it. Touches no conversation, context or
        knowledge state."""
        return self.language_relationships.relate(from_ref, to_ref, relation_type, **kwargs)

    def get_language_relationships(self, ref, relation_type=None, language=None):
        """Every relationship touching a learned language item (or
        concept), from either side, optionally narrowed by relation type
        and/or by the language/locale of the related end. Read-only
        passthrough to self.language_relationships."""
        return self.language_relationships.relationships_for(
            ref, relation_type=relation_type, language=language
        )

    # ------------------------------------------------------------------
    # Learned Expression Variation Matching (see language_intelligence/
    # learned_expression_variation_matcher.py, Prompt 438)
    # ------------------------------------------------------------------
    def match_learned_expression_variation(self, expression, language=None, **kwargs):
        """Decide whether `expression` is (or is explicitly connected,
        through an already-stored relationship, to) a learned expression.
        Thin passthrough to this Core's own
        `self.expression_variation_matcher`
        (LearnedExpressionVariationMatcher); optional keyword arguments:
        item_type, locale, relation_types, max_source_items,
        max_candidates.

        Returns a LearnedExpressionVariationMatchResult whose `status` is
        MATCHED, AMBIGUOUS or NOT_FOUND - never a guess based on spelling
        similarity or semantic intuition; only an existing, explicit
        relationship (or an exact learned-item match) connects two
        expressions. Read-only; this SAME instance also backs
        resolve_language_meaning() and match_learned_pattern() above as
        an optional fallback - see those methods."""
        return self.expression_variation_matcher.match(expression, language=language, **kwargs)

    # ------------------------------------------------------------------
    # Learned Meaning Resolution (see language_intelligence/
    # meaning_resolution.py, Prompt 418)
    # ------------------------------------------------------------------
    def resolve_language_meaning(self, expression, language=None, **kwargs):
        """Resolve what the system has LEARNED `expression` (a word,
        phrase or pattern) to mean, from the language items and
        relationships already stored. Thin passthrough to this Core's own
        `self.meaning_resolver` (MeaningResolver); optional keyword
        arguments: item_type, relation_types, max_depth, max_related.

        Returns a MeaningResolutionResult whose `status` is RESOLVED or
        NOT_FOUND. Deterministic, bounded and read-only: it writes
        nothing, is not a language model, and never invents a meaning - an
        expression nothing was learned about is simply NOT_FOUND."""
        return self.meaning_resolver.resolve(expression, language=language, **kwargs)

    # ------------------------------------------------------------------
    # Learned Meaning Disambiguation (see language_intelligence/
    # learned_meaning_disambiguation.py, Prompt 420)
    # ------------------------------------------------------------------
    def disambiguate_learned_meaning(self, expression, language=None, use_context=True,
                                      preferred_language=None, **kwargs):
        """Resolve `expression`'s learned meaning (via
        `resolve_language_meaning` above, REUSED unchanged) and then
        decide - deterministically, never guessing - whether one of
        possibly-several learned meanings actually applies here. Thin
        passthrough that composes this Core's own `self.meaning_resolver`
        and `self.meaning_disambiguator`; optional `**kwargs` (item_type,
        relation_types, max_depth, max_related) are forwarded to the
        resolver exactly as `resolve_language_meaning` already forwards
        them.

        With `use_context=True` (the default), this reads the SAME
        active-topic/conversation-context pieces `understand_language()`
        already reads (via the existing `get_active_topic`/`self.context` -
        never a second, competing computation of either) as
        disambiguation signals. `preferred_language` is an independent
        hint (e.g. a caller-known conversation language) used only to
        narrow between several already-found candidates - see
        learned_meaning_disambiguation.py's own docstring for the exact,
        fixed decision order.

        Returns a DisambiguationResult whose `status` is RESOLVED,
        AMBIGUOUS, or NOT_FOUND. Read-only: writes nothing to memory,
        knowledge, or conversation state - same convention as
        resolve_language_meaning/understand_language above."""
        resolution = self.meaning_resolver.resolve(expression, language=language, **kwargs)
        active_topic = self.get_active_topic() if use_context else None
        conversation_context = self.context if use_context else None
        return self.meaning_disambiguator.disambiguate(
            resolution, language=language, active_topic=active_topic,
            conversation_context=conversation_context, preferred_language=preferred_language,
        )

    # ------------------------------------------------------------------
    # Learned Sentence Pattern Matching (see language_intelligence/
    # learned_pattern_matching.py, Prompt 421)
    # ------------------------------------------------------------------
    def match_learned_pattern(self, message, language=None, **kwargs):
        """Recognize `message` as an instance of a previously learned
        sentence pattern (a word/phrase/pattern learned via
        `learn_language_item(..., item_type=ITEM_TYPE_PATTERN, ...)`
        above). Thin passthrough to this Core's own `self.pattern_matcher`
        (LearnedPatternMatcher); optional keyword arguments: locale,
        max_patterns.

        Returns a LearnedPatternMatchResult whose `status` is MATCHED,
        NOT_FOUND, AMBIGUOUS, or NOT_RESOLVED. Deterministic, bounded and
        read-only: it writes nothing, is not a language model, and never
        invents a pattern - a message with no matching learned structure
        is simply NOT_FOUND."""
        return self.pattern_matcher.match(message, language=language, **kwargs)

    # ------------------------------------------------------------------
    # Learned Sentence Pattern Teaching (see language_intelligence/
    # learned_pattern_teaching.py, Prompt 423)
    # ------------------------------------------------------------------
    def teach_sentence_pattern(self, language, pattern, **kwargs):
        """Explicitly teach a reusable sentence pattern for `language`,
        e.g. ("fa", "من {{X}} را دوست دارم"). Thin passthrough to this
        Core's own `self.pattern_teacher` (LearnedPatternTeacher);
        optional keyword arguments: locale, meaning, confidence, source,
        examples.

        Returns a LearnedPatternTeachingResult whose `status` is CREATED,
        ALREADY_EXISTS, CONFLICT, or INVALID. The caller supplies the
        pattern and its named variables - nothing is inferred - and an
        invalid pattern stores nothing. Once taught, the pattern is found
        by match_learned_pattern() and extract_sentence_structure()."""
        return self.pattern_teacher.teach(language, pattern, **kwargs)

    # ------------------------------------------------------------------
    # Learned Pattern Meaning Binding (see language_intelligence/
    # learned_pattern_meaning.py, Prompt 424)
    # ------------------------------------------------------------------
    def bind_pattern_meaning(self, language, pattern, meaning, **kwargs):
        """Explicitly bind the meaning/intention named `meaning` (e.g.
        "express_preference") to a sentence pattern already taught for
        `language` (see `teach_sentence_pattern` above). Thin passthrough
        to this Core's own `self.pattern_meaning_binder`
        (LearnedPatternMeaningBinder); optional keyword arguments:
        locale, confidence, source, source_context, examples.

        Returns a PatternMeaningBindingResult whose `status` is BOUND,
        ALREADY_BOUND, CONFLICT, PATTERN_NOT_FOUND, or INVALID. The
        caller names the meaning - nothing is inferred - and an unknown
        pattern is refused, never created."""
        return self.pattern_meaning_binder.bind(language, pattern, meaning, **kwargs)

    def resolve_pattern_meaning(self, message, language=None, **kwargs):
        """Recognize `message` as an instance of a learned sentence
        pattern (`match_learned_pattern` above) and report the meaning
        EXPLICITLY bound to that pattern. Optional keyword arguments:
        locale, max_patterns (matching) and max_meanings (binding).

        Returns a LearnedPatternMeaningResult whose `status` is RESOLVED
        (one bound meaning applies), AMBIGUOUS (several are bound and
        nothing distinguishes them) or NOT_FOUND (no pattern matched, or
        the pattern has no bound meaning); the Prompt 421 match and its
        variables are kept whole in `pattern_match`. Read-only."""
        match_kwargs = {k: kwargs.pop(k) for k in ("locale", "max_patterns") if k in kwargs}
        match = self.pattern_matcher.match(message, language=language, **match_kwargs)
        return self.pattern_meaning_binder.resolve(
            match, locale=match_kwargs.get("locale"), **kwargs)

    # ------------------------------------------------------------------
    # Learned Sentence Structure Extraction (see language_intelligence/
    # learned_sentence_structure.py, Prompt 422)
    # ------------------------------------------------------------------
    def extract_sentence_structure(self, message, language=None, **kwargs):
        """Report the structure of `message` - its ordered fixed and
        variable components - as defined by the previously learned
        sentence pattern it matches (see `match_learned_pattern` above).
        Thin passthrough to this Core's own
        `self.sentence_structure_extractor`; optional keyword arguments:
        locale, max_patterns.

        Returns a LearnedSentenceStructureResult whose `status` is
        MATCHED, NOT_FOUND, AMBIGUOUS, or NOT_RESOLVED. Deterministic,
        bounded and read-only: it writes nothing, is not grammar
        analysis, and never invents a role or meaning - a part of the
        message the pattern does not define stays unresolved."""
        return self.sentence_structure_extractor.extract(
            message, language=language, **kwargs)

    # ------------------------------------------------------------------
    # Conversational context (see context/) - inspection and reset only.
    # Population happens automatically inside understand()/
    # learn_from_text() above; nothing here ever touches
    # memory/knowledge/concepts.
    # ------------------------------------------------------------------
    def get_recent_context(self, limit=None):
        """Structured (JSON-shaped) view of recent short-term context."""
        return self.context.get_recent_context(limit)

    def get_recent_turns(self, limit=None):
        """The last few {"user", "assistant"} turns of this conversation,
        oldest-first (see ConversationContext.get_recent_turns)."""
        return self.context.get_recent_turns(limit)

    def get_relevant_context(self, text):
        """The recent turns relevant to `text`, as a RelevantContextResult
        (see context/relevance.py): chronological, each with a score and
        the reasons behind it. Empty if nothing recent is relevant.
        Read-only - it does not record `text` as a turn."""
        return select_relevant_turns(text, self.context.get_recent_turns())

    def resolve_reference(self, text, relevant_context=None):
        """Message-level conversational reference resolution (Prompt
        392, context/message_reference_resolution.py): does `text`
        contain a simple reference ("it", "that boss", "the game I
        mentioned", ...), and if so, which already-selected turn does
        it most plausibly point back to? Returns a ResolvedReference -
        see that module for exactly what it does and does not attempt.

        `relevant_context` is the RelevantContextResult already
        selected for `text` (see get_relevant_context above); when
        omitted it is computed the same way, so this can also be
        called on its own, independent of _handle_conversation's own
        fallback branch. This never selects a *different* context than
        `relevant_context` already holds, and it never writes to
        memory/knowledge/context - purely a read-only, structured
        analysis, same convention as get_relevant_context/understand/
        reason above."""
        if relevant_context is None:
            relevant_context = self.get_relevant_context(text)
        return resolve_conversational_reference(text, relevant_context)

    def get_active_topic(self):
        """The current Active Conversation Topic (Prompt 393,
        context/active_topic.py) as an ActiveTopicResult - `.topic` is
        None when nothing is known. Read-only."""
        return self.topic_tracker.current

    def reset_context(self):
        """Clear short-term conversational context only (entries and
        turns), plus the active topic derived from it. Persistent knowledge, memory, skills, and capabilities
        are untouched - see
        context/conversation_context.py:ConversationContext.reset.

        Prompt 581: also resets `last_response_correction_usable` (Prompt
        580) to its safe default (False) through this same existing
        reset lifecycle - the smallest concrete fix so a stale True from
        a previous turn's correction-aware response can never leak past
        a context reset. Nothing else this method already clears is
        touched, and `last_conversation_response`/`last_language_
        response` keep their existing (unreset) behavior exactly as
        before this prompt; no correction retrieval, selection,
        application, or usability criterion is invoked here.

        Prompt 613: also resets `last_response_normalized_input` to its
        safe default (None) through this same existing reset lifecycle -
        the smallest concrete fix so a stale normalized_input from a
        previous turn can never leak past a context reset."""
        self.context.reset()
        self.topic_tracker.reset()
        self.conversation_state.reset()
        self.last_response_correction_usable = False
        self.last_response_normalized_input = None

    # ------------------------------------------------------------------
    # Goals (see planning/) - foundation only. Creation/storage/
    # retrieval for the future Planning Engine; no automatic step
    # generation or execution happens here. Reachable from
    # process_input() only when the input is clearly goal-oriented
    # (see _handle_goal_or_conversation/planning/goal_detection.py) -
    # every other conversational input (ordinary questions,
    # statements, unknown input) still goes through the unchanged
    # _handle_conversation() path below, exactly as before this stage.
    # ------------------------------------------------------------------
    def create_goal(self, raw_text, goal_type=None, requirements=None, metadata=None):
        """Create a Goal (through GoalManager, unchanged) and, for
        that same Goal, start exactly one empty Plan for it (through
        PlanManager, also unchanged - see planning/plan_manager.py) -
        connecting the Goal system to the Plan system without
        redesigning either one. The returned value is still just the
        created Goal (same as before this stage), so every existing
        caller of create_goal() keeps working unchanged; the Plan
        itself is retrievable the normal way, via all_plans()/get_plan()
        on self.plans, once its own goal_id is known.

        The Plan is created with no steps and no dependencies/
        required_capabilities/expected_outputs (PlanManager.create_plan's
        own defaults) - nothing here adds a step or executes anything;
        that remains the Planner's job (see plan_first_step/
        plan_second_step/plan_third_step below) and, eventually, the
        future Planning/Execution Engine's.

        Calls PlanManager.create_plan exactly once per create_goal()
        call - one Goal, one Plan, never more - so repeated or nested
        calls can never pile up duplicate Plans for the same
        invocation."""
        goal = self.goals.create_goal(
            raw_text, goal_type=goal_type, requirements=requirements, metadata=metadata
        )
        self.plans.create_plan(goal.goal_id)
        return goal

    def get_goal(self, goal_id):
        return self.goals.get_goal(goal_id)

    def describe_goal(self, goal_id):
        """Structured (JSON-shaped) representation of one goal, for
        debugging/inspection - see GoalManager.describe_goal."""
        return self.goals.describe_goal(goal_id)

    # ------------------------------------------------------------------
    # Plans (see planning/plan.py) - foundation only. Creation/storage/
    # retrieval for the future Planning Engine; no step generation or
    # execution happens here. This explicit create_plan() (distinct
    # from the one empty Plan create_goal() above already starts
    # automatically) is never called from process_input() - only
    # create_goal() is, and only for clearly goal-oriented input - so
    # today's AEL/conversation routing for everything else is
    # unaffected by its presence.
    # ------------------------------------------------------------------
    def create_plan(
        self, goal_id, dependencies=None, required_capabilities=None,
        expected_outputs=None, metadata=None,
    ):
        return self.plans.create_plan(
            goal_id, dependencies=dependencies, required_capabilities=required_capabilities,
            expected_outputs=expected_outputs, metadata=metadata,
        )

    def add_plan_step(
        self, plan_id, description, dependencies=None, required_capabilities=None,
        expected_output=None,
    ):
        return self.plans.add_step(
            plan_id, description, dependencies=dependencies,
            required_capabilities=required_capabilities, expected_output=expected_output,
        )

    def get_plan(self, plan_id):
        return self.plans.get_plan(plan_id)

    def describe_plan(self, plan_id):
        """Structured (JSON-shaped) representation of one plan, for
        debugging/inspection - see PlanManager.describe_plan."""
        return self.plans.describe_plan(plan_id)

    # ------------------------------------------------------------------
    # Planner (see planning/planner.py) - foundation only. A minimal,
    # deterministic Goal -> first three PlanSteps bridge; no general
    # dependency graphs or execution happens here. Never called from
    # process_input(), so today's AEL/conversation routing is
    # unaffected by its presence.
    # ------------------------------------------------------------------
    def plan_first_step(self, goal_id):
        return self.planner.create_first_step(goal_id)

    def plan_second_step(self, goal_id):
        return self.planner.create_second_step(goal_id)

    def plan_third_step(self, goal_id):
        return self.planner.create_third_step(goal_id)

    # ------------------------------------------------------------------
    # Execution preparation (see execution/step_execution_preparation.py)
    # - foundation only. Connects the existing goal_id -> Plan -> first
    # PlanStep relationship (self.planner.create_first_step, unchanged,
    # already idempotent - see plan_first_step above) to the existing,
    # read-only StepExecutionPreparation checkpoint (self.step_preparation,
    # also unchanged). Never called from process_input(), so today's
    # AEL/conversation routing is unaffected by its presence, and never
    # executes anything - this only answers "would running this step be
    # safe right now", exactly what StepExecutionPreparation.prepare
    # itself already answers (see that method's own docstring for the
    # complete check list and return shape). No new execution engine,
    # and no ExecutionResult is created here or by anything this calls.
    # ------------------------------------------------------------------
    def prepare_first_step(self, goal_id, capability_system=None):
        """Ensure `goal_id` has a first PlanStep (via plan_first_step,
        reusing the existing, already-idempotent Planner - calling
        this again for the same goal_id creates no duplicate Plan or
        step) and return the existing, structured preparation result
        for that exact step, unmodified.

        `capability_system` defaults to this Core's own
        self.capabilities (the real, already-seeded registry) when not
        given, so a normal call reflects this application's actual
        capability state; a caller/test may still pass its own (or
        explicitly None, to skip the capability-availability check
        entirely - see StepExecutionPreparation.prepare's own
        docstring) instead.

        Before checking, this refreshes only the one first step's own
        READY/BLOCKED status (PlanManager.refresh_step_status - the
        same one-time dependency/capability refresh
        PlanExecutionController.execute_plan already performs before
        its own loop, see execution/plan_execution_controller.py -
        reused here, not reinvented) so a first step fresh out of
        plan_first_step (created PENDING, since it has no dependencies
        to ever be BLOCKED on) is correctly classified as READY before
        StepExecutionPreparation checks it, rather than always failing
        its step_ready check for no real reason. This only ever
        recomputes/records that one step's status from its (empty)
        dependencies and required_capabilities, exactly as
        refresh_step_status already documents doing - it never creates,
        enables, or calls anything, and never touches any other step.

        Raises ValueError for an unknown goal_id - the same guard
        plan_first_step (and, beneath it, Planner.create_first_step)
        already raises; there is no real Goal/Plan/step to prepare.

        Never executes the step, never calls a capability handler, and
        never creates an ExecutionResult - see
        StepExecutionPreparation.prepare's own docstring for the
        complete read-only contract this method inherits unchanged."""
        plan = self.plan_first_step(goal_id)
        step = plan.steps[0]
        registry = capability_system if capability_system is not None else self.capabilities
        self.plans.refresh_step_status(plan.plan_id, step.step_id, registry)
        return self.step_preparation.prepare(plan.plan_id, step.step_id, registry)

    def execute_first_step(self, goal_id, capability_system=None):
        """Ensure `goal_id` has a first PlanStep (via plan_first_step,
        exactly as prepare_first_step above already does - reusing
        the existing, already-idempotent Planner; calling this again
        for the same goal_id creates no duplicate Plan or step and,
        for a step already COMPLETED/FAILED, runs it through the
        exact same StepExecutionController.execute_step gate below,
        which itself never re-executes a step that isn't READY - see
        that method's own docstring) and run *only* that one step
        through the existing StepExecutionController, unchanged,
        returning its existing structured result exactly as-is.

        `capability_system` defaults to this Core's own
        self.capabilities when not given (same convention as
        prepare_first_step above) - a caller/test may still pass its
        own instead.

        Before executing, this refreshes only the one first step's
        own READY/BLOCKED status (PlanManager.refresh_step_status -
        the exact same one-time refresh prepare_first_step already
        performs, and the same one PlanExecutionController.execute_plan
        performs before its own loop - reused here, not reinvented),
        so a first step fresh out of plan_first_step (created
        PENDING, since it has no dependencies to ever be BLOCKED on)
        is correctly classified READY before
        StepExecutionController.execute_step gates it through
        StepExecutionPreparation, rather than always failing that
        gate for no real reason.

        This method never selects, inspects, or executes any step
        other than this one, explicitly-named first step - not the
        plan's second step, not any other step that might become
        READY as a side effect of this one completing (see
        StepExecutionController.execute_step's own "NEVER" list,
        module docstring). It never adds automatic retry - a failed
        run is simply reported, once, in the structured result
        StepExecutionController.execute_step already returns. It
        never introduces a second execution engine, capability
        handler, or registry of its own - self.step_controller (see
        __init__) is the one and only place this method, or anything
        else on Core, actually runs a step.

        Raises ValueError for an unknown goal_id - the same guard
        plan_first_step (and, beneath it, Planner.create_first_step)
        already raises; there is no real Goal/Plan/step to execute.

        After the run, if - and only if - a real `ExecutionResult` was
        actually produced (`result["execution_id"]` is not None - a
        preparation failure never reaches this point, exactly as
        ExecutionLearning.create_record itself would decline to build
        a record for anything else), this looks that exact result up
        in self.step_controller.history (the single existing
        ExecutionHistory this same run just recorded it into - never a
        second copy of it) and hands it, unmodified, to
        self.execution_learning.learn_from_execution(...), which
        builds a LearningRecord (unchanged model, unchanged
        ExecutionLearning logic) and stores it into self.learning_records
        (the one existing LearningRecordStore - see __init__). This is
        best-effort and strictly observational: it never changes
        `result` itself, never retries the step, never learns from its
        own record, and never touches a plan, capability, skill, or
        code file - a caller reads self.learning_records afterward if
        it wants to see what was recorded."""
        plan = self.plan_first_step(goal_id)
        step = plan.steps[0]
        registry = capability_system if capability_system is not None else self.capabilities
        self.plans.refresh_step_status(plan.plan_id, step.step_id, registry)
        result = self.step_controller.execute_step(plan.plan_id, step.step_id, registry)

        if result.get("execution_id") is not None:
            execution_result = self.step_controller.history.get(result["execution_id"])
            if execution_result is not None:
                self.execution_learning.learn_from_execution(
                    execution_result, self.learning_records
                )

        return result

    # ------------------------------------------------------------------
    # Section 4 foundation (Prompt 680; see planning/request_context.py,
    # planning/plan_validation.py, planning/execution_handoff.py) - explicit
    # entry points only, never called from process_input(), so existing
    # routing is unchanged. Request Context -> Reasoning -> Gaps -> Plan ->
    # Validation -> INERT handoff. Nothing here executes a step.
    # ------------------------------------------------------------------
    def prepare_request_context(self, raw_text, use_context=True, propose_plan=False):
        """Build a per-request RequestContext (in-memory, never persisted, writes no knowledge/memory/
        conversation context). With `propose_plan=True`, and only for a goal-oriented request with no
        blocking information gap, ONE Goal + Plan is created through the existing GoalManager/Planner
        (in-memory), validated, and attached; otherwise no plan is proposed."""
        ctx = build_request_context(
            raw_text, self.knowledge, self.reasoning, capability_system=self.capabilities,
            executable_registry=getattr(self.step_preparation, "executable_capabilities", None),
            conversation_context=self.context if use_context else None,
        )
        if not propose_plan:
            return ctx
        if ctx.goal is None:
            ctx.add_observation("plan_not_proposed", "request is not goal-oriented")
        elif ctx.blocking_gaps():
            ctx.add_observation("plan_not_proposed", "blocking information gaps")
        else:
            goal = self.create_goal(ctx.goal)
            plan = self.plan_third_step(goal.goal_id)
            ctx.attach_plan(plan)
            ctx.attach_validation(self.validate_plan(plan, goal=ctx.goal))
        return ctx

    def _plan_from(self, plan_or_id):
        return self.plans.get_plan(plan_or_id) if isinstance(plan_or_id, str) else plan_or_id

    def validate_plan(self, plan_or_id, goal=None, claimed_execution_eligible=None):
        """Deterministic, read-only validation of a Plan (or plan id) against this Core's capability
        registry; see planning/plan_validation.validate_plan. Never repairs or mutates the plan."""
        plan = self._plan_from(plan_or_id)
        if goal is None and plan is not None and getattr(plan, "goal_id", None):
            goal = self.goals.get_goal(plan.goal_id)
        return _validate_plan(plan, goal=goal, capability_system=self.capabilities,
                              claimed_execution_eligible=claimed_execution_eligible)

    def build_plan_from_context(self, request_context):
        """Prompt 681: deterministic, UNEXECUTED plan for a prepared RequestContext (see
        planning/plan_builder.py). Returns a PlanBuildResult; invalid/incomplete/blocked contexts are
        rejected with failure codes and no plan. Stores nothing, attaches nothing, executes nothing."""
        return _build_plan_from_context(request_context)

    def prepare_execution_handoff(self, plan_or_id, request_context=None):
        """Validate the plan and return an INERT ExecutionHandoff record (ready_for_executor or
        rejected). Executes nothing, changes no plan/step status."""
        plan = self._plan_from(plan_or_id)
        validation = self.validate_plan(plan)
        return _prepare_execution_handoff(plan, validation, request_context=request_context)

    # ------------------------------------------------------------------
    # Code intelligence (backs the code_analysis capability)
    # ------------------------------------------------------------------
    def inspect_code(self, source):
        """Real, safe (parse-only, no execution) Python code analysis."""
        return inspect_source(source)

    # ------------------------------------------------------------------
    # Developer panel data
    # ------------------------------------------------------------------
    def status_snapshot(self):
        counts = self.memory.counts()
        version = self.upgrades.versions.current_version()
        health = self.health.check()
        return {
            "app_version": self.memory.get_config("app_version", APP_VERSION),
            "active_version_label": version["version_label"] if version else "unknown",
            **counts,
            "system_status": health["overall"],
            "health_components": health["components"],
            "upgrade_history": self.upgrades.history(20),
        }

    # ------------------------------------------------------------------
    # Thin application-service accessors for presentation layers (the
    # web UI today, a future Android UI later). A UI should go through
    # these instead of reaching into self.memory directly - it keeps
    # each subsystem's internal schema/storage details private to Core,
    # which matters more once more than one UI exists.
    # ------------------------------------------------------------------
    def recent_messages(self, limit=50):
        return self.memory.recent_messages(limit)

    def recent_learning_events(self, limit=50):
        return self.memory.recent_learning_events(limit)

    def recent_errors(self, limit=50):
        return self.memory.recent_errors(limit)

    def log_error(self, operation, message):
        return self.memory.log_error(operation=operation, message=message)
