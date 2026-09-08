{
  symlinkJoin,
  boost
}:
symlinkJoin {
  name = "boost-merged";
  paths = [ boost.dev boost ];
}