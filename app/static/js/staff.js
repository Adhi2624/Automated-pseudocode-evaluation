"use strict";
const goLogin = () => { location.href = "/staff/login"; };

/** Run an API call; bounce to the login page on 401, otherwise rethrow. */
async function call(path, opts) {
  try { return await api(path, opts); }
  catch (e) { if (e.status === 401) goLogin(); throw e; }
}

/* ---- current test ---- */
let currentTest = null;
let testList = [];
const T = (path = "") => `/api/staff/tests/${encodeURIComponent(currentTest)}${path}`;
const TABS = ["tests", "contest", "monitor", "questions", "subs", "results", "students"];
let activeTab = "tests";

const PHASE = { draft: ["warn", "Draft"], upcoming: ["warn", "Scheduled"], open: ["ok", "Open now"], closed: ["bad", "Closed"] };

function selectTab(name) {
  activeTab = name;
  const scoped = $(`.tab[data-tab="${name}"]`).hasAttribute("data-scoped");
  $$(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  stopAllPolling();
  const blocked = scoped && !currentTest;
  $("#noTest").classList.toggle("hidden", !blocked);
  TABS.forEach((n) => $("#tab-" + n).classList.toggle("hidden", n !== name || blocked));
  if (blocked) return;
  if (name === "tests") loadTests();
  if (name === "contest") loadSettings();
  if (name === "monitor") startMonitor();
  if (name === "questions") loadQuestions();
  if (name === "subs") { $("#detail").replaceChildren(); loadSubs(); }
  if (name === "results") loadResults();
  if (name === "students") loadRoster();
}
$$(".tab").forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));

function setCurrent(id, { reload = true } = {}) {
  currentTest = id || null;
  try { currentTest ? localStorage.setItem("staffTest", currentTest) : localStorage.removeItem("staffTest"); } catch (e) { /* ignore */ }
  $("#testPick").value = currentTest || "";
  const t = testList.find((x) => x.id === currentTest);
  const [kind, label] = t ? PHASE[t.phase] : ["", ""];
  $("#testPhase").replaceChildren(t ? h("span", { class: "chip " + kind }, label) : "");
  if (reload) selectTab(activeTab);
}

/** Refresh the test list that feeds the picker, the overview and the "copy from" select. */
async function refreshTests() {
  testList = await call("/api/staff/tests");
  const pick = $("#testPick");
  pick.replaceChildren(...(testList.length ? testList.map((t) => h("option", { value: t.id }, t.title)) : [h("option", { value: "" }, "— no tests —")]));
  $("#tCopy").replaceChildren(h("option", { value: "" }, "Start empty"), ...testList.map((t) => h("option", { value: t.id }, t.title)));
  if (!testList.find((t) => t.id === currentTest)) {
    let saved = null; try { saved = localStorage.getItem("staffTest"); } catch (e) { /* ignore */ }
    currentTest = (testList.find((t) => t.id === saved) || testList[0] || {}).id || null;
  }
  setCurrent(currentTest, { reload: false });
}
$("#testPick").addEventListener("change", (e) => setCurrent(e.target.value));

async function loadTests() {
  try {
    await refreshTests();
    $("#testRows").replaceChildren(...(testList.length ? testList.map((t) => {
      const [kind, label] = PHASE[t.phase];
      return h("tr", { class: "click" + (t.id === currentTest ? " short" : ""), tabindex: 0,
        onclick: () => { setCurrent(t.id, { reload: false }); selectTab("monitor"); } },
        h("td", {}, t.title), h("td", {}, h("span", { class: "chip " + kind }, label)),
        h("td", { class: "num" }, t.duration_minutes), h("td", { class: "num" }, t.questions),
        h("td", { class: "num" }, t.started), h("td", { class: "num" }, t.submitted),
        h("td", {}, h("span", { class: "muted mono", style: "font-size:.8rem" }, "Open →")));
    }) : [h("tr", {}, h("td", { colspan: 7, class: "muted" }, "No tests yet. Create the first one below."))]));
  } catch (e) { toast(e.message, "error"); }
}
bindForm($("#tnew"), async (f) => {
  const body = { title: f.title, duration_minutes: Number(f.duration_minutes) };
  if (f.copy_from) body.copy_from = f.copy_from;
  const t = await call("/api/staff/tests", { method: "POST", body });
  $("#tnew").reset();
  toast("Test created. Add questions, then publish it in Settings.");
  await refreshTests();
  setCurrent(t.id, { reload: false });
  selectTab("questions");
});

