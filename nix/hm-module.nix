# services.pasture for home-manager (Linux): run `pasture serve` as a systemd
# user service on a machine that is on a tailnet, NixOS or not. It finds the
# node's MagicDNS name and sets up `tailscale serve` itself; `pasture enroll`
# shows the QR code for a phone.
self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib) mkOption mkEnableOption types mkIf;
  cfg = config.services.pasture;
  packages = self.packages.${pkgs.stdenv.hostPlatform.system};
  args = lib.escapeShellArgs (
    [
      "--port"
      (toString cfg.port)
      "--https-port"
      (toString cfg.httpsPort)
      "--name"
      cfg.name
    ]
    ++ lib.optionals (cfg.host != null) [
      "--host"
      cfg.host
    ]
    ++ lib.optional (!cfg.tailscaleServe) "--no-tailscale-serve"
  );
in
{
  options.services.pasture = {
    enable = mkEnableOption "pasture, a passkey-gated PWA terminal for your phone, on your tailnet";
    package = mkOption {
      type = types.package;
      default = if cfg.dictation then packages.pasture-dictation else packages.pasture;
      defaultText = lib.literalExpression "pasture.packages.\${system}.pasture (or pasture-dictation)";
    };
    dictation = mkOption {
      type = types.bool;
      default = false;
      description = "Bundle whisper.cpp (CPU) and the base.en model for the mic button. Use a GPU build for speed.";
    };
    name = mkOption {
      type = types.str;
      default = "pasture";
      description = "App name on the phone's home screen.";
    };
    host = mkOption {
      type = types.nullOr types.str;
      default = null;
      description = "DNS name the phone uses; null = this node's MagicDNS name.";
    };
    port = mkOption {
      type = types.port;
      default = 8795;
      description = "Loopback port of the gateway.";
    };
    httpsPort = mkOption {
      type = types.port;
      default = 443;
      description = "Tailnet HTTPS port (tailscale serve).";
    };
    tailscaleServe = mkOption {
      type = types.bool;
      default = true;
      description = "Configure `tailscale serve` (needs `sudo tailscale set --operator=$USER` once).";
    };
    environment = mkOption {
      type = types.attrsOf types.str;
      default = { };
      example = {
        PASTURE_AGENT_KINDS = "claude,codex";
      };
      description = "Extra gateway environment (PASTURE_* settings, see the README).";
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.hostPlatform.isLinux;
        message = "services.pasture (home-manager) supports Linux only for now.";
      }
    ];
    home.packages = [ cfg.package ];
    systemd.user.services.pasture = {
      Unit = {
        Description = "pasture: passkey PWA terminal on the tailnet";
        After = [ "network-online.target" ];
      };
      Service = {
        ExecStart = "${lib.getExe cfg.package} serve ${args}";
        # Shells started from here should find the user's tools.
        Environment = [
          "PATH=${config.home.profileDirectory}/bin:/run/current-system/sw/bin:/usr/local/bin:/usr/bin:/bin"
        ] ++ lib.mapAttrsToList (k: v: "${k}=${v}") cfg.environment;
        Restart = "on-failure";
        RestartSec = 5;
        KillMode = "control-group";
        TimeoutStopSec = 10;
      };
      Install.WantedBy = [ "default.target" ];
    };
  };
}
