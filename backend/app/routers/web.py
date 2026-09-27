"""External web account-deletion path for store compliance (spec §30.1).

``GET /account/delete`` serves a small page that signs the user in with the same Firebase project (Google,
Apple or email/password), shows the cross-product deletion warning and calls ``POST /web/v1/account/delete``
with a fresh ID token. The web route has no App Check (browsers have no mobile attestation), so it is limited to
this single, rate-limited, reauthentication-gated action.
"""

from __future__ import annotations

import html
import json
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.common import rate_limit
from app.common.api import Caller, get_container, run_mutation
from app.common.errors import ApiError, ErrorCode
from app.container import Container

router = APIRouter(include_in_schema=False)

FIREBASE_JS = "https://www.gstatic.com/firebasejs/10.12.2"


class WebDeleteRequest(BaseModel):
    request_id: str
    confirm: Literal["DELETE"]


async def web_caller(request: Request, c: Container = Depends(get_container)) -> Caller:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    token = await c.token_verifier.verify(header.removeprefix("Bearer ").strip())
    return Caller(token.uid, token)


@router.post("/web/v1/account/delete")
async def web_delete(body: WebDeleteRequest, request: Request, caller: Caller = Depends(web_caller),
                     c: Container = Depends(get_container)) -> dict:
    await c.rate_limiter.hit(rate_limit.WEB_DELETE, caller.uid)

    async def handler() -> dict:
        return await c.deletion.request(caller.uid, caller.token)

    return await run_mutation(c, request, caller, "account.delete", {"request_id": body.request_id}, handler)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Delete your Synova account</title>
