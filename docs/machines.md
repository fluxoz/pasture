# Several machines, one app

Run pasture on every machine with agents, and keep one app on the phone: one
passkey, one home-screen icon, one set of notifications. The phone uses one of
them, the **hub**; the hub reaches the others over your tailnet.

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

## Set it up

1. Set up the hub as usual ([docs/setup.md](setup.md)): pick the machine that
   is on most, enroll the phone, turn on push notifications.
2. On each other machine, install and run pasture the same way (as a service),
   but skip enrolling and notifications there. Then make a link code:

   ```sh
   pasture link
   ```

   It prints a command with a long `pasture-link:…` code.
3. On the hub, run that command:

   ```sh
   pasture machines add pasture-link:eyJ2Ijox…
   ```

   It checks the machine answers, then the machine shows up on the phone's
   dashboard within a few seconds.

Claude Code hooks (`pasture hooks claude --install`) and herdr alerts on the
other machine go to its own pasture, which hands them to the hub.

## Manage them

| On | Command | |
|---|---|---|
| the hub | `pasture machines list` | The machines it reaches. |
| the hub | `pasture machines remove box` | Stop showing a machine (its link stays valid there until revoked). |
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
