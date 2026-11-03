{
  description = "pasture: a passkey-gated PWA terminal and session dashboard for your own machine";

  # Consumers should override this with `inputs.nixpkgs.follows = "nixpkgs"`.
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      # mkWeb pkgs { theme ? <palette attrs>; fonts ? { family; regular; bold; }; iconFont; appName; shortName; }
      lib.mkWeb = pkgs: args: pkgs.callPackage ./nix/web.nix args;

      packages = forAllSystems (pkgs: {
        gateway = pkgs.callPackage ./nix/gateway.nix { };
        web = self.lib.mkWeb pkgs { };
        default = self.packages.${pkgs.stdenv.hostPlatform.system}.gateway;
      });

      nixosModules.pasture = import ./nix/module.nix self;
      nixosModules.default = self.nixosModules.pasture;

      # `nix develop`: Python with the gateway's dependencies, for running the
      # tests and a local gateway (see README "Development").
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: [
              ps.aiohttp
              ps.webauthn
            ]))
            pkgs.woff2
          ];
        };
      });
    };
}
