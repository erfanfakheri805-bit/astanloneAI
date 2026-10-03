"""
Planning - Planner
=====================
`Planner` is a minimal, deterministic bridge from an existing `Goal`
to the first three `PlanStep`s of its `Plan`:

    GOAL (planning/goal.py) -> PLANNER (this module) -> PLAN + first three PlanSteps

This is intentionally NOT the future Planning Engine. It produces at
most three fixed, rule-based steps per Goal (e.g. "Understand the
requirements of the requested calculator", then "Design a solution
for the requested calculator", then "Validate the planned solution
for the requested calculator"), never chooses between alternative
approaches, never builds a general dependency graph, and never
executes anything. The only dependency relationships it ever records
are the second step depending on the first and the third step
depending on the second, using PlanStep's existing `dependencies`
field - a simple chain, not a new graph structure. Full multi-step
planning, arbitrary dependency graphs, automatic execution, code
generation, self-upgrade, and any external/network access remain out
of scope for this stage - see planning/plan.py and
planning/plan_manager.py's own module docstrings for where real plan
generation eventually belongs.

Built entirely on the existing GoalManager and PlanManager - no new
storage, no new id scheme, no bypassing either manager's validation.
A Planner holds no state of its own: it only calls through to the
managers it is given, the same "bookkeeping, not a new source of
truth" relationship PlanManager itself has with GoalManager (see
plan_manager.py's module docstring).
"""

# Fixed, deterministic vocabulary used to derive a step's subject from
# a Goal's own text. Intentionally small and rule-based (never
# guessed, never randomized) - same "crude but deterministic"
# convention as goal_manager._estimate_confidence and
# plan_manager._estimate_confidence.
_ACTION_VERBS = {
    "create", "build", "make", "write", "design", "implement",
    "develop", "add", "generate", "produce", "setup",
}
_ARTICLES = {"a", "an", "the"}

_FIRST_STEP_TEMPLATE = "Understand the requirements of the requested {subject}"
_SECOND_STEP_TEMPLATE = "Design a solution for the requested {subject}"
_THIRD_STEP_TEMPLATE = "Validate the planned solution for the requested {subject}"


def _extract_subject(goal_text):
    """Deterministically derive a step subject from a Goal's text.

    Strips at most one leading action verb and, if present, one
    leading article (e.g. "Create a calculator" -> subject
    "calculator"). Matching is case-insensitive but the subject keeps
    the Goal's original casing. Falls back to the Goal's full text
    unchanged when it doesn't start with a recognized verb/article, or
    when the text is empty (in which case "goal" is used).
    """
    text = (goal_text or "").strip()
    if not text:
        return "goal"

    words = text.split(" ")
    lowered = [w.lower() for w in words]

    idx = 0
    if lowered and lowered[0] in _ACTION_VERBS:
        idx = 1
        if idx < len(lowered) and lowered[idx] in _ARTICLES:
            idx += 1

    subject_words = words[idx:] if idx < len(words) else words
    subject = " ".join(w for w in subject_words if w).strip()
    if not subject:
        subject = text
    return subject


def _first_step_description(goal_text):
    """Deterministically derive a first-step description from a Goal's
    text (e.g. "Create a calculator" -> "Understand the requirements
    of the requested calculator" - matching the Planner's worked
    example)."""
    return _FIRST_STEP_TEMPLATE.format(subject=_extract_subject(goal_text))


def _second_step_description(goal_text):
    """Deterministically derive a second-step description from a
    Goal's text (e.g. "Create a calculator" -> "Design a solution for
    the requested calculator" - matching the Planner's worked
    example). Uses the same subject-extraction rules as the first
    step, so both steps stay consistent with each other."""
    return _SECOND_STEP_TEMPLATE.format(subject=_extract_subject(goal_text))


def _third_step_description(goal_text):
    """Deterministically derive a third-step description from a
    Goal's text (e.g. "Create a calculator" -> "Validate the planned
    solution for the requested calculator" - matching the Planner's
    worked example). Uses the same subject-extraction rules as the
    first two steps, so all three stay consistent with each other."""
    return _THIRD_STEP_TEMPLATE.format(subject=_extract_subject(goal_text))