/* ---- session ---- */
call("/api/staff/me").then((m) => { $("#me").textContent = m.username; }).catch(() => {});
$("#logout").addEventListener("click", async (e) => {
  e.preventDefault();
  try { await api("/api/staff/logout", { method: "POST" }); } catch (x) { /* ignore */ }
  goLogin();
});

/* ---- test settings ---- */
function fillConfig(c) {
  $("#title").value = c.title;
  $("#duration").value = c.duration_minutes;
  $("#opens").value = toLocalInput(c.opens_at);
  $("#closes").value = toLocalInput(c.closes_at);
  $("#published").checked = c.published;
  $("#evalMode").value = c.eval_mode || "manual";
  $("#evalAt").value = toLocalInput(c.eval_at);
  $("#evalDelay").value = c.eval_delay_minutes || 0;
  syncEvalFields();
  const [kind, label] = PHASE[c.phase];
  $("#phase").replaceChildren(h("span", { class: "chip " + kind }, label));
}
const EVAL_HELP = {
  manual: "Nothing happens automatically. Queue a grading job from the Results tab when you are ready.",
  immediate: "Each student's answers are queued for grading shortly after they submit or run out of time.",
  after_close: "Grading starts once the closing time (plus the wait below) has passed. Set a closing time above.",
  scheduled: "Grading starts at the chosen time. Students still writing at that moment are skipped, so pick a time after the test ends.",
};
function syncEvalFields() {
  const m = $("#evalMode").value;
  $("#evalAtBox").classList.toggle("hidden", m !== "scheduled");
  $("#evalDelayBox").classList.toggle("hidden", m !== "after_close");
  $("#evalHelp").textContent = EVAL_HELP[m];
}
$("#evalMode").addEventListener("change", syncEvalFields);

async function loadSettings() {
  try { fillConfig(await call(T())); } catch (e) { toast(e.message, "error"); }
}
bindForm($("#cfg"), async (f) => {
  const saved = await call(T(), {
    method: "PUT",
    body: {
      title: f.title, duration_minutes: Number(f.duration_minutes),
      opens_at: fromLocalInput(f.opens_at), closes_at: fromLocalInput(f.closes_at),
      published: $("#published").checked,
      eval_mode: f.eval_mode, eval_at: fromLocalInput(f.eval_at), eval_delay_minutes: Number(f.eval_delay_minutes || 0),
    },
  });
  fillConfig(saved);
  await refreshTests();
  toast("Settings saved");
});
(() => {
  const btn = $("#delTest");
  let armedAt = 0;
  btn.addEventListener("click", async () => {
    if (Date.now() - armedAt > 4000) { armedAt = Date.now(); btn.textContent = "Click again to delete"; setTimeout(() => { btn.textContent = "Delete test"; }, 4000); return; }
    armedAt = 0; btn.textContent = "Delete test";
    try {
      try { await call(T(), { method: "DELETE" }); }
      catch (e) {
        if (e.status !== 409) throw e;
        if (!confirm(e.message + "\n\nDelete anyway?")) return;
        await call(T() + "?force=true", { method: "DELETE" });
      }
      toast("Test deleted");
      currentTest = null;
      await refreshTests();
      selectTab("tests");
    } catch (e) { toast(e.message, "error"); }
  });
})();

