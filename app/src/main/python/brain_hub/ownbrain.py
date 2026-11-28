"""
brain_hub.ownbrain - the assistant gets its OWN brain by itself
================================================================
The user's wish: an assistant that provides what it lacks FOR ITSELF - no key, no cost, no other AI service, nothing to download elsewhere
and hand over. For understanding free Persian that means a real language model living on the phone. This module is the part of the app that
fetches it, checks it, loads it and keeps an honest account of where that stands:

    consent («بله», given in the chat)  ->  download (resumable, only the hosts of the catalog, the file must equal the pinned SHA-256)
      ->  register the model (its card holds the real size and the pin)  ->  MOVE the verified file into the model store
      ->  `model_runtime`'s own pipeline: hash again, compatibility, load, a REAL test answer  ->  ready

What it never does
* nothing starts without the explicit consent flag, and the internet is open only for that one job: the gate it hands to the downloader
  answers "yes" only while the job runs, the user has not stopped it AND the app-wide internet switch (the one «اینترنت را خاموش کن» turns
  off) is on - so that switch really cuts this download too. The user's «بله» to the card that says so also turns that switch on (like the
  cloud brain's); a later «ادامه» never turns it on again by itself, and switching it off stops a running download at once (`net_off`);
* only the models of `ownbrain_catalog` (a hash read from the model's page) and only their hosts; a changed file is refused, not installed;
* it does not load a model again after the app died while loading it (`crashed_before`): the user decides («مغز را دوباره امتحان کن»);
* it never claims "ready" before the model produced a real answer; it never says what it could not verify;
* a model's answer is only text (see `llm.py`); nothing here runs anything it downloaded.

State survives a restart (`ownbrain_state`); a download the user agreed to continues by itself after the app is opened again (`tick`), a
download he stopped does not. One worker thread at most; every public method is safe to call from the chat thread and never raises.

The install step has its own account (Prompt 959, stage B3): after the download the model is checked once more, tested for compatibility, loaded
into the engine and asked a real question - minutes during which the user must see that something is going on. `status()["install"]` says which
of the four steps it is in, how far (`INSTALL_STEPS`) and for how long it has been going; only the file check can be MEASURED (bytes read), the
engine reports nothing while it loads the model and answers the first question, so for those the percent is an estimate from the time passed and
`estimated` says so. A heartbeat refreshes the listener (the notification) every couple of seconds while the step runs.
"""

import inspect
import os
import shutil
import socket
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from net_tools import CallableGate
from net_tools.permission import NETWORK
from net_tools.policy import classify_ip
from net_tools.resumable import discard_partial, download_resumable, partial_size

from . import ownbrain_catalog as catalog
from . import ownbrain_state as ST

__all__ = ["OwnBrain", "StartResult", "get_ownbrain", "IDLE_UNLOAD_SECONDS", "PROGRESS_NOTIFY_SECONDS", "RESUMABLE_FAILURES", "INSTALL_STEPS",
           "INSTALL_HEARTBEAT_SECONDS"]

IDLE_UNLOAD_SECONDS = 10 * 60          # the engine's memory (about 3 GB for the strong brain) is given back after this long without a question
PROGRESS_NOTIFY_SECONDS = 2.0
SAVE_EVERY_SECONDS = 5.0
JOIN_SECONDS = 15.0
GRACE_SECONDS = 3.0                    # a stop that the downloader does not see within this long (a dead connection) cuts the sockets
# failures after which what was already fetched is kept and "continue" makes sense
RESUMABLE_FAILURES = frozenset({"interrupted", "insufficient_space", "permission_denied", "io_error", "timeout", "offline", "dns_failure",
                                "connect_refused", "tls_error", "protocol_error", "http_error", "unknown_error", "too_many_redirects"})
_TEST_PROMPT = "سلام! خودت را در یک جمله‌ی کوتاه و ساده معرفی کن."
INSTALL_HEARTBEAT_SECONDS = 2.0        # while the install step runs the listener is told this often (the engine reports nothing for a long while)
# The install step as the user sees it, `(step, from_percent, to_percent, expected_seconds)`: the names are the stages of `ModelManager.prepare`. The
# file check (`expected_seconds` None) is MEASURED - bytes read / size of the file. The two engine steps report no progress at all, so their percent is
# an ESTIMATE from the time passed in the step: `elapsed / (elapsed + expected)` of the step's span, which climbs steadily, is halfway after
# `expected_seconds` and never reaches the end of the step before the step is really over (so "99%" is never said while it is still running).
INSTALL_STEPS = (("verify", 0, 30, None), ("compatibility", 30, 32, 2.0), ("load", 32, 82, 45.0), ("smoke", 82, 98, 20.0))
SLOW_FACTOR = 4.0                      # an estimated step that has lasted this many times its expected time is called slow (the text says so)
_NO_INSTALL = {"stage": "", "step": 0, "steps": len(INSTALL_STEPS), "percent": 0, "stage_percent": None, "elapsed": 0, "estimated": False,
               "slow": False}
