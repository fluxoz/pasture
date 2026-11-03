# A NixOS host on a Tailscale tailnet, certificate from your own CA (or see
# acme-host.nix). Import from a flake that has `inputs.pasture`.
{
  inputs,
  config,
  pkgs,
  ...
}:
{
  imports = [ inputs.pasture.nixosModules.default ];

  services.pasture = {
    enable = true;
    user = "alice";
    hostName = "myhost.example.ts.net";
    listenAddresses = [ "100.64.0.10" ]; # example; use your `tailscale ip -4`
    nonlocalBind = true; # nginx may start before tailscaled has the IP
    nginx.after = [ "tailscaled.service" ];
    allowedCIDRs = [ "100.64.0.0/10" ];
    firewall.interfaces = [ config.services.tailscale.interfaceName ];

    tls.certFile = ./certs/myhost.pem;
    tls.keyFile = "/run/secrets/pasture-tls-key"; # readable by nginx only
    secrets = {
      sessionKeyFile = "/run/secrets/pasture-session-key";
      enrollTokenFile = "/run/secrets/pasture-enroll-token";
      credentialsFile = "/run/secrets/pasture-credentials"; # JSON list, "[]" before enrolling
    };
    enrollment.enable = true; # turn off after enrolling your passkey

    tmux.defaultSession = "main";
    # Optional integrations:
    # herdr.package = pkgs.herdr;                     # if you use herdr
    # herdr.agentKinds = [ "claude" "codex" ];
    # alerts.ntfy.url = "http://127.0.0.1:2586";
    # dictation = {
    #   enable = true;
    #   model = pkgs.fetchurl {
    #     url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin";
    #     hash = "sha256-…";
    #   };
    # };
    # theme.palette = import ./my-palette.nix;
  };
}
