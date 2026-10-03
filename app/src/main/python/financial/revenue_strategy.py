"""
Revenue Strategy
==================
`RevenueStrategy` is a small, standalone data record representing one
possible, legal method of working toward a `FinancialGoal`
(financial/financial_goal.py):

    FinancialGoal -> ... -> RevenueStrategy -> [Strategy Execution: not built yet]

This stage only defines the *shape* of a revenue strategy:

- It does NOT assume `estimated_income` is guaranteed - it is only an
  estimate or target, never a promise.
- It does NOT execute anything: no banking access, no payment
  processing, no account access, no web automation, no hacking, and no
  financial transaction of any kind happens here.
- It does NOT create, deposit, move, or pretend to create any money.
- It does NOT activate itself or any other strategy - a strategy's
  `status` only ever changes because something else (a caller, a later
  stage) explicitly asks for that change.

A RevenueStrategy only records a *proposed or ongoing approach* -
what it's called, how it's meant to make money, what it would need,
what it might produce, and what could go wrong - so a later planning/
execution stage has something structured to reason about, evaluate,
and choose between.

Same "construction never raises, is_valid() is a plain boolean check"
convention already used by `FinancialGoal` (financial/financial_goal.py)
and `LearningRecord` (learning/learning_record.py): a caller can freely
build a RevenueStrategy from untrusted/partial input and then call
`is_valid()` to decide whether it is fit to use, rather than having to
wrap construction in a try/except.
"""

from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# Small, fixed vocabulary for strategy status (matches the STATUS_*
# pattern already used by financial/financial_goal.py and
# planning/goal.py) so callers can branch on it reliably instead of
# comparing against free-form strings. A strategy starts life as
# PROPOSED - nothing in this module ever moves it to ACTIVE or any
# other status on its own; that always requires an explicit
# `update_status` call from a caller.
STATUS_PROPOSED = "PROPOSED"
STATUS_ACTIVE = "ACTIVE"
STATUS_PAUSED = "PAUSED"
STATUS_COMPLETED = "COMPLETED"
STATUS_REJECTED = "REJECTED"

ALL_STATUSES = (
    STATUS_PROPOSED, STATUS_ACTIVE, STATUS_PAUSED, STATUS_COMPLETED, STATUS_REJECTED,
)

DEFAULT_STATUS = STATUS_PROPOSED

# Illustrative, non-exhaustive vocabulary for `revenue_model` - a free
# marker of what kind of legal income approach a strategy describes.
# `is_valid()` deliberately does NOT restrict `revenue_model` to this
# list (see is_valid()'s docstring): it exists as a shared reference
# vocabulary for callers, not a closed enum enforced here.
REVENUE_MODEL_PRODUCT_SALES = "PRODUCT_SALES"
REVENUE_MODEL_SOFTWARE = "SOFTWARE"
REVENUE_MODEL_GAME = "GAME"
REVENUE_MODEL_DIGITAL_SERVICE = "DIGITAL_SERVICE"
REVENUE_MODEL_FREELANCE = "FREELANCE"
REVENUE_MODEL_SUBSCRIPTION = "SUBSCRIPTION"
REVENUE_MODEL_ADVERTISING = "ADVERTISING"
REVENUE_MODEL_CONTENT = "CONTENT"
REVENUE_MODEL_E_COMMERCE = "E_COMMERCE"
REVENUE_MODEL_AUTOMATION_SERVICE = "AUTOMATION_SERVICE"
REVENUE_MODEL_OTHER = "OTHER"

KNOWN_REVENUE_MODELS = (
    REVENUE_MODEL_PRODUCT_SALES,
    REVENUE_MODEL_SOFTWARE,
    REVENUE_MODEL_GAME,
    REVENUE_MODEL_DIGITAL_SERVICE,
    REVENUE_MODEL_FREELANCE,
    REVENUE_MODEL_SUBSCRIPTION,
    REVENUE_MODEL_ADVERTISING,
    REVENUE_MODEL_CONTENT,
    REVENUE_MODEL_E_COMMERCE,
    REVENUE_MODEL_AUTOMATION_SERVICE,
    REVENUE_MODEL_OTHER,
)

# Safe, structured-data-only types allowed inside the structured
# fields (`required_capabilities`, `required_tools`, `required_inputs`,
# `expected_outputs`, `risks`, `constraints`, `metadata`). Same
# convention as financial/financial_goal.py's own
# `_is_safe_structured_value` / learning/learning_record.py's
# `_is_safe_metadata_value`.
_SAFE_SCALAR_TYPES = (str, int, float, bool, type(None))


def _is_safe_structured_value(value):
    """True if `value` is made only of plain, structured data (str,
    int, float, bool, None, list/tuple, dict with string keys) -
    recursively. No functions, class instances, or other objects that
    could carry behavior."""
    if isinstance(value, _SAFE_SCALAR_TYPES):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_safe_structured_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_safe_structured_value(val)
            for key, val in value.items()
        )
    return False