<style>
  :root { --bg:#0f1020; --card:#1a1c33; --text:#f4f4fb; --muted:#b5b7d0; --accent:#8b5cf6; --danger:#ef4444; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; background:var(--bg);
         color:var(--text); display:flex; justify-content:center; padding:24px 16px; }
  main { width:100%%; max-width:480px; background:var(--card); border-radius:20px; padding:28px; }
  h1 { font-size:22px; margin:0 0 12px; }
  p, li { color:var(--muted); line-height:1.5; font-size:15px; }
  button { width:100%%; padding:14px; border:0; border-radius:12px; font-size:16px; font-weight:600;
           cursor:pointer; margin-top:10px; }
  .provider { background:#fff; color:#111; }
  .danger { background:var(--danger); color:#fff; }
  input { width:100%%; padding:12px; border-radius:10px; border:1px solid #3a3d60; background:#0f1020;
          color:var(--text); margin-top:8px; font-size:15px; }
  .hidden { display:none; }
  #status { margin-top:16px; min-height:22px; }
  .lang { text-align:right; font-size:13px; }
  .lang a { color:var(--muted); }
</style>
</head>
<body>
<main>
  <div class="lang"><a href="?lang=en">English</a> · <a href="?lang=tr">Türkçe</a></div>
  <h1 data-i18n="title"></h1>
  <p data-i18n="intro"></p>
  <ul>
    <li data-i18n="item1"></li><li data-i18n="item2"></li><li data-i18n="item3"></li>
  </ul>
  <section id="signin">
    <button class="provider" id="google" data-i18n="google"></button>
    <button class="provider" id="apple" data-i18n="apple"></button>
    <input id="email" type="email" autocomplete="email" data-i18n-placeholder="email">
    <input id="password" type="password" autocomplete="current-password" data-i18n-placeholder="password">
    <button class="provider" id="emailBtn" data-i18n="emailSignIn"></button>
  </section>
  <section id="confirm" class="hidden">
    <p><span data-i18n="signedInAs"></span> <strong id="who"></strong></p>
    <p data-i18n="warning"></p>
    <button class="danger" id="delete" data-i18n="delete"></button>
  </section>
  <p id="status" role="status" aria-live="polite"></p>
</main>
<script type="module">
  import { initializeApp } from "%(js)s/firebase-app.js";
  import { getAuth, connectAuthEmulator, signInWithPopup, GoogleAuthProvider, OAuthProvider,
           signInWithEmailAndPassword } from "%(js)s/firebase-auth.js";
  const cfg = %(cfg)s;
  const T = {
    en: { title: "Delete your Synova account",
      intro: "This permanently deletes your shared Synova account across every participating product.",
      item1: "Your profile, friends, devices and settings are removed.",
      item2: "Match history is anonymised; your username is held for 30 days, then released.",
      item3: "If you are in a live match, deletion completes right after it settles.",
      google: "Continue with Google", apple: "Continue with Apple", email: "Email", password: "Password",
      emailSignIn: "Sign in with email", signedInAs: "Signed in as",
      warning: "This cannot be undone. Purchases are not refunded by deleting your account.",
      delete: "Delete my account permanently", working: "Deleting…",
      done: "Your deletion request was received. You can close this page.",
      reauth: "Please sign in again, then retry.", failed: "Something went wrong. Please try again." },
    tr: { title: "Synova hesabını sil",
      intro: "Bu işlem, ortak Synova hesabını katılan tüm ürünlerde kalıcı olarak siler.",
      item1: "Profilin, arkadaşların, cihazların ve ayarların kaldırılır.",
      item2: "Maç geçmişi anonimleştirilir; kullanıcı adın 30 gün ayrılır, sonra serbest bırakılır.",
      item3: "Canlı bir maçtaysan silme işlemi maç sonuçlanınca tamamlanır.",
      google: "Google ile devam et", apple: "Apple ile devam et", email: "E-posta", password: "Şifre",
      emailSignIn: "E-posta ile giriş yap", signedInAs: "Giriş yapılan hesap:",
      warning: "Bu işlem geri alınamaz. Hesabı silmek satın alımları iade etmez.",
      delete: "Hesabımı kalıcı olarak sil", working: "Siliniyor…",
      done: "Silme talebin alındı. Bu sayfayı kapatabilirsin.",
      reauth: "Lütfen tekrar giriş yapıp yeniden dene.", failed: "Bir sorun oluştu. Lütfen tekrar dene." } };
  const lang = new URLSearchParams(location.search).get("lang") === "tr" ||
    (!location.search.includes("lang=") && navigator.language.startsWith("tr")) ? "tr" : "en";
  const t = T[lang];
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach(el => el.textContent = t[el.dataset.i18n]);
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => el.placeholder = t[el.dataset.i18nPlaceholder]);
  const app = initializeApp({ apiKey: cfg.apiKey, authDomain: cfg.authDomain, projectId: cfg.projectId });
  const auth = getAuth(app);
  if (cfg.emulator) connectAuthEmulator(auth, "http://" + cfg.emulator, { disableWarnings: true });
  const status = document.getElementById("status");
  const signedIn = (user) => {
    document.getElementById("who").textContent = user.email || user.displayName || user.uid;
    document.getElementById("signin").classList.add("hidden");
    document.getElementById("confirm").classList.remove("hidden");
  };
  const run = (p) => p.then(r => signedIn(r.user)).catch(() => status.textContent = t.failed);
  document.getElementById("google").onclick = () => run(signInWithPopup(auth, new GoogleAuthProvider()));
  document.getElementById("apple").onclick = () => run(signInWithPopup(auth, new OAuthProvider("apple.com")));
  document.getElementById("emailBtn").onclick = () => run(signInWithEmailAndPassword(auth,
    document.getElementById("email").value, document.getElementById("password").value));
  document.getElementById("delete").onclick = async () => {
    status.textContent = t.working;
    try {
      const token = await auth.currentUser.getIdToken(true);
      const res = await fetch("/web/v1/account/delete", { method: "POST",
        headers: { "authorization": "Bearer " + token, "content-type": "application/json" },
        body: JSON.stringify({ request_id: crypto.randomUUID(), confirm: "DELETE" }) });
      if (res.ok) { status.textContent = t.done; document.getElementById("delete").disabled = true; return; }
      const body = await res.json().catch(() => ({}));
      status.textContent = body?.error?.detail?.reason === "recent_login_required" ? t.reauth : t.failed;
    } catch { status.textContent = t.failed; }
  };
</script>
</body>
</html>
"""


@router.get("/account/delete", response_class=HTMLResponse)
async def delete_page(c: Container = Depends(get_container)) -> HTMLResponse:
    s = c.settings
    cfg = {"apiKey": s.firebase_web_api_key, "authDomain": s.firebase_auth_domain or
           f"{s.firebase_project_id}.firebaseapp.com", "projectId": s.firebase_project_id,
           "emulator": s.auth_emulator_host if s.env in ("dev", "test") else ""}
    # JSON inside a <script>: escape "<" so a value can never close the script element.
    body = PAGE % {"js": html.escape(FIREBASE_JS), "cfg": json.dumps(cfg).replace("<", "\\u003c")}
    csp = ("default-src 'none'; script-src 'self' 'unsafe-inline' https://www.gstatic.com https://apis.google.com; "
           "connect-src 'self' https://*.googleapis.com http://127.0.0.1:* http://localhost:*; "
           "frame-src https://*.firebaseapp.com https://appleid.apple.com https://accounts.google.com; "
           "style-src 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; form-action 'none'")
    return HTMLResponse(body, headers={"content-security-policy": csp, "x-frame-options": "DENY",
                                       "referrer-policy": "no-referrer", "cache-control": "no-store"})