_BLOCKED_IPS = 2                       # how many of the addresses behind a blocked download are written into the failure's detail


@dataclass(frozen=True)
class StartResult:
    ok: bool
    code: str                  # started | consent_required | unknown_choice | already_running | already_ready | have_other | engine_missing
    detail: str = ""           #   | ram_too_small | ram_unknown | not_enough_space | offline | nothing_to_resume | network_off | network_failed


class OwnBrain:
    def __init__(self, hub, *, catalog_choices=None, clock=None, monotonic=time.monotonic, sleep=time.sleep, meminfo=ST._MEMINFO,
                 usage_fn=None, downloader=None, notifier=None, idle_unload_seconds=IDLE_UNLOAD_SECONDS, use_thread=True, resolver=None):
        self._hub = hub
        self._choices = tuple(catalog_choices) if catalog_choices is not None else catalog.CHOICES
        self._clock = clock or getattr(hub, "clock", None) or time.time
        self._mono, self._sleep, self._meminfo = monotonic, sleep, meminfo
        self._usage_fn = usage_fn or getattr(hub, "_free_space_fn", None) or shutil.disk_usage
        self._downloader = downloader or download_resumable
        self._notifier = notifier
        self._resolver = resolver              # `getaddrinfo`-like; only used to name the address behind a blocked download (default: the system's)
        self._idle_s = float(idle_unload_seconds)
        self._use_thread = bool(use_thread)
        self._dir = os.path.join(hub.root, ST.DIR_NAME)
        self._file = ST.StateFile(self._dir, self._clock)
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._net_open = False
        self._sub = ""
        self._speed, self._last_sample, self._last_bytes = 0.0, 0.0, 0
        self._last_save = self._last_notify = 0.0
        self._pause_code = "user_paused"
        self._install = None                   # the install step's clock while it runs (see `_install_begin`)
        self._beat = None                      # the heartbeat's stop flag while the install step runs
        self._seq, self._delivered = 0, 0      # numbers the accounts handed to the listener: an older one never arrives after a newer one
        self._seq_lock, self._deliver_lock = threading.Lock(), threading.Lock()
        self._auto_done = False
        self._idle_timer = None
        self._gate = CallableGate(lambda permission: permission == NETWORK and self._net_open and self.network_on())
        self._state, note = self._file.load()
        self.state_note = note
        if self._state["phase"] in ("downloading", "installing"):           # the app was closed in the middle of it
            self._state.update(phase="paused", code="app_closed", detail="")
            self._file.save(self._state)

    # ================================================================== the catalog
    def choices(self):
        return self._choices

    def choice(self, key):
        return next((c for c in self._choices if c.key == key), None)

    def _by_model(self, model_id):
        return next((c for c in self._choices if c.model_id == model_id), None)

    # ================================================================== facts and plan
    def _engine(self):
        """`(available, code, reason_fa)` of the engine that runs a `.litertlm` model in THIS build."""
        try:
            for row in self._hub.model_runtimes_info():
                if "litertlm" in (row.get("formats") or ()):
                    return bool(row.get("available")), str(row.get("code") or ""), str(row.get("reason_fa") or "")
        except Exception:
            pass
        return False, "no_runtime_for_format", ""

    def _engine_api(self):
        """The engine's real class and signature listing (only present when the engine does not match the app: see `model_runtimes_info`)."""
        try:
            for row in self._hub.model_runtimes_info():
                if "litertlm" in (row.get("formats") or ()):
                    return str(row.get("api") or "")[:1500]
        except Exception:
            pass
        return ""

    def _online(self):
        try:
            return str(self._hub.network_status().state)
        except Exception:
            return "unknown"

    def network_on(self):
        """Is the app-wide internet switch (the one «اینترنت را روشن / خاموش کن» changes) on? A switch that cannot be read counts as off."""
        try:
            return bool(self._hub.permissions.is_granted(NETWORK))
        except Exception:
            return False

    def _allow_internet(self):
        """The user's «بله» also switches the app's internet on (the card says so): without it not a byte could be fetched. None when the switch is
        on afterwards; otherwise the refusal (nothing was changed and nothing starts)."""
        if self.network_on():
            return None
        try:
            self._hub.grant_permission(NETWORK, user_approved=True)
        except Exception:
            pass
        return None if self.network_on() else StartResult(False, "network_failed")

    def _needs_internet_but_off(self, choice):
        """More has to be downloaded (the whole file is not in the model store yet) and the app's internet switch is off."""
        return not self.network_on() and not self._file_on_phone(choice)

    def partial_bytes(self, choice):
        return partial_size(self._dir, choice.rel_dest)

    def facts(self):
        """What this phone has: `{ram, free, engine_ok, engine_code, engine_reason_fa, online}` (a number that cannot be read is 0); `engine_api`
        (the engine's real classes and signatures) is added only when the engine does not match the app (`api_mismatch`)."""
        facts = ST.device_facts(self._dir, self._usage_fn, self._meminfo)
        ok, code, reason = self._engine()
        facts.update(engine_ok=ok, engine_code=code, engine_reason_fa=reason, online=self._online())
        if code == "api_mismatch":
            facts["engine_api"] = self._engine_api()
        return facts

    def plan(self):
        """The offer for THIS phone: `{facts, options: [{key, fit, need, have_partial, recommended}], recommended}`. Nothing is started."""
        facts = self.facts()
        options, best = [], None
        for choice in self._choices:
            partial = self.partial_bytes(choice)
            fit = catalog.fits(choice, facts["ram"], facts["free"], partial)
            options.append({"key": choice.key, "fit": fit.code, "need": fit.need_bytes, "partial": partial, "recommended": False})
        pick = catalog.recommend(facts["ram"], facts["free"], 0) if self._choices is catalog.CHOICES else None
        if pick is None:                                                    # a custom catalog (tests): the first one that fits
            pick = next((c for c, o in zip(self._choices, options) if o["fit"] == "ok"), None)
        if pick is not None:
            best = pick.key
            for option in options:
                option["recommended"] = option["key"] == best
        return {"facts": facts, "options": options, "recommended": best or ""}

    # ================================================================== state
    def _set(self, **changes):
        with self._lock:
            self._state.update(changes)
            self._file.save(self._state)
            self._last_save = self._mono()
        self._notify(force=True)

    def set_notifier(self, notifier):
        """Who hears about every change of the job: `notifier(status_dict)` - the body's foreground service (Prompt 959, stage B) - or None for
        nobody. It is called from the download thread and from the chat thread, so it must be quick; an exception in it is swallowed."""
        self._notifier = notifier if callable(notifier) else None

    def _notify(self, force=False):
        notifier = self._notifier
        if notifier is None:
            return
        now = self._mono()
        if not force and now - self._last_notify < PROGRESS_NOTIFY_SECONDS:
            return
        self._last_notify = now
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        try:
            account = self.status()
        except Exception:
            return
        with self._deliver_lock:                                            # the heartbeat and the worker both tell the listener: the newer account wins
            if seq < self._delivered:
                return
            self._delivered = seq
            try:
                notifier(account)
            except Exception:
                pass

    def _running(self):
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def status(self, deep=False):
        """The honest account: `{phase, sub, choice, title_fa, model_id, bytes, total, percent, speed, eta, code, detail, resumable, consent, install}`.
        `install` is `{stage, step, steps, percent, stage_percent, elapsed, estimated, slow}` while the phase is "installing" (see `INSTALL_STEPS`) and
        all zeros otherwise; `percent` (the download's) stays 100 during the install. `deep=True` also asks the model manager whether a model
        recorded as ready really is (it may have been removed by another command)."""
        if deep:
            self._reconcile()
        with self._lock:
            state = dict(self._state)
            sub = self._sub if self._running() else ""
        choice = self.choice(state["choice"])
        have, total = state["bytes"], state["total"]
        if choice is not None:
            if state["phase"] in ("paused", "failed", "idle") and not have:
                have = self.partial_bytes(choice)
            elif state["phase"] == "paused":                                # the file on the disk is the truth (the progress report lags by a step)
                have = max(have, self.partial_bytes(choice))
            if not total:
                total = choice.exact_size or choice.size_hint
        percent = max(0, min(100, int(have * 100 / total))) if total else 0
        if state["phase"] == "ready":
            percent = 100
        speed = int(self._speed) if state["phase"] == "downloading" and sub == "download" else 0
        eta = int((total - have) / speed) if speed > 0 and total > have else None
        return {"phase": state["phase"], "sub": sub, "choice": state["choice"], "title_fa": choice.short_fa if choice else "",
                "model_id": state["model_id"] or (choice.model_id if choice else ""), "bytes": have, "total": total, "percent": percent,
                "speed": speed, "eta": eta, "code": state["code"], "detail": state["detail"], "consent": bool(state["consent_at"]),
                "resumable": bool(choice and (state["phase"] == "paused" or (state["phase"] == "failed" and self._resumable(state)))),
                "install": self._install_view(state["phase"])}

    def _resumable(self, state):
        choice = self.choice(state["choice"])
        return bool(choice and (state["code"] in RESUMABLE_FAILURES or state["code"] == "app_closed") and self.partial_bytes(choice) > 0)

    def _reconcile(self):
        """A brain recorded as ready whose model is gone or no longer usable is not ready (the model commands of the app can remove it)."""
        with self._lock:
            state = dict(self._state)
        if state["phase"] != "ready" or self._running():
            return
        try:
            status = self._hub.model_status(state["model_id"])
        except Exception:
            return
        if status.usable or status.state in ("usable",):
            return
        if status.state == "unregistered":
            self._set(phase="idle", choice="", model_id="", bytes=0, total=0, code="", detail="removed", consent_at=0.0, ready_at=0.0)
            return
        code = str(status.code or "")
        if code in ("", "ok"):                                              # "ok" is how a healthy but not loaded model reports itself
            code = "not_usable"
        try:
            from model_runtime.litertlm_runtime import crash_guard_active
            path = self._hub.model_file_path(state["model_id"])
            if path and crash_guard_active(path):                           # the last load never finished: the user decides about another try
                code = "crashed_before"
        except Exception:
            pass
        self._set(phase="failed", code=code[:60], detail=str(status.stage or "")[:60])

    # ================================================================== starting, stopping
    def _file_on_phone(self, choice):
        """Is the whole (verified) model file already in the model store? Then nothing more is downloaded: no free space and no internet are needed
        for it. A model that FAILED after its file was stored (the engine could not load it, the first answer failed) still has its file; the
        pipeline reopens it instead of downloading again, so it counts too - as long as the file really is there."""
        try:
            state = self._hub.model_status(choice.model_id).state
            if state in ("downloaded", "verified", "compatible", "usable"):
                return True
            if state == "failed":
                path = self._hub.model_file_path(choice.model_id)
                return bool(path) and os.path.isfile(path) and not os.path.islink(path) and os.path.getsize(path) > 0
        except Exception:
            return False
        return False

    def file_on_phone(self, choice=None):
        """Is the whole model file of `choice` (default: the brain of the job) already in the model store? Then a retry installs it and does not
        download anything. False when there is no such brain."""
        choice = choice or self.choice(self._state["choice"])
        return bool(choice is not None and self._file_on_phone(choice))

    def _preflight(self, choice):
        facts = self.facts()
        if not facts["engine_ok"]:
            return StartResult(False, "engine_missing", facts["engine_code"])
        fit = catalog.fits(choice, facts["ram"], facts["free"], self.partial_bytes(choice))
        if not fit.ok and not (fit.code == "not_enough_space" and self._file_on_phone(choice)):   # memory still counts: the model must be loaded
            return StartResult(False, fit.code, "%d/%d" % (fit.have_bytes, fit.need_bytes))
        if facts["online"] == "offline":
            return StartResult(False, "offline", "")
        return None

    def start(self, choice_key, *, consent=False):
        """Begin fetching the brain `choice_key`. Needs `consent=True` (the user's explicit «بله» to the card that named the size and the cost)."""
        if consent is not True:
            return StartResult(False, "consent_required")
        choice = self.choice(choice_key)
        if choice is None:
            return StartResult(False, "unknown_choice")
        with self._lock:
            if self._running():
                return StartResult(False, "already_running")
            state = self._state
            if state["phase"] == "ready":
                return StartResult(False, "already_ready" if state["choice"] == choice.key else "have_other", state["choice"])
            blocked = self._preflight(choice)
            if blocked is not None:
                return blocked
            if not self._file_on_phone(choice):                              # the «بله» covers the internet switch too (the card says so)
                blocked = self._allow_internet()
                if blocked is not None:
                    return blocked
            if state["choice"] and state["choice"] != choice.key:           # a half or failed brain of the other kind: its leftovers go
                self._discard_choice(self.choice(state["choice"]))
            self._cancel.clear()
            self._set(choice=choice.key, phase="downloading", consent_at=float(self._clock()), code="", detail="", bytes=self.partial_bytes(choice),
                      total=0, model_id=choice.model_id, ready_at=0.0)
            self._launch(choice)
        return StartResult(True, "started")

    def resume(self):
        """Continue a stopped, interrupted or failed-but-resumable job (the user's earlier consent still stands: it is the same job)."""
        with self._lock:
            state = self._state
            choice = self.choice(state["choice"])
            if choice is None or not state["consent_at"]:
                return StartResult(False, "nothing_to_resume")
            if self._running():                                             # it is already going (never "there is nothing to continue")
                return StartResult(False, "already_running")
            if state["phase"] not in ("paused", "failed"):
                return StartResult(False, "nothing_to_resume")
            blocked = self._preflight(choice)
            if blocked is not None:
                return blocked
            if self._needs_internet_but_off(choice):                         # the user switched it off: only he switches it on again
                return StartResult(False, "network_off")
            self._cancel.clear()
            self._set(phase="downloading", code="", detail="", bytes=self.partial_bytes(choice))
            self._launch(choice)
        return StartResult(True, "started")

    def retry(self):
        """After a failure that is not about the download (the model would not load, the test answer failed, the app died while loading):
        forget the unfinished-load marker and run the checks again. The user's explicit «مغز را دوباره امتحان کن». When the file is NOT on the
        phone (the download itself failed) there is nothing to check: the download starts again, and the phase says "downloading", not "installing"."""
        with self._lock:
            state = self._state
            choice = self.choice(state["choice"])
            if choice is None or not state["consent_at"]:
                return StartResult(False, "nothing_to_resume")
            if self._running():
                return StartResult(False, "already_running")
            if state["phase"] not in ("failed", "paused", "ready"):
                return StartResult(False, "nothing_to_resume")
            if self._needs_internet_but_off(choice):
                return StartResult(False, "network_off")
            on_phone = self._file_on_phone(choice)
            self._reset_guard(choice)
            self._cancel.clear()
            if on_phone:
                self._set(phase="installing", code="", detail="")
            else:
                self._set(phase="downloading", code="", detail="", bytes=self.partial_bytes(choice))
            self._launch(choice)
        return StartResult(True, "started")

    def wait(self, timeout=None):
        """Block until the worker has finished (tests, and `cancel`). True when no job is running any more."""
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        return not self._running()

    def _downloading(self):
        """Is a DOWNLOAD (not the install and test that follow it) in progress in the worker right now?"""
        with self._lock:
            return self._running() and self._state["phase"] == "downloading"

    @staticmethod
    def _cut_sockets():
        """Cut every network request in flight. The downloader, told to stop, then reports the stop and keeps what it fetched."""
        try:
            from net_tools.transport import abort_all
            return abort_all()
        except Exception:
            return 0

    def _stop_download(self, code, *, immediately):
        """Ask the worker to stop and wait until its DOWNLOAD has ended. The downloader looks at the stop flag between chunks, but a worker that
        sits in a read of a dead connection cannot: after a short grace period - at once for the emergency stop - the sockets are cut. Never
        waits for the install step (nothing interrupts a model that is loading). Real time is used on purpose: these are deadlines of the phone."""
        self._pause_code = code
        self._cancel.set()
        cut = bool(immediately)
        if cut:
            self._cut_sockets()
        started = time.monotonic()
        while self._downloading() and time.monotonic() - started < JOIN_SECONDS:
            if not cut and time.monotonic() - started >= GRACE_SECONDS:
                self._cut_sockets()
                cut = True
            self.wait(0.05)
        self.wait(1.0)                                                      # the worker's last moments (a thread that has already answered the stop)
        self._net_open = False

    def cancel(self):
        """Stop the download the user asked to stop. What was fetched stays (continue later with `resume`). True when a download was running; False
        when there was none - also while the finished file is being installed and tested, which cannot be interrupted."""
        if not self._downloading():
            return False
        self._stop_download("user_paused", immediately=False)
        return True

    def halt(self):
        """The emergency stop («ایست»): stop a running download at once (sockets cut); what was fetched stays. True when a download was running.
        Only a download is stopped - a model that is loaded and answering is never killed by it (the engine has its own `cancel`)."""
        if not self._downloading():
            return False
        self._stop_download("halted", immediately=True)
        return True

    def net_off(self):
        """The app's internet switch was turned off («اینترنت را خاموش کن»): a running download stops at once - the sockets are cut - and what was
        fetched stays. True when a download was running (the install and the first test use no network and are left alone)."""
        if not self._downloading():
            return False
        self._stop_download("net_off", immediately=True)
        return True

    def resume_after_halt(self):
        """The word that ends an emergency stop («ادامه») also continues a download that THAT stop paused - and nothing else (a download the
        user stopped himself stays stopped). A `StartResult`, or None when there was nothing of that kind."""
        with self._lock:
            state = self._state
            if state["phase"] == "paused" and state["code"] == "halted" and state["consent_at"] and state["choice"]:
                return self.resume()
        return None

    def footprint(self):
        """Bytes this brain holds on the phone now (the model and an unfinished download) - what «پاک کن» would free."""
        held = 0
        for choice in self._choices:
            held += self._model_bytes(choice) + self.partial_bytes(choice)
        return held

    def delete(self):
        """Remove the brain completely - the model, an unfinished download, the record - and say what was freed. The user's explicit order.
        `{freed, had, busy}`: `busy` is True (and nothing was removed) while the finished file is being installed and tested - that step cannot
        be interrupted, and nothing is removed from under it; the order can be given again when it has ended."""
        self.cancel()
        if self._running():
            return {"freed": 0, "had": True, "busy": True}
        freed = 0
        with self._lock:
            state = dict(self._state)
        for choice in self._choices:
            freed += self._model_bytes(choice) + self.partial_bytes(choice)
            self._discard_choice(choice)
        self._file.remove()
        with self._lock:
            self._state = ST.default_state()
            self._sub = ""
        self._cancel_idle()
        return {"freed": freed, "had": bool(state["choice"]), "busy": False}

    def _model_bytes(self, choice):
        try:
            status = self._hub.model_status(choice.model_id)
            return int((status.file or {}).get("size") or 0)
        except Exception:
            return 0

    def _discard_choice(self, choice):
        if choice is None:
            return
        try:
            self._hub.cancel_model_generation()
            self._hub.remove_model(choice.model_id)
        except Exception:
            pass
        discard_partial(self._dir, choice.rel_dest)
        try:
            os.rmdir(os.path.dirname(os.path.join(self._dir, choice.rel_dest)))      # its (now empty) folder goes too
        except OSError:
            pass

    def _reset_guard(self, choice):
        try:
            from model_runtime.litertlm_runtime import reset_crash_guard
            path = self._hub.model_file_path(choice.model_id)
            if path:
                reset_crash_guard(path)
        except Exception:
            pass

    # ================================================================== the worker
    def _launch(self, choice):
        if not self._use_thread:
            self._worker(choice)
            return
        thread = threading.Thread(target=self._worker, args=(choice,), name="own-brain", daemon=True)
        self._thread = thread
        try:
            thread.start()
        except RuntimeError:
            self._thread = None
            self._install_end()
            self._set(phase="failed", code="no_thread", detail="")

    def _worker(self, choice):
        try:
            self._pipeline(choice)
        except Exception as exc:                                            # the job can never take the app down; the account says what happened
            self._net_open = False
            self._set(phase="failed", code="unexpected_error", detail=type(exc).__name__)
        finally:
            self._net_open = False
            self._sub = ""
            self._install_end()

    def _on_progress(self, phase, done, total):
        now = self._mono()
        with self._lock:
            self._sub = "verify" if phase == "verify" else "download"
            self._state["bytes"] = int(done)
            if total:
                self._state["total"] = int(total)
            if phase != "verify":
                dt = now - self._last_sample if self._last_sample else 0.0
                if self._last_sample == 0.0 or done < self._last_bytes:
                    self._last_sample, self._last_bytes = now, int(done)
                elif dt >= 1.0:
                    instant = (int(done) - self._last_bytes) / dt
                    self._speed = instant if self._speed == 0.0 else 0.8 * self._speed + 0.2 * instant
                    self._last_sample, self._last_bytes = now, int(done)
            if now - self._last_save >= SAVE_EVERY_SECONDS:
                self._file.save(self._state)
                self._last_save = now
        self._notify()

    def _card(self, choice, size):
        return {"model_id": choice.model_id, "title": choice.title, "version": choice.version, "format": "litertlm", "source_url": choice.url,
                "sha256": choice.sha256, "size_bytes": int(size), "license": choice.license, "languages": list(choice.languages),
                "runtime_hint": "litertlm", "min_free_mb": 0, "notes": "own brain (fetched by the app itself)"}

    def _fail(self, code, detail=""):
        self._set(phase="failed", code=str(code)[:60], detail=str(detail)[:120])

    def _should_stop(self):
        """The downloader's stop flag, looked at between chunks: the user's stop, or the app's internet switch turned off meanwhile."""
        return self._cancel.is_set() or not self.network_on()

    def _download(self, choice):
        """True when the verified file is on the phone; otherwise the state already says why."""
        self._net_open, self._sub, self._speed, self._last_sample = True, "download", 0.0, 0.0
        try:
            result = self._downloader(choice.url, self._dir, choice.rel_dest, gate=self._gate, expected_sha256=choice.sha256,
                                      size_hint=choice.size_hint, max_bytes=choice.max_bytes, policy=getattr(self._hub, "_policy", None),
                                      transport=getattr(self._hub, "_download_transport", None), progress=self._on_progress,
                                      should_cancel=self._should_stop, allowed_hosts=catalog.ALLOWED_HOSTS, free_space_fn=self._usage_fn,
                                      size_tolerance=choice.tolerance, sleep=self._sleep)
        finally:
            self._net_open = False
        if result.ok:
            return True
        if result.code == "cancelled":                                      # the user's stop - or the app's internet switch turned off meanwhile
            self._set(phase="paused", code=self._pause_code if self._cancel.is_set() else "net_off", detail="", bytes=self.partial_bytes(choice))
        else:
            detail = str(result.detail or "")
            if result.code == "blocked_address":
                detail = self._blocked_detail(choice, detail)
            self._set(phase="failed", code=str(result.code)[:60], detail=detail[:120], bytes=self.partial_bytes(choice))
        return False

    def _blocked_detail(self, choice, detail):
        """`blocked_address` says only that the address the phone's name lookup gave for the model's site is not a public one. WHICH address decides
        what is wrong (a VPN's, the provider's block page, ...) and the user cannot see it, so it is written into the failure's detail:
        «private ip=10.10.34.34». The lookup is the same one the download just made (the catalog's own host, never anything else), made again only
        while the app's internet switch is on; what cannot be found is left out. Never raises."""
        try:
            if not self.network_on():
                return detail
            host = urlsplit(choice.url).hostname or ""
            if host not in catalog.ALLOWED_HOSTS:
                return detail
            rows = (self._resolver or socket.getaddrinfo)(host, 443, type=socket.SOCK_STREAM)
            found = []
            for row in rows:
                ip = str(row[4][0]).split("%", 1)[0]
                if ip not in found and classify_ip(ip) != "public":
                    found.append(ip)
            return ("%s ip=%s" % (detail, ",".join(found[:_BLOCKED_IPS]))).strip() if found else detail
        except Exception:
            return detail

    def _pipeline(self, choice):
        hub, model_id = self._hub, choice.model_id
        status = hub.model_status(model_id)
        state = status.state
        if status.usable:
            return self._ready(choice)
        if state == "failed":
            if hub.reopen_model(model_id).ok:
                state = "downloaded"
            else:                                                           # no file to try again with: start over from the download
                hub.remove_model(model_id)
                state = "unregistered"
        if state in ("unregistered", "registered"):
            if self._state["phase"] != "downloading":                       # a retry that has to fetch the file again must not call it "installing"
                self._set(phase="downloading", code="", detail="", bytes=self.partial_bytes(choice))
            if not self._download(choice):
                return None
            self._install_begin()
            self._set(phase="installing", code="", detail="", bytes=self._state["total"] or self._state["bytes"])
            path = os.path.join(self._dir, choice.rel_dest)
            try:
                size = os.path.getsize(path)
            except OSError:
                return self._fail("io_error", "downloaded_file")
            registered = hub.register_model(self._card(choice, size))
            if not registered.ok:
                return self._fail(registered.code or "register_failed", "register")
            adopted = hub.adopt_model_file(model_id, path)
            if not adopted.ok:
                return self._fail(adopted.code or "adopt_failed", "adopt")
            try:
                os.rmdir(os.path.dirname(path))                             # the file moved into the model store: its empty folder goes
            except OSError:
                pass
        else:
            self._install_begin()
            self._set(phase="installing", code="", detail="")
        report = self._prepare(model_id)
        if getattr(report, "ok", False) and getattr(report.status, "usable", False):
            return self._ready(choice)
        last = report.stages[-1] if getattr(report, "stages", None) else None
        return self._fail(getattr(last, "code", "") or report.status.code or "prepare_failed", getattr(last, "stage", ""))

    def _ready(self, choice):
        self._set(phase="ready", code="", detail="", model_id=choice.model_id, ready_at=float(self._clock()))
        self.touch()

    # ================================================================== the install step's account (Prompt 959, stage B3)
    def _prepare(self, model_id):
        """The model pipeline (verify, compatibility, load, the real first answer) with the install account listening. A hub whose `prepare_model`
        takes no progress function (an older one) is called the old way."""
        prepare = self._hub.prepare_model
        try:
            listens = "progress" in inspect.signature(prepare).parameters
        except (TypeError, ValueError):
            listens = False
        return prepare(model_id, progress=self._install_progress) if listens else prepare(model_id)

    def _install_begin(self):
        """The install step starts: from now on `status()["install"]` has the clock, and a heartbeat refreshes the listener while it runs."""
        now = self._mono()
        with self._lock:
            if self._install is not None:
                return
            self._install = {"started": now, "stage": "", "stage_started": now, "fraction": None, "floor": 0.0}
        self._start_heartbeat()

    def _install_progress(self, stage, fraction=None, done=0, total=0):
        """`ModelManager.prepare`'s progress function: which step the pipeline is in now and, for the file check, how much of the file is read
        (`fraction` 0..1; None for the steps that cannot be measured). Never raises."""
        try:
            now, changed = self._mono(), False
            with self._lock:
                inst = self._install
                if inst is None:
                    return
                if stage != inst["stage"]:
                    inst["stage"], inst["stage_started"], changed = str(stage), now, True
                number = isinstance(fraction, (int, float)) and not isinstance(fraction, bool) and fraction == fraction
                inst["fraction"] = max(0.0, min(1.0, float(fraction))) if number else None
            self._notify(force=changed)
        except Exception:
            pass

    def _install_view(self, phase):
        """The dict under `status()["install"]` (see `INSTALL_STEPS`); all zeros unless the phase is "installing" and the step has begun."""
        with self._lock:
            inst = self._install
            if phase != "installing" or inst is None:
                return dict(_NO_INSTALL)
            now = self._mono()
            elapsed = max(0.0, now - inst["started"])
            names = [row[0] for row in INSTALL_STEPS]
            if inst["stage"] not in names:                                  # registering / moving the file: instant, no step of its own
                return dict(_NO_INSTALL, elapsed=int(elapsed))
            index = names.index(inst["stage"])
            _name, low, high, expected = INSTALL_STEPS[index]
            in_step = max(0.0, now - inst["stage_started"])
            if expected is None:                                            # measured
                fraction, estimated, slow = inst["fraction"] or 0.0, False, False
            else:                                                           # estimated from the time passed
                fraction, estimated, slow = in_step / (in_step + expected), True, in_step > SLOW_FACTOR * expected
            percent = max(inst["floor"], low + (high - low) * fraction)     # never backwards, and never 100 before the model really answered
            inst["floor"] = percent
            return {"stage": inst["stage"], "step": index + 1, "steps": len(INSTALL_STEPS), "percent": min(99, int(percent)),
                    "stage_percent": min(99, int(fraction * 100)) if estimated else int(fraction * 100), "elapsed": int(elapsed),
                    "estimated": estimated, "slow": slow}

    def _start_heartbeat(self):
        """While the install step runs, tell the listener every `INSTALL_HEARTBEAT_SECONDS`: the engine reports nothing for a long while, and a
        notification that stood still would look like a hang. Only with a worker thread (a synchronous test run has nothing to refresh)."""
        if not self._use_thread or self._beat is not None:
            return
        stop = threading.Event()

        def beat():
            while not stop.wait(INSTALL_HEARTBEAT_SECONDS):
                self._notify(force=True)

        thread = threading.Thread(target=beat, name="own-brain-heartbeat", daemon=True)
        self._beat = stop
        try:
            thread.start()
        except RuntimeError:
            self._beat = None

    def _install_end(self):
        """The worker is done (or never got to install): stop the heartbeat and forget the clock. Safe to call at any time, any number of times."""
        stop, self._beat = self._beat, None
        if stop is not None:
            stop.set()
        with self._lock:
            self._install = None

    # ================================================================== use
    def tick(self):
        """Cheap; called at every chat message. After the app was opened again, a download the user agreed to and did not stop continues."""
        with self._lock:
            if self._auto_done:
                return None
            self._auto_done = True
            state = self._state
            if state["phase"] == "paused" and state["code"] == "app_closed" and state["consent_at"] and state["choice"]:
                return self.resume()
        return None

    def is_ready(self):
        with self._lock:
            return self._state["phase"] == "ready"

    def model_id(self):
        with self._lock:
            return self._state["model_id"] if self._state["phase"] == "ready" else ""

    def test(self, llm=None):
        """A real question through the real answer path: `{ok, text, seconds, code}`. The model is loaded first if it was unloaded."""
        model_id = self.model_id()
        if not model_id:
            return {"ok": False, "text": "", "seconds": 0.0, "code": "not_ready"}
        if llm is None:
            from . import llm as hub_llm
            llm = hub_llm.get_llm(self._hub)
        result = llm.reply(_TEST_PROMPT, model_id=model_id, remember=False)
        return {"ok": bool(result.ok), "text": result.text if result.ok else "", "seconds": float(result.seconds), "code": result.code}

    # ---- idle: give the memory back ---------------------------------------------------------------------------------------
    def touch(self):
        """The brain was just used: (re)start the idle timer that frees its memory later. Never raises."""
        if self._idle_s <= 0:
            return
        with self._lock:
            self._cancel_idle()
            timer = threading.Timer(self._idle_s, self._idle_unload)
            timer.daemon = True
            self._idle_timer = timer
        try:
            timer.start()
        except RuntimeError:
            pass

    def _cancel_idle(self):
        timer, self._idle_timer = self._idle_timer, None
        if timer is not None:
            timer.cancel()

    def _idle_unload(self):
        try:
            model_id = self.model_id()
            if model_id:
                self._hub.unload_model(model_id)
        except Exception:
            pass


_GET_LOCK = threading.Lock()


def get_ownbrain(hub, **kwargs):
    """The one `OwnBrain` of this hub object (created on first use; nothing is written until a job starts), or None for something that is not a hub.
    `kwargs` (tests: a tiny catalog, a fake downloader, a fixed clock ...) only count for the call that creates it."""
    if hub is None or not hasattr(hub, "root") or not hasattr(hub, "model_status"):
        return None
    brain = getattr(hub, "_own_brain", None)
    if isinstance(brain, OwnBrain):
        return brain
    with _GET_LOCK:
        brain = getattr(hub, "_own_brain", None)
        if not isinstance(brain, OwnBrain):
            brain = OwnBrain(hub, **kwargs)
            if kwargs.get("notifier") is None:
                _attach_body(hub, brain)
            try:
                hub._own_brain = brain
            except Exception:
                return brain
        return brain


def _attach_body(hub, brain):
    """The default listener of a job: the hub's `Body`, which keeps the phone's foreground service for as long as the download or the install
    runs (and does nothing at all outside the Android app: its door then answers "unavailable"). Never raises."""
    try:
        from .body import get_body
        body = get_body(hub)
        if body is not None:
            brain.set_notifier(body.on_ownbrain)
    except Exception:
        pass
