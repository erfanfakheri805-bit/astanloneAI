"""
Self-Builder - policy (allowlists and limits)
=============================================
Everything the Self-Builder is allowed to touch, create or run is declared
here, in one place, and enforced by `Policy` before any file operation or
code load happens.

What the Self-Builder may do
----------------------------
* Work only inside ONE writable root directory (`<app data dir>/self_builder`
  - on Android that is `files_dir/data/self_builder`). The application's own
  source tree (the APK's python assets) is never written to.
* Create only files whose directory, name pattern and suffix are allowed
  below (generated modules, JSON test suites, JSON specs, JSON checkpoints,
  one manifest, quarantined leftovers). No other path or file type.
* Perform only the operations in `ALLOWED_OPERATIONS`.
* Build only the capability archetypes in `SUPPORTED_ARCHETYPES`, and only
  with the permissions in `GRANTABLE_PERMISSIONS` (pure computation - no
  file, network, device, process or import access is ever grantable).

Resource limits are deliberately small: they bound the size of anything a
user request can make the Self-Builder generate, store or run.
"""

import os
import re

from .errors import PolicyViolation

SCHEMA_VERSION = 1

# Capability archetypes the Self-Builder can build (closed set - there is no
# code-generating model in this application, so "supported" means "a template
# archetype exists for it").
ARCHETYPE_UNIT_CONVERSION = "unit_conversion"
ARCHETYPE_FORMULA = "formula"
ARCHETYPE_TEXT_TOOL = "text_tool"
SUPPORTED_ARCHETYPES = (
    ARCHETYPE_UNIT_CONVERSION,
    ARCHETYPE_FORMULA,
    ARCHETYPE_TEXT_TOOL,
)

# Capability permissions. Only pure computation can be granted.
PERMISSION_COMPUTE = "compute"
GRANTABLE_PERMISSIONS = frozenset({PERMISSION_COMPUTE})

# Operations (see Policy.check_operation).
OP_STAGE = "stage_files"
OP_CREATE_MODULE = "create_module"
OP_CREATE_TESTS = "create_tests"
OP_CREATE_SPEC = "create_spec"
OP_WRITE_MANIFEST = "write_manifest"
OP_SNAPSHOT = "snapshot_checkpoint"
OP_RESTORE = "restore_version"
OP_QUARANTINE = "quarantine_file"
OP_REMOVE_STAGED = "remove_staged"
OP_REGISTER = "update_registry"
OP_LOAD_MODULE = "load_validated_module"
ALLOWED_OPERATIONS = frozenset({
    OP_STAGE, OP_CREATE_MODULE, OP_CREATE_TESTS, OP_CREATE_SPEC, OP_WRITE_MANIFEST,
    OP_SNAPSHOT, OP_RESTORE, OP_QUARANTINE, OP_REMOVE_STAGED, OP_REGISTER, OP_LOAD_MODULE,
})

# Sub-directories of the root, and the one file-name pattern allowed in each.
SUBDIR_STAGING = "staging"
SUBDIR_MODULES = "modules"
SUBDIR_TESTS = "tests"
SUBDIR_SPECS = "specs"
SUBDIR_CHECKPOINTS = "checkpoints"
SUBDIR_QUARANTINE = "quarantine"
ROOT_FILE_MANIFEST = "manifest.json"
ROOT_FILE_DB = "self_builder.db"
ROOT_FILE_LOCK = "self_builder.lock"     # empty file; see lock.py

_ID_BODY = r"[a-z][a-z0-9_]{2,47}"
_FILE_PATTERNS = {
    SUBDIR_STAGING: re.compile(r"^stg_[a-z0-9_]{3,64}\.(py|json)$"),
    SUBDIR_MODULES: re.compile(r"^" + _ID_BODY + r"_v[0-9]{1,4}\.py$"),
    SUBDIR_TESTS: re.compile(r"^" + _ID_BODY + r"_v[0-9]{1,4}\.json$"),
    SUBDIR_SPECS: re.compile(r"^" + _ID_BODY + r"_v[0-9]{1,4}\.json$"),
    SUBDIR_CHECKPOINTS: re.compile(r"^ck_[0-9]{1,9}\.json$"),
    SUBDIR_QUARANTINE: re.compile(r"^q_[0-9A-Za-z_.\-]{3,160}$"),
}
ALLOWED_SUFFIXES = frozenset({".py", ".json"})
CAPABILITY_ID_RE = re.compile(r"^" + _ID_BODY + r"$")

# ---- resource limits -------------------------------------------------------
MAX_SOURCE_BYTES = 12_000          # one generated module
MAX_TESTS_BYTES = 40_000           # one JSON test suite
MAX_EXPR_CHARS = 240               # formula text as typed by the user
MAX_EXPR_NODES = 160               # nodes in the parsed expression tree
MAX_EXPR_DEPTH = 24                # nesting depth of the parsed expression
MAX_VARIABLES = 8
MAX_TEST_CASES = 48
MAX_CAPABILITIES = 200
MAX_VERSIONS_PER_CAPABILITY = 60
MAX_REPAIR_ATTEMPTS = 6            # one repair per failure class: chains of 3-4 are normal
MAX_REQUEST_CHARS = 2000           # a build request
MAX_INVOKE_TEXT_CHARS = 4000       # text handed to a capability when it runs
MAX_RESULT_ABS = 1e300             # numeric results must stay finite and below this
MAX_CALL_SECONDS = 0.5             # soft wall-clock budget per generated-code call
MAX_AST_NODES = 1500               # nodes in a generated module
MAX_STRING_CONSTANT = 200          # longest string literal in a generated module
PENDING_TTL_SECONDS = 30 * 60      # how long an unanswered clarification stays valid
LOCK_TIMEOUT_SECONDS = 30.0        # how long a build / rollback waits for another one that is still running
RECONCILE_LOCK_SECONDS = 10.0      # how long the start-up reconciliation waits before it leaves clean-up for later


