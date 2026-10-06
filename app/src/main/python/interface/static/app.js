// Prompt 956: Persian-first, portrait chat UI over the unchanged local API
// (GET /api/status, POST /api/message). All Persian strings and display-only
// conversions live in i18n.js (window.FaUI).
(function () {
  "use strict";

  var T = window.FaUI;
  var S = T.STR;

  var messagesEl = document.getElementById("messages");
  var formEl = document.getElementById("input-form");
  var inputEl = document.getElementById("input-box");
  var sendBtn = document.getElementById("send-btn");
  var hintsEl = document.getElementById("hints");
  var statusDot = document.getElementById("status-dot");
  var statusText = document.getElementById("status-text");
  var sheetEl = document.getElementById("info-sheet");
  var backdropEl = document.getElementById("sheet-backdrop");
  var openBtn = document.getElementById("info-open");
  var closeBtn = document.getElementById("info-close");

  var busy = false;
  var typingEl = null;
  var MAX_INPUT_PX = 140; // ~5 lines; the textarea scrolls beyond this.

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
    addMessage("user", text, false);
    setBusy(true);
    showTyping();

    var httpStatus = 0;
    fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
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
      });
  }

  // A failed send must never lose what the user typed.
  function restoreDraft(text) {
    if (inputEl.value.trim() === "") {
      inputEl.value = text;
      syncInput();
    }
  }

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
