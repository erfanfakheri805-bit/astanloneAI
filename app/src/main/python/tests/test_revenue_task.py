"""
Tests for the RevenueTask model (financial/revenue_task.py).

Covers: creating a valid task, validation failures (including invalid
status), and to_dict(). This stage is standalone - it is not wired
into RevenueOpportunityManager, a planner, or any other system yet.

Run directly:
    python -m unittest tests.test_revenue_task -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

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
    ALL_STATUSES,
    PRIORITY_LOW,
    PRIORITY_NORMAL,
    PRIORITY_HIGH,
    PRIORITY_CRITICAL,
    ALL_PRIORITIES,
    DEFAULT_ESTIMATED_DURATION,
)

# STATUS_* and ALL_STATUSES above already cover every status this
# file's tests need (including is_valid_transition() coverage).


def _make_task(**overrides):
    fields = dict(
        task_id="task-test-1",
        opportunity_id="opp-test-1",
        name="Draft the store listing",
        description="Write the app store listing copy for the opportunity.",
    )
    fields.update(overrides)
    return RevenueTask(**fields)


# ----------------------------------------------------------------------
# 1. Valid task
# ----------------------------------------------------------------------
class TestValidTask(unittest.TestCase):
    def test_valid_task_has_expected_fields_and_is_valid(self):
        task = _make_task()

        self.assertEqual(task.task_id, "task-test-1")
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.name, "Draft the store listing")
        self.assertEqual(
            task.description, "Write the app store listing copy for the opportunity."
        )
        self.assertEqual(task.status, STATUS_PENDING)
        self.assertTrue(task.created_at)
        self.assertEqual(task.metadata, {})
        self.assertTrue(task.is_valid())

    def test_all_supported_statuses_are_valid(self):
        for status in (
            STATUS_PENDING, STATUS_READY, STATUS_IN_PROGRESS, STATUS_COMPLETED,
            STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED,
        ):
            self.assertTrue(_make_task(status=status).is_valid())
            self.assertIn(status, ALL_STATUSES)

    def test_description_and_metadata_are_optional(self):
        task = RevenueTask(
            task_id="task-min", opportunity_id="opp-min", name="Minimal task"
        )
        self.assertTrue(task.is_valid())
        self.assertIsNone(task.description)
        self.assertEqual(task.metadata, {})

    def test_metadata_is_copied_not_aliased(self):
        source = {"note": "priority"}
        task = _make_task(metadata=source)
        task.metadata["note"] = "changed"
        self.assertEqual(source["note"], "priority")


# ----------------------------------------------------------------------
# 2. Invalid task (general field validation)
# ----------------------------------------------------------------------
class TestInvalidTask(unittest.TestCase):
    def test_empty_task_id_is_invalid(self):
        self.assertFalse(_make_task(task_id="").is_valid())

    def test_non_string_task_id_is_invalid(self):
        self.assertFalse(_make_task(task_id=123).is_valid())
        self.assertFalse(_make_task(task_id=None).is_valid())

    def test_empty_opportunity_id_is_invalid(self):
        self.assertFalse(_make_task(opportunity_id="").is_valid())

    def test_non_string_opportunity_id_is_invalid(self):
        self.assertFalse(_make_task(opportunity_id=42).is_valid())
        self.assertFalse(_make_task(opportunity_id=None).is_valid())

    def test_empty_name_is_invalid(self):
        self.assertFalse(_make_task(name="").is_valid())

    def test_whitespace_only_name_is_invalid(self):
        self.assertFalse(_make_task(name="   ").is_valid())

    def test_non_string_name_is_invalid(self):
        self.assertFalse(_make_task(name=None).is_valid())

    def test_unsafe_metadata_is_invalid(self):
        self.assertFalse(_make_task(metadata={"callback": lambda: None}).is_valid())

    def test_unsafe_metadata_object_is_invalid(self):
        class Unsafe:
            pass

        self.assertFalse(_make_task(metadata={"thing": Unsafe()}).is_valid())


# ----------------------------------------------------------------------
# 3. Invalid status
# ----------------------------------------------------------------------
class TestInvalidStatus(unittest.TestCase):
    def test_unsupported_status_string_is_invalid(self):
        self.assertFalse(_make_task(status="LAUNCHED").is_valid())

    def test_none_status_is_invalid(self):
        self.assertFalse(_make_task(status=None).is_valid())

    def test_lowercase_status_is_invalid(self):
        # Statuses are a closed, case-sensitive vocabulary.
        self.assertFalse(_make_task(status="pending").is_valid())


# ----------------------------------------------------------------------
# 4. to_dict()
# ----------------------------------------------------------------------
class TestToDict(unittest.TestCase):
    def test_to_dict_returns_expected_shape(self):
        task = _make_task(status=STATUS_READY, metadata={"priority": "high"})
        data = task.to_dict()

        self.assertEqual(
            data,
            {
                "task_id": "task-test-1",
                "opportunity_id": "opp-test-1",
                "name": "Draft the store listing",
                "description": "Write the app store listing copy for the opportunity.",
                "status": STATUS_READY,
                "priority": PRIORITY_NORMAL,
                "estimated_duration": DEFAULT_ESTIMATED_DURATION,
                "dependencies": [],
                "created_at": task.created_at,
                "metadata": {"priority": "high"},
                "result": None,
            },
        )

    def test_to_dict_metadata_is_a_copy(self):
        task = _make_task(metadata={"priority": "high"})
        data = task.to_dict()
        data["metadata"]["priority"] = "changed"
        self.assertEqual(task.metadata["priority"], "high")


# ----------------------------------------------------------------------
# 5. Priority
# ----------------------------------------------------------------------
class TestPriority(unittest.TestCase):
    def test_default_priority_is_normal(self):
        task = _make_task()
        self.assertEqual(task.priority, PRIORITY_NORMAL)
        self.assertTrue(task.is_valid())

    def test_all_supported_priorities_are_accepted(self):
        for priority in (PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_CRITICAL):
            self.assertTrue(_make_task(priority=priority).is_valid())
            self.assertIn(priority, ALL_PRIORITIES)

    def test_invalid_priority_is_rejected(self):
        self.assertFalse(_make_task(priority="URGENT").is_valid())
        self.assertFalse(_make_task(priority=None).is_valid())
        self.assertFalse(_make_task(priority="normal").is_valid())

    def test_priority_appears_in_to_dict(self):
        task = _make_task(priority=PRIORITY_HIGH)
        self.assertEqual(task.to_dict()["priority"], PRIORITY_HIGH)


# ----------------------------------------------------------------------
# 6. Estimated duration
# ----------------------------------------------------------------------
class TestEstimatedDuration(unittest.TestCase):
    def test_default_duration_is_zero(self):
        task = _make_task()
        self.assertEqual(task.estimated_duration, DEFAULT_ESTIMATED_DURATION)
        self.assertTrue(task.is_valid())

    def test_valid_duration_is_accepted(self):
        self.assertTrue(_make_task(estimated_duration=45).is_valid())
        self.assertTrue(_make_task(estimated_duration=12.5).is_valid())

    def test_zero_is_accepted(self):
        self.assertTrue(_make_task(estimated_duration=0).is_valid())

    def test_negative_duration_is_rejected(self):
        self.assertFalse(_make_task(estimated_duration=-1).is_valid())

    def test_non_numeric_duration_is_rejected(self):
        self.assertFalse(_make_task(estimated_duration="45").is_valid())
        self.assertFalse(_make_task(estimated_duration=None).is_valid())

    def test_boolean_duration_is_rejected(self):
        self.assertFalse(_make_task(estimated_duration=True).is_valid())

    def test_duration_appears_in_to_dict(self):
        task = _make_task(estimated_duration=30)
        self.assertEqual(task.to_dict()["estimated_duration"], 30)


# ----------------------------------------------------------------------
# 7. Dependencies
# ----------------------------------------------------------------------
class TestDependencies(unittest.TestCase):
    def test_default_dependencies_are_empty(self):
        task = _make_task()
        self.assertEqual(task.dependencies, [])
        self.assertTrue(task.is_valid())

    def test_default_dependencies_are_not_shared_between_instances(self):
        first = _make_task(task_id="task-first")
        second = _make_task(task_id="task-second")
        first.dependencies.append("task-other")
        self.assertEqual(second.dependencies, [])

    def test_valid_dependency_ids_are_accepted(self):
        task = _make_task(dependencies=["task-a", "task-b"])
        self.assertTrue(task.is_valid())
        self.assertEqual(task.dependencies, ["task-a", "task-b"])

    def test_dependencies_appear_in_to_dict(self):
        task = _make_task(dependencies=["task-a", "task-b"])
        self.assertEqual(task.to_dict()["dependencies"], ["task-a", "task-b"])

    def test_get_dependencies_returns_a_safe_copy(self):
        task = _make_task(dependencies=["task-a"])
        fetched = task.get_dependencies()
        fetched.append("task-b")
        self.assertEqual(task.dependencies, ["task-a"])

    def test_non_list_dependencies_are_rejected(self):
        self.assertFalse(_make_task(dependencies="task-a").is_valid())
        self.assertFalse(_make_task(dependencies={"task-a": True}).is_valid())

    def test_non_string_dependency_entries_are_rejected(self):
        self.assertFalse(_make_task(dependencies=["task-a", 123]).is_valid())
        self.assertFalse(_make_task(dependencies=[None]).is_valid())

    def test_empty_string_dependency_entry_is_rejected(self):
        self.assertFalse(_make_task(dependencies=["task-a", ""]).is_valid())


# ----------------------------------------------------------------------
# 8. has_dependencies()
# ----------------------------------------------------------------------
class TestHasDependencies(unittest.TestCase):
    def test_no_dependencies_returns_false(self):
        task = _make_task()
        self.assertFalse(task.has_dependencies())

    def test_one_dependency_returns_true(self):
        task = _make_task(dependencies=["task-a"])
        self.assertTrue(task.has_dependencies())

    def test_multiple_dependencies_returns_true(self):
        task = _make_task(dependencies=["task-a", "task-b", "task-c"])
        self.assertTrue(task.has_dependencies())


# ----------------------------------------------------------------------
# 9. is_completed() / is_failed()
# ----------------------------------------------------------------------
class TestStatusChecks(unittest.TestCase):
    def test_completed_task_is_completed_true(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertTrue(task.is_completed())

    def test_non_completed_task_is_completed_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_completed())

    def test_failed_task_is_failed_true(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertTrue(task.is_failed())

    def test_non_failed_task_is_failed_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_failed())


# ----------------------------------------------------------------------
# 10. is_ready()
# ----------------------------------------------------------------------
class TestIsReady(unittest.TestCase):
    def test_ready_task_is_ready_true(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.is_ready())

    def test_pending_task_is_ready_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_ready())

    def test_in_progress_task_is_ready_false(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertFalse(task.is_ready())

    def test_completed_task_is_ready_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.is_ready())

    def test_failed_task_is_ready_false(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertFalse(task.is_ready())


# ----------------------------------------------------------------------
# 11. is_cancelled()
# ----------------------------------------------------------------------
class TestIsCancelled(unittest.TestCase):
    def test_cancelled_task_is_cancelled_true(self):
        task = _make_task(status=STATUS_CANCELLED)
        self.assertTrue(task.is_cancelled())

    def test_pending_task_is_cancelled_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_cancelled())

    def test_ready_task_is_cancelled_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.is_cancelled())

    def test_completed_task_is_cancelled_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.is_cancelled())


# ----------------------------------------------------------------------
# 12. is_in_progress()
# ----------------------------------------------------------------------
class TestIsInProgress(unittest.TestCase):
    def test_in_progress_task_is_in_progress_true(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertTrue(task.is_in_progress())

    def test_pending_task_is_in_progress_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_in_progress())

    def test_ready_task_is_in_progress_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.is_in_progress())

    def test_completed_task_is_in_progress_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.is_in_progress())

    def test_failed_task_is_in_progress_false(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertFalse(task.is_in_progress())


# ----------------------------------------------------------------------
# 13. is_pending()
# ----------------------------------------------------------------------
class TestIsPending(unittest.TestCase):
    def test_pending_task_is_pending_true(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.is_pending())

    def test_ready_task_is_pending_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.is_pending())

    def test_in_progress_task_is_pending_false(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertFalse(task.is_pending())

    def test_completed_task_is_pending_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.is_pending())

    def test_failed_task_is_pending_false(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertFalse(task.is_pending())


# ----------------------------------------------------------------------
# 14. is_blocked()
# ----------------------------------------------------------------------
class TestIsBlocked(unittest.TestCase):
    def test_blocked_task_is_blocked_true(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertTrue(task.is_blocked())

    def test_pending_task_is_blocked_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_blocked())

    def test_ready_task_is_blocked_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.is_blocked())

    def test_in_progress_task_is_blocked_false(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertFalse(task.is_blocked())

    def test_completed_task_is_blocked_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.is_blocked())


# ----------------------------------------------------------------------
# 15. is_active()
# ----------------------------------------------------------------------
class TestIsActive(unittest.TestCase):
    def test_ready_task_is_active_true(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.is_active())

    def test_in_progress_task_is_active_true(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertTrue(task.is_active())

    def test_pending_task_is_active_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_active())

    def test_blocked_task_is_active_false(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertFalse(task.is_active())

    def test_completed_task_is_active_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.is_active())

    def test_failed_task_is_active_false(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertFalse(task.is_active())

    def test_cancelled_task_is_active_false(self):
        task = _make_task(status=STATUS_CANCELLED)
        self.assertFalse(task.is_active())


# ----------------------------------------------------------------------
# 16. is_final()
# ----------------------------------------------------------------------
class TestIsFinal(unittest.TestCase):
    def test_completed_task_is_final_true(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertTrue(task.is_final())

    def test_failed_task_is_final_true(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertTrue(task.is_final())

    def test_cancelled_task_is_final_true(self):
        task = _make_task(status=STATUS_CANCELLED)
        self.assertTrue(task.is_final())

    def test_pending_task_is_final_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_final())

    def test_ready_task_is_final_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.is_final())

    def test_in_progress_task_is_final_false(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertFalse(task.is_final())

    def test_blocked_task_is_final_false(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertFalse(task.is_final())


# ----------------------------------------------------------------------
# 17. get_status()
# ----------------------------------------------------------------------
class TestGetStatus(unittest.TestCase):
    def test_ready_returns_ready(self):
        task = _make_task(status=STATUS_READY)
        self.assertEqual(task.get_status(), "READY")

    def test_pending_returns_pending(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertEqual(task.get_status(), "PENDING")

    def test_completed_returns_completed(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertEqual(task.get_status(), "COMPLETED")

    def test_failed_returns_failed(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertEqual(task.get_status(), "FAILED")


# ----------------------------------------------------------------------
# 18. belongs_to_opportunity()
# ----------------------------------------------------------------------
class TestBelongsToOpportunity(unittest.TestCase):
    def test_matching_opportunity_id_returns_true(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertTrue(task.belongs_to_opportunity("opp-test-1"))

    def test_different_opportunity_id_returns_false(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertFalse(task.belongs_to_opportunity("opp-other"))

    def test_empty_opportunity_id_is_invalid(self):
        self.assertFalse(_make_task(opportunity_id="").is_valid())

    def test_existing_behavior_still_works(self):
        task = _make_task()
        self.assertTrue(task.is_valid())
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertIn("opportunity_id", task.to_dict())


# ----------------------------------------------------------------------
# 19. get_opportunity_id()
# ----------------------------------------------------------------------
class TestGetOpportunityId(unittest.TestCase):
    def test_returns_the_correct_opportunity_id(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertEqual(task.get_opportunity_id(), "opp-test-1")

    def test_works_with_a_normal_valid_opportunity_id(self):
        task = _make_task(opportunity_id="opp-mobile-game-42")
        self.assertEqual(task.get_opportunity_id(), "opp-mobile-game-42")
        self.assertTrue(task.is_valid())

    def test_does_not_modify_the_stored_value(self):
        task = _make_task(opportunity_id="opp-test-1")
        task.get_opportunity_id()
        self.assertEqual(task.opportunity_id, "opp-test-1")

    def test_existing_behavior_still_works(self):
        task = _make_task()
        self.assertTrue(task.is_valid())
        self.assertEqual(task.to_dict()["opportunity_id"], task.get_opportunity_id())


# ----------------------------------------------------------------------
# 20. has_opportunity()
# ----------------------------------------------------------------------
class TestHasOpportunity(unittest.TestCase):
    def test_valid_opportunity_id_returns_true(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertTrue(task.has_opportunity())

    def test_empty_opportunity_id_returns_false(self):
        task = _make_task(opportunity_id="")
        self.assertFalse(task.has_opportunity())
        self.assertFalse(task.is_valid())

    def test_existing_behavior_remains_unchanged(self):
        task = _make_task()
        self.assertTrue(task.is_valid())
        self.assertEqual(task.status, STATUS_PENDING)
        self.assertEqual(task.priority, PRIORITY_NORMAL)

    def test_get_opportunity_id_still_works(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertEqual(task.get_opportunity_id(), "opp-test-1")

    def test_belongs_to_opportunity_still_works(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertTrue(task.belongs_to_opportunity("opp-test-1"))
        self.assertFalse(task.belongs_to_opportunity("opp-other"))


# ----------------------------------------------------------------------
# 21. is_open()
# ----------------------------------------------------------------------
class TestIsOpen(unittest.TestCase):
    def test_pending_is_open_true(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.is_open())

    def test_ready_is_open_true(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.is_open())

    def test_in_progress_is_open_true(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertTrue(task.is_open())

    def test_blocked_is_open_true(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertTrue(task.is_open())

    def test_completed_is_open_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.is_open())

    def test_failed_is_open_false(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertFalse(task.is_open())

    def test_cancelled_is_open_false(self):
        task = _make_task(status=STATUS_CANCELLED)
        self.assertFalse(task.is_open())

    def test_existing_is_final_behavior_unchanged(self):
        self.assertTrue(_make_task(status=STATUS_COMPLETED).is_final())
        self.assertTrue(_make_task(status=STATUS_FAILED).is_final())
        self.assertTrue(_make_task(status=STATUS_CANCELLED).is_final())
        self.assertFalse(_make_task(status=STATUS_PENDING).is_final())
        self.assertFalse(_make_task(status=STATUS_READY).is_final())
        self.assertFalse(_make_task(status=STATUS_IN_PROGRESS).is_final())
        self.assertFalse(_make_task(status=STATUS_BLOCKED).is_final())


# ----------------------------------------------------------------------
# 22. can_start()
# ----------------------------------------------------------------------
class TestCanStart(unittest.TestCase):
    def test_ready_can_start_true(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.can_start())

    def test_pending_can_start_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.can_start())

    def test_in_progress_can_start_false(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertFalse(task.can_start())

    def test_blocked_can_start_false(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertFalse(task.can_start())

    def test_completed_can_start_false(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertFalse(task.can_start())

    def test_failed_can_start_false(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertFalse(task.can_start())

    def test_cancelled_can_start_false(self):
        task = _make_task(status=STATUS_CANCELLED)
        self.assertFalse(task.can_start())

    def test_existing_is_ready_and_is_open_behavior_unchanged(self):
        self.assertTrue(_make_task(status=STATUS_READY).is_ready())
        self.assertFalse(_make_task(status=STATUS_PENDING).is_ready())

        self.assertTrue(_make_task(status=STATUS_READY).is_open())
        self.assertTrue(_make_task(status=STATUS_PENDING).is_open())
        self.assertTrue(_make_task(status=STATUS_IN_PROGRESS).is_open())
        self.assertTrue(_make_task(status=STATUS_BLOCKED).is_open())
        self.assertFalse(_make_task(status=STATUS_COMPLETED).is_open())
        self.assertFalse(_make_task(status=STATUS_FAILED).is_open())
        self.assertFalse(_make_task(status=STATUS_CANCELLED).is_open())


# ----------------------------------------------------------------------
# 23. is_startable()
# ----------------------------------------------------------------------
class TestIsStartable(unittest.TestCase):
    def test_ready_with_valid_opportunity_id_returns_true(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        self.assertTrue(task.is_startable())

    def test_ready_with_empty_opportunity_id_returns_false(self):
        task = _make_task(status=STATUS_READY, opportunity_id="")
        self.assertFalse(task.is_startable())

    def test_pending_with_valid_opportunity_id_returns_false(self):
        task = _make_task(status=STATUS_PENDING, opportunity_id="opp-test-1")
        self.assertFalse(task.is_startable())

    def test_in_progress_with_valid_opportunity_id_returns_false(self):
        task = _make_task(status=STATUS_IN_PROGRESS, opportunity_id="opp-test-1")
        self.assertFalse(task.is_startable())

    def test_blocked_with_valid_opportunity_id_returns_false(self):
        task = _make_task(status=STATUS_BLOCKED, opportunity_id="opp-test-1")
        self.assertFalse(task.is_startable())

    def test_completed_with_valid_opportunity_id_returns_false(self):
        task = _make_task(status=STATUS_COMPLETED, opportunity_id="opp-test-1")
        self.assertFalse(task.is_startable())

    def test_failed_with_valid_opportunity_id_returns_false(self):
        task = _make_task(status=STATUS_FAILED, opportunity_id="opp-test-1")
        self.assertFalse(task.is_startable())

    def test_cancelled_with_valid_opportunity_id_returns_false(self):
        task = _make_task(status=STATUS_CANCELLED, opportunity_id="opp-test-1")
        self.assertFalse(task.is_startable())

    def test_can_start_still_works(self):
        self.assertTrue(_make_task(status=STATUS_READY).can_start())
        self.assertFalse(_make_task(status=STATUS_PENDING).can_start())

    def test_has_opportunity_still_works(self):
        self.assertTrue(_make_task(opportunity_id="opp-test-1").has_opportunity())
        self.assertFalse(_make_task(opportunity_id="").has_opportunity())

    def test_is_open_still_works(self):
        self.assertTrue(_make_task(status=STATUS_READY).is_open())
        self.assertFalse(_make_task(status=STATUS_COMPLETED).is_open())

    def test_is_final_still_works(self):
        self.assertTrue(_make_task(status=STATUS_CANCELLED).is_final())
        self.assertFalse(_make_task(status=STATUS_READY).is_final())


# ----------------------------------------------------------------------
# 24. get_startability_status()
# ----------------------------------------------------------------------
class TestGetStartabilityStatus(unittest.TestCase):
    def test_ready_task_with_valid_opportunity_id(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        self.assertEqual(
            task.get_startability_status(),
            {"startable": True, "ready": True, "has_opportunity": True},
        )

    def test_ready_task_without_opportunity_id(self):
        task = _make_task(status=STATUS_READY, opportunity_id="")
        self.assertEqual(
            task.get_startability_status(),
            {"startable": False, "ready": True, "has_opportunity": False},
        )

    def test_pending_task_with_valid_opportunity_id(self):
        task = _make_task(status=STATUS_PENDING, opportunity_id="opp-test-1")
        self.assertEqual(
            task.get_startability_status(),
            {"startable": False, "ready": False, "has_opportunity": True},
        )

    def test_completed_task_with_valid_opportunity_id(self):
        task = _make_task(status=STATUS_COMPLETED, opportunity_id="opp-test-1")
        self.assertEqual(
            task.get_startability_status(),
            {"startable": False, "ready": False, "has_opportunity": True},
        )

    def test_all_returned_values_are_booleans(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        status = task.get_startability_status()
        for key in ("startable", "ready", "has_opportunity"):
            self.assertIsInstance(status[key], bool)

    def test_existing_methods_still_work(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        self.assertTrue(task.has_opportunity())
        self.assertTrue(task.can_start())
        self.assertTrue(task.is_startable())
        self.assertTrue(task.is_ready())
        self.assertTrue(task.is_open())


# ----------------------------------------------------------------------
# 25. get_status_summary()
# ----------------------------------------------------------------------
class TestGetStatusSummary(unittest.TestCase):
    def test_returns_correct_task_id(self):
        task = _make_task(task_id="task-summary-1")
        self.assertEqual(task.get_status_summary()["task_id"], "task-summary-1")

    def test_returns_correct_opportunity_id(self):
        task = _make_task(opportunity_id="opp-summary-1")
        self.assertEqual(
            task.get_status_summary()["opportunity_id"], "opp-summary-1"
        )

    def test_returns_correct_status(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertEqual(task.get_status_summary()["status"], STATUS_IN_PROGRESS)

    def test_returns_correct_priority(self):
        task = _make_task(priority=PRIORITY_HIGH)
        self.assertEqual(task.get_status_summary()["priority"], PRIORITY_HIGH)

    def test_returns_correct_startable_value_true(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        self.assertTrue(task.get_status_summary()["startable"])
        self.assertEqual(
            task.get_status_summary()["startable"], task.is_startable()
        )

    def test_returns_correct_startable_value_false(self):
        task = _make_task(status=STATUS_PENDING, opportunity_id="opp-test-1")
        self.assertFalse(task.get_status_summary()["startable"])
        self.assertEqual(
            task.get_status_summary()["startable"], task.is_startable()
        )

    def test_returns_correct_final_value_true(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertTrue(task.get_status_summary()["final"])
        self.assertEqual(task.get_status_summary()["final"], task.is_final())

    def test_returns_correct_final_value_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.get_status_summary()["final"])
        self.assertEqual(task.get_status_summary()["final"], task.is_final())

    def test_returns_a_dictionary(self):
        task = _make_task()
        self.assertIsInstance(task.get_status_summary(), dict)

    def test_returns_expected_shape(self):
        task = _make_task(
            task_id="task-summary-2",
            opportunity_id="opp-summary-2",
            status=STATUS_READY,
            priority=PRIORITY_CRITICAL,
        )
        self.assertEqual(
            task.get_status_summary(),
            {
                "task_id": "task-summary-2",
                "opportunity_id": "opp-summary-2",
                "status": STATUS_READY,
                "priority": PRIORITY_CRITICAL,
                "startable": task.is_startable(),
                "final": task.is_final(),
            },
        )

    def test_does_not_modify_status_or_task(self):
        task = _make_task(status=STATUS_PENDING, priority=PRIORITY_LOW)
        task.get_status_summary()
        self.assertEqual(task.status, STATUS_PENDING)
        self.assertEqual(task.priority, PRIORITY_LOW)

    def test_existing_methods_still_work(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        self.assertTrue(task.is_valid())
        self.assertTrue(task.has_opportunity())
        self.assertTrue(task.can_start())
        self.assertTrue(task.is_startable())
        self.assertTrue(task.is_ready())
        self.assertTrue(task.is_open())
        self.assertFalse(task.is_final())
        self.assertEqual(task.get_opportunity_id(), "opp-test-1")
        self.assertEqual(
            task.get_startability_status(),
            {"startable": True, "ready": True, "has_opportunity": True},
        )
        self.assertIsInstance(task.to_dict(), dict)


# ----------------------------------------------------------------------
# 26. set_status()
# ----------------------------------------------------------------------
class TestSetStatus(unittest.TestCase):
    def test_setting_a_valid_status_returns_true(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.set_status(STATUS_READY))

    def test_setting_a_valid_status_updates_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.set_status(STATUS_READY)
        self.assertEqual(task.status, STATUS_READY)

    def test_setting_each_valid_status_works(self):
        for status in ALL_STATUSES:
            task = _make_task(status=STATUS_PENDING)
            self.assertTrue(task.set_status(status))
            self.assertEqual(task.status, status)

    def test_setting_an_invalid_status_returns_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.set_status("LAUNCHED"))

    def test_setting_an_invalid_status_does_not_change_status(self):
        task = _make_task(status=STATUS_READY)
        task.set_status("LAUNCHED")
        self.assertEqual(task.status, STATUS_READY)

    def test_setting_none_status_returns_false_and_does_not_change_status(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.set_status(None))
        self.assertEqual(task.status, STATUS_READY)

    def test_setting_lowercase_status_returns_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.set_status("ready"))
        self.assertEqual(task.status, STATUS_READY)

    def test_set_status_does_not_change_other_fields(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            opportunity_id="opp-test-1",
            dependencies=["task-a"],
        )
        task.set_status(STATUS_COMPLETED)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.dependencies, ["task-a"])

    def test_status_helpers_still_work_after_changing_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.set_status(STATUS_COMPLETED)
        self.assertTrue(task.is_completed())
        self.assertTrue(task.is_final())
        self.assertFalse(task.is_open())
        self.assertFalse(task.is_pending())
        self.assertFalse(task.is_ready())

        task.set_status(STATUS_READY)
        self.assertTrue(task.is_ready())
        self.assertTrue(task.can_start())
        self.assertTrue(task.is_active())
        self.assertTrue(task.is_open())
        self.assertFalse(task.is_final())

    def test_get_status_reflects_change_after_set_status(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertEqual(task.get_status(), STATUS_PENDING)
        task.set_status(STATUS_IN_PROGRESS)
        self.assertEqual(task.get_status(), STATUS_IN_PROGRESS)

    def test_get_status_unchanged_after_failed_set_status(self):
        task = _make_task(status=STATUS_BLOCKED)
        task.set_status("NOT_A_STATUS")
        self.assertEqual(task.get_status(), STATUS_BLOCKED)


# ----------------------------------------------------------------------
# 27. change_status()
# ----------------------------------------------------------------------
class TestChangeStatus(unittest.TestCase):
    def test_correct_old_status_and_valid_new_status_returns_true(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.change_status(STATUS_PENDING, STATUS_READY))

    def test_correct_old_status_and_valid_new_status_updates_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.change_status(STATUS_PENDING, STATUS_READY)
        self.assertEqual(task.status, STATUS_READY)

    def test_incorrect_old_status_returns_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.change_status(STATUS_READY, STATUS_IN_PROGRESS))

    def test_incorrect_old_status_does_not_change_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.change_status(STATUS_READY, STATUS_IN_PROGRESS)
        self.assertEqual(task.status, STATUS_PENDING)

    def test_invalid_new_status_returns_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.change_status(STATUS_PENDING, "LAUNCHED"))

    def test_invalid_new_status_does_not_change_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.change_status(STATUS_PENDING, "LAUNCHED")
        self.assertEqual(task.status, STATUS_PENDING)

    def test_same_old_and_new_status_returns_true_and_stays_consistent(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.change_status(STATUS_READY, STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertTrue(task.is_valid())

    def test_change_status_does_not_modify_other_fields(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            opportunity_id="opp-test-1",
            dependencies=["task-a"],
        )
        task.change_status(STATUS_PENDING, STATUS_COMPLETED)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.dependencies, ["task-a"])

    def test_set_status_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.set_status(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertFalse(task.set_status("NOT_A_STATUS"))
        self.assertEqual(task.status, STATUS_READY)

    def test_get_status_still_works_after_change_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.change_status(STATUS_PENDING, STATUS_IN_PROGRESS)
        self.assertEqual(task.get_status(), STATUS_IN_PROGRESS)

    def test_status_helper_methods_still_work_after_change_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.change_status(STATUS_PENDING, STATUS_READY)
        self.assertTrue(task.is_ready())
        self.assertFalse(task.is_completed())

        task.change_status(STATUS_READY, STATUS_IN_PROGRESS)
        self.assertTrue(task.is_in_progress())
        self.assertFalse(task.is_ready())

        task.change_status(STATUS_IN_PROGRESS, STATUS_COMPLETED)
        self.assertTrue(task.is_completed())
        self.assertTrue(task.is_final())
        self.assertFalse(task.is_failed())
        self.assertFalse(task.is_cancelled())


# ----------------------------------------------------------------------
# 28. can_change_status()
# ----------------------------------------------------------------------
class TestCanChangeStatus(unittest.TestCase):
    def test_every_valid_status_returns_true(self):
        task = _make_task(status=STATUS_PENDING)
        for status in ALL_STATUSES:
            self.assertTrue(task.can_change_status(status))

    def test_invalid_status_returns_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.can_change_status("LAUNCHED"))
        self.assertFalse(task.can_change_status(None))
        self.assertFalse(task.can_change_status("pending"))

    def test_status_unchanged_after_true_result(self):
        task = _make_task(status=STATUS_PENDING)
        task.can_change_status(STATUS_COMPLETED)
        self.assertEqual(task.status, STATUS_PENDING)

    def test_status_unchanged_after_false_result(self):
        task = _make_task(status=STATUS_PENDING)
        task.can_change_status("LAUNCHED")
        self.assertEqual(task.status, STATUS_PENDING)

    def test_status_unchanged_after_repeated_calls(self):
        task = _make_task(status=STATUS_READY)
        for status in ALL_STATUSES:
            task.can_change_status(status)
        self.assertEqual(task.status, STATUS_READY)

    def test_does_not_modify_other_fields(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            opportunity_id="opp-test-1",
            dependencies=["task-a"],
        )
        task.can_change_status(STATUS_COMPLETED)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.dependencies, ["task-a"])

    def test_set_status_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.set_status(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertFalse(task.set_status("NOT_A_STATUS"))
        self.assertEqual(task.status, STATUS_READY)

    def test_change_status_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.change_status(STATUS_PENDING, STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertFalse(task.change_status(STATUS_PENDING, STATUS_COMPLETED))
        self.assertEqual(task.status, STATUS_READY)

    def test_status_helper_methods_still_work(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.can_change_status(STATUS_COMPLETED))
        self.assertTrue(task.is_ready())
        self.assertTrue(task.can_start())
        self.assertFalse(task.is_final())

        task.set_status(STATUS_COMPLETED)
        self.assertTrue(task.is_completed())
        self.assertTrue(task.is_final())
        self.assertFalse(task.is_failed())
        self.assertFalse(task.is_cancelled())
        self.assertEqual(task.get_status(), STATUS_COMPLETED)


# ----------------------------------------------------------------------
# 29. is_valid_transition()
# ----------------------------------------------------------------------
class TestIsValidTransition(unittest.TestCase):
    ALLOWED = (
        (STATUS_PENDING, STATUS_READY),
        (STATUS_PENDING, STATUS_BLOCKED),
        (STATUS_PENDING, STATUS_CANCELLED),
        (STATUS_READY, STATUS_IN_PROGRESS),
        (STATUS_READY, STATUS_BLOCKED),
        (STATUS_READY, STATUS_CANCELLED),
        (STATUS_IN_PROGRESS, STATUS_COMPLETED),
        (STATUS_IN_PROGRESS, STATUS_FAILED),
        (STATUS_IN_PROGRESS, STATUS_CANCELLED),
        (STATUS_BLOCKED, STATUS_READY),
        (STATUS_BLOCKED, STATUS_CANCELLED),
    )

    def test_every_allowed_transition_returns_true(self):
        for from_status, to_status in self.ALLOWED:
            task = _make_task(status=from_status)
            self.assertTrue(
                task.is_valid_transition(to_status),
                f"{from_status} -> {to_status} should be valid",
            )

    def test_several_invalid_transitions_return_false(self):
        invalid_pairs = (
            (STATUS_PENDING, STATUS_IN_PROGRESS),
            (STATUS_PENDING, STATUS_COMPLETED),
            (STATUS_READY, STATUS_COMPLETED),
            (STATUS_READY, STATUS_FAILED),
            (STATUS_COMPLETED, STATUS_READY),
            (STATUS_FAILED, STATUS_READY),
            (STATUS_CANCELLED, STATUS_READY),
            (STATUS_BLOCKED, STATUS_IN_PROGRESS),
            (STATUS_IN_PROGRESS, STATUS_READY),
        )
        for from_status, to_status in invalid_pairs:
            task = _make_task(status=from_status)
            self.assertFalse(
                task.is_valid_transition(to_status),
                f"{from_status} -> {to_status} should be invalid",
            )

    def test_invalid_status_returns_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.is_valid_transition("LAUNCHED"))
        self.assertFalse(task.is_valid_transition(None))

    def test_same_status_transition_returns_false(self):
        for status in ALL_STATUSES:
            task = _make_task(status=status)
            self.assertFalse(task.is_valid_transition(status))

    def test_calling_it_never_changes_current_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.is_valid_transition(STATUS_READY)
        self.assertEqual(task.status, STATUS_PENDING)
        task.is_valid_transition("LAUNCHED")
        self.assertEqual(task.status, STATUS_PENDING)
        task.is_valid_transition(STATUS_COMPLETED)
        self.assertEqual(task.status, STATUS_PENDING)

    def test_status_helper_methods_still_work(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.is_valid_transition(STATUS_IN_PROGRESS))
        self.assertTrue(task.is_ready())
        self.assertTrue(task.can_start())
        self.assertFalse(task.is_final())

        task.set_status(STATUS_IN_PROGRESS)
        self.assertTrue(task.is_in_progress())
        self.assertFalse(task.is_ready())
        self.assertTrue(task.is_valid_transition(STATUS_COMPLETED))

    def test_set_status_behavior_unchanged(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.set_status(STATUS_COMPLETED))
        self.assertEqual(task.status, STATUS_COMPLETED)
        self.assertFalse(task.set_status("NOT_A_STATUS"))
        self.assertEqual(task.status, STATUS_COMPLETED)

    def test_change_status_behavior_unchanged(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.change_status(STATUS_PENDING, STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertFalse(task.change_status(STATUS_PENDING, STATUS_COMPLETED))
        self.assertEqual(task.status, STATUS_READY)

    def test_can_change_status_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.can_change_status(STATUS_COMPLETED))
        self.assertFalse(task.can_change_status("LAUNCHED"))


# ----------------------------------------------------------------------
# 30. transition_to()
# ----------------------------------------------------------------------
class TestTransitionTo(unittest.TestCase):
    def test_pending_to_ready_succeeds(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.transition_to(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)

    def test_ready_to_in_progress_succeeds(self):
        task = _make_task(status=STATUS_READY)
        self.assertTrue(task.transition_to(STATUS_IN_PROGRESS))
        self.assertEqual(task.status, STATUS_IN_PROGRESS)

    def test_in_progress_to_completed_succeeds(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertTrue(task.transition_to(STATUS_COMPLETED))
        self.assertEqual(task.status, STATUS_COMPLETED)

    def test_in_progress_to_failed_succeeds(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertTrue(task.transition_to(STATUS_FAILED))
        self.assertEqual(task.status, STATUS_FAILED)

    def test_in_progress_to_cancelled_succeeds(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertTrue(task.transition_to(STATUS_CANCELLED))
        self.assertEqual(task.status, STATUS_CANCELLED)

    def test_blocked_to_ready_succeeds(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertTrue(task.transition_to(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)

    def test_invalid_transition_returns_false(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertFalse(task.transition_to(STATUS_COMPLETED))

    def test_same_status_transition_returns_false(self):
        task = _make_task(status=STATUS_READY)
        self.assertFalse(task.transition_to(STATUS_READY))

    def test_failed_transition_leaves_status_unchanged(self):
        task = _make_task(status=STATUS_PENDING)
        task.transition_to(STATUS_COMPLETED)
        self.assertEqual(task.status, STATUS_PENDING)
        task.transition_to("LAUNCHED")
        self.assertEqual(task.status, STATUS_PENDING)
        task.transition_to(STATUS_PENDING)
        self.assertEqual(task.status, STATUS_PENDING)

    def test_failed_transition_does_not_modify_other_fields(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            opportunity_id="opp-test-1",
            dependencies=["task-a"],
            metadata={"note": "keep"},
        )
        task.transition_to(STATUS_COMPLETED)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.dependencies, ["task-a"])
        self.assertEqual(task.metadata, {"note": "keep"})

    def test_successful_transition_does_not_modify_other_fields(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            opportunity_id="opp-test-1",
            dependencies=["task-a"],
            metadata={"note": "keep"},
        )
        task.transition_to(STATUS_READY)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.dependencies, ["task-a"])
        self.assertEqual(task.metadata, {"note": "keep"})

    def test_is_valid_transition_remains_correct(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.is_valid_transition(STATUS_READY))
        self.assertFalse(task.is_valid_transition(STATUS_COMPLETED))
        self.assertFalse(task.is_valid_transition(STATUS_PENDING))
        self.assertFalse(task.is_valid_transition("LAUNCHED"))

    def test_set_status_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.set_status(STATUS_COMPLETED))
        self.assertEqual(task.status, STATUS_COMPLETED)
        self.assertFalse(task.set_status("NOT_A_STATUS"))
        self.assertEqual(task.status, STATUS_COMPLETED)

    def test_change_status_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.change_status(STATUS_PENDING, STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertFalse(task.change_status(STATUS_PENDING, STATUS_COMPLETED))
        self.assertEqual(task.status, STATUS_READY)


# ----------------------------------------------------------------------
# 31. get_transition_status()
# ----------------------------------------------------------------------
class TestGetTransitionStatus(unittest.TestCase):
    def test_valid_transition_returns_valid_true(self):
        task = _make_task(status=STATUS_PENDING)
        result = task.get_transition_status(STATUS_READY)
        self.assertTrue(result["valid"])

    def test_invalid_transition_returns_valid_false(self):
        task = _make_task(status=STATUS_PENDING)
        result = task.get_transition_status(STATUS_COMPLETED)
        self.assertFalse(result["valid"])

    def test_current_status_is_correct(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        result = task.get_transition_status(STATUS_COMPLETED)
        self.assertEqual(result["current_status"], STATUS_IN_PROGRESS)

    def test_target_status_is_exactly_the_supplied_value(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertEqual(
            task.get_transition_status(STATUS_READY)["target_status"], STATUS_READY
        )
        self.assertEqual(
            task.get_transition_status("LAUNCHED")["target_status"], "LAUNCHED"
        )
        self.assertIsNone(task.get_transition_status(None)["target_status"])

    def test_returns_expected_shape(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertEqual(
            task.get_transition_status(STATUS_READY),
            {
                "current_status": STATUS_BLOCKED,
                "target_status": STATUS_READY,
                "valid": True,
            },
        )

    def test_calling_it_never_changes_task_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.get_transition_status(STATUS_READY)
        self.assertEqual(task.status, STATUS_PENDING)
        task.get_transition_status(STATUS_COMPLETED)
        self.assertEqual(task.status, STATUS_PENDING)
        task.get_transition_status("LAUNCHED")
        self.assertEqual(task.status, STATUS_PENDING)

    def test_calling_it_never_changes_other_fields(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            opportunity_id="opp-test-1",
            dependencies=["task-a"],
        )
        task.get_transition_status(STATUS_READY)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.dependencies, ["task-a"])

    def test_transition_to_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.transition_to(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertFalse(task.transition_to(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)

    def test_is_valid_transition_still_works(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.is_valid_transition(STATUS_READY))
        self.assertFalse(task.is_valid_transition(STATUS_COMPLETED))


# ----------------------------------------------------------------------
# 32. get_allowed_transitions()
# ----------------------------------------------------------------------
class TestGetAllowedTransitions(unittest.TestCase):
    def test_pending_returns_correct_transitions(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertEqual(
            task.get_allowed_transitions(),
            [STATUS_READY, STATUS_BLOCKED, STATUS_CANCELLED],
        )

    def test_ready_returns_correct_transitions(self):
        task = _make_task(status=STATUS_READY)
        self.assertEqual(
            task.get_allowed_transitions(),
            [STATUS_IN_PROGRESS, STATUS_BLOCKED, STATUS_CANCELLED],
        )

    def test_in_progress_returns_correct_transitions(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertEqual(
            task.get_allowed_transitions(),
            [STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED],
        )

    def test_blocked_returns_correct_transitions(self):
        task = _make_task(status=STATUS_BLOCKED)
        self.assertEqual(
            task.get_allowed_transitions(), [STATUS_READY, STATUS_CANCELLED]
        )

    def test_completed_returns_empty_list(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertEqual(task.get_allowed_transitions(), [])

    def test_failed_returns_empty_list(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertEqual(task.get_allowed_transitions(), [])

    def test_cancelled_returns_empty_list(self):
        task = _make_task(status=STATUS_CANCELLED)
        self.assertEqual(task.get_allowed_transitions(), [])

    def test_calling_it_does_not_change_task_status(self):
        task = _make_task(status=STATUS_PENDING)
        task.get_allowed_transitions()
        self.assertEqual(task.status, STATUS_PENDING)

    def test_returned_list_is_not_shared_mutable_state(self):
        task = _make_task(status=STATUS_PENDING)
        result = task.get_allowed_transitions()
        result.append(STATUS_COMPLETED)
        self.assertEqual(
            task.get_allowed_transitions(),
            [STATUS_READY, STATUS_BLOCKED, STATUS_CANCELLED],
        )

    def test_is_valid_transition_behavior_unchanged(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.is_valid_transition(STATUS_READY))
        self.assertFalse(task.is_valid_transition(STATUS_COMPLETED))
        self.assertFalse(task.is_valid_transition(STATUS_PENDING))

    def test_transition_to_behavior_unchanged(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertTrue(task.transition_to(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)
        self.assertFalse(task.transition_to(STATUS_READY))
        self.assertEqual(task.status, STATUS_READY)


# ----------------------------------------------------------------------
# 33. get_completion_status()
# ----------------------------------------------------------------------
class TestGetCompletionStatus(unittest.TestCase):
    def test_pending(self):
        task = _make_task(status=STATUS_PENDING)
        self.assertEqual(
            task.get_completion_status(),
            {
                "status": STATUS_PENDING,
                "completed": False,
                "failed": False,
                "cancelled": False,
                "final": False,
                "open": True,
            },
        )

    def test_ready(self):
        task = _make_task(status=STATUS_READY)
        self.assertEqual(
            task.get_completion_status(),
            {
                "status": STATUS_READY,
                "completed": False,
                "failed": False,
                "cancelled": False,
                "final": False,
                "open": True,
            },
        )

    def test_in_progress(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertEqual(
            task.get_completion_status(),
            {
                "status": STATUS_IN_PROGRESS,
                "completed": False,
                "failed": False,
                "cancelled": False,
                "final": False,
                "open": True,
            },
        )

    def test_completed(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertEqual(
            task.get_completion_status(),
            {
                "status": STATUS_COMPLETED,
                "completed": True,
                "failed": False,
                "cancelled": False,
                "final": True,
                "open": False,
            },
        )

    def test_failed(self):
        task = _make_task(status=STATUS_FAILED)
        self.assertEqual(
            task.get_completion_status(),
            {
                "status": STATUS_FAILED,
                "completed": False,
                "failed": True,
                "cancelled": False,
                "final": True,
                "open": False,
            },
        )

    def test_cancelled(self):
        task = _make_task(status=STATUS_CANCELLED)
        self.assertEqual(
            task.get_completion_status(),
            {
                "status": STATUS_CANCELLED,
                "completed": False,
                "failed": False,
                "cancelled": True,
                "final": True,
                "open": False,
            },
        )

    def test_all_returned_boolean_values_have_expected_type(self):
        task = _make_task(status=STATUS_BLOCKED)
        result = task.get_completion_status()
        for key in ("completed", "failed", "cancelled", "final", "open"):
            self.assertIsInstance(result[key], bool)

    def test_calling_it_never_changes_the_task(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            opportunity_id="opp-test-1",
            dependencies=["task-a"],
        )
        task.get_completion_status()
        self.assertEqual(task.status, STATUS_PENDING)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.dependencies, ["task-a"])

    def test_existing_status_helper_methods_still_work(self):
        task = _make_task(status=STATUS_COMPLETED)
        self.assertTrue(task.is_completed())
        self.assertTrue(task.is_final())
        self.assertFalse(task.is_open())
        self.assertFalse(task.is_failed())
        self.assertFalse(task.is_cancelled())
        self.assertEqual(task.get_status(), STATUS_COMPLETED)
        self.assertEqual(task.get_allowed_transitions(), [])


# ----------------------------------------------------------------------
# 34. set_opportunity_id()
# ----------------------------------------------------------------------
class TestSetOpportunityId(unittest.TestCase):
    def test_setting_a_valid_opportunity_id_returns_true(self):
        task = _make_task(opportunity_id="opp-old")
        self.assertTrue(task.set_opportunity_id("opp-new"))

    def test_opportunity_id_is_actually_updated(self):
        task = _make_task(opportunity_id="opp-old")
        task.set_opportunity_id("opp-new")
        self.assertEqual(task.opportunity_id, "opp-new")

    def test_empty_string_returns_false_and_does_not_modify(self):
        task = _make_task(opportunity_id="opp-old")
        self.assertFalse(task.set_opportunity_id(""))
        self.assertEqual(task.opportunity_id, "opp-old")

    def test_whitespace_only_returns_false_and_does_not_modify(self):
        task = _make_task(opportunity_id="opp-old")
        self.assertFalse(task.set_opportunity_id("   "))
        self.assertEqual(task.opportunity_id, "opp-old")

    def test_non_string_input_returns_false_and_does_not_modify(self):
        task = _make_task(opportunity_id="opp-old")
        self.assertFalse(task.set_opportunity_id(123))
        self.assertEqual(task.opportunity_id, "opp-old")
        self.assertFalse(task.set_opportunity_id(None))
        self.assertEqual(task.opportunity_id, "opp-old")

    def test_get_opportunity_id_returns_updated_value(self):
        task = _make_task(opportunity_id="opp-old")
        task.set_opportunity_id("opp-new")
        self.assertEqual(task.get_opportunity_id(), "opp-new")

    def test_has_opportunity_reflects_updated_value(self):
        task = _make_task(opportunity_id="")
        self.assertFalse(task.has_opportunity())
        task.set_opportunity_id("opp-new")
        self.assertTrue(task.has_opportunity())

    def test_belongs_to_opportunity_still_works(self):
        task = _make_task(opportunity_id="opp-old")
        task.set_opportunity_id("opp-new")
        self.assertTrue(task.belongs_to_opportunity("opp-new"))
        self.assertFalse(task.belongs_to_opportunity("opp-old"))

    def test_set_opportunity_id_does_not_modify_other_fields(self):
        task = _make_task(
            opportunity_id="opp-old",
            status=STATUS_READY,
            priority=PRIORITY_HIGH,
            dependencies=["task-a"],
            metadata={"note": "keep"},
        )
        task.set_opportunity_id("opp-new")
        self.assertEqual(task.status, STATUS_READY)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.dependencies, ["task-a"])
        self.assertEqual(task.metadata, {"note": "keep"})

    def test_existing_behavior_remains_unchanged(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        self.assertTrue(task.is_valid())
        self.assertTrue(task.is_startable())
        self.assertTrue(task.can_start())
        self.assertEqual(
            task.get_startability_status(),
            {"startable": True, "ready": True, "has_opportunity": True},
        )


# ----------------------------------------------------------------------
# 35. get_opportunity_reference()
# ----------------------------------------------------------------------
class TestGetOpportunityReference(unittest.TestCase):
    def test_task_with_valid_opportunity_id(self):
        task = _make_task(opportunity_id="opp-test-1")
        result = task.get_opportunity_reference()
        self.assertEqual(result["opportunity_id"], "opp-test-1")
        self.assertTrue(result["has_opportunity"])

    def test_task_without_opportunity_id(self):
        task = _make_task(opportunity_id="")
        result = task.get_opportunity_reference()
        self.assertEqual(result["opportunity_id"], "")
        self.assertFalse(result["has_opportunity"])

    def test_correct_opportunity_id_is_returned(self):
        task = _make_task(opportunity_id="opp-specific")
        self.assertEqual(
            task.get_opportunity_reference()["opportunity_id"], "opp-specific"
        )

    def test_correct_has_opportunity_value_is_returned(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertEqual(
            task.get_opportunity_reference()["has_opportunity"],
            task.has_opportunity(),
        )

    def test_returned_object_is_a_dictionary(self):
        task = _make_task()
        self.assertIsInstance(task.get_opportunity_reference(), dict)

    def test_calling_it_does_not_modify_the_task(self):
        task = _make_task(
            opportunity_id="opp-test-1",
            status=STATUS_READY,
            priority=PRIORITY_HIGH,
            dependencies=["task-a"],
            metadata={"note": "keep"},
        )
        task.get_opportunity_reference()
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.status, STATUS_READY)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.dependencies, ["task-a"])
        self.assertEqual(task.metadata, {"note": "keep"})

    def test_get_opportunity_id_still_works(self):
        task = _make_task(opportunity_id="opp-test-1")
        self.assertEqual(task.get_opportunity_id(), "opp-test-1")

    def test_has_opportunity_still_works(self):
        self.assertTrue(_make_task(opportunity_id="opp-test-1").has_opportunity())
        self.assertFalse(_make_task(opportunity_id="").has_opportunity())

    def test_set_opportunity_id_still_works(self):
        task = _make_task(opportunity_id="opp-old")
        self.assertTrue(task.set_opportunity_id("opp-new"))
        self.assertEqual(task.opportunity_id, "opp-new")
        self.assertFalse(task.set_opportunity_id(""))
        self.assertEqual(task.opportunity_id, "opp-new")


# ----------------------------------------------------------------------
# 36. to_reference_dict()
# ----------------------------------------------------------------------
class TestToReferenceDict(unittest.TestCase):
    def test_correct_task_id(self):
        task = _make_task(task_id="task-ref-1")
        self.assertEqual(task.to_reference_dict()["task_id"], "task-ref-1")

    def test_correct_opportunity_id(self):
        task = _make_task(opportunity_id="opp-ref-1")
        self.assertEqual(
            task.to_reference_dict()["opportunity_id"], "opp-ref-1"
        )

    def test_correct_name(self):
        task = _make_task(name="Reference test task")
        self.assertEqual(task.to_reference_dict()["name"], "Reference test task")

    def test_correct_status(self):
        task = _make_task(status=STATUS_IN_PROGRESS)
        self.assertEqual(task.to_reference_dict()["status"], STATUS_IN_PROGRESS)

    def test_returns_a_new_dictionary(self):
        task = _make_task()
        self.assertIsInstance(task.to_reference_dict(), dict)
        self.assertIsNot(task.to_reference_dict(), task.to_reference_dict())

    def test_returns_expected_shape(self):
        task = _make_task(
            task_id="task-ref-2",
            opportunity_id="opp-ref-2",
            name="Ref shape task",
            status=STATUS_BLOCKED,
        )
        self.assertEqual(
            task.to_reference_dict(),
            {
                "task_id": "task-ref-2",
                "opportunity_id": "opp-ref-2",
                "name": "Ref shape task",
                "status": STATUS_BLOCKED,
            },
        )

    def test_modifying_returned_dict_does_not_modify_task(self):
        task = _make_task(task_id="task-ref-3", name="Original name")
        data = task.to_reference_dict()
        data["task_id"] = "changed"
        data["name"] = "changed"
        self.assertEqual(task.task_id, "task-ref-3")
        self.assertEqual(task.name, "Original name")

    def test_does_not_modify_the_task(self):
        task = _make_task(
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
            dependencies=["task-a"],
            metadata={"note": "keep"},
        )
        task.to_reference_dict()
        self.assertEqual(task.status, STATUS_PENDING)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.dependencies, ["task-a"])
        self.assertEqual(task.metadata, {"note": "keep"})

    def test_existing_methods_continue_to_work(self):
        task = _make_task(status=STATUS_READY, opportunity_id="opp-test-1")
        self.assertTrue(task.is_valid())
        self.assertTrue(task.is_startable())
        self.assertIsInstance(task.to_dict(), dict)
        self.assertEqual(task.get_status(), STATUS_READY)
        self.assertEqual(task.get_opportunity_id(), "opp-test-1")


# ----------------------------------------------------------------------
# to_execution_reference()
# ----------------------------------------------------------------------
class TestToExecutionReference(unittest.TestCase):
    def test_normal_task(self):
        task = _make_task(
            task_id="task-exec-1",
            opportunity_id="opp-exec-1",
            name="Normal task",
            description="A normal task.",
            status=STATUS_PENDING,
            priority=PRIORITY_NORMAL,
            estimated_duration=30,
        )
        self.assertEqual(
            task.to_execution_reference(),
            {
                "task_id": "task-exec-1",
                "opportunity_id": "opp-exec-1",
                "name": "Normal task",
                "description": "A normal task.",
                "status": STATUS_PENDING,
                "priority": PRIORITY_NORMAL,
                "estimated_duration": 30,
                "dependencies": [],
                "startable": task.is_startable(),
                "final": task.is_final(),
            },
        )

    def test_task_with_dependencies(self):
        task = _make_task(dependencies=["task-a", "task-b"])
        reference = task.to_execution_reference()
        self.assertEqual(reference["dependencies"], ["task-a", "task-b"])

    def test_ready_task(self):
        task = _make_task(status=STATUS_READY)
        reference = task.to_execution_reference()
        self.assertEqual(reference["status"], STATUS_READY)
        self.assertEqual(reference["startable"], task.is_startable())
        self.assertEqual(reference["final"], task.is_final())
        self.assertFalse(reference["final"])

    def test_completed_task(self):
        task = _make_task(status=STATUS_COMPLETED)
        reference = task.to_execution_reference()
        self.assertEqual(reference["status"], STATUS_COMPLETED)
        self.assertTrue(reference["final"])
        self.assertFalse(reference["startable"])

    def test_failed_task(self):
        task = _make_task(status=STATUS_FAILED)
        reference = task.to_execution_reference()
        self.assertEqual(reference["status"], STATUS_FAILED)
        self.assertTrue(reference["final"])
        self.assertFalse(reference["startable"])

    def test_cancelled_task(self):
        task = _make_task(status=STATUS_CANCELLED)
        reference = task.to_execution_reference()
        self.assertEqual(reference["status"], STATUS_CANCELLED)
        self.assertTrue(reference["final"])
        self.assertFalse(reference["startable"])

    def test_returned_data_does_not_mutate_original_task(self):
        task = _make_task(
            task_id="task-exec-2",
            dependencies=["task-a"],
            status=STATUS_PENDING,
            priority=PRIORITY_HIGH,
        )
        reference = task.to_execution_reference()
        reference["task_id"] = "tampered"
        reference["opportunity_id"] = "tampered"
        reference["status"] = "tampered"
        reference["dependencies"].append("tampered")
        reference["dependencies"][0] = "tampered"

        self.assertEqual(task.task_id, "task-exec-2")
        self.assertEqual(task.opportunity_id, "opp-test-1")
        self.assertEqual(task.status, STATUS_PENDING)
        self.assertEqual(task.priority, PRIORITY_HIGH)
        self.assertEqual(task.dependencies, ["task-a"])

    def test_returns_new_dictionary_each_call(self):
        task = _make_task()
        self.assertIsInstance(task.to_execution_reference(), dict)
        self.assertIsNot(
            task.to_execution_reference(), task.to_execution_reference()
        )
        self.assertIsNot(
            task.to_execution_reference()["dependencies"],
            task.to_execution_reference()["dependencies"],
        )


# ----------------------------------------------------------------------
# get_dependency_status()
# ----------------------------------------------------------------------
class TestGetDependencyStatus(unittest.TestCase):
    def test_no_dependencies(self):
        task = _make_task(dependencies=[])
        self.assertEqual(
            task.get_dependency_status(),
            {
                "has_dependencies": False,
                "total": 0,
                "completed": 0,
                "remaining": [],
                "ready": True,
            },
        )

    def test_all_dependencies_completed(self):
        task = _make_task(dependencies=["task-a", "task-b"])
        self.assertEqual(
            task.get_dependency_status(["task-a", "task-b"]),
            {
                "has_dependencies": True,
                "total": 2,
                "completed": 2,
                "remaining": [],
                "ready": True,
            },
        )

    def test_partially_completed_dependencies(self):
        task = _make_task(dependencies=["task-a", "task-b", "task-c"])
        self.assertEqual(
            task.get_dependency_status(["task-a"]),
            {
                "has_dependencies": True,
                "total": 3,
                "completed": 1,
                "remaining": ["task-b", "task-c"],
                "ready": False,
            },
        )

    def test_no_completed_dependencies(self):
        task = _make_task(dependencies=["task-a", "task-b"])
        self.assertEqual(
            task.get_dependency_status([]),
            {
                "has_dependencies": True,
                "total": 2,
                "completed": 0,
                "remaining": ["task-a", "task-b"],
                "ready": False,
            },
        )

    def test_duplicate_dependency_ids(self):
        task = _make_task(
            dependencies=["task-a", "task-a", "task-b", "task-a"]
        )
        self.assertEqual(
            task.get_dependency_status(["task-a", "task-a"]),
            {
                "has_dependencies": True,
                "total": 2,
                "completed": 1,
                "remaining": ["task-b"],
                "ready": False,
            },
        )

    def test_whitespace_around_ids(self):
        task = _make_task(dependencies=[" task-a ", "task-b\t"])
        self.assertEqual(
            task.get_dependency_status([" task-a", "task-b "]),
            {
                "has_dependencies": True,
                "total": 2,
                "completed": 2,
                "remaining": [],
                "ready": True,
            },
        )

    def test_none_input(self):
        task = _make_task(dependencies=["task-a", "task-b"])
        self.assertEqual(
            task.get_dependency_status(None),
            {
                "has_dependencies": True,
                "total": 2,
                "completed": 0,
                "remaining": ["task-a", "task-b"],
                "ready": False,
            },
        )

    def test_original_task_is_unchanged(self):
        task = _make_task(
            task_id="task-dep-1",
            dependencies=["task-a", "task-b"],
            status=STATUS_PENDING,
        )
        task.get_dependency_status(["task-a"])
        task.get_dependency_status(None)
        self.assertEqual(task.task_id, "task-dep-1")
        self.assertEqual(task.dependencies, ["task-a", "task-b"])
        self.assertEqual(task.status, STATUS_PENDING)

    def test_invalid_entries_ignored(self):
        task = _make_task(dependencies=["task-a", "", "   ", None, 123])
        self.assertEqual(
            task.get_dependency_status(["task-a", "", None, 123]),
            {
                "has_dependencies": True,
                "total": 1,
                "completed": 1,
                "remaining": [],
                "ready": True,
            },
        )


# ----------------------------------------------------------------------
# get_readiness_report()
# ----------------------------------------------------------------------
class TestGetReadinessReport(unittest.TestCase):
    def test_task_with_no_dependencies(self):
        task = _make_task(
            task_id="task-rr-1",
            opportunity_id="opp-rr-1",
            status=STATUS_READY,
            dependencies=[],
        )
        self.assertEqual(
            task.get_readiness_report(),
            {
                "task_id": "task-rr-1",
                "status": STATUS_READY,
                "has_opportunity": True,
                "has_dependencies": False,
                "dependencies_ready": True,
                "startable": True,
                "ready": True,
            },
        )

    def test_task_with_completed_dependencies(self):
        task = _make_task(
            opportunity_id="opp-rr-2",
            status=STATUS_READY,
            dependencies=["task-a", "task-b"],
        )
        report = task.get_readiness_report(["task-a", "task-b"])
        self.assertTrue(report["has_dependencies"])
        self.assertTrue(report["dependencies_ready"])
        self.assertTrue(report["ready"])

    def test_task_with_incomplete_dependencies(self):
        task = _make_task(
            opportunity_id="opp-rr-3",
            status=STATUS_READY,
            dependencies=["task-a", "task-b"],
        )
        report = task.get_readiness_report(["task-a"])
        self.assertTrue(report["has_dependencies"])
        self.assertFalse(report["dependencies_ready"])
        self.assertFalse(report["ready"])

    def test_task_without_an_opportunity(self):
        task = _make_task(
            opportunity_id=None,
            status=STATUS_READY,
            dependencies=[],
        )
        report = task.get_readiness_report()
        self.assertFalse(report["has_opportunity"])
        self.assertFalse(report["ready"])

    def test_ready_task(self):
        task = _make_task(
            opportunity_id="opp-rr-4",
            status=STATUS_READY,
            dependencies=["task-a"],
        )
        report = task.get_readiness_report(["task-a"])
        self.assertEqual(report["status"], STATUS_READY)
        self.assertTrue(report["startable"])
        self.assertTrue(report["ready"])

    def test_non_ready_task(self):
        task = _make_task(
            opportunity_id="opp-rr-5",
            status=STATUS_PENDING,
            dependencies=[],
        )
        report = task.get_readiness_report()
        self.assertEqual(report["status"], STATUS_PENDING)
        self.assertFalse(report["startable"])
        self.assertFalse(report["ready"])

    def test_task_remains_unchanged_after_inspection(self):
        task = _make_task(
            task_id="task-rr-6",
            opportunity_id="opp-rr-6",
            status=STATUS_READY,
            dependencies=["task-a"],
        )
        task.get_readiness_report(["task-a"])
        task.get_readiness_report(None)
        self.assertEqual(task.task_id, "task-rr-6")
        self.assertEqual(task.opportunity_id, "opp-rr-6")
        self.assertEqual(task.status, STATUS_READY)
        self.assertEqual(task.dependencies, ["task-a"])

    def test_returns_new_dictionary(self):
        task = _make_task(opportunity_id="opp-rr-7", status=STATUS_READY)
        self.assertIsInstance(task.get_readiness_report(), dict)
        self.assertIsNot(
            task.get_readiness_report(), task.get_readiness_report()
        )


if __name__ == "__main__":
    unittest.main()
