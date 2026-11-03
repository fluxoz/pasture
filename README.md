# pasture

A passkey-gated terminal and session dashboard for your own machine, installed
on your phone's home screen as a web app.

Open it, unlock with Face ID (a passkey, no passwords), and you get a live
dashboard of what is running on the machine: tmux sessions and, if you use
[herdr](https://herdr.dev), every workspace and coding agent with its state
(working, needs you, done, idle) and its last lines of output. Tap one for a
full-screen terminal attached to it, with a key bar for Esc, Ctrl, arrows and
your multiplexer prefix. Optionally, a mic button transcribes speech on the
machine itself with whisper.cpp.

It is a NixOS module. Nothing about it talks to a third party at runtime: no
CDN, no push relay, no tunnel. Fonts and xterm.js are bundled at build time.

> Screenshot: _dashboard, terminal and sheets (placeholder)_

## Features

- **Passkey login** (WebAuthn): Face ID / Touch ID / a security key. Resident
  keys, user verification required, no attestation. One-time enrollment token.
- **Installable PWA** that holds still: no layout shift, no bounce, the
  terminal resizes with the on-screen keyboard instead of scrolling the page.
- **Terminal**: xterm.js over a WebSocket to a PTY on the host. Targets are a
  fixed set: a login shell, `tmux new-session -A -s <name>`, `herdr agent
  attach <pane>`, or the full herdr TUI. Closing the terminal ends only the
  attach client, never the tmux session or herdr pane. Rendering uses xterm's
  DOM renderer; WebGL can be switched on per device from the terminal menu.
- **Key bar**: Esc, Tab, sticky Ctrl/Alt (double-tap locks), arrows with
  auto-repeat, symbols, PgUp/PgDn, the multiplexer prefix, paste, hide keyboard.
  One-finger drag scrolls, pinch changes the font size.
- **Dashboards** (each optional):
  - tmux: list, attach, create in a project directory, rename, kill.
  - herdr: sessions, workspaces, tabs and panes from herdr's socket API with
    live events; agent status, unseen-done dots, previews; start an agent in a
    project, rename, mark seen, send quick keys (Esc, Enter, y/n, 1-3, Ctrl-C),
    send a prompt, close a pane or workspace.
  - alerts: an inbox fed by an ntfy topic on the same host.
- **Dictation** (optional): the mic sits at the right end of the key bar. Tap
  to start and again to stop, or hold it while you talk. Audio streams to the
  host as 16 kHz PCM; whisper.cpp's `whisper-server` (started on first use,
  kept loaded, stopped after `idleMinutes` unused) shows partial text while
  you talk and pastes the final text right after you stop. Pressing Enter
  afterwards is a per-device toggle in the terminal menu. With a GPU build of
  whisper.cpp a sentence takes well under 100 ms.
- **Themes**: any palette attrset (see [nix/themes/schema.md](nix/themes/schema.md))
  and any Nerd Font.

## Security model

Read this before you deploy it. pasture gives whoever unlocks it **a shell as
your user**. It is built for one owner on a private network.

- **Never expose it to the public internet.** Bind it to a VPN or LAN address
  (`listenAddresses`), open the port only on that interface
  (`firewall.interfaces`) and restrict client networks (`allowedCIDRs`).
- TLS is terminated by nginx; the certificate must be one your phone trusts
  (WebAuthn does not run on a page with a certificate error).
- Authentication happens in the gateway, not in nginx: even a local process
  that talks to the loopback port needs a valid session.
- Passkeys: exact origin and RP ID checks, user verification required,
  single-use 120 s challenges. Enrollment is off by default and needs a
  one-time token that is burned on use.
- Sessions: `__Host-` cookie (Secure, HttpOnly, SameSite=Strict), 30 min idle
  and 8 h absolute by default, kept in memory (a restart logs you out).
- Every POST needs the exact `Origin` and a custom header; the WebSocket
  checks `Origin` too. Strict CSP: scripts, fonts and connections are
  same-origin only.
- The terminal runs a fixed argv per target kind; names and IDs are validated
  and checked against live state. herdr calls go through a fixed allowlist;
  client JSON is never forwarded.

See [SECURITY.md](SECURITY.md) for the threat model and how to report issues.

## Requirements

- NixOS (x86_64-linux or aarch64-linux).
- A DNS name for the host that the phone can resolve, e.g. a Tailscale
  MagicDNS name. WebAuthn needs a domain name, not an IP. **Passkeys are bound
  to this name**: pick it once.
- A certificate for that name that the phone trusts: from your own CA (install
  and fully trust its root on the phone) or from ACME with a DNS challenge.
  For iOS the leaf needs a SAN, EKU serverAuth and at most 825 days validity.
