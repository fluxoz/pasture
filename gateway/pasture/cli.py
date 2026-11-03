"""`pasture`: run pasture on any machine on a tailnet, no NixOS module needed.

    pasture serve     find this node's MagicDNS name, put the gateway behind
                      `tailscale serve` (HTTPS with the node's ts.net
                      certificate) and run it; the first time, show the
                      enrollment QR code
    pasture enroll    show a QR code to enroll a phone (a new one-time code
                      once the last one was used)

Secrets live in the state dir ($XDG_STATE_HOME/pasture): a session key, the
one-time enrollment token, and the passkeys enrolled with it. tmux, herdr
and whisper-server are used when they are on PATH.
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

from .config import ensure_secret, new_token


def state_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "pasture"


def tailnet() -> dict:
    tailscale = shutil.which("tailscale")
    if not tailscale:
        raise SystemExit("pasture: tailscale is not installed (or not on PATH); pass --host to run without it")
    try:
        out = subprocess.run([tailscale, "status", "--json"], capture_output=True, text=True, timeout=10, check=True).stdout
        status = json.loads(out)
    except (subprocess.SubprocessError, ValueError) as e:
        raise SystemExit(f"pasture: `tailscale status` failed ({e}); is tailscaled running and logged in?")
    name = ((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
    if not name:
        raise SystemExit("pasture: this node has no MagicDNS name; turn MagicDNS on in the Tailscale admin console")
    return {"name": name, "https": bool(status.get("CertDomains")), "tailscale": tailscale}


def serve_https(tailscale: str, https_port: int, port: int) -> None:
    cmd = [tailscale, "serve", "--bg", "--yes", f"--https={https_port}", f"http://127.0.0.1:{port}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode == 0:
        return
    err = (r.stderr or r.stdout).strip()
    if "access denied" in err.lower() or "permission" in err.lower():
        raise SystemExit(
            "pasture: `tailscale serve` needs permission. Once, run:\n"
            f"    sudo tailscale set --operator=$USER\n"
            "then start pasture again (or run this yourself and pass --no-tailscale-serve):\n"
            f"    sudo {' '.join(cmd)}"
        )
    raise SystemExit(f"pasture: `tailscale serve` failed:\n{err}")


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


def show_qr(url: str) -> None:
    qrencode = shutil.which("qrencode")
    if qrencode:
        kind = "ANSIUTF8" if sys.stdout.isatty() else "UTF8"
        subprocess.run([qrencode, "-t", kind, "-m", "2", "--", url], check=False)
    print(f"Scan it with your phone's camera, open the link, tap Create passkey.\n{url}\n(The code works once.)")


def enroll_url(host: str, token: str) -> str:
    from urllib.parse import quote

    return f"https://{host}/enroll#t={quote(token, safe='')}"


def gateway_says_open(port: int) -> bool | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/auth/info", timeout=3) as r:
            return bool(json.load(r).get("enroll"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


# -- commands -------------------------------------------------------------------


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
    show_qr(enroll_url(host, token))


def cmd_serve(args) -> None:
    state = state_dir(args.state)
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.host:
        host, info = args.host, None
    else:
        info = tailnet()
        host = info["name"]
        if not info["https"]:
            print(
                "pasture: HTTPS certificates look off for this tailnet. Turn them on in the Tailscale admin\n"
                "console (DNS > HTTPS Certificates); the phone needs https:// for passkeys.",
                file=sys.stderr,
            )
    if info and not args.no_tailscale_serve:
        serve_https(info["tailscale"], args.https_port, args.port)

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
    for var, tool in (("PASTURE_TMUX", "tmux"), ("PASTURE_HERDR", "herdr")):
        found = shutil.which(tool)
        if found and var not in env:
            env[var] = found
    whisper = env.get("PASTURE_DICTATE_SERVER") or shutil.which("whisper-server")
    if env.get("PASTURE_DICTATE_MODEL") and whisper and "PASTURE_DICTATE" not in env:
        env["PASTURE_DICTATE"] = "1"
        env["PASTURE_DICTATE_SERVER"] = whisper

    print(f"pasture: https://{host}{'' if args.https_port == 443 else f':{args.https_port}'}/", file=sys.stderr)
    if not enrolled(state) and "PASTURE_CREDENTIALS_FILE" not in env:
        print("No passkey yet. Enroll your phone:", file=sys.stderr)
        sys.stdout.flush()
        show_qr(enroll_url(host, fresh_token(state)))
    else:
        print("Add another device with `pasture enroll`.", file=sys.stderr)

    from .__main__ import main as run_gateway

    run_gateway()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pasture", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--host", help="DNS name the phone uses (default: this node's MagicDNS name)")
        p.add_argument("--port", type=int, default=int(os.environ.get("PASTURE_PORT", "8795")), help="loopback port of the gateway")
        p.add_argument("--state", help="state directory (default: $XDG_STATE_HOME/pasture)")

    serve = sub.add_parser("serve", help="run pasture (the default)")
    common(serve)
    serve.add_argument("--https-port", type=int, default=443, help="tailnet HTTPS port for tailscale serve")
    serve.add_argument("--no-tailscale-serve", action="store_true", help="don't configure tailscale serve (you front it yourself)")
    serve.add_argument("--name", default="pasture", help="app name on the phone's home screen")
    enroll = sub.add_parser("enroll", help="show a QR code to enroll a device")
    common(enroll)
    enroll.add_argument("--new", action="store_true", help="make a new one-time code even if the last is unused")

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("serve", "enroll", "-h", "--help"):
        argv.insert(0, "serve")  # `pasture` alone, or with serve's flags
    args = parser.parse_args(argv)
    (cmd_enroll if args.cmd == "enroll" else cmd_serve)(args)


if __name__ == "__main__":
    main()
