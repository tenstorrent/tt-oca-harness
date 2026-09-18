# Bundle Antora with extensions to build documentation
{
  lib,
  antora,
  antora-lunr-extension,
  asciidoctor-kroki,
  runCommand,
  writeShellScript,
  ...
}:
let
  pkgList = [
    (antora-lunr-extension.overrideAttrs (old: {
      postInstall = "";
    }))
    asciidoctor-kroki
  ];
  nodePath = lib.concatMapStringsSep ":" (p: "${p}/lib/node_modules") pkgList;
  wrapper = writeShellScript "antora" ''
    export NODE_PATH="${nodePath}"
    extra=()
    [[ -n "''${KROKI_SERVER_URL:-}" ]] && extra+=(--attribute "kroki-server-url=''${KROKI_SERVER_URL}")
    exec ${antora}/bin/antora "''${extra[@]}" "$@"
  '';
in
runCommand "ocah-antora" {} ''
  mkdir -p $out/bin
  cp ${wrapper} $out/bin/antora
  chmod +x $out/bin/antora
''
