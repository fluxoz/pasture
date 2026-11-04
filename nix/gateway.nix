# The gateway: aiohttp + py_webauthn. The unit tests (pure, no network) run as
# part of the build. Tool paths (tmux, herdr, ffmpeg, whisper) come from the
# environment the NixOS module sets, not from this package.
{ lib, python3Packages }:
python3Packages.buildPythonApplication {
  pname = "pasture-gateway";
  version = "0.4.0";
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../gateway;
    fileset = lib.fileset.unions [
      ../gateway/pyproject.toml
      (lib.fileset.fileFilter (f: f.hasExt "py") ../gateway/pasture)
      (lib.fileset.fileFilter (f: f.hasExt "py") ../gateway/tests)
    ];
  };

  build-system = [ python3Packages.setuptools ];
  dependencies = with python3Packages; [
    aiohttp
    cryptography
    segno
    webauthn
  ];

  nativeCheckInputs = [ python3Packages.unittestCheckHook ];
  unittestFlags = [
    "-s"
    "tests"
    "-t"
    "."
    "-v"
  ];
  pythonImportsCheck = [ "pasture" ];

  meta = {
    description = "Gateway for pasture, a passkey-gated PWA terminal and session dashboard";
    license = lib.licenses.mit;
    mainProgram = "pasture-gateway";
    platforms = lib.platforms.unix;
  };
}
