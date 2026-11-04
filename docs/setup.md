# Setting up pasture

This guide takes you from nothing to your phone talking to your agents:
Tailscale, HTTPS (Tailscale's certificate or your own CA), the passkey, and
keeping pasture running. For NixOS, see the [README](../README.md#nixos).

## 1. Tailscale on the machine and the phone

pasture is reachable only on your tailnet, so both ends need Tailscale.

1. Install Tailscale on the machine that runs your agents
   ([downloads](https://tailscale.com/download)) and log in.
2. Install the Tailscale app on your phone and log in to the same tailnet.
3. In the [admin console](https://login.tailscale.com/admin/dns), turn on
   **MagicDNS**. Your machine now has a name like
   `myhost.your-tailnet.ts.net`. That name is what the phone opens, and your
   passkey is bound to it, so keep it (rename the machine before you enroll,
   not after).
4. If you share the tailnet with others, limit who can reach the machine with
   an [ACL](https://tailscale.com/kb/1018/acls): pasture is a shell on your
   machine.

## 2. Get pasture

| Platform | Get it |
|---|---|
| Linux (x86_64, arm64) | `pasture-linux-*` from [Releases](https://github.com/fluxoz/pasture/releases), or `nix run github:fluxoz/pasture` |
| macOS (Apple Silicon, Intel) | `pasture-macos-*` from Releases |
| Windows (x86_64) | `pasture-windows-x86_64.exe` from Releases |
| Anything with Python 3.11+ | `pip install pasture-*.whl` (from Releases) |

```sh
chmod +x pasture-linux-x86_64 && mv pasture-linux-x86_64 ~/.local/bin/pasture
```

On macOS the binary is not notarized: after downloading, run
`xattr -d com.apple.quarantine pasture-macos-arm64` (or right-click → Open
once). On Windows, SmartScreen may ask you to confirm the first run.

What you get per platform:

- **Linux and macOS**: terminals are your login shell; tmux and
  [herdr](https://herdr.dev) dashboards when they are installed.
- **Windows**: terminals are PowerShell (ConPTY). tmux and herdr do not run on
  Windows; agents in PowerShell windows work, the agent dashboard does not.

## 3. HTTPS: pick one

Passkeys only work on an HTTPS page the phone trusts. Two ways:

### A. Tailscale's certificate (simplest)

Turn on **HTTPS certificates** in the admin console (DNS page). pasture then
uses `tailscale serve`, which gets a Let's Encrypt certificate for your
`ts.net` name. Nothing to install on the phone.

The trade-off: public certificates are logged in
[Certificate Transparency](https://certificate.transparency.dev/) logs, so your
machine's `ts.net` name becomes public (not reachable, but known).

### B. Your own CA (nothing public)

Make a certificate authority that can only vouch for this one machine's name,
and teach your phone to trust it.

```sh
pasture tls init      # a CA and a certificate for this machine's MagicDNS name
pasture tls phone     # serves the CA on your tailnet and prints a QR code
```

The CA carries an X.509 *name constraint*: even if its key leaked, it could not
sign a certificate for any other site, so trusting it on your phone risks
nothing beyond pasture. The keys stay in pasture's state directory.

Scan the QR code with the phone's camera; the page walks you through it:

**iPhone / iPad**

1. Tap **Download the certificate**, then **Allow**.
2. Open Settings. Tap **Profile Downloaded** near the top (or General → VPN &
   Device Management), then **Install** and enter your passcode.
3. Settings → General → About → **Certificate Trust Settings**: turn on
   **pasture CA (your machine's name)**. iOS will not trust it for websites
   until you do this.

**Android**

1. Tap **Download the certificate**.
2. Settings → Security → Encryption & credentials → **Install a certificate**
   → **CA certificate**, and pick the downloaded file.

Press Ctrl-C in the terminal once the phone has it. From now on
`pasture serve` terminates TLS itself with your certificate and asks Tailscale
only to forward TCP (`tailscale serve --tcp`), so Tailscale never needs to
issue a certificate. The certificate is valid for 800 days (iOS's limit is
825); `pasture tls init --renew` issues a new one from the same CA, nothing to
reinstall on the phone.

## 4. Start it and enroll your phone

```sh
pasture            # same as `pasture serve`
```

On Linux, `tailscale serve` needs permission once:
`sudo tailscale set --operator=$USER`. pasture prints the exact command if it
is missing. On Windows, run the printed command once in an administrator
terminal if Tailscale says access is denied.

The first time, pasture prints a QR code:

1. Scan it with the phone's camera and open the link (Safari on iPhone).
2. Tap **Create passkey** and confirm with Face ID.
3. Share → **Add to Home Screen**. Open the installed app and tap **Unlock**.

The code works once. For another device: `pasture enroll`.

## 5. Notifications

In the installed app: ⋮ → **Push notifications**, allow them, then
**Send a test** and lock the phone. Choose whether you want an alert when an
agent needs you, when one finishes, or both. iPhone needs iOS 16.4 or later
and the app on the Home Screen.

Alerts go through your phone's push service (Apple's for an iPhone), encrypted
end to end; the service sees only that a message of some size arrived.

## 6. Dictation (the mic button)

pasture runs whisper.cpp's `whisper-server` on your machine. Give it the server
and a model:

```sh
export PASTURE_DICTATE_SERVER=/path/to/whisper-server
export PASTURE_DICTATE_MODEL=/path/to/ggml-small.en-q8_0.bin
pasture
```

- Models: [ggml-base.en-q8_0.bin](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en-q8_0.bin)
  (fast on a CPU) or
  [ggml-small.en-q8_0.bin](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q8_0.bin)
  (better, wants a GPU).
- macOS: `brew install whisper-cpp` (Metal on Apple Silicon).
- Windows: the [whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases)
  have CPU, CUDA and Vulkan builds.
- Linux with Nix: `nix run github:fluxoz/pasture#pasture-dictation` bundles a
  CPU build and the base.en model.

With a GPU the text lands about 50 ms after you stop talking; on a fast CPU,
about half a second. Speak, pause, and it types the text and presses Enter
(change both in a terminal's ⋮ menu).

## 7. Keep it running

**Linux (systemd user service)**: `~/.config/systemd/user/pasture.service`:

```ini
[Unit]
Description=pasture
After=network-online.target

[Service]
ExecStart=%h/.local/bin/pasture serve
Restart=on-failure

[Install]
WantedBy=default.target
```

```sh
systemctl --user enable --now pasture
loginctl enable-linger $USER    # keep running while logged out
```

With home-manager, use the module instead (README).

**macOS (launchd)**: `~/Library/LaunchAgents/dev.pasture.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.pasture</string>
  <key>ProgramArguments</key><array><string>/usr/local/bin/pasture</string><string>serve</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>/tmp/pasture.log</string>
</dict></plist>
```

```sh
launchctl load ~/Library/LaunchAgents/dev.pasture.plist
```

**Windows**: Task Scheduler → Create Task → trigger **At log on**, action
`pasture-windows-x86_64.exe serve`, and "Run only when user is logged on" (the
terminals are your desktop session's).

## Where things live

- State (session key, enrollment code, passkeys, push subscriptions, TLS keys):
  `~/.local/state/pasture` (Linux, macOS), `%LOCALAPPDATA%\pasture` (Windows).
- Logs: the terminal you started it in, or `journalctl --user -u pasture`.
- Start over: stop pasture and delete the state directory; then enroll again.
