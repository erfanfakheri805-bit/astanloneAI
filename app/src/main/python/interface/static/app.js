// Prompt 956: Persian-first, portrait chat UI over the unchanged local API
// (GET /api/status, POST /api/message). All Persian strings and display-only
// conversions live in i18n.js (window.FaUI).
// Prompt 957: a text/JSON file can be attached (read on this device into the message box - nothing is
// sent until the user presses send) and very long messages are shown shortened in their bubble.
(function () {
  "use strict";

  var T = window.FaUI;
  var S = T.STR;

  var messagesEl = document.getElementById("messages");
  var formEl = document.getElementById("input-form");
  var inputEl = document.getElementById("input-box");
  var sendBtn = document.getElementById("send-btn");
  var hintsEl = document.getElementById("hints");
  var attachBtn = document.getElementById("attach-btn");
  var attachInput = document.getElementById("attach-input");
  var attachNote = document.getElementById("attach-note");
  var nativeBar = document.getElementById("native-bar");
  var voiceBtn = document.getElementById("voice-btn");
  var modelBtn = document.getElementById("model-btn");
  var statusDot = document.getElementById("status-dot");
  var statusText = document.getElementById("status-text");
  var sheetEl = document.getElementById("info-sheet");
  var backdropEl = document.getElementById("sheet-backdrop");
  var openBtn = document.getElementById("info-open");
  var closeBtn = document.getElementById("info-close");

  var busy = false;
  var typingEl = null;
  var MAX_INPUT_PX = 140; // ~5 lines; the textarea scrolls beyond this.
  var MAX_ATTACH_BYTES = 200000; // the same ceiling the assistant applies to one extension package.
  var MAX_SHOWN_CHARS = 600; // longer user messages are shortened in their bubble only.

  function scrollToEnd() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  // role: "user" | "assistant"; isError marks a failure notice (not runtime output).
  // textContent only - runtime/user text is never interpreted as markup.
  function addMessage(role, text, isError) {
    var wrap = document.createElement("div");
    wrap.className = "message " + role + (isError ? " error" : "");
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.setAttribute("dir", "auto");
    bubble.textContent = text;
    wrap.appendChild(bubble);
    messagesEl.appendChild(wrap);
    scrollToEnd();
    return wrap;
  }

  function showTyping() {
    hideTyping();
    typingEl = document.createElement("div");
    typingEl.className = "message assistant typing";
    typingEl.setAttribute("role", "status");
    var bubble = document.createElement("div");
    bubble.className = "bubble";
    var label = document.createElement("span");
    label.className = "typing-label";
    label.textContent = S.thinking;
    bubble.appendChild(label);
    for (var i = 0; i < 3; i++) {
      var d = document.createElement("span");
      d.className = "typing-dot";
      bubble.appendChild(d);
    }
    typingEl.appendChild(bubble);
    messagesEl.appendChild(typingEl);
    scrollToEnd();
  }

  function hideTyping() {
    if (typingEl && typingEl.parentNode) typingEl.parentNode.removeChild(typingEl);
    typingEl = null;
  }

  function setBusy(value) {
    busy = value;
    sendBtn.disabled = value;
    attachBtn.disabled = value;
    voiceBtn.disabled = value;
    modelBtn.disabled = value;
    sendBtn.textContent = value ? S.sending : S.send;
    formEl.setAttribute("aria-busy", value ? "true" : "false");
  }

  function setOnline(online) {
    statusDot.className = "dot " + (online ? "dot-live" : "dot-off");
    statusText.textContent = online ? S.online : S.offline;
  }

  // ---------------- info sheet (formerly the developer panel) ----------------

  function renderList(container, items, toRow, emptyMessage) {
    if (!container) return;
    container.innerHTML = "";
    if (items.length === 0) {
      var empty = document.createElement("div");
      empty.className = "muted small";
      empty.textContent = emptyMessage;
      container.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var row = toRow(item);
      var el = document.createElement("div");
      el.className = "history-item";

      var nameSpan = document.createElement("span");
      nameSpan.className = "history-name";
      nameSpan.setAttribute("dir", "ltr"); // technical identifiers stay left-to-right
      nameSpan.textContent = row.label;

      var badge = document.createElement("span");
      badge.className = "badge " + row.badgeClass;
      badge.textContent = row.badgeText;
      if (row.title) badge.title = row.title;

      el.appendChild(nameSpan);
      el.appendChild(badge);
      container.appendChild(el);
    });
  }

  function setText(id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function renderStatus(status) {
    if (!status) return;
    setText("version-label", String(status.app_version));
    setText("m-version", String(status.active_version_label));
    setText("m-knowledge", T.formatCount(status.knowledge_count));
    setText("m-concepts", T.formatCount(status.concept_count));
    setText("m-skills", T.formatCount(status.skill_count));
    setText("m-capabilities", T.formatCount(status.capability_count));
    setText("m-installed", T.formatCount(status.installed_upgrades));
    setText("m-failed", T.formatCount(status.failed_upgrades));
    setText("m-learning-events", T.formatCount(status.learning_event_count));
    setText("m-errors", T.formatCount(status.error_count));
    setText("m-status", T.statusLabel(status.system_status));

    renderList(document.getElementById("upgrade-history"), status.upgrade_history || [], function (u) {
      var key = String(u.status).toLowerCase();
      return {
        label: u.name,
        badgeText: T.statusLabel(u.status),
        badgeClass: key === "installed" ? "installed" : key === "failed" ? "failed" : "pending"
      };
    }, S.upgradesEmpty);

    renderList(document.getElementById("health-components"), status.health_components || [], function (c) {
      return {
        label: c.name,
        badgeText: T.statusLabel(c.status),
        badgeClass: String(c.status).toLowerCase(),
        title: c.detail
      };
    }, S.healthEmpty);
  }

  function fetchStatus() {
    return fetch("/api/status")
      .then(function (res) {
        if (!res.ok) throw new Error("status " + res.status);
        return res.json();
      })
      .then(function (status) {
        setOnline(true);
        renderStatus(status);
      })
      .catch(function () {
        setOnline(false); // the chat form stays usable; the header tells the user
      });
  }

  function openSheet() {
    sheetEl.hidden = false;
    backdropEl.hidden = false;
    closeBtn.focus();
    fetchStatus();
  }

  function closeSheet() {
    sheetEl.hidden = true;
    backdropEl.hidden = true;
    openBtn.focus();
  }

  // ---------------- sending ----------------

  function sendMessage(text) {
    if (busy) return;
    if (hintsEl && hintsEl.parentNode) hintsEl.parentNode.removeChild(hintsEl);
    showAttachNote("");
    addMessage("user", T.shortenForDisplay(text, MAX_SHOWN_CHARS), false); // display only; `text` is sent whole
    setBusy(true);
    showTyping();

    var httpStatus = 0;
    fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: T.protectPackage(text) }) // an extension package keeps its code indentation
    })
      .then(function (res) {
        httpStatus = res.status;
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (r) {
        hideTyping();
        if (!r.ok || !r.data || typeof r.data.reply !== "string") {
          var msg = r.data && typeof r.data.error === "string" ? r.data.error : "";
          addMessage("assistant", T.localizeError(msg, httpStatus), true);
          restoreDraft(text);
          return;
        }
        setOnline(true);
        addMessage("assistant", T.localizeReply(r.data.reply), false);
        renderStatus(r.data.status);
      })
      .catch(function () {
        hideTyping();
        setOnline(false);
        addMessage("assistant", S.errorNetwork, true);
        restoreDraft(text);
      })
      .then(function () {
        setBusy(false);
        flushQueued();
      });
  }

  // A failed send must never lose what the user typed.
  function restoreDraft(text) {
    if (inputEl.value.trim() === "") {
      inputEl.value = text;
      syncInput();
    }
  }

  // ---------------- attaching a text file ----------------

  // One honest line about the attached file (read / refused and why). Empty text hides it.
  function showAttachNote(message) {
    attachNote.textContent = message || "";
    attachNote.hidden = !message;
  }

  // The file is decoded as UTF-8 text on this device and put into the message box, after anything the user
  // already typed. A binary or non-UTF-8 file, an empty one and one over the size ceiling are refused with
  // a reason; nothing is ever uploaded or sent from here.
  function readAttachment(file) {
    showAttachNote("");
    if (!file) return;
    if (!file.size) { showAttachNote(S.attachEmpty); return; }
    if (file.size > MAX_ATTACH_BYTES) { showAttachNote(S.attachTooLarge); return; }
    var reader = new FileReader();
    reader.onload = function () {
      var text = typeof reader.result === "string" ? reader.result : "";
      if (text.indexOf("\uFFFD") !== -1 || text.indexOf("\u0000") !== -1) { showAttachNote(S.attachNotText); return; }
      if (text.trim() === "") { showAttachNote(S.attachEmpty); return; }
      var typed = inputEl.value.trim();
      inputEl.value = typed === "" ? text : typed + "\n\n" + text;
      syncInput();
      inputEl.focus();
      showAttachNote(T.fillTemplate(S.attachReady, { name: String(file.name || "").slice(0, 60), n: Array.from(text).length }));
    };
    reader.onerror = function () { showAttachNote(S.attachFailed); };
    try {
      reader.readAsText(file, "utf-8");
    } catch (e) {
      showAttachNote(S.attachFailed);
    }
  }

  attachBtn.addEventListener("click", function () {
    // (while a message is in flight the button is disabled by setBusy, so it fires no click at all)
    attachInput.value = ""; // choosing the same file twice must still fire "change"
    attachInput.click();
  });

  attachInput.addEventListener("change", function () {
    var files = attachInput.files;
    readAttachment(files && files.length ? files[0] : null);
  });

  // ---------------- the phone's own buttons (inside the Android app only) ----------------

  // `window.AndroidBridge` is added to this page by the Android app and exists nowhere else: in an ordinary browser the
  // bar stays hidden and none of this runs. Each button needs the user's own tap here AND a dialog of Android's; what
  // comes back arrives through the four window.nativeOn... functions below (the app calls them with ONE JSON text).
  // Speech and shared text only FILL the message box. The two messages this page sends by itself (sendOrQueue) are plain
  // sentences that the user's own action asked for («جواب آمد» after he shared an answer into the app while a request
  // was waiting; «مدل <file> را وارد کن» after he chose a model file) - the assistant still asks its own question
  // and changes nothing without the user's «بله».
  var MODEL_NAME_RE = /^(?=[A-Za-z0-9._-]{1,100}$)[A-Za-z0-9][A-Za-z0-9._-]*\.(?:task|gguf)$/i;
  var FILE_PROBLEMS = {
    cancelled: "pickCancelled", busy: "pickBusy", unsupported_type: "pickUnsupported", no_space: "pickNoSpace",
    unreadable: "pickUnreadable", io_error: "pickIoError", size_mismatch: "pickSizeMismatch", empty: "pickEmpty",
    no_inbox: "pickNoInbox"
  };
  var MAX_QUEUED = 5;
  var queued = [];

  function bridgeFeatures() {
    try {
      var bridge = window.AndroidBridge;
      if (!bridge || typeof bridge.features !== "function") return [];
      var list = JSON.parse(String(bridge.features()));
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }

  // True only when the app really started the thing (its dialog is open).
  function bridgeCall(name, arg) {
    try {
      var bridge = window.AndroidBridge;
      return !!(bridge && typeof bridge[name] === "function" && bridge[name](arg));
    } catch (e) {
      return false;
    }
  }

  function parseNative(json) {
    try {
      var data = JSON.parse(String(json));
      return data && typeof data === "object" ? data : null;
    } catch (e) {
      return null;
    }
  }

  // The same refusal as for an attached file: a replacement character or a NUL means the text is not text.
  function hasBadChars(text) {
    return text.indexOf(String.fromCharCode(65533)) !== -1 || text.indexOf(String.fromCharCode(0)) !== -1;
  }

  // Text into the message box, after whatever the user has already typed there.
  function putInComposer(text, separator) {
    var typed = inputEl.value.trim();
    inputEl.value = typed === "" ? text : typed + separator + text;
    syncInput();
    inputEl.focus();
  }

  // A message this page sends for the user's own action: right away, or after the one that is still on its way.
  function sendOrQueue(text) {
    if (busy) {
      if (queued.length < MAX_QUEUED) queued.push(text);
      return;
    }
    sendMessage(text);
  }

  function flushQueued() {
    if (!busy && queued.length > 0) sendMessage(queued.shift());
  }

  voiceBtn.addEventListener("click", function () {
    if (busy) return;
    showAttachNote("");
    if (!bridgeCall("startVoice", "fa-IR")) showAttachNote(S.voiceUnavailable);
  });

  modelBtn.addEventListener("click", function () {
    if (busy) return;
    showAttachNote("");
    if (!bridgeCall("pickFile", "model")) showAttachNote(S.pickUnavailable);
  });

  window.nativeOnVoice = function (json) {
    var data = parseNative(json);
    var text = data && typeof data.text === "string" ? data.text.trim() : "";
    if (!data || !data.ok || text === "" || hasBadChars(text)) {
      showAttachNote(S.voiceNothing);
      return;
    }
    putInComposer(text, " ");
    showAttachNote(T.fillTemplate(S.voiceHeard, { n: Array.from(text).length }));
  };

  window.nativeOnShared = function (json) {
    var data = parseNative(json);
    if (!data) return;
    if (!data.ok) {
      showAttachNote(data.code === "empty" ? S.sharedEmpty : S.sharedFailed);
      return;
    }
    var n = typeof data.chars === "number" ? data.chars : 0;
    if (data.mission_open) {
      sendOrQueue(S.answerCame);                  // the assistant reads the saved text itself and only reviews it
      showAttachNote(T.fillTemplate(S.sharedMission, { n: n }));
      return;
    }
    var text = typeof data.text === "string" ? data.text : "";
    if (text === "") {
      showAttachNote(T.fillTemplate(data.truncated ? S.sharedCut : S.sharedTooLong, { n: n }));
      return;
    }
    if (hasBadChars(text)) {
      showAttachNote(S.sharedNotText);
      return;
    }
    putInComposer(text, "\n\n");
    showAttachNote(T.fillTemplate(S.sharedReady, { n: Array.from(text).length }));
  };

  window.nativeOnProgress = function (json) {
    var data = parseNative(json);
    if (!data) return;
    var copied = Number(data.copied) || 0;
    var total = Number(data.total) || 0;
    var values = { name: String(data.name || "").slice(0, 100), done: T.plain(T.formatBytes(copied)) };
    if (total > 0) {
      values.total = T.plain(T.formatBytes(total));
      values.percent = Math.min(99, Math.floor((copied * 100) / total));
      showAttachNote(T.fillTemplate(S.copyProgress, values));
    } else {
      showAttachNote(T.fillTemplate(S.copyProgressUnknown, values));
    }
  };

  window.nativeOnFile = function (json) {
    var data = parseNative(json);
    if (!data) return;
    var name = typeof data.name === "string" ? data.name.slice(0, 100) : "";
    var purpose = data.purpose === "model" ? "model" : "file";
    if (data.ok) {
      var size = T.plain(T.formatBytes(Number(data.size) || 0));
      if (purpose === "model" && MODEL_NAME_RE.test(name)) {
        sendOrQueue(S.importCommand.replace("{name}", name));   // only the question: the file is read and copied after the user's «بله»
        showAttachNote(T.fillTemplate(S.modelCopied, { name: name, size: size }));
      } else {
        showAttachNote(T.fillTemplate(S.fileCopied, { name: name, size: size }));
      }
      return;
    }
    var key = data.code === "too_large" ? (purpose === "model" ? "pickTooLargeModel" : "pickTooLargeFile") : FILE_PROBLEMS[data.code];
    showAttachNote(S[key] || S.pickFailed);
  };

  (function showNativeBar() {
    var features = bridgeFeatures();
    voiceBtn.hidden = features.indexOf("voice_input") === -1;
    modelBtn.hidden = features.indexOf("file_pick") === -1;
    nativeBar.hidden = voiceBtn.hidden && modelBtn.hidden;
  })();

  // ---------------- composer ----------------

  // An empty field is forced RTL so the Persian placeholder sits on the right;
  // once text exists the browser picks the direction from its first strong letter.
  function syncInput() {
    inputEl.setAttribute("dir", inputEl.value.trim() === "" ? "rtl" : "auto");
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, MAX_INPUT_PX) + "px";
  }

  function submit() {
    var text = inputEl.value.trim();
    if (!text || busy) return;
    inputEl.value = "";
    syncInput();
    sendMessage(text);
  }

  formEl.addEventListener("submit", function (e) {
    e.preventDefault();
    submit();
  });

  inputEl.addEventListener("input", syncInput);

  // Enter sends on a hardware keyboard; Shift+Enter adds a new line.
  // Never send while an IME composition is in progress.
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      submit();
    }
  });

  // Keep the newest message visible when the soft keyboard opens or closes.
  inputEl.addEventListener("focus", function () {
    setTimeout(scrollToEnd, 300);
  });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", scrollToEnd);
  }
  window.addEventListener("resize", scrollToEnd);

  hintsEl.addEventListener("click", function (e) {
    var t = e.target;
    if (t && t.getAttribute && t.getAttribute("data-insert")) {
      inputEl.value = t.getAttribute("data-insert");
      syncInput();
      inputEl.focus();
    }
  });

  openBtn.addEventListener("click", openSheet);
  closeBtn.addEventListener("click", closeSheet);
  backdropEl.addEventListener("click", closeSheet);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !sheetEl.hidden) closeSheet();
  });

  syncInput();
  fetchStatus();
  setInterval(function () {
    if (!document.hidden) fetchStatus();
  }, 8000);
})();
