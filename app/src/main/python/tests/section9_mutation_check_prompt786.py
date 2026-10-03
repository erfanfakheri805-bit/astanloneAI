"""Prompt 786 - mutation / sensitivity check for the Section 9 acceptance suite (run by hand; not collected as a test).

    PYTHONDONTWRITEBYTECODE=1 python3 tests/section9_mutation_check_prompt786.py

Copies the project to a temporary directory, applies ONE deliberate fault at a time to a production file of the copy and runs the acceptance
suite there. Behavioral faults must be caught by the BEHAVIORAL classes alone (the byte-pin classes are left out of that run, so a pin cannot
hide a weak assertion). Tree faults (an added import, a changed non-web module, a changed database) must be caught by the full suite.
The real project is never modified. Exit status 0 only when every fault is caught and the unmutated copy passes.
"""
import os
import shutil
import subprocess
import sys
import tempfile

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
MODULE = "tests.test_section9_final_acceptance_prompt786"
BEHAVIORAL = ("TestChainComposition", "TestInvalidInputsAreRejectedDeterministically", "TestExactTypeAndImmutabilityContracts",
              "TestDeterminismOrderAndNoDuplicateExecution", "TestBatchSummaryIsDeterministicAndDoesNotReinterpret",
              "TestScopeHonestyNetworkTransportIsNotImplemented", "TestNoAccidentalExternalAccessAndNoRetainedState")

B = "web/web_request_batch.py"
S = "web/web_request_batch_summary.py"
P = "web/web_request_pipeline.py"
D = "web/web_request_dispatcher.py"
X = "web/web_request_executor.py"
# (name, relative file, old text, new text, scope)  scope: "behavioral" or "full"
MUTATIONS = [
    ("batch reverses output order", B, "tuple(run_web_request_pipeline(plan) for plan in plans)", "tuple(run_web_request_pipeline(plan) for plan in reversed(plans))", "behavioral"),
    ("batch runs every plan twice", B, "tuple(run_web_request_pipeline(plan) for plan in plans)", "tuple([run_web_request_pipeline(plan), run_web_request_pipeline(plan)][0] for plan in plans)", "behavioral"),
    ("batch accepts lists", B, "if type(plans) is not tuple:", "if type(plans) not in (tuple, list):", "behavioral"),
    ("batch short-circuits to the first plan", B, "tuple(run_web_request_pipeline(plan) for plan in plans)", "tuple(run_web_request_pipeline(plan) for plan in plans[:1])", "behavioral"),
    ("batch runs valid items even when one is bad", B, "    if failures:\n        return WebRequestBatchResult(_CREATE_TOKEN, (), failures)\n", "    if failures:\n        [run_web_request_pipeline(p) for p in plans if type(p) is WebRequestPlan]\n        return WebRequestBatchResult(_CREATE_TOKEN, (), failures)\n", "behavioral"),
    ("pipeline copies the dispatched output", P, "    return dispatch_web_request(plan)", "    o = dispatch_web_request(plan)\n    return WebRequestOutput(_OUTPUT_CREATE_TOKEN, o.status, o.code, tuple(o.metadata.items()))", "behavioral"),
    ("pipeline skips its own plan check", P, "if type(plan) is not WebRequestPlan:", "if plan is None:", "behavioral"),
    ("pipeline dispatches twice", P, "    return dispatch_web_request(plan)", "    dispatch_web_request(plan)\n    return dispatch_web_request(plan)", "behavioral"),
    ("dispatcher skips its own plan check", D, "if type(plan) is not WebRequestPlan:", "if plan is None:", "behavioral"),
    ("dispatcher executes twice", D, "return create_web_request_output(execute_web_request_plan(plan))", "execute_web_request_plan(plan)\n    return create_web_request_output(execute_web_request_plan(plan))", "behavioral"),
    ("summary uses first-seen order", S, "sorted(status_counts.items()), sorted(code_counts.items())", "list(status_counts.items()), list(code_counts.items())", "behavioral"),
    ("summary success depends on outputs", S, "batch_result.ok is True, ())", "bool(output_count), ())", "behavioral"),
    ("summary folds status case", S, "status = output.status\n", "status = output.status.upper()\n", "behavioral"),
    ("summary reads metadata", S, "        code = output.code\n", "        code = output.code\n        output.metadata\n", "behavioral"),
    ("summary counts the caller-visible failures only for rejected", S, "output_count + failure_count, output_count", "output_count, output_count", "behavioral"),
    ("executor reports executed", X, "    def executed(self):\n        return False", "    def executed(self):\n        return True", "behavioral"),
    ("executor reports success", X, "    def ok(self):\n        return False", "    def ok(self):\n        return True", "behavioral"),
    ("executor drops a plan value from metadata", X, '"resource_type": self._resource_type, "timeout_ms": self._timeout_ms}\n\n    def to_dict', '"resource_type": self._resource_type}\n\n    def to_dict', "behavioral"),
    ("validator ignores the registry lookup", "web/web_request_validator.py", "if lookup.found and type(lookup.resource) is WebResource:", "if True:", "behavioral"),
    ("plan factory ignores failed validation", "web/web_request_plan.py", "    if not validation_result.ok:\n", "    if False:\n", "behavioral"),
    ("registry allows duplicate ids", "web/web_resource_registry.py", "elif item.resource_id in seen:", "elif False:", "behavioral"),
    ("resource allows an empty url", "web/web_resource.py", "elif field in REQUIRED_NON_EMPTY and len(value) == 0:", "elif False:", "behavioral"),
    ("request accepts a zero timeout", "web/web_request.py", "elif value <= 0:", "elif value < 0:", "behavioral"),
    ("request accepts bool as timeout", "web/web_request.py", "if type(value) is not int:", "if not isinstance(value, int):", "behavioral"),
    ("output validator ignores status type", "web/web_request_output_validator.py", "status_ok = type(output.status) is str", "status_ok = True", "behavioral"),
    ("metadata executor accepts invalid output", "web/web_request_metadata_executor.py", "    if not checked.ok:\n", "    if False:\n", "behavioral"),
    ("output keeps a mutable metadata dict", "web/web_request_output.py", "        return dict(self._items)", "        return self._items", "behavioral"),
    ("immutability removed from the batch result", B, 'raise AttributeError("WebRequestBatchResult is immutable.")\n\n    def __delattr__', "pass\n\n    def __delattr__", "behavioral"),
    ("network import added to the dispatcher", D, "from .web_request_executor import", "import socket\nfrom .web_request_executor import", "behavioral"),
    ("file access added to the pipeline", P, "    return dispatch_web_request(plan)", "    open(__file__).close()\n    return dispatch_web_request(plan)", "behavioral"),
    ("module-level mutable state added to the batch", B, "_CREATE_TOKEN = object()", "_CREATE_TOKEN = object()\n_CACHE = []", "behavioral"),
    ("comment appended to a Section 9 module", D, "from .web_request_executor import", "# tampered\nfrom .web_request_executor import", "full"),
    ("non-web production module changed", "planning/plan_manager.py", "\n", "\n# tampered\n", "full"),
    ("project database changed", "data/memory.db", None, None, "full"),
    ("bytecode artifact present", "web/__pycache__/x.pyc", None, None, "full"),
    ("extra production file in the web package", "web/web_request_extra.py", None, None, "full"),
]