- A secrets manager for the runtime secrets (sops-nix, agenix, or plain files).

## Quick start

Add the input:

```nix
inputs.pasture = {
  url = "github:<owner>/pasture";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

Then a host module like [examples/tailnet-host.nix](examples/tailnet-host.nix):

```nix
{ inputs, config, ... }:
{
  imports = [ inputs.pasture.nixosModules.default ];

  services.pasture = {
    enable = true;
    user = "alice";
    hostName = "myhost.example.ts.net";
    listenAddresses = [ "100.64.0.10" ];        # your `tailscale ip -4`
    nonlocalBind = true;
    nginx.after = [ "tailscaled.service" ];
    allowedCIDRs = [ "100.64.0.0/10" ];
    firewall.interfaces = [ config.services.tailscale.interfaceName ];

    tls.certFile = ./certs/myhost.pem;
    tls.keyFile = "/run/secrets/pasture-tls-key";      # owned by nginx
    secrets = {
      sessionKeyFile = "/run/secrets/pasture-session-key";    # owned by alice
      enrollTokenFile = "/run/secrets/pasture-enroll-token";  # owned by alice
      credentialsFile = "/run/secrets/pasture-credentials";   # owned by alice, "[]" at first
    };
    enrollment.enable = true;   # only until your passkey is enrolled
  };
}
```

Generate the secrets, for example:

```sh
head -c 64 /dev/urandom | base64 -w0          # session key
head -c 32 /dev/urandom | basenc --base64url  # enrollment token
echo '[]'                                     # credentials, before enrollment
```

[examples/acme-host.nix](examples/acme-host.nix) shows the same with a
Let's Encrypt certificate via `security.acme`.

## Enrollment

1. Set `enrollment.enable = true`, deploy.
2. On the host, as `user`, run `pasture-enroll`. It prints a QR code of
   `https://<hostName>/enroll#t=<token>`; the token is in the fragment, so the
   browser never sends it to the server.
3. Scan it with the phone's camera and open the link. The token is filled in;
   tap **Create passkey** and confirm with Face ID. You are logged in.
   (No camera handy: open `https://<hostName>/` and paste the token instead.)
4. Install the app: Share → **Add to Home Screen**, open it, tap **Unlock**.
   Home-screen apps have their own cookie jar, so they log in once on their
   own; the passkey itself is shared through iCloud Keychain.
5. The gateway logs the new credential as one JSON line
   (`journalctl --user -u pasture`) and keeps it in
   `~/.local/state/pasture/enrolled.json` while enrollment is on.
6. Copy that JSON object into your credentials secret (a JSON list), set
   `enrollment.enable = false`, rotate the enrollment token, deploy. From then
   on only the declared passkeys work and `/enroll` is a 404.

The token works once: after the first enrollment `pasture-enroll` says so. To
add another device later, rotate the token, redeploy and run it again.

## Options

All options live under `services.pasture`. Required: `user`, `hostName`,
`listenAddresses`, `tls.certFile` + `tls.keyFile` (or `tls.acmeHost`) and the
three `secrets.*` paths.

| Option | Default | Notes |
|---|---|---|
| `enable` | `false` | |
| `user` | required | Account whose shells are served; the gateway is its user unit. |
| `linger` | `true` | So the user unit runs without a login. |
| `hostName` | required | nginx server name, WebAuthn RP ID, origin. Must contain a dot. |
| `listenAddresses` | required | nginx listen IPs; wildcards need `allowWildcardListen`. |
| `allowWildcardListen` | `false` | |
| `listenPort` / `backendPort` | `443` / `8795` | The gateway binds 127.0.0.1 only. |
| `allowedCIDRs` | `[ ]` | `allow …; deny all;` in the vhost when set. |
| `firewall.interfaces` | `[ ]` | Opens `listenPort` on these interfaces only. |
| `nonlocalBind` | `false` | `ip_nonlocal_bind=1`, for addresses that appear after boot. |
| `nginx.after` | `[ ]` | e.g. `[ "tailscaled.service" ]`. |
| `tls.certFile` / `tls.keyFile` / `tls.acmeHost` | `null` | |
| `secrets.sessionKeyFile` / `enrollTokenFile` / `credentialsFile` | required | Runtime paths, readable by `user`. |
| `enrollment.enable` | `false` | |
| `session.idleMinutes` / `absoluteMinutes` | `30` / `480` | |
| `webauthn.rpName` / `webauthn.userName` | `"pasture"` / `"owner"` | Shown in the passkey sheet. |
| `appName` / `shortName` | `"pasture"` | Manifest and home-screen label. |
| `shell.enable` / `shell.command` | `true` / `null` | `null` = login shell with `-l`. |
| `tmux.enable` / `tmux.package` / `tmux.defaultSession` | `true` / `pkgs.tmux` / `null` | |
| `herdr.package` | `null` | `null` disables everything herdr. |
| `herdr.sessions` / `herdr.agentKinds` / `herdr.prefixKey` | `[ "default" ]` / `[ ]` / `"ctrl+b"` | |
| `projectRoots` | `[ "~" ]` | Allowed working directories for new sessions/agents. |
| `alerts.ntfy.url` / `alerts.ntfy.topic` | `null` / `"agents"` | |
| `dictation.enable` / `package` / `model` | `false` / `pkgs.whisper-cpp` / `null` | `model` is required when enabled. |
| `dictation.language` / `threads` / `maxSeconds` / `ffmpegPackage` | `"en"` / `4` / `60` / `pkgs.ffmpeg-headless` | ffmpeg only decodes uploads from browsers without AudioWorklet. |
| `dictation.idleMinutes` / `prompt` / `extraArgs` | `30` / `null` / `[ ]` | Unload after idle (0 = never); whisper's initial prompt; extra `whisper-server` flags. |
| `theme.palette` | bundled "pasture dark" | See [nix/themes/schema.md](nix/themes/schema.md). |
| `theme.fonts` | `null` | `{ family; regular; bold; }`; `null` = JetBrainsMono Nerd Font Mono. |
| `webPackage` | `mkWeb` of the above | Replace the whole frontend. |
| `extraEnvironment` | `{ }` | Extra gateway (and shell) environment. |

