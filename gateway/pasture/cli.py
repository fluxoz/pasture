"""`pasture`: run pasture on any machine on a tailnet (Linux, macOS, Windows).

    pasture serve        find this node's MagicDNS name, put the gateway behind
                         `tailscale serve` and run it; the first time, show the
                         enrollment QR code
    pasture enroll       show a QR code to enroll a phone (a new one-time code
                         once the last one was used)
    pasture tls init     make your own CA and a certificate for this node, so
                         the name stays out of Certificate Transparency logs
    pasture tls phone    serve the CA certificate on the tailnet with a QR code,
                         for installing it on the phone

HTTPS comes from the node's ts.net certificate (`tailscale serve`), or, after
`pasture tls init`, from your own CA: the gateway then terminates TLS itself
and `tailscale serve` only forwards TCP. Secrets live in the state dir: a
session key, the one-time enrollment token, the passkeys enrolled with it and
the TLS keys. tmux, herdr and whisper-server are used when they are on PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from .config import ensure_secret, new_token

# Where Tailscale's CLI lives when it is not on PATH.
TAILSCALE_PATHS = (
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
)


def state_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "pasture"
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "pasture"


def find_tailscale() -> str | None:
    return shutil.which("tailscale") or next((p for p in TAILSCALE_PATHS if os.path.exists(p)), None)


def tailnet() -> dict:
    tailscale = find_tailscale()
    if not tailscale:
        raise SystemExit("pasture: Tailscale is not installed (or not on PATH); pass --host to run without it")
    try:
        out = subprocess.run([tailscale, "status", "--json"], capture_output=True, text=True, timeout=10, check=True).stdout
        status = json.loads(out)
    except (subprocess.SubprocessError, ValueError) as e:
        raise SystemExit(f"pasture: `tailscale status` failed ({e}); is Tailscale running and logged in?")
    me = status.get("Self") or {}
    name = (me.get("DNSName") or "").rstrip(".")
    if not name:
        raise SystemExit("pasture: this node has no MagicDNS name; turn MagicDNS on in the Tailscale admin console")
    return {"name": name, "https": bool(status.get("CertDomains")), "tailscale": tailscale, "ips": me.get("TailscaleIPs") or []}


def tailscale_serve(tailscale: str, args: list[str]) -> None:
    cmd = [tailscale, "serve", "--bg", "--yes", *args]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        return
    err = (r.stderr or r.stdout).strip()
    if "access denied" in err.lower() or "permission" in err.lower():
        how = "run this once as an administrator" if sys.platform == "win32" else "once, run:\n    sudo tailscale set --operator=$USER\nthen start pasture again, or"
        raise SystemExit(
            f"pasture: `tailscale serve` needs permission; {how} run it yourself and pass --no-tailscale-serve:\n"
            f"    {' '.join(cmd)}"
        )
    raise SystemExit(f"pasture: `tailscale serve` failed:\n{err}")


def tailscale_unserve(tailscale: str, flag: str) -> None:
    subprocess.run([tailscale, "serve", flag, "off"], capture_output=True, timeout=30)


def token_used(state: Path, token: bytes) -> bool:
    digest = hashlib.sha256(token).hexdigest()
    try:
        return digest in (state / "token-consumed").read_text().split()
    except FileNotFoundError:
        return False


def fresh_token(state: Path, renew: bool = False) -> str:
    path = state / "enroll-token"
    ensure_secret(path, new_token)
    token = path.read_bytes().strip()
    if renew or token_used(state, token) or len(token) < 16:
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(new_token())
        os.replace(tmp, path)
        token = path.read_bytes().strip()
    return token.decode()


def enrolled(state: Path) -> int:
    try:
        data = json.loads((state / "enrolled.json").read_text())
        return len(data) if isinstance(data, list) else 0
    except (FileNotFoundError, ValueError):
        return 0


def show_qr(url: str, what: str) -> None:
    try:
        import segno

        segno.make(url, error="m").terminal(compact=True, border=2)
    except ImportError:
        pass
    print(f"{what}\n{url}")


def enroll_url(host: str, token: str, https_port: int = 443) -> str:
    port = "" if https_port == 443 else f":{https_port}"
    return f"https://{host}{port}/enroll#t={quote(token, safe='')}"


def gateway_says_open(port: int) -> bool | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/auth/info", timeout=3) as r:
            return bool(json.load(r).get("enroll"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


# -- commands -------------------------------------------------------------------

ENROLL_HINT = "Scan it with your phone's camera, open the link, tap Create passkey. The code works once."


def cmd_enroll(args) -> None:
    state = state_dir(args.state)
    host = args.host or os.environ.get("PASTURE_HOST") or tailnet()["name"]
    token_file = os.environ.get("PASTURE_ENROLL_TOKEN_FILE")
    if token_file:  # a token from a secrets manager: shown, never rewritten
        token = Path(token_file).read_text().strip()
        if gateway_says_open(args.port) is False:
            raise SystemExit("pasture: enrollment is closed: that token was used. Rotate it in your secrets and redeploy.")
    else:
        token = fresh_token(state, renew=args.new)
    show_qr(enroll_url(host, token, args.https_port), ENROLL_HINT)


def cmd_tls_init(args) -> None:
    from . import tls

    state = state_dir(args.state)
    host = args.host or tailnet()["name"]
    try:
        p = tls.init(state, host, renew=args.renew)
    except ValueError as e:
        raise SystemExit(f"pasture: {e}")
    print(f"CA and certificate for {host} in {p['dir']} (the certificate is good for {tls.days_left(p['cert'])} days).")
    print("Next: `pasture tls phone` to install the CA on your phone, then `pasture serve` uses it.")


def phone_server(state: Path, host: str, ip: str, port: int, https_port: int = 443):
    """An HTTP server for the phone: a page with the steps, and the CA certificate."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from . import tls

    der = tls.ca_der(state)
    page = tls.PHONE_PAGE.format(host=host, origin_host=host if https_port == 443 else f"{host}:{https_port}").encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server naming)
            if self.path.startswith("/pasture-ca.cer"):
                body, ctype = der, "application/x-x509-ca-cert"
            elif self.path in ("/", "/index.html"):
                body, ctype = page, "text/html; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    return ThreadingHTTPServer((ip, port), Handler)


