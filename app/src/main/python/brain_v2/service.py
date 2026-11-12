"""
brain_v2.service - the cloud brain as the chat uses it
======================================================
`BrainV2` owns the user's decisions (`settings`), his key (`keyvault`), the short history and the one rule that matters: **a
request leaves the phone only when ALL of these hold at that very moment**

    1. the user switched the cloud brain on (mode "auto") and has not pressed the emergency stop;
    2. he said «بله» to sending his messages to THIS host (consent is bound to the host - changing provider asks again);
    3. the app's internet permission is on (the master switch he already has: «اینترنت را خاموش کن» stops everything);
    4. a key is stored;
    5. the message passed the privacy check (`privacy.check`) and the hourly cap is not used up.

The gate handed to the network layer re-evaluates 1-4 on every call (fail closed), so switching anything off takes effect at
once. Audit lines (`brain.*`) record the host, the outcome and character COUNTS - never a message, an answer or a key.
"""

import os
import threading
import time
import weakref
from collections import deque
from dataclasses import dataclass

from net_tools import NETWORK, CallableGate, FetchPolicy, post_json

from . import cloud, learned, persona, privacy, providers
from .history import History
from .keyvault import KeyVault
from .settings import Settings

__all__ = ["BrainV2", "BrainReply", "get_brain", "reset_brain", "DIRNAME", "MAX_CALLS_PER_HOUR", "MAX_QUESTION_CHARS", "MAX_AUTHOR_REQUEST_CHARS",
           "WRONG_WINDOW_S"]

DIRNAME = "brain_v2"
MAX_CALLS_PER_HOUR = 120
MAX_QUESTION_CHARS = 2000
MAX_AUTHOR_REQUEST_CHARS = 20_000      # the text of one authoring request (the user's wish + the app's own format instructions)
AUTHOR_TIMEOUT_S = 60.0                # a pack takes a model longer to write than a chat answer
AUTHOR_TOTAL_S = 180.0
WRONG_WINDOW_S = 24 * 3600          # «این جواب غلط بود» refers to the brain's answer only when that was the previous reply and is this fresh
_BRAINS = weakref.WeakKeyDictionary()
_BRAINS_LOCK = threading.Lock()


@dataclass(frozen=True)
class BrainReply:
    kind: str            # answer | memory | blocked | not_ready | halted | rate | too_long | failed
    text: str = ""
    code: str = ""       # not_ready: why; blocked: which kind of private thing; failed: cloud failure code
    reason_fa: str = ""
    detail: str = ""     # the provider's own short, key-free error message
    label_fa: str = ""
    secret: bool = False
    truncated: bool = False
    source: str = ""     # "cloud" | "memory"
    age_s: float = 0.0
    exact: bool = True   # memory: False when only filler words differed from the question that was kept
    kept: bool = False   # cloud: the answer was kept on the phone for next time
    first_keep: bool = False   # ... and this is the first time (the chat adds the one-time note)
    keep_reason: str = ""      # cloud: why it was NOT kept (see `learned.eligible`)


