# pasture

**Your coding agents, on your phone.** A passkey-gated terminal and agent
dashboard for your own machine, served only on your Tailscale network and
installed on your phone's home screen.

![The dashboard, live dictation and an agent finishing a task](docs/screenshots.png)

▶ [35-second demo video](docs/demo.mp4)

- **See every agent at a glance**: which [herdr](https://herdr.dev) agent is
  working, done or needs you, with its last lines of output, plus your tmux
  sessions.
- **Jump in**: a full-screen terminal attached to the agent, tmux session or a
  shell, with a key bar made for thumbs (Esc, Tab, sticky Ctrl/Alt, arrows,
  Enter, paste).
- **Just say it**: tap the mic and talk. whisper.cpp transcribes on your own
  machine while you speak; pause, and it types the text and presses Enter.
- **Know when they finish**: push notifications when an agent needs you or is
  done, even with the app closed. Tap one to open that agent.
- **Yours**: it runs as your user on your machine (Linux, macOS or Windows).
  Passkey login (Face ID), one-time QR enrollment, reachable only on your
  tailnet. No accounts, no telemetry, no CDN.

## Quick start

**[The setup guide](docs/setup.md)** walks through everything: Tailscale on
both ends, HTTPS with Tailscale's certificate or your own CA installed on the
phone, enrolling, notifications, dictation, and running it as a service.

### Linux, macOS, Windows

1. Install [Tailscale](https://tailscale.com/download) on the machine and the
   phone; turn on **MagicDNS** in the admin console.
2. Download `pasture` for your platform from
   [Releases](https://github.com/fluxoz/pasture/releases) (or, with Nix,
   `nix run github:fluxoz/pasture`).
3. Pick HTTPS: turn on **HTTPS certificates** in the Tailscale admin console,
   or keep your machine's name private with your own CA:
   `pasture tls init`, then `pasture tls phone` and scan the QR code to trust
   it on the phone ([how](docs/setup.md#b-your-own-ca-nothing-public)).
4. Run `pasture`. It finds your machine's `*.ts.net` name, serves itself on it
   with `tailscale serve`, and prints a QR code.
5. Scan the QR code with your phone's camera, open the link, tap **Create
   passkey**. Then Share → **Add to Home Screen**, open the app, tap **Unlock**.

On Linux, `tailscale serve` needs permission once:
`sudo tailscale set --operator=$USER`. `pasture enroll` prints a new one-time
QR code for another device.

### home-manager (Linux)

```nix
# flake inputs
inputs.pasture.url = "github:fluxoz/pasture";

# your home configuration
{ inputs, ... }:
{
  imports = [ inputs.pasture.homeManagerModules.default ];
  services.pasture = {
    enable = true;
    # dictation = true;   # bundle whisper.cpp (CPU) and the base.en model
  };
}
```

It runs `pasture serve` as a systemd user service. Run
`loginctl enable-linger $USER` so it keeps running while you are logged out,
and `pasture enroll` for the QR code.

### NixOS

```nix
# flake inputs
inputs.pasture = {
  url = "github:fluxoz/pasture";
  inputs.nixpkgs.follows = "nixpkgs";
};

# a host module
{ inputs, ... }:
{
  imports = [ inputs.pasture.nixosModules.default ];
  services.tailscale.enable = true;
  services.pasture = {
    enable = true;
    user = "alice";
    hostName = "myhost.your-tailnet.ts.net"; # this machine's MagicDNS name
  };
}
```

Deploy, then run `pasture-enroll` as `alice` for the QR code.
[examples/agents-host.nix](examples/agents-host.nix) adds herdr and GPU
dictation; [examples/tailnet-host.nix](examples/tailnet-host.nix) serves with
nginx and your own certificate instead of `tailscale serve`, so the host name
never appears in Certificate Transparency logs.

## On the phone

- **Enroll**: scan the QR code, open the link in Safari, tap Create passkey.
  The code works once.
- **Install**: Share → Add to Home Screen. The installed app keeps its own
  cookies, so it asks you to Unlock once; the passkey itself is shared.
- **Notifications**: ⋮ → Push notifications (iOS 16.4+ in the installed app,
  or Android Chrome). Choose "needs you" and/or "finishes", then Send a test.
- **Dictation**: the round mic at the right of the key bar. Tap to start, or
  hold while you talk. In a terminal's ⋮ menu: how long a pause ends the
  recording (0.6 to 2.5 s, or off) and whether it then presses Enter.

Tested on iPhone. Android should work (Chrome has passkeys, Web Push and
AudioWorklet) but is untested.

## Works with

- **[herdr](https://herdr.dev)** for the agent dashboard: any agent herdr
  tracks (Claude Code, Codex, ...). Its status changes drive the badges and
  push notifications. Without herdr you get tmux sessions and shells.
- **tmux**: list, attach, create in a project directory, rename, kill.
- **Plain shells**: your login shell.
- **ntfy** (optional): an inbox fed by a topic on the same machine, also
  forwarded as push notifications.

## Security and privacy

pasture gives whoever unlocks it **a shell as your user**. It is built for one
owner on a private network. Read [SECURITY.md](SECURITY.md).

- **Tailnet only.** `tailscale serve` (never `funnel`) or nginx bound to your
  tailnet address. If you share the tailnet, limit the port to your own
  devices with Tailscale ACLs.
- **Passkeys**: exact origin and RP ID checks, user verification required,
  single-use 120 s challenges. Enrollment codes are one-time and travel in the
  URL fragment, which browsers never send to a server.
- **Sessions**: `__Host-` cookie (Secure, HttpOnly, SameSite=Strict), 30 min
  idle and 8 h absolute, in memory. Every POST and WebSocket checks `Origin`;
  strict CSP; terminals run a fixed command per target kind.
- **What leaves the machine**: with Tailscale's certificate, the machine's
  `ts.net` name appears in public Certificate Transparency logs. Your own CA
  (`pasture tls init`, or the nginx frontend on NixOS) avoids that; the CA is
  name-constrained to that one name, so trusting it on the phone risks
  nothing else. Push notifications go through the
  phone's push service (Apple's for an iPhone), encrypted end to end, so it
  sees only size and timing. Nothing else: dictation audio stays on the
  machine, and fonts and xterm.js are bundled.

## Requirements

- Linux (x86_64, arm64), macOS (Apple Silicon, Intel) or Windows (x86_64);
  NixOS and home-manager modules for Nix users. On Windows the terminals are
  PowerShell and there is no tmux or herdr dashboard.
- Tailscale with MagicDNS, plus HTTPS certificates or your own CA.
- A phone browser with passkeys. Push needs iOS 16.4+ with the app installed.
- Fast dictation wants a GPU build of whisper.cpp (Vulkan or CUDA): the text
  lands about 50 ms after you pause. On a fast CPU it is about half a second.

## Configuration

### NixOS options

All under `services.pasture`; only `enable`, `user` and `hostName` are required.

| Option | Default | Notes |
|---|---|---|
| `user` | required | Account whose shells are served; the gateway is its user unit. |
| `hostName` | required | The name the phone uses: WebAuthn RP ID and origin. Passkeys are bound to it. |
| `frontend` | `"tailscale"` | `"tailscale"` (`tailscale serve`, needs `services.tailscale.enable`) or `"nginx"`. |
| `listenAddresses` | `[ ]` | nginx: listen IPs; wildcards need `allowWildcardListen`. |
| `listenPort` / `backendPort` | `443` / `8795` | The gateway binds 127.0.0.1 only. |
| `allowedCIDRs` / `firewall.interfaces` | `[ ]` | nginx: allowed client networks; interfaces that get `listenPort`. |
| `nonlocalBind` / `nginx.after` | `false` / `[ ]` | nginx: bind an address that appears after boot (start after `tailscaled.service`). |
| `tls.certFile` / `tls.keyFile` / `tls.acmeHost` | `null` | nginx: your certificate. |
| `secrets.sessionKeyFile` / `enrollTokenFile` / `credentialsFile` | `null` | Optional; without them the gateway keeps its own in its state dir. |
| `enrollment.enable` | `credentialsFile == null` | With a credentials secret, turn it off to allow only those passkeys. |
| `push.enable` / `push.subject` | `true` / `null` | Web Push; nothing is sent until a device turns it on. |
| `session.idleMinutes` / `absoluteMinutes` | `30` / `480` | |
| `appName` / `shortName` | `"pasture"` | Home-screen label. |
| `shell.enable` / `shell.command` | `true` / `null` | `null` = login shell. |
| `tmux.enable` / `tmux.defaultSession` | `true` / `null` | |
| `herdr.package` / `sessions` / `agentKinds` / `prefixKey` | `null` / `[ "default" ]` / `[ ]` / `"ctrl+b"` | `null` disables herdr. |
| `projectRoots` | `[ "~" ]` | Where new sessions and agents may start. |
| `alerts.ntfy.url` / `topic` | `null` / `"agents"` | |
| `dictation.enable` / `package` / `model` | `false` / `pkgs.whisper-cpp` / `null` | Use `whisper-cpp-vulkan` (or a CUDA build) for speed. |
| `dictation.idleMinutes` / `prompt` / `extraArgs` | `0` / `null` / `[ ]` | 0 keeps the model loaded from boot; whisper's initial prompt; extra `whisper-server` flags. |
| `dictation.language` / `threads` / `maxSeconds` | `"en"` / `4` / `60` | |
| `theme.palette` / `theme.fonts` | "pasture dark" / JetBrains Mono | Any palette ([schema](nix/themes/schema.md)) and Nerd Font. |
| `extraEnvironment` | `{ }` | Extra gateway (and shell) environment. |

### The `pasture` command

`pasture serve` (the default) takes `--host` (default: the MagicDNS name),
`--port`, `--https-port`, `--name`, `--state`, `--no-tailscale-serve` and
`--tailscale-cert` (ignore your own CA). `pasture enroll [--new]` prints the
QR code. `pasture tls init [--renew]` makes your own CA and certificate;
`pasture tls phone` serves the CA for the phone. tmux, herdr and `whisper-server`
are used when they are on `PATH`; `PASTURE_*` environment variables (see
[gateway/pasture/config.py](gateway/pasture/config.py)) set the rest.

## Troubleshooting

- **"tailscale serve needs permission"**: run
  `sudo tailscale set --operator=$USER` once.
- **The passkey prompt never appears**: the page needs a trusted HTTPS origin
  with a domain name. Check that HTTPS certificates are on for the tailnet,
  or, with your own CA, that full trust is on for it (iOS: Settings → General
  → About → Certificate Trust Settings).
- **Logged out after an update**: sessions live in memory; unlock again.
- **Logs**: `journalctl --user -u pasture -f`. Each recording logs its timings
  (never audio or text).

## Development

```sh
nix develop
cd gateway && python -m unittest discover -s tests -t . -v
nix build .#gateway .#web .#pasture   # the gateway's tests run here too
```

Layout: `gateway/` (Python: auth, sessions, providers, PTY bridge, dictation,
push, the `pasture` command), `web/` (vanilla ES modules, one stylesheet, the
bundle builder), `nix/` (packages, theme, NixOS and home-manager modules),
`examples/`.

## License and credits

MIT. Bundled at build time: xterm.js and addons (MIT), JetBrains Mono and the
Nerd Fonts symbols (OFL-1.1 / MIT). The demo video's voice was synthesized
with [Piper](https://github.com/OHF-Voice/piper1-gpl) using the
`en_US-libritts_r` voice, trained on LibriTTS-R (CC BY 4.0).
