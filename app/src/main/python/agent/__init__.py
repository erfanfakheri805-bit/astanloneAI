"""
Agent (foundation)
=====================
Home for the future Agent layer. So far this holds only `AgentLoop`
(agent_loop.py) - a small, deterministic coordinator that decides
"given this Goal and this existing Plan, should anything run right
now, and if so, run it once (through the already-existing execution
stack) and report what happened."

`AgentLoop` never generates a Goal, never generates a Plan, never
executes a step itself, and never calls out to an external AI API. It
is built entirely on top of the Planning/Execution modules that
already exist in this project (`planning.goal_manager.GoalManager`,
`planning.plan_manager.PlanManager`, `planning.goal_completion.
GoalCompletionEvaluator`, `execution.plan_execution_controller.
PlanExecutionController`, `execution.execution_event_log.
ExecutionEventLog`) - see agent_loop.py's own module docstring for the
full picture.

`test_result_evaluation.py` adds one small, deterministic, stateless
classifier - `classify_test_result`/`build_test_evaluation` - that
turns an already-produced `execution.python_test_runner_capability`
result into exactly one of `"PASSED"`/`"FAILED"`/`"TIMEOUT"`/
`"INVALID"`, using only that result's own `success`/`timed_out`
fields (never re-running or retrying a test, never touching a source
file). `AgentLoop.evaluate_test_result` exposes this, reused
unchanged, as part of this loop's own context - the same way
`request_analysis`/`request_proposal` expose `AdaptivePlanAnalyzer`/
`AdaptivePlanProposal` - so a caller can get a fixed-vocabulary
verdict on a completed test run without re-inspecting the raw result
fields itself.
"""