class RevenueStrategy:
    """One possible, legal approach to working toward a FinancialGoal -
    captured but not yet acted on. Purely a data record: construction
    never raises (unlike e.g. ExecutionResult) so a caller can freely
    build a RevenueStrategy from untrusted/partial data and then use
    `is_valid()` to decide whether it is fit to use.

    `required_capabilities`, `required_tools`, `required_inputs`,
    `expected_outputs`, and `risks` are always plain lists (never
    None); `constraints` and `metadata` are always plain dicts (never
    None) - same "no None checks needed by callers" convention as
    FinancialGoal.constraints/metadata (financial/financial_goal.py).
    """

    __slots__ = (
        "strategy_id", "goal_id", "name", "description", "revenue_model",
        "estimated_income", "currency", "time_period",
        "required_capabilities", "required_tools", "required_inputs",
        "expected_outputs", "risks", "constraints", "status", "confidence",
        "created_at", "metadata",
    )

    def __init__(
        self,
        strategy_id,
        goal_id,
        name,
        description,
        revenue_model=None,
        estimated_income=None,
        currency=None,
        time_period=None,
        required_capabilities=None,
        required_tools=None,
        required_inputs=None,
        expected_outputs=None,
        risks=None,
        constraints=None,
        status=DEFAULT_STATUS,
        confidence=0.0,
        created_at=None,
        metadata=None,
    ):
        self.strategy_id = strategy_id
        self.goal_id = goal_id
        self.name = name
        self.description = description
        self.revenue_model = revenue_model
        self.estimated_income = estimated_income
        self.currency = currency
        self.time_period = time_period
        self.required_capabilities = (
            list(required_capabilities) if required_capabilities else []
        )
        self.required_tools = list(required_tools) if required_tools else []
        self.required_inputs = list(required_inputs) if required_inputs else []
        self.expected_outputs = list(expected_outputs) if expected_outputs else []
        self.risks = list(risks) if risks else []
        self.constraints = dict(constraints) if constraints else {}
        self.status = status
        self.confidence = confidence
        self.created_at = created_at if created_at is not None else _now_iso()
        self.metadata = dict(metadata) if metadata else {}

    def __repr__(self):
        return (
            f"RevenueStrategy(strategy_id={self.strategy_id!r}, "
            f"goal_id={self.goal_id!r}, name={self.name!r}, "
            f"revenue_model={self.revenue_model!r}, status={self.status!r})"
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def is_valid(self):
        """Plain boolean check - never raises. A strategy is valid
        when:
        - strategy_id, goal_id, name, and description are non-empty
          strings
        - estimated_income is numeric (int/float, not bool) and >= 0
        - currency and time_period are non-empty strings
        - confidence is a number between 0.0 and 1.0 (inclusive)
        - status is one of the supported values (see ALL_STATUSES)
        - required_capabilities, required_tools, required_inputs,
          expected_outputs, risks, constraints, and metadata contain
          only safe, structured data (see `_is_safe_structured_value`)

        `revenue_model` is intentionally not restricted to
        `KNOWN_REVENUE_MODELS` - that tuple is a shared reference
        vocabulary, not a closed enum, so a caller describing a
        legitimate approach that doesn't fit an existing label isn't
        forced to mislabel it as OTHER or fail validation.

        This intentionally says nothing about whether the strategy
        would actually work, whether `estimated_income` is realistic,
        or whether it should be activated - only whether the record is
        well-formed enough to use.
        """
        for field in (self.strategy_id, self.goal_id, self.name, self.description):
            if not isinstance(field, str) or not field.strip():
                return False

        if isinstance(self.estimated_income, bool):
            return False
        if not isinstance(self.estimated_income, (int, float)):
            return False
        if self.estimated_income < 0:
            return False

        if not isinstance(self.currency, str) or not self.currency.strip():
            return False
        if not isinstance(self.time_period, str) or not self.time_period.strip():
            return False

        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            return False
        if not (0.0 <= self.confidence <= 1.0):
            return False

        if self.status not in ALL_STATUSES:
            return False

        for structured_field in (
            self.required_capabilities,
            self.required_tools,
            self.required_inputs,
            self.expected_outputs,
            self.risks,
            self.constraints,
            self.metadata,
        ):
            if not _is_safe_structured_value(structured_field):
                return False

        return True

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get_required_capabilities(self):
        """A plain list (never None) of capabilities this strategy
        would need. This stage never checks whether they exist or
        grants/uses any of them."""
        return list(self.required_capabilities)

    def get_required_tools(self):
        """A plain list (never None) of tools this strategy would
        need. This stage never installs, invokes, or otherwise touches
        any of them."""
        return list(self.required_tools)

    def get_expected_outputs(self):
        """A plain list (never None) of outputs this strategy is
        expected to produce (e.g. "a published app", "10 client
        deliverables"). Purely descriptive - nothing here is produced
        or verified by this stage."""
        return list(self.expected_outputs)

    def get_risks(self):
        """A plain list (never None) of user- or system-noted risks
        associated with this strategy. This stage never scores,
        mitigates, or acts on them."""
        return list(self.risks)

    def get_constraints(self):
        """A plain dict (never None) of constraints on how this
        strategy should be pursued. This stage never interprets or
        acts on them."""
        return dict(self.constraints)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """Structured (JSON-shaped) representation - used both as the
        general-purpose serialization and as
        RevenueStrategyManager's debugging view."""
        return {
            "strategy_id": self.strategy_id,
            "goal_id": self.goal_id,
            "name": self.name,
            "description": self.description,
            "revenue_model": self.revenue_model,
            "estimated_income": self.estimated_income,
            "currency": self.currency,
            "time_period": self.time_period,
            "required_capabilities": list(self.required_capabilities),
            "required_tools": list(self.required_tools),
            "required_inputs": list(self.required_inputs),
            "expected_outputs": list(self.expected_outputs),
            "risks": list(self.risks),
            "constraints": dict(self.constraints),
            "status": self.status,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }
