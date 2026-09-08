{
  symlinkJoin,
  openssl
}:
symlinkJoin {
  name = "openssl-merged";
  paths = [ openssl.dev openssl.out ];
}