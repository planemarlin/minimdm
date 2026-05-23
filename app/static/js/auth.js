/* miniMDM – auth page handlers */

function initLoginPage() {
  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("login-btn");
    const errEl = document.getElementById("login-error");
    errEl.style.display = "none";
    btn.disabled = true;
    btn.textContent = "Signing in…";

    const username = document.getElementById("username").value;
    const password = document.getElementById("password").value;

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (res.ok) {
        const rawNext = new URLSearchParams(window.location.search).get("next") || "/";
        const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";
        window.location.href = next;
      } else {
        const data = await res.json().catch(() => ({}));
        errEl.textContent = data.detail || "Invalid username or password.";
        errEl.style.display = "flex";
        btn.disabled = false;
        btn.textContent = "Sign in";
      }
    } catch {
      errEl.textContent = "Could not reach the server. Please try again.";
      errEl.style.display = "flex";
      btn.disabled = false;
      btn.textContent = "Sign in";
    }
  });
}

function initResetPasswordPage() {
  document.getElementById("reset-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("reset-btn");
    const errEl = document.getElementById("reset-error");
    const okEl  = document.getElementById("reset-success");
    errEl.style.display = "none";
    okEl.style.display  = "none";

    const password = document.getElementById("new-password").value;
    const confirm  = document.getElementById("confirm-password").value;
    const token    = document.getElementById("reset-token").value;

    if (password !== confirm) {
      errEl.textContent = "Passwords do not match.";
      errEl.style.display = "flex";
      return;
    }

    btn.disabled = true;
    btn.textContent = "Saving…";

    try {
      const res = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });

      if (res.ok) {
        document.getElementById("reset-form").style.display = "none";
        okEl.textContent = "Password updated. You can now sign in with your new password.";
        okEl.style.display = "flex";
        setTimeout(() => { window.location.href = "/login"; }, 2500);
      } else {
        const data = await res.json().catch(() => ({}));
        errEl.textContent = data.detail || "Failed to reset password.";
        errEl.style.display = "flex";
        btn.disabled = false;
        btn.textContent = "Set new password";
      }
    } catch {
      errEl.textContent = "Could not reach the server. Please try again.";
      errEl.style.display = "flex";
      btn.disabled = false;
      btn.textContent = "Set new password";
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("login-form")) initLoginPage();
  if (document.getElementById("reset-form")) initResetPasswordPage();
});
