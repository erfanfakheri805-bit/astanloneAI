"""
Language Intelligence - Local Model Configuration
=====================================================
Prompt 398. `LocalModelConfig` describes ONE on-device language model
a `LocalModelRuntime` (local_model_runtime.py) may be asked to load.
It is a plain, dependency-free data holder plus a safe validator - it
never touches the filesystem, never loads anything, never downloads
anything, and never raises for bad values (bad values are *reported*
by `validate()`; see below).

What it can represent (Prompt 398, item 4):

    model_id          - short, human-meaningful identifier (a label,
                        used in results/logs; not a URL, not a repo id
                        that would imply a download).
    model_path        - LOCAL filesystem location of the model
                        file/directory. Remote locations (http://,
                        https://, ftp://, any "scheme://") are rejected
                        by validate(): this project has no cloud AI and
                        no background model downloading.
    model_format      - one of the MODEL_FORMAT_* labels below. A label
                        only: listing a format here does NOT mean any
                        runtime in this project can load it (today none
                        can - see local_model_runtime.py).
    context_length    - total token window (prompt + output) the
                        runtime is allowed to use.
    max_output_tokens - hard cap on generated tokens per request.
    temperature/top_p - default sampling parameters (a request may
                        override them; see inference.GenerationParameters).
    cpu_threads       - None = let the runtime decide, otherwise a
                        positive thread count.
    max_memory_mb     - None = no declared limit, otherwise the memory
                        budget (MiB) the model may occupy. The base
                        runtime uses it for a real, cheap pre-load check
                        (model file size); a concrete runtime may
                        enforce it further.
    timeout_seconds   - default wall-clock limit for one inference.
    enabled           - a configured-but-disabled model is treated as
                        NOT configured (nothing is loaded).

Language capabilities (Prompt 401) - all optional, all DECLARATIONS by
whoever configures the model, never inferred or verified here. None
means unknown (and stays unknown; a model is never reported as
supporting a language it was not declared to support):

    supported_languages - non-empty list of language codes/names the
                          model is declared to support ("fa", "en",
                          "persian", ...).
    supported_scripts   - non-empty list of scripts ("arabic", "latin").
    multilingual        - True/False, or None if unknown.
    default_language    - the model's preferred language; when
                          supported_languages is also declared it must
                          be one of them.

Validation contract: `validate()` returns a `ConfigValidationResult`
listing EVERY problem found (not just the first), each as a short
"field: reason" string. It never raises, even for wrong types
(`temperature="hot"`, `context_length=None`, ...). `from_dict()` is
equally safe: unknown keys are not silently dropped - they are kept and
reported by `validate()`.
"""

import math
import re

from .language_context import canonical_language

MODEL_FORMAT_GGUF = "gguf"
MODEL_FORMAT_ONNX = "onnx"
MODEL_FORMAT_TFLITE = "tflite"
MODEL_FORMAT_OTHER = "other"

ALL_MODEL_FORMATS = (
    MODEL_FORMAT_GGUF, MODEL_FORMAT_ONNX, MODEL_FORMAT_TFLITE, MODEL_FORMAT_OTHER,
)

# Conservative defaults chosen for a phone-class device, not a desktop.
DEFAULT_CONTEXT_LENGTH = 2048
DEFAULT_MAX_OUTPUT_TOKENS = 256
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TOP_P = 0.95
DEFAULT_TIMEOUT_SECONDS = 60.0

# Sanity ceilings (reject obviously-broken values; not a claim about
# what any model supports).
MAX_CONTEXT_LENGTH_CEILING = 131072
MAX_CPU_THREADS_CEILING = 256
MAX_TIMEOUT_SECONDS_CEILING = 3600.0
MAX_TEMPERATURE = 2.0

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

_FIELD_NAMES = (
    "model_id", "model_path", "model_format", "context_length",
    "max_output_tokens", "temperature", "top_p", "cpu_threads",
    "max_memory_mb", "timeout_seconds", "enabled",
    "supported_languages", "supported_scripts", "multilingual", "default_language",
)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


class ConfigValidationResult:
    """`valid` is True exactly when `problems` is empty."""

    def __init__(self, problems=None):
        self.problems = list(problems) if problems else []

    @property
    def valid(self):
        return not self.problems

    def __bool__(self):
        return self.valid

    def __repr__(self):
        return f"ConfigValidationResult(valid={self.valid}, problems={self.problems!r})"

    def to_dict(self):
        return {"valid": self.valid, "problems": list(self.problems)}


