$("#out").addEventListener("click", async () => { try { await api("/api/student/logout", { method: "POST" }); } catch (e) {} location.href = "/"; });
