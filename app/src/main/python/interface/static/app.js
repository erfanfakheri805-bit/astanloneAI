const messagesEl = document.getElementById("messages");
const formEl = document.getElementById("input-form");
const inputEl = document.getElementById("input-box");
const toggleEl = document.getElementById("dev-panel-toggle");
const panelEl = document.getElementById("dev-panel");

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderStatus(status) {
  if (!status) return;
  document.getElementById("version-label").textContent = `Version: ${status.app_version}`;
  document.getElementById("m-version").textContent = status.active_version_label;
  document.getElementById("m-knowledge").textContent = status.knowledge_count;
  document.getElementById("m-concepts").textContent = status.concept_count;
  document.getElementById("m-skills").textContent = status.skill_count;
  document.getElementById("m-capabilities").textContent = status.capability_count;
  document.getElementById("m-installed").textContent = status.installed_upgrades;
  document.getElementById("m-failed").textContent = status.failed_upgrades;
  document.getElementById("m-learning-events").textContent = status.learning_event_count;
  document.getElementById("m-errors").textContent = status.error_count;
  document.getElementById("m-status").textContent = status.system_status;

  renderList(document.getElementById("upgrade-history"), status.upgrade_history || [], (u) => ({
    label: u.name,
    badgeText: u.status,
    badgeClass: u.status === "installed" ? "installed" : u.status === "failed" ? "failed" : "pending",
  }), "No upgrades yet.");

  renderList(document.getElementById("health-components"), status.health_components || [], (c) => ({
    label: c.name,
    badgeText: c.status,
    badgeClass: c.status.toLowerCase(),
    title: c.detail,
  }), "No health data yet.");
}

// Builds each row via DOM APIs (textContent, not innerHTML) so that
// data coming from the backend - upgrade names, health details, etc. -
// can never be interpreted as markup, even though AEL/validator-level
// checks already keep most of it to a safe character set upstream.
function renderList(container, items, toRow, emptyMessage) {
  if (!container) return;
  container.innerHTML = "";
  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "muted small";
    empty.textContent = emptyMessage;
    container.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const { label, badgeText, badgeClass, title } = toRow(item);
    const row = document.createElement("div");
    row.className = "history-item";

    const nameSpan = document.createElement("span");
    nameSpan.textContent = label;

    const badgeSpan = document.createElement("span");
    badgeSpan.className = `badge ${badgeClass}`;
    badgeSpan.textContent = badgeText;
    if (title) badgeSpan.title = title;

    row.appendChild(nameSpan);
    row.appendChild(badgeSpan);
    container.appendChild(row);
  });
}

async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();
    renderStatus(status);
  } catch (e) {
    // Silent fail is fine here - the chat still works without the panel.
  }
}

async function sendMessage(text) {
  addMessage("user", text);
  try {
    const res = await fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    addMessage("assistant", data.reply);
    renderStatus(data.status);
  } catch (e) {
    addMessage("assistant", "Something went wrong reaching the local server.");
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  sendMessage(text);
});

toggleEl.addEventListener("click", () => {
  toggleEl.classList.toggle("open");
  panelEl.classList.toggle("open");
});

fetchStatus();
setInterval(fetchStatus, 8000);
