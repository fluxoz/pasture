# Several machines, one app

Run pasture on every machine with agents, and keep one app on the phone: one
passkey, one home-screen icon, one set of notifications. The phone uses one of
them, the **hub**; the hub reaches the others over your tailnet.

The hub is simply the machine the phone enrolled on (usually the first you set
up). Pick one that is always on: when it is off, the phone cannot reach the
others either. The other machines need no passkey and nothing on the phone;
they trust the hub through a link token they issued.

```text
phone ──passkey──▶ hub (pasture) ──link token──▶ box  (pasture)
                                  ──link token──▶ mini (pasture)
```

On the hub's dashboard, a row of machine chips switches between them. Agents,
tmux sessions, shells, previews, new agents, image uploads and terminals all
work as on the hub; dictation runs on the hub and types into the other
machine's terminal. Every machine's alerts reach the phone through the hub,
labelled with the machine (`box: api needs you`), and tapping one opens that
agent on that machine.

## Add a machine

1. Set up the hub as usual ([docs/setup.md](setup.md)): enroll the phone, turn
   on push notifications.
2. On the new machine, install pasture and run it as a service (steps 1, 2 and
   5 of [setup](setup.md)); skip enrolling. If your tailnet has no HTTPS
   certificates, pasture makes its own CA there on its own; nothing goes on the
   phone for it.
3. On the phone, tap the machine name at the top left → **Add a machine**. It
   shows a command with a one-time code (good for 15 minutes):

   ```sh
   pasture join desktop K7QF-3MZX-9RTD-PQ2W-XY7Z
   ```

   Run it on the new machine (**Copy** puts it on the clipboard; from an
   iPhone, a Mac pastes it directly). The new machine checks it is talking to
   your hub (the code carries the hub's certificate fingerprint when the hub
   uses its own), gives the hub a link token, and the hub checks it can reach
   the machine back. The phone switches to it when it is in.
4. Hold the machine in that sheet and turn on its agents' alerts (Claude Code,
   Grok Build): pasture adds its hooks to their settings there. Installing the
   agents themselves is up to you; the phone gives you a terminal there.

Without the phone: `pasture link` on the machine prints a
`pasture machines add <code>` command to run on the hub.

## Updates

⋮ → **Updates** on the phone lists every machine with its version. Release
binaries update themselves (or on **Update now**), each once no terminal is
open on it; set **Auto**, **Notify** or **Off** per machine. Machines on a
pasture older than 0.5 need one update by hand first.

## Manage them

| On | Command | |
|---|---|---|
| the hub | `pasture machines list` | The machines it reaches. |
| the phone | tap the name → hold a machine → **Remove** | Stop showing it; it revokes the hub's link. |
| the hub | `pasture machines remove box` | The same, from a terminal. |
| the hub | `pasture machines add CODE --name build` | Show it under another name. |
| the machine | `pasture link --list` | Hubs that may reach it. |
| the machine | `pasture link --revoke hub` | Cut the hub off at once, open terminals included. |
| the machine | `pasture link --name hub2` | A code for a second hub (each has its own token). |

A new `pasture link` with the same `--name` replaces that hub's token; add the
new code on the hub again.

## HTTPS between machines

The hub talks to each machine at the same HTTPS address the phone would use,
and verifies it:

- **Tailscale's certificate**: publicly trusted; nothing to do.
- **Your own CA** (`pasture tls init`): the link code carries the machine's
  CA certificate, and the hub trusts only that CA for that machine.
- **nginx with a certificate of your own** (NixOS module): set
  `services.pasture.tls.caFile` to the CA that signed it (or pass `--ca FILE`)
  and the code carries the CA. Without it, `pasture link` pins the certificate
  itself; after renewing it, link again.

The phone never talks to the other machines, so their certificates do not
need to be installed on it.

## What a link allows

A link token is a key to that machine's pasture, like the phone's passkey: the
hub can do whatever the phone can there, which includes opening a shell. The
machine stores only its SHA-256 hash (`<state>/links.json`); the hub stores
the token in `<state>/machines.json` (0600). It cannot enroll devices, sign in
or change push subscriptions, and it is not limited by the phone's session
timeout, so revoke it when you retire the hub. The link code is a credential
until you add it: don't paste it into issues, chats or commits.

## Notes

- A machine that is off shows a grey chip and what it last reported; the hub
  reconnects on its own.
- Two machines can each be the other's hub (the phone uses either): their
  states are not nested, and forwarded alerts are never forwarded again.
- If the phone also has notifications turned on in another machine's own app,
  it gets that machine's alerts twice; turn them off there
  (⋮ → Push notifications).