class BrainV2:
    def __init__(self, root, *, network_granted, transport=None, policy=None, audit=None, clock=time.time,
                 monotonic=time.monotonic):
        self.root = os.fspath(root)
        self._clock, self._mono = clock, monotonic
        self._network_granted = network_granted
        self._transport = transport
        self._policy = policy if policy is not None else FetchPolicy()
        self._audit = audit
        self.settings = Settings(os.path.join(self.root, "settings.json"), clock)
        self.vault = KeyVault(os.path.join(self.root, "key.dat"))
        self.history = History(os.path.join(self.root, "history.json"), clock)
        self.learned = learned.LearnedReplies(os.path.join(self.root, learned.FILE_NAME), clock)
        self._turn_answer = None      # what the brain answered in THIS turn (for «این جواب غلط بود»)
        self._prev_answer = None      # ... and in the previous turn
        self._calls = deque()
        self._lock = threading.RLock()
        self._busy = threading.Semaphore(2)
        self._gate = CallableGate(self._gate_allows)

    # ------------------------------------------------------------------ small helpers
    def note(self, event, subject="", **detail):
        """One audit line (kind `brain.<event>`); never raises; callers must not put text or keys in `detail`."""
        try:
            if self._audit is not None:
                self._audit.append("brain." + event, subject, detail)
        except Exception:
            pass

    def _provider(self, s=None):
        s = s or self.settings.get()
        return providers.get(s["provider"])

    def host(self, s=None):
        """The host requests would go to ('' when no provider is chosen)."""
        s = s or self.settings.get()
        return providers.host_of(providers.endpoint(s["provider"], s["base_url"])) if s["provider"] else ""

    def model(self, s=None):
        s = s or self.settings.get()
        provider = self._provider(s)
        return s["model"] or (provider.default_model if provider else "")

    def _consent_ok(self, s=None):
        s = s or self.settings.get()
        consent = s["consent"]
        return bool(consent) and bool(self.host(s)) and consent["host"] == self.host(s) and consent["provider"] == s["provider"]

    def _network_on(self):
        try:
            return bool(self._network_granted()) is True
        except Exception:
            return False

    def _gate_allows(self, permission):
        if permission != NETWORK:
            return False
        s = self.settings.get()
        return (s["mode"] == "auto" and not s["halted"] and self._consent_ok(s) and self._network_on() and self.vault.exists())

    # ------------------------------------------------------------------ state
    def ready(self):
        """(True, "ok") or (False, why) where why is one of: off, local, no_provider, no_consent, no_key, no_network, halted."""
        s = self.settings.get()
        if s["halted"]:
            return False, "halted"
        if s["mode"] == "off":
            return False, "off"
        if s["mode"] == "local":
            return False, "local"
        if not s["provider"] or not self.host(s):
            return False, "no_provider"
        if not self._consent_ok(s):
            return False, "no_consent"
        if not self.vault.exists():
            return False, "no_key"
        if not self._network_on():
            return False, "no_network"
        return True, "ok"

    def status(self):
        s = self.settings.get()
        ok, why = self.ready()
        provider = self._provider(s)
        return {"ready": ok, "why": why, "mode": s["mode"], "provider": s["provider"], "provider_title": provider.title_fa if provider else "",
                "host": self.host(s), "model": self.model(s), "model_is_default": not s["model"], "key": self.vault.masked(),
                "consent": self._consent_ok(s), "network": self._network_on(), "halted": s["halted"],
                "share_private": s["share_private"], "history": self.history.count(), "calls_last_hour": self._calls_in_hour(),
                "wire": provider.wire if provider else "", "memory_on": s["memory_on"], "learned": self.learned.count()}

    # ------------------------------------------------------------------ the user's decisions
    def choose_provider(self, provider_id, base_url=""):
        """Pick a provider. The old consent is dropped when the host changes (the user must agree to the NEW host). ValueError if invalid."""
        provider = providers.get(provider_id)
        if provider is None:
            raise ValueError("unknown provider")
        clean = ""
        if provider_id == providers.CUSTOM:
            clean, _ = providers.valid_custom_base(base_url)
            if not clean:
                raise ValueError("bad base url")
        old = self.settings.get()
        new_host = providers.host_of(providers.endpoint(provider_id, clean))
        changes = {"provider": provider_id, "base_url": clean, "model": ""}
        if old["consent"] is None or old["consent"]["host"] != new_host:
            changes["consent"] = None
            changes["mode"] = "off"
        self.settings.update(**changes)
        self.note("provider", new_host, provider=provider_id)
        return new_host

    def give_consent(self):
        """The user said «بله» to sending his messages to the chosen host. Returns the host ('' when nothing is chosen)."""
        s = self.settings.get()
        host = self.host(s)
        if not host:
            return ""
        self.settings.update(consent={"host": host, "ts": float(self._clock()), "provider": s["provider"]})
        self.note("consent", host, provider=s["provider"])
        return host

    def set_key(self, key):
        ok = self.vault.put(key)
        self.note("key_saved" if ok else "key_refused", self.host())
        return ok

    def forget_key(self):
        """Delete the key, switch the brain off, withdraw the consent and wipe the history."""
        gone = self.vault.forget()
        try:
            self.settings.update(mode="off", consent=None)
        except (ValueError, OSError):
            pass
        self.history.clear()
        self.note("key_forgotten", "", removed=gone)
        return gone

    def set_mode(self, mode):
        self.settings.update(mode=mode)
        self.note("mode", self.host(), mode=mode)

    def set_model(self, model):
        if model != "" and not providers.valid_model(model):
            raise ValueError("bad model")
        self.settings.update(model=model)
        self.note("model", self.host(), custom=bool(model))

    def set_share_private(self, value):
        self.settings.update(share_private=bool(value))
        self.note("private", self.host(), share=bool(value))

    def clear_history(self):
        n = self.history.clear()
        self.note("history_cleared", "", turns=n)
        return n

    def set_memory(self, on):
        """Switch the keeping of answers (for offline use) on or off. Already kept answers stay until they are cleared."""
        self.settings.update(memory_on=bool(on))
        self.note("memory", "", on=bool(on))

    def clear_learned(self):
        """Forget every kept answer; returns how many."""
        n = self.learned.clear()
        with self._lock:
            self._turn_answer = self._prev_answer = None
        self.note("memory_cleared", "", answers=n)
        return n

    # ------------------------------------------------------------------ «این جواب غلط بود»
    def begin_turn(self):
        """A new message of the user starts: what was answered in the turn before becomes 'the previous answer'."""
        with self._lock:
            self._prev_answer, self._turn_answer = self._turn_answer, None

    def _given(self, key, source):
        with self._lock:
            self._turn_answer = {"at": float(self._clock()), "key": tuple(key) if key else None, "source": source}

    def last_answer(self):
        """{"at", "key", "source"} of the answer the brain gave in the PREVIOUS turn (None when the previous reply was something else)."""
        with self._lock:
            prev = self._prev_answer
            if prev is None or not 0 <= float(self._clock()) - prev["at"] <= WRONG_WINDOW_S:
                return None
            return dict(prev)

    def forget_last_answer(self):
        """The user said the last answer was wrong. "dropped" when it was a kept answer and is now forgotten, "not_kept" when it was
        never kept (a new asking goes to the cloud brain again), None when the previous reply was not the brain's."""
        with self._lock:
            prev = self.last_answer()
            if prev is None:
                return None
            self._prev_answer = None
            if prev["key"] and self.learned.drop(prev["key"]):
                self.note("memory_dropped", "")
                return "dropped"
            return "not_kept"

    def halt(self):
        self.settings.update(halted=True)
        self.note("halt", "")

    def resume(self):
        self.settings.update(halted=False)
        self.note("resume", "")

    # ------------------------------------------------------------------ rate cap
    def _calls_in_hour(self):
        with self._lock:
            now = self._mono()
            while self._calls and now - self._calls[0] > 3600:
                self._calls.popleft()
            return len(self._calls)

    def _take_call(self):
        with self._lock:
            if self._calls_in_hour() >= MAX_CALLS_PER_HOUR:
                return False
            self._calls.append(self._mono())
            return True

    # ------------------------------------------------------------------ talking to the service
    def _post(self, url, payload, headers=None, secrets=()):
        return post_json(url, payload, headers=headers, gate=self._gate, policy=self._policy, transport=self._transport,
                         clock=self._mono, secrets=secrets)

    def _post_slow(self, url, payload, headers=None, secrets=()):
        return post_json(url, payload, headers=headers, gate=self._gate, policy=self._policy, transport=self._transport,
                         clock=self._mono, secrets=secrets, timeout_s=AUTHOR_TIMEOUT_S, total_timeout_s=AUTHOR_TOTAL_S,
                         max_bytes=1_048_576)

    def _call(self, system, messages, *, max_tokens, temperature, what, raw=False):
        """One request to the consented host; a CloudResult. Re-checks every condition at the moment of the call.
        `raw`: an authoring request (verbatim answer, more time, a bigger answer allowed)."""
        s = self.settings.get()
        provider = self._provider(s)
        key = self.vault.get()
        host = self.host(s)
        if provider is None or not key or not host or not self._consent_ok(s) or s["halted"] or s["mode"] != "auto":
            return cloud._failure("blocked", host, self._mono(), self._mono)
        with self._busy:
            result = cloud.ask(self._post_slow if raw else self._post, provider, s["base_url"], self.model(s), key, system, messages,
                               max_tokens=max_tokens, temperature=temperature, clock=self._mono, raw=raw)
        self.note(what, result.host or host, ok=result.ok, code=result.code, status=result.status, chars_in=result.in_chars,
                  chars_out=result.out_chars, ms=int(result.elapsed_s * 1000))
        return result

    def probe(self):
        """A tiny real request that proves key + host + model work. An empty answer with a good status still proves it."""
        ok, why = self.ready()
        if not ok:
            return cloud._failure("blocked", self.host(), self._mono(), self._mono)
        if not self._take_call():
            return cloud._failure("quota", self.host(), self._mono(), self._mono)
        result = self._call(persona.system_prompt(), [{"role": "user", "content": "فقط یک کلمه بنویس: سلام"}], max_tokens=400,
                            temperature=0.2, what="probe")
        if not result.ok and result.code == "empty":
            return cloud.CloudResult(True, "", "ok", result.status, result.host, result.elapsed_s, "", "", False, "", result.in_chars, 0)
        return result

    def reply(self, text):
        """The answer to one free sentence. Never raises. See `BrainReply.kind` for what the chat must do with each outcome."""
        try:
            return self._reply(str(text or ""))
        except Exception:
            return BrainReply("failed", code="internal", reason_fa=cloud.reason("internal")[0])

    def author(self, request_text, wish=""):
        """ONE tool-less request that asks the cloud brain to WRITE something the app's own validator will read (a pack). Never raises.

        `request_text` is built by the app (the user's wish + the live format instructions); `wish` is the user's own words, checked by
        the privacy filter like every message. No conversation history goes with it, the answer is not put into the history and not kept
        as a remembered answer, and nothing in it is ever executed here: the caller only READS it (the pack review, then the user's «بله»).
        Kinds: answer (text = the brain's reply, verbatim), halted, not_ready, too_long, blocked, rate, failed."""
        try:
            return self._author(str(request_text or ""), str(wish or ""))
        except Exception:
            return BrainReply("failed", code="internal", reason_fa=cloud.reason("internal")[0])

    def precheck(self, text):
        """None when `text` may go to the cloud brain, else the `BrainReply("blocked", ...)` that says WHICH kind of private thing it holds.
        Nothing is sent either way; the chat uses it to refuse BEFORE it asks the user to confirm a request. Never raises."""
        try:
            verdict = privacy.check(str(text or ""), self.settings.get()["share_private"])
        except Exception:
            return BrainReply("failed", code="internal", reason_fa=cloud.reason("internal")[0])
        if verdict.ok:
            return None
        self.note("blocked", "", kind=verdict.kind, what="precheck")
        return BrainReply("blocked", code=verdict.kind, label_fa=verdict.label_fa, secret=verdict.secret)

    def _author(self, request_text, wish):
        s = self.settings.get()
        if s["halted"]:
            return BrainReply("halted")
        ok, why = self.ready()
        if not ok:
            return BrainReply("not_ready", code=why)
        if not request_text.strip() or len(request_text) > MAX_AUTHOR_REQUEST_CHARS:
            return BrainReply("too_long", code="request")
        verdict = privacy.check(wish, s["share_private"])
        if not verdict.ok:
            self.note("blocked", "", kind=verdict.kind, what="author")
            return BrainReply("blocked", code=verdict.kind, label_fa=verdict.label_fa, secret=verdict.secret)
        if not self._take_call():
            return BrainReply("rate")
        result = self._call(persona.AUTHOR_FA, [{"role": "user", "content": request_text}], max_tokens=cloud.MAX_TOKENS_AUTHOR,
                            temperature=0.2, what="author", raw=True)
        if not result.ok:
            return BrainReply("failed", code=result.code, reason_fa=result.reason_fa, detail=result.detail)
        if result.truncated:
            self.note("author_cut", result.host, chars=len(result.text))
            return BrainReply("too_long", code="answer")
        return BrainReply("answer", text=result.text, source="cloud", keep_reason="author")

    def _recall(self, question, s):
        """An answer kept before, or None. Nothing leaves the phone: this works offline, with the cloud brain off, even without a key."""
        if not s["memory_on"]:
            return None
        hit = self.learned.find(question)
        if hit is None:
            return None
        self._given(hit.key, "memory")
        self.note("memory_hit", "", exact=hit.exact, uses=hit.uses)
        if privacy.check(question, s["share_private"]).ok:       # so that a follow-up question sent to the cloud has its context
            self.history.add(question, hit.answer, skip_repeat=True)
        return BrainReply("memory", text=hit.answer, source="memory", age_s=hit.age_s, exact=hit.exact)

    def _reply(self, text):
        s = self.settings.get()
        if s["halted"]:
            return BrainReply("halted")
        question = " ".join(text.split())
        if not question:
            return BrainReply("not_ready", code="off")
        recalled = self._recall(question, s)
        if recalled is not None:
            return recalled
        ok, why = self.ready()
        if not ok:
            return BrainReply("not_ready", code=why)
        if len(question) > MAX_QUESTION_CHARS:
            return BrainReply("too_long")
        verdict = privacy.check(question, s["share_private"])
        if not verdict.ok:
            self.note("blocked", "", kind=verdict.kind)
            return BrainReply("blocked", code=verdict.kind, label_fa=verdict.label_fa, secret=verdict.secret)
        if not self._take_call():
            return BrainReply("rate")
        messages = self.history.messages() + [{"role": "user", "content": question}]
        today = time.strftime("%Y-%m-%d", time.localtime(self._clock()))
        result = self._call(persona.system_prompt(today), messages, max_tokens=cloud.MAX_TOKENS_CHAT, temperature=0.4, what="ask")
        if not result.ok:
            return BrainReply("failed", code=result.code, reason_fa=result.reason_fa, detail=result.detail)
        self.history.add(question, result.text)
        kept = learned.Kept(False, "memory_off")
        if s["memory_on"] and not result.truncated:
            kept = self.learned.keep(question, result.text)
        elif s["memory_on"]:
            kept = learned.Kept(False, "truncated")
        self._given(kept.key if kept.ok else None, "cloud")
        first = False
        if kept.ok:
            self.note("memory_kept", "", chars=len(result.text))
            if not s["kept_note"]:
                try:
                    self.settings.update(kept_note=True)
                    first = True
                except (ValueError, OSError):
                    pass
        return BrainReply("answer", text=result.text, truncated=result.truncated, source="cloud", kept=kept.ok, first_keep=first,
                          keep_reason=kept.reason)


def get_brain(hub):
    """The cloud brain of a hub (created on first use; nothing is written to disk until the user decides something)."""
    if hub is None:
        return None
    with _BRAINS_LOCK:
        brain = _BRAINS.get(hub)
        if brain is None:
            ref = weakref.ref(hub)

            def network_granted():
                h = ref()
                return h is not None and h.permissions.is_granted("network")
            brain = BrainV2(os.path.join(hub.root, DIRNAME), network_granted=network_granted, transport=getattr(hub, "_transport", None),
                            policy=getattr(hub, "_policy", None), audit=hub.audit, clock=hub.clock)
            _BRAINS[hub] = brain
        return brain


def reset_brain(hub):
    with _BRAINS_LOCK:
        _BRAINS.pop(hub, None)
