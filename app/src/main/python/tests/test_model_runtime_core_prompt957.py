"""Prompt 957 - model_runtime: model cards, the n-gram model and its STRICT loader, engines, the registry store."""
import copy
import json
import os
import pickle
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_runtime import (CardError, LlamaCppRuntime, ModelStore, NgramModelError, NgramRuntime, STATES, license_policy,
                           load_ngram_model, parse_card, tokenize, train_ngram_model)
from model_runtime import ngram as ngram_module
from model_runtime.ngram import detokenize
from model_runtime.runtimes import LoadedModel, RuntimeGenerateError, RuntimeLoadError
from model_runtime.store import RegistryProblem, validate_entry

SHA = "a" * 64
TEXTS = ["سلام دوست من. امروز هوا خیلی خوب است.", "من به مدرسه می‌روم و کتاب می‌خوانم.", "سلام، حال شما چطور است؟",
         "امروز هوا خوب است و من خوشحالم.", "کتاب خوب دوست خوب است."]


def card_dict(**over):
    data = dict(model_id="fa-ngram", title="مدل آزمایشی", version="1.0", format="ngram-json",
                source_url="https://models.example.org/fa-ngram.json", sha256=SHA, size_bytes=1000, license="mit")
    data.update(over)
    return data


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def gguf_file(directory, data=b"GGUF" + bytes(range(64)), name="m.gguf"):
    path = os.path.join(directory, name)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


class CardTests(unittest.TestCase):
    def test_valid_card_and_defaults(self):
        card = parse_card(card_dict(sha256="A" * 64))
        self.assertEqual((card.model_id, card.format, card.sha256), ("fa-ngram", "ngram-json", "a" * 64))
        self.assertEqual((card.languages, card.runtime_hint, card.min_free_mb, card.notes), ((), "", 0, ""))
        full = parse_card(card_dict(languages=["fa", "en-US"], runtime_hint="ngram", min_free_mb=50, notes="n"))
        self.assertEqual(parse_card(full.to_dict()), full)
        self.assertEqual(parse_card(card_dict(source_url="local-import")).source_url, "local-import")

    def test_rejections(self):
        bad = {
            "unknown key": dict(extra=1), "missing id": None, "id upper": dict(model_id="Fa"), "id short": dict(model_id="a"),
            "id dash": dict(model_id="-ab"), "id long": dict(model_id="a" * 65), "id slash": dict(model_id="a/b"),
            "version": dict(version="1 0"), "version empty": dict(version=""), "format": dict(format="pickle"),
            "format safetensors": dict(format="safetensors"), "http": dict(source_url="http://models.example.org/x"),
            "ftp": dict(source_url="ftp://models.example.org/x"), "file": dict(source_url="file:///etc/passwd"),
            "private": dict(source_url="https://192.168.1.5/x"), "localhost": dict(source_url="https://localhost/x"),
            "userinfo": dict(source_url="https://u:p@models.example.org/x"), "no url": dict(source_url=""),
            "url type": dict(source_url=5), "sha short": dict(sha256="a" * 63), "sha chars": dict(sha256="g" * 64),
            "size zero": dict(size_bytes=0), "size neg": dict(size_bytes=-1), "size bool": dict(size_bytes=True),
            "size float": dict(size_bytes=1.5), "size huge": dict(size_bytes=9 * 2 ** 30), "license empty": dict(license=""),
            "license long": dict(license="x" * 65), "title empty": dict(title=" "), "title ctrl": dict(title="a\nb"),
            "languages str": dict(languages="fa"), "languages bad": dict(languages=["fa", "not a tag!"]),
            "languages many": dict(languages=["fa"] * 9), "hint": dict(runtime_hint="a b"), "min_free": dict(min_free_mb=-1),
            "notes long": dict(notes="x" * 501),
        }
        for name, override in bad.items():
            with self.subTest(case=name):
                data = card_dict(**(override or {}))
                if override is None:
                    del data["model_id"]
                with self.assertRaises(CardError):
                    parse_card(data)

    def test_non_dict_inputs(self):
        class D(dict):
            pass
        for value in (None, [], "card", 5, D(card_dict())):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(CardError):
                    parse_card(value)

    def test_license_policy(self):
        table = {"mit": "permissive", "Apache-2.0": "permissive", " BSD-3-Clause ": "permissive", "cc0-1.0": "permissive",
                 "cc-by-sa-4.0": "needs_review", "gpl-3.0": "needs_review", "AGPL-3.0": "needs_review",
                 "llama3-community": "needs_review", "gemma": "needs_review", "openrail++": "needs_review",
                 "research-only": "needs_review", "proprietary": "restricted", "non-commercial": "restricted",
                 "cc-by-nc-4.0": "restricted", "": "unknown", "my-own": "unknown", None: "unknown", 5: "unknown"}
        for name, expected in table.items():
            with self.subTest(license=name):
                self.assertEqual(license_policy(name), expected)


