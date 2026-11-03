# services.pasture: the NixOS module.
#
# nginx terminates TLS on the listen addresses you give it and proxies to the
# gateway on 127.0.0.1. The gateway runs as a systemd *user* unit for
# `services.pasture.user`, so terminals are that user's shells and it can reach
# per-user sockets (herdr, tmux). Authentication (passkeys) happens in the
# gateway, not in nginx. Nothing here has a host-specific default: user, host
# name, addresses, certificate and secrets must all be set.
self:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib)
    mkOption
    mkEnableOption
    mkIf
    mkDefault
    types
    literalExpression
    optional
    optionalString
    concatMapStrings
    ;
  cfg = config.services.pasture;

  gateway = pkgs.callPackage ./gateway.nix { };
  herdrOn = cfg.herdr.package != null;
  herdrMethods = pkgs.callPackage ./herdr-methods.nix { herdr = cfg.herdr.package; };
  wildcard = [
    "0.0.0.0"
    "[::]"
    "::"
    "*"
  ];
  listen = map (addr: {
    inherit addr;
    port = cfg.listenPort;
    ssl = true;
  }) cfg.listenAddresses;
  boolStr = b: if b then "1" else "0";

  # Prints the enrollment link as a QR code: scan it with the phone and tap
  # "Create passkey". The token rides in the URL fragment, which browsers never
  # send to the server (so it is not in any access log).
  enrollCommand = pkgs.writeShellApplication {
    name = "pasture-enroll";
    runtimeInputs = [
      pkgs.qrencode
      pkgs.curl
      pkgs.jq
    ];
    text = ''
      token_file=${lib.escapeShellArg cfg.secrets.enrollTokenFile}
      if ! token=$(cat -- "$token_file" 2>/dev/null) || [ "''${#token}" -lt 16 ]; then
        echo "pasture-enroll: can't read a token from $token_file (run it as ${cfg.user})" >&2
        exit 1
      fi
      if open=$(curl -fsS --max-time 3 http://127.0.0.1:${toString cfg.backendPort}/auth/info | jq -r .enroll); then
        if [ "$open" != true ]; then
          echo "pasture-enroll: enrollment is closed; this token was used already. Rotate it and redeploy." >&2
          exit 1
        fi
      else
        echo "pasture-enroll: the gateway is not answering; the code works once it runs" >&2
      fi
      url="https://${cfg.hostName}/enroll#t=$(jq -rn --arg t "$token" '$t | @uri')"
      # Explicit black on white in a terminal; plain blocks when captured.
      if [ -t 1 ]; then type=ANSIUTF8; else type=UTF8; fi
      qrencode -t "$type" -m 2 -- "$url"
      echo "Scan with the phone's camera, open the link, tap Create passkey. The code works once."
    '';
  };

  environment = lib.filterAttrs (_: v: v != null) (
    {
      PASTURE_HOST = cfg.hostName;
      PASTURE_PORT = toString cfg.backendPort;
      PASTURE_STATIC = "${cfg.webPackage}";
      PASTURE_SESSION_KEY_FILE = cfg.secrets.sessionKeyFile;
      PASTURE_ENROLL_TOKEN_FILE = cfg.secrets.enrollTokenFile;
      PASTURE_CREDENTIALS_FILE = cfg.secrets.credentialsFile;
      PASTURE_ENROLL = boolStr cfg.enrollment.enable;
      PASTURE_SESSION_IDLE_MINUTES = toString cfg.session.idleMinutes;
      PASTURE_SESSION_ABSOLUTE_MINUTES = toString cfg.session.absoluteMinutes;
      PASTURE_RP_NAME = cfg.webauthn.rpName;
      PASTURE_USER_NAME = cfg.webauthn.userName;
      PASTURE_APP_NAME = cfg.appName;
      PASTURE_SHELL = boolStr cfg.shell.enable;
      PASTURE_SHELL_COMMAND = if cfg.shell.command == null then null else builtins.toJSON cfg.shell.command;
      PASTURE_TMUX = if cfg.tmux.enable then "${cfg.tmux.package}/bin/tmux" else null;
      PASTURE_TMUX_DEFAULT = cfg.tmux.defaultSession;
      PASTURE_PROJECT_ROOTS = lib.concatStringsSep "," cfg.projectRoots;
      PASTURE_CERT_FILE = if cfg.tls.certFile == null then null else toString cfg.tls.certFile;
    }
    // lib.optionalAttrs herdrOn {
      PASTURE_HERDR = "${cfg.herdr.package}/bin/herdr";
      PASTURE_HERDR_SESSIONS = lib.concatStringsSep "," cfg.herdr.sessions;
      PASTURE_HERDR_METHODS = "${herdrMethods}";
      PASTURE_HERDR_PREFIX = cfg.herdr.prefixKey;
      PASTURE_AGENT_KINDS = lib.concatStringsSep "," cfg.herdr.agentKinds;
    }
    // lib.optionalAttrs (cfg.alerts.ntfy.url != null) {
      PASTURE_NTFY = cfg.alerts.ntfy.url;
      PASTURE_NTFY_TOPIC = cfg.alerts.ntfy.topic;
    }
    // lib.optionalAttrs cfg.dictation.enable {
      PASTURE_DICTATE = "1";
      PASTURE_DICTATE_SERVER = lib.getExe' cfg.dictation.package "whisper-server";
      PASTURE_DICTATE_MODEL = toString cfg.dictation.model;
      PASTURE_DICTATE_FFMPEG = "${cfg.dictation.ffmpegPackage}/bin/ffmpeg";
      PASTURE_DICTATE_LANGUAGE = cfg.dictation.language;
      PASTURE_DICTATE_THREADS = toString cfg.dictation.threads;
      PASTURE_DICTATE_MAX_SECONDS = toString cfg.dictation.maxSeconds;
      PASTURE_DICTATE_IDLE_MINUTES = toString cfg.dictation.idleMinutes;
      PASTURE_DICTATE_ARGS = builtins.toJSON cfg.dictation.extraArgs;
    }
    // lib.optionalAttrs (cfg.dictation.enable && cfg.dictation.prompt != null) {
      PASTURE_DICTATE_PROMPT = cfg.dictation.prompt;
    }
    // cfg.extraEnvironment
  );

  fontsType = types.submodule {
    options = {
      family = mkOption {
        type = types.str;
        description = "Font family name (informational; the bundle serves it as \"pasture-mono\").";
      };
      regular = mkOption {
        type = types.either types.path types.str;
        description = "TTF/OTF file for the regular weight. Converted to WOFF2 at build time.";
      };
      bold = mkOption {
        type = types.nullOr (types.either types.path types.str);
        default = null;
        description = "TTF/OTF file for the bold weight.";
      };
    };
  };