class LocalModelConfig:
    def __init__(
        self,
        model_id=None,
        model_path=None,
        model_format=MODEL_FORMAT_GGUF,
        context_length=DEFAULT_CONTEXT_LENGTH,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        temperature=DEFAULT_TEMPERATURE,
        top_p=DEFAULT_TOP_P,
        cpu_threads=None,
        max_memory_mb=None,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        enabled=True,
        supported_languages=None,
        supported_scripts=None,
        multilingual=None,
        default_language=None,
        _unknown_fields=None,
    ):
        self.model_id = model_id
        self.model_path = model_path
        self.model_format = model_format
        self.context_length = context_length
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.cpu_threads = cpu_threads
        self.max_memory_mb = max_memory_mb
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled
        self.supported_languages = supported_languages
        self.supported_scripts = supported_scripts
        self.multilingual = multilingual
        self.default_language = default_language
        self._unknown_fields = list(_unknown_fields) if _unknown_fields else []

    @classmethod
    def from_dict(cls, data):
        """Build a config from a plain dict (e.g. parsed JSON). Never
        raises: a non-dict yields a config that fails `validate()`;
        unknown keys are remembered and reported by `validate()`."""
        if not isinstance(data, dict):
            config = cls()
            config._unknown_fields = ["<config is not a dict>"]
            return config
        known = {k: v for k, v in data.items() if k in _FIELD_NAMES}
        unknown = [str(k) for k in data if k not in _FIELD_NAMES]
        return cls(_unknown_fields=unknown, **known)

    def to_dict(self):
        return {name: getattr(self, name) for name in _FIELD_NAMES}

    def __repr__(self):
        return (
            f"LocalModelConfig(model_id={self.model_id!r}, "
            f"model_format={self.model_format!r}, enabled={self.enabled!r})"
        )

    # ------------------------------------------------------------------
    def validate(self):
        problems = []

        for key in self._unknown_fields:
            problems.append(f"{key}: unknown configuration field")

        if not isinstance(self.model_id, str) or not self.model_id.strip():
            problems.append("model_id: must be a non-empty string")

        if not isinstance(self.enabled, bool):
            problems.append("enabled: must be a bool")

        self._validate_path(problems)

        if self.model_format not in ALL_MODEL_FORMATS:
            problems.append(f"model_format: must be one of {list(ALL_MODEL_FORMATS)}")

        context_ok = _is_int(self.context_length) and \
            1 <= self.context_length <= MAX_CONTEXT_LENGTH_CEILING
        if not context_ok:
            problems.append(
                f"context_length: must be an int between 1 and {MAX_CONTEXT_LENGTH_CEILING}"
            )

        if not _is_int(self.max_output_tokens) or self.max_output_tokens < 1:
            problems.append("max_output_tokens: must be an int >= 1")
        elif context_ok and self.max_output_tokens >= self.context_length:
            problems.append(
                "max_output_tokens: must be smaller than context_length "
                "(the prompt needs room too)"
            )

        if not _is_number(self.temperature) or not 0.0 <= self.temperature <= MAX_TEMPERATURE:
            problems.append(f"temperature: must be a number between 0.0 and {MAX_TEMPERATURE}")

        if not _is_number(self.top_p) or not 0.0 < self.top_p <= 1.0:
            problems.append("top_p: must be a number in (0.0, 1.0]")

        if self.cpu_threads is not None and (
            not _is_int(self.cpu_threads) or not 1 <= self.cpu_threads <= MAX_CPU_THREADS_CEILING
        ):
            problems.append(
                f"cpu_threads: must be None or an int between 1 and {MAX_CPU_THREADS_CEILING}"
            )

        if self.max_memory_mb is not None and (
            not _is_int(self.max_memory_mb) or self.max_memory_mb < 1
        ):
            problems.append("max_memory_mb: must be None or an int >= 1")

        if not _is_number(self.timeout_seconds) or not \
                0.0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS_CEILING:
            problems.append(
                f"timeout_seconds: must be a number in (0, {MAX_TIMEOUT_SECONDS_CEILING}]"
            )

        self._validate_language_capabilities(problems)

        return ConfigValidationResult(problems)

    def _validate_language_capabilities(self, problems):
        for name in ("supported_languages", "supported_scripts"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, (list, tuple)) or not value
                or not all(isinstance(item, str) and item.strip() for item in value)
            ):
                problems.append(
                    f"{name}: must be None (unknown) or a non-empty list of non-empty strings"
                )

        if self.multilingual is not None and not isinstance(self.multilingual, bool):
            problems.append("multilingual: must be None (unknown) or a bool")

        default = self.default_language
        if default is not None:
            if not isinstance(default, str) or canonical_language(default) is None:
                problems.append("default_language: must be None (unknown) or a language code/name")
            elif (isinstance(self.supported_languages, (list, tuple))
                  and self.supported_languages
                  and all(isinstance(item, str) for item in self.supported_languages)):
                declared = {canonical_language(item) for item in self.supported_languages}
                if canonical_language(default) not in declared:
                    problems.append(
                        "default_language: must be one of supported_languages when both are declared"
                    )

    def _validate_path(self, problems):
        path = self.model_path
        if path is None or (isinstance(path, str) and not path.strip()):
            # A disabled config may legitimately have no path yet.
            if self.enabled is not False:
                problems.append("model_path: required when the model is enabled")
            return
        if not isinstance(path, str):
            problems.append("model_path: must be a string")
            return
        if "\x00" in path:
            problems.append("model_path: must not contain NUL characters")
        elif _SCHEME_RE.match(path.strip()):
            problems.append(
                "model_path: must be a LOCAL path; remote locations are not "
                "supported (no cloud AI, no model downloading)"
            )