class Planner:
    """Minimal, deterministic Goal -> first PlanStep bridge.

    Not thread-safe (matches GoalManager/PlanManager - see their own
    notes). Safe to use one instance per Core / per conversation
    session, same as GoalManager/PlanManager.
    """

    def __init__(self, goal_manager, plan_manager):
        # Duck-typed on purpose (checks the actual methods used below)
        # rather than isinstance-checked against GoalManager/PlanManager,
        # so tests can pass lightweight fakes - same tolerance already
        # relied on elsewhere in the project's own test suite (e.g.
        # HealthSystem's dependencies).
        if goal_manager is None or not hasattr(goal_manager, "get_goal"):
            raise TypeError("Planner requires a GoalManager instance.")
        if (
            plan_manager is None
            or not hasattr(plan_manager, "all_plans")
            or not hasattr(plan_manager, "create_plan")
            or not hasattr(plan_manager, "add_step")
        ):
            raise TypeError("Planner requires a PlanManager instance.")
        self._goal_manager = goal_manager
        self._plan_manager = plan_manager

    def create_first_step(self, goal_id):
        """Create (or reuse) a Plan for `goal_id`, ensure it has a
        first PlanStep, and return the resulting Plan.

        Raises ValueError if `goal_id` doesn't match a Goal the
        GoalManager actually knows about - a Planner always operates
        on something real, same guard as PlanManager.create_plan.

        Deterministic and idempotent: calling this again for a Goal
        that already has a plan with a step does not add a second
        "first" step - it returns that same plan unchanged. This
        keeps repeated calls safe without introducing any new
        execution or re-planning behaviour.
        """
        goal = self._goal_manager.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Cannot plan for unknown goal_id: {goal_id!r}")

        plan = self._get_or_create_plan(goal_id)
        if not plan.steps:
            description = _first_step_description(
                goal.normalized_text or goal.original_text
            )
            self._plan_manager.add_step(plan.plan_id, description)
        return plan

    def create_second_step(self, goal_id):
        """Ensure the Plan for `goal_id` has a second PlanStep that
        depends on the first, creating the first step too if it
        doesn't exist yet, and return the resulting Plan.

        Raises ValueError if `goal_id` doesn't match a Goal the
        GoalManager actually knows about - same guard as
        create_first_step.

        Deterministic and idempotent: calling this again for a Goal
        that already has a plan with two (or more) steps does not add
        another second step - it returns that same plan unchanged.
        The second step's `dependencies` is set to the first step's
        `step_id`, using PlanStep's existing dependency field (this
        is still just one fixed edge, not a general dependency
        graph). Step ids are assigned by PlanManager.add_step, which
        already numbers steps by the plan's current step count, so
        they stay unique within the plan.
        """
        goal = self._goal_manager.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Cannot plan for unknown goal_id: {goal_id!r}")

        # Reuses create_first_step's own idempotent guard, so the
        # first step is created if missing and left untouched
        # otherwise.
        plan = self.create_first_step(goal_id)
        if len(plan.steps) < 2:
            first_step = plan.steps[0]
            description = _second_step_description(
                goal.normalized_text or goal.original_text
            )
            self._plan_manager.add_step(
                plan.plan_id, description, dependencies=[first_step.step_id]
            )
        return plan

    def create_third_step(self, goal_id):
        """Ensure the Plan for `goal_id` has a third PlanStep that
        depends on the second, creating the first and second steps
        too if they don't exist yet, and return the resulting Plan.

        Raises ValueError if `goal_id` doesn't match a Goal the
        GoalManager actually knows about - same guard as
        create_first_step/create_second_step.

        Deterministic and idempotent: calling this again for a Goal
        that already has a plan with three (or more) steps does not
        add another third step - it returns that same plan unchanged.
        The third step's `dependencies` is set to the second step's
        `step_id`, using PlanStep's existing dependency field - this
        chains onto the second step's own dependency on the first,
        giving Step 3 -> Step 2 -> Step 1 without building any general
        dependency graph. Step ids are assigned by
        PlanManager.add_step, which already numbers steps by the
        plan's current step count, so they stay unique within the
        plan.
        """
        goal = self._goal_manager.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Cannot plan for unknown goal_id: {goal_id!r}")

        # Reuses create_second_step's own idempotent guard, so the
        # first and second steps are created if missing and left
        # untouched otherwise.
        plan = self.create_second_step(goal_id)
        if len(plan.steps) < 3:
            second_step = plan.steps[1]
            description = _third_step_description(
                goal.normalized_text or goal.original_text
            )
            self._plan_manager.add_step(
                plan.plan_id, description, dependencies=[second_step.step_id]
            )
        return plan

    def _get_or_create_plan(self, goal_id):
        """Reuse the oldest existing Plan already linked to this goal,
        if any (so a Planner "updates" a Goal's plan rather than
        piling up duplicates on repeated calls); otherwise create a
        new one through the PlanManager, so every Plan still goes
        through its normal validation and id assignment."""
        for plan in self._plan_manager.all_plans():
            if plan.goal_id == goal_id:
                return plan
        return self._plan_manager.create_plan(goal_id)
