# Security

pasture hands a shell on your machine to whoever unlocks it. Treat it like
SSH: one owner, a private network, and never the public internet.

## Threat model

**Protected against**

- Anyone who can reach the port but has no enrolled passkey: they get the
  static app shell and the login button, nothing else. All data and every
  action require a session; sessions require a passkey assertion with user
  verification, for this exact origin and RP ID.
- Cross-site requests and cross-site WebSocket hijacking: every POST checks
  `Origin` and a custom header (which forces a CORS preflight that is never
  granted); the WebSocket upgrade checks `Origin`. Cookies are `__Host-`,
  Secure, HttpOnly, SameSite=Strict.
- Replay: login and registration challenges are random, single-use and expire
  after 120 seconds. Authenticator sign counters are checked when non-zero.
- Enrollment abuse: enrollment is off by default; when on, it needs a token
  compared in constant time, which is burned (persistently) on first use.
  `pasture-enroll` shows it as a QR code (in the URL fragment, never sent to
  the server or logged); anyone who sees that code before you scan it could
  enroll first, and the gateway logs every enrollment.
- Command injection: terminals run a fixed argv per target kind; names and IDs
  are validated by pattern and against live state. The herdr integration
  calls a fixed set of methods with validated parameters and never forwards
  client JSON.
- Content injection: a strict Content-Security-Policy (scripts, fonts, images
  and connections from the same origin only). Styles allow `'unsafe-inline'`
  only because xterm.js creates `<style>` elements at runtime.
- Brute force: auth endpoints are rate-limited per client (10/min) with a
  global 5-minute lockout after 20 failures.

**Not protected against**

- A compromised or stolen *unlocked* device, or a compromised passkey
  provider (e.g. your iCloud account): a session is a shell.
- Anyone who can already run code as your user on the host.
- Exposure beyond a private network. Nothing in pasture is designed to face
  the internet; the module refuses wildcard listen addresses unless you opt in.
- Other users of a shared VPN reaching the login page. Restrict the port with
  your VPN's ACLs (for Tailscale: only your own devices to `host:443`).

**Operational notes**

- The TLS key belongs to nginx; the gateway (which spawns shells) never needs
  to read it.
- If you sign the certificate with your own CA, that root is trusted by your
  phone for every domain unless it is name-constrained. Keep its key offline
  or encrypted, or use a name-constrained intermediate.
- A gateway restart logs everyone out (sessions are in memory).
- Audio for dictation exists only in a private temporary directory for the
  duration of the request and is never logged.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting ("Report a vulnerability"
under the repository's Security tab). Do not open a public issue for security
problems.
