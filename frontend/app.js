const $ = (id) => document.getElementById(id);

let sessionId = null;
let projId = null;
let projName = null;

const QUICK_QUERIES = [
  "Show critical path",
  "Top float risks",
  "Schedule health summary",
  "Duration analysis",
];

function setSending(isSending) {
  const btn = $("sendBtn");
  const icon = $("sendIcon");
  const spn = $("sendSpinner");
  btn.disabled = isSending;
  $("chatInput").disabled = isSending;
  if (icon) icon.hidden = isSending;
  if (spn) spn.hidden = !isSending;
}

function addMessage(role, text, meta = "", extraClass = "") {
  const el = document.createElement("div");
  el.className = `msg ${role === "user" ? "user" : "bot"} ${extraClass}`.trim();

  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = role === "user" ? "You" : "CriticalPath AI";
  el.appendChild(label);

  const content = document.createElement("div");
  content.className = "msg-content";
  content.textContent = text;
  el.appendChild(content);

  if (meta) {
    const m = document.createElement("div");
    m.className = "meta";
    m.textContent = meta;
    el.appendChild(m);
  }

  $("messages").appendChild(el);
  $("messages").scrollTop = $("messages").scrollHeight;
  return el;
}

function addQuickActions() {
  const container = document.createElement("div");
  container.className = "quick-actions";
  QUICK_QUERIES.forEach((q) => {
    const btn = document.createElement("button");
    btn.className = "quick-btn";
    btn.textContent = q;
    btn.addEventListener("click", () => {
      $("chatInput").value = q;
      sendMessage();
      container.remove();
    });
    container.appendChild(btn);
  });
  $("messages").appendChild(container);
  $("messages").scrollTop = $("messages").scrollHeight;
}

async function loadProjects() {
  const res = await fetch("/api/projects");
  const data = await res.json();
  const select = $("projectSelect");
  select.innerHTML = "";
  data.projects.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.proj_id;
    opt.textContent = `${p.proj_name} (ID: ${p.proj_id})`;
    select.appendChild(opt);
  });
}

async function startSession() {
  projId = $("projectSelect").value;
  projName = $("projectSelect").selectedOptions[0]?.textContent || projId;

  const res = await fetch("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ proj_id: projId }),
  });
  const data = await res.json();
  sessionId = data.session_id;

  $("projectPill").textContent = projName;
  $("projectPill").classList.add("active");
  $("onboarding").hidden = true;
  $("chat").hidden = false;

  addMessage(
    "bot",
    `Session active for: ${projName}\n\nI can analyze critical path, total float, predecessor/successor chains, durations, and overall schedule health. What would you like to explore?`,
    "",
    "welcome"
  );
  addQuickActions();
  $("chatInput").focus();
}

async function sendMessage() {
  const input = $("chatInput");
  const msg = input.value.trim();
  if (!msg) return;

  input.value = "";
  addMessage("user", msg);

  setSending(true);
  const typingEl = addMessage("bot", "Analyzing schedule data\u2026", "", "typing");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: msg }),
    });

    if (!res.ok) {
      const err = await res.json();
      typingEl.remove();
      addMessage("bot", `Error: ${err.detail || res.statusText}`);
      return;
    }

    const data = await res.json();
    typingEl.remove();
    addMessage(
      "bot",
      data.reply,
      data.data?.intent ? `intent: ${data.data.intent}` : ""
    );
  } catch (e) {
    try {
      typingEl.remove();
    } catch (_) {}
    addMessage("bot", `Connection error: ${e?.message || e}`);
  } finally {
    setSending(false);
    $("chatInput").focus();
  }
}

// Event listeners
$("startBtn").addEventListener("click", startSession);
$("sendBtn").addEventListener("click", sendMessage);
$("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) sendMessage();
});

loadProjects().catch((e) => {
  console.error(e);
  $("projectSelect").innerHTML =
    "<option>Failed to load projects</option>";
});
