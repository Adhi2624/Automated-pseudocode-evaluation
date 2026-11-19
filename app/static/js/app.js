/* Shared helpers: DOM builder, API wrapper, toasts, formatting. */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Build an element. Children are always text or nodes, never HTML, so user content cannot inject markup. */
function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function errorText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const field = Array.isArray(d.loc) ? d.loc.filter((p) => p !== "body").join(".") : "";
      const msg = String(d.msg || "invalid").replace(/^Value error, /, "");
      return field ? `${field}: ${msg}` : msg;
    }).join("; ");
  }
  return "Something went wrong.";
}

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiError(0, "Cannot reach the server. Check your connection.");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty or non-JSON body */ }
  if (!res.ok) throw new ApiError(res.status, errorText(data && data.detail));
  return data;
}

function toast(message, kind = "ok") {
  const el = h("div", { class: "toast " + (kind === "error" ? "error" : ""), role: "status" }, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 4500);
}

function formatDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

/** "2024-05-01T10:00:00Z" -> value for <input type="datetime-local"> in local time. */
function toLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** datetime-local value (local time) -> ISO UTC string, or null when empty. */
function fromLocalInput(value) {
  return value ? new Date(value).toISOString() : null;
}

function formatClock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return (hh ? pad(hh) + ":" : "") + pad(mm) + ":" + pad(ss);
}

/** Wire a form: run `submit(formData)` on submit, show errors in .form-error, disable the button meanwhile. */
function bindForm(form, submit) {
  const err = $(".form-error", form), btn = $("button[type=submit]", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    btn.disabled = true;
    try { await submit(Object.fromEntries(new FormData(form))); }
    catch (ex) { err.textContent = ex.message; }
    finally { btn.disabled = false; }
  });
}
