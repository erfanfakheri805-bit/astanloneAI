"""
Test support (Prompt 958): a fake MediaPipe LLM engine for `model_runtime.mediapipe_runtime` (not a test module itself).

`state["gate"] = threading.Event()` (set by a test AFTER the model was prepared) makes every later answer wait for that event, which is how
the "busy" and "too slow" paths are exercised; `state["delay_calls"]` counts the calls that waited.

`with_llm_engine(jvm, answers=...)` puts hand-written stand-ins for `LlmInference` and `LlmInference$LlmInferenceOptions` into a `FakeJava`.
They record what the adapter calls (model path, token window, top-k, the prompts) and answer from a script, so the ADAPTER's logic can be
tested without a phone. It follows Google's documented Java API; it proves nothing about how the real engine behaves on a device.
"""

from model_runtime.mediapipe_runtime import LLM_CLASS, OPTIONS_CLASS

import threading

__all__ = ["with_llm_engine", "LLM_CLASS", "OPTIONS_CLASS"]


def with_llm_engine(jvm, answers=("سلام! من یک مدل آزمایشی هستم.",), load_error=None, generate_error=None):
    """Add the fake engine classes to `jvm` (a `FakeJava`) and return the recording state."""
    state = {"created": [], "prompts": [], "closed": 0, "answers": list(answers), "options": [], "gate": None, "delay_calls": 0}

    class Engine:
        def __init__(self, options):
            self.options = options

        def generateResponse(self, prompt):
            state["prompts"].append(prompt)
            gate = state["gate"]
            if gate is not None:
                state["delay_calls"] += 1
                gate.wait(20)
            if generate_error is not None:
                raise generate_error
            answers_left = state["answers"]
            if not answers_left:
                return ""
            return answers_left.pop(0) if len(answers_left) > 1 else answers_left[0]

        def close(self):
            state["closed"] += 1

    class Builder:
        def __init__(self):
            self.values = {}

        def setModelPath(self, path):
            self.values["model_path"] = path
            return self

        def setMaxTokens(self, count):
            self.values["max_tokens"] = count
            return self

        def setMaxTopK(self, count):
            self.values["top_k"] = count
            return self

        def build(self):
            state["options"].append(dict(self.values))
            return dict(self.values)

    class Options:
        @staticmethod
        def builder():
            return Builder()

    class LlmInference:
        @staticmethod
        def createFromOptions(context, options):
            if load_error is not None:
                raise load_error
            engine = Engine(options)
            state["created"].append((context, options))
            return engine

    jvm.classes[LLM_CLASS] = LlmInference
    jvm.classes[OPTIONS_CLASS] = Options
    return state
