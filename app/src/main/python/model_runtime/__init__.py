"""
model_runtime - truthful local-model management (Prompt 957)
============================================================
A model file is never "usable" because it exists. It becomes usable only after
its size and SHA-256 match its card, its licence and engine are compatible, an
engine REALLY loaded it and a REAL inference smoke test passed. Downloads need
explicit approval, the network permission and a verified hash. No external AI
service, API or key is involved anywhere.

    ModelManager(root, ...).register(card) / download / import_local_file / prepare / generate
    NgramRuntime  - a small statistical n-gram model (NOT an LLM), always available
    LlamaCppRuntime - GGUF through the `llama_cpp` package, only when really installed

`model_runtime.bridge` (imported explicitly, because it needs `language_intelligence`)
adapts a managed model to the existing `LocalModelRuntime` contract.
"""

from .card import CardError, ModelCard, license_policy, parse_card
from .manager import (GenerationResult, ModelManager, ModelStatus, PipelineReport, StageReport, TRANSITIONS,
                      default_downloader, transition_allowed)
from .ngram import NgramModel, NgramModelError, load_ngram_model, tokenize, train_ngram_model
from .runtimes import (InferenceRuntime, LlamaCppRuntime, LoadedModel, NgramRuntime, RuntimeAvailability, SmokeReport,
                       default_runtimes)
from .store import STATES, ModelStore

__all__ = [
    "CardError", "ModelCard", "license_policy", "parse_card", "GenerationResult", "ModelManager", "ModelStatus",
    "PipelineReport", "StageReport", "TRANSITIONS", "default_downloader", "transition_allowed", "NgramModel",
    "NgramModelError", "load_ngram_model", "tokenize", "train_ngram_model", "InferenceRuntime", "LlamaCppRuntime",
    "LoadedModel", "NgramRuntime", "RuntimeAvailability", "SmokeReport", "default_runtimes", "STATES", "ModelStore",
]
