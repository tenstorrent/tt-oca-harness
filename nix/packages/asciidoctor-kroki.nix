{
  buildNpmPackage,
  fetchFromGitHub,
  ...
}:
buildNpmPackage {
  pname = "asciidoctor-kroki";
  version = "0.18.1";

  src = fetchFromGitHub {
    owner = "asciidoctor";
    repo = "asciidoctor-kroki";
    rev = "v0.18.1";
    sha256 = "sha256-nAG+JxpQ8Ai+77uHscJ83lf2ghG+nQ6r+1KmnIg+iak=";
  };

  npmDepsHash = "sha256-NCrEZuwpb98YRF+OhzmasgreanrJLqKQ2aJIh+/rcdc=";
  dontNpmBuild = true;

  PUPPETEER_SKIP_DOWNLOAD = 1;

  installPhase = ''
    runHook preInstall
    mkdir -p $out/lib/node_modules/asciidoctor-kroki
    find . -mindepth 1 -maxdepth 1 -not -name 'node_modules' \
      -exec cp -r {} $out/lib/node_modules/asciidoctor-kroki/ \;
    cp -r node_modules/. $out/lib/node_modules/
    runHook postInstall
  '';
}