def cmd_tls_phone(args) -> None:
    """Serve the CA certificate over plain HTTP on the tailnet address only, until Ctrl-C."""
    from . import tls

    state = state_dir(args.state)
    if not tls.paths(state)["ca"].exists():
        raise SystemExit("pasture: no CA yet; run `pasture tls init` first")
    info = tailnet()
    host = args.host or info["name"]
    ip = next((a for a in info["ips"] if ":" not in a), None)
    if not ip:
        raise SystemExit("pasture: this node has no Tailscale IPv4 address")
    server = phone_server(state, host, ip, args.port, args.https_port)  # the tailnet address only, never 0.0.0.0
    show_qr(f"http://{host}:{args.port}/", "Scan it with your phone's camera and follow the steps on the page. Ctrl-C when done.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cmd_serve(args) -> None:
    from . import tls

    state = state_dir(args.state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    own_tls = tls.paths(state)
    use_tls = own_tls["cert"].exists() and not args.tailscale_cert
    if args.host:
        host, info = args.host, None
    else:
        info = tailnet()
        host = info["name"]
        if not info["https"] and not use_tls:
            print(
                "pasture: HTTPS certificates look off for this tailnet. Turn them on in the Tailscale admin\n"
                "console (DNS > HTTPS Certificates), or use your own CA: `pasture tls init`.",
                file=sys.stderr,
            )
    if info and not args.no_tailscale_serve:
        if use_tls:  # we terminate TLS; Tailscale forwards bytes
            tailscale_unserve(info["tailscale"], f"--https={args.https_port}")
            tailscale_serve(info["tailscale"], [f"--tcp={args.https_port}", f"tcp://127.0.0.1:{args.port}"])
        else:
            tailscale_unserve(info["tailscale"], f"--tcp={args.https_port}")
            tailscale_serve(info["tailscale"], [f"--https={args.https_port}", f"http://127.0.0.1:{args.port}"])

    env = os.environ
    env.setdefault("PASTURE_HOST", host)
    if args.https_port != 443:
        env.setdefault("PASTURE_ORIGIN", f"https://{host}:{args.https_port}")
    env["PASTURE_PORT"] = str(args.port)
    env["PASTURE_STATE_DIR"] = str(state)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    env.setdefault("PASTURE_RUNTIME_DIR", str(Path(runtime) / "pasture" if runtime else state / "run"))
    env.setdefault("PASTURE_ENROLL", "1")  # one-time codes from `pasture enroll`
    env.setdefault("PASTURE_APP_NAME", args.name)
    if use_tls:
        env.setdefault("PASTURE_TLS_CERT", str(own_tls["cert"]))
        env.setdefault("PASTURE_TLS_KEY", str(own_tls["key"]))
        env.setdefault("PASTURE_CERT_FILE", str(own_tls["cert"]))
    for var, tool in (("PASTURE_TMUX", "tmux"), ("PASTURE_HERDR", "herdr")):
        found = shutil.which(tool)
        if found and var not in env:
            env[var] = found
    whisper = env.get("PASTURE_DICTATE_SERVER") or shutil.which("whisper-server")
    if env.get("PASTURE_DICTATE_MODEL") and whisper and "PASTURE_DICTATE" not in env:
        env["PASTURE_DICTATE"] = "1"
        env["PASTURE_DICTATE_SERVER"] = whisper

    port = "" if args.https_port == 443 else f":{args.https_port}"
    how = "your own CA" if use_tls else "the ts.net certificate"
    print(f"pasture: https://{host}{port}/ ({how})", file=sys.stderr)
    if not enrolled(state) and "PASTURE_CREDENTIALS_FILE" not in env:
        print("No passkey yet. Enroll your phone:", file=sys.stderr)
        sys.stdout.flush()
        show_qr(enroll_url(host, fresh_token(state), args.https_port), ENROLL_HINT)
    else:
        print("Add another device with `pasture enroll`.", file=sys.stderr)

    from .__main__ import main as run_gateway

    run_gateway()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pasture", description=__doc__.split("\n\n")[0].split("\n")[0])
    sub = parser.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--host", help="DNS name the phone uses (default: this node's MagicDNS name)")
        p.add_argument("--port", type=int, default=int(os.environ.get("PASTURE_PORT", "8795")), help="loopback port of the gateway")
        p.add_argument("--https-port", type=int, default=443, help="tailnet HTTPS port")
        p.add_argument("--state", help="state directory")

    serve = sub.add_parser("serve", help="run pasture (the default)")
    common(serve)
    serve.add_argument("--no-tailscale-serve", action="store_true", help="don't configure tailscale serve (you front it yourself)")
    serve.add_argument("--tailscale-cert", action="store_true", help="use the ts.net certificate even if `pasture tls init` was run")
    serve.add_argument("--name", default="pasture", help="app name on the phone's home screen")
    enroll = sub.add_parser("enroll", help="show a QR code to enroll a device")
    common(enroll)
    enroll.add_argument("--new", action="store_true", help="make a new one-time code even if the last is unused")
    tls_cmd = sub.add_parser("tls", help="your own CA instead of the ts.net certificate")
    tls_sub = tls_cmd.add_subparsers(dest="tls_cmd", required=True)
    init = tls_sub.add_parser("init", help="make the CA and a certificate for this node")
    common(init)
    init.add_argument("--renew", action="store_true", help="issue a new server certificate (same CA)")
    phone = tls_sub.add_parser("phone", help="serve the CA certificate for the phone (Ctrl-C to stop)")
    common(phone)
    phone.set_defaults(port=8411)

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("serve", "enroll", "tls", "-h", "--help"):
        argv.insert(0, "serve")  # `pasture` alone, or with serve's flags
    args = parser.parse_args(argv)
    if args.cmd == "tls":
        (cmd_tls_init if args.tls_cmd == "init" else cmd_tls_phone)(args)
    else:
        (cmd_enroll if args.cmd == "enroll" else cmd_serve)(args)


if __name__ == "__main__":
    main()