def is_valid_capability_id(value):
    return isinstance(value, str) and bool(CAPABILITY_ID_RE.match(value))


class Policy:
    """Stateless checks. Every Self-Builder file operation goes through
    `resolve()`; every pipeline step announces itself with `check_operation()`."""

    @staticmethod
    def check_operation(operation):
        if operation not in ALLOWED_OPERATIONS:
            raise PolicyViolation(f"operation not allowed: {operation!r}", code="E_POLICY_OPERATION",
                                  operation=str(operation))
        return operation

    @staticmethod
    def check_archetype(kind):
        if kind not in SUPPORTED_ARCHETYPES:
            raise PolicyViolation(f"unsupported capability archetype: {kind!r}", code="E_POLICY_ARCHETYPE",
                                  kind=str(kind))
        return kind

    @staticmethod
    def check_permissions(permissions):
        perms = list(permissions or [])
        extra = [p for p in perms if p not in GRANTABLE_PERMISSIONS]
        if extra:
            raise PolicyViolation(f"permissions not grantable: {extra!r}", code="E_POLICY_PERMISSION",
                                  permissions=[str(p) for p in extra])
        return perms

    @staticmethod
    def check_capability_id(capability_id):
        if not is_valid_capability_id(capability_id):
            raise PolicyViolation(f"invalid capability id: {capability_id!r}", code="E_POLICY_ID")
        return capability_id

    @staticmethod
    def check_file_name(subdir, filename):
        pattern = _FILE_PATTERNS.get(subdir)
        if pattern is None:
            raise PolicyViolation(f"directory not allowed: {subdir!r}", code="E_POLICY_DIR", directory=str(subdir))
        if not isinstance(filename, str) or not pattern.match(filename):
            raise PolicyViolation(f"file name not allowed in {subdir}: {filename!r}", code="E_POLICY_NAME",
                                  directory=subdir)
        if os.path.splitext(filename)[1] not in ALLOWED_SUFFIXES:
            raise PolicyViolation(f"file type not allowed: {filename!r}", code="E_POLICY_SUFFIX")
        return filename

    @staticmethod
    def check_root_file(filename):
        if filename not in (ROOT_FILE_MANIFEST, ROOT_FILE_DB, ROOT_FILE_LOCK):
            raise PolicyViolation(f"root file not allowed: {filename!r}", code="E_POLICY_NAME")
        return filename

    @classmethod
    def resolve(cls, root, subdir, filename):
        """Absolute path of an allowed file inside `root`. `subdir=None`
        addresses the two fixed root files. Refuses anything that could
        escape `root` (separators, `..`, symlinks)."""
        if subdir is None:
            cls.check_root_file(filename)
        else:
            cls.check_file_name(subdir, filename)
        if os.sep in filename or (os.altsep and os.altsep in filename) or filename in (".", ".."):
            raise PolicyViolation(f"path separator in file name: {filename!r}", code="E_POLICY_NAME")
        real_root = os.path.realpath(root)
        directory = real_root if subdir is None else os.path.join(real_root, subdir)
        if subdir is not None and os.path.islink(directory):
            raise PolicyViolation(f"directory is a symlink: {subdir}", code="E_POLICY_SYMLINK")
        path = os.path.join(directory, filename)
        if os.path.islink(path):
            raise PolicyViolation(f"file is a symlink: {filename}", code="E_POLICY_SYMLINK")
        real = os.path.realpath(path)
        if os.path.commonpath([real_root, real]) != real_root:
            raise PolicyViolation("path escapes the Self-Builder root", code="E_POLICY_PATH")
        return real

    @classmethod
    def describe(cls):
        """Plain-data description of the policy (shown by the capability status command and tested)."""
        return {
            "archetypes": list(SUPPORTED_ARCHETYPES),
            "permissions": sorted(GRANTABLE_PERMISSIONS),
            "operations": sorted(ALLOWED_OPERATIONS),
            "directories": sorted(_FILE_PATTERNS),
            "suffixes": sorted(ALLOWED_SUFFIXES),
            "limits": {
                "max_source_bytes": MAX_SOURCE_BYTES,
                "max_expr_chars": MAX_EXPR_CHARS,
                "max_expr_nodes": MAX_EXPR_NODES,
                "max_variables": MAX_VARIABLES,
                "max_test_cases": MAX_TEST_CASES,
                "max_capabilities": MAX_CAPABILITIES,
                "max_versions_per_capability": MAX_VERSIONS_PER_CAPABILITY,
                "max_repair_attempts": MAX_REPAIR_ATTEMPTS,
                "max_call_seconds": MAX_CALL_SECONDS,
            },
        }
