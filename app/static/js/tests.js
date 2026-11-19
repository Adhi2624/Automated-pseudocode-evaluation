"use strict";
const goLogin = () => { location.href = "/login"; };

const STATE = {
  not_started: ["", "Not started"], in_progress: ["warn", "In progress"],
  submitted: ["ok", "Submitted"], timed_out: ["bad", "Time ran out"],
};
const PHASE = { upcoming: ["warn", "Opens soon"], open: ["ok", "Open now"], closed: ["bad", "Closed"] };

function card(t) {
  const st = t.attempt.state;
  const [pk, pl] = PHASE[t.phase] || ["", t.phase];
  const [sk, sl] = STATE[st];
  let cta;
  if (st === "submitted") cta = h("a", { class: "btn ghost small", href: "/tests/" + t.id }, "View");
  else if (st === "in_progress") cta = h("a", { class: "btn small", href: "/tests/" + t.id }, "Continue");
  else if (st === "timed_out") cta = h("span", { class: "muted mono" }, "Your time is over");
  else if (t.phase === "open") cta = h("a", { class: "btn small", href: "/tests/" + t.id }, "Open");
  else cta = h("a", { class: "btn ghost small", href: "/tests/" + t.id }, "Details");
  return h("div", { class: "panel" },
    h("div", { class: "inline", style: "justify-content:space-between" }, h("span", { class: "chip " + pk }, pl), h("span", { class: "chip " + sk }, sl)),
    h("h3", { style: "margin-top:.9rem" }, t.title),
    h("p", { class: "muted mono", style: "font-size:.85rem" },
      `${t.duration_minutes} min`, t.opens_at ? ` · opens ${formatDateTime(t.opens_at)}` : "", t.closes_at ? ` · closes ${formatDateTime(t.closes_at)}` : ""),
    cta);
}

async function load() {
  try {
    const data = await api("/api/tests");
    $("#who").textContent = data.profile.Name + " · " + data.profile.RegNo;
    $("#list").replaceChildren(...(data.tests.length ? data.tests.map(card)
      : [h("div", { class: "panel" }, h("p", { class: "muted", style: "margin:0" }, "No tests are published yet. Check back soon."))]));
  } catch (e) {
    if (e.status === 401) { try { sessionStorage.setItem("notice", e.message); } catch (x) {} return goLogin(); }
    $("#list").replaceChildren(h("div", { class: "panel" }, e.message));
  }
}
$("#logout").addEventListener("click", async (e) => {
  e.preventDefault();
  try { await api("/api/student/logout", { method: "POST" }); } catch (x) { /* ignore */ }
  goLogin();
});
load();
setInterval(() => { if (!document.hidden) load(); }, 30000);
