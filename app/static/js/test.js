"use strict";
const app = $("#app");
const TID = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop());
const API = "/api/tests/" + encodeURIComponent(TID);
let clockOffset = 0;            // server time minus client time, ms
let deadlineMs = null;
let questions = [];
let answers = {};
let dirty = false, saving = false, finished = false;
let tickTimer = null, saveTimer = null, beatTimer = null;
let lastAnnouncement = null, lastEventAt = {};
let maxChars = 4000;

const nowServer = () => Date.now() + clockOffset;
const goLogin = () => { location.href = "/login"; };

function show(...nodes) { app.replaceChildren(...nodes); }

async function boot() {
  let state;
  try { state = await api(API); }
  catch (e) {
    if (e.status === 401) return goLogin();
    return show(h("div", { class: "panel" }, e.message, " ", h("a", { href: "/tests" }, "Back to tests")));
  }
  clockOffset = Date.parse(state.attempt.server_time) - Date.now();
  maxChars = state.limits.max_answer_chars;
  $("#who").textContent = state.profile.Name + " · " + state.profile.RegNo;
  if (state.attempt.submitted) return (location.href = "/thank");
  if (state.attempt.started) return begin();   // resume an attempt in progress
  renderGate(state);
}

function logoutBtn() {
  return h("button", { class: "btn ghost small", onclick: async () => { await api("/api/student/logout", { method: "POST" }); goLogin(); } }, "Sign out");
}

function renderGate(state) {
  const c = state.contest;
  const head = [h("div", { class: "eyebrow" }, "Test"), h("h1", {}, c.title)];
  const who = h("p", { class: "muted" }, `Signed in as ${state.profile.Name} (${state.profile.RegNo}). `, h("a", { href: "/tests" }, "All tests"), " · ", logoutBtn());
  if (c.phase === "draft") {
    return show(...head, who, h("div", { class: "panel" }, h("span", { class: "chip warn" }, "Not published"),
      h("p", { style: "margin-top:1rem" }, "The test has not been published yet. Check back soon.")));
  }
  if (c.phase === "closed") {
    return show(...head, who, h("div", { class: "panel" }, h("span", { class: "chip bad" }, "Closed"),
      h("p", { style: "margin-top:1rem" }, "This test is closed. You did not start an attempt.")));
  }
  if (c.phase === "upcoming") {
    const clock = h("div", { class: "bigclock" }, "--:--");
    show(...head, who, h("div", { class: "panel" }, h("span", { class: "chip warn" }, "Opens " + formatDateTime(c.opens_at)),
      h("p", { class: "muted", style: "margin:1rem 0 .25rem" }, "Starts in"), clock));
    const opens = Date.parse(c.opens_at);
    const t = setInterval(() => {
      const left = (opens - nowServer()) / 1000;
      if (left <= 0) { clearInterval(t); boot(); } else clock.textContent = formatClock(left);
    }, 500);
    return;
  }
  const btn = h("button", { class: "btn", onclick: async () => {
    btn.disabled = true;
    try { await begin(); } catch (e) { btn.disabled = false; toast(e.message, "error"); }
  } }, "Start test");
  show(...head, who, h("div", { class: "panel accent" },
    h("span", { class: "chip ok" }, "Open"),
    h("dl", { class: "kv" },
      h("div", {}, h("dt", {}, "Time allowed"), h("dd", {}, c.duration_minutes + " min")),
      c.closes_at ? h("div", {}, h("dt", {}, "Closes at"), h("dd", {}, formatDateTime(c.closes_at))) : null),
    h("ul", { class: "rules" },
      h("li", {}, "The timer starts when you press Start and cannot be paused."),
      h("li", {}, "Answers autosave. If you reload, you resume with the time that is left."),
      h("li", {}, "The test submits automatically when time runs out."),
      h("li", {}, "Write pseudocode, not a specific programming language."),
      h("li", {}, "Switching tabs or windows, pasting and copying are recorded and shown to the coordinator."),
      h("li", {}, "Sign in on one device only: a new sign-in logs the old one out.")),
    btn));
}

async function begin() {
  const data = await api(API + "/start", { method: "POST" });
  if (data.attempt.submitted) return (location.href = "/thank");
  clockOffset = Date.parse(data.attempt.server_time) - Date.now();
  maxChars = data.limits.max_answer_chars;
  deadlineMs = Date.parse(data.attempt.deadline);
  questions = data.questions;
  answers = data.answers || {};
  renderTest(data.contest);
}