/* ---- questions ---- */
function questionRow(q, index) {
  const text = h("textarea", { rows: 3, maxlength: 2000 }); text.value = q.text;
  const score = h("input", { type: "number", min: 1, max: 100, value: q.max_score, style: "width:90px" });
  const err = h("div", { class: "form-error" });
  let armed = false;
  const del = h("button", { class: "btn danger small", type: "button", onclick: async () => {
    if (!armed) { armed = true; del.textContent = "Click again to delete"; setTimeout(() => { armed = false; del.textContent = "Delete"; }, 4000); return; }
    try { await call(T("/questions/" + q.id), { method: "DELETE" }); toast("Question deleted"); loadQuestions(); }
    catch (e) { err.textContent = e.message; }
  } }, "Delete");
  const save = h("button", { class: "btn small", type: "button", onclick: async () => {
    err.textContent = "";
    try { await call(T("/questions/" + q.id), { method: "PUT", body: { text: text.value, max_score: Number(score.value) } }); toast("Question saved"); }
    catch (e) { err.textContent = e.message; }
  } }, "Save");
  return h("div", { class: "qrow" },
    h("div", { class: "qmeta" }, h("span", { class: "mono" }, `Q${index + 1}`), h("span", { class: "muted mono" }, "max score ", score)),
    text, err, h("div", { class: "actions" }, save, del));
}
async function loadQuestions() {
  try {
    const qs = await call(T("/questions"));
    $("#qlist").replaceChildren(...(qs.length ? qs.map(questionRow) : [h("p", { class: "muted" }, "No questions yet. Add the first one below.")]));
  } catch (e) { toast(e.message, "error"); }
}
bindForm($("#qnew"), async (f) => {
  await call(T("/questions"), { method: "POST", body: { text: f.text, max_score: Number(f.max_score) } });
  $("#qtext").value = "";
  toast("Question added");
  loadQuestions();
});

/* ---- submissions ---- */
function subStatus(s) {
  if (s.submitted_at) return h("span", { class: "chip ok" }, "Submitted");
  if (s.started_at) return h("span", { class: "chip warn" }, "In progress");
  return h("span", { class: "chip" }, "Not started");
}
async function loadSubs() {
  try {
    const rows = await call(T("/submissions"));
    const submitted = rows.filter((r) => r.submitted_at).length;
    const progress = rows.filter((r) => r.started_at && !r.submitted_at).length;
    const stat = (n, label) => h("div", { class: "stat" }, h("b", {}, n), h("span", {}, label));
    $("#stats").replaceChildren(stat(rows.length, "Registered"), stat(progress, "In progress"), stat(submitted, "Submitted"));
    $("#subrows").replaceChildren(...rows.map((r) => h("tr", { class: "click", tabindex: 0, onclick: () => showDetail(r.RegNo), onkeydown: (e) => { if (e.key === "Enter") showDetail(r.RegNo); } },
      h("td", { class: "mono" }, r.RegNo), h("td", {}, r.Name), h("td", {}, [r.Branch, r.year && "Y" + r.year, r.Sec].filter(Boolean).join(" · ") || "—"),
      h("td", {}, subStatus(r)), h("td", {}, r.answered), h("td", { class: "mono" }, r.totalScore ?? "—"))));
    if (!rows.length) $("#subrows").replaceChildren(h("tr", {}, h("td", { colspan: 6, class: "muted" }, "No students registered yet.")));
  } catch (e) { toast(e.message, "error"); }
}
$("#refresh").addEventListener("click", loadSubs);

async function showDetail(regNo) {
  try {
    const d = await call(T("/submissions/" + regNo));
    const blocks = d.questions.map((q, i) => {
      const ev = d.evaluation[String(q.id)];
      return h("div", {},
        h("div", { class: "label" }, `Q${i + 1}`), h("p", {}, q.text),
        h("pre", { class: "answer" }, d.answers[String(q.id)] || "(no answer)"),
        ev ? h("p", { class: "muted mono" }, `Score: ${ev.score ?? "—"}/${q.max_score} · ${ev.status}${ev.explanation ? " · " + ev.explanation : ""}`) : null);
    });
    $("#detail").replaceChildren(h("div", { class: "panel accent" },
      h("h3", {}, `${d.Name} (${d.RegNo})`),
      h("p", { class: "muted mono" }, `${d.email} · ${d.MobNo} · started ${formatDateTime(d.started_at)} · submitted ${formatDateTime(d.submitted_at)}`),
      ...blocks,
      h("button", { class: "btn ghost small", onclick: () => $("#detail").replaceChildren() }, "Close")));
    $("#detail").scrollIntoView({ behavior: "smooth" });
  } catch (e) { toast(e.message, "error"); }
}