## iOS notes

- Safari and the installed app do not share cookies: after enrolling in
  Safari (the QR code opens there), the installed app needs one Unlock.
- With a private CA: install its root as a profile and turn it on under
  Settings → General → About → Certificate Trust Settings.
- The iOS keyboard's own dictation may send audio to Apple. The app's mic
  button records locally and transcribes on your host.
- The app badge shows blocked + finished agents where iOS allows it.
- Lock-screen notifications are out of scope (Web Push on iOS goes through
  Apple's servers); the ntfy app covers that.

## herdr and ntfy

With `herdr.package` set, the gateway talks to herdr's JSON socket API
(`~/.config/herdr/herdr.sock` and named sessions) as your user. It subscribes
to events and re-reads the session snapshot on each one. "Mark seen" uses
herdr's focus, which is shared server state: it also moves the focus of a
desktop TUI attached to the same session.

With `alerts.ntfy.url` set, the inbox shows the last hour of messages on the
topic. Titles of the form `"<agent> - <project> (<host>)"` are matched to the
agent pane whose working directory is `<project>`.

## Troubleshooting

- **Passkey prompt never appears / "operation is insecure"**: the page has a
  certificate problem or the host name is an IP. WebAuthn needs a trusted
  HTTPS origin with a domain name.
- **nginx fails at boot with "cannot assign requested address"**: the listen
  address is not up yet (Tailscale). Set `nonlocalBind = true` and
  `nginx.after = [ "tailscaled.service" ]`.
- **Logged out after a deploy**: sessions live in memory; restarting the
  gateway logs out. Unlock again.
- **Gateway logs**: `journalctl --user -u pasture -f`; health:
  `curl -s http://127.0.0.1:8795/healthz` (loopback only; shows certificate
  days left).

## Development

```sh
nix develop                     # Python with aiohttp + webauthn
cd gateway && python -m unittest discover -s tests -t . -v
```

Build the web bundle by hand (any theme JSON, any font file, an unpacked
xterm vendor directory as produced by `nix/vendor.nix`):

```sh
python3 web/build.py --src web --theme theme.json --vendor <xterm-dir> \
  --font-regular Font-Regular.ttf --font-bold Font-Bold.ttf --out /tmp/pasture-web
```

Run a gateway against it on plain HTTP for local work (dev only; the origin
override disables Secure cookies):

```sh
PASTURE_HOST=localhost PASTURE_ORIGIN=http://localhost:8795 \
PASTURE_STATIC=/tmp/pasture-web PASTURE_STATE_DIR=/tmp/pasture-state \
PASTURE_SESSION_KEY_FILE=./key PASTURE_ENROLL_TOKEN_FILE=./token \
PASTURE_CREDENTIALS_FILE=./creds PASTURE_ENROLL=1 \
PASTURE_TMUX=$(command -v tmux) python -m pasture
```

Layout: `gateway/` (Python: auth, sessions, providers, PTY bridge, dictation),
`web/` (vanilla ES modules, one stylesheet, the bundle builder), `nix/`
(packages, theme, module), `examples/`.

Future work: non-NixOS packaging (container, Homebrew).

## License

MIT. Bundled at build time: xterm.js and addons (MIT), your chosen fonts
(JetBrains Mono and Nerd Fonts are OFL-1.1 / MIT).