def run_suite(root, scope):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    names = [MODULE + "." + c for c in BEHAVIORAL] if scope == "behavioral" else [MODULE]
    p = subprocess.run([sys.executable, "-m", "unittest"] + names, cwd=os.path.join(root, "app", "src", "main", "python"), env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""


def apply(root, rel, old, new):
    path = os.path.join(root, "app", "src", "main", "python", rel)
    if old is None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if rel == "data/memory.db":
            with open(path, "ab") as fh:
                fh.write(b"x")
        else:
            with open(path, "wb") as fh:
                fh.write(b"")
        return
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if old == "\n":
        text = text.replace("\n", new, 1)
    else:
        assert text.count(old) == 1, (rel, old, text.count(old))
        text = text.replace(old, new)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    caught_all = True
    tmp = tempfile.mkdtemp(prefix="s9mut_")
    try:
        pristine = os.path.join(tmp, "pristine")
        shutil.copytree(REPO_ROOT, pristine, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        code, last = run_suite(pristine, "full")
        print("unmutated copy: %s (%s)" % ("PASS" if code == 0 else "FAIL", last))
        caught_all &= code == 0
        for i, (name, rel, old, new, scope) in enumerate(MUTATIONS, 1):
            work = os.path.join(tmp, "m%d" % i)
            shutil.copytree(pristine, work)
            apply(work, rel, old, new)
            code, last = run_suite(work, scope)
            caught = code != 0
            caught_all &= caught
            print("%2d. %-62s [%s] %s" % (i, name, scope, ("CAUGHT " + last) if caught else "NOT CAUGHT (%s)" % last))
            shutil.rmtree(work)
        print("RESULT:", "all faults caught" if caught_all else "SOME FAULTS WERE NOT CAUGHT")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if caught_all else 1


if __name__ == "__main__":
    sys.exit(main())