in
{
  options.services.pasture = {
    enable = mkEnableOption "pasture, a passkey-gated PWA terminal and session dashboard";

    user = mkOption {
      type = types.str;
      example = "alice";
      description = "The account whose shells and sessions are served. The gateway runs as a user unit of this account.";
    };
    linger = mkOption {
      type = types.bool;
      default = true;
      description = "Enable lingering for `user`, so the gateway runs without a login session.";
    };

    hostName = mkOption {
      type = types.str;
      example = "host.example.ts.net";
      description = ''
        DNS name the phone uses: nginx `server_name`, the WebAuthn RP ID and the origin host.
        Passkeys are bound to it for good; changing it means enrolling again.
      '';
    };
    listenAddresses = mkOption {
      type = types.listOf types.str;
      example = [ "100.64.0.10" ];
      description = "Addresses nginx listens on (IPv6 in brackets). Wildcards need `allowWildcardListen`.";
    };
    allowWildcardListen = mkOption {
      type = types.bool;
      default = false;
      description = "Allow 0.0.0.0/[::] in `listenAddresses`, for hosts that rely on firewall scoping alone.";
    };
    listenPort = mkOption {
      type = types.port;
      default = 443;
    };
    backendPort = mkOption {
      type = types.port;
      default = 8795;
      description = "Loopback port of the gateway.";
    };
    allowedCIDRs = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [ "100.64.0.0/10" ];
      description = "When non-empty, nginx allows only these client networks (`allow ...; deny all;`).";
    };
    firewall.interfaces = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = literalExpression "[ config.services.tailscale.interfaceName ]";
      description = "Interfaces on which `listenPort` is opened. The global allow list is never touched.";
    };
    nonlocalBind = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Set net.ipv{4,6}.ip_nonlocal_bind so nginx can bind an address that appears
        later (a Tailscale IP assigned after nginx starts).
      '';
    };
    nginx.after = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [ "tailscaled.service" ];
      description = "Units nginx should start after (and want).";
    };

    tls = {
      certFile = mkOption {
        type = types.nullOr (types.either types.path types.str);
        default = null;
        description = "PEM certificate (chain) for `hostName`. Required unless `tls.acmeHost` is set.";
      };
      keyFile = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "/run/secrets/pasture-tls-key";
        description = "Runtime path of the private key, readable by nginx. Never read at evaluation time.";
      };
      acmeHost = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Use the certificate of `security.acme.certs.<name>` instead of certFile/keyFile.";
      };
    };

    secrets = {
      sessionKeyFile = mkOption {
        type = types.str;
        description = "Runtime path of a random key (32+ bytes) that signs session cookies. Readable by `user`.";
      };
      enrollTokenFile = mkOption {
        type = types.str;
        description = "Runtime path of the one-time enrollment token (16+ characters). Readable by `user`.";
      };
      credentialsFile = mkOption {
        type = types.str;
        description = ''
          Runtime path of the passkey allowlist: a JSON list of credentials as the
          gateway logs them at enrollment ("[]" before the first one). Readable by `user`.
        '';
      };
    };

    enrollment.enable = mkOption {
      type = types.bool;
      default = false;
      description = ''
        Open /enroll so a new passkey can be registered with the enrollment token,
        and give `user` the `pasture-enroll` command (shows the link as a QR code).
        Turn off afterwards.
      '';
    };

    session = {
      idleMinutes = mkOption {
        type = types.ints.positive;
        default = 30;
      };
      absoluteMinutes = mkOption {
        type = types.ints.positive;
        default = 480;
      };
    };

    webauthn = {
      rpName = mkOption {
        type = types.str;
        default = "pasture";
        description = "Relying party name shown in the passkey sheet.";
      };
      userName = mkOption {
        type = types.str;
        default = "owner";
        description = "Account name stored with the passkey.";
      };
    };

    appName = mkOption {
      type = types.str;
      default = "pasture";
      description = "App name (manifest, page title).";
    };
    shortName = mkOption {
      type = types.str;
      default = cfg.appName;
      defaultText = literalExpression "config.services.pasture.appName";
      description = "Home-screen label.";
    };

    shell = {
      enable = mkOption {
        type = types.bool;
        default = true;
        description = "Offer a plain shell (a fresh one per terminal; nothing persists).";
      };
      command = mkOption {
        type = types.nullOr (types.listOf types.str);
        default = null;
        example = [
          "/run/current-system/sw/bin/zsh"
          "-l"
        ];
        description = "argv of the shell. null = the user's login shell with -l.";
      };
    };

    tmux = {
      enable = mkOption {
        type = types.bool;
        default = true;
        description = "List, attach, create, rename and kill tmux sessions.";
      };
      package = lib.mkPackageOption pkgs "tmux" { };
      defaultSession = mkOption {
        type = types.nullOr types.str;
        default = null;
        description = "Session opened (or created) by the tmux quick button.";
      };
    };

    herdr = {
      package = mkOption {
        type = types.nullOr types.package;
        default = null;
        description = "The herdr package. null disables the herdr dashboard entirely.";
      };
      sessions = mkOption {
        type = types.listOf types.str;
        default = [ "default" ];
        description = "herdr sessions always listed; running named sessions are discovered too.";
      };
      agentKinds = mkOption {
        type = types.listOf types.str;
        default = [ ];
        example = [
          "claude"
          "codex"
        ];
        description = "Agent kinds offered under New agent. Empty hides it.";
      };
      prefixKey = mkOption {
        type = types.str;
        default = "ctrl+b";
        description = "herdr's prefix key, sent by the key bar's prefix button.";
      };
    };

    projectRoots = mkOption {
      type = types.listOf types.str;
      default = [ "~" ];
      example = [ "~/dev" ];
      description = "Directories (and their children) allowed as the working directory of new sessions and agents.";
    };

    alerts.ntfy = {
      url = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "http://127.0.0.1:2586";
        description = "Base URL of an ntfy server whose topic feeds the in-app inbox. null disables it.";
      };
      topic = mkOption {
        type = types.str;
        default = "agents";
      };
    };

    dictation = {
      enable = mkEnableOption ''
        the dictation button. Audio is transcribed on this host by whisper.cpp's
        whisper-server, which the gateway starts on first use and keeps loaded
        (partial text while you talk, the final text right after)'';
      package = lib.mkPackageOption pkgs "whisper-cpp" {
        extraDescription = "Must provide `bin/whisper-server`. Use whisper-cpp-vulkan (or a CUDA build) for a GPU.";
      };
      model = mkOption {
        type = types.nullOr types.path;
        default = null;
        example = literalExpression ''
          pkgs.fetchurl {
            url = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin";
            hash = "sha256-...";
          }
        '';
        description = "A ggml whisper model. Required when dictation is on.";
      };
      language = mkOption {
        type = types.str;
        default = "en";
      };
      threads = mkOption {
        type = types.ints.positive;
        default = 4;
      };
      maxSeconds = mkOption {
        type = types.ints.positive;
        default = 60;
      };
      idleMinutes = mkOption {
        type = types.numbers.nonnegative;
        default = 30;
        description = "Stop whisper-server (freeing its memory) after this long without dictation; 0 keeps it loaded.";
      };
      prompt = mkOption {
        type = types.nullOr types.str;
        default = null;
        example = "Claude, tmux, NixOS, git rebase, pull request.";
        description = "Initial prompt for whisper: words and spellings to expect.";
      };
      extraArgs = mkOption {
        type = types.listOf types.str;
        default = [ ];
        example = [ "--device" "1" ];
        description = "Extra whisper-server arguments.";
      };
      ffmpegPackage = lib.mkPackageOption pkgs "ffmpeg-headless" {
        extraDescription = "Only decodes uploaded recordings, from browsers without AudioWorklet.";
      };
    };

    theme = {
      palette = mkOption {
        type = types.attrsOf types.anything;
        default = import ./themes/default.nix;
        defaultText = literalExpression "import \"\${pasture}/nix/themes/default.nix\"";
        description = "Colour palette; keys in nix/themes/schema.md. Extra keys and non-string values are ignored.";
      };
      fonts = mkOption {
        type = types.nullOr fontsType;
        default = null;
        description = "Terminal/UI font (a Nerd Font Mono). null = JetBrainsMono Nerd Font Mono.";
      };
    };

    webPackage = mkOption {
      type = types.package;
      default = self.lib.mkWeb pkgs {
        theme = cfg.theme.palette;
        inherit (cfg.theme) fonts;
        inherit (cfg) appName shortName;
      };
      defaultText = literalExpression "pasture.lib.mkWeb pkgs { theme = cfg.theme.palette; ... }";
      description = "The static PWA bundle. Override for a custom frontend.";
    };

    extraEnvironment = mkOption {
      type = types.attrsOf types.str;
      default = { };
      example = {
        SHELL = "/run/current-system/sw/bin/bash";
      };
      description = "Extra environment for the gateway (and so for the shells it starts).";
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = lib.hasInfix "." cfg.hostName;
        message = "services.pasture.hostName must be a domain name (WebAuthn does not accept bare host names or IPs).";
      }
      {
        assertion = cfg.listenAddresses != [ ];
        message = "services.pasture.listenAddresses must not be empty.";
      }
      {
        assertion = cfg.allowWildcardListen || !(lib.any (a: lib.elem a wildcard) cfg.listenAddresses);
        message = "services.pasture.listenAddresses contains a wildcard; set allowWildcardListen = true if that is intended.";
      }
      {
        assertion = cfg.tls.acmeHost != null || (cfg.tls.certFile != null && cfg.tls.keyFile != null);
        message = "services.pasture needs tls.certFile and tls.keyFile, or tls.acmeHost.";
      }
      {
        assertion = !cfg.dictation.enable || cfg.dictation.model != null;
        message = "services.pasture.dictation.model must be set when dictation is enabled.";
      }
      {
        assertion = cfg.backendPort != cfg.listenPort;
        message = "services.pasture.backendPort must differ from listenPort.";
      }
    ];

    services.nginx = {
      enable = true;
      recommendedTlsSettings = mkDefault true;
      recommendedOptimisation = mkDefault true;
      recommendedGzipSettings = mkDefault true;
      recommendedProxySettings = mkDefault true;

      virtualHosts.${cfg.hostName} = {
        onlySSL = true;
        inherit listen;
        sslCertificate = mkIf (cfg.tls.acmeHost == null) cfg.tls.certFile;
        sslCertificateKey = mkIf (cfg.tls.acmeHost == null) cfg.tls.keyFile;
        useACMEHost = cfg.tls.acmeHost;
        extraConfig = ''
          ${concatMapStrings (cidr: "allow ${cidr};\n") cfg.allowedCIDRs}${optionalString (cfg.allowedCIDRs != [ ]) "deny all;\n"}
          add_header Strict-Transport-Security "max-age=31536000" always;
          client_max_body_size 3m;
        '';
        locations."/" = {
          proxyPass = "http://127.0.0.1:${toString cfg.backendPort}";
          proxyWebsockets = true;
          extraConfig = ''
            proxy_buffering off;
            proxy_request_buffering off;
            proxy_read_timeout 1h;
            proxy_send_timeout 1h;
          '';
        };
      };

      # Anything that is not our host name on these addresses: no certificate,
      # the TLS handshake is refused; a wrong Host header gets 444.
      virtualHosts."pasture-reject" = {
        default = true;
        rejectSSL = true;
        inherit listen;
        locations."/".return = "444";
      };
    };

    systemd.services.nginx = mkIf (cfg.nginx.after != [ ]) {
      after = cfg.nginx.after;
      wants = cfg.nginx.after;
    };

    boot.kernel.sysctl = mkIf cfg.nonlocalBind {
      "net.ipv4.ip_nonlocal_bind" = 1;
      "net.ipv6.ip_nonlocal_bind" = 1;
    };

    networking.firewall.interfaces = lib.genAttrs cfg.firewall.interfaces (_: {
      allowedTCPPorts = [ cfg.listenPort ];
    });

    users.users.${cfg.user} = {
      linger = mkIf cfg.linger true;
      packages = mkIf cfg.enrollment.enable [ enrollCommand ];
    };

    systemd.user.services.pasture = {
      description = "pasture gateway (passkey PWA terminal)";
      wantedBy = [ "default.target" ];
      after = optional herdrOn "herdr.service";
      wants = optional herdrOn "herdr.service";
      unitConfig.ConditionUser = cfg.user;
      # Inherit the user manager's PATH instead of NixOS' minimal service PATH:
      # shells (and any tmux server) started from here should look like a login.
      enableDefaultPath = false;
      inherit environment;
      serviceConfig = {
        ExecStart = lib.getExe gateway;
        Restart = "on-failure";
        RestartSec = 2;
        StateDirectory = "pasture";
        StateDirectoryMode = "0700";
        RuntimeDirectory = "pasture";
        RuntimeDirectoryMode = "0700";
        # Terminals are children of this unit: stopping it ends attach clients and
        # plain shells, never herdr panes or tmux sessions (separate servers).
        KillMode = "control-group";
        TimeoutStopSec = 10;
      };
    };
  };
}
