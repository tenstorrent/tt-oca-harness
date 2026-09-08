# Build SystemC and other dependencies of Virtual Platform
{
  systemc,
  ...
}: systemc.overrideAttrs (old: {
  cmakeFlags = (old.cmakeFlags or []) ++ [ "-DCMAKE_CXX_STANDARD=20" ];
  configureFlags = (old.configureFlags or []) ++ [ "CXXFLAGS=\"-std=c++20\"" ];
})