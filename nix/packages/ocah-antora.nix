# Bundle Antora with extensions to build documentation
{
  lib,
  antora,
  antora-lunr-extension,
  asciidoctor-kroki,
  runCommand,
  makeWrapper,
  ...
}: let
  pkgList = [
    (antora-lunr-extension.overrideAttrs (old: {
      postInstall = "";
    }))
    asciidoctor-kroki
  ];
  nodePath = lib.concatMapStringsSep ":" (p: "${p}/lib/node_modules") pkgList;
in
  runCommand "ocah-antora"
  {
    nativeBuildInputs = [makeWrapper];
  }
  ''
    mkdir -p $out/bin
    makeWrapper ${antora}/bin/antora $out/bin/antora \
      --set NODE_PATH "${nodePath}"
  ''
