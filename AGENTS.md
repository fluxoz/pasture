# AGENTS.md

For coding agents. Two jobs: **setting pasture up for your user** (most
likely, if they pointed you here) and **working on this repository**.

## Setting pasture up for your user

The goal: your user opens pasture on their phone over Tailscale, unlocked with
a passkey, sees their agents, gets push notifications, and (optionally)
dictates. Human docs: [docs/setup.md](docs/setup.md); details on HTTPS:
[docs/tls.md](docs/tls.md); NixOS: [docs/nixos.md](docs/nixos.md).

### Ground rules

- **pasture is a shell on this machine for whoever unlocks it.** Keep it on the
  tailnet: never `tailscale funnel`, never a public reverse proxy, never bind
  it to `0.0.0.0` or a LAN address.
- Run it as the user, never as root. The only command that needs `sudo` is
  `sudo tailscale set --operator=$USER` (Linux, once): ask before running it.
- **Ask first** before: picking the HTTPS mode (below), installing a background
  service, adding hooks to the user's Claude Code settings, editing a NixOS or
  home-manager configuration, or deploying it.
- The enrollment link/QR code is a one-time credential. Show it to your user
  and nowhere else (no issues, commits, logs or other chats).
- Never delete pasture's state directory (`~/.local/state/pasture`,
  `%LOCALAPPDATA%\pasture` on Windows): it holds the passkeys and, with the own
  CA, the CA.
- Some steps need the user's hands: Tailscale login and admin-console
  switches, scanning QR codes, installing a CA profile, Face ID, "Add to Home
  Screen". Say exactly what to tap, then wait for them to confirm.

### Steps

`pasture doctor --json` drives the whole thing: each check has an `id`, a
`status` (`ok`, `warn`, `fail`, `info`) and, unless it is ok, a `fix`. Run it
after every step and work through what is left.

1. **Get pasture.** Is it on PATH (`pasture --version`)? If not, ask how they
   want it:
   - a release binary (default):

     ```sh
     # pick: linux-x86_64, linux-arm64, macos-arm64, macos-x86_64
     T=linux-x86_64
     mkdir -p ~/.local/bin
     curl -fL -o ~/.local/bin/pasture "https://github.com/fluxoz/pasture/releases/latest/download/pasture-$T"
     chmod +x ~/.local/bin/pasture
     xattr -d com.apple.quarantine ~/.local/bin/pasture 2>/dev/null || true   # macOS
     ```

     Windows (PowerShell):

     ```powershell
     New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\pasture" | Out-Null
     Invoke-WebRequest "https://github.com/fluxoz/pasture/releases/latest/download/pasture-windows-x86_64.exe" -OutFile "$env:LOCALAPPDATA\pasture\pasture.exe"
     ```

     Checksums: `SHA256SUMS` in the same release.
   - with Nix: `nix run github:fluxoz/pasture -- <command>`, or the
     home-manager / NixOS module (docs/nixos.md). With a module, edit their
     configuration and let them deploy.
2. **Tailscale.** Installed, connected, MagicDNS on (`tailscale.*` checks). The
   install and login are theirs; MagicDNS is a switch at
   https://login.tailscale.com/admin/dns.
3. **HTTPS.** Ask: "Tailscale's certificate (one switch, but your machine's
   name becomes public in Certificate Transparency logs) or your own CA
   (nothing public, you install one certificate on the phone)?"
   - Tailscale's: they turn on HTTPS certificates on the DNS page.
   - Own CA: run `pasture tls init`. Then run `pasture tls phone` in the
     background (it serves until stopped), show its QR code or link, and walk
     them through docs/tls.md "Installing the CA on the phone". Stop it when
     they confirm.
4. **Run it.** If they want it always on (usually yes), `pasture service install`
   (pass serve options after `--`). Otherwise `pasture serve` in a terminal they
   keep. On Linux, if it reports a `tailscale serve` permission problem, ask to
   run `sudo tailscale set --operator=$USER`, then restart it.
5. **Enroll the phone.** Run `pasture enroll`: it prints a QR code and the
   link. They scan it with the camera, tap Create passkey, then Share → Add to
   Home Screen, open the app and tap Unlock.
6. **Notifications.** In the installed app: ⋮ → Push notifications → Allow →
   Send a test. If they use Claude Code, offer `pasture hooks claude --install`
   (merges two hooks into `~/.claude/settings.json`, plus a rule that lets
   agents read the images the user sends from the phone; keeps a backup); new
   sessions then notify. Grok Build: `pasture hooks grok --install`.
7. **Dictation (optional).** Needs whisper.cpp's `whisper-server` (macOS:
   `brew install whisper-cpp`; Windows: a whisper.cpp release; Linux: their
   package manager, or the Nix `pasture-dictation` package) and a model, e.g.
   `ggml-base.en-q8_0.bin` (CPU) or `ggml-small.en-q8_0.bin` (GPU) from
   https://huggingface.co/ggerganov/whisper.cpp. Set `PASTURE_DICTATE_SERVER`
   and `PASTURE_DICTATE_MODEL`, then re-run `pasture service install` from that
   shell so the service keeps them.
8. **Check.** `pasture doctor` until nothing fails; ask them to confirm the
   dashboard opens on the phone and a test notification arrives.

## Working on this repository

- `gateway/`: Python 3.11+, aiohttp. Auth (WebAuthn), sessions, providers
  (shell, tmux, herdr, alerts), the PTY bridge (POSIX PTY or Windows ConPTY),
  dictation (whisper-server), Web Push, the `pasture` command
  (`cli.py`, `doctor.py`, `install.py`, `tls.py`).
- `web/`: the PWA, vanilla ES modules and one stylesheet, bundled by
  `web/build.py`. No CDN, no frameworks.
- `nix/`: packages, the NixOS and home-manager modules, the theme.
- Tests: `cd gateway && python -m unittest discover -s tests -t . -v`
  (dependencies: `pip install ./gateway`, or `nix develop`). They must pass on
  Linux, macOS and Windows; skip a test on a platform only when the feature
  cannot exist there.
- Builds: `nix build .#gateway .#web .#pasture` (the gateway's tests run in its
  build). CI runs both on every push; tags `v*` publish release binaries.
- Keep: everything on the tailnet; strict CSP; inputs validated, herdr calls
  from a fixed allowlist, client JSON never forwarded; Web Push only to known
  push services; no audio or text in logs.
- Never commit media (videos, recordings) or anything identifying a person or
  machine (host names, tailnet names, IPs, user names, emails); examples use
  `example.ts.net` and `100.64.0.0/10` addresses.
- Docs live in `README.md` and `docs/`; update them with behaviour changes.
