"""
Prompt 959 (stage B, «مغز خودکار») - the catalog of brains the app may fetch by itself, and the two small helpers under the service:
what the phone has (memory, free space) and the file that remembers where the own brain stands.

The catalog is DATA that the app trusts blindly after the user's «بله»: a wrong address, host or licence here would fetch the wrong thing, so the
tests pin what an entry must look like and which entries exist. They do not prove that the files on the server are still the ones the hashes
were read from (the downloader compares the server's announced hash with the pin before storing a byte and says so when they differ).
"""
import os
import re
import sys
import tempfile
import unittest
from collections import namedtuple

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import ownbrain_catalog as C
from brain_hub import ownbrain_state as ST
from model_runtime.card import license_policy, parse_card
from net_tools.policy import FetchPolicy, UrlError, parse_url

HEX64 = re.compile(r"^[0-9a-f]{64}$")
GB, MB = 1_000_000_000, 1_000_000
Usage = namedtuple("Usage", "total used free")


class CatalogEntryTests(unittest.TestCase):
    def test_exactly_the_two_known_brains_in_a_fixed_order(self):
        self.assertEqual([c.key for c in C.CHOICES], ["strong", "light"])
        self.assertEqual(len({c.model_id for c in C.CHOICES}), 2)
        self.assertIs(C.get("strong"), C.STRONG_CHOICE)
        self.assertIs(C.get("light"), C.LIGHT_CHOICE)
        self.assertIsNone(C.get("medium"))
        self.assertIsNone(C.get(None))
        self.assertIs(C.by_model_id(C.LIGHT_CHOICE.model_id), C.LIGHT_CHOICE)
        self.assertIsNone(C.by_model_id("own-unknown"))

    def test_the_pinned_hashes_and_sizes_are_the_ones_that_were_read_from_the_model_pages(self):
        # light: the page of litert-community/Qwen3.5-0.8B shows 964,566,992 bytes and a hash beginning 25447e25 (read again on 2026-11-16)
        self.assertEqual(C.LIGHT_CHOICE.exact_size, 964_566_992)
        self.assertTrue(C.LIGHT_CHOICE.sha256.startswith("25447e25"))
        # strong: the hash as it was read when the entry was written; a change must be a conscious one
        self.assertEqual(C.STRONG_CHOICE.sha256, "181938105e0eefd105961417e8da75903eacda102c4fce9ce90f50b97139a63c")

    def test_every_entry_is_well_formed_and_safe_to_fetch_without_a_login(self):
        for choice in C.CHOICES:
            with self.subTest(choice.key):
                self.assertRegex(choice.sha256, HEX64)
                self.assertRegex(choice.model_id, r"^[a-z0-9][a-z0-9._-]{2,63}$")
                self.assertEqual(license_policy(choice.license), "permissive", "an open licence that needs no click-through")
                self.assertGreater(choice.size_hint, 100 * MB)
                self.assertLess(choice.size_hint, 8 * GB)
                self.assertGreater(choice.max_bytes, choice.size_hint)
                self.assertLessEqual(choice.tolerance, 0.1)
                self.assertTrue(choice.exact_size == 0 or choice.exact_size == choice.size_hint)
                self.assertGreaterEqual(choice.min_ram, 2 * GB)
                self.assertIn("fa", choice.languages)
                self.assertTrue(choice.persian_fa.strip() and choice.source_fa.strip() and choice.short_fa.strip())
                self.assertEqual(choice.rel_dest, "%s-%s/model.litertlm" % (choice.key, choice.sha256[:12]))
                self.assertNotIn("..", choice.rel_dest)

    def test_every_address_is_https_on_an_allowed_host_and_ends_in_a_model_file(self):
        self.assertEqual(C.ALLOWED_HOSTS, ("huggingface.co", "hf.co"))
        for choice in C.CHOICES:
            with self.subTest(choice.key):
                parsed = parse_url(choice.url, FetchPolicy())
                self.assertNotIsInstance(parsed, UrlError, "the app's own URL policy accepts it")
                self.assertTrue(choice.url.startswith("https://"))
                host = choice.url.split("/")[2]
                self.assertIn(host, C.ALLOWED_HOSTS)
                self.assertTrue(choice.url.endswith(".litertlm"))
                self.assertIn("/litert-community/", choice.url, "only the on-device packaging of the engine's own community")
                self.assertIn("/resolve/main/", choice.url)
                self.assertNotIn("?", choice.url)

    def test_the_card_the_service_registers_is_accepted_by_the_strict_model_card(self):
        from brain_hub.ownbrain import OwnBrain
        for choice in C.CHOICES:
            with self.subTest(choice.key):
                size = choice.exact_size or choice.size_hint
                card = parse_card(OwnBrain._card(object.__new__(OwnBrain), choice, size))
                self.assertEqual((card.model_id, card.format, card.sha256, card.size_bytes), (choice.model_id, "litertlm", choice.sha256, size))
                self.assertEqual(card.runtime_hint, "litertlm")


