"""
Prompt 958 - the on-device language-model engine adapter (`MediaPipeLlmRuntime`) against a fake MediaPipe.

Proven: it reports exactly why it is unavailable (not on Android / the APK was built without the engine), it passes the documented
options to the engine, it never lets an engine error escape as anything but a stable code, it cuts an answer to the token budget, it
closes the engine on unload - and the whole model lifecycle of 957 (card, local import, hash check, load, smoke test, generate) runs
through it. NOT proven: how the real engine behaves on a real phone with a real Gemma file.
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_runtime import LlamaCppRuntime, MediaPipeLlmRuntime, ModelManager, NgramRuntime, parse_card
from model_runtime.card import LOCAL_IMPORT, license_policy
from model_runtime.mediapipe_runtime import CHARS_PER_TOKEN, ENGINE_CONTEXT_TOKENS, _cut
from model_runtime.runtimes import LoadedModel, RuntimeGenerateError, RuntimeLoadError
from native_bridge.jvm import NullJava
from tests.llm_support_prompt958 import LLM_CLASS, with_llm_engine
from tests.native_support_prompt958 import FakeJava


def card_for(path, model_id="gemma-test", license_name="apache-2.0"):
    with open(path, "rb") as handle:
        data = handle.read()
    return {"model_id": model_id, "title": "Gemma آزمایشی", "version": "1", "format": "task", "source_url": LOCAL_IMPORT,
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "license": license_name, "languages": ["fa", "en"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mp_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.model = os.path.join(self.tmp, "gemma.task")
        with open(self.model, "wb") as handle:
            handle.write(b"PK\x03\x04 pretend this is a task bundle " * 40)
        self.jvm = FakeJava(installed=set())
        self.engine = with_llm_engine(self.jvm)
        self.runtime = MediaPipeLlmRuntime(jvm_provider=lambda: self.jvm)
        self.card = parse_card(card_for(self.model))


class AvailabilityTests(Base):
    def test_it_is_a_registered_default_engine_for_the_task_format(self):
        from model_runtime import default_runtimes
        names = {r.name: r for r in default_runtimes()}
        self.assertEqual(names["mediapipe_llm"].formats, ("task",))
        self.assertEqual(self.runtime.formats, ("task",))

    def test_with_the_engine_in_the_apk_it_is_available(self):
        availability = self.runtime.availability()
        self.assertTrue(availability.available, availability)
        self.assertEqual(availability.code, "ok")

    def test_not_on_android_it_says_so(self):
        runtime = MediaPipeLlmRuntime(jvm_provider=NullJava)
        availability = runtime.availability()
        self.assertFalse(availability.available)
        self.assertEqual(availability.code, "unavailable_platform")
        self.assertIn("tasks-genai", availability.requires[0])

    def test_an_apk_built_without_the_engine_says_the_dependency_is_missing(self):
        del self.jvm.classes[LLM_CLASS]
        availability = self.runtime.availability()
        self.assertFalse(availability.available)
        self.assertEqual(availability.code, "dependency_missing")
        self.assertIn("MediaPipe", availability.reason_fa)

    def test_loading_without_the_engine_is_refused_with_a_stable_code(self):
        del self.jvm.classes[LLM_CLASS]
        with self.assertRaises(RuntimeLoadError) as caught:
            self.runtime.load(self.model, self.card)
        self.assertEqual(caught.exception.code, "dependency_missing")

    def test_the_default_provider_goes_through_the_native_bridge(self):
        # no jvm_provider: the real facade is used, and in this test process there is no Android
        from native_bridge import facade
        facade.reset_for_tests()
        self.addCleanup(facade.reset_for_tests)
        self.assertEqual(MediaPipeLlmRuntime().availability().code, "unavailable_platform")


class LoadAndGenerateTests(Base):
    def test_load_passes_the_documented_options_and_the_app_context(self):
        loaded = self.runtime.load(self.model, self.card)
        self.assertEqual(loaded.runtime, "mediapipe_llm")
        self.assertEqual(self.engine["options"], [{"model_path": self.model, "max_tokens": ENGINE_CONTEXT_TOKENS, "top_k": 40}])
        self.assertIs(self.engine["created"][0][0], self.jvm.context())

    def test_generate_returns_the_engine_text_and_passes_the_prompt_unchanged(self):
        loaded = self.runtime.load(self.model, self.card)
        self.assertEqual(self.runtime.generate(loaded, "سلام", max_tokens=64, seed=0), "سلام! من یک مدل آزمایشی هستم.")
        self.assertEqual(self.engine["prompts"], ["سلام"])

    def test_an_answer_is_cut_to_the_token_budget_at_a_word_boundary(self):
        text = "کلمه " * 200
        self.engine["answers"][:] = [text]
        loaded = self.runtime.load(self.model, self.card)
        out = self.runtime.generate(loaded, "x", max_tokens=10, seed=0)
        self.assertLessEqual(len(out), 10 * CHARS_PER_TOKEN)
        self.assertTrue(out.endswith("کلمه"), out)
        self.assertEqual(_cut("کوتاه", 10), "کوتاه")

    def test_a_missing_or_linked_model_file_is_refused_before_the_engine_sees_it(self):
        with self.assertRaises(RuntimeLoadError) as caught:
            self.runtime.load(os.path.join(self.tmp, "nope.task"), self.card)
        self.assertEqual(caught.exception.code, "model_file_invalid")
        link = os.path.join(self.tmp, "link.task")
        os.symlink(self.model, link)
        with self.assertRaises(RuntimeLoadError):
            self.runtime.load(link, self.card)
        self.assertEqual(self.engine["created"], [])

    def test_an_engine_failure_while_loading_names_only_the_exception_type(self):
        self.engine = with_llm_engine(self.jvm, load_error=RuntimeError("secret model path /data/x"))
        with self.assertRaises(RuntimeLoadError) as caught:
            self.runtime.load(self.model, self.card)
        self.assertEqual(caught.exception.code, "engine_load_failed")
        self.assertEqual(caught.exception.detail, "RuntimeError")
        self.assertNotIn("secret", str(caught.exception))

    def test_an_engine_failure_while_generating_is_a_stable_code(self):
        loaded = self.runtime.load(self.model, self.card)
        self.engine_failing = with_llm_engine(self.jvm, generate_error=ValueError("boom"))
        loaded2 = MediaPipeLlmRuntime(jvm_provider=lambda: self.jvm).load(self.model, self.card)
        with self.assertRaises(RuntimeGenerateError) as caught:
            self.runtime.generate(loaded2, "x", max_tokens=8, seed=0)
        self.assertEqual(caught.exception.code, "engine_generate_failed")
        self.assertEqual(caught.exception.detail, "ValueError")
        self.assertIsNotNone(loaded)

    def test_generating_with_nothing_loaded_is_refused(self):
        with self.assertRaises(RuntimeGenerateError) as caught:
            self.runtime.generate(LoadedModel("m", "mediapipe_llm", None, "x"), "x", max_tokens=8, seed=0)
        self.assertEqual(caught.exception.code, "not_loaded")

    def test_the_smoke_test_needs_real_text(self):
        loaded = self.runtime.load(self.model, self.card)
        self.assertTrue(self.runtime.smoke_test(loaded).ok)
        self.engine["answers"][:] = ["   "]
        report = self.runtime.smoke_test(loaded)
        self.assertFalse(report.ok)
        self.assertEqual(report.details, "empty_output")

    def test_unload_closes_the_engine_once(self):
        loaded = self.runtime.load(self.model, self.card)
        self.runtime.unload(loaded)
        self.assertEqual(self.engine["closed"], 1)
        self.assertIsNone(loaded.handle)
        self.runtime.unload(loaded)
        self.assertEqual(self.engine["closed"], 1)


class LifecycleThroughTheManagerTests(Base):
    def setUp(self):
        super().setUp()
        self.manager = ModelManager(os.path.join(self.tmp, "models"), runtimes=[NgramRuntime(), LlamaCppRuntime(spec_finder=lambda n: None), self.runtime],
                                    free_space_fn=lambda path: type("U", (), {"free": 10 ** 12, "total": 10 ** 12, "used": 0})())

    def test_a_file_the_user_chose_becomes_usable_only_after_every_real_check(self):
        status = self.manager.register(card_for(self.model))
        self.assertTrue(status.ok, status)
        self.assertFalse(self.manager.is_usable("gemma-test"))
        self.assertTrue(self.manager.import_local_file("gemma-test", self.model).ok)
        self.assertEqual(self.engine["created"], [])                    # nothing is loaded by an import
        report = self.manager.prepare("gemma-test")
        self.assertTrue(report.ok, report)
        self.assertEqual([s.stage for s in report.stages], ["verify", "compatibility", "load", "smoke"])
        self.assertTrue(self.manager.is_usable("gemma-test"))
        result = self.manager.generate("gemma-test", "سلام", max_tokens=32)
        self.assertTrue(result.ok, result)
        self.assertEqual(result.runtime, "mediapipe_llm")
        self.assertIn("مدل آزمایشی", result.text)

    def test_a_flipped_byte_is_caught_before_the_engine_ever_loads_it(self):
        self.manager.register(card_for(self.model))
        self.manager.import_local_file("gemma-test", self.model)
        target = self.manager.model_path("gemma-test")
        with open(target, "r+b") as handle:
            handle.seek(10)
            handle.write(b"\x00")
        report = self.manager.prepare("gemma-test")
        self.assertFalse(report.ok)
        self.assertEqual(self.engine["created"], [])

    def test_without_the_engine_the_pipeline_stops_at_compatibility_with_the_reason(self):
        del self.jvm.classes[LLM_CLASS]
        self.manager.register(card_for(self.model))
        self.manager.import_local_file("gemma-test", self.model)
        report = self.manager.prepare("gemma-test")
        self.assertFalse(report.ok)
        self.assertEqual(report.stages[-1].stage, "compatibility")
        self.assertEqual(report.stages[-1].code, "dependency_missing")

    def test_an_unrecognised_licence_needs_the_users_own_acknowledgement(self):
        self.assertEqual(license_policy("user-supplied"), "needs_review")
        self.manager.register(card_for(self.model, license_name="user-supplied"))
        self.manager.import_local_file("gemma-test", self.model)
        report = self.manager.prepare("gemma-test")
        self.assertFalse(report.ok)
        self.assertEqual(report.stages[-1].code, "license_needs_ack")
        self.assertTrue(self.manager.acknowledge_license("gemma-test").ok)
        self.assertTrue(self.manager.prepare("gemma-test").ok)


if __name__ == "__main__":
    unittest.main()
