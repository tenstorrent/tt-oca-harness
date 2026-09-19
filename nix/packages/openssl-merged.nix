{
  symlinkJoin,
  # Use nixpkgs openssl3 to get correct patches
  openssl_3_5,
  runCommand,
  yq-go,
  fetchurl,
  writeText,
  lib,
  ...
}: let
  # Once VP is merged, source OpenSSL Version from CI Yaml
  vp_mk = ../../virtual_platform/tt-oca-harness-model/.github/workflows/ci-rhel8.yml;
  configJson = runCommand "config.json" {} ''
    ${yq-go}/bin/yq -o=json '${vp_mk}' > $out
  '';

  config = builtins.fromJSON (builtins.readFile configJson);

  vp_version = config.env.OPENSSL3_VERSION;

  version =
    if builtins.pathExists vp_mk
    then vp_version
    else "3.3.2";

  openssl = openssl_3_5.overrideAttrs (prev: {
    inherit version;
    src = fetchurl {
      url = "https://github.com/openssl/openssl/releases/download/openssl-${version}/openssl-${version}.tar.gz";
      hash = "sha256-LopAsBl5r+i+C7+z3l3BxnCf7bRtbInBDaEUq1/D0oE=";
    };
    # Overriding a newer version of OpenSSL means a patch needs to be replaced - this should be able to be removed if the openssl dependency is updated to 3.5+
    patches = let
      openssl_subst_patch = writeText "openssl-3.3.2-cert.patch" ''
        diff --git a/include/internal/common.h b/include/internal/common.h
        index b176a27..302e1c6 100644
        --- a/include/internal/common.h
        +++ b/include/internal/common.h
        @@ -83,7 +83,7 @@ __owur static ossl_inline int ossl_assert_int(int expr, const char *exprstr,
         # ifndef OPENSSL_SYS_VMS
         #  define X509_CERT_AREA          OPENSSLDIR
         #  define X509_CERT_DIR           OPENSSLDIR "/certs"
        -#  define X509_CERT_FILE          OPENSSLDIR "/cert.pem"
        +#  define X509_CERT_FILE          "/etc/certs/ca-certificates.crt"
         #  define X509_PRIVATE_DIR        OPENSSLDIR "/private"
         #  define CTLOG_FILE              OPENSSLDIR "/ct_log_list.cnf"
         # else
      '';
    in
      map (p:
        if lib.hasSuffix "-use-etc-ssl-certs.patch" p
        then openssl_subst_patch
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
