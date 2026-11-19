"use strict";
try {
  const n = sessionStorage.getItem("notice");
  if (n) { $("#notice").textContent = n; sessionStorage.removeItem("notice"); }
} catch (e) { /* storage unavailable */ }
bindForm($("#login"), async (f) => {
  await api("/api/student/login", { method: "POST", body: { RegNo: Number(f.RegNo), dob: f.dob } });
  location.href = "/tests";
});
