{
  fetchurl,
  version ? "0.32.1",
  fetchFromGitHub,
  ...
}:{
  inherit version;

  jar = fetchurl {
    url = "https://github.com/yuzutech/kroki/releases/download/v${version}/kroki-standalone-server-v${version}.jar";
    hash = "sha256-OICxNNzbKhsyWD7OCMNEIB4gw5zYl31QNmghgzjPsWc==";
  };

  src = fetchFromGitHub {
    owner = "yuzutech";
    repo = "kroki";
    rev = "v${version}";
    hash = "sha256-WQxqVGa3UIR+JfpzEV9EX82kgbRrHfHZyWrJIEg0jmo==";
  };
}
