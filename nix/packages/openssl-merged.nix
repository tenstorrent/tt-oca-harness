{
  symlinkJoin,
  # nixpkgs openssl3 already carries the correct build patches; take it as-is.
  openssl_3_5,
  writeText,
  lib,
  ...
}: let
  # The container's CA bundle lives at /etc/certs/ca-certificates.crt, not the
  # /etc/ssl/certs location nixpkgs' use-etc-ssl-certs patch points at, so swap
  # that patch for one redirecting X509_CERT_FILE to the container's path.
  openssl = openssl_3_5.overrideAttrs (prev: {
    # Overriding the patches forces a local rebuild, which reruns the test suite
    # against the current clock. 90-test_sslapi ships fixed-lifetime certificates
    # that have since expired, so exclude that one file; the rest of the suite runs.
    # openssl's TESTS matcher globs *-<name>.t, so the token drops the NN- prefix.
    checkFlags = (prev.checkFlags or []) ++ ["TESTS=-test_sslapi"];
    patches = let
      cert_path_patch = writeText "openssl-cert-path.patch" ''
        diff --git a/include/internal/common.h b/include/internal/common.h
        --- a/include/internal/common.h
        +++ b/include/internal/common.h
        @@ -83,7 +83,7 @@ __owur static ossl_inline int ossl_assert_int(int expr, const char *exprstr,
         #ifndef OPENSSL_SYS_VMS
         #define X509_CERT_AREA OPENSSLDIR
         #define X509_CERT_DIR OPENSSLDIR "/certs"
        -#define X509_CERT_FILE OPENSSLDIR "/cert.pem"
        +#define X509_CERT_FILE "/etc/certs/ca-certificates.crt"
         #define X509_PRIVATE_DIR OPENSSLDIR "/private"
         #define CTLOG_FILE OPENSSLDIR "/ct_log_list.cnf"
         #else
      '';
    in
      map (p:
        if lib.hasSuffix "-use-etc-ssl-certs.patch" p
        then cert_path_patch
        else p)
      prev.patches;
  });
in
  symlinkJoin {
    name = "openssl-merged";
    paths = [
      openssl.dev
      openssl.out
    ];
  }
