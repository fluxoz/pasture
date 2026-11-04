# Troubleshooting

Start with `pasture doctor`: it checks Tailscale, HTTPS, the gateway, enrolled
devices, notifications, dictation and hooks, and prints the fix for anything
missing.

## Reaching it

**The phone says the page can't be opened.** The Tailscale app on the phone
must be connected to the same tailnet. Check the name with `pasture doctor`
(MagicDNS must be on).

**"tailscale serve needs permission"** (Linux): run
`sudo tailscale set --operator=$USER` once. Windows: run the command pasture
prints once in an administrator PowerShell.

**"HTTPS certificates look off"**: turn them on at the
[DNS page](https://login.tailscale.com/admin/dns), or use your own CA
([tls.md](tls.md#your-own-ca)).

**Port 8795 is taken**: `pasture serve --port 8796` (and
`pasture service install -- --port 8796`).

## Passkeys

**The passkey prompt never appears, or Safari shows a certificate warning.**
The certificate is not trusted. With your own CA on iPhone, the profile must be
installed *and* full trust turned on (Settings → General → About → Certificate
Trust Settings). With Tailscale's certificate, the first visit after turning
HTTPS on can take a few seconds while it is issued.

**"Enrollment is closed; that code was used already."** Codes work once:
`pasture enroll` makes a new one.

**The installed app asks to Unlock although I just enrolled.** Home Screen apps
keep their own cookies; tap Unlock once. The passkey is the same.

**I renamed the machine.** Passkeys are bound to the old name: enroll again
(`pasture enroll`), and with your own CA run `pasture tls init` afresh after
deleting `~/.local/state/pasture/tls`.

## Notifications

**No "Push notifications" switch, or it says to add the app to the Home
Screen.** On iPhone, push works only in the installed app (iOS 16.4+), not in
Safari.

**"Send a test" works but agents never notify.** herdr agents notify on their
own. Claude Code needs `pasture hooks claude --install` (then start a new
session). Notifications are skipped while the app is open in front: the alert
shows inside the app instead.

**Notifications stopped.** iOS drops a subscription when the app is deleted or
notifications are turned off in Settings. Turn Push notifications off and on
again in the app.

## Dictation

**The mic does nothing or "Microphone permission denied".** Allow the
microphone for the app (iOS: Settings → the app, or Settings → Safari →
Microphone). In the installed app iOS asks again after a restart.

**The first words are slow.** The model loads when pasture starts; give it a
few seconds after a restart. A GPU build of whisper.cpp makes the rest fast.

**It sends too early or too late.** In a terminal's ⋮ menu, change "Stop when
I pause" (0.6 to 2.5 s, or off) and whether it presses Enter.

## Logs

- `journalctl --user -u pasture -f` (Linux service), `~/Library/Logs/pasture.log`
  (macOS service), or the terminal running `pasture`.
- Each recording logs its timings, never audio or text.
- Sessions live in memory: restarting pasture logs every device out; Unlock again.
