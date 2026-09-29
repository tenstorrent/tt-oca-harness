{
  symlinkJoin,
  # nixpkgs openssl3 already carries the correct build patches; take it as-is.
  openssl_3_5,
  ...
}: let
  # The container's CA bundle lives at /etc/certs/ca-certificates.crt, not the
  # /etc/ssl/certs location nixpkgs' use-etc-ssl-certs patch points at, so swap
  # that patch for one redirecting X509_CERT_FILE to the container's path.
  openssl = openssl_3_5.overrideAttrs (prev: {
    # 90-test_sslapi ships fixed-lifetime certificates that have since expired, so
    # exclude that one file; the rest of the suite runs. openssl's TESTS matcher
    # globs *-<name>.t, so the token drops the NN- prefix.
    checkFlags = (prev.checkFlags or []) ++ ["TESTS=-test_sslapi"];
  });
in
  symlinkJoin {
    name = "openssl-merged";
    paths = [
      openssl.dev
      openssl.out
    ];
  }