function renderTest(c) {
  $("#bar").classList.remove("hidden");
  const cards = questions.map((q, i) => {
    const ta = h("textarea", {
      class: "code", id: "q" + q.id, spellcheck: "false", maxlength: maxChars, rows: 9,
      placeholder: "BEGIN\n  ...\nEND",
      oninput: () => { answers[q.id] = ta.value; counter.textContent = `${ta.value.length}/${maxChars}`; dirty = true; markSaved("Unsaved changes"); updateProgress(); },
      onkeydown: (e) => { // Tab inserts indentation instead of leaving the field
        if (e.key === "Tab" && !e.shiftKey) {
          e.preventDefault();
          const { selectionStart: s, selectionEnd: en } = ta;
          ta.setRangeText("    ", s, en, "end");
          ta.dispatchEvent(new Event("input"));
        }
      },
    });
    ta.value = answers[q.id] || "";
    const counter = h("div", { class: "counter" }, `${ta.value.length}/${maxChars}`);
    return h("section", { class: "panel qcard" },
      h("div", { class: "qhead" }, h("span", { class: "qno" }, `Q${i + 1} of ${questions.length}`), h("span", { class: "muted mono" }, q.max_score + " marks")),
      h("p", { class: "qtext" }, q.text), ta, counter);
  });
  const submit = h("button", { class: "btn", id: "submit", onclick: onSubmitClick }, "Submit test");
  show(h("div", { id: "banner", class: "banner hidden", role: "alert" }), h("h1", {}, c.title), ...cards, h("div", { class: "panel" },
    h("div", { class: "form-error", id: "subErr", role: "alert" }),
    h("div", { class: "actions" }, submit, h("span", { class: "muted mono", id: "subHint" }, "Autosaves every few seconds."))));
  updateProgress();
  markSaved("All changes saved");
  tick();
  tickTimer = setInterval(tick, 500);
  saveTimer = setInterval(() => { if (dirty) save(false); }, 8000);
  beatTimer = setInterval(heartbeat, 8000);
  heartbeat();
  document.addEventListener("visibilitychange", () => { if (document.hidden) reportEvent("blur", "tab hidden"); });
  addEventListener("blur", () => { if (!document.hidden) reportEvent("blur", "window unfocused"); });
  $$("textarea.code").forEach((ta, i) => {
    ta.addEventListener("paste", () => reportEvent("paste", "Q" + (i + 1)));
    ta.addEventListener("copy", () => reportEvent("copy", "Q" + (i + 1)));
  });
  addEventListener("beforeunload", (e) => { if (dirty && !finished) { e.preventDefault(); e.returnValue = ""; } });
}

/** Integrity log. Fire-and-forget; throttled so a flapping focus does not spam the server. */
function reportEvent(type, detail) {
  const now = Date.now();
  if (finished || now - (lastEventAt[type] || 0) < 1500) return;
  lastEventAt[type] = now;
  api(API + "/event", { method: "POST", body: { type, detail } }).catch(() => {});
}

/** Live state from the server: staff extensions, force-submit/reset, announcements, online presence. */
async function heartbeat() {
  if (finished) return;
  try {
    const hb = await api(API + "/heartbeat", { method: "POST" });
    clockOffset = Date.parse(hb.attempt.server_time) - Date.now();
    if (hb.attempt.submitted) { finished = true; dirty = false; location.href = "/thank?t=" + encodeURIComponent(TID); return; }
    if (!hb.attempt.started) { finished = true; dirty = false; location.reload(); return; }   // staff reset the attempt
    if (hb.attempt.deadline) deadlineMs = Date.parse(hb.attempt.deadline);
    const a = hb.announcement, banner = $("#banner");
    if (banner) {
      banner.classList.toggle("hidden", !a);
      banner.textContent = a ? "📢 " + a.text : "";
      if (a && a.id !== lastAnnouncement) toast(a.text);
    }
    lastAnnouncement = a ? a.id : null;
  } catch (e) {
    if (e.status === 401) { finished = true; dirty = false; sessionStorage.setItem("notice", e.message); goLogin(); }
  }
}

function markSaved(text) { $("#saved").textContent = text; }
function updateProgress() {
  const done = questions.filter((q) => (answers[q.id] || "").trim()).length;
  $("#prog").style.width = (questions.length ? (done / questions.length) * 100 : 0) + "%";
}

function tick() {
  const left = (deadlineMs - nowServer()) / 1000;
  const t = $("#timer");
  t.textContent = formatClock(left);
  t.classList.toggle("low", left <= 300 && left > 60);
  t.classList.toggle("critical", left <= 60);
  if (left <= 0 && !finished) { finished = true; clearInterval(tickTimer); finalSubmit(true); }
}

async function save(final) {
  if (saving && !final) return true;
  saving = true;
  try {
    await api(API + "/answers", { method: "PUT", body: { pseudoCodeAnswers: collect(), final } });
    dirty = false;
    markSaved("Saved " + new Date().toLocaleTimeString());
    return true;
  } catch (e) {
    if (e.status === 401) { goLogin(); return false; }
    markSaved("Save failed — retrying");
    if (final) throw e;
    return false;
  } finally { saving = false; }
}

function collect() {
  const out = {};
  for (const q of questions) out[String(q.id)] = answers[q.id] || "";
  return out;
}

let confirming = false;
function onSubmitClick() {
  const btn = $("#submit");
  const blanks = questions.filter((q) => !(answers[q.id] || "").trim()).length;
  if (!confirming) {
    confirming = true;
    btn.textContent = blanks ? `${blanks} unanswered — click again to submit` : "Click again to confirm";
    setTimeout(() => { confirming = false; btn.textContent = "Submit test"; }, 5000);
    return;
  }
  finished = true;
  finalSubmit(false);
}

async function finalSubmit(auto) {
  clearInterval(saveTimer);
  clearInterval(beatTimer);
  const btn = $("#submit");
  if (btn) btn.disabled = true;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      await api(API + "/answers", { method: "PUT", body: { pseudoCodeAnswers: collect(), final: true } });
      dirty = false;
      location.href = "/thank?t=" + encodeURIComponent(TID);
      return;
    } catch (e) {
      if (e.status === 401) return goLogin();
      if (e.status === 409) { location.href = "/thank?t=" + encodeURIComponent(TID); return; }
      if (e.status === 403) { // deadline passed on the server; last autosave is what counts
        dirty = false;
        location.href = "/thank?t=" + encodeURIComponent(TID);
        return;
      }
      $("#subErr").textContent = e.message + " Retrying…";
      await new Promise((r) => setTimeout(r, 1500));
    }
  }
  finished = false;
  if (btn) btn.disabled = false;
  $("#subErr").textContent = "Could not submit. Check your connection and press Submit again.";
}

boot();
