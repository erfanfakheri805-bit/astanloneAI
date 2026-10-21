"""
Extension runtime (PROMPT 957)
==============================
Everything needed to accept, validate, test and run user/ChatGPT-supplied extensions safely, without a model and
without external services:

    manifest     the `ext.v1` package format (validation, normalization, fingerprint, typed inputs/outputs)
    srcvalidate  allowlist validation of the extension's Python source (never runs it)
    instrument   rewrites validated code so every loop/call/growth op is metered
    guards       the run-time namespace: budget (work+time), size limits, safe builtins, permission helpers
    sandbox      compile_source() + run(): fresh module per call, `__builtins__ = {}`
    patterns     trigger phrases -> inputs, for normal chat invocation
    intake       package bytes (JSON / ZIP) -> validated manifest (path, size, hash and type checks)
    lifecycle    the extension manager: propose -> test -> approve -> activate -> invoke -> update -> rollback

Nothing here imports a network, process or dynamic-execution facility; the only module that can reach the network
is `net_tools`, and only for extensions that were granted the `network` permission.
"""

from .errors import ExtError, LimitExceeded, ManifestError, PackageError, SourceRejected  # noqa: F401
from .limits import EXT_KIND, EXT_SCHEMA  # noqa: F401
