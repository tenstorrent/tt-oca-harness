{
  symlinkJoin,
  boost182,
  runCommand,
  yq-go,
  fetchurl,
  ...
}:
let
# Once VP is merged, source Boost Version from CI Yaml
vp_mk = ../../virtual_platform/tt-oca-harness-model/.github/workflows/ci-rhel8.yml;
configJson = runCommand "config.json" {} ''
  ${yq-go}/bin/yq -o=json '${vp_mk}' > $out
'';

config = builtins.fromJSON (builtins.readFile configJson);

vp_version = config.env.BOOST_VERSION;
version = if builtins.pathExists vp_mk then vp_version else "1.84.0";

boost=boost182.overrideAttrs(old: {
  inherit version;
  src = fetchurl {
    urls = [
      "mirror://sourceforge/boost/boost_${builtins.replaceStrings [ "." ] [ "_" ] version}.tar.bz2"
      "https://boostorg.jfrog.io/artifactory/main/release/${version}/source/boost_${
        builtins.replaceStrings [ "." ] [ "_" ] version
      }.tar.bz2"
    ];
    hash = "sha256-zEuJOs9kXJ1LaY6aDwjKiEaqXWxoJ1wUw+eUnCQQlFQ=";
  };
});

in symlinkJoin {
  name = "boost-merged";
  paths = [
    boost.dev
    boost
  ];
}
