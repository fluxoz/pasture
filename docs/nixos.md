# NixOS and home-manager

## NixOS

Add the input:

```nix
inputs.pasture = {
  url = "github:fluxoz/pasture";
  inputs.nixpkgs.follows = "nixpkgs";
};
```

### Minimal

```nix
{ inputs, ... }:
{
  imports = [ inputs.pasture.nixosModules.default ];
  services.tailscale.enable = true;
  services.pasture = {
    enable = true;
    user = "alice";                            # whose shells and agents
    hostName = "myhost.your-tailnet.ts.net";   # this machine's MagicDNS name
  };
}
```

This serves pasture with `tailscale serve` and Tailscale's certificate (turn
on HTTPS certificates in the admin console), runs the gateway as a systemd
user unit for `alice` (lingering, so it runs without a login) and keeps its
secrets in `~alice/.local/state/pasture`. After deploying, as `alice`:

```sh
pasture-enroll     # QR code for the phone
```

then do the phone steps from [Getting started, step 4](setup.md#4-start-pasture-and-enroll-your-phone).

The module also gives `alice` a `pasture` command pointed at this service
(`pasture doctor`, and `pasture link` / `pasture machines` for
[several machines](machines.md)). With the nginx frontend and a private CA,
set `tls.caFile` to that CA's certificate so link codes carry it.

To keep the host name out of Certificate Transparency logs, use your own CA
with the nginx frontend: [tls.md](tls.md#your-own-ca-on-nixos).

### Agents, notifications and dictation

```nix
services.pasture = {
  # ...
  herdr = {
    package = inputs.llm-agents.packages.${pkgs.stdenv.hostPlatform.system}.herdr;  # github:numtide/llm-agents.nix
    agentKinds = [ "claude" "codex" ];
  };
  tmux.defaultSession = "main";
  projectRoots = [ "~/code" ];

  notify.claudeCode = true;   # Claude Code hooks (managed settings) report to pasture

  dictation = {
    enable = true;
    package = pkgs.whisper-cpp-vulkan;   # or a CUDA build; pkgs.whisper-cpp for CPU
    model = pkgs.fetchurl {
      url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en-q8_0.bin";
      hash = "sha256-Z6F59gjqYRS9P9uQYOditYij+zvQDEOHlxvk0XeVgGc=";
    };
  };
};
```

- herdr agents raise "needs you" and "finished" alerts on their own.
- `notify.claudeCode` adds Claude Code hooks for every session on the machine
  (in herdr or not), and lets agents read the images sent from the phone
  (`~/.local/state/pasture/uploads`) without asking. For other agents, call
  `${config.services.pasture.notify.package}/bin/pasture-notify --hook <agent> stop`
  from their hooks.
- Dictation keeps the model loaded on the GPU from boot
  (`dictation.idleMinutes = 0`), so the first word is as fast as the rest.

[examples/agents-host.nix](../examples/agents-host.nix) is a complete host.

### Passkeys from your secrets manager

By default the gateway keeps enrolled passkeys in its state directory and
enrollment stays available through one-time codes. To pin the passkeys in
your configuration instead:

1. Enroll as usual. The gateway logs each new passkey as one JSON line:
   `journalctl --user -u pasture | grep -A1 enrolled`.
2. Put those objects, as a JSON list, in a secret readable by the user, e.g.
   sops-nix `pasture/credentials`.
3. Set `secrets.credentialsFile` to its path. Enrollment then turns off by
   default (`enrollment.enable` follows `credentialsFile == null`), `/enroll`
   is a 404, and only the listed passkeys work.

`secrets.sessionKeyFile` and `secrets.enrollTokenFile` can come from the
secrets manager too.

All options: [README → NixOS options](../README.md#nixos-options).

## home-manager

For Linux or macOS with home-manager (NixOS or not):

```nix
{ inputs, ... }:
{
  imports = [ inputs.pasture.homeManagerModules.default ];
  services.pasture = {
    enable = true;
    name = "devbox";        # the home-screen label
    hooks.claude = true;    # Claude Code sessions alert the phone (merged on each switch; yours kept)
    # hooks.grok = true;
    # dictation = true;     # whisper.cpp (CPU) and the base.en model
    # environment.PASTURE_DICTATE_MODEL = "/path/to/model.bin";
  };
}
```

It runs `pasture serve` as a systemd user service (Linux; add
`loginctl enable-linger $USER`) or a launchd agent (macOS, logs in
`~/Library/Logs/pasture.log`). The `pasture` command is installed too:
`pasture enroll`, `pasture join`, `pasture tls init`, `pasture doctor`. To add
the machine to your hub, see [several machines](machines.md).
