"""Prompt 957 - brain_hub core pieces: atomic files, permissions, audit chain, capability graph, catalog and gap matching."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_hub import atomic, audit as audit_mod, catalog, gaps, graph, permissions
from brain_hub.graph import (BLOCKER_KINDS, Blocker, CapabilityGraph, CapabilityNode, NODE_KINDS, STATES, STATE_TEXT,
                             USABLE_STATES, state_label)


def has_persian(text):
    return any("؀" <= ch <= "ۿ" for ch in text)


class TempCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def read(self, *parts):
        with open(self.path(*parts), "rb") as handle:
            return handle.read()

    def write(self, data, *parts):
        os.makedirs(os.path.dirname(self.path(*parts)), exist_ok=True)
        with open(self.path(*parts), "wb") as handle:
            handle.write(data)


# ================================================================================ atomic
class AtomicTests(TempCase):
    def test_write_creates_parent_and_roundtrips_persian(self):
        target = self.path("a", "b", "x.json")
        atomic.write_json_atomic(target, {"k": "سلام", "n": 1})
        self.assertEqual(atomic.read_json_bounded(target, 1000), {"k": "سلام", "n": 1})
        self.assertEqual(os.listdir(os.path.dirname(target)), ["x.json"])

    def test_failed_replace_keeps_the_old_file_and_leaves_no_temp(self):
        target = self.path("x.json")
        atomic.write_json_atomic(target, {"v": 1})
        with mock.patch("brain_hub.atomic.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                atomic.write_json_atomic(target, {"v": 2})
        self.assertEqual(atomic.read_json_bounded(target, 1000), {"v": 1})
        self.assertEqual(os.listdir(self.dir), ["x.json"])

    def test_read_refuses_links_large_and_unreadable_files(self):
        self.write(b'{"a": 1}', "ok.json")
        os.symlink(self.path("ok.json"), self.path("link.json"))
        with self.assertRaises(ValueError):
            atomic.read_json_bounded(self.path("link.json"), 1000)
        self.write(b"x" * 50, "big.json")
        with self.assertRaises(ValueError):
            atomic.read_json_bounded(self.path("big.json"), 10)
        self.write(b"\xff\xfe\x00bad", "bad.json")
        with self.assertRaises(ValueError):
            atomic.read_json_bounded(self.path("bad.json"), 1000)
        with self.assertRaises(ValueError):
            self.write(b"{not json", "j.json")
            atomic.read_json_bounded(self.path("j.json"), 1000)
        with self.assertRaises(FileNotFoundError):
            atomic.read_json_bounded(self.path("missing.json"), 1000)

    def test_set_aside_numbers_the_copies(self):
        for expected in ("p.corrupt.1", "p.corrupt.2"):
            self.write(b"x", "p")
            self.assertEqual(atomic.set_aside(self.path("p")), expected)
        self.assertFalse(os.path.exists(self.path("p")))
        self.assertEqual(atomic.set_aside(self.path("nothing")), "")


# =========================================================================== permissions
class PermissionTests(TempCase):
    def store(self, **kw):
        return permissions.PermissionStore(self.path("hub"), **kw)

    def test_reading_never_creates_anything(self):
        s = self.store()
        self.assertFalse(s.is_granted("network"))
        self.assertEqual(s.snapshot(), {})
        self.assertEqual([r["granted"] for r in s.describe()], [False])
        self.assertFalse(os.path.exists(self.path("hub")))

    def test_grant_needs_an_explicit_true(self):
        s = self.store()
        for value in (False, None, "yes", 1, "true", [], 0.5):
            with self.subTest(value=value):
                change = s.grant("network", user_approved=value)
                self.assertEqual((change.ok, change.code, change.granted), (False, "approval_required", False))
        self.assertFalse(s.is_granted("network"))
        self.assertFalse(os.path.exists(self.path("hub")))
        self.assertIn("تأیید", s.grant("network").message_fa)

    def test_grant_is_persisted_and_survives_a_new_store(self):
        s = self.store(clock=lambda: 1234.5)
        change = s.grant("network", user_approved=True, by="user")
        self.assertEqual((change.ok, change.code, change.granted), (True, "ok", True))
        again = self.store()
        self.assertTrue(again.is_granted("network"))
        self.assertEqual(again.snapshot()["network"], {"at": 1234.5, "by": "user"})
        self.assertEqual(self.store().grant("network", user_approved=True).code, "already_granted")

    def test_unknown_permissions_are_refused_everywhere(self):
        s = self.store()
        for name in ("microphone", "", None, 5, "NETWORK", "network ", "android.permission.CAMERA"):
            with self.subTest(name=name):
                self.assertEqual(s.grant(name, user_approved=True).code, "unknown_permission")
                self.assertEqual(s.revoke(name).code, "unknown_permission")
                self.assertFalse(s.is_granted(name))

    def test_revoke_turns_it_off_for_good(self):
        s = self.store()
        s.grant("network", user_approved=True)
        change = s.revoke("network")
        self.assertEqual((change.ok, change.code, change.granted), (True, "ok", False))
        self.assertFalse(self.store().is_granted("network"))
        self.assertEqual(s.revoke("network").code, "not_granted")

    def test_the_gate_is_live(self):
        s = self.store()
        gate = s.gate()
        self.assertFalse(gate.allowed("network"))
        s.grant("network", user_approved=True)
        self.assertTrue(gate.allowed("network"))
        s.revoke("network")
        self.assertFalse(gate.allowed("network"))
        self.assertFalse(gate.allowed("microphone"))

    def test_a_damaged_file_grants_nothing_and_is_set_aside(self):
        bad = [b"not json", b"[]", b'{"schema": 2, "granted": {}}', b'{"schema": 1}', b'{"schema": 1, "granted": {"camera": {"at": 1, "by": "u"}}}',
               b'{"schema": 1, "granted": {"network": {"at": 1}}}', b'{"schema": 1, "granted": {"network": {"at": true, "by": "u"}}}',
               b'{"schema": 1, "granted": {"network": {"at": 1, "by": "u", "x": 1}}}', b"x" * 9000, b'{"schema": 1, "granted": {"network": {"at": 1, "by": "' + b"u" * 60 + b'"}}}']
        for index, content in enumerate(bad):
            with self.subTest(index=index):
                self.write(content, "hub", "permissions.json")
                s = self.store()
                self.assertFalse(s.is_granted("network"))
                self.assertIsNotNone(s.recovery)
                self.assertTrue(s.recovery["moved_to"].startswith("permissions.json.corrupt."))
                self.assertFalse(os.path.exists(self.path("hub", "permissions.json")))
                self.assertTrue(s.grant("network", user_approved=True).ok)            # usable again afterwards
                os.unlink(self.path("hub", "permissions.json"))

    def test_a_symlinked_file_is_treated_as_damaged(self):
        self.write(b'{"schema": 1, "granted": {"network": {"at": 1, "by": "user"}}}', "real.json")
        os.makedirs(self.path("hub"))
        os.symlink(self.path("real.json"), self.path("hub", "permissions.json"))
        s = self.store()
        self.assertFalse(s.is_granted("network"))
        self.assertIsNotNone(s.recovery)

    def test_a_failed_save_changes_nothing(self):
        s = self.store()
        with mock.patch("brain_hub.permissions.atomic.write_json_atomic", side_effect=OSError("full")):
            change = s.grant("network", user_approved=True)
        self.assertEqual((change.ok, change.code, change.granted), (False, "io_error", False))
        self.assertFalse(s.is_granted("network"))
        s.grant("network", user_approved=True)
        with mock.patch("brain_hub.permissions.atomic.write_json_atomic", side_effect=OSError("full")):
            change = s.revoke("network")
        self.assertEqual((change.ok, change.code, change.granted), (False, "io_error", True))
        self.assertTrue(s.is_granted("network"))
        self.assertTrue(self.store().is_granted("network"))

    def test_describe_explains_what_the_permission_covers(self):
        row = self.store().describe()[0]
        self.assertEqual(row["name"], "network")
        self.assertTrue(has_persian(row["label_fa"]) and has_persian(row["covers_fa"]))
        self.assertTrue(row["label_en"] and row["covers_en"])

    def test_bad_roots_are_programming_errors(self):
        for root in ("", None, 5):
            with self.assertRaises(ValueError):
                permissions.PermissionStore(root)


# ================================================================================== audit
class AuditTests(TempCase):
    def log(self, **kw):
        kw.setdefault("clock", lambda: 100.0)
        return audit_mod.HubAudit(self.path("a", "hub_audit.jsonl"), **kw)

    def lines(self):
        return self.read("a", "hub_audit.jsonl").split(b"\n")[:-1]

    def test_nothing_exists_until_the_first_append(self):
        a = self.log()
        self.assertEqual(a.entries(), [])
        self.assertEqual(a.verify(), {"ok": True, "entries": 0, "first_bad_seq": None})
        self.assertFalse(os.path.exists(self.path("a")))

    def test_entries_form_a_valid_chain_across_instances(self):
        a = self.log()
        first = a.append("permission.grant", "network", {"ok": True})
        second = self.log().append("web.fetch", "https://x.test/p", {"code": "ok"})
        self.assertEqual((first["seq"], second["seq"]), (1, 2))
        self.assertEqual(second["prev"], first["hash"])
        self.assertEqual(self.log().verify(), {"ok": True, "entries": 2, "first_bad_seq": None})
        self.assertEqual([e["kind"] for e in self.log().tail(10)], ["permission.grant", "web.fetch"])

    def test_every_kind_of_tampering_is_found(self):
        a = self.log()
        for i in range(4):
            a.append("test.event", "s%d" % i, {"i": i})
        original = self.read("a", "hub_audit.jsonl")
        rows = original.split(b"\n")[:-1]

        def check(new_rows, label):
            self.write(b"\n".join(new_rows) + b"\n", "a", "hub_audit.jsonl")
            verdict = self.log().verify()
            self.assertFalse(verdict["ok"], label)
            self.assertIsNotNone(verdict["first_bad_seq"], label)

        check([rows[0], rows[1].replace(b'"i":1', b'"i":9'), rows[2], rows[3]], "edited detail")
        check([rows[0], rows[2], rows[3]], "deleted middle line")
        check([rows[0], rows[2], rows[1], rows[3]], "swapped lines")
        check([rows[0], rows[1], b"not json", rows[3]], "garbage line")
        check([rows[0], rows[1], rows[2], rows[3].replace(b'"kind":"test.event"', b'"kind":"test.other"')], "edited kind")
        first = rows[0].decode("utf-8")
        anchor = '"prev":"' + "0" * 64 + '"'
        self.assertIn(anchor, first)
        check([first.replace(anchor, '"prev":"' + "1" * 64 + '"').encode("utf-8"), rows[1], rows[2], rows[3]], "edited anchor")
        self.write(original, "a", "hub_audit.jsonl")
        self.assertTrue(self.log().verify()["ok"])

    def test_a_torn_last_line_is_cut_off_and_the_chain_continues(self):
        a = self.log()
        a.append("test.event", "one")
        with open(self.path("a", "hub_audit.jsonl"), "ab") as handle:
            handle.write(b'{"seq": 2, "ts": 1, "kind": "te')                     # a crash in the middle of an append
        b = self.log()
        entry = b.append("test.event", "two")
        self.assertTrue(b.repaired_tail)
        self.assertEqual(entry["seq"], 2)
        self.assertEqual(self.log().verify(), {"ok": True, "entries": 2, "first_bad_seq": None})

    def test_a_complete_last_line_without_newline_is_kept(self):
        a = self.log()
        a.append("test.event", "one")
        raw = self.read("a", "hub_audit.jsonl")
        self.write(raw.rstrip(b"\n"), "a", "hub_audit.jsonl")
        b = self.log()
        self.assertEqual(b.append("test.event", "two")["seq"], 2)
        self.assertFalse(b.repaired_tail)
        self.assertEqual(self.log().verify()["entries"], 2)

    def test_details_are_clipped_and_json_safe(self):
        a = self.log()
        entry = a.append("test.event", "s" * 500, {"long": "x" * 900, "nan": float("nan"), "inf": float("inf"), "obj": object(),
                                                   "deep": {"a": {"b": {"c": {"d": 1}}}}, "many": list(range(50)), "t": True, "none": None,
                                                   **{"k%d" % i: i for i in range(30)}})
        self.assertEqual(len(entry["subject"]), 200)
        self.assertEqual(len(entry["detail"]), 12)
        stored = json.loads(self.lines()[0].decode("utf-8"))
        self.assertEqual(stored["hash"], entry["hash"])
        self.assertTrue(self.log().verify()["ok"])
        wide = self.log().append("test.event", "", {"long": "x" * 900, "nan": float("nan"), "deep": {"a": {"b": {"c": {"d": 1}}}}})
        self.assertEqual(len(wide["detail"]["long"]), 200)
        self.assertIsNone(wide["detail"]["nan"])
        self.assertIsNone(wide["detail"]["deep"]["a"]["b"])

    def test_bad_kinds_become_unknown(self):
        a = self.log()
        for kind in ("", "A", "a b", None, 5, "x" * 80, "../etc"):
            self.assertEqual(a.append(kind)["kind"], "unknown")
        self.assertEqual(a.append("model.transition")["kind"], "model.transition")

    def test_the_file_rotates_and_the_chain_continues(self):
        with mock.patch.object(audit_mod, "MAX_BYTES", 400):
            a = self.log()
            last = None
            for i in range(8):
                last = a.append("test.event", "subject-%d" % i, {"i": i})
        self.assertTrue(os.path.exists(self.path("a", "hub_audit.jsonl.1")))
        current = [json.loads(x) for x in self.lines()]
        self.assertEqual(current[-1]["hash"], last["hash"])
        self.assertTrue(self.log().verify()["ok"])
        old = [json.loads(x) for x in self.read("a", "hub_audit.jsonl.1").split(b"\n")[:-1]]
        self.assertEqual(current[0]["prev"], old[-1]["hash"])
        self.assertEqual(current[0]["seq"], old[-1]["seq"] + 1)

    def test_a_failed_write_is_counted_and_never_raised(self):
        a = self.log()
        a.append("test.event", "one")
        with mock.patch("brain_hub.audit.os.fsync", side_effect=OSError("io")):
            self.assertIsNone(a.append("test.event", "lost"))
        self.assertEqual(a.failures, 1)
        self.assertEqual(a.append("test.event", "again")["seq"], 2)

    def test_tail_is_bounded(self):
        a = self.log()
        for i in range(5):
            a.append("test.event", str(i))
        self.assertEqual(len(a.tail(3)), 3)
        self.assertEqual(len(a.tail(0)), 1)
        self.assertEqual(len(a.tail(10_000)), 5)
        self.assertEqual(a.tail(2)[-1]["subject"], "4")


# ================================================================================== graph
def node(node_id="x.one", **over):
    data = dict(node_id=node_id, kind="tool", title_fa="عنوان", title_en="Title", state="available")
    data.update(over)
    return CapabilityNode(**data)


class GraphTests(unittest.TestCase):
    def test_a_node_validates_itself(self):
        for over in (dict(state="bogus"), dict(kind="bogus"), dict(state="active"), dict(node_id=""), dict(node_id="x" * 101),
                     dict(node_id=5)):
            with self.subTest(over=over), self.assertRaises(ValueError):
                node(**over)
        with self.assertRaises(ValueError):
            Blocker("bogus", "a", "b")
        self.assertTrue(node(state="active", tested=True).usable)

    def test_only_active_and_available_are_usable(self):
        for state in STATES:
            n = node(state=state, tested=state == "active")
            self.assertEqual(n.usable, state in USABLE_STATES, state)
        self.assertEqual(USABLE_STATES, {"active", "available"})

    def test_every_state_and_kind_is_described(self):
        for state in STATES:
            fa, en = STATE_TEXT[state]
            self.assertTrue(has_persian(fa) and en, state)
            self.assertEqual(state_label(state), fa)
            self.assertEqual(state_label(state, "en"), en)
        self.assertEqual(state_label("nope"), "nope")
        self.assertEqual(len(set(BLOCKER_KINDS)), len(BLOCKER_KINDS))
        self.assertEqual(len(set(NODE_KINDS)), len(NODE_KINDS))

    def test_the_graph_rejects_duplicates_and_foreign_objects(self):
        with self.assertRaises(ValueError):
            CapabilityGraph([node("a.one"), node("a.one")])
        for bad in ({"node_id": "a"}, "a", None):
            with self.assertRaises(ValueError):
                CapabilityGraph([bad])

    def test_lookup_filter_and_summary(self):
        g = CapabilityGraph([node("a.1", state="active", tested=True, kind="extension"), node("a.2", state="available"),
                             node("a.3", state="permission_blocked", blockers=(Blocker("permission", "فا", "en"),)),
                             node("a.4", state="scaffold_only", kind="infra")])
        self.assertEqual(len(g), 4)
        self.assertIn("a.2", g)
        self.assertNotIn("zzz", g)
        self.assertIsNone(g.get("zzz"))
        self.assertIsNone(g.get(5))
        self.assertEqual([n.node_id for n in g.nodes(kind="infra")], ["a.4"])
        self.assertEqual([n.node_id for n in g.nodes(state="available")], ["a.2"])
        self.assertEqual([n.node_id for n in g.usable()], ["a.1", "a.2"])
        s = g.summary()
        self.assertEqual((s["total"], s["tested"], s["usable"]), (4, 1, 2))
        self.assertEqual(s["by_state"], {"active": 1, "available": 1, "permission_blocked": 1, "scaffold_only": 1})
        self.assertEqual(s["by_kind"], {"extension": 1, "tool": 2, "infra": 1})
        data = g.to_dict()
        json.dumps(data, ensure_ascii=False)
        self.assertEqual(data["nodes"][0]["usable"], True)
        self.assertEqual(data["nodes"][2]["blockers"][0]["kind"], "permission")
        self.assertTrue(has_persian(data["nodes"][2]["state_label_fa"]))

    def test_nodes_are_immutable(self):
        n = node()
        with self.assertRaises(Exception):
            n.state = "active"


# ========================================================================== catalog + gaps
class CatalogTests(unittest.TestCase):
    def test_every_entry_is_fully_described_in_both_languages(self):
        for area in catalog.CONNECTED:
            self.assertTrue(has_persian(area.title_fa) and has_persian(area.summary_fa), area.area_id)
            self.assertTrue(area.title_en and area.summary_en and area.entry, area.area_id)
        for area in catalog.SCAFFOLDS:
            self.assertTrue(has_persian(area.title_fa) and has_persian(area.summary_fa), area.area_id)
            self.assertTrue(area.title_en and area.summary_en, area.area_id)
        ids = [a.area_id for a in catalog.CONNECTED] + [a.area_id for a in catalog.SCAFFOLDS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_scaffolds_never_claim_to_execute_anything(self):
        for area in catalog.SCAFFOLDS:
            text = (area.summary_fa + area.summary_en).lower()
            self.assertNotIn("installed", text)
            self.assertTrue(area.missing or area.area_id == "web", area.area_id)

    def test_packages_named_by_the_catalog_exist_in_this_build(self):
        # one scaffold is keyed by its area_id alone (earlier frozen boundary tests forbid naming that package in
        # production code); this table - tests may name it - keeps that entry tied to the real package
        unnamed = {"images_audio": "multimedia"}
        for area in list(catalog.CONNECTED) + list(catalog.SCAFFOLDS):
            package = area.package if area.package is not None else unnamed[area.area_id]
            self.assertTrue(catalog.package_present(package), package)
            if area.package is None:
                self.assertEqual([a.area_id for a in catalog.SCAFFOLDS if a.package is None], list(unnamed))
        self.assertFalse(catalog.package_present("definitely_not_a_package_957"))
        self.assertFalse(catalog.package_present(""))
        self.assertFalse(catalog.package_present("a..b"))

    def test_probing_a_package_does_not_import_it(self):
        sys.modules.pop("autonomy", None)
        self.assertTrue(catalog.package_present("autonomy"))
        self.assertNotIn("autonomy", sys.modules)


class GapTests(unittest.TestCase):
    def test_every_gap_is_well_formed(self):
        self.assertEqual(len(gaps.gap_ids()), len(set(gaps.gap_ids())))
        for g in gaps.GAPS:
            self.assertIn(g.state, ("dependency_blocked", "not_implemented", "policy_blocked", "scaffold_only"), g.gap_id)
            self.assertTrue(g.blockers, g.gap_id)
            for b in g.blockers:
                self.assertIn(b.kind, BLOCKER_KINDS)
                self.assertTrue(has_persian(b.text_fa) and b.text_en, g.gap_id)
            for text in (g.title_fa, g.exists_fa, g.next_fa):
                self.assertTrue(has_persian(text), g.gap_id)
            self.assertTrue(g.title_en and g.exists_en and g.next_en, g.gap_id)
            self.assertTrue(g.words, g.gap_id)
            self.assertIs(gaps.get_gap(g.gap_id), g)
        self.assertIsNone(gaps.get_gap("nope"))
        self.assertIsNone(gaps.get_gap(None))

    def test_nothing_in_a_gap_promises_the_impossible(self):
        for g in gaps.GAPS:
            text = (g.next_fa + g.next_en + g.exists_fa + g.exists_en).lower()
            for banned in ("done", "installed", "activated", "انجام شد", "نصب شد", "ساخته شد"):
                self.assertNotIn(banned, text, g.gap_id)

    def test_listed_examples_match_their_own_gap(self):
        for g in gaps.GAPS:
            for sentence in g.examples_fa:
                with self.subTest(sentence=sentence):
                    self.assertEqual(gaps.match_gap(sentence).gap_id, g.gap_id)

    def test_requests_are_recognised(self):
        table = {
            "برام یک ویدئو بسازی؟": "video_animation", "میتونی انیمیشن درست کنی؟": "video_animation",
            "می‌تونی آهنگ بسازی": "music_audio", "یک آهنگ برام بنویس": "music_audio", "برای من یک بازی بساز": "game_creation",
            "میخوام یه بازی بسازی": "game_creation", "یک نقاشی از گربه بکش": "image_generation", "برام لوگو بساز": "image_generation",
            "یه خبر از اینترنت برام بیار": "idle_web_gathering", "قفل گوشی را باز کن": "phone_control", "وای فای را خاموش کن": "phone_control",
            "روشن کن وای فای": "phone_control", "جارویس، ساعت چنده؟": "wake_word_voice", "جارویس": "wake_word_voice",
            "رمز ارز بخر": "income_crypto", "حالت شب رو اضافه کن": "ui_self_change", "یک دکمه به صفحه اضافه کن": "ui_self_change",
            "به تماس‌هایم جواب بده": "phone_calls", "تماس بگیر": "phone_calls", "هر روز ساعت ۸ یک پست در اینستاگرام بگذار": "social_posting",
            "یک پست بذار": "social_posting", "به پیام‌های تلگرام جواب بده": "other_apps", "صدای من را بشناس": "speaker_identity",
            "با دوربین ببین این چیه": "camera_vision", "عکس بگیر": "camera_vision", "برنامه بنویس که": "local_code_model",
            "یک مدل سه بعدی بساز": "three_d", "نسخهٔ ویندوز بساز": "windows_companion",
        }
        for sentence, expected in table.items():
            with self.subTest(sentence=sentence):
                hit = gaps.match_gap(sentence)
                self.assertIsNotNone(hit, sentence)
                self.assertEqual(hit.gap_id, expected)

    def test_ordinary_sentences_are_left_alone(self):
        for sentence in ("من آهنگ دوست دارم", "آهنگ دوست داری؟", "بازی‌ها رو دوست دارم", "سلام", "اسمت چیه؟", "چه کارهایی بلدی؟",
                         "یک مبدل کیلومتر به مایل بساز", "پایتخت ایران کجاست؟", "ساعت چنده؟", "روشنایی اتاق", "پست الکترونیک چیست",
                         "من پول دوست دارم", "یک ماشین حساب بساز", "آهنگ", "ویدیو", "", "   ", "بله", "نه"):
            with self.subTest(sentence=sentence):
                self.assertIsNone(gaps.match_gap(sentence))

    def test_odd_input_is_safe(self):
        for value in (None, 5, [], b"x", "x" * 401, "‌" * 10):
            self.assertIsNone(gaps.match_gap(value))
        self.assertIsNone(gaps.match_gap("آ" * 399))


if __name__ == "__main__":
    unittest.main()
