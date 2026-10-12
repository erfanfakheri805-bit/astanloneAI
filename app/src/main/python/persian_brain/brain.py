"""
Persian conversation brain - the coordinator
============================================
`PersianBrain.respond(text)` is the whole pipeline of one Persian message:

    text -> normalization -> pending question? -> personal facts stay with the
         existing Persian NLU -> intent (GREETING | QUESTION | REQUEST |
         COMMAND | STATEMENT | TEACHING | CONTINUATION | REFERENCE |
         FEEDBACK | UNKNOWN) -> handler -> reply (or None)

and the handlers talk to the real systems of the application:

  memory / knowledge   the stored user name and likes, taught sentences
                       (KnowledgeSystem / LearningSystem, memory.db)
  dialogue state       what was asked last, what is pending (dialogue.py,
                       persisted in memory.db so it survives a restart)
  capability system    the Self-Builder registry: which capabilities exist,
                       call one, build a missing one (request -> analysis ->
                       gap -> plan -> generate -> validate -> test -> repair ->
                       apply -> persist -> register -> version -> audit),
                       roll back, switch off, history, status

`respond()` returns the reply text, or None when the message is not something
the brain can honestly handle - the application's existing pipeline (Persian
NLU, reasoning, fallback) then answers exactly as it always did. A reply that
claims more than the brain really did is never produced: a build that failed
says so, a capability that does not exist is offered, not faked.

Which messages the brain may claim depends on the runtime (activation.py):
the whole conversation inside the application, only the capability domain in
a plain library Core.
"""

import threading
import weakref

from self_builder import fa_text, matcher, policy, request_parser, units
from self_builder import service as sb_service
from self_builder.builder import ST_APPLIED, ST_CONFIRM, ST_NOOP
from self_builder.registry import CAP_ACTIVE
from understanding import persian_nlu

from . import activation
from . import intents as I
from . import messages as M
from . import normalization as nz
from .dialogue import MAX_PENDING_ATTEMPTS, Dialogue

MAX_INPUT_CHARS = 2000
NAME_FACT = "کاربر.نام"
LIKES_FACT = "کاربر.دوست_دارد"
DISLIKES_FACT = "کاربر.دوست_ندارد"
NLU_SOURCE = "persian_nlu_v1"        # the same provenance Core uses for the facts it stores itself
BRAIN_SOURCE = "persian_brain_v1"
_LATIN_ANSWERS = frozenset({"yes", "y", "ok", "okay", "no", "n", "cancel"})
_DETERMINERS = frozenset({"یک", "یه", "یکی"})
_UNHANDLED = object()


class _Turn:
    """Everything one message needs (plain holder)."""

    def __init__(self, text, norm, toks, dlg, scope, service):
        self.text = text
        self.norm = norm
        self.toks = toks
        self.dlg = dlg
        self.scope = scope
        self.service = service
        self.intent = None

    @property
    def full(self):
        return self.scope == activation.SCOPE_FULL


