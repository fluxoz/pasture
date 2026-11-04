# `pasture`: the command for running pasture without the NixOS module
# (`nix run`, home-manager; Linux or macOS with Nix, on a tailnet). It wraps the
# gateway with the web bundle; give it whisper-cpp and a model for dictation.
{
  lib,
  runCommand,
  makeWrapper,
  gateway,
  web,
  dictationServer ? null, # a whisper-cpp package (provides whisper-server)
  dictationModel ? null, # a ggml model file
}:
let
  dictation = dictationServer != null && dictationModel != null;
in
runCommand "pasture"
  {
    nativeBuildInputs = [ makeWrapper ];
    passthru = { inherit gateway web; };
    meta = gateway.meta // {
      description = "Passkey-gated PWA terminal and agent dashboard for your tailnet";
      mainProgram = "pasture";
    };
  }
  ''
    makeWrapper ${lib.getExe' gateway "pasture"} $out/bin/pasture \
      --set-default PASTURE_STATIC ${web} \
      ${lib.optionalString dictation ''
        --set-default PASTURE_DICTATE_SERVER ${lib.getExe' dictationServer "whisper-server"} \
        --set-default PASTURE_DICTATE_MODEL ${dictationModel}
      ''}
  ''