class FitTests(unittest.TestCase):
    STRONG, LIGHT = C.STRONG_CHOICE, C.LIGHT_CHOICE

    def test_memory_that_cannot_be_read_is_never_guessed(self):
        for bad in (0, -1, None, "8", True, 1.5):
            report = C.fits(self.LIGHT, bad, 100 * GB)
            self.assertEqual((report.ok, report.code), (False, "ram_unknown"), bad)

    def test_too_little_memory_is_refused_with_both_numbers(self):
        report = C.fits(self.STRONG, 4 * GB, 100 * GB)
        self.assertEqual((report.ok, report.code, report.need_bytes, report.have_bytes), (False, "ram_too_small", self.STRONG.min_ram, 4 * GB))
        self.assertTrue(C.fits(self.STRONG, self.STRONG.min_ram, 100 * GB).ok, "exactly the minimum is enough")
        self.assertFalse(C.fits(self.STRONG, self.STRONG.min_ram - 1, 100 * GB).ok)

    def test_free_space_counts_the_whole_file_plus_a_safety_margin_minus_what_is_already_there(self):
        need = int(self.LIGHT.size_hint * (1 + self.LIGHT.tolerance)) + C.SAFETY_FREE
        self.assertEqual(C.fits(self.LIGHT, 8 * GB, need).need_bytes, need)
        self.assertTrue(C.fits(self.LIGHT, 8 * GB, need).ok)
        short = C.fits(self.LIGHT, 8 * GB, need - 1)
        self.assertEqual((short.ok, short.code, short.need_bytes, short.have_bytes), (False, "not_enough_space", need, need - 1))
        half = self.LIGHT.size_hint // 2
        self.assertTrue(C.fits(self.LIGHT, 8 * GB, need - half, already_have=half).ok, "a half download needs only the rest")
        self.assertEqual(C.fits(self.LIGHT, 8 * GB, 10 ** 12, already_have=10 ** 12).need_bytes, C.SAFETY_FREE, "never a negative need")
        self.assertEqual(C.fits(self.LIGHT, 8 * GB, None).code, "not_enough_space")
        self.assertEqual(C.fits(self.LIGHT, 8 * GB, True).code, "not_enough_space")

    def test_the_strong_brain_is_recommended_only_on_a_phone_with_comfortable_memory(self):
        self.assertIs(C.recommend(8 * GB, 100 * GB), self.STRONG)
        self.assertIs(C.recommend(self.STRONG.comfortable_ram, 100 * GB), self.STRONG)
        self.assertIs(C.recommend(self.STRONG.comfortable_ram - 1, 100 * GB), self.LIGHT, "fits, but not comfortably")
        self.assertIs(C.recommend(5 * GB, 100 * GB), self.LIGHT)
        self.assertIs(C.recommend(3 * GB, 100 * GB), self.LIGHT)
        self.assertIsNone(C.recommend(2 * GB, 100 * GB), "nothing fits a phone this small")
        self.assertIsNone(C.recommend(0, 100 * GB))

    def test_the_recommendation_follows_the_free_space(self):
        light_need = int(self.LIGHT.size_hint * (1 + self.LIGHT.tolerance)) + C.SAFETY_FREE
        strong_need = int(self.STRONG.size_hint * (1 + self.STRONG.tolerance)) + C.SAFETY_FREE
        self.assertIs(C.recommend(8 * GB, strong_need), self.STRONG)
        self.assertIs(C.recommend(8 * GB, strong_need - 1), self.LIGHT, "the strong one does not fit the disk, the light one does")
        self.assertIsNone(C.recommend(8 * GB, light_need - 1))
        self.assertIs(C.recommend(8 * GB, strong_need - 1 - 10 * MB, already_have=10 * MB), self.LIGHT)
        self.assertIs(C.recommend(8 * GB, strong_need - 10 * MB, already_have=10 * MB), self.STRONG, "a partial file lowers the need")


class RamAndSpaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def write(self, name, text, mode="w"):
        path = os.path.join(self.dir, name)
        with open(path, mode, encoding=None if "b" in mode else "ascii") as handle:
            handle.write(text)
        return path

    def test_memory_is_read_from_the_meminfo_total_in_kilobytes(self):
        path = self.write("meminfo", "MemTotal:       8000000 kB\nMemFree:  1 kB\n")
        self.assertEqual(ST.ram_bytes(path), 8_000_000 * 1024)

    def test_other_units_are_understood_and_an_absent_unit_means_kilobytes(self):
        self.assertEqual(ST.ram_bytes(self.write("a", "MemTotal: 4000 mB\n")), 4000 * 1024 * 1024)
        self.assertEqual(ST.ram_bytes(self.write("b", "MemTotal: 123456 B\n")), 123456)
        self.assertEqual(ST.ram_bytes(self.write("c", "MemTotal: 2048\n")), 2048 * 1024)

    def test_what_cannot_be_read_is_zero_never_a_guess(self):
        self.assertEqual(ST.ram_bytes(os.path.join(self.dir, "missing")), 0)
        self.assertEqual(ST.ram_bytes(self.write("empty", "")), 0)
        self.assertEqual(ST.ram_bytes(self.write("nototal", "MemFree: 5 kB\n")), 0)
        self.assertEqual(ST.ram_bytes(self.write("garbage", "MemTotal: lots kB\n")), 0)
        self.assertEqual(ST.ram_bytes(self.write("neg", "MemTotal: -5 kB\n")), 0)
        self.assertEqual(ST.ram_bytes(self.write("zero", "MemTotal: 0 kB\n")), 0)
        self.assertEqual(ST.ram_bytes(self.write("huge", "MemTotal: %d kB\n" % (1 << 41))), 0)
        self.assertEqual(ST.ram_bytes(self.write("bin", b"\xff\xfe\x00MemTotal: 5 kB", mode="wb")), 0)

    def test_free_space_is_asked_for_the_nearest_existing_folder(self):
        asked = []

        def usage(path):
            asked.append(path)
            return Usage(100, 40, 60)

        deep = os.path.join(self.dir, "not", "yet", "there")
        self.assertEqual(ST.free_bytes(deep, usage), 60)
        self.assertEqual(asked, [self.dir])
        self.assertEqual(ST.free_bytes(self.dir, lambda p: (100, 40, 70)), 70, "a plain tuple works too")

    def test_a_disk_that_cannot_be_asked_is_zero(self):
        def broken(_path):
            raise OSError("no")

        self.assertEqual(ST.free_bytes(self.dir, broken), 0)
        self.assertEqual(ST.free_bytes(self.dir, lambda p: None), 0)
        facts = ST.device_facts(self.dir, broken, os.path.join(self.dir, "missing"))
        self.assertEqual(facts, {"ram": 0, "free": 0})


class StateFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.join(self._tmp.name, "own_brain")
        self.file = ST.StateFile(self.dir, lambda: 1234.5)

    def put(self, raw):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.file.path, "wb") as handle:
            handle.write(raw if isinstance(raw, bytes) else raw.encode("utf-8"))

    def raw(self):
        with open(self.file.path, "rb") as handle:
            return handle.read()

    def asides(self):
        return sorted(name for name in os.listdir(self.dir) if name.startswith("state.json.corrupt"))

    def test_a_missing_file_is_an_empty_state_and_nothing_is_created(self):
        state, note = self.file.load()
        self.assertEqual((state, note), (ST.default_state(), "missing"))
        self.assertFalse(os.path.exists(self.dir))

    def test_a_saved_state_comes_back_exactly_with_the_time_of_the_save(self):
        state = dict(ST.default_state(), choice="light", phase="downloading", consent_at=99.0, bytes=5, total=10, model_id="own-x")
        self.assertTrue(self.file.save(state))
        loaded, note = self.file.load()
        self.assertEqual(note, "")
        self.assertEqual(loaded, dict(state, updated=1234.5))

    def test_a_damaged_file_is_set_aside_and_the_state_starts_empty(self):
        for raw in (b"{not json", b"", b"[]", b"null", b"\xff\xfe\x00", b'{"v": 1, "phase": "ready", "extra": 1}'):
            with self.subTest(raw=raw[:20]):
                self.put(raw)
                state, note = self.file.load()
                self.assertEqual((state, note), (ST.default_state(), "damaged"))
                self.assertFalse(os.path.exists(self.file.path), "the broken file may not stay where it can be read again")
        self.assertGreaterEqual(len(self.asides()), 1, "set aside, not deleted: the evidence stays")

    def test_a_file_that_claims_a_brain_it_cannot_have_is_refused(self):
        good = dict(ST.default_state())
        bad = [dict(good, v=2), dict(good, phase="weird"), dict(good, bytes=-1), dict(good, bytes=True), dict(good, bytes=1.5),
               dict(good, total="10"), dict(good, consent_at=-5), dict(good, consent_at=True), dict(good, code="x" * 201),
               dict(good, code="a\nb"), dict(good, choice=7), dict(good, model_id=None), dict(good, bytes=1 << 46)]
        import json
        for raw in bad:
            with self.subTest(raw=raw):
                self.put(json.dumps(raw))
                state, note = self.file.load()
                self.assertEqual((state, note), (ST.default_state(), "damaged"))

    def test_a_file_that_is_too_big_is_not_read(self):
        self.put(b'{"v": 1, "detail": "' + b"a" * (ST.MAX_STATE_BYTES + 10) + b'"}')
        self.assertEqual(self.file.load(), (ST.default_state(), "damaged"))

    def test_an_invalid_state_is_not_written_and_nothing_changes(self):
        self.assertTrue(self.file.save(dict(ST.default_state(), phase="ready", choice="light")))
        before = self.raw()
        self.assertFalse(self.file.save(dict(ST.default_state(), phase="weird")))
        self.assertFalse(self.file.save(dict(ST.default_state(), bytes=-3)))
        self.assertEqual(self.raw(), before)

    def test_remove_is_idempotent(self):
        self.assertTrue(self.file.remove())
        self.file.save(ST.default_state())
        self.assertTrue(self.file.remove())
        self.assertFalse(os.path.exists(self.file.path))
        self.assertTrue(self.file.remove())

    def test_a_disk_that_refuses_the_write_gives_false_not_an_exception(self):
        os.makedirs(os.path.dirname(self.dir), exist_ok=True)
        with open(self.dir, "w") as handle:                           # a FILE where the folder must be
            handle.write("x")
        self.assertFalse(self.file.save(ST.default_state()))


if __name__ == "__main__":
    unittest.main()