class TokenizerTests(unittest.TestCase):
    def test_persian_words_zwnj_and_punctuation(self):
        self.assertEqual(tokenize("می‌روم؟ بله، حتماً!"), ["می‌روم", "؟", "بله", "،", "حتماً", "!"])

    def test_nfc_and_case_and_special_tokens_cannot_be_forged(self):
        self.assertEqual(tokenize("é"), ["é"])
        self.assertEqual(tokenize("Hello WORLD"), ["hello", "world"])
        self.assertNotIn("<s>", tokenize("<s> </s> <unk>"))
        self.assertEqual(tokenize(""), [])
        self.assertEqual(max(len(t) for t in tokenize("ا" * 500)), 64)

    def test_detokenize_spacing(self):
        self.assertEqual(detokenize(["سلام", "،", "دنیا", "!"]), "سلام، دنیا!")
        self.assertEqual(detokenize(["«", "سلام", "»"]), "«سلام»")


class TrainingTests(unittest.TestCase):
    def test_training_is_deterministic_and_canonical(self):
        a, b = train_ngram_model(TEXTS, order=3), train_ngram_model(list(TEXTS), order=3)
        self.assertEqual(a, b)
        payload = json.loads(a)
        self.assertEqual((payload["schema"], payload["order"]), ("ngram-json/1", 3))
        self.assertEqual(payload["vocab"][:3], ["<s>", "</s>", "<unk>"])
        self.assertEqual(a, json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        self.assertNotEqual(a, train_ngram_model(TEXTS, order=2))

    def test_argument_validation(self):
        for kwargs in ({"order": 1}, {"order": 6}, {"order": True}, {"order": "3"}, {"max_vocab": 8}, {"max_vocab": 10 ** 6},
                       {"max_vocab": True}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    train_ngram_model(TEXTS, **kwargs)
        for texts in ([], [""], ["   ", "\n"], [5], [None]):
            with self.subTest(texts=texts):
                with self.assertRaises(ValueError):
                    train_ngram_model(texts)
        with mock.patch.object(ngram_module, "MAX_TRAIN_CHARS", 50):
            with self.assertRaises(ValueError):
                train_ngram_model(TEXTS)

    def test_vocabulary_is_capped_and_rare_words_become_unknown(self):
        words = ["w%d" % i for i in range(100)]
        model = load_ngram_model(train_ngram_model([" ".join(words)], order=2, max_vocab=20))
        self.assertEqual(len(model.vocab), 20)
        self.assertEqual(len(model.vocabulary()), 17)


class GenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_ngram_model(train_ngram_model(TEXTS, order=3))

    def test_same_prompt_and_seed_give_the_same_text_and_seeds_matter(self):
        first = self.model.generate("سلام", 20, seed=0)
        self.assertEqual(first, self.model.generate("سلام", 20, seed=0))
        self.assertTrue(first.strip())
        outputs = {self.model.generate("امروز", 20, seed=s) for s in range(40)}
        self.assertGreater(len(outputs), 1)

    def test_output_only_uses_vocabulary_tokens_and_respects_max_tokens(self):
        allowed = self.model.vocabulary()
        for seed in range(30):
            text = self.model.generate("امروز هوا", 6, seed=seed)
            tokens = tokenize(text)
            self.assertLessEqual(len(tokens), 6)
            self.assertTrue(all(t in allowed for t in tokens), tokens)
            self.assertNotIn("<unk>", text)
        self.assertEqual(len(tokenize(self.model.generate("سلام", 1, seed=3))), 1)

    def test_unknown_prompt_words_back_off_instead_of_failing(self):
        text = self.model.generate("qqqq zzzz ناشناخته", 8, seed=1)
        self.assertIsInstance(text, str)
        self.assertTrue(text.strip())

    def test_a_finished_sentence_starts_a_new_one(self):
        self.assertTrue(self.model.generate("سلام.", 8, seed=0).strip())
        self.assertTrue(self.model.generate("", 8, seed=0).strip())

    def test_bad_arguments(self):
        for prompt, tokens in ((5, 5), ("a", 0), ("a", 513), ("a", True), ("a", "5")):
            with self.subTest(prompt=prompt, tokens=tokens):
                with self.assertRaises(ValueError):
                    self.model.generate(prompt, tokens)


class StrictLoaderTests(unittest.TestCase):
    @staticmethod
    def payload():
        return json.loads(train_ngram_model(TEXTS, order=3))

    @staticmethod
    def encode(obj):
        return json.dumps(obj, ensure_ascii=False).encode("utf-8")

    def rejected(self, data, code=None):
        with self.assertRaises(NgramModelError) as ctx:
            load_ngram_model(data)
        if code:
            self.assertEqual(ctx.exception.code, code)

    def test_a_valid_model_loads(self):
        model = load_ngram_model(self.encode(self.payload()))
        self.assertEqual(model.order, 3)

    def test_wrong_inputs_and_encodings(self):
        for data in (None, "text", 5, [], pickle.dumps({"schema": "ngram-json/1"}), b"", b"\xff\xfe\x00", b"{", b"[]", b"null",
                     b'"x"', b"{}"):
            with self.subTest(data=repr(data)[:30]):
                self.rejected(data)

    def test_size_and_depth_limits(self):
        valid = self.encode(self.payload())
        with mock.patch.object(ngram_module, "MAX_MODEL_BYTES", len(valid) - 1):
            self.rejected(valid, "too_large")
        self.rejected(b"[" * 200 + b"]" * 200, "too_deep")
        self.rejected(b'{"a":' * 50 + b"1" + b"}" * 50, "too_deep")
        nested = self.payload()
        nested["contexts"][0][0] = [[[[[1]]]]]
        self.rejected(self.encode(nested))

    def test_numbers_and_duplicate_keys(self):
        valid = self.encode(self.payload()).decode("utf-8")
        for bad, code in (("NaN", "bad_number"), ("Infinity", "bad_number"), ("-Infinity", "bad_number")):
            with self.subTest(bad=bad):
                self.rejected(valid.replace('"order": 3', '"order": %s' % bad).encode(), code)
        self.rejected(valid.replace('"order": 3', '"order": 3.0').encode(), "bad_number")
        self.rejected(valid.replace('"order": 3', '"order": 1e0').encode(), "bad_number")
        self.rejected(valid.replace('"order": 3', '"order": 3, "order": 4').encode(), "duplicate_key")
        self.rejected(('{"schema":"ngram-json/1","order":3,"order":2,"vocab":[],"contexts":[]}').encode(), "duplicate_key")

    def test_structural_mutations_are_all_refused(self):
        def mutate(fn):
            data = self.payload()
            fn(data)
            return self.encode(data)
        cases = {
            "extra key": lambda d: d.update(extra=1), "missing key": lambda d: d.pop("order"),
            "schema": lambda d: d.update(schema="ngram-json/2"), "schema type": lambda d: d.update(schema=1),
            "order low": lambda d: d.update(order=1), "order high": lambda d: d.update(order=6),
            "order bool": lambda d: d.update(order=True), "order str": lambda d: d.update(order="3"),
            "vocab type": lambda d: d.update(vocab="abc"), "vocab specials": lambda d: d["vocab"].__setitem__(0, "x"),
            "vocab short": lambda d: d.update(vocab=["<s>", "</s>"]), "vocab empty token": lambda d: d["vocab"].append(""),
            "vocab int token": lambda d: d["vocab"].append(5), "vocab long token": lambda d: d["vocab"].append("x" * 65),
            "vocab control": lambda d: d["vocab"].append("a\x07"), "vocab dup": lambda d: d["vocab"].append(d["vocab"][5]),
            "contexts type": lambda d: d.update(contexts={}), "contexts empty": lambda d: d.update(contexts=[]),
            "row type": lambda d: d["contexts"].append("x"), "row len": lambda d: d["contexts"].append([[], [[1, 1]], 3]),
            "ctx id range": lambda d: d["contexts"][1][0].__setitem__(0, 10 ** 6),
            "ctx id negative": lambda d: d["contexts"][1][0].__setitem__(0, -1),
            "ctx id bool": lambda d: d["contexts"][1][0].__setitem__(0, True),
            "ctx too long": lambda d: d["contexts"].append([[1, 1, 1], [[1, 1]]]),
            "next empty": lambda d: d["contexts"].append([[2], []]),
            "next too many": lambda d: d["contexts"].append([[2, 2], [[i % 3 + 3, 1] for i in range(65)]]),
            "next pair type": lambda d: d["contexts"][0][1].append("x"),
            "next id range": lambda d: d["contexts"][0][1].append([10 ** 6, 1]),
            "count zero": lambda d: d["contexts"][0][1].append([3, 0]),
            "count negative": lambda d: d["contexts"][0][1].append([3, -5]),
            "count huge": lambda d: d["contexts"][0][1].append([3, 10 ** 10]),
            "count bool": lambda d: d["contexts"][0][1].append([3, True]),
            "dup context": lambda d: d["contexts"].append(copy.deepcopy(d["contexts"][1])),
            "no unigram": lambda d: d.update(contexts=[row for row in d["contexts"] if row[0]]),
        }
        for name, fn in cases.items():
            with self.subTest(case=name):
                self.rejected(mutate(fn))

    def test_total_entry_limit(self):
        with mock.patch.object(ngram_module, "MAX_ENTRIES", 5):
            self.rejected(self.encode(self.payload()), "too_large")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.card = parse_card(card_dict())

    def write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_ngram_runtime_loads_generates_and_passes_its_smoke_test(self):
        runtime = NgramRuntime()
        self.assertTrue(runtime.availability().available)
        self.assertIn("LLM", runtime.description_en)
        self.assertIn("n-gram", runtime.description_fa)
        loaded = runtime.load(self.write("m.json", train_ngram_model(TEXTS)), self.card)
        report = runtime.smoke_test(loaded)
        self.assertTrue(report.ok, report)
        self.assertTrue(report.output_excerpt)
        self.assertTrue(runtime.generate(loaded, "سلام", max_tokens=5, seed=2).strip())
        runtime.unload(loaded)
        with self.assertRaises(RuntimeGenerateError):
            runtime.generate(loaded, "سلام", max_tokens=5, seed=0)

    def test_ngram_runtime_refuses_bad_files(self):
        runtime = NgramRuntime()
        os.symlink(self.write("real.json", train_ngram_model(TEXTS)), os.path.join(self.dir, "link.json"))
        for name, path in (("missing", os.path.join(self.dir, "nope")), ("dir", self.dir), ("symlink", os.path.join(self.dir, "link.json")),
                           ("garbage", self.write("g.json", b"not json")), ("pickle", self.write("p.json", pickle.dumps([1])))):
            with self.subTest(case=name):
                with self.assertRaises(RuntimeLoadError):
                    runtime.load(path, self.card)
        with mock.patch("model_runtime.runtimes.MAX_MODEL_BYTES", 10):
            with self.assertRaises(RuntimeLoadError):
                runtime.load(self.write("big.json", train_ngram_model(TEXTS)), self.card)

    def test_ngram_smoke_test_fails_for_a_useless_or_unstable_model(self):
        runtime = NgramRuntime()
        empty = load_ngram_model(train_ngram_model(["a"], order=2))
        loaded = LoadedModel("m", "ngram", empty, "")
        self.assertTrue(runtime.smoke_test(loaded).ok)  # one-word vocabulary still produces its word
        only_specials = json.dumps({"schema": "ngram-json/1", "order": 2, "vocab": ["<s>", "</s>", "<unk>"],
                                    "contexts": [[[], [[1, 1]]]]}).encode()
        self.assertFalse(runtime.smoke_test(LoadedModel("m", "ngram", load_ngram_model(only_specials), "")).ok)

        class Flaky:
            vocab = ["<s>", "</s>", "<unk>", "x"]
            calls = 0

            def generate(self, prompt, max_tokens, seed):
                Flaky.calls += 1
                return "x" * Flaky.calls

            def vocabulary(self):
                return frozenset({"x"})
        with mock.patch("model_runtime.runtimes.NgramModel", Flaky):
            report = runtime.smoke_test(LoadedModel("m", "ngram", Flaky(), ""))
        self.assertEqual((report.ok, report.details), (False, "not_deterministic"))

    def test_ngram_smoke_test_rejects_empty_output_and_words_the_model_never_learned(self):
        runtime = NgramRuntime()

        class Scripted:
            vocab = ["<s>", "</s>", "<unk>", "x"]

            def __init__(self, text):
                self.text = text

            def generate(self, prompt, max_tokens, seed):
                return self.text

            def vocabulary(self):
                return frozenset({"x"})
        for text, details in (("   ", "empty_output"), ("", "empty_output"), ("x intruder", "output_outside_vocabulary")):
            with self.subTest(text=text):
                with mock.patch("model_runtime.runtimes.NgramModel", Scripted):
                    report = runtime.smoke_test(LoadedModel("m", "ngram", Scripted(text), ""))
                self.assertEqual((report.ok, report.details), (False, details))
        with mock.patch("model_runtime.runtimes.NgramModel", Scripted):
            self.assertTrue(runtime.smoke_test(LoadedModel("m", "ngram", Scripted("x x"), "")).ok)

    def test_llama_cpp_is_unavailable_without_the_package_and_says_exactly_what_is_missing(self):
        runtime = LlamaCppRuntime(spec_finder=lambda name: None)
        availability = runtime.availability()
        self.assertEqual((availability.available, availability.code), (False, "dependency_missing"))
        self.assertTrue(any("llama_cpp" in item for item in availability.requires))
        gguf = parse_card(card_dict(format="gguf"))
        with self.assertRaises(RuntimeLoadError) as ctx:
            runtime.load("/x.gguf", gguf)
        self.assertEqual(ctx.exception.code, "dependency_missing")
        for finder in (lambda n: (_ for _ in ()).throw(ValueError("x")), lambda n: (_ for _ in ()).throw(ImportError("x"))):
            self.assertFalse(LlamaCppRuntime(spec_finder=finder).availability().available)
        import importlib.util
        if importlib.util.find_spec("llama_cpp") is None:
            self.assertFalse(LlamaCppRuntime().availability().available)

    def test_llama_cpp_with_a_fake_package(self):
        calls = {}

        class Llama:
            def __init__(self, **kwargs):
                calls["init"] = kwargs

            def __call__(self, prompt, **kwargs):
                calls["call"] = (prompt, kwargs)
                return {"choices": [{"text": " سلام دنیا"}]}

        class Module:
            pass
        Module.Llama = Llama
        runtime = LlamaCppRuntime(module_loader=lambda name: Module, spec_finder=lambda name: object())
        self.assertTrue(runtime.availability().available)
        gguf = parse_card(card_dict(format="gguf"))
        with tempfile.TemporaryDirectory() as tmp:
            path = gguf_file(tmp)
            loaded = runtime.load(path, gguf)
        self.assertEqual(calls["init"]["model_path"], path)
        self.assertEqual((calls["init"]["n_ctx"], calls["init"]["verbose"]), (2048, False))
        self.assertLessEqual(calls["init"]["n_threads"], 4)
        self.assertEqual(runtime.generate(loaded, "سلام", max_tokens=7, seed=3), " سلام دنیا")
        self.assertEqual(calls["call"], ("سلام", {"max_tokens": 7, "temperature": 0.0, "seed": 3}))
        report = runtime.smoke_test(loaded)
        self.assertEqual((report.ok, calls["call"][1]["max_tokens"]), (True, 8))

    def test_llama_cpp_refuses_files_that_are_not_gguf_before_the_engine_sees_them(self):
        touched = []

        class Module:
            @staticmethod
            def Llama(**kwargs):
                touched.append(kwargs)

        runtime = LlamaCppRuntime(module_loader=lambda n: Module, spec_finder=lambda n: object())
        card = parse_card(card_dict(format="gguf"))
        with tempfile.TemporaryDirectory() as tmp:
            cases = {
                "wrong magic": gguf_file(tmp, b"NOPE" + bytes(64), "a.gguf"),
                "empty": gguf_file(tmp, b"", "b.gguf"),
                "short": gguf_file(tmp, b"GGU", "c.gguf"),
                "directory": tmp,
                "missing": os.path.join(tmp, "absent.gguf"),
            }
            link = os.path.join(tmp, "link.gguf")
            os.symlink(gguf_file(tmp, name="real.gguf"), link)
            cases["symlink"] = link
            for label, path in cases.items():
                with self.subTest(label):
                    with self.assertRaises(RuntimeLoadError) as ctx:
                        runtime.load(path, card)
                    self.assertEqual(ctx.exception.code, "model_file_invalid")
        self.assertEqual(touched, [])

    def test_llama_cpp_failures_report_only_the_exception_type(self):
        class Boom:
            def __init__(self, **kwargs):
                raise RuntimeError("secret path /data/x")

        class Module:
            Llama = Boom
        runtime = LlamaCppRuntime(module_loader=lambda n: Module, spec_finder=lambda n: object())
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeLoadError) as ctx:
                runtime.load(gguf_file(tmp), parse_card(card_dict(format="gguf")))
        self.assertEqual((ctx.exception.code, ctx.exception.detail), ("engine_load_failed", "RuntimeError"))
        self.assertNotIn("secret", str(ctx.exception))
        for output in ({}, {"choices": []}, {"choices": [{"text": 5}]}, None, "x"):
            engine = lambda prompt, **kw: output  # noqa: E731
            with self.subTest(output=output):
                with self.assertRaises(RuntimeGenerateError):
                    runtime.generate(LoadedModel("m", "llama_cpp", engine, ""), "x", max_tokens=1, seed=0)
        empty = LoadedModel("m", "llama_cpp", lambda prompt, **kw: {"choices": [{"text": "  "}]}, "")
        self.assertFalse(runtime.smoke_test(empty).ok)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.join(self._tmp.name, "models")

    @staticmethod
    def entry(**over):
        card = parse_card(card_dict())
        data = {"card": card.to_dict(), "state": "registered", "origin": "user", "license_ack": False, "reasons": [], "stage": "",
                "file": None, "smoke": None, "registered_at": 1.0, "updated_at": 1.0}
        data.update(over)
        return data

    def test_constructing_a_store_touches_nothing(self):
        ModelStore(self.root)
        self.assertFalse(os.path.exists(self.root))
        self.assertEqual(ModelStore(self.root).load(), ({}, None))

    def test_round_trip(self):
        store = ModelStore(self.root)
        store.save({"fa-ngram": validate_entry("fa-ngram", self.entry())})
        models, recovery = ModelStore(self.root).load()
        self.assertIsNone(recovery)
        self.assertEqual(models["fa-ngram"]["card"]["title"], "مدل آزمایشی")

    def test_failed_write_keeps_the_old_registry_and_leaves_no_temp_file(self):
        store = ModelStore(self.root)
        store.save({"fa-ngram": validate_entry("fa-ngram", self.entry())})
        before = read_bytes(store.registry_path)
        updated = validate_entry("fa-ngram", self.entry(state="failed", reasons=["x"]))
        with mock.patch("model_runtime.store.os.replace", side_effect=OSError("disk gone")):
            with self.assertRaises(OSError):
                store.save({"fa-ngram": updated})
        self.assertEqual(read_bytes(store.registry_path), before)
        self.assertEqual([n for n in os.listdir(self.root) if n.endswith(".tmp")], [])

    def test_a_corrupt_registry_is_moved_aside_reported_and_never_silently_reset(self):
        store = ModelStore(self.root)
        os.makedirs(self.root)
        for number, junk in enumerate((b"{not json", b'{"schema": 2, "models": {}}', b'{"schema": 1, "models": []}'), start=1):
            with open(store.registry_path, "wb") as handle:
                handle.write(junk)
            models, recovery = store.load()
            self.assertEqual(models, {})
            self.assertEqual(recovery["moved_to"], "registry.json.corrupt.%d" % number)
            self.assertEqual(read_bytes(os.path.join(self.root, recovery["moved_to"])), junk)
            self.assertFalse(os.path.exists(store.registry_path))

    def test_invalid_entries_make_the_whole_registry_corrupt(self):
        store = ModelStore(self.root)
        smoke = {"ok": True, "details": "d", "excerpt": "e", "at": 1.0, "runtime": "ngram"}
        file_info = {"rel": "files/fa-ngram/1.0/model.bin", "size": 5, "mtime_ns": 5}
        bad = {
            "unknown state": self.entry(state="installed"), "bad origin": self.entry(origin="web"),
            "extra key": dict(self.entry(), extra=1), "bad card": self.entry(card={"model_id": "fa-ngram"}),
            "id mismatch": self.entry(card=parse_card(card_dict(model_id="other-model")).to_dict()),
            "usable without smoke": self.entry(state="usable", file=file_info),
            "usable failed smoke": self.entry(state="usable", file=file_info, smoke=dict(smoke, ok=False)),
            "usable without file": self.entry(state="usable", smoke=smoke),
            "verified without file": self.entry(state="verified"),
            "foreign path": self.entry(state="downloaded", file=dict(file_info, rel="../../etc/passwd")),
            "ack type": self.entry(license_ack="yes"), "reasons type": self.entry(reasons="x"),
            "nan time": self.entry(updated_at=float("nan")),
        }
        for name, entry in bad.items():
            with self.subTest(case=name):
                with self.assertRaises(RegistryProblem):
                    validate_entry("fa-ngram", entry)
        good = self.entry(state="usable", file=file_info, smoke=smoke)
        self.assertEqual(validate_entry("fa-ngram", good)["state"], "usable")

    def test_symlinked_or_oversized_registry_is_refused(self):
        store = ModelStore(self.root)
        os.makedirs(self.root)
        target = os.path.join(self._tmp.name, "elsewhere.json")
        with open(target, "w") as handle:
            handle.write('{"schema": 1, "models": {}}')
        os.symlink(target, store.registry_path)
        models, recovery = store.load()
        self.assertEqual((models, bool(recovery)), ({}, True))

    def test_model_paths_are_validated(self):
        store = ModelStore(self.root)
        self.assertEqual(store.model_file("fa-ngram", "1.0"), os.path.join(self.root, "files", "fa-ngram", "1.0", "model.bin"))
        for model_id, version in (("../x", "1"), ("a/b", "1"), ("fa-ngram", "../1"), ("FA", "1"), ("fa-ngram", ""), ("", "1")):
            with self.subTest(model_id=model_id, version=version):
                with self.assertRaises(ValueError):
                    store.model_dir(model_id, version)

    def test_states_are_the_documented_seven(self):
        self.assertEqual(STATES, ("registered", "downloading", "downloaded", "verified", "compatible", "usable", "failed"))


if __name__ == "__main__":
    unittest.main()
