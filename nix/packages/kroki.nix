{
  stdenv,
  kroki-src,
  jre,
  writeShellScript,
  lib,
  graphviz,
  plantuml,
  svgbob,
  ocah-ditaa,
  pikchr,
  d2,
  umlet,
  wireviz,
  vega-cli,
  blockdiag,
  python313Packages,
  kroki-mermaid ? null,
  port ? "8001",
  ...
}: let
  wavedrom = python313Packages.wavedrom;

  # Delegator-based companions: HTTP services started alongside the main server.
  # Add kroki-bpmn, kroki-excalidraw, kroki-diagramsnet here as they are packaged,
  # following the same pattern.
  companions = lib.optional (kroki-mermaid != null) {
    pkg = kroki-mermaid;
    bin = "kroki-mermaid";
    hostVar = "KROKI_MERMAID_HOST";
    portVar = "KROKI_MERMAID_PORT";
    port = 8002;
  };

  companionLines =
    lib.concatMapStrings (c: ''
      ${c.pkg}/bin/${c.bin} &
      _PIDS+=($!)
      export ${c.hostVar}=localhost
      export ${c.portVar}=${toString c.port}
    '')
    companions;

  wrapper = writeShellScript "kroki" ''
    set -euo pipefail
    _PIDS=()
    cleanup() {
      for pid in "''${_PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
      done
      wait "''${_PIDS[@]:-}" 2>/dev/null || true
    }
    trap cleanup EXIT

    ${companionLines}

    export KROKI_DOT_BIN_PATH=${graphviz}/bin/dot
    export KROKI_SVGBOB_BIN_PATH=${svgbob}/bin/svgbob
    export KROKI_PLANTUML_BIN_PATH=${plantuml}/bin/plantuml
    export KROKI_PIKCHR_BIN_PATH=${pikchr}/bin/pikchr
    export KROKI_D2_BIN_PATH=${d2}/bin/d2
    export KROKI_UMLET_BIN_PATH=${umlet}/bin/umlet
    export KROKI_DITAA_BIN_PATH=${ocah-ditaa}/bin/ditaa
    export KROKI_WIREVIZ_BIN_PATH=${wireviz}/bin/wireviz
    export KROKI_BLOCKDIAG_BIN_PATH=${blockdiag}/bin/blockdiag
    export KROKI_VEGA_BIN_PATH=${vega-cli}/bin/vg2svg
    export KROKI_WAVEDROM_BIN_PATH=${wavedrom}/bin/wavedrompy
    export KROKI_PORT=${port}

    ${jre}/bin/java \
      -jar "$(dirname "$0")/../lib/kroki.jar" \
      "$@" &
    _KROKI_PID=$!
    _PIDS+=($_KROKI_PID)
    wait "$_KROKI_PID"
  '';
in
  stdenv.mkDerivation rec {
    pname = "kroki";
    version = kroki-src.version;

    src = kroki-src.jar;

    dontUnpack = true;
    dontBuild = true;

    installPhase = ''
      runHook preInstall
      mkdir -p $out/lib $out/bin
      cp $src $out/lib/kroki.jar
      cp ${wrapper} $out/bin/kroki
      chmod +x $out/bin/kroki
      runHook postInstall
    '';

    meta = {
      description = "Convert plain text diagrams to images";
      homepage = "https://kroki.io";
      license = lib.licenses.mit;
      mainProgram = "kroki";
    };
  }