class PersianBrain:
    def __init__(self, memory, clock=None):
        self.memory = memory
        self._clock = clock
        self._lock = threading.RLock()
        self.last_trace = None   # inspection only: {"intent", "scope", "claimed"}

    # ----------------------------------------------------------------- entry
    def respond(self, text, scope=None):
        """Reply text for `text`, or None when the message is not the brain's."""
        self.last_trace = None
        if not isinstance(text, str) or not text.strip():
            return None
        if scope is None:
            scope = activation.scope_for(self.memory)
        if scope == activation.SCOPE_OFF:
            return None
        with self._lock:
            try:
                return self._respond(text, scope)
            except Exception as e:  # the brain must never break a conversation
                self._log_error(e, text)
                return None

    def reset_dialogue(self):
        """Forget the pending question and the last topic."""
        with self._lock:
            dlg = Dialogue(self.memory, self._clock).load()
            dlg.clear_pending()
            dlg.clear_last()
            dlg.commit()

    def _log_error(self, error, text):
        try:
            self.memory.log_error("persian_brain", f"{type(error).__name__}: {error}"[:300], (text or "")[:200])
        except Exception:
            pass

    # --------------------------------------------------------------- routing
    def _respond(self, text, scope):
        norm = nz.normalize(text)
        if not norm or len(text) > MAX_INPUT_CHARS:
            return None
        toks = fa_text.words(norm)
        persian = nz.has_persian_script(norm)
        number_only = 0 < len(toks) <= 8 and all(fa_text.parse_number(t) is not None for t in toks)
        if not persian and not number_only and not (0 < len(toks) <= 3 and set(toks) <= _LATIN_ANSWERS):
            return None  # English (or anything without Persian letters) is never the brain's
        dlg = Dialogue(self.memory, self._clock).load()
        if not persian and dlg.pending is None:
            return None  # a bare «yes» / «70» is only the brain's when it answers an open question
        turn = _Turn(text, norm, toks, dlg, scope, sb_service.get_service(self.memory))
        try:
            reply = self._route(turn)
        finally:
            dlg.commit()
        self.last_trace = {"intent": turn.intent.to_dict() if turn.intent else None, "scope": scope,
                           "claimed": reply is not None}
        return reply

    def _route(self, turn):
        dlg = turn.dlg
        if dlg.pending is not None:
            word = I.answer_word(turn.toks)
            if word:
                turn.intent = I.Intent(I.CONTINUATION, word, 0.95, ["pending:" + dlg.pending_type])
                reply = self._answer_pending(turn, word)
                if reply is not _UNHANDLED:
                    return reply
        # personal facts (name, likes, "what is my name") belong to the existing Persian NLU
        nlu = persian_nlu.analyze_persian(turn.norm)
        if nlu.intent in (persian_nlu.INTENT_INTRODUCE_NAME, persian_nlu.INTENT_LIKE,
                          persian_nlu.INTENT_DISLIKE, persian_nlu.INTENT_ASK_USER_NAME):
            dlg.clear_pending()
            return None
        if dlg.pending is not None:
            turn.intent = I.Intent(I.CONTINUATION, "answer", 0.8, ["pending:" + dlg.pending_type])
            reply = self._answer_pending_free(turn)
            if reply is not _UNHANDLED:
                return reply
            turn.intent = None
            dlg.clear_pending()
        last_kind = dlg.last["kind"] if dlg.last else None
        mention = False
        if turn.service is not None and turn.service.exists():
            mention = turn.service.find_capability(turn.norm) is not None
        intent = I.classify(turn.text, I.Context(None, last_kind, mention))
        if intent.kind == I.UNKNOWN:
            word = I.answer_word(turn.toks)
            if word:  # a bare yes / no / cancel while nothing is being asked
                intent = I.Intent(I.CONTINUATION, word, 0.6, ["no_pending_question"])
        turn.intent = intent
        if intent.is_(I.GREETING) and intent.slots.get("rest"):
            return self._compound_greeting(turn, intent)
        return self._dispatch(turn, intent)

    def _dispatch(self, turn, intent):
        kind, sub = intent.kind, intent.sub
        full = turn.full
        last_kind = turn.dlg.last["kind"] if turn.dlg.last else None
        try:
            if kind == I.GREETING:
                return self._social(turn, intent) if full else None
            if kind == I.FEEDBACK:
                if not full and last_kind not in ("invoke", "build"):
                    return None
                return self._feedback(turn, intent)
            if kind == I.COMMAND:
                return self._command(turn, intent)
            if kind == I.REQUEST and sub == "build":
                return self._build_request(turn, intent.slots["request"])
            if kind == I.REQUEST and sub == "build_unsupported":
                return M.unsupported_build()
            if kind == I.TEACHING:
                return self._teach_command(turn, intent) if full else None
            if kind == I.REFERENCE:
                return self._reference(turn, intent)
            if kind == I.CONTINUATION:
                return self._continue(turn, intent)
            return self._general(turn, intent)
        except Exception as e:
            self._log_error(e, turn.text)
            return M.unexpected_error()

    # ---------------------------------------------------------------- helpers
    def _kn(self):
        from knowledge.knowledge_system import KnowledgeSystem
        return KnowledgeSystem(self.memory)

    def _learning(self):
        from concepts.concept_system import ConceptSystem
        from learning.learning_system import LearningSystem
        kn = self._kn()
        return LearningSystem(ConceptSystem(kn), kn, memory=self.memory)

    def _user_name(self):
        try:
            rec = self._kn().get(NAME_FACT)
        except Exception:
            return None
        if rec is not None and rec["status"] == "active" and rec["description"]:
            return rec["description"]
        return None

    def _records(self, turn):
        return turn.service.capabilities() if turn.service is not None else []

    def _need_service(self):
        return "ثبت قابلیت‌ها در این اجرا در دسترس نیست (مسیر ذخیره‌سازی تعیین نشده)."

    # ============================================================== SOCIAL ==
    def _social(self, turn, intent):
        name = self._user_name()
        flavor = intent.slots.get("flavor")
        if intent.sub == "wellbeing":
            return M.wellbeing(name, flavor, turn.norm)
        if intent.sub == "thanks":
            return M.thanks(name)
        if intent.sub == "farewell":
            return M.farewell(name)
        return M.hello(name, flavor, turn.norm)

    def _compound_greeting(self, turn, intent):
        """«سلام، ...» followed by the real message."""
        rest = intent.slots["rest"]
        flavor = intent.slots.get("flavor")
        if turn.full:
            nlu = persian_nlu.analyze_persian(rest)
            if nlu.intent in (persian_nlu.INTENT_INTRODUCE_NAME, persian_nlu.INTENT_LIKE, persian_nlu.INTENT_DISLIKE):
                self._store_fact(nlu, turn.text)
                if nlu.intent == persian_nlu.INTENT_INTRODUCE_NAME:
                    return M.intro_name(nlu.entities["name"], flavor)
                item = nlu.entities["item"]
                verb = "دوست داری" if nlu.intent == persian_nlu.INTENT_LIKE else "دوست نداری"
                return f"سلام! باشه، یاد گرفتم که {item} را {verb}."
        sub = _Turn(rest, nz.normalize(rest), fa_text.words(nz.normalize(rest)), turn.dlg, turn.scope, turn.service)
        last_kind = turn.dlg.last["kind"] if turn.dlg.last else None
        mention = turn.service is not None and turn.service.exists() and \
            turn.service.find_capability(sub.norm) is not None
        inner = I.classify(rest, I.Context(None, last_kind, mention))
        turn.intent = inner
        sub.intent = inner
        if inner.is_(I.GREETING):
            return self._social(turn, intent) if turn.full else None
        reply = self._dispatch(sub, inner)
        if reply is None:
            return None
        if turn.full:
            name = self._user_name()
            return f"{M.hello_short(name, flavor)}\n{reply}"
        return reply

    # ================================================== personal-fact storage
    def _store_fact(self, nlu, text):
        """Same storage the application's own Persian-NLU step performs for
        'من X هستم' / 'من X را دوست دارم' (used only for the compound
        greeting, where the existing step never sees the sentence)."""
        learning, kn = self._learning(), self._kn()
        parts = {"name": NAME_FACT, "likes": LIKES_FACT, "dislikes": DISLIKES_FACT}
        for fact in nlu.facts:
            predicate, value = fact["predicate"], fact["value"]
            name = parts["name"] if predicate == "name" else f"{parts[predicate]}.{value}"
            learning.teach(name, value, source=NLU_SOURCE, confidence=nlu.confidence, source_text=text,
                           learning_method=NLU_SOURCE)
            existing = kn.get(name)
            if existing is not None and existing["status"] != "active":
                learning.set_status(name, "active", source=NLU_SOURCE)
            if predicate in ("likes", "dislikes"):
                other = f"{parts['dislikes' if predicate == 'likes' else 'likes']}.{value}"
                if kn.get(other) is not None:
                    learning.set_status(other, "inactive", source=NLU_SOURCE)

    # ============================================================= PENDING ==
    def _answer_pending(self, turn, word):
        """A yes / no / cancel to the pending question. Returns a reply or _UNHANDLED."""
        dlg = turn.dlg
        p = dlg.pending
        ptype, data = p["type"], p["data"]
        if word == "cancel":
            dlg.clear_pending()
            return M.cancelled()
        if word == "deny":
            dlg.clear_pending()
            if ptype == "confirm_teach":
                return M.statement_declined()
            return M.declined()
        # confirm
        dlg.clear_pending()
        if ptype == "confirm_build":
            req = request_parser.BuildRequest.from_dict(data["request"])
            return self._run_build(turn, req, data.get("text") or turn.text, confirmed=True)
        if ptype == "offer_build":
            return self._build_offered(turn, data)
        if ptype == "confirm_rollback":
            return self._do_rollback(turn, data.get("capability_id"), data.get("version"))
        if ptype == "confirm_disable":
            return self._do_disable(turn, data.get("capability_id"))
        if ptype == "confirm_teach":
            return self._teach_sentence(data.get("sentence") or "")
        if ptype in ("clarify_build", "ask_inputs"):
            dlg.set_pending(ptype, data, attempts=p["attempts"])  # a bare "yes" answers nothing here
            return _UNHANDLED
        return _UNHANDLED

    def _answer_pending_free(self, turn):
        """The answer to a clarification / missing-input question (free wording)."""
        dlg = turn.dlg
        p = dlg.pending
        if p["type"] == "clarify_build":
            return self._answer_clarify(turn, p)
        if p["type"] == "ask_inputs":
            return self._answer_inputs(turn, p)
        return _UNHANDLED  # yes/no style pending questions are not answered with free text

    def _looks_like_new_topic(self, turn):
        last_kind = turn.dlg.last["kind"] if turn.dlg.last else None
        mention = turn.service is not None and turn.service.exists() and \
            turn.service.find_capability(turn.norm) is not None
        other = I.classify(turn.text, I.Context(None, last_kind, mention))
        return other.kind in (I.COMMAND, I.GREETING, I.TEACHING, I.FEEDBACK) or \
            other.is_(I.REQUEST, "build") or other.is_(I.QUESTION, "likes") or \
            (other.kind == I.QUESTION and nz.ends_with_question(turn.norm))   # a typed question mark: «هر چی» is no question

    def _is_other_request(self, turn, cid):
        """A reply that is plainly a different request (a command, a greeting, a
        question another capability answers or the offer to build one) and so
        not the text the pending question was waiting for."""
        if self._looks_like_new_topic(turn):
            return True
        hit = matcher.match_invocation(turn.text, self._records(turn))
        return hit is not None and hit.get("capability_id") != cid

    @staticmethod
    def _is_new_build_request(text):
        """A whole sentence of its own - a build verb AND the thing to build («یک ماشین حساب بساز …») - is a new
        request, never the missing word of the old one (it must not become the NAME of a half-finished formula)."""
        markers = request_parser.build_markers(text)
        return "capability_noun" in markers and bool(markers & {"build_verb", "learn", "new_capability"})

    def _answer_clarify(self, turn, p):
        dlg = turn.dlg
        data = p["data"]
        if self._is_new_build_request(turn.text):
            return _UNHANDLED  # the open question is dropped and the sentence is handled as the new request it is
        pending = {"kind": data.get("kind"), "slots": data.get("slots") or {}, "missing": data.get("missing") or []}
        req = request_parser.merge_answer(pending, turn.text)
        progress = (req.kind != pending["kind"] or req.slots != pending["slots"]
                    or set(req.missing) < set(pending["missing"]) or req.status == request_parser.STATUS_READY)
        if req.status == request_parser.STATUS_READY:
            dlg.clear_pending()
            joined = ((data.get("text") or "") + " — " + turn.text)[:policy.MAX_REQUEST_CHARS]
            return self._run_build(turn, req, joined)
        if progress and req.status == request_parser.STATUS_CLARIFY:
            dlg.set_pending("clarify_build", {"kind": req.kind, "slots": req.slots, "missing": req.missing,
                                              "note": req.note, "text": data.get("text")}, attempts=0)
            return M.clarify(req)
        if self._looks_like_new_topic(turn):
            return _UNHANDLED
        attempts = dlg.bump_attempts()
        if attempts >= MAX_PENDING_ATTEMPTS or (pending["kind"] is None and attempts >= 2):
            dlg.clear_pending()
            return M.unsupported_build() if pending["kind"] is None else M.gave_up()
        return M.pending_retry(request_parser.BuildRequest(request_parser.STATUS_CLARIFY, pending["kind"],
                                                           pending["slots"], pending["missing"],
                                                           note=data.get("note")))

    def _answer_inputs(self, turn, p):
        dlg = turn.dlg
        data = p["data"]
        cid = data.get("capability_id")
        rec = turn.service.capability(cid) if turn.service is not None and cid else None
        if rec is None or rec.get("status") != CAP_ACTIVE or rec.get("version") is None:
            dlg.clear_pending()
            return M.unavailable(data.get("title") or cid or "")
        if data.get("need") == "text":
            if self._is_other_request(turn, cid):
                return _UNHANDLED
            _, payload = matcher.split_payload(turn.text)
            payload = payload if payload is not None else turn.text
            if len(payload) > policy.MAX_INVOKE_TEXT_CHARS or not payload.strip():
                return M.needs_text(rec)
            dlg.clear_pending()
            return self._invoke(turn, cid, {"text": payload})
        have = data.get("have") or {}
        fill = matcher.value_answer(rec, turn.text, have)
        if fill["kind"] is not None:  # a real answer: «قد ۱٫۷۵», «۷۰ و ۱٫۷۵» - not just a message with numbers in it
            if not fill["missing"]:
                dlg.clear_pending()
                inputs = {v["name"]: fill["values"][v["name"]] for v in rec["spec"]["variables"]}
                return self._invoke(turn, cid, inputs)
            if len(fill["values"]) > len(have):
                dlg.set_pending("ask_inputs", dict(data, have=fill["values"]), attempts=0)
                return M.needs_inputs(rec, [v["label"] for v in fill["missing"]], self._labelled(rec, fill["values"]))
        if self._is_other_request(turn, cid):
            return _UNHANDLED
        attempts = dlg.bump_attempts()
        if attempts >= MAX_PENDING_ATTEMPTS:
            dlg.clear_pending()
            return M.gave_up()
        return M.needs_inputs(rec, [v["label"] for v in fill["missing"]], self._labelled(rec, fill["values"]))

    @staticmethod
    def _labelled(rec, values):
        labels = {v["name"]: v["label"] for v in rec["spec"].get("variables", [])}
        return {labels.get(k, k): v for k, v in values.items()}

    # ================================================================ BUILD ==
    def _build_request(self, turn, req):
        if turn.service is None:
            return self._need_service()
        if req.status == request_parser.STATUS_READY:
            return self._run_build(turn, req, turn.text)
        turn.dlg.set_pending("clarify_build", {"kind": req.kind, "slots": req.slots, "missing": req.missing,
                                               "note": req.note, "text": turn.text[:policy.MAX_REQUEST_CHARS]})
        return M.clarify(req)

    def _run_build(self, turn, req, request_text, confirmed=False):
        service = turn.service
        if service is None:
            return self._need_service()
        result = service.build(request_text[:policy.MAX_REQUEST_CHARS], req, confirmed=confirmed)
        status = result.get("status")
        if status in (ST_APPLIED, ST_NOOP):
            rec = service.capability(result["capability_id"])
            turn.dlg.set_last("build", capability_id=result["capability_id"], title=result.get("title"),
                              version=result.get("version"))
            return M.build_applied(result, rec) if status == ST_APPLIED else M.build_noop(result, rec)
        if status == ST_CONFIRM:
            turn.dlg.set_pending("confirm_build", {"request": req.to_dict(), "text": request_text[:policy.MAX_REQUEST_CHARS]})
            return M.build_confirmation(result)
        return M.build_failed(result)

    def _build_offered(self, turn, data):
        """«بله» to «I do not have this - build it?», then the original question is answered."""
        archetype = data.get("archetype")
        req = request_parser.BuildRequest(request_parser.STATUS_READY, archetype, dict(data.get("slots") or {}))
        reply = self._run_build(turn, req, data.get("question") or turn.text)
        last = turn.dlg.last
        if not last or last.get("kind") != "build" or not last.get("capability_id"):
            return reply  # nothing was built: the reply already says why
        cid = last["capability_id"]
        if archetype == policy.ARCHETYPE_UNIT_CONVERSION and data.get("value") is not None:
            inputs = {"value": float(data["value"])}
        elif archetype == policy.ARCHETYPE_TEXT_TOOL and data.get("payload") is not None:
            inputs = {"text": data["payload"]}
        else:
            return reply
        answer = self._invoke(turn, cid, inputs)
        return f"{reply}\n\nجواب سؤالت:\n{answer}"

    # ================================================================ INVOKE ==
    def _invoke(self, turn, cid, inputs):
        service = turn.service
        out = service.invoke(cid, inputs)
        rec = service.capability(cid)
        title = (rec or {}).get("title") or cid
        if out.get("error") in ("no_registry", "not_active") and not out.get("ok"):
            return M.unavailable(title) + M.fallback_note(out.get("fallback"))
        if out.get("ok"):
            turn.dlg.set_last("invoke", capability_id=cid, title=title, inputs=inputs, version=out.get("version"))
            return M.invoke_ok(rec, inputs, out) + M.fallback_note(out.get("fallback"))
        turn.dlg.set_last("invoke", capability_id=cid, title=title, inputs=inputs, version=out.get("version"))
        return M.invoke_failed(rec, out) + M.fallback_note(out.get("fallback"))

    def _handle_match(self, turn, hit):
        service = turn.service
        status = hit["status"]
        if status == "invoke":
            return self._invoke(turn, hit["capability_id"], hit["inputs"])
        if status == "describe":
            rec = service.capability(hit["capability_id"])
            turn.dlg.set_last("describe", capability_id=hit["capability_id"], title=rec["title"])
            return M.capability_detail(rec)
        if status == "needs_inputs":
            rec = service.capability(hit["capability_id"])
            if hit.get("missing_names") == ["text"]:
                turn.dlg.set_pending("ask_inputs", {"capability_id": rec["id"], "need": "text", "title": rec["title"]})
                return M.needs_text(rec)
            have = hit.get("have") or {}
            turn.dlg.set_pending("ask_inputs", {"capability_id": rec["id"], "have": have, "title": rec["title"],
                                                "missing": hit.get("missing_names")})
            return M.needs_inputs(rec, hit["missing"], self._labelled(rec, have))
        if status == "gap":
            return self._offer_build(turn, hit)
        return None

    def _offer_build(self, turn, hit):
        archetype = hit["archetype"]
        data = {"archetype": archetype, "slots": hit["slots"], "question": turn.text[:policy.MAX_REQUEST_CHARS]}
        if archetype == policy.ARCHETYPE_UNIT_CONVERSION:
            a = units.UNITS[hit["slots"]["from_unit"]].display
            b = units.UNITS[hit["slots"]["to_unit"]].display
            data["value"] = hit.get("value")
            reply = M.offer_build_unit(a, b)
        else:
            from self_builder import textops
            data["payload"] = hit.get("text")
            reply = M.offer_build_text([textops.op_label(o) for o in hit["slots"]["ops"]])
        turn.dlg.set_pending("offer_build", data)
        return reply

    # ================================================================ GENERAL ==
    def _general(self, turn, intent):
        service = turn.service
        full = turn.full
        records = service.capabilities() if service is not None else []
        bad = service.unavailable() if service is not None else None
        if bad is not None:
            # the registry is on disk but cannot be opened: "I have it" / "I do not have it" cannot be said
            if (intent.is_(I.QUESTION, "capability") and service.match_question(turn.text) is not None) \
                    or matcher.match_invocation(turn.text, []) is not None:
                return M.registry_unavailable(bad["code"])
        if intent.is_(I.QUESTION, "capability") and service is not None:
            q = service.match_question(turn.text)
            if q is not None:
                return self._capability_question(turn, q)
        hit = matcher.match_invocation(turn.text, records)
        if hit is not None and service is not None:
            reply = self._handle_match(turn, hit)
            if reply is not None:
                return reply
        if not full:
            return None
        if intent.is_(I.QUESTION, "likes"):
            return self._likes()
        if intent.kind == I.QUESTION:
            return self._knowledge_answer(turn, intent)
        if intent.is_(I.STATEMENT, "assertion"):
            return self._statement(turn, intent)
        return None

    def _capability_question(self, turn, q):
        service = turn.service
        if q["status"] == "have":
            rec = service.capability(q["capability_id"])
            turn.dlg.set_last("describe", capability_id=rec["id"], title=rec["title"])
            return M.capability_exists(rec)
        if q["archetype"] == policy.ARCHETYPE_UNIT_CONVERSION:
            a = units.UNITS[q["slots"]["from_unit"]].display
            b = units.UNITS[q["slots"]["to_unit"]].display
            turn.dlg.set_pending("offer_build", {"archetype": q["archetype"], "slots": q["slots"],
                                                 "question": turn.text[:policy.MAX_REQUEST_CHARS]})
            return M.capability_missing(f"«تبدیل {a} به {b}»") + " ولی می‌توانم خودم بسازمش. بسازمش؟ (بله / نه)"
        from self_builder import textops
        labels = [textops.op_label(o) for o in q["slots"]["ops"]]
        turn.dlg.set_pending("offer_build", {"archetype": q["archetype"], "slots": q["slots"],
                                             "question": turn.text[:policy.MAX_REQUEST_CHARS]})
        return M.capability_missing(f"ابزار «{' و '.join(labels)}»") + " ولی می‌توانم خودم بسازمش. بسازمش؟ (بله / نه)"

    # ================================================================ COMMAND ==
    def _command(self, turn, intent):
        service = turn.service
        sub = intent.sub
        if sub == "help":
            return M.help_text()
        if service is None:
            return self._need_service()
        if sub in ("list", "history", "detail", "rollback", "disable"):
            bad = service.unavailable()
            if bad is not None:
                return M.capability_list_unavailable(bad["code"]) if sub == "list" \
                    else M.registry_unavailable(bad["code"])
        if sub == "list":
            q = service.match_question(turn.text)
            if q is not None:                  # the sentence names one concrete capability: answer about THAT one
                return self._capability_question(turn, q)
            records = service.capabilities()
            turn.dlg.set_last("list")
            return M.capability_list(records)
        if sub == "status":
            return M.status_report(service.status(), service.self_check() if service.exists() else None)
        if sub == "history":
            rec = service.find_capability(turn.norm) if service.exists() else None
            rows = service.history(rec["id"] if rec else None, limit=8)
            titles = {r["id"]: r["title"] for r in service.capabilities()}
            return M.history(rows, titles)
        if sub == "detail":
            rec = self._target(turn)
            if rec is None:
                return M.which_capability("توضیح بدهم") if service.has_active_capabilities() or service.exists() \
                    else M.no_registry()
            turn.dlg.set_last("describe", capability_id=rec["id"], title=rec["title"])
            return M.capability_detail(rec)
        if sub == "rollback":
            rec = self._target(turn, prefer_restorable=True)
            if rec is None:
                return M.which_capability("برگردانم") if service.exists() else M.no_registry()
            return self._do_rollback(turn, rec["id"], intent.slots.get("version"))
        if sub == "disable":
            rec = self._target(turn)
            if rec is None:
                return M.which_capability("غیرفعال کنم") if service.exists() else M.no_registry()
            turn.dlg.set_pending("confirm_disable", {"capability_id": rec["id"]})
            return M.ask_disable(rec)
        return None

    def _target(self, turn, prefer_restorable=False):
        """The capability a command is about: named in the sentence, else the
        last one talked about, else the only candidate."""
        service = turn.service
        if not service.exists():
            return None
        rec = service.find_capability(turn.norm)
        if rec is not None:
            return rec
        last = turn.dlg.last
        if last and last.get("capability_id"):
            rec = service.capability(last["capability_id"])
            if rec is not None:
                return rec
        candidates = [r for r in service.capabilities()
                      if r["status"] == CAP_ACTIVE and (not prefer_restorable or (r.get("rollback") or {}).get("restorable"))]
        return candidates[0] if len(candidates) == 1 else None

    def _do_rollback(self, turn, cid, version):
        service = turn.service
        if service is None or not cid:
            return M.no_registry()
        result = service.rollback(cid, to_version=version)
        if result.get("status") == ST_APPLIED:
            turn.dlg.set_last("rollback", capability_id=cid, title=result.get("title"), version=result.get("version"))
            return M.rollback_done(result)
        reply = M.rollback_failed(result)
        err = result.get("error") or {}
        if err.get("code") == "E_ROLLBACK_NO_TARGET":
            rec = service.capability(cid)
            if rec is not None and rec["status"] == CAP_ACTIVE:
                turn.dlg.set_pending("confirm_disable", {"capability_id": cid})
                reply += "\n" + M.ask_disable(rec)
        return reply

    def _do_disable(self, turn, cid):
        service = turn.service
        if service is None or not cid:
            return M.no_registry()
        result = service.disable(cid)
        if result.get("status") == ST_APPLIED:
            return M.disable_done(result)
        return M.disable_failed(result)

    # =============================================================== FEEDBACK ==
    def _feedback(self, turn, intent):
        last = turn.dlg.last
        service = turn.service
        rec, recorded = None, False
        if last and last.get("kind") in ("invoke", "build") and last.get("capability_id") and service is not None:
            rec = service.capability(last["capability_id"])
            if rec is not None and rec.get("version") is not None:
                recorded = service.feedback(rec["id"], rec["version"], intent.sub, turn.text[:200])
        if intent.sub == "positive":
            return M.feedback_positive(recorded)
        can_rollback = bool(rec and rec.get("status") == CAP_ACTIVE and (rec.get("rollback") or {}).get("restorable"))
        reply = M.feedback_negative(recorded, can_rollback)
        if can_rollback:
            turn.dlg.set_pending("confirm_rollback", {"capability_id": rec["id"]})
            reply += " " + M.ask_rollback(rec)
        return reply

    # ============================================================== REFERENCE ==
    def _reference(self, turn, intent):
        last = turn.dlg.last
        service = turn.service
        if not last or not last.get("capability_id") or service is None:
            return M.reference_missing() if turn.full else None
        rec = service.capability(last["capability_id"])
        if rec is None or rec.get("status") != CAP_ACTIVE or rec.get("version") is None:
            return M.unavailable(last.get("title") or last["capability_id"])
        previous = dict(last.get("inputs") or {})
        if intent.sub == "repeat":
            if not previous:
                return M.reference_missing()
            return self._invoke(turn, rec["id"], previous)
        kind = rec["kind"]
        toks = fa_text.words(turn.norm)
        nums = fa_text.scan_numbers(toks)
        if kind == policy.ARCHETYPE_UNIT_CONVERSION:
            if not nums:
                return M.reference_inputs_mismatch(rec)
            return self._invoke(turn, rec["id"], {"value": nums[0][2]})
        if kind == policy.ARCHETYPE_FORMULA:
            fill = matcher.fill_formula_inputs(rec, turn.text, None)
            values = dict(fill["values"])
            for var in fill["missing"]:
                if var["name"] in previous:
                    values[var["name"]] = previous[var["name"]]
            if any(v["name"] not in values for v in rec["spec"]["variables"]) or not fill["values"]:
                return M.reference_inputs_mismatch(rec)
            return self._invoke(turn, rec["id"], {v["name"]: values[v["name"]] for v in rec["spec"]["variables"]})
        _, payload = matcher.split_payload(turn.text)
        if payload is None:
            turn.dlg.set_pending("ask_inputs", {"capability_id": rec["id"], "need": "text", "title": rec["title"]})
            return M.needs_text(rec)
        return self._invoke(turn, rec["id"], {"text": payload})

    # ============================================================ CONTINUATION ==
    def _continue(self, turn, intent):
        if intent.sub != "more":
            # a bare yes/no with no open question: said honestly inside the application,
            # left alone in a plain library Core
            return M.no_pending() if turn.full else None
        last = turn.dlg.last
        if not last:
            return M.nothing_to_continue() if turn.full else None
        service = turn.service
        kind = last.get("kind")
        if kind in ("invoke", "build", "describe", "rollback") and last.get("capability_id") and service is not None:
            rec = service.capability(last["capability_id"])
            if rec is not None:
                if kind == "invoke":
                    return M.how_computed(rec)
                return M.more_about(rec)
        if kind == "knowledge":
            return M.more_knowledge(last.get("name") or "")
        if kind == "list" and service is not None:
            records = [r for r in service.capabilities() if r["status"] == CAP_ACTIVE]
            if records:
                return "\n\n".join(M.capability_detail(r) for r in records[:5])
        return M.nothing_to_continue() if turn.full else None

    # ============================================================== KNOWLEDGE ==
    def _likes(self):
        kn = self._kn()
        likes = self._facts_under(kn, LIKES_FACT)
        dislikes = self._facts_under(kn, DISLIKES_FACT)
        return M.likes_answer(likes, dislikes)

    @staticmethod
    def _facts_under(kn, prefix):
        pre = prefix + "."
        rows = kn.memory.query(
            "SELECT name, description FROM knowledge WHERE substr(name, 1, ?) = ? AND status = 'active' "
            "ORDER BY id", (len(pre), pre))
        return [r["description"] for r in rows if r["description"]]

    def _knowledge_answer(self, turn, intent):
        content = [t for t in intent.slots.get("content", []) if not fa_text.parse_number(t)]
        if not content:
            return None
        rows = self.memory.query(
            "SELECT name, description, source_text, status, source FROM knowledge WHERE status = 'active' "
            "ORDER BY updated_at DESC, id DESC LIMIT 2000")
        rows = [r for r in rows if not r["name"].startswith("کاربر.")]
        key = nz.match_key(" ".join(content))
        for r in rows:  # the question names a taught concept ("پایتون چیست؟")
            if nz.match_key(r["name"]) == key and r["description"]:
                turn.dlg.set_last("knowledge", name=r["name"])
                return M.definition_answer(r["name"], r["description"])
        wanted = set(content)
        best = None
        for r in rows:  # a taught sentence that contains every content word
            sentence = r["source_text"] or f"{r['name']} {r['description'] or ''}"
            have = set(fa_text.words(" ".join((r["name"], r["description"] or "", sentence))))
            if wanted <= have:
                extra = len(have - wanted)
                if best is None or extra < best[0]:
                    best = (extra, r, sentence)
        if best is not None:
            turn.dlg.set_last("knowledge", name=best[1]["name"])
            return M.knowledge_answer(self._clean_sentence(best[2]))
        return None

    @staticmethod
    def _clean_sentence(sentence):
        s = sentence.strip()
        return s if s.endswith((".", "!", "؟", "?")) else s + "."

    # =============================================================== TEACHING ==
    @staticmethod
    def _split_fact(sentence):
        """(subject, predicate) of a copular Persian sentence. The subject runs
        up to the first determiner («یک/یه»), otherwise it is the first word;
        the predicate (with its copula) is the rest."""
        toks = fa_text.words(sentence)
        if len(toks) < 3:
            return None
        cut = next((i for i, t in enumerate(toks) if i >= 1 and t in _DETERMINERS), 1)
        cut = min(cut, 3)
        return " ".join(toks[:cut]), " ".join(toks[cut:])

    def _teach_command(self, turn, intent):
        if intent.sub == "incomplete":
            return M.teach_incomplete()
        return self._teach_sentence(intent.slots.get("body") or "")

    def _teach_sentence(self, sentence):
        sentence = (sentence or "").strip(" .!؟?،")
        parts = self._split_fact(sentence)
        if parts is None:
            return M.teach_incomplete()
        subject, predicate = parts
        learning, kn = self._learning(), self._kn()
        before = kn.get(subject)
        learning.teach(subject, predicate, source=BRAIN_SOURCE, source_text=sentence, learning_method=BRAIN_SOURCE)
        entry = kn.get(subject)
        if entry is not None and entry["status"] != "active":
            learning.set_status(subject, "active", source=BRAIN_SOURCE)
        return M.teach_ok(sentence, updated=before is not None and before["description"] != predicate)

    def _statement(self, turn, intent):
        sentence = intent.slots.get("sentence") or ""
        if self._split_fact(sentence) is None:
            return None
        turn.dlg.set_pending("confirm_teach", {"sentence": sentence[:300]})
        return M.statement_ack(sentence)


# --------------------------------------------------------------- module API --
_BRAINS = weakref.WeakKeyDictionary()
_BRAINS_LOCK = threading.Lock()


def get_brain(memory):
    """The one brain of a MemorySystem (nothing is created on disk)."""
    with _BRAINS_LOCK:
        brain = _BRAINS.get(memory)
        if brain is None:
            brain = PersianBrain(memory)
            _BRAINS[memory] = brain
        return brain


def dynamic_skill(memory, text):
    """The 'skill' the SkillSystem hands to Core's step 1 when the brain
    answers `text` ({"name", "response", ...}), else None. Never raises."""
    try:
        scope = activation.scope_for(memory)
        if scope == activation.SCOPE_OFF:
            return None
        reply = get_brain(memory).respond(text, scope=scope)
    except Exception:
        return None
    if reply is None:
        return None
    return {"name": "persian_conversation", "description": "Persian conversation brain (dynamic skill)",
            "trigger": {"type": "dynamic"}, "response": reply, "dynamic": True}


__all__ = ["PersianBrain", "get_brain", "dynamic_skill"]
