"""`pasture doctor`: is everything in place to use pasture from the phone?

One line per check, with the fix when something is missing. `--json` is for
coding agents setting pasture up for someone: every check has an id, a status
(ok, warn, fail, info), a message, and a fix to run or tell the user.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"
NIXOS_UNIT = Path("/etc/systemd/user/pasture.service")  # the NixOS module runs pasture
SYMBOL = {OK: "✓", WARN: "!", FAIL: "✗", INFO: "·"}


def check(cid: str, status: str, message: str, fix: str | None = None) -> dict:
    item = {"id": cid, "status": status, "message": message}
    if fix:
        item["fix"] = fix
    return item


def _json(cmd: list[str]) -> dict:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
        return json.loads(out) if out.strip() else {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def run(state: Path, port: int, https_port: int = 443) -> list[dict]:
    from . import cli, install, tls

    module = NIXOS_UNIT.exists()
    where = "the NixOS module" if module else f"state in {state}"
    out = [check("pasture", INFO, f"pasture {__version__} on {sys.platform}, {where}")]

    tailscale = cli.find_tailscale()
    status: dict | None = None
    if not tailscale:
        out.append(check("tailscale.installed", FAIL, "Tailscale is not installed", "Install it from https://tailscale.com/download and log in"))
    else:
        status = _json([tailscale, "status", "--json"])
        backend = status.get("BackendState")
        if backend == "Running":
            out.append(check("tailscale.running", OK, "Tailscale is connected"))
        else:
            out.append(check("tailscale.running", FAIL, f"Tailscale is not connected ({backend or 'no answer'})", "Run `tailscale up` (or open the Tailscale app) and log in"))
        name = ((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if name:
            out.append(check("tailscale.magicdns", OK, f"This machine's name: {name}"))
        else:
            out.append(check("tailscale.magicdns", FAIL, "No MagicDNS name", "Turn on MagicDNS at https://login.tailscale.com/admin/dns"))

    own = tls.paths(state)
    if module:
        out.append(check("https", INFO, "HTTPS: set up by the NixOS module (services.pasture.frontend)"))
    elif own["cert"].exists():
        days = tls.days_left(own["cert"])
        out.append(
            check("https", OK if days > 30 else WARN, f"HTTPS with your own CA; the certificate is good for {days} more days",
                  None if days > 30 else "Renew: `pasture tls init --renew`, then restart pasture")
        )
    elif status and status.get("CertDomains"):
        out.append(check("https", OK, "HTTPS with Tailscale's certificate (HTTPS certificates are on)"))
    else:
        out.append(
            check("https", FAIL, "No HTTPS yet; the phone needs it for passkeys",
                  "Either turn on HTTPS certificates at https://login.tailscale.com/admin/dns, "
                  "or use your own CA: `pasture tls init`, then `pasture tls phone` and trust it on the phone (docs/tls.md)")
        )

    if tailscale and status and status.get("BackendState") == "Running" and not module:
        serve = _json([tailscale, "serve", "status", "--json"])
        if f"127.0.0.1:{port}" in json.dumps(serve):
            out.append(check("tailscale.serve", OK, f"tailscale serve forwards port {https_port} to pasture"))
        else:
            fix = "Start pasture (`pasture serve`); it sets this up"
            if sys.platform.startswith("linux"):
                fix += ". If it reports a permission problem: `sudo tailscale set --operator=$USER` (once)"
            out.append(check("tailscale.serve", WARN, "tailscale serve does not point at pasture yet", fix))

    info = cli.gateway_info(state, port)
    if info is None:
        out.append(check("gateway", WARN, f"pasture is not running on port {port}", "Run `pasture serve`, or `pasture service install` to keep it running"))
    else:
        out.append(check("gateway", OK, f"pasture is running (enrollment {'open' if info.get('enroll') else 'closed'})"))

    n = cli.enrolled(state)
    out.append(
        check("passkeys", OK if n else WARN, f"{n} device(s) enrolled" if n else "No phone enrolled yet",
              None if n else "Run `pasture enroll` and scan the QR code with the phone's camera")
    )
    try:
        subs = len(json.loads((state / "push.json").read_text()))
    except (OSError, ValueError, TypeError):
        subs = 0
    out.append(
        check("push", OK if subs else INFO, f"{subs} device(s) get push notifications" if subs else "No device has push notifications on",
              None if subs else "In the installed app: ⋮ → Push notifications (iPhone: iOS 16.4+, app on the Home Screen)")
    )

    for tool, what in (("tmux", "tmux dashboard"), ("herdr", "agent dashboard (herdr)")):
        found = shutil.which(tool)
        out.append(check(f"tools.{tool}", INFO, f"{what}: {'uses ' + found if found else 'not installed'}"))
    whisper = os.environ.get("PASTURE_DICTATE_SERVER") or shutil.which("whisper-server")
    model = os.environ.get("PASTURE_DICTATE_MODEL")
    ready = bool(whisper and model)
    out.append(
        check("dictation", OK if ready else INFO, "Dictation: ready" if ready else "Dictation: off",
              None if ready else "Set PASTURE_DICTATE_SERVER (whisper.cpp's whisper-server) and PASTURE_DICTATE_MODEL (a ggml model); docs/setup.md")
    )
    hooked = install.claude_hooks_installed()
    out.append(
        check("hooks.claude", OK if hooked else INFO,
              "Claude Code reports to pasture" if hooked else "Claude Code sessions outside herdr do not notify the phone",
              None if hooked else "`pasture hooks claude --install`")
    )
    svc = module or install.service_installed()
    out.append(
        check("service", OK if svc else INFO, "Runs as a background service" if svc else "Not set up as a background service",
              None if svc else "`pasture service install`")
    )
    return out


def report(checks: list[dict], as_json: bool) -> int:
    failed = any(c["status"] == FAIL for c in checks)
    if as_json:
        print(json.dumps({"ok": not failed, "checks": checks}, indent=2))
    else:
        for c in checks:
            print(f"{SYMBOL[c['status']]} {c['message']}")
            if c.get("fix") and c["status"] != OK:
                print(f"    → {c['fix']}")
    return 1 if failed else 0