/* ---- students (roster) ---- */
async function loadRoster() {
  try {
    const rows = await call("/api/staff/students");
    $("#rosterCount").textContent = `(${rows.length})`;
    $("#rosterRows").replaceChildren(...(rows.length ? rows.map((r) => {
      let armed = false;
      const del = h("button", { class: "btn danger small", type: "button", onclick: async () => {
        if (!armed) { armed = true; del.textContent = "Sure?"; setTimeout(() => { armed = false; del.textContent = "Delete"; }, 4000); return; }
        try { await call("/api/staff/students/" + r.RegNo, { method: "DELETE" }); toast("Student removed"); loadRoster(); }
        catch (e) { toast(e.message, "error"); }
      } }, "Delete");
      return h("tr", {}, h("td", { class: "mono" }, r.RegNo), h("td", {}, r.Name), h("td", {}, [r.Branch, r.year && "Y" + r.year, r.Sec].filter(Boolean).join(" · ") || "—"), h("td", {}, del));
    }) : [h("tr", {}, h("td", { colspan: 4, class: "muted" }, "No students yet. Upload a list above."))]));
  } catch (e) { toast(e.message, "error"); }
}

$("#rosterUpload").addEventListener("click", async () => {
  const file = $("#rosterFile").files[0];
  const out = $("#rosterResult");
  if (!file) { out.replaceChildren(h("div", { class: "form-error" }, "Choose a .csv or .xlsx file first.")); return; }
  out.replaceChildren(h("span", { class: "muted mono" }, "Uploading…"));
  try {
    const res = await fetch("/api/staff/students/upload", {
      method: "POST", credentials: "same-origin",
      headers: { "X-Filename": file.name, "Content-Type": "application/octet-stream" }, body: file,
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) return goLogin();
    if (!res.ok) throw new Error(errorText(data.detail));
    out.replaceChildren(
      h("p", {}, h("span", { class: "chip ok" }, `${data.created} added`), " ", h("span", { class: "chip" }, `${data.updated} updated`), " ",
        data.skipped ? h("span", { class: "chip bad" }, `${data.skipped} skipped`) : null),
      data.errors.length ? h("pre", { class: "answer" }, data.errors.join("\n")) : null);
    $("#rosterFile").value = "";
    loadRoster();
  } catch (e) { out.replaceChildren(h("div", { class: "form-error" }, e.message)); }
});

$("#rosterTemplate").addEventListener("click", () => {
  const csv = "RegNo,Name,DOB,Email,Mobile,Year,Branch,Section\n1001,Asha Rao,2005-03-09,asha@example.com,9876543210,2,CSE,A\n";
  const a = h("a", { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "students-template.csv" });
  document.body.append(a); a.click(); a.remove();
});

bindForm($("#snew"), async (f) => {
  const body = { RegNo: Number(f.RegNo), Name: f.Name, dob: f.dob };
  for (const k of ["email", "MobNo", "Branch", "Sec"]) if (f[k]) body[k] = f[k];
  if (f.year) body.year = Number(f.year);
  const r = await call("/api/staff/students", { method: "POST", body });
  toast(r.created ? "Student added" : "Student updated");
  $("#snew").reset();
  loadRoster();
});

/* ---- live monitor ---- */
let monitorTimer = null;
const STATE_CHIP = {
  not_started: ["", "Not started"], in_progress: ["warn", "In progress"],
  submitted: ["ok", "Submitted"], timed_out: ["bad", "Time ran out"],
};
function stopAllPolling() { stopMonitor(); clearTimeout(gradeTimer); gradeTimer = null; }
function startMonitor() { loadMonitor(); monitorTimer = setInterval(() => { if (!document.hidden) loadMonitor(); }, 5000); }
function stopMonitor() { clearInterval(monitorTimer); monitorTimer = null; }

function armed(btn, label, run) {   // two-click confirm for destructive actions
  let on = false;
  btn.addEventListener("click", async () => {
    if (!on) { on = true; btn.textContent = "Sure?"; setTimeout(() => { on = false; btn.textContent = label; }, 4000); return; }
    on = false; btn.textContent = label;
    await run();
  });
  return btn;
}
async function act(path, body, okMsg) {
  try { await call(path, { method: "POST", body }); toast(okMsg); loadMonitor(); }
  catch (e) { toast(e.message, "error"); }
}

function monitorRow(r) {
  const [kind, label] = STATE_CHIP[r.state];
  const flagged = r.blur >= 3 || r.paste > 0;
  const mins = h("select", { "aria-label": "Extra minutes", style: "width:auto;padding:.3rem" }, [5, 10, 15, 30].map((m) => h("option", { value: m }, "+" + m + "m")));
  const extend = h("button", { class: "btn ghost small", type: "button", onclick: () => act(T(`/students/${r.RegNo}/extend`), { minutes: Number(mins.value) }, "Time extended") }, "Extend");
  const acts = [];
  if (r.state === "in_progress" || r.state === "timed_out") {
    if (r.state === "in_progress") acts.push(mins, extend);
    acts.push(armed(h("button", { class: "btn ghost small", type: "button" }, "Force submit"), "Force submit", () => act(T(`/students/${r.RegNo}/force-submit`), undefined, "Submitted")));
  }
  if (r.state !== "not_started") acts.push(armed(h("button", { class: "btn danger small", type: "button" }, "Reset"), "Reset", () => act(T(`/students/${r.RegNo}/reset`), undefined, "Attempt reset")));
  const left = r.remaining_seconds == null ? "—" : formatClock(r.remaining_seconds);
  return h("tr", { class: flagged ? "flag" : "" },
    h("td", { class: "mono" }, r.RegNo),
    h("td", {}, h("span", { class: "dot" + (r.online ? " on" : ""), title: r.online ? "Online" : "Offline" }), r.Name),
    h("td", {}, h("span", { class: "chip " + kind }, label), r.extra_minutes ? h("span", { class: "muted mono" }, ` +${r.extra_minutes}m`) : null),
    h("td", { class: "num" }, left), h("td", { class: "num" }, `${r.answered}`),
    h("td", { class: "num", style: r.blur >= 3 ? "color:var(--amber)" : "" }, r.blur),
    h("td", { class: "num", style: r.paste ? "color:var(--amber)" : "" }, r.paste),
    h("td", {}, h("div", { class: "mini" }, acts)));
}

async function loadMonitor() {
  try {
    const m = await call(T("/monitor"));
    const c = m.counts;
    const stat = (n, label) => h("div", { class: "stat" }, h("b", {}, n), h("span", {}, label));
    $("#mstats").replaceChildren(stat(c.registered, "Registered"), stat(c.not_started, "Not started"), stat(c.in_progress, "In progress"),
      stat(c.online, "Online now"), stat(c.submitted + c.timed_out, "Finished"), stat(c.flagged, "Flagged"));
    $("#mrows").replaceChildren(...(m.students.length ? m.students.map(monitorRow)
      : [h("tr", {}, h("td", { colspan: 8, class: "muted" }, "No students yet. Add them in the Students tab."))]));
    $("#annNow").textContent = m.announcement ? "Showing to students: " + m.announcement : "No announcement showing.";
    $("#mclock").textContent = `Auto-refreshing every 5 s · contest is ${m.contest.phase} · updated ${new Date().toLocaleTimeString()}`;
  } catch (e) { $("#mclock").textContent = "Refresh failed: " + e.message; }
}
async function sendAnnouncement(text) {
  try { await call(T("/announcement"), { method: "PUT", body: { text } }); toast(text ? "Announcement sent" : "Announcement cleared"); $("#annText").value = ""; loadMonitor(); }
  catch (e) { toast(e.message, "error"); }
}
$("#annSend").addEventListener("click", () => sendAnnouncement($("#annText").value));
$("#annClear").addEventListener("click", () => sendAnnouncement(""));
$("#annText").addEventListener("keydown", (e) => { if (e.key === "Enter") sendAnnouncement($("#annText").value); });

/* ---- results & grading (jobs run in the worker process; we poll the status) ---- */
let gradeTimer = null;
const JOB_CHIP = { pending: ["warn", "Waiting"], running: ["warn", "Running"], done: ["ok", "Done"], failed: ["bad", "Failed"], cancelled: ["", "Cancelled"] };
const EVAL_NAME = { manual: "manual", immediate: "immediately after each submission", after_close: "after the test closes", scheduled: "at a scheduled time" };

function renderGrade(st) {
  $("#workerChip").replaceChildren(st.worker.online ? h("span", { class: "chip ok" }, "Worker online")
    : h("span", { class: "chip bad", title: "Start it with: python -m app.worker (or docker compose up worker)" }, "Worker offline"));
  const e = st.evaluation;
  $("#evalSummary").textContent = "Evaluation starts: " + EVAL_NAME[e.mode]
    + (e.scheduled_for ? ` (${e.fired ? "ran" : "will run"} ${formatDateTime(e.scheduled_for)})` : "") + ". Change this in Settings.";
  $("#jobRows").replaceChildren(...(st.jobs.length ? st.jobs.map((j) => {
    const [kind, label] = JOB_CHIP[j.status];
    const p = j.progress;
    const cancel = j.status === "pending" ? h("button", { class: "btn ghost small", type: "button", onclick: async () => {
      try { await call(T(`/grade/${j.id}/cancel`), { method: "POST" }); pollGrade(); } catch (x) { toast(x.message, "error"); }
    } }, "Cancel") : null;
    return h("tr", {}, h("td", {}, h("span", { class: "chip " + kind }, label), j.result && j.result.failures ? h("span", { class: "chip bad", style: "margin-left:.4rem" }, j.result.failures + " with errors") : null),
      h("td", { class: "mono" }, j.trigger + (j.force ? " · force" : "")), h("td", {}, formatDateTime(j.created_at)),
      h("td", { class: "num" }, p.total ? `${p.done}/${p.total}` : "—"), h("td", {}, cancel));
  }) : [h("tr", {}, h("td", { colspan: 5, class: "muted" }, "No grading jobs yet."))]));
  const latest = st.jobs[0];
  const lines = latest ? [...(latest.error ? ["ERROR: " + latest.error] : []), ...latest.log] : [];
  $("#gradeStatus").replaceChildren(lines.length ? h("pre", { class: "answer" }, lines.join("\n")) : "");
  return st;
}
let lastJobsDone = null;
async function pollGrade() {
  clearTimeout(gradeTimer);
  try {
    const st = renderGrade(await call(T("/grade")));
    const sig = st.jobs.map((j) => j.id + j.status).join();
    if (lastJobsDone !== null && sig !== lastJobsDone && !st.active) loadResults({ skipPoll: true });   // a job just finished: refresh scores
    lastJobsDone = sig;
    gradeTimer = setTimeout(pollGrade, st.active ? 2000 : 6000);
  } catch (e) { /* ignore; retry on next tab visit */ }
}
$("#gradeRun").addEventListener("click", async () => {
  try {
    const r = await call(T("/grade?force=" + $("#gradeForce").checked), { method: "POST" });
    toast(r.queued ? (r.worker.online ? "Grading queued" : "Queued, but the worker is offline. It will run when the worker starts.") : "A grading job is already waiting");
    pollGrade();
  } catch (e) { toast(e.message, "error"); }
});

function cutoffValue() { const v = $("#cutoff").value; return v === "" ? "" : "?cutoff=" + encodeURIComponent(v); }
async function loadResults(opts = {}) {
  const q = cutoffValue();
  $("#csvLink").href = T("/results.csv") + q;
  if (!opts.skipPoll) { lastJobsDone = null; pollGrade(); }
  try {
    const r = await call(T("/results") + q);
    const stat = (n, label) => h("div", { class: "stat" }, h("b", {}, n), h("span", {}, label));
    $("#rstats").replaceChildren(stat(r.rows.length, "Students"), stat(r.graded, "Graded"), stat(r.max_total, "Max score"), ...(q ? [stat(r.shortlisted, "Shortlisted")] : []));
    $("#rrows").replaceChildren(...(r.rows.length ? r.rows.map((x, i) => {
      const [kind, label] = STATE_CHIP[x.state];
      return h("tr", { class: x.shortlisted ? "short click" : "click", tabindex: 0, onclick: () => { selectTab("subs"); showDetail(x.RegNo); } },
        h("td", { class: "num" }, x.totalScore == null ? "—" : i + 1), h("td", { class: "mono" }, x.RegNo), h("td", {}, x.Name),
        h("td", {}, [x.Branch, x.year && "Y" + x.year, x.Sec].filter(Boolean).join(" · ") || "—"),
        h("td", {}, h("span", { class: "chip " + kind }, label)), h("td", { class: "num" }, x.totalScore == null ? "—" : `${x.totalScore}/${r.max_total}`),
        h("td", {}, x.shortlisted ? h("span", { class: "chip ok" }, "Shortlisted") : null));
    }) : [h("tr", {}, h("td", { colspan: 7, class: "muted" }, "No students yet."))]));
  } catch (e) { toast(e.message, "error"); }
}
$("#cutApply").addEventListener("click", loadResults);
$("#cutoff").addEventListener("keydown", (e) => { if (e.key === "Enter") loadResults(); });

/* ---- boot ---- */
refreshTests().then(() => selectTab("tests")).catch((e) => toast(e.message, "error"));
