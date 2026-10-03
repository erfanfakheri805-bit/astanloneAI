"""
Tests for the RevenueTaskManager (financial/revenue_task_manager.py).

Covers: manager creation, add_task(), duplicate-id rejection,
create_task(), get_task(), get_all(), get_for_opportunity(),
remove_task(), clear(), invalid inputs, and that returned lists/
objects are independent from the manager's own internal storage. This
stage only stores/retrieves already-built RevenueTask records - it
does not execute anything, does not change a task's status on its
own, and does not attach tasks to opportunities.

Run directly:
    python -m unittest tests.test_revenue_task_manager -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest
import unittest.mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from financial.revenue_task import (
    RevenueTask,
    STATUS_PENDING,
    STATUS_READY,
    STATUS_IN_PROGRESS,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    PRIORITY_HIGH,
)
from financial.revenue_task_manager import RevenueTaskManager
from financial.revenue_opportunity import RevenueOpportunity, STATUS_DISCOVERED


def _make_task(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        name="Draft the store listing",
        description="Write the app store listing copy for the opportunity.",
    )
    fields.update(overrides)
    return RevenueTask(**fields)


def _make_opportunity(**overrides):
    fields = dict(
        opportunity_id="opp-test-1",
        goal_id="fin-goal-test-1",
        strategy_id="rev-strategy-test-1",
        name="Sell a small mobile game",
        description="Ship and sell a small mobile game on an app store.",
        revenue_model="GAME",
        estimated_income=500,
        currency="USD",
        time_period="monthly",
        confidence=0.6,
    )
    fields.update(overrides)
    return RevenueOpportunity(**fields)


# ----------------------------------------------------------------------
# 1. Manager creation
# ----------------------------------------------------------------------
class TestManagerCreation(unittest.TestCase):
    def test_starts_empty(self):
        manager = RevenueTaskManager()
        self.assertEqual(len(manager), 0)
        self.assertEqual(manager.get_all(), [])

    def test_repr(self):
        manager = RevenueTaskManager()
        self.assertIn("RevenueTaskManager", repr(manager))


# ----------------------------------------------------------------------
# 2. add_task()
# ----------------------------------------------------------------------
class TestAddTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_add_valid_task(self):
        task = _make_task()
        result = self.manager.add_task(task)
        self.assertIs(result, task)
        self.assertEqual(len(self.manager), 1)

    def test_stored_task_is_retrievable(self):
        task = _make_task(task_id="task-add-1")
        self.manager.add_task(task)
        stored = self.manager.get_task("task-add-1")
        self.assertEqual(stored.task_id, "task-add-1")

    def test_does_not_modify_task_object(self):
        task = _make_task(
            task_id="task-add-2", status=STATUS_PENDING, priority=PRIORITY_HIGH
        )
        self.manager.add_task(task)
        self.assertEqual(task.task_id, "task-add-2")
        self.assertEqual(task.status, STATUS_PENDING)
        self.assertEqual(task.priority, PRIORITY_HIGH)

    def test_rejects_non_revenue_task(self):
        self.assertIsNone(self.manager.add_task("not-a-task"))
        self.assertIsNone(self.manager.add_task(None))
        self.assertIsNone(self.manager.add_task({"task_id": "x"}))
        self.assertEqual(len(self.manager), 0)

    def test_rejects_invalid_task(self):
        invalid_task = _make_task(name="")
        self.assertIsNone(self.manager.add_task(invalid_task))
        self.assertEqual(len(self.manager), 0)

    def test_rejects_empty_task_id(self):
        task = _make_task(task_id="")
        self.assertIsNone(self.manager.add_task(task))
        self.assertEqual(len(self.manager), 0)


# ----------------------------------------------------------------------
# 3. Duplicate task rejection
# ----------------------------------------------------------------------
class TestDuplicateTaskRejection(unittest.TestCase):
    def test_add_task_rejects_duplicate_id(self):
        manager = RevenueTaskManager()
        first = _make_task(task_id="task-dup-1", name="First")
        second = _make_task(task_id="task-dup-1", name="Second")

        self.assertIs(manager.add_task(first), first)
        self.assertIsNone(manager.add_task(second))
        self.assertEqual(len(manager), 1)
        self.assertEqual(manager.get_task("task-dup-1").name, "First")

    def test_create_task_raises_on_duplicate_id(self):
        manager = RevenueTaskManager()
        manager.create_task(
            opportunity_id="opp-test-1", name="First", task_id="task-dup-2"
        )
        with self.assertRaises(ValueError):
            manager.create_task(
                opportunity_id="opp-test-1",
                name="Second",
                task_id="task-dup-2",
            )
        self.assertEqual(len(manager), 1)


# ----------------------------------------------------------------------
# 4. create_task()
# ----------------------------------------------------------------------
class TestCreateTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_create_task_with_explicit_id(self):
        task = self.manager.create_task(
            opportunity_id="opp-test-1",
            name="Explicit id task",
            task_id="task-create-1",
        )
        self.assertEqual(task.task_id, "task-create-1")
        self.assertEqual(len(self.manager), 1)

    def test_create_task_generates_id_when_omitted(self):
        task = self.manager.create_task(
            opportunity_id="opp-test-1", name="Generated id task"
        )
        self.assertTrue(task.task_id)
        self.assertEqual(len(self.manager), 1)

    def test_create_task_returns_independent_copy(self):
        task = self.manager.create_task(
            opportunity_id="opp-test-1",
            name="Copy task",
            task_id="task-create-2",
        )
        task.name = "Tampered"
        stored = self.manager.get_task("task-create-2")
        self.assertEqual(stored.name, "Copy task")

    def test_create_task_raises_on_invalid_fields(self):
        with self.assertRaises(ValueError):
            self.manager.create_task(opportunity_id="opp-test-1", name="")
        self.assertEqual(len(self.manager), 0)

    def test_create_task_respects_optional_fields(self):
        task = self.manager.create_task(
            opportunity_id="opp-test-1",
            name="Full task",
            status=STATUS_READY,
            priority=PRIORITY_HIGH,
            estimated_duration=45,
            dependencies=["task-a"],
            task_id="task-create-3",
        )
        self.assertEqual(task.status, STATUS_READY)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.estimated_duration, 45)
        self.assertEqual(task.dependencies, ["task-a"])


# ----------------------------------------------------------------------
# 5. get_task()
# ----------------------------------------------------------------------
class TestGetTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()
        self.manager.add_task(_make_task(task_id="task-get-1"))

    def test_get_existing_task(self):
        task = self.manager.get_task("task-get-1")
        self.assertIsNotNone(task)
        self.assertEqual(task.task_id, "task-get-1")

    def test_get_missing_task_returns_none(self):
        self.assertIsNone(self.manager.get_task("task-missing"))

    def test_get_task_handles_invalid_ids_safely(self):
        self.assertIsNone(self.manager.get_task(None))
        self.assertIsNone(self.manager.get_task(123))
        self.assertIsNone(self.manager.get_task(""))

    def test_get_task_returns_independent_copy(self):
        task = self.manager.get_task("task-get-1")
        task.name = "Tampered"
        task_again = self.manager.get_task("task-get-1")
        self.assertNotEqual(task_again.name, "Tampered")


# ----------------------------------------------------------------------
# 6. get_all()
# ----------------------------------------------------------------------
class TestGetAll(unittest.TestCase):
    def test_get_all_empty(self):
        manager = RevenueTaskManager()
        self.assertEqual(manager.get_all(), [])

    def test_get_all_preserves_insertion_order(self):
        manager = RevenueTaskManager()
        manager.add_task(_make_task(task_id="task-a"))
        manager.add_task(_make_task(task_id="task-b"))
        manager.add_task(_make_task(task_id="task-c"))
        ids = [t.task_id for t in manager.get_all()]
        self.assertEqual(ids, ["task-a", "task-b", "task-c"])

    def test_get_all_returns_independent_list(self):
        manager = RevenueTaskManager()
        manager.add_task(_make_task(task_id="task-a"))
        result = manager.get_all()
        result.append("tampered")
        result[0].name = "Tampered"
        self.assertEqual(len(manager), 1)
        self.assertEqual(manager.get_task("task-a").name, "Draft the store listing")


# ----------------------------------------------------------------------
# 7. get_for_opportunity()
# ----------------------------------------------------------------------
class TestGetForOpportunity(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()
        self.manager.add_task(
            _make_task(task_id="task-a", opportunity_id="opp-1")
        )
        self.manager.add_task(
            _make_task(task_id="task-b", opportunity_id="opp-2")
        )
        self.manager.add_task(
            _make_task(task_id="task-c", opportunity_id="opp-1")
        )

    def test_matches_exact_opportunity_id(self):
        results = self.manager.get_for_opportunity("opp-1")
        ids = [t.task_id for t in results]
        self.assertEqual(ids, ["task-a", "task-c"])

    def test_preserves_insertion_order(self):
        results = self.manager.get_for_opportunity("opp-1")
        self.assertEqual(results[0].task_id, "task-a")
        self.assertEqual(results[1].task_id, "task-c")

    def test_no_match_returns_empty_list(self):
        self.assertEqual(self.manager.get_for_opportunity("opp-missing"), [])
        self.assertEqual(self.manager.get_for_opportunity(None), [])

    def test_returns_independent_list(self):
        results = self.manager.get_for_opportunity("opp-1")
        results.append("tampered")
        results[0].name = "Tampered"
        fresh = self.manager.get_for_opportunity("opp-1")
        self.assertEqual(len(fresh), 2)
        self.assertEqual(fresh[0].name, "Draft the store listing")


# ----------------------------------------------------------------------
# 8. remove_task()
# ----------------------------------------------------------------------
class TestRemoveTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()
        self.manager.add_task(_make_task(task_id="task-a"))
        self.manager.add_task(_make_task(task_id="task-b"))

    def test_remove_existing_task(self):
        removed = self.manager.remove_task("task-a")
        self.assertEqual(removed.task_id, "task-a")
        self.assertIsNone(self.manager.get_task("task-a"))
        self.assertEqual(len(self.manager), 1)

    def test_remove_only_requested_task(self):
        self.manager.remove_task("task-a")
        self.assertIsNotNone(self.manager.get_task("task-b"))

    def test_remove_missing_task_returns_none(self):
        self.assertIsNone(self.manager.remove_task("task-missing"))
        self.assertEqual(len(self.manager), 2)

    def test_remove_task_handles_invalid_ids_safely(self):
        self.assertIsNone(self.manager.remove_task(None))
        self.assertIsNone(self.manager.remove_task(123))
        self.assertEqual(len(self.manager), 2)


# ----------------------------------------------------------------------
# 9. clear()
# ----------------------------------------------------------------------
class TestClear(unittest.TestCase):
    def test_clear_removes_all_tasks(self):
        manager = RevenueTaskManager()
        manager.add_task(_make_task(task_id="task-a"))
        manager.add_task(_make_task(task_id="task-b"))
        manager.clear()
        self.assertEqual(len(manager), 0)
        self.assertEqual(manager.get_all(), [])

    def test_clear_on_empty_manager(self):
        manager = RevenueTaskManager()
        manager.clear()
        self.assertEqual(len(manager), 0)


# ----------------------------------------------------------------------
# 10. No automatic behavior
# ----------------------------------------------------------------------
class TestNoAutomaticBehavior(unittest.TestCase):
    def test_add_task_does_not_change_status(self):
        manager = RevenueTaskManager()
        task = _make_task(status=STATUS_PENDING)
        manager.add_task(task)
        self.assertEqual(manager.get_task(task.task_id).status, STATUS_PENDING)

    def test_create_task_defaults_to_pending_status(self):
        manager = RevenueTaskManager()
        task = manager.create_task(
            opportunity_id="opp-test-1", name="Default status task"
        )
        self.assertEqual(task.status, STATUS_PENDING)


# ----------------------------------------------------------------------
# 11. attach_task_to_opportunity()
# ----------------------------------------------------------------------
class TestAttachTaskToOpportunity(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_successful_attachment(self):
        opportunity = _make_opportunity(opportunity_id="opp-attach-1")
        task = _make_task(task_id="task-attach-1", opportunity_id="opp-attach-1")
        self.manager.add_task(task)

        result = self.manager.attach_task_to_opportunity(
            "task-attach-1", opportunity
        )
        self.assertEqual(
            result,
            {
                "success": True,
                "task_id": "task-attach-1",
                "opportunity_id": "opp-attach-1",
                "attached": True,
            },
        )
        self.assertTrue(opportunity.has_task("task-attach-1"))

    def test_missing_task(self):
        opportunity = _make_opportunity(opportunity_id="opp-attach-2")
        result = self.manager.attach_task_to_opportunity(
            "task-missing", opportunity
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["attached"])
        self.assertEqual(result["error"], "task_not_found")
        self.assertEqual(result["task_id"], "task-missing")
        self.assertEqual(result["opportunity_id"], "opp-attach-2")
        self.assertEqual(opportunity.task_ids, [])

    def test_invalid_opportunity(self):
        task = _make_task(task_id="task-attach-3", opportunity_id="opp-attach-3")
        self.manager.add_task(task)

        for bad_opportunity in (None, "not-an-opportunity", 123, {}):
            result = self.manager.attach_task_to_opportunity(
                "task-attach-3", bad_opportunity
            )
            self.assertFalse(result["success"])
            self.assertFalse(result["attached"])
            self.assertEqual(result["error"], "invalid_opportunity")
            self.assertIsNone(result["opportunity_id"])

    def test_invalid_opportunity_object_that_fails_is_valid(self):
        task = _make_task(task_id="task-attach-3b", opportunity_id="opp-attach-3b")
        self.manager.add_task(task)
        invalid_opportunity = _make_opportunity(
            opportunity_id="opp-attach-3b", name=""
        )
        result = self.manager.attach_task_to_opportunity(
            "task-attach-3b", invalid_opportunity
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_opportunity")

    def test_mismatched_opportunity_ids(self):
        opportunity = _make_opportunity(opportunity_id="opp-attach-4")
        task = _make_task(
            task_id="task-attach-4", opportunity_id="opp-different"
        )
        self.manager.add_task(task)

        result = self.manager.attach_task_to_opportunity(
            "task-attach-4", opportunity
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["attached"])
        self.assertEqual(result["error"], "opportunity_mismatch")
        self.assertEqual(opportunity.task_ids, [])

    def test_duplicate_attachment(self):
        opportunity = _make_opportunity(opportunity_id="opp-attach-5")
        task = _make_task(task_id="task-attach-5", opportunity_id="opp-attach-5")
        self.manager.add_task(task)

        first = self.manager.attach_task_to_opportunity(
            "task-attach-5", opportunity
        )
        self.assertTrue(first["success"])

        second = self.manager.attach_task_to_opportunity(
            "task-attach-5", opportunity
        )
        self.assertTrue(second["success"])
        self.assertTrue(second["attached"])
        self.assertTrue(second.get("already_attached"))
        self.assertEqual(opportunity.task_ids, ["task-attach-5"])
        self.assertEqual(opportunity.get_task_count(), 1)

    def test_invalid_task_id(self):
        opportunity = _make_opportunity(opportunity_id="opp-attach-6")
        for bad_task_id in (None, "", "   ", 123, []):
            result = self.manager.attach_task_to_opportunity(
                bad_task_id, opportunity
            )
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "invalid_task_id")

    def test_task_status_is_unchanged(self):
        opportunity = _make_opportunity(opportunity_id="opp-attach-7")
        task = _make_task(
            task_id="task-attach-7",
            opportunity_id="opp-attach-7",
            status=STATUS_PENDING,
        )
        self.manager.add_task(task)

        self.manager.attach_task_to_opportunity("task-attach-7", opportunity)

        stored = self.manager.get_task("task-attach-7")
        self.assertEqual(stored.status, STATUS_PENDING)
        self.assertEqual(task.status, STATUS_PENDING)

    def test_opportunity_data_other_than_task_ids_is_unchanged(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-attach-8",
            name="Sell a small mobile game",
            status=STATUS_DISCOVERED,
        )
        task = _make_task(task_id="task-attach-8", opportunity_id="opp-attach-8")
        self.manager.add_task(task)

        self.manager.attach_task_to_opportunity("task-attach-8", opportunity)

        self.assertEqual(opportunity.opportunity_id, "opp-attach-8")
        self.assertEqual(opportunity.name, "Sell a small mobile game")
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)
        self.assertEqual(opportunity.goal_id, "fin-goal-test-1")
        self.assertTrue(opportunity.is_valid())


# ----------------------------------------------------------------------
# 12. create_task_for_opportunity()
# ----------------------------------------------------------------------
class TestCreateTaskForOpportunity(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_successful_task_creation(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-1")
        result = self.manager.create_task_for_opportunity(
            opportunity, "Draft the store listing"
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["created"])
        self.assertTrue(result["attached"])
        self.assertEqual(result["opportunity_id"], "opp-cfo-1")
        self.assertTrue(result["task_id"])
        self.assertEqual(len(self.manager), 1)

    def test_successful_opportunity_attachment(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-2")
        result = self.manager.create_task_for_opportunity(
            opportunity, "Draft the store listing"
        )
        self.assertTrue(opportunity.has_task(result["task_id"]))
        self.assertEqual(opportunity.task_ids, [result["task_id"]])

    def test_invalid_opportunity(self):
        for bad_opportunity in (None, "not-an-opportunity", 123, {}):
            result = self.manager.create_task_for_opportunity(
                bad_opportunity, "Some task"
            )
            self.assertFalse(result["success"])
            self.assertIsNone(result["task_id"])
            self.assertFalse(result["created"])
            self.assertFalse(result["attached"])
            self.assertEqual(result["error"], "invalid_opportunity")
        self.assertEqual(len(self.manager), 0)

    def test_invalid_opportunity_object_that_fails_is_valid(self):
        invalid_opportunity = _make_opportunity(
            opportunity_id="opp-cfo-3", name=""
        )
        result = self.manager.create_task_for_opportunity(
            invalid_opportunity, "Some task"
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "invalid_opportunity")
        self.assertEqual(len(self.manager), 0)

    def test_empty_task_name(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-4")
        for bad_name in ("", "   ", None, 123):
            result = self.manager.create_task_for_opportunity(
                opportunity, bad_name
            )
            self.assertFalse(result["success"])
            self.assertIsNone(result["task_id"])
            self.assertFalse(result["created"])
            self.assertFalse(result["attached"])
            self.assertEqual(result["error"], "invalid_name")
        self.assertEqual(len(self.manager), 0)
        self.assertEqual(opportunity.task_ids, [])

    def test_provided_dependencies(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-5")
        result = self.manager.create_task_for_opportunity(
            opportunity, "Task with deps", dependencies=["task-a", "task-b"]
        )
        self.assertTrue(result["success"])
        stored = self.manager.get_task(result["task_id"])
        self.assertEqual(stored.dependencies, ["task-a", "task-b"])

    def test_provided_metadata(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-6")
        result = self.manager.create_task_for_opportunity(
            opportunity, "Task with metadata", metadata={"source": "prompt-177"}
        )
        self.assertTrue(result["success"])
        stored = self.manager.get_task(result["task_id"])
        self.assertEqual(stored.metadata, {"source": "prompt-177"})

    def test_preserves_description_priority_and_duration(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-7")
        result = self.manager.create_task_for_opportunity(
            opportunity,
            "Full task",
            description="A full description",
            priority=PRIORITY_HIGH,
            estimated_duration=30,
        )
        self.assertTrue(result["success"])
        stored = self.manager.get_task(result["task_id"])
        self.assertEqual(stored.description, "A full description")
        self.assertEqual(stored.priority, PRIORITY_HIGH)
        self.assertEqual(stored.estimated_duration, 30)

    def test_default_priority_falls_back_to_normal(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-8")
        result = self.manager.create_task_for_opportunity(
            opportunity, "Default priority task"
        )
        self.assertTrue(result["success"])
        stored = self.manager.get_task(result["task_id"])
        self.assertEqual(stored.status, STATUS_PENDING)

    def test_duplicate_id_collision_protection(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-9")
        first = self.manager.create_task_for_opportunity(
            opportunity, "First task"
        )
        second = self.manager.create_task_for_opportunity(
            opportunity, "Second task"
        )
        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertEqual(len(self.manager), 2)
        self.assertEqual(
            sorted(opportunity.task_ids),
            sorted([first["task_id"], second["task_id"]]),
        )

    def test_failed_attachment_handling(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-10")
        with unittest.mock.patch.object(
            RevenueOpportunity, "attach_task", return_value=False
        ):
            result = self.manager.create_task_for_opportunity(
                opportunity, "Task that fails to attach"
            )
        self.assertFalse(result["success"])
        self.assertIsNone(result["task_id"])
        self.assertFalse(result["created"])
        self.assertFalse(result["attached"])
        self.assertEqual(result["error"], "attachment_rejected")
        # Nothing left behind in the store, and nothing attached.
        self.assertEqual(len(self.manager), 0)
        self.assertEqual(opportunity.task_ids, [])

    def test_created_task_can_be_retrieved_from_manager(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-11")
        result = self.manager.create_task_for_opportunity(
            opportunity, "Retrievable task"
        )
        stored = self.manager.get_task(result["task_id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.task_id, result["task_id"])
        self.assertEqual(stored.opportunity_id, "opp-cfo-11")
        self.assertEqual(stored.name, "Retrievable task")

    def test_opportunity_contains_task_id(self):
        opportunity = _make_opportunity(opportunity_id="opp-cfo-12")
        result = self.manager.create_task_for_opportunity(
            opportunity, "Attached task"
        )
        self.assertIn(result["task_id"], opportunity.get_task_ids())
        self.assertTrue(opportunity.has_task(result["task_id"]))

    def test_does_not_execute_or_change_status(self):
        opportunity = _make_opportunity(
            opportunity_id="opp-cfo-13", status=STATUS_DISCOVERED
        )
        result = self.manager.create_task_for_opportunity(
            opportunity, "No side effects task"
        )
        stored = self.manager.get_task(result["task_id"])
        self.assertEqual(stored.status, STATUS_PENDING)
        self.assertEqual(opportunity.status, STATUS_DISCOVERED)


# ----------------------------------------------------------------------
# 13. get_tasks_for_opportunity() / get_task_ids_for_opportunity()
# ----------------------------------------------------------------------
class TestGetTasksForOpportunity(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()
        self.manager.add_task(
            _make_task(task_id="task-gto-a", opportunity_id="opp-gto-1")
        )
        self.manager.add_task(
            _make_task(task_id="task-gto-b", opportunity_id="opp-gto-2")
        )
        self.manager.add_task(
            _make_task(task_id="task-gto-c", opportunity_id="opp-gto-1")
        )

    def test_multiple_tasks_for_same_opportunity(self):
        results = self.manager.get_tasks_for_opportunity("opp-gto-1")
        ids = [t.task_id for t in results]
        self.assertEqual(ids, ["task-gto-a", "task-gto-c"])

    def test_tasks_for_different_opportunities_are_excluded(self):
        results = self.manager.get_tasks_for_opportunity("opp-gto-1")
        ids = [t.task_id for t in results]
        self.assertNotIn("task-gto-b", ids)

        other_results = self.manager.get_tasks_for_opportunity("opp-gto-2")
        self.assertEqual([t.task_id for t in other_results], ["task-gto-b"])

    def test_no_matching_tasks_returns_empty_list(self):
        self.assertEqual(
            self.manager.get_tasks_for_opportunity("opp-missing"), []
        )

    def test_invalid_or_empty_opportunity_id(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            self.assertEqual(
                self.manager.get_tasks_for_opportunity(bad_id), []
            )

    def test_preserves_insertion_order(self):
        results = self.manager.get_tasks_for_opportunity("opp-gto-1")
        self.assertEqual(results[0].task_id, "task-gto-a")
        self.assertEqual(results[1].task_id, "task-gto-c")

    def test_returned_list_is_independent(self):
        results = self.manager.get_tasks_for_opportunity("opp-gto-1")
        results.append("tampered")
        results[0].name = "Tampered"
        fresh = self.manager.get_tasks_for_opportunity("opp-gto-1")
        self.assertEqual(len(fresh), 2)
        self.assertEqual(fresh[0].name, "Draft the store listing")

    def test_task_objects_remain_unchanged(self):
        self.manager.get_tasks_for_opportunity("opp-gto-1")
        stored = self.manager.get_task("task-gto-a")
        self.assertEqual(stored.status, STATUS_PENDING)
        self.assertEqual(stored.opportunity_id, "opp-gto-1")

    def test_does_not_modify_manager_state(self):
        before = len(self.manager)
        self.manager.get_tasks_for_opportunity("opp-gto-1")
        self.assertEqual(len(self.manager), before)


class TestGetTaskIdsForOpportunity(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()
        self.manager.add_task(
            _make_task(task_id="task-ids-a", opportunity_id="opp-ids-1")
        )
        self.manager.add_task(
            _make_task(task_id="task-ids-b", opportunity_id="opp-ids-2")
        )
        self.manager.add_task(
            _make_task(task_id="task-ids-c", opportunity_id="opp-ids-1")
        )

    def test_task_ids_returned_correctly(self):
        ids = self.manager.get_task_ids_for_opportunity("opp-ids-1")
        self.assertEqual(ids, ["task-ids-a", "task-ids-c"])

    def test_tasks_belonging_to_different_opportunities(self):
        ids = self.manager.get_task_ids_for_opportunity("opp-ids-2")
        self.assertEqual(ids, ["task-ids-b"])

    def test_no_matching_tasks_returns_empty_list(self):
        self.assertEqual(
            self.manager.get_task_ids_for_opportunity("opp-missing"), []
        )

    def test_invalid_or_empty_opportunity_id(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            self.assertEqual(
                self.manager.get_task_ids_for_opportunity(bad_id), []
            )

    def test_preserves_insertion_order(self):
        ids = self.manager.get_task_ids_for_opportunity("opp-ids-1")
        self.assertEqual(ids[0], "task-ids-a")
        self.assertEqual(ids[1], "task-ids-c")

    def test_returned_list_is_independent(self):
        ids = self.manager.get_task_ids_for_opportunity("opp-ids-1")
        ids.append("tampered")
        fresh = self.manager.get_task_ids_for_opportunity("opp-ids-1")
        self.assertEqual(fresh, ["task-ids-a", "task-ids-c"])

    def test_deduplicates_repeated_ids(self):
        # Stored task_ids can't actually collide (add_task rejects
        # duplicates), so simulate the defensive dedup path directly
        # against the manager's own internal store.
        manager = RevenueTaskManager()
        manager.add_task(
            _make_task(task_id="task-dup-x", opportunity_id="opp-dup")
        )
        duplicate = _make_task(
            task_id="task-dup-x", opportunity_id="opp-dup", name="Duplicate"
        )
        manager._tasks["task-dup-x-shadow"] = duplicate
        manager._tasks["task-dup-x-shadow"].task_id = "task-dup-x"

        ids = manager.get_task_ids_for_opportunity("opp-dup")
        self.assertEqual(ids, ["task-dup-x"])

    def test_does_not_modify_internal_storage(self):
        before = len(self.manager)
        self.manager.get_task_ids_for_opportunity("opp-ids-1")
        self.assertEqual(len(self.manager), before)
        # The underlying tasks are untouched.
        self.assertEqual(
            self.manager.get_task("task-ids-a").opportunity_id, "opp-ids-1"
        )


# ----------------------------------------------------------------------
# 14. get_opportunity_task_status()
# ----------------------------------------------------------------------
class TestGetOpportunityTaskStatus(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def _base_counts(self, opportunity_id, task_count=0):
        return {
            "opportunity_id": opportunity_id,
            "task_count": task_count,
            "pending": 0,
            "ready": 0,
            "in_progress": 0,
            "completed": 0,
            "failed": 0,
            "blocked": 0,
            "cancelled": 0,
            "active_count": 0,
            "final_count": 0,
            "all_completed": False,
            "has_failed": False,
        }

    def test_empty_opportunity_returns_zeroed_summary(self):
        result = self.manager.get_opportunity_task_status("opp-empty")
        self.assertEqual(result, self._base_counts("opp-empty", 0))

    def test_one_pending_task(self):
        self.manager.add_task(
            _make_task(
                task_id="task-pending",
                opportunity_id="opp-status-1",
                status=STATUS_PENDING,
            )
        )
        result = self.manager.get_opportunity_task_status("opp-status-1")
        expected = self._base_counts("opp-status-1", 1)
        expected.update(pending=1)
        self.assertEqual(result, expected)

    def test_ready_task(self):
        self.manager.add_task(
            _make_task(
                task_id="task-ready",
                opportunity_id="opp-status-2",
                status=STATUS_READY,
            )
        )
        result = self.manager.get_opportunity_task_status("opp-status-2")
        expected = self._base_counts("opp-status-2", 1)
        expected.update(ready=1, active_count=1)
        self.assertEqual(result, expected)

    def test_in_progress_task(self):
        self.manager.add_task(
            _make_task(
                task_id="task-inprog",
                opportunity_id="opp-status-3",
                status=STATUS_IN_PROGRESS,
            )
        )
        result = self.manager.get_opportunity_task_status("opp-status-3")
        expected = self._base_counts("opp-status-3", 1)
        expected.update(in_progress=1, active_count=1)
        self.assertEqual(result, expected)

    def test_completed_task(self):
        self.manager.add_task(
            _make_task(
                task_id="task-completed",
                opportunity_id="opp-status-4",
                status=STATUS_COMPLETED,
            )
        )
        result = self.manager.get_opportunity_task_status("opp-status-4")
        expected = self._base_counts("opp-status-4", 1)
        expected.update(completed=1, final_count=1, all_completed=True)
        self.assertEqual(result, expected)

    def test_failed_task(self):
        self.manager.add_task(
            _make_task(
                task_id="task-failed",
                opportunity_id="opp-status-5",
                status=STATUS_FAILED,
            )
        )
        result = self.manager.get_opportunity_task_status("opp-status-5")
        expected = self._base_counts("opp-status-5", 1)
        expected.update(failed=1, final_count=1, has_failed=True)
        self.assertEqual(result, expected)

    def test_blocked_task(self):
        self.manager.add_task(
            _make_task(
                task_id="task-blocked",
                opportunity_id="opp-status-6",
                status=STATUS_BLOCKED,
            )
        )
        result = self.manager.get_opportunity_task_status("opp-status-6")
        expected = self._base_counts("opp-status-6", 1)
        expected.update(blocked=1)
        self.assertEqual(result, expected)

    def test_cancelled_task(self):
        self.manager.add_task(
            _make_task(
                task_id="task-cancelled",
                opportunity_id="opp-status-7",
                status=STATUS_CANCELLED,
            )
        )
        result = self.manager.get_opportunity_task_status("opp-status-7")
        expected = self._base_counts("opp-status-7", 1)
        expected.update(cancelled=1, final_count=1)
        self.assertEqual(result, expected)

    def test_mixed_task_statuses(self):
        opp = "opp-status-mixed"
        self.manager.add_task(
            _make_task(task_id="m-pending", opportunity_id=opp, status=STATUS_PENDING)
        )
        self.manager.add_task(
            _make_task(task_id="m-ready", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(
                task_id="m-inprog", opportunity_id=opp, status=STATUS_IN_PROGRESS
            )
        )
        self.manager.add_task(
            _make_task(
                task_id="m-completed", opportunity_id=opp, status=STATUS_COMPLETED
            )
        )
        self.manager.add_task(
            _make_task(task_id="m-failed", opportunity_id=opp, status=STATUS_FAILED)
        )
        self.manager.add_task(
            _make_task(task_id="m-blocked", opportunity_id=opp, status=STATUS_BLOCKED)
        )
        self.manager.add_task(
            _make_task(
                task_id="m-cancelled", opportunity_id=opp, status=STATUS_CANCELLED
            )
        )
        # Unrelated task on a different opportunity must not be counted.
        self.manager.add_task(
            _make_task(
                task_id="other-opp-task",
                opportunity_id="opp-other",
                status=STATUS_COMPLETED,
            )
        )

        result = self.manager.get_opportunity_task_status(opp)
        self.assertEqual(result["opportunity_id"], opp)
        self.assertEqual(result["task_count"], 7)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["in_progress"], 1)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["cancelled"], 1)
        self.assertEqual(result["active_count"], 2)  # ready + in_progress
        self.assertEqual(result["final_count"], 3)  # completed + failed + cancelled
        self.assertFalse(result["all_completed"])
        self.assertTrue(result["has_failed"])

    def test_all_tasks_completed(self):
        opp = "opp-status-all-completed"
        self.manager.add_task(
            _make_task(task_id="ac-1", opportunity_id=opp, status=STATUS_COMPLETED)
        )
        self.manager.add_task(
            _make_task(task_id="ac-2", opportunity_id=opp, status=STATUS_COMPLETED)
        )
        result = self.manager.get_opportunity_task_status(opp)
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["completed"], 2)
        self.assertTrue(result["all_completed"])
        self.assertFalse(result["has_failed"])

    def test_at_least_one_failed_task(self):
        opp = "opp-status-has-failed"
        self.manager.add_task(
            _make_task(task_id="hf-1", opportunity_id=opp, status=STATUS_COMPLETED)
        )
        self.manager.add_task(
            _make_task(task_id="hf-2", opportunity_id=opp, status=STATUS_FAILED)
        )
        result = self.manager.get_opportunity_task_status(opp)
        self.assertTrue(result["has_failed"])
        self.assertFalse(result["all_completed"])

    def test_invalid_opportunity_id(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            result = self.manager.get_opportunity_task_status(bad_id)
            self.assertEqual(result, self._base_counts(bad_id, 0))

    def test_no_task_or_manager_state_modified(self):
        opp = "opp-status-readonly"
        task = _make_task(task_id="ro-1", opportunity_id=opp, status=STATUS_PENDING)
        self.manager.add_task(task)
        before_len = len(self.manager)

        self.manager.get_opportunity_task_status(opp)

        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("ro-1")
        self.assertEqual(stored.status, STATUS_PENDING)
        self.assertEqual(stored.opportunity_id, opp)
        # The original task object handed to add_task is untouched too.
        self.assertEqual(task.status, STATUS_PENDING)


# ----------------------------------------------------------------------
# 15. get_next_startable_task()
# ----------------------------------------------------------------------
class TestGetNextStartableTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_one_startable_task(self):
        opp = "opp-start-1"
        self.manager.add_task(
            _make_task(task_id="s-1", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_next_startable_task(opp)
        self.assertIsNotNone(result)
        self.assertEqual(result.task_id, "s-1")

    def test_first_blocked_second_startable(self):
        opp = "opp-start-2"
        self.manager.add_task(
            _make_task(task_id="s-blocked", opportunity_id=opp, status=STATUS_BLOCKED)
        )
        self.manager.add_task(
            _make_task(task_id="s-ready", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_next_startable_task(opp)
        self.assertIsNotNone(result)
        self.assertEqual(result.task_id, "s-ready")

    def test_multiple_startable_picks_first_by_insertion_order(self):
        opp = "opp-start-3"
        self.manager.add_task(
            _make_task(task_id="s-first", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="s-second", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_next_startable_task(opp)
        self.assertEqual(result.task_id, "s-first")

    def test_task_with_incomplete_dependencies_is_skipped(self):
        opp = "opp-start-4"
        self.manager.add_task(
            _make_task(
                task_id="s-dep-incomplete",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        result = self.manager.get_next_startable_task(opp)
        self.assertIsNone(result)

    def test_task_with_completed_dependencies_is_selected(self):
        opp = "opp-start-5"
        self.manager.add_task(
            _make_task(
                task_id="s-dep-complete",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        result = self.manager.get_next_startable_task(
            opp, completed_task_ids=["dep-a"]
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.task_id, "s-dep-complete")

    def test_task_without_opportunity_is_not_selected(self):
        opp = "opp-start-6"
        task = _make_task(task_id="s-no-opp", opportunity_id=opp, status=STATUS_READY)
        self.manager.add_task(task)
        # Simulate a corrupted/blank opportunity reference directly in
        # the store, without going through add_task's own validation.
        self.manager._tasks["s-no-opp"].opportunity_id = ""

        result = self.manager.get_next_startable_task(opp)
        self.assertIsNone(result)

    def test_no_matching_tasks_returns_none(self):
        opp = "opp-start-7"
        self.manager.add_task(
            _make_task(
                task_id="other-opp", opportunity_id="opp-different",
                status=STATUS_READY,
            )
        )
        result = self.manager.get_next_startable_task(opp)
        self.assertIsNone(result)

    def test_invalid_opportunity_id(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            self.assertIsNone(self.manager.get_next_startable_task(bad_id))

    def test_none_completed_task_ids_treated_as_empty(self):
        opp = "opp-start-8"
        self.manager.add_task(
            _make_task(
                task_id="s-dep-none",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-x"],
            )
        )
        result = self.manager.get_next_startable_task(
            opp, completed_task_ids=None
        )
        self.assertIsNone(result)

    def test_non_ready_statuses_are_skipped(self):
        opp = "opp-start-9"
        for status in (
            STATUS_PENDING, STATUS_IN_PROGRESS, STATUS_COMPLETED,
            STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED,
        ):
            self.manager.add_task(
                _make_task(
                    task_id=f"s-{status.lower()}", opportunity_id=opp,
                    status=status,
                )
            )
        result = self.manager.get_next_startable_task(opp)
        self.assertIsNone(result)

    def test_no_task_status_or_manager_state_changes(self):
        opp = "opp-start-10"
        task = _make_task(task_id="s-readonly", opportunity_id=opp, status=STATUS_READY)
        self.manager.add_task(task)
        before_len = len(self.manager)

        result = self.manager.get_next_startable_task(opp)

        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("s-readonly")
        self.assertEqual(stored.status, STATUS_READY)
        self.assertEqual(task.status, STATUS_READY)
        # Returned task is an independent copy.
        result.name = "Tampered"
        fresh = self.manager.get_task("s-readonly")
        self.assertEqual(fresh.name, "Draft the store listing")


# ----------------------------------------------------------------------
# 16. inspect_opportunity_execution_queue()
# ----------------------------------------------------------------------
class TestInspectOpportunityExecutionQueue(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def _empty_report(self, opportunity_id):
        return {
            "opportunity_id": opportunity_id,
            "task_count": 0,
            "startable_task_ids": [],
            "blocked_task_ids": [],
            "in_progress_task_ids": [],
            "completed_task_ids": [],
            "failed_task_ids": [],
            "cancelled_task_ids": [],
            "next_startable_task_id": None,
        }

    def test_empty_opportunity(self):
        result = self.manager.inspect_opportunity_execution_queue("opp-empty")
        self.assertEqual(result, self._empty_report("opp-empty"))

    def test_pending_task(self):
        opp = "opp-q-pending"
        self.manager.add_task(
            _make_task(task_id="q-pending", opportunity_id=opp, status=STATUS_PENDING)
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["task_count"], 1)
        self.assertEqual(result["startable_task_ids"], [])
        self.assertEqual(result["blocked_task_ids"], ["q-pending"])
        self.assertIsNone(result["next_startable_task_id"])

    def test_ready_task(self):
        opp = "opp-q-ready"
        self.manager.add_task(
            _make_task(task_id="q-ready", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["startable_task_ids"], ["q-ready"])
        self.assertEqual(result["blocked_task_ids"], [])
        self.assertEqual(result["next_startable_task_id"], "q-ready")

    def test_blocked_status_task(self):
        opp = "opp-q-blocked"
        self.manager.add_task(
            _make_task(task_id="q-blocked", opportunity_id=opp, status=STATUS_BLOCKED)
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["blocked_task_ids"], ["q-blocked"])
        self.assertEqual(result["startable_task_ids"], [])
        self.assertIsNone(result["next_startable_task_id"])

    def test_in_progress_task(self):
        opp = "opp-q-inprog"
        self.manager.add_task(
            _make_task(
                task_id="q-inprog", opportunity_id=opp, status=STATUS_IN_PROGRESS
            )
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["in_progress_task_ids"], ["q-inprog"])
        self.assertEqual(result["startable_task_ids"], [])
        self.assertEqual(result["blocked_task_ids"], [])

    def test_completed_task(self):
        opp = "opp-q-completed"
        self.manager.add_task(
            _make_task(
                task_id="q-completed", opportunity_id=opp, status=STATUS_COMPLETED
            )
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["completed_task_ids"], ["q-completed"])
        self.assertEqual(result["blocked_task_ids"], [])

    def test_failed_task(self):
        opp = "opp-q-failed"
        self.manager.add_task(
            _make_task(task_id="q-failed", opportunity_id=opp, status=STATUS_FAILED)
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["failed_task_ids"], ["q-failed"])
        self.assertEqual(result["blocked_task_ids"], [])

    def test_cancelled_task(self):
        opp = "opp-q-cancelled"
        self.manager.add_task(
            _make_task(
                task_id="q-cancelled", opportunity_id=opp, status=STATUS_CANCELLED
            )
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["cancelled_task_ids"], ["q-cancelled"])
        self.assertEqual(result["blocked_task_ids"], [])

    def test_multiple_tasks_across_statuses(self):
        opp = "opp-q-multi"
        self.manager.add_task(
            _make_task(task_id="q-m-pending", opportunity_id=opp, status=STATUS_PENDING)
        )
        self.manager.add_task(
            _make_task(task_id="q-m-ready", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(
                task_id="q-m-inprog", opportunity_id=opp, status=STATUS_IN_PROGRESS
            )
        )
        self.manager.add_task(
            _make_task(
                task_id="q-m-completed", opportunity_id=opp, status=STATUS_COMPLETED
            )
        )
        self.manager.add_task(
            _make_task(task_id="q-m-failed", opportunity_id=opp, status=STATUS_FAILED)
        )
        self.manager.add_task(
            _make_task(
                task_id="q-m-cancelled", opportunity_id=opp, status=STATUS_CANCELLED
            )
        )
        # Unrelated task on a different opportunity must not be counted.
        self.manager.add_task(
            _make_task(
                task_id="other-opp", opportunity_id="opp-other", status=STATUS_READY
            )
        )

        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["opportunity_id"], opp)
        self.assertEqual(result["task_count"], 6)
        self.assertEqual(result["startable_task_ids"], ["q-m-ready"])
        self.assertEqual(result["blocked_task_ids"], ["q-m-pending"])
        self.assertEqual(result["in_progress_task_ids"], ["q-m-inprog"])
        self.assertEqual(result["completed_task_ids"], ["q-m-completed"])
        self.assertEqual(result["failed_task_ids"], ["q-m-failed"])
        self.assertEqual(result["cancelled_task_ids"], ["q-m-cancelled"])
        self.assertEqual(result["next_startable_task_id"], "q-m-ready")

    def test_dependency_completion_moves_task_to_startable(self):
        opp = "opp-q-dep"
        self.manager.add_task(
            _make_task(
                task_id="q-dep",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        incomplete = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(incomplete["blocked_task_ids"], ["q-dep"])
        self.assertEqual(incomplete["startable_task_ids"], [])

        complete = self.manager.inspect_opportunity_execution_queue(
            opp, completed_task_ids=["dep-a"]
        )
        self.assertEqual(complete["startable_task_ids"], ["q-dep"])
        self.assertEqual(complete["blocked_task_ids"], [])
        self.assertEqual(complete["next_startable_task_id"], "q-dep")

    def test_correct_insertion_order_within_buckets(self):
        opp = "opp-q-order"
        self.manager.add_task(
            _make_task(task_id="q-o-1", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="q-o-2", opportunity_id=opp, status=STATUS_PENDING)
        )
        self.manager.add_task(
            _make_task(task_id="q-o-3", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="q-o-4", opportunity_id=opp, status=STATUS_PENDING)
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["startable_task_ids"], ["q-o-1", "q-o-3"])
        self.assertEqual(result["blocked_task_ids"], ["q-o-2", "q-o-4"])

    def test_next_startable_task_id_is_first_startable(self):
        opp = "opp-q-next"
        self.manager.add_task(
            _make_task(task_id="q-n-1", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="q-n-2", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(result["next_startable_task_id"], "q-n-1")

    def test_invalid_opportunity_id(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            result = self.manager.inspect_opportunity_execution_queue(bad_id)
            self.assertEqual(result, self._empty_report(bad_id))

    def test_none_completed_task_ids_treated_as_empty(self):
        opp = "opp-q-none-deps"
        self.manager.add_task(
            _make_task(
                task_id="q-none-dep",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-y"],
            )
        )
        result = self.manager.inspect_opportunity_execution_queue(
            opp, completed_task_ids=None
        )
        self.assertEqual(result["blocked_task_ids"], ["q-none-dep"])
        self.assertEqual(result["startable_task_ids"], [])

    def test_returned_lists_are_independent(self):
        opp = "opp-q-independent"
        self.manager.add_task(
            _make_task(task_id="q-i-1", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.inspect_opportunity_execution_queue(opp)
        result["startable_task_ids"].append("tampered")
        fresh = self.manager.inspect_opportunity_execution_queue(opp)
        self.assertEqual(fresh["startable_task_ids"], ["q-i-1"])

    def test_manager_and_task_state_unchanged(self):
        opp = "opp-q-readonly"
        task = _make_task(
            task_id="q-readonly",
            opportunity_id=opp,
            status=STATUS_READY,
            dependencies=["dep-z"],
        )
        self.manager.add_task(task)
        before_len = len(self.manager)

        self.manager.inspect_opportunity_execution_queue(
            opp, completed_task_ids=["dep-z"]
        )

        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("q-readonly")
        self.assertEqual(stored.status, STATUS_READY)
        self.assertEqual(stored.dependencies, ["dep-z"])
        self.assertEqual(task.status, STATUS_READY)
        self.assertEqual(task.dependencies, ["dep-z"])


# ----------------------------------------------------------------------
# 17. get_startable_tasks()
# ----------------------------------------------------------------------
class TestGetStartableTasks(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_no_tasks_returns_empty_list(self):
        result = self.manager.get_startable_tasks("opp-gst-empty")
        self.assertEqual(result, [])

    def test_one_startable_task(self):
        opp = "opp-gst-1"
        self.manager.add_task(
            _make_task(task_id="gst-1", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_startable_tasks(opp)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].task_id, "gst-1")

    def test_multiple_startable_tasks(self):
        opp = "opp-gst-2"
        self.manager.add_task(
            _make_task(task_id="gst-2a", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="gst-2b", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_startable_tasks(opp)
        self.assertEqual([t.task_id for t in result], ["gst-2a", "gst-2b"])

    def test_blocked_tasks_excluded(self):
        opp = "opp-gst-3"
        self.manager.add_task(
            _make_task(task_id="gst-3-blocked", opportunity_id=opp, status=STATUS_BLOCKED)
        )
        self.manager.add_task(
            _make_task(task_id="gst-3-pending", opportunity_id=opp, status=STATUS_PENDING)
        )
        result = self.manager.get_startable_tasks(opp)
        self.assertEqual(result, [])

    def test_incomplete_dependencies_excluded(self):
        opp = "opp-gst-4"
        self.manager.add_task(
            _make_task(
                task_id="gst-4-dep",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        result = self.manager.get_startable_tasks(opp)
        self.assertEqual(result, [])

    def test_completed_dependencies_included(self):
        opp = "opp-gst-5"
        self.manager.add_task(
            _make_task(
                task_id="gst-5-dep",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        result = self.manager.get_startable_tasks(opp, completed_task_ids=["dep-a"])
        self.assertEqual([t.task_id for t in result], ["gst-5-dep"])

    def test_mixed_task_statuses(self):
        opp = "opp-gst-6"
        self.manager.add_task(
            _make_task(task_id="gst-6-pending", opportunity_id=opp, status=STATUS_PENDING)
        )
        self.manager.add_task(
            _make_task(task_id="gst-6-ready", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(
                task_id="gst-6-inprog", opportunity_id=opp, status=STATUS_IN_PROGRESS
            )
        )
        self.manager.add_task(
            _make_task(
                task_id="gst-6-completed", opportunity_id=opp, status=STATUS_COMPLETED
            )
        )
        self.manager.add_task(
            _make_task(task_id="gst-6-failed", opportunity_id=opp, status=STATUS_FAILED)
        )
        result = self.manager.get_startable_tasks(opp)
        self.assertEqual([t.task_id for t in result], ["gst-6-ready"])

    def test_tasks_from_different_opportunities_excluded(self):
        opp = "opp-gst-7"
        self.manager.add_task(
            _make_task(task_id="gst-7-mine", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(
                task_id="gst-7-other", opportunity_id="opp-gst-other",
                status=STATUS_READY,
            )
        )
        result = self.manager.get_startable_tasks(opp)
        self.assertEqual([t.task_id for t in result], ["gst-7-mine"])

    def test_correct_insertion_order(self):
        opp = "opp-gst-8"
        self.manager.add_task(
            _make_task(task_id="gst-8-c", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="gst-8-a", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="gst-8-b", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_startable_tasks(opp)
        self.assertEqual(
            [t.task_id for t in result], ["gst-8-c", "gst-8-a", "gst-8-b"]
        )

    def test_invalid_opportunity_id(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            self.assertEqual(self.manager.get_startable_tasks(bad_id), [])

    def test_none_completed_task_ids_treated_as_empty(self):
        opp = "opp-gst-9"
        self.manager.add_task(
            _make_task(
                task_id="gst-9-dep",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-x"],
            )
        )
        result = self.manager.get_startable_tasks(opp, completed_task_ids=None)
        self.assertEqual(result, [])

    def test_no_task_or_manager_state_modified(self):
        opp = "opp-gst-10"
        task = _make_task(task_id="gst-10", opportunity_id=opp, status=STATUS_READY)
        self.manager.add_task(task)
        before_len = len(self.manager)

        result = self.manager.get_startable_tasks(opp)

        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("gst-10")
        self.assertEqual(stored.status, STATUS_READY)
        self.assertEqual(task.status, STATUS_READY)
        # Returned list and its entries are independent copies.
        result.append("tampered")
        result[0].name = "Tampered"
        fresh = self.manager.get_startable_tasks(opp)
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0].name, "Draft the store listing")


# ----------------------------------------------------------------------
# 18. get_execution_queue_summary()
# ----------------------------------------------------------------------
class TestGetExecutionQueueSummary(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def _empty_summary(self, opportunity_id):
        return {
            "opportunity_id": opportunity_id,
            "task_count": 0,
            "startable_count": 0,
            "blocked_count": 0,
            "in_progress_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "cancelled_count": 0,
            "next_startable_task_id": None,
            "has_startable_tasks": False,
            "has_blocked_tasks": False,
            "has_failed_tasks": False,
            "all_completed": False,
        }

    def test_empty_opportunity(self):
        result = self.manager.get_execution_queue_summary("opp-qs-empty")
        self.assertEqual(result, self._empty_summary("opp-qs-empty"))

    def test_all_task_statuses(self):
        opp = "opp-qs-all-statuses"
        self.manager.add_task(
            _make_task(task_id="qs-pending", opportunity_id=opp, status=STATUS_PENDING)
        )
        self.manager.add_task(
            _make_task(task_id="qs-ready", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(
                task_id="qs-inprog", opportunity_id=opp, status=STATUS_IN_PROGRESS
            )
        )
        self.manager.add_task(
            _make_task(
                task_id="qs-completed", opportunity_id=opp, status=STATUS_COMPLETED
            )
        )
        self.manager.add_task(
            _make_task(task_id="qs-failed", opportunity_id=opp, status=STATUS_FAILED)
        )
        self.manager.add_task(
            _make_task(task_id="qs-blocked", opportunity_id=opp, status=STATUS_BLOCKED)
        )
        self.manager.add_task(
            _make_task(
                task_id="qs-cancelled", opportunity_id=opp, status=STATUS_CANCELLED
            )
        )
        result = self.manager.get_execution_queue_summary(opp)
        self.assertEqual(result["opportunity_id"], opp)
        self.assertEqual(result["task_count"], 7)
        self.assertEqual(result["startable_count"], 1)
        self.assertEqual(result["blocked_count"], 2)  # pending + blocked-status
        self.assertEqual(result["in_progress_count"], 1)
        self.assertEqual(result["completed_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["cancelled_count"], 1)
        self.assertEqual(result["next_startable_task_id"], "qs-ready")
        self.assertTrue(result["has_startable_tasks"])
        self.assertTrue(result["has_blocked_tasks"])
        self.assertTrue(result["has_failed_tasks"])
        self.assertFalse(result["all_completed"])

    def test_multiple_startable_tasks(self):
        opp = "opp-qs-multi-startable"
        self.manager.add_task(
            _make_task(task_id="qs-ms-1", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="qs-ms-2", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_execution_queue_summary(opp)
        self.assertEqual(result["startable_count"], 2)
        self.assertTrue(result["has_startable_tasks"])
        self.assertEqual(result["next_startable_task_id"], "qs-ms-1")

    def test_blocked_dependencies(self):
        opp = "opp-qs-dep-blocked"
        self.manager.add_task(
            _make_task(
                task_id="qs-dep-blocked",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        result = self.manager.get_execution_queue_summary(opp)
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["startable_count"], 0)
        self.assertTrue(result["has_blocked_tasks"])
        self.assertFalse(result["has_startable_tasks"])
        self.assertIsNone(result["next_startable_task_id"])

    def test_completed_dependencies(self):
        opp = "opp-qs-dep-completed"
        self.manager.add_task(
            _make_task(
                task_id="qs-dep-completed",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        result = self.manager.get_execution_queue_summary(
            opp, completed_task_ids=["dep-a"]
        )
        self.assertEqual(result["startable_count"], 1)
        self.assertEqual(result["blocked_count"], 0)
        self.assertTrue(result["has_startable_tasks"])
        self.assertEqual(result["next_startable_task_id"], "qs-dep-completed")

    def test_failed_tasks(self):
        opp = "opp-qs-failed"
        self.manager.add_task(
            _make_task(task_id="qs-f-1", opportunity_id=opp, status=STATUS_FAILED)
        )
        self.manager.add_task(
            _make_task(task_id="qs-f-2", opportunity_id=opp, status=STATUS_COMPLETED)
        )
        result = self.manager.get_execution_queue_summary(opp)
        self.assertEqual(result["failed_count"], 1)
        self.assertTrue(result["has_failed_tasks"])
        self.assertFalse(result["all_completed"])

    def test_all_tasks_completed(self):
        opp = "opp-qs-all-completed"
        self.manager.add_task(
            _make_task(task_id="qs-ac-1", opportunity_id=opp, status=STATUS_COMPLETED)
        )
        self.manager.add_task(
            _make_task(task_id="qs-ac-2", opportunity_id=opp, status=STATUS_COMPLETED)
        )
        result = self.manager.get_execution_queue_summary(opp)
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["completed_count"], 2)
        self.assertTrue(result["all_completed"])
        self.assertFalse(result["has_failed_tasks"])

    def test_correct_next_startable_task_id(self):
        opp = "opp-qs-next"
        self.manager.add_task(
            _make_task(task_id="qs-n-blocked", opportunity_id=opp, status=STATUS_PENDING)
        )
        self.manager.add_task(
            _make_task(task_id="qs-n-ready", opportunity_id=opp, status=STATUS_READY)
        )
        result = self.manager.get_execution_queue_summary(opp)
        self.assertEqual(result["next_startable_task_id"], "qs-n-ready")

    def test_invalid_opportunity_id(self):
        for bad_id in (None, "", "   ", 123, [], {}):
            result = self.manager.get_execution_queue_summary(bad_id)
            self.assertEqual(result, self._empty_summary(bad_id))

    def test_none_completed_task_ids_treated_as_empty(self):
        opp = "opp-qs-none-deps"
        self.manager.add_task(
            _make_task(
                task_id="qs-none-dep",
                opportunity_id=opp,
                status=STATUS_READY,
                dependencies=["dep-y"],
            )
        )
        result = self.manager.get_execution_queue_summary(
            opp, completed_task_ids=None
        )
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["startable_count"], 0)

    def test_no_state_mutation(self):
        opp = "opp-qs-readonly"
        task = _make_task(
            task_id="qs-readonly",
            opportunity_id=opp,
            status=STATUS_READY,
            dependencies=["dep-z"],
        )
        self.manager.add_task(task)
        before_len = len(self.manager)

        self.manager.get_execution_queue_summary(opp, completed_task_ids=["dep-z"])

        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("qs-readonly")
        self.assertEqual(stored.status, STATUS_READY)
        self.assertEqual(stored.dependencies, ["dep-z"])
        self.assertEqual(task.status, STATUS_READY)
        self.assertEqual(task.dependencies, ["dep-z"])


# ----------------------------------------------------------------------
# 19. prepare_task_execution()
# ----------------------------------------------------------------------
class TestPrepareTaskExecution(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_valid_ready_task_is_prepared(self):
        self.manager.add_task(
            _make_task(task_id="pte-ready", opportunity_id="opp-pte-1", status=STATUS_READY)
        )
        result = self.manager.prepare_task_execution("pte-ready")
        self.assertEqual(result["task_id"], "pte-ready")
        self.assertEqual(result["opportunity_id"], "opp-pte-1")
        self.assertEqual(result["status"], STATUS_READY)
        self.assertTrue(result["ready"])
        self.assertTrue(result["startable"])
        self.assertTrue(result["has_opportunity"])
        self.assertTrue(result["prepared"])
        self.assertNotIn("error", result)
        self.assertEqual(
            result["dependency_status"],
            {"has_dependencies": False, "total": 0, "completed": 0,
             "remaining": [], "ready": True},
        )

    def test_task_with_completed_dependencies_is_prepared(self):
        self.manager.add_task(
            _make_task(
                task_id="pte-dep-complete",
                opportunity_id="opp-pte-2",
                status=STATUS_READY,
                dependencies=["dep-a"],
            )
        )
        result = self.manager.prepare_task_execution(
            "pte-dep-complete", completed_task_ids=["dep-a"]
        )
        self.assertTrue(result["ready"])
        self.assertTrue(result["prepared"])
        self.assertEqual(result["dependency_status"]["remaining"], [])
        self.assertTrue(result["dependency_status"]["ready"])

    def test_task_with_incomplete_dependencies_is_not_prepared(self):
        self.manager.add_task(
            _make_task(
                task_id="pte-dep-incomplete",
                opportunity_id="opp-pte-3",
                status=STATUS_READY,
                dependencies=["dep-a", "dep-b"],
            )
        )
        result = self.manager.prepare_task_execution(
            "pte-dep-incomplete", completed_task_ids=["dep-a"]
        )
        self.assertFalse(result["ready"])
        self.assertFalse(result["prepared"])
        # startable/has_opportunity are unaffected by dependencies.
        self.assertTrue(result["startable"])
        self.assertTrue(result["has_opportunity"])
        self.assertEqual(result["dependency_status"]["remaining"], ["dep-b"])
        self.assertFalse(result["dependency_status"]["ready"])

    def test_task_without_opportunity_is_not_prepared(self):
        task = _make_task(
            task_id="pte-no-opp", opportunity_id="opp-pte-4", status=STATUS_READY
        )
        self.manager.add_task(task)
        # Simulate a corrupted/blank opportunity reference directly in
        # the store, without going through add_task's own validation.
        self.manager._tasks["pte-no-opp"].opportunity_id = ""

        result = self.manager.prepare_task_execution("pte-no-opp")
        self.assertFalse(result["has_opportunity"])
        self.assertFalse(result["startable"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["prepared"])

    def test_non_startable_task_is_not_prepared(self):
        self.manager.add_task(
            _make_task(
                task_id="pte-pending", opportunity_id="opp-pte-5", status=STATUS_PENDING
            )
        )
        result = self.manager.prepare_task_execution("pte-pending")
        self.assertEqual(result["status"], STATUS_PENDING)
        self.assertFalse(result["startable"])
        self.assertFalse(result["ready"])
        self.assertFalse(result["prepared"])

    def test_missing_task_returns_safe_structured_result(self):
        result = self.manager.prepare_task_execution("pte-does-not-exist")
        self.assertEqual(
            result,
            {
                "task_id": "pte-does-not-exist",
                "opportunity_id": None,
                "status": None,
                "ready": False,
                "startable": False,
                "has_opportunity": False,
                "dependency_status": None,
                "prepared": False,
                "error": "task_not_found",
            },
        )

    def test_none_completed_task_ids_treated_as_empty(self):
        self.manager.add_task(
            _make_task(
                task_id="pte-none-deps",
                opportunity_id="opp-pte-6",
                status=STATUS_READY,
                dependencies=["dep-x"],
            )
        )
        result = self.manager.prepare_task_execution(
            "pte-none-deps", completed_task_ids=None
        )
        self.assertFalse(result["ready"])
        self.assertFalse(result["prepared"])
        self.assertEqual(result["dependency_status"]["remaining"], ["dep-x"])

    def test_dependency_status_matches_task_helper_directly(self):
        task = _make_task(
            task_id="pte-dep-match",
            opportunity_id="opp-pte-7",
            status=STATUS_READY,
            dependencies=["dep-a", "dep-b"],
        )
        self.manager.add_task(task)
        completed = ["dep-a"]

        result = self.manager.prepare_task_execution(
            "pte-dep-match", completed_task_ids=completed
        )
        expected = task.get_dependency_status(completed)
        self.assertEqual(result["dependency_status"], expected)

    def test_prepared_true_only_when_fully_ready(self):
        # ready + startable + no deps -> prepared True
        self.manager.add_task(
            _make_task(task_id="pte-true", opportunity_id="opp-pte-8", status=STATUS_READY)
        )
        self.assertTrue(self.manager.prepare_task_execution("pte-true")["prepared"])

        # ready status but blocked by an incomplete dependency -> prepared False
        self.manager.add_task(
            _make_task(
                task_id="pte-false",
                opportunity_id="opp-pte-8",
                status=STATUS_READY,
                dependencies=["dep-unmet"],
            )
        )
        self.assertFalse(self.manager.prepare_task_execution("pte-false")["prepared"])

    def test_no_task_or_manager_state_modified(self):
        opp = "opp-pte-9"
        task = _make_task(
            task_id="pte-readonly",
            opportunity_id=opp,
            status=STATUS_READY,
            dependencies=["dep-z"],
        )
        self.manager.add_task(task)
        before_len = len(self.manager)

        self.manager.prepare_task_execution("pte-readonly", completed_task_ids=["dep-z"])

        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("pte-readonly")
        self.assertEqual(stored.status, STATUS_READY)
        self.assertEqual(stored.dependencies, ["dep-z"])
        self.assertEqual(task.status, STATUS_READY)
        self.assertEqual(task.dependencies, ["dep-z"])


# ----------------------------------------------------------------------
# 20. start_task()
# ----------------------------------------------------------------------
class TestStartTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_successful_ready_to_in_progress_transition(self):
        self.manager.add_task(
            _make_task(task_id="st-ready", opportunity_id="opp-st-1", status=STATUS_READY)
        )
        result = self.manager.start_task("st-ready")
        self.assertEqual(
            result,
            {
                "success": True,
                "task_id": "st-ready",
                "opportunity_id": "opp-st-1",
                "previous_status": STATUS_READY,
                "status": STATUS_IN_PROGRESS,
                "started": True,
            },
        )
        stored = self.manager.get_task("st-ready")
        self.assertEqual(stored.status, STATUS_IN_PROGRESS)

    def test_missing_task(self):
        result = self.manager.start_task("st-does-not-exist")
        self.assertEqual(
            result,
            {
                "success": False,
                "task_id": "st-does-not-exist",
                "opportunity_id": None,
                "previous_status": None,
                "status": None,
                "started": False,
                "error": "task_not_found",
            },
        )

    def test_pending_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="st-pending", opportunity_id="opp-st-2", status=STATUS_PENDING)
        )
        result = self.manager.start_task("st-pending")
        self.assertFalse(result["success"])
        self.assertFalse(result["started"])
        self.assertEqual(result["previous_status"], STATUS_PENDING)
        self.assertEqual(result["status"], STATUS_PENDING)
        self.assertEqual(result["error"], "not_ready")
        self.assertEqual(self.manager.get_task("st-pending").status, STATUS_PENDING)

    def test_blocked_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="st-blocked", opportunity_id="opp-st-3", status=STATUS_BLOCKED)
        )
        result = self.manager.start_task("st-blocked")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_BLOCKED)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["error"], "not_ready")
        self.assertEqual(self.manager.get_task("st-blocked").status, STATUS_BLOCKED)

    def test_completed_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="st-completed", opportunity_id="opp-st-4", status=STATUS_COMPLETED)
        )
        result = self.manager.start_task("st-completed")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_COMPLETED)
        self.assertEqual(result["status"], STATUS_COMPLETED)
        self.assertEqual(result["error"], "not_ready")
        self.assertEqual(self.manager.get_task("st-completed").status, STATUS_COMPLETED)

    def test_failed_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="st-failed", opportunity_id="opp-st-5", status=STATUS_FAILED)
        )
        result = self.manager.start_task("st-failed")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_FAILED)
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["error"], "not_ready")
        self.assertEqual(self.manager.get_task("st-failed").status, STATUS_FAILED)

    def test_cancelled_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="st-cancelled", opportunity_id="opp-st-6", status=STATUS_CANCELLED)
        )
        result = self.manager.start_task("st-cancelled")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_CANCELLED)
        self.assertEqual(result["status"], STATUS_CANCELLED)
        self.assertEqual(result["error"], "not_ready")
        self.assertEqual(self.manager.get_task("st-cancelled").status, STATUS_CANCELLED)

    def test_incomplete_dependencies_block_start(self):
        self.manager.add_task(
            _make_task(
                task_id="st-dep-incomplete",
                opportunity_id="opp-st-7",
                status=STATUS_READY,
                dependencies=["dep-a", "dep-b"],
            )
        )
        result = self.manager.start_task(
            "st-dep-incomplete", completed_task_ids=["dep-a"]
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["started"])
        self.assertEqual(result["previous_status"], STATUS_READY)
        self.assertEqual(result["status"], STATUS_READY)
        self.assertEqual(result["error"], "dependencies_not_satisfied")
        self.assertEqual(self.manager.get_task("st-dep-incomplete").status, STATUS_READY)

    def test_completed_dependencies_allow_start(self):
        self.manager.add_task(
            _make_task(
                task_id="st-dep-complete",
                opportunity_id="opp-st-8",
                status=STATUS_READY,
                dependencies=["dep-a", "dep-b"],
            )
        )
        result = self.manager.start_task(
            "st-dep-complete", completed_task_ids=["dep-a", "dep-b"]
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["started"])
        self.assertEqual(result["previous_status"], STATUS_READY)
        self.assertEqual(result["status"], STATUS_IN_PROGRESS)
        self.assertEqual(self.manager.get_task("st-dep-complete").status, STATUS_IN_PROGRESS)

    def test_none_completed_task_ids_treated_as_empty(self):
        self.manager.add_task(
            _make_task(
                task_id="st-dep-none",
                opportunity_id="opp-st-9",
                status=STATUS_READY,
                dependencies=["dep-x"],
            )
        )
        result = self.manager.start_task("st-dep-none", completed_task_ids=None)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "dependencies_not_satisfied")
        self.assertEqual(self.manager.get_task("st-dep-none").status, STATUS_READY)

    def test_missing_opportunity_blocks_start(self):
        task = _make_task(
            task_id="st-no-opp", opportunity_id="opp-st-10", status=STATUS_READY
        )
        self.manager.add_task(task)
        # Simulate a corrupted/blank opportunity reference directly in
        # the store, without going through add_task's own validation.
        self.manager._tasks["st-no-opp"].opportunity_id = ""

        result = self.manager.start_task("st-no-opp")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "no_opportunity")
        self.assertEqual(result["previous_status"], STATUS_READY)
        self.assertEqual(result["status"], STATUS_READY)
        self.assertEqual(self.manager.get_task("st-no-opp").status, STATUS_READY)

    def test_invalid_task_id(self):
        for bad_id in (None, "", "   ", 123):
            result = self.manager.start_task(bad_id)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "task_not_found")
            self.assertEqual(result["task_id"], bad_id)

    def test_only_target_task_changes(self):
        opp = "opp-st-11"
        self.manager.add_task(
            _make_task(task_id="st-other-1", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="st-target", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="st-other-2", opportunity_id=opp, status=STATUS_PENDING)
        )

        result = self.manager.start_task("st-target")

        self.assertTrue(result["success"])
        self.assertEqual(self.manager.get_task("st-target").status, STATUS_IN_PROGRESS)
        self.assertEqual(self.manager.get_task("st-other-1").status, STATUS_READY)
        self.assertEqual(self.manager.get_task("st-other-2").status, STATUS_PENDING)

    def test_no_other_manager_or_task_state_changes(self):
        opp = "opp-st-12"
        task = _make_task(
            task_id="st-side-effect-free",
            opportunity_id=opp,
            status=STATUS_READY,
            name="Draft the store listing",
            description="Write the app store listing copy for the opportunity.",
            priority=PRIORITY_HIGH,
            dependencies=["dep-done"],
            metadata={"note": "keep me"},
        )
        self.manager.add_task(task)
        before_len = len(self.manager)

        result = self.manager.start_task(
            "st-side-effect-free", completed_task_ids=["dep-done"]
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("st-side-effect-free")
        self.assertEqual(stored.status, STATUS_IN_PROGRESS)
        # Nothing besides status changed.
        self.assertEqual(stored.opportunity_id, opp)
        self.assertEqual(stored.name, "Draft the store listing")
        self.assertEqual(stored.priority, PRIORITY_HIGH)
        self.assertEqual(stored.dependencies, ["dep-done"])
        self.assertEqual(stored.metadata, {"note": "keep me"})
        # The caller's own local reference was never mutated in place;
        # it reflects the same store, read back independently.
        self.assertEqual(task.status, STATUS_IN_PROGRESS)


# ----------------------------------------------------------------------
# 21. complete_task()
# ----------------------------------------------------------------------
class TestCompleteTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_successful_in_progress_to_completed_transition(self):
        self.manager.add_task(
            _make_task(
                task_id="ct-in-progress",
                opportunity_id="opp-ct-1",
                status=STATUS_IN_PROGRESS,
            )
        )
        result = self.manager.complete_task("ct-in-progress")
        self.assertEqual(
            result,
            {
                "success": True,
                "task_id": "ct-in-progress",
                "opportunity_id": "opp-ct-1",
                "previous_status": STATUS_IN_PROGRESS,
                "status": STATUS_COMPLETED,
                "completed": True,
                "output": None,
                "metadata": None,
            },
        )
        self.assertEqual(self.manager.get_task("ct-in-progress").status, STATUS_COMPLETED)

    def test_output_is_returned_but_not_stored_on_task(self):
        self.manager.add_task(
            _make_task(
                task_id="ct-output",
                opportunity_id="opp-ct-2",
                status=STATUS_IN_PROGRESS,
            )
        )
        output = {"summary": "Draft written", "word_count": 420}
        result = self.manager.complete_task("ct-output", output=output)
        self.assertTrue(result["success"])
        self.assertEqual(result["output"], output)
        # The RevenueTask model has no output field; to_dict() must
        # not have gained one, and the task's own recognized fields
        # are untouched aside from status.
        stored = self.manager.get_task("ct-output")
        self.assertNotIn("output", stored.__slots__)
        self.assertEqual(stored.status, STATUS_COMPLETED)

    def test_metadata_is_returned_but_not_merged_into_task_metadata(self):
        self.manager.add_task(
            _make_task(
                task_id="ct-metadata",
                opportunity_id="opp-ct-3",
                status=STATUS_IN_PROGRESS,
                metadata={"original": "value"},
            )
        )
        extra_metadata = {"reviewer": "auto-check", "score": 9}
        result = self.manager.complete_task("ct-metadata", metadata=extra_metadata)
        self.assertTrue(result["success"])
        self.assertEqual(result["metadata"], extra_metadata)
        # The task's own stored metadata is left exactly as it was.
        stored = self.manager.get_task("ct-metadata")
        self.assertEqual(stored.metadata, {"original": "value"})

    def test_missing_task(self):
        result = self.manager.complete_task("ct-does-not-exist")
        self.assertEqual(
            result,
            {
                "success": False,
                "task_id": "ct-does-not-exist",
                "opportunity_id": None,
                "previous_status": None,
                "status": None,
                "completed": False,
                "error": "task_not_found",
            },
        )

    def test_pending_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="ct-pending", opportunity_id="opp-ct-4", status=STATUS_PENDING)
        )
        result = self.manager.complete_task("ct-pending")
        self.assertFalse(result["success"])
        self.assertFalse(result["completed"])
        self.assertEqual(result["previous_status"], STATUS_PENDING)
        self.assertEqual(result["status"], STATUS_PENDING)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ct-pending").status, STATUS_PENDING)

    def test_ready_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="ct-ready", opportunity_id="opp-ct-5", status=STATUS_READY)
        )
        result = self.manager.complete_task("ct-ready")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_READY)
        self.assertEqual(result["status"], STATUS_READY)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ct-ready").status, STATUS_READY)

    def test_blocked_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="ct-blocked", opportunity_id="opp-ct-6", status=STATUS_BLOCKED)
        )
        result = self.manager.complete_task("ct-blocked")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_BLOCKED)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ct-blocked").status, STATUS_BLOCKED)

    def test_failed_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="ct-failed", opportunity_id="opp-ct-7", status=STATUS_FAILED)
        )
        result = self.manager.complete_task("ct-failed")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_FAILED)
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ct-failed").status, STATUS_FAILED)

    def test_cancelled_task_is_rejected(self):
        self.manager.add_task(
            _make_task(
                task_id="ct-cancelled", opportunity_id="opp-ct-8", status=STATUS_CANCELLED
            )
        )
        result = self.manager.complete_task("ct-cancelled")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_CANCELLED)
        self.assertEqual(result["status"], STATUS_CANCELLED)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ct-cancelled").status, STATUS_CANCELLED)

    def test_invalid_transitions_are_rejected_for_every_non_in_progress_status(self):
        for status in (
            STATUS_PENDING, STATUS_READY, STATUS_BLOCKED,
            STATUS_FAILED, STATUS_CANCELLED,
        ):
            task_id = f"ct-invalid-{status.lower()}"
            self.manager.add_task(
                _make_task(task_id=task_id, opportunity_id="opp-ct-9", status=status)
            )
            result = self.manager.complete_task(task_id)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "not_in_progress")
            self.assertEqual(self.manager.get_task(task_id).status, status)

    def test_other_tasks_remain_unchanged(self):
        opp = "opp-ct-10"
        self.manager.add_task(
            _make_task(task_id="ct-other-1", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="ct-target", opportunity_id=opp, status=STATUS_IN_PROGRESS)
        )
        self.manager.add_task(
            _make_task(task_id="ct-other-2", opportunity_id=opp, status=STATUS_PENDING)
        )

        result = self.manager.complete_task("ct-target")

        self.assertTrue(result["success"])
        self.assertEqual(self.manager.get_task("ct-target").status, STATUS_COMPLETED)
        self.assertEqual(self.manager.get_task("ct-other-1").status, STATUS_READY)
        self.assertEqual(self.manager.get_task("ct-other-2").status, STATUS_PENDING)

    def test_manager_state_remains_consistent(self):
        opp = "opp-ct-11"
        task = _make_task(
            task_id="ct-consistent",
            opportunity_id=opp,
            status=STATUS_IN_PROGRESS,
            name="Draft the store listing",
            description="Write the app store listing copy for the opportunity.",
            priority=PRIORITY_HIGH,
            dependencies=["dep-done"],
            metadata={"note": "keep me"},
        )
        self.manager.add_task(task)
        before_len = len(self.manager)

        result = self.manager.complete_task(
            "ct-consistent", output={"result": "ok"}, metadata={"extra": True}
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("ct-consistent")
        self.assertEqual(stored.status, STATUS_COMPLETED)
        # Nothing besides status changed on the task itself.
        self.assertEqual(stored.opportunity_id, opp)
        self.assertEqual(stored.name, "Draft the store listing")
        self.assertEqual(stored.priority, PRIORITY_HIGH)
        self.assertEqual(stored.dependencies, ["dep-done"])
        self.assertEqual(stored.metadata, {"note": "keep me"})
        self.assertEqual(task.status, STATUS_COMPLETED)


# ----------------------------------------------------------------------
# 22. fail_task()
# ----------------------------------------------------------------------
class TestFailTask(unittest.TestCase):
    def setUp(self):
        self.manager = RevenueTaskManager()

    def test_successful_in_progress_to_failed_transition(self):
        self.manager.add_task(
            _make_task(
                task_id="ft-in-progress",
                opportunity_id="opp-ft-1",
                status=STATUS_IN_PROGRESS,
            )
        )
        result = self.manager.fail_task("ft-in-progress")
        self.assertEqual(
            result,
            {
                "success": True,
                "task_id": "ft-in-progress",
                "opportunity_id": "opp-ft-1",
                "previous_status": STATUS_IN_PROGRESS,
                "status": STATUS_FAILED,
                "failed": True,
                "error": "No error detail provided.",
                "metadata": None,
            },
        )
        self.assertEqual(self.manager.get_task("ft-in-progress").status, STATUS_FAILED)

    def test_error_information_is_returned_but_not_stored_on_task(self):
        self.manager.add_task(
            _make_task(
                task_id="ft-error",
                opportunity_id="opp-ft-2",
                status=STATUS_IN_PROGRESS,
            )
        )
        error = {"type": "TimeoutError", "message": "Upstream call timed out"}
        result = self.manager.fail_task("ft-error", error=error)
        self.assertTrue(result["success"])
        self.assertEqual(result["error"], error)
        stored = self.manager.get_task("ft-error")
        self.assertNotIn("error", stored.__slots__)
        self.assertEqual(stored.status, STATUS_FAILED)

    def test_metadata_is_returned_but_not_merged_into_task_metadata(self):
        self.manager.add_task(
            _make_task(
                task_id="ft-metadata",
                opportunity_id="opp-ft-3",
                status=STATUS_IN_PROGRESS,
                metadata={"original": "value"},
            )
        )
        extra_metadata = {"attempt": 2, "retriable": False}
        result = self.manager.fail_task("ft-metadata", metadata=extra_metadata)
        self.assertTrue(result["success"])
        self.assertEqual(result["metadata"], extra_metadata)
        stored = self.manager.get_task("ft-metadata")
        self.assertEqual(stored.metadata, {"original": "value"})

    def test_none_error_uses_safe_placeholder(self):
        self.manager.add_task(
            _make_task(
                task_id="ft-none-error",
                opportunity_id="opp-ft-4",
                status=STATUS_IN_PROGRESS,
            )
        )
        result = self.manager.fail_task("ft-none-error", error=None)
        self.assertTrue(result["success"])
        self.assertEqual(result["error"], "No error detail provided.")

    def test_missing_task(self):
        result = self.manager.fail_task("ft-does-not-exist")
        self.assertEqual(
            result,
            {
                "success": False,
                "task_id": "ft-does-not-exist",
                "opportunity_id": None,
                "previous_status": None,
                "status": None,
                "failed": False,
                "error": "task_not_found",
            },
        )

    def test_pending_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="ft-pending", opportunity_id="opp-ft-5", status=STATUS_PENDING)
        )
        result = self.manager.fail_task("ft-pending")
        self.assertFalse(result["success"])
        self.assertFalse(result["failed"])
        self.assertEqual(result["previous_status"], STATUS_PENDING)
        self.assertEqual(result["status"], STATUS_PENDING)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ft-pending").status, STATUS_PENDING)

    def test_ready_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="ft-ready", opportunity_id="opp-ft-6", status=STATUS_READY)
        )
        result = self.manager.fail_task("ft-ready")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_READY)
        self.assertEqual(result["status"], STATUS_READY)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ft-ready").status, STATUS_READY)

    def test_blocked_task_is_rejected(self):
        self.manager.add_task(
            _make_task(task_id="ft-blocked", opportunity_id="opp-ft-7", status=STATUS_BLOCKED)
        )
        result = self.manager.fail_task("ft-blocked")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_BLOCKED)
        self.assertEqual(result["status"], STATUS_BLOCKED)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ft-blocked").status, STATUS_BLOCKED)

    def test_completed_task_is_rejected(self):
        self.manager.add_task(
            _make_task(
                task_id="ft-completed", opportunity_id="opp-ft-8", status=STATUS_COMPLETED
            )
        )
        result = self.manager.fail_task("ft-completed")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_COMPLETED)
        self.assertEqual(result["status"], STATUS_COMPLETED)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ft-completed").status, STATUS_COMPLETED)

    def test_cancelled_task_is_rejected(self):
        self.manager.add_task(
            _make_task(
                task_id="ft-cancelled", opportunity_id="opp-ft-9", status=STATUS_CANCELLED
            )
        )
        result = self.manager.fail_task("ft-cancelled")
        self.assertFalse(result["success"])
        self.assertEqual(result["previous_status"], STATUS_CANCELLED)
        self.assertEqual(result["status"], STATUS_CANCELLED)
        self.assertEqual(result["error"], "not_in_progress")
        self.assertEqual(self.manager.get_task("ft-cancelled").status, STATUS_CANCELLED)

    def test_invalid_transitions_are_rejected_for_every_non_in_progress_status(self):
        for status in (
            STATUS_PENDING, STATUS_READY, STATUS_BLOCKED,
            STATUS_COMPLETED, STATUS_CANCELLED,
        ):
            task_id = f"ft-invalid-{status.lower()}"
            self.manager.add_task(
                _make_task(task_id=task_id, opportunity_id="opp-ft-10", status=status)
            )
            result = self.manager.fail_task(task_id)
            self.assertFalse(result["success"])
            self.assertEqual(result["error"], "not_in_progress")
            self.assertEqual(self.manager.get_task(task_id).status, status)

    def test_other_tasks_remain_unchanged(self):
        opp = "opp-ft-11"
        self.manager.add_task(
            _make_task(task_id="ft-other-1", opportunity_id=opp, status=STATUS_READY)
        )
        self.manager.add_task(
            _make_task(task_id="ft-target", opportunity_id=opp, status=STATUS_IN_PROGRESS)
        )
        self.manager.add_task(
            _make_task(task_id="ft-other-2", opportunity_id=opp, status=STATUS_PENDING)
        )

        result = self.manager.fail_task("ft-target")

        self.assertTrue(result["success"])
        self.assertEqual(self.manager.get_task("ft-target").status, STATUS_FAILED)
        self.assertEqual(self.manager.get_task("ft-other-1").status, STATUS_READY)
        self.assertEqual(self.manager.get_task("ft-other-2").status, STATUS_PENDING)

    def test_manager_state_remains_consistent(self):
        opp = "opp-ft-12"
        task = _make_task(
            task_id="ft-consistent",
            opportunity_id=opp,
            status=STATUS_IN_PROGRESS,
            name="Draft the store listing",
            description="Write the app store listing copy for the opportunity.",
            priority=PRIORITY_HIGH,
            dependencies=["dep-done"],
            metadata={"note": "keep me"},
        )
        self.manager.add_task(task)
        before_len = len(self.manager)

        result = self.manager.fail_task(
            "ft-consistent",
            error={"type": "ValueError", "message": "bad input"},
            metadata={"extra": True},
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(self.manager), before_len)
        stored = self.manager.get_task("ft-consistent")
        self.assertEqual(stored.status, STATUS_FAILED)
        # Nothing besides status changed on the task itself.
        self.assertEqual(stored.opportunity_id, opp)
        self.assertEqual(stored.name, "Draft the store listing")
        self.assertEqual(stored.priority, PRIORITY_HIGH)
        self.assertEqual(stored.dependencies, ["dep-done"])
        self.assertEqual(stored.metadata, {"note": "keep me"})
        self.assertEqual(task.status, STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
