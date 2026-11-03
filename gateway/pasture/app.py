"""The aiohttp application: static PWA, passkey auth, dashboard API, SSE, PTY bridge."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from . import validate
from .auth import Auth, AuthError
from .config import Config, read_secret
from .dictate import MAX_STREAMS, Dictation, DictationError
from .hub import Hub
from .providers import ActionError
from .providers.alerts import AlertsProvider
from .providers.herdr import HerdrProvider
from .providers.shell import ShellProvider
from .providers.tmux import TmuxProvider
from .pty_bridge import MAX_PTYS_PER_SESSION, Bridge, Pty, clamp_size
from .sessions import Session, SessionStore

log = logging.getLogger("pasture")

# Styles allow 'unsafe-inline' only because xterm.js builds <style> elements at
# runtime; scripts, fonts and connections stay 'self'-only.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; media-src 'self' blob:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), payment=(), usb=(), microphone=(self), "
    "clipboard-read=(self), clipboard-write=(self), publickey-credentials-get=(self), "
    "publickey-credentials-create=(self)",
}
CSRF_HEADER = "X-Pasture"
# Variables systemd sets for the service itself; shells should not inherit them.
SERVICE_ENV = {
    "INVOCATION_ID",
    "JOURNAL_STREAM",
    "NOTIFY_SOCKET",
    "LISTEN_PID",
    "LISTEN_FDS",
    "STATE_DIRECTORY",
    "RUNTIME_DIRECTORY",
    "MANAGERPID",
    "SYSTEMD_EXEC_PID",
}

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")


class Static:
    """The PWA bundle, read into memory once (it is an immutable store path)."""

    def __init__(self, root: Path | None):
        self.files: dict[str, tuple[bytes, str, str]] = {}
        if root is None:
            return
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            data = path.read_bytes()
            ctype = mimetypes.guess_type(rel)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/json", "application/manifest+json", "image/svg+xml"):
                ctype += "; charset=utf-8"
            etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
            self.files[rel] = (data, ctype, etag)

    def response(self, request: web.Request, rel: str) -> web.Response:
        entry = self.files.get(rel)
        if entry is None:
            raise web.HTTPNotFound()
        data, ctype, etag = entry
        headers = {"ETag": etag, "Cache-Control": "no-cache"}
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304, headers=headers)
        resp = web.Response(body=data if request.method != "HEAD" else None, headers=headers)
        resp.headers["Content-Type"] = ctype
        if request.method == "HEAD":
            resp.headers["Content-Length"] = str(len(data))
        return resp


def remote_addr(request: web.Request) -> str:
    """The client address: nginx's X-Real-IP when the peer is loopback."""
    peer = request.remote or ""
    try:
        loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        loopback = False
    if loopback:
        real = request.headers.get("X-Real-IP")
        if real:
            return real.strip()
    return peer


def json_error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


