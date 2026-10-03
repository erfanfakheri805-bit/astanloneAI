"""
Tests for the built-in `code_change_apply_and_test` capability
(execution/code_change_apply_and_test_capability.py) - connects the
existing `code_change_apply` capability (itself already a connection
of `code_change_plan`/`text_file_edit`) to the existing
`python_test_runner` capability and the existing
`agent.test_result_evaluation` classifier.

Covers: a successful code change followed by a passing test; a failed
code change never starting the test; a failing test being reported as
FAILED; and a hanging test being reported as TIMEOUT.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_code_change_apply_and_test_capability -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.capability import Capability
from execution.code_change_apply_and_test_capability import (
    CAPABILITY_NAME,
    CHANGE_STATUS_APPLIED,
    CHANGE_STATUS_NOT_APPLIED,
    create_code_change_apply_and_test_capability,
)
from agent.test_result_evaluation import (
    RESULT_PASSED,
    RESULT_FAILED,
    RESULT_TIMEOUT,
)

VALID_SOURCE = (
    "def greet(name):\n"
    "    return 'hi ' + name\n"
)

PASSING_TEST_SOURCE = (
    "import unittest\n"
    "from thing import greet\n\n"
    "class TestGreet(unittest.TestCase):\n"
    "    def test_greet(self):\n"
    "        self.assertEqual(greet('world'), 'hello world')\n"
)

FAILING_TEST_SOURCE = (
    "import unittest\n\n"
    "class TestFailing(unittest.TestCase):\n"
    "    def test_not_ok(self):\n"
    "        self.assertEqual(1 + 1, 3)\n"
)

HANGING_TEST_SOURCE = (
    "import time\n"
    "import unittest\n\n"
    "class TestHanging(unittest.TestCase):\n"
    "    def test_hangs(self):\n"
    "        time.sleep(60)\n"
)


class CodeChangeApplyAndTestCapabilityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, *relative_parts, content=""):
        path = os.path.join(self.allowed_dir, *relative_parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _capability(self, **kwargs):
        return create_code_change_apply_and_test_capability(
            allowed_dirs=[self.allowed_dir], **kwargs
        )


class TestCapabilityIsARealCapability(CodeChangeApplyAndTestCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)


# ----------------------------------------------------------------------
# 1. Successful code change followed by a passing test.
# ----------------------------------------------------------------------
class TestSuccessfulChangeFollowedByPassingTest(CodeChangeApplyAndTestCapabilityTestBase):
    def test_change_applied_and_test_passes(self):
        self._write("thing.py", content=VALID_SOURCE)
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": os.path.join(self.allowed_dir, "thing.py"),
            "old_text": "return 'hi ' + name",
            "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        output = result.output
        self.assertEqual(output["change_status"], CHANGE_STATUS_APPLIED)
        self.assertEqual(output["test_status"], RESULT_PASSED)
        self.assertIsNone(output["error"])
        self.assertIsNotNone(output["test_output"])
        self.assertTrue(output["change_result"]["change_applied"])
        self.assertTrue(output["test_result"]["success"])

    def test_file_was_actually_modified(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        capability.execute({
            "path": path,
            "old_text": "return 'hi ' + name",
            "new_text": "return 'hello ' + name",
        })

        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn("return 'hello ' + name", fh.read())


# ----------------------------------------------------------------------
# 2. A failed code change never starts the test.
# ----------------------------------------------------------------------
class TestFailedChangeDoesNotStartTest(CodeChangeApplyAndTestCapabilityTestBase):
    def test_missing_fragment_does_not_run_test(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path,
            "old_text": "this text is not in the file",
            "new_text": "anything",
        })

        output = result.output
        self.assertEqual(output["change_status"], CHANGE_STATUS_NOT_APPLIED)
        self.assertIsNone(output["test_status"])
        self.assertIsNone(output["test_output"])
        self.assertIsNone(output["test_result"])
        self.assertIsNotNone(output["error"])
        # File is left untouched.
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), VALID_SOURCE)

    def test_syntactically_broken_source_does_not_run_test(self):
        path = self._write("broken.py", content="def broken(:\n    pass\n")
        self._write("test_thing.py", content=PASSING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "pass", "new_text": "return",
        })

        output = result.output
        self.assertEqual(output["change_status"], CHANGE_STATUS_NOT_APPLIED)
        self.assertIsNone(output["test_status"])
        self.assertIsNone(output["test_result"])


# ----------------------------------------------------------------------
# 3. A failing test is reported as FAILED.
# ----------------------------------------------------------------------
class TestFailingTestIsReportedAsFailed(CodeChangeApplyAndTestCapabilityTestBase):
    def test_failing_test_reported(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        self._write("test_thing.py", content=FAILING_TEST_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path,
            "old_text": "return 'hi ' + name",
            "new_text": "return 'hello ' + name",
        })

        output = result.output
        self.assertEqual(output["change_status"], CHANGE_STATUS_APPLIED)
        self.assertEqual(output["test_status"], RESULT_FAILED)
        self.assertIsNone(output["error"])
        self.assertFalse(output["test_result"]["success"])


# ----------------------------------------------------------------------
# 4. A hanging test is reported as TIMEOUT.
# ----------------------------------------------------------------------
class TestHangingTestIsReportedAsTimeout(CodeChangeApplyAndTestCapabilityTestBase):
    def test_timeout_reported(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        self._write("test_thing.py", content=HANGING_TEST_SOURCE)
        capability = self._capability(timeout_seconds=1)

        result = capability.execute({
            "path": path,
            "old_text": "return 'hi ' + name",
            "new_text": "return 'hello ' + name",
        })

        output = result.output
        self.assertEqual(output["change_status"], CHANGE_STATUS_APPLIED)
        self.assertEqual(output["test_status"], RESULT_TIMEOUT)
        self.assertIsNone(output["error"])
        self.assertTrue(output["test_result"]["timed_out"])


if __name__ == "__main__":
    unittest.main()
