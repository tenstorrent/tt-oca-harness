{bender, ...}:
bender.overrideAttrs (old: {
  postPatch =
    (old.postPatch or "")
    + ''
      substituteInPlace crates/bender-slang/build.rs \
        --replace-fail '("SLANG_USE_MIMALLOC", "1")' '("SLANG_USE_MIMALLOC", "0")'
    '';
})
