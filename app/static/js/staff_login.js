bindForm($("#staff"), async (f) => {
  await api("/api/staff/login", { method: "POST", body: { username: f.username, password: f.password } });
  location.href = "/staff";
});
