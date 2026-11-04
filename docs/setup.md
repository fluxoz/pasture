# Getting started

From nothing to your phone talking to your agents, on Linux, macOS or
Windows. NixOS has its own guide: [nixos.md](nixos.md). Would rather have
your coding agent do it? See [Let your agent set it up](../README.md#let-your-agent-set-it-up).

At any point, `pasture doctor` checks everything and says what to fix next.

## 1. Tailscale on the machine and the phone

pasture is reachable only on your tailnet, so both ends need Tailscale.

1. Install [Tailscale](https://tailscale.com/download) on the machine where
   your agents run, and log in.
2. Install the Tailscale app on your phone and log in to the **same** tailnet.
   Keep it connected when you use pasture.
3. In the [admin console](https://login.tailscale.com/admin/dns), turn on
   **MagicDNS**. Your machine now has a name like `myhost.your-tailnet.ts.net`.
   That is the address the phone opens, and your passkey is tied to it: if you
   want a different machine name, rename it now, before you enroll.
4. If anyone else is on your tailnet, use an
   [ACL](https://tailscale.com/kb/1018/acls) so only your devices reach this
   machine. pasture is a shell on it.

## 2. Install pasture

| Platform | Get it |
|---|---|
| Linux (x86_64, arm64) | `pasture-linux-*` from [Releases](https://github.com/fluxoz/pasture/releases) |
| macOS (Apple Silicon, Intel) | `pasture-macos-*` from Releases |
| Windows (x86_64) | `pasture-windows-x86_64.exe` from Releases |
| Linux or macOS with Nix | `nix run github:fluxoz/pasture` (or the [home-manager module](nixos.md#home-manager)) |
| Anything with Python 3.11+ | `pip install pasture-*.whl` from Releases |

Linux and macOS:

```sh
chmod +x pasture-macos-arm64
mkdir -p ~/.local/bin && mv pasture-macos-arm64 ~/.local/bin/pasture   # make sure ~/.local/bin is on PATH
xattr -d com.apple.quarantine ~/.local/bin/pasture                    # macOS only: the binary is not notarized
```

Windows: put `pasture-windows-x86_64.exe` somewhere permanent, e.g.
`%LOCALAPPDATA%\pasture\pasture.exe`, and run it from PowerShell. SmartScreen
asks once ("More info" → "Run anyway").

What you get:

- **Linux and macOS**: terminals are your login shell; the tmux dashboard if
  tmux is installed; the agent dashboard if [herdr](https://herdr.dev) is.
- **Windows**: terminals are PowerShell (ConPTY). tmux and herdr do not run on
  Windows, so there is no agent dashboard; terminals, dictation and
  notifications work.

## 3. Choose HTTPS

Passkeys need an HTTPS page the phone trusts. Pick one; [tls.md](tls.md) has
the details.

- **Tailscale's certificate** (one switch): turn on **HTTPS certificates** on
  the [DNS page](https://login.tailscale.com/admin/dns). Nothing to install on
  the phone. Your machine's name ends up in public Certificate Transparency
  logs (known, not reachable).
- **Your own CA** (nothing public): run `pasture tls init`, then
  `pasture tls phone` and scan the QR code to install and trust the CA on the
  phone ([step by step](tls.md#your-own-ca)). The CA can only ever vouch for
  this one machine's name.

## 4. Start pasture and enroll your phone

```sh
pasture
```

It finds the machine's name, sets up `tailscale serve`, and the first time
prints a QR code.

- **Linux**: if it says `tailscale serve` needs permission, run
  `sudo tailscale set --operator=$USER` once and start it again.
- **Windows**: if Tailscale says access is denied, run the command pasture
  prints once in an administrator PowerShell.

On the phone:

1. Scan the QR code with the **camera** and open the link (Safari on iPhone).
2. Tap **Create passkey** and confirm with Face ID or your fingerprint.
3. Install the app: Share → **Add to Home Screen** (iPhone), or ⋮ → **Install
   app** (Android Chrome). Open it and tap **Unlock**.

The code works once. `pasture enroll` makes a new one for another device.

## 5. Keep it running

```sh
pasture service install
```

That is a systemd user service on Linux, a launchd agent on macOS and a
Startup-folder entry on Windows, running `pasture serve` with the PATH and any
`PASTURE_*` settings of the shell you run it from. Options for `serve` go after
`--`, e.g. `pasture service install -- --name devbox`.

- Linux: `loginctl enable-linger $USER` keeps it running while you are logged
  out. Logs: `journalctl --user -u pasture -f`.
- macOS logs: `~/Library/Logs/pasture.log`.
- `pasture service uninstall` removes it; `--dry-run` shows what it would do.

## 6. Notifications on the lock screen

In the installed app: ⋮ → **Push notifications** → Allow → **Send a test**,
then lock the phone. Choose alerts for "needs you", "finishes", or both.
(iPhone: iOS 16.4 or later, the app on the Home Screen.)

No account and no notification app: pasture signs pushes with its own key and
sends them to your phone's push service (Apple's or Google's), encrypted end
to end.

Where alerts come from:

- **herdr agents**: automatically, when one starts waiting for you or finishes.
- **Claude Code**: `pasture hooks claude --install` adds two hooks to
  `~/.claude/settings.json` (merged in; a backup is kept). New sessions report
  to pasture, inside herdr or not. Grok Build: `pasture hooks grok --install`.
- **Anything else**: `pasture notify --kind done --agent build "Release is out"`.

While the app is open in front, alerts show inside it instead of as a push.

## 7. Images

Show an agent a screenshot, a whiteboard or an error on another screen:

- In a terminal, tap the **image** key at the right of the key bar (next to
  Enter) and take a photo or pick from your library; several at once work.
- Or copy a screenshot and tap the **paste** key: an image on the clipboard is
  sent as an image.
- In an agent's Prompt sheet, the image button adds them to the prompt.

pasture shrinks each image to at most 2048 px on the phone (which also drops
its metadata, GPS included), stores it in pasture's `uploads` folder on the
machine, and types its path into the session. Claude Code takes an image path
in a prompt as the image. `pasture hooks claude --install` also lets agents
read that folder without asking. Uploads are deleted after 7 days
(`PASTURE_UPLOAD_DAYS`).

## 8. Dictation

pasture runs whisper.cpp's `whisper-server` on your machine. Point it at the
server and a model, then restart pasture (or re-run `pasture service install`
from that shell so the service keeps the settings):

```sh
export PASTURE_DICTATE_SERVER=/path/to/whisper-server
export PASTURE_DICTATE_MODEL=/path/to/ggml-small.en-q8_0.bin
```

- Models: [base.en q8](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en-q8_0.bin)
  (fine on a CPU) or [small.en q8](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q8_0.bin)
  (better, wants a GPU).
- macOS: `brew install whisper-cpp` (Metal on Apple Silicon).
- Windows: [whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases)
  have CPU, CUDA and Vulkan builds.
- Linux with Nix: `nix run github:fluxoz/pasture#pasture-dictation` bundles a
  CPU build and the base.en model.

In a terminal, tap the mic, talk, pause: the text is typed and Enter pressed.
The pause length and the Enter are per-device settings in the terminal's ⋮
menu. With a GPU the text lands about 50 ms after you stop; on a fast CPU,
about half a second.

## 9. Check it

```sh
pasture doctor
```

Every line is ✓, or says what to do next.

## Day to day

**Another device**: `pasture enroll`, scan, Create passkey, install the app.

**Remove a device**: open `~/.local/state/pasture/enrolled.json`
(`%LOCALAPPDATA%\pasture\enrolled.json` on Windows), delete that device's entry
(each has a `label` and a `created` date), then restart pasture. Its sessions
end, and it gets no more notifications.

**Update**: replace the binary with the new release and restart the service
(`systemctl --user restart pasture`, or `launchctl kickstart -k gui/$UID/dev.pasture`,
or log out and in on Windows). With Nix: `nix run --refresh github:fluxoz/pasture`.
Passkeys and settings are kept. The phone app offers "New version ready".

**Back up**: the state directory holds your passkeys and, with your own CA, the
CA. Copy it if you want to restore without enrolling again.

**Uninstall**: `pasture service uninstall`; `tailscale serve --https=443 off`
(with your own CA: `tailscale serve --tcp=443 off`); delete the state
directory; delete the app from the phone, and with your own CA remove its
profile ([how](tls.md#removing-the-ca-from-the-phone)).

## Where things live

| | Linux, macOS | Windows |
|---|---|---|
| State: passkeys, keys, push subscriptions, your CA, images from the phone (`uploads/`) | `~/.local/state/pasture` | `%LOCALAPPDATA%\pasture` |
| Service | `~/.config/systemd/user/pasture.service`, `~/Library/LaunchAgents/dev.pasture.plist` | Startup folder: `pasture.cmd` |
| Logs | `journalctl --user -u pasture`, `~/Library/Logs/pasture.log` | the window it runs in |

Something off? [troubleshooting.md](troubleshooting.md).