def cert_days_left(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(path.read_bytes())
    except Exception:
        return None
    return (cert.not_valid_after_utc - datetime.now(timezone.utc)).days


class Gateway:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        cfg.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(cfg.state_dir, 0o700)
        key = read_secret(cfg.session_key_file)
        if len(key) < 16:
            raise SystemExit("pasture: the session key file is missing or shorter than 16 bytes")
        self.sessions = SessionStore(key, cfg.idle_minutes * 60, cfg.absolute_minutes * 60)
        self.auth = Auth(cfg)
        self.hub = Hub()
        self.static = Static(cfg.static_dir)
        self.cookie = "__Host-pasture" if cfg.secure_cookies else "pasture"
        self.pre_cookie = "__Host-pasture-pre" if cfg.secure_cookies else "pasture-pre"

        self.shell = ShellProvider(cfg) if cfg.shell_enable else None
        self.tmux = TmuxProvider(cfg, self.hub) if cfg.tmux else None
        self.herdr = HerdrProvider(cfg, self.hub) if cfg.herdr else None
        self.alerts = AlertsProvider(cfg, self.hub) if cfg.ntfy_url else None
        self.dictation = Dictation(cfg) if cfg.dictate else None
        for provider in (self.shell, self.tmux, self.herdr, self.alerts):
            if provider is not None:
                self.hub.register(provider.name, provider.state)

    # -- plumbing --------------------------------------------------------

    def client_config(self) -> dict:
        return {
            "appName": self.cfg.app_name,
            "providers": {
                "shell": self.shell is not None,
                "tmux": self.tmux is not None,
                "herdr": self.herdr is not None,
                "alerts": self.alerts is not None,
            },
            "dictation": self.dictation is not None,
            "projectRoots": [str(p) for p in self.cfg.project_roots],
            "home": str(Path.home()),
            "idleMinutes": self.cfg.idle_minutes,
        }

    def session(self, request: web.Request, touch: bool = True) -> Session | None:
        return self.sessions.get(request.cookies.get(self.cookie), touch=touch)

    def require(self, request: web.Request, touch: bool = True) -> Session:
        session = self.session(request, touch)
        if session is None:
            raise web.HTTPUnauthorized(
                text=json.dumps({"error": "login required"}), content_type="application/json"
            )
        return session

    def check_origin(self, request: web.Request) -> None:
        if request.headers.get("Origin") != self.cfg.origin:
            raise web.HTTPForbidden(text=json.dumps({"error": "bad origin"}), content_type="application/json")

    def check_csrf(self, request: web.Request) -> None:
        self.check_origin(request)
        if request.headers.get(CSRF_HEADER) != "1":
            raise web.HTTPForbidden(text=json.dumps({"error": "missing header"}), content_type="application/json")

    async def body_json(self, request: web.Request, limit: int = 64 * 1024) -> dict:
        if request.content_length is not None and request.content_length > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=request.content_length)
        raw = await request.content.read(limit + 1)
        if len(raw) > limit:
            raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=len(raw))
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise web.HTTPBadRequest(text=json.dumps({"error": "invalid JSON"}), content_type="application/json")
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text=json.dumps({"error": "expected an object"}), content_type="application/json")
        return data

    def set_session_cookie(self, resp: web.StreamResponse, value: str) -> None:
        resp.set_cookie(
            self.cookie,
            value,
            path="/",
            secure=self.cfg.secure_cookies,
            httponly=True,
            samesite="Strict",
            max_age=self.cfg.absolute_minutes * 60,
        )

    def set_pre_cookie(self, resp: web.StreamResponse, value: str) -> None:
        resp.set_cookie(
            self.pre_cookie,
            value,
            path="/",
            secure=self.cfg.secure_cookies,
            httponly=True,
            samesite="Strict",
            max_age=120,
        )

    # -- middleware ------------------------------------------------------

    @web.middleware
    async def headers_mw(self, request: web.Request, handler):
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            resp = e
            if request.path.startswith(("/api/", "/auth/")) and not (e.text or "").startswith("{"):
                resp = json_error(e.status, e.reason)
        if not resp.prepared:
            for k, v in SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
            if request.path.startswith(("/api/", "/auth/", "/ws/", "/healthz")):
                resp.headers["Cache-Control"] = "no-store"
        if isinstance(resp, web.HTTPException):
            raise resp
        return resp

    # -- auth routes -----------------------------------------------------

    async def auth_info(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "enroll": self.auth.enrollment_open(),
                "appName": self.cfg.app_name,
                "loggedIn": self.session(request, touch=False) is not None,
            }
        )

    def _limit(self, request: web.Request) -> None:
        self.auth.limiter.check(remote_addr(request))

    async def login_options(self, request: web.Request) -> web.Response:
        self.check_csrf(request)
        try:
            self._limit(request)
            pre, options = self.auth.login_options()
        except AuthError as e:
            return json_error(e.status, str(e))
        resp = web.Response(text=options, content_type="application/json")
        self.set_pre_cookie(resp, pre)
        return resp

    async def login_verify(self, request: web.Request) -> web.Response:
        self.check_csrf(request)
        body = await self.body_json(request)
        try:
            self._limit(request)
            cred_id = self.auth.login_verify(request.cookies.get(self.pre_cookie), body.get("credential"))
        except AuthError as e:
            self.auth.limiter.failure()
            log.warning("login failed from %s: %s", remote_addr(request), e)
            return json_error(e.status, str(e))
        _, cookie = self.sessions.create(cred_id)
        log.info("login ok from %s (passkey %s…)", remote_addr(request), cred_id[:8])
        resp = web.json_response({"ok": True})
        self.set_session_cookie(resp, cookie)
        resp.del_cookie(self.pre_cookie, path="/")
        return resp

    async def logout(self, request: web.Request) -> web.Response:
        self.check_csrf(request)
        session = self.session(request, touch=False)
        if session:
            self.sessions.revoke(session)
        resp = web.json_response({"ok": True})
        resp.del_cookie(self.cookie, path="/")
        return resp

    async def register_options(self, request: web.Request) -> web.Response:
        self.check_csrf(request)
        try:
            self._limit(request)
            pre, options = self.auth.register_options(request.headers.get("X-Enroll-Token"))
        except AuthError as e:
            if e.status in (401, 403):
                self.auth.limiter.failure()
            log.warning("enrollment refused from %s: %s", remote_addr(request), e)
            return json_error(e.status, str(e))
        resp = web.Response(text=options, content_type="application/json")
        self.set_pre_cookie(resp, pre)
        return resp

    async def register_verify(self, request: web.Request) -> web.Response:
        self.check_csrf(request)
        body = await self.body_json(request)
        try:
            self._limit(request)
            record = self.auth.register_verify(
                request.cookies.get(self.pre_cookie),
                request.headers.get("X-Enroll-Token"),
                body.get("credential"),
                str(body.get("label") or ""),
            )
        except AuthError as e:
            self.auth.limiter.failure()
            log.warning("enrollment failed from %s: %s", remote_addr(request), e)
            return json_error(e.status, str(e))
        _, cookie = self.sessions.create(record["id"])
        resp = web.json_response({"ok": True, "credential": record})
        self.set_session_cookie(resp, cookie)
        resp.del_cookie(self.pre_cookie, path="/")
        return resp

    # -- API -------------------------------------------------------------

    async def api_state(self, request: web.Request) -> web.Response:
        self.require(request)
        return web.json_response({"config": self.client_config(), "state": self.hub.state()})

    async def api_events(self, request: web.Request) -> web.StreamResponse:
        session = self.require(request)
        resp = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
                **SECURITY_HEADERS,
            }
        )
        await resp.prepare(request)
        queue = self.hub.subscribe()
        try:
            state = json.dumps(self.hub.state(), separators=(",", ":"))
            await resp.write(f"retry: 3000\nevent: state\ndata: {state}\n\n".encode())
            while True:
                try:
                    event, data = await asyncio.wait_for(queue.get(), 20.0)
                except asyncio.TimeoutError:
                    if not self.sessions.alive(session):
                        await resp.write(b"event: expired\ndata: {}\n\n")
                        break
                    await resp.write(b": ping\n\n")
                    continue
                if not self.sessions.alive(session):
                    await resp.write(b"event: expired\ndata: {}\n\n")
                    break
                await resp.write(f"event: {event}\ndata: {data}\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.hub.unsubscribe(queue)
        return resp

    async def api_projects(self, request: web.Request) -> web.Response:
        self.require(request)
        roots = []
        for root in self.cfg.project_roots:
            try:
                entries = sorted(
                    e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=True) and not e.name.startswith(".")
                )
            except OSError:
                continue
            roots.append({"path": str(root), "dirs": entries[:300]})
        return web.json_response({"roots": roots})

    async def api_preview(self, request: web.Request) -> web.Response:
        self.require(request, touch=False)
        kind = request.query.get("k")
        target = request.query.get("t", "")
        lines = max(1, min(int(request.query.get("n", "40") or 40), 200))
        try:
            if kind == "agent" and self.herdr:
                text = await self.herdr.preview(request.query.get("s"), target, lines)
            elif kind == "tmux" and self.tmux:
                text = await self.tmux.preview(target, lines)
            else:
                return json_error(404, "nothing to preview")
        except (ActionError, validate.Invalid) as e:
            return json_error(getattr(e, "status", 400), str(e))
        except (OSError, asyncio.TimeoutError):
            return json_error(503, "not reachable")
        return web.json_response({"text": text})

    async def api_action(self, request: web.Request) -> web.Response:
        session = self.require(request)
        self.check_csrf(request)
        body = await self.body_json(request)
        op = body.get("op")
        if not isinstance(op, str):
            return json_error(400, "missing op")
        try:
            if op.startswith("tmux_") and self.tmux:
                if op == "tmux_seen":
                    self.tmux.mark_seen(validate.tmux_name(body.get("target")))
                    result = {"ok": True}
                else:
                    result = await self.tmux.action(op, body)
            elif self.herdr and op in (
                "focus",
                "focus_pane",
                "rename_agent",
                "rename_workspace",
                "rename_tab",
                "new_agent",
                "close_pane",
                "close_workspace",
                "keys",
                "prompt",
            ):
                result = await self.herdr.action(op, body)
            else:
                return json_error(400, "unknown action")
        except (ActionError, validate.Invalid) as e:
            return json_error(getattr(e, "status", 400), str(e))
        log.info("action %s (passkey %s…)", op, session.cred_id[:8])
        return web.json_response(result)

    async def api_dictate(self, request: web.Request) -> web.Response:
        self.require(request)
        self.check_csrf(request)
        if self.dictation is None:
            return json_error(404, "dictation is off")
        ctype = (request.content_type or "").lower()
        if not (ctype.startswith("audio/") or ctype == "application/octet-stream"):
            return json_error(415, "send audio")
        limit = 2 * 1024 * 1024
        if request.content_length is not None and request.content_length > limit:
            return json_error(413, "recording too long")
        audio = await request.content.read(limit + 1)
        try:
            text = await self.dictation.transcribe_upload(audio)
        except DictationError as e:
            return json_error(e.status, str(e))
        return web.json_response({"text": text})

    # -- terminal --------------------------------------------------------

    def term_argv(self, kind: str | None, target: str, session_name: str | None) -> list[str]:
        if kind == "shell" and self.shell:
            return self.shell.argv()
        if kind == "tmux" and self.tmux:
            return self.tmux.argv(target or (self.cfg.tmux_default or ""))
        if kind == "agent" and self.herdr:
            return self.herdr.argv_agent(session_name, target)
        if kind == "herdr" and self.herdr:
            return self.herdr.argv_tui(session_name)
        raise ActionError("unknown terminal kind", 404)

    def term_env(self) -> dict[str, str]:
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("PASTURE_") or key in SERVICE_ENV:
                env.pop(key)
        env.update({"TERM": "xterm-256color", "COLORTERM": "truecolor", "LANG": env.get("LANG") or "C.UTF-8"})
        return env

    async def ws_term(self, request: web.Request) -> web.StreamResponse:
        session = self.session(request)
        if session is None:
            return json_error(401, "login required")
        if request.headers.get("Origin") != self.cfg.origin:
            return json_error(403, "bad origin")
        q = request.query
        try:
            argv = self.term_argv(q.get("k"), q.get("t", ""), q.get("s"))
        except (ActionError, validate.Invalid) as e:
            return json_error(getattr(e, "status", 400), str(e))
        if session.ptys >= MAX_PTYS_PER_SESSION:
            return json_error(429, "too many open terminals")
        cols, rows = clamp_size(q.get("c"), q.get("r"))

        ws = web.WebSocketResponse(max_msg_size=64 * 1024, heartbeat=30.0, compress=False)
        await ws.prepare(request)
        session.ptys += 1
        if q.get("k") == "tmux" and self.tmux:
            self.tmux.mark_seen(q.get("t") or self.cfg.tmux_default or "")
        log.info("terminal open: %s (passkey %s…)", " ".join(argv[1:4]) or argv[0], session.cred_id[:8])
        pty = Pty(argv, self.term_env(), str(Path.home()), cols, rows)
        bridge = Bridge(ws, pty, alive=lambda: self.sessions.alive(session), touch=lambda: self.sessions.touch(session))
        try:
            await bridge.run()
        except OSError as e:
            log.warning("terminal failed: %s", e)
            if not ws.closed:
                await ws.close(code=1011, message=b"spawn failed")
        finally:
            session.ptys -= 1
            if q.get("k") == "tmux" and self.tmux:
                self.tmux.mark_seen(q.get("t") or self.cfg.tmux_default or "")
        return ws

    async def ws_dictate(self, request: web.Request) -> web.StreamResponse:
        session = self.session(request)
        if session is None:
            return json_error(401, "login required")
        if request.headers.get("Origin") != self.cfg.origin:
            return json_error(403, "bad origin")
        if self.dictation is None:
            return json_error(404, "dictation is off")
        if self.dictation.streams >= MAX_STREAMS:
            return json_error(429, "busy with other recordings")
        ws = web.WebSocketResponse(max_msg_size=256 * 1024, heartbeat=30.0, compress=False)
        await ws.prepare(request)
        await self.dictation.stream(ws)
        return ws

    # -- static and health ----------------------------------------------

    async def healthz(self, request: web.Request) -> web.Response:
        peer = request.remote or ""
        forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP")
        try:
            ok = ipaddress.ip_address(peer).is_loopback and not forwarded
        except ValueError:
            ok = False
        if not ok:
            raise web.HTTPNotFound()
        return web.json_response({"ok": True, "cert_days_left": cert_days_left(self.cfg.cert_file)})

    async def static_handler(self, request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        if path in ("", "index.html"):
            return self.static.response(request, "index.html")
        if path == "enroll":
            # Served while enrollment is configured, even after the token is used,
            # so a scanned link says "already used" instead of a bare 404.
            if not self.cfg.enrollment:
                raise web.HTTPNotFound()
            return self.static.response(request, "index.html")
        return self.static.response(request, path)

    # -- lifecycle -------------------------------------------------------

    async def on_startup(self, app: web.Application) -> None:
        for provider in (self.tmux, self.herdr, self.alerts):
            if provider is not None:
                try:
                    await provider.start()
                except Exception:
                    log.exception("provider %s failed to start", provider.name)
        if self.dictation is not None:
            # Load and warm the model now, not on the first word someone says.
            self._warming = asyncio.create_task(self.dictation.warm())

    async def on_cleanup(self, app: web.Application) -> None:
        for provider in (self.tmux, self.herdr, self.alerts):
            if provider is not None:
                await provider.stop()
        if self.dictation is not None:
            await self.dictation.close()

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.headers_mw], client_max_size=2 * 1024 * 1024 + 1024)
        r = app.router
        r.add_get("/healthz", self.healthz)
        r.add_get("/auth/info", self.auth_info)
        r.add_post("/auth/login/options", self.login_options)
        r.add_post("/auth/login/verify", self.login_verify)
        r.add_post("/auth/logout", self.logout)
        r.add_post("/auth/register/options", self.register_options)
        r.add_post("/auth/register/verify", self.register_verify)
        r.add_get("/api/state", self.api_state)
        r.add_get("/api/events", self.api_events)
        r.add_get("/api/projects", self.api_projects)
        r.add_get("/api/preview", self.api_preview)
        r.add_post("/api/action", self.api_action)
        r.add_post("/api/dictate", self.api_dictate)
        r.add_get("/ws/term", self.ws_term)
        r.add_get("/ws/dictate", self.ws_dictate)
        r.add_get("/{path:.*}", self.static_handler)
        app.on_startup.append(self.on_startup)
        app.on_cleanup.append(self.on_cleanup)
        return app
