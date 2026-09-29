# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  gradle,
  jdk,
  fetchFromGitHub,
  stdenv,
  jre,
  ...
}:
stdenv.mkDerivation (finalAttrs: {
  pname = "ditaa";
  version = "mini-1.0.3";

  src = fetchFromGitHub {
    owner = "pepijnve";
    repo = "ditaa";
    rev = "${finalAttrs.version}";
    hash = "sha256-VTB4A4v4ZzMIiQU2S7y7WaX/UsCZ7BxnBOGxL+Et2qs=";
  };

  nativeBuildInputs = [
    gradle
    jdk
  ];

  patchPhase = ''
    sed -i '/net.researchgate.release/d' build.gradle
    sed -i '/^release {/,/^}/d' build.gradle
    sed -i '/^dependencies {/,/^}/d' build.gradle
  '';

  buildPhase = ''
    export GRADLE_USER_HOME=$(mktemp -d)
    gradle --no-daemon jar
  '';

  installPhase = ''
    mkdir -p $out/bin $out/lib
    cp build/libs/ditaa${finalAttrs.version}.jar $out/lib/ditaa.jar
    cat > $out/bin/ditaa << 'EOF'
    #!${stdenv.shell}
    exec ${jre}/bin/java -jar $out/lib/ditaa.jar "$@"
    EOF
    chmod a+x $out/bin/ditaa
  '';
})
