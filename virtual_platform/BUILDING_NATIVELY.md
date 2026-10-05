# Building and running the VP natively

How to build `sep-vp` and run the test suites on your own host, without the
OCAH container.

The container path in [`README.md`](README.md) needs no host toolchain and is
the shorter route when it is available. Build natively when it is not: no nix
and no container engine, a host where the container cannot start, or a
build/test loop tight enough that the container round trip is the slow part.

## What the host must provide

| | requirement | why |
|---|---|---|
| C++ compiler | g++ >= 10, or a clang new enough for C++20 | the VP is C++20 |
| Boost | >= 1.74 (`BOOST_VERSION` >= `107400`), with the compiled `program_options` and `iostreams` libraries | older releases are not C++20-clean; `std::allocator::allocate(n, hint)` was removed |
| OpenSSL | >= 3.0 | the hmac/kmac peripherals use the `EVP_MAC` API, which 1.1.x lacks. `include/openssl/core_names.h` is the marker |
| SystemC, CCI | none | rarely packaged, so always built from source into `local/` |
| RISC-V toolchain | optional | only for the suites that build firmware; see below |

Nothing else is required. SystemC and CCI compile in about a minute.

## Pointing the build at them

`make -C virtual_platform deps-info` reports where each prefix resolved and why,
and is the fastest way to see what a build will do before starting it.

If the system compiler is too old, activate a newer one first. On a distribution
that ships toolsets in parallel, that is usually a `scl enable` or an `enable`
script; otherwise set `CXX` to the compiler you want:

```bash
export CXX=/path/to/g++          # or: scl enable gcc-toolset-<N> bash
make -C virtual_platform check-cxx      # silent on success
```

Boost and OpenSSL resolve in this order: an explicit `BOOST_ROOT` /
`OPENSSL_ROOT`, then a complete build already in `local/`, then an adequate
system install under `/usr`, and failing all of those they are built from
source. So a host whose `/usr` copies are too old still works -- it just spends
the time. If newer ones are installed elsewhere, point at them and both source
builds drop out:

```bash
export BOOST_ROOT=/path/to/boost OPENSSL_ROOT=/path/to/openssl
make -C virtual_platform deps-info      # both should read "explicit (environment)"
```

Set a variable back to empty (`make vp BOOST_ROOT=`) to re-enable
auto-resolution. `VP_SYS_DEPS=0` refuses system copies entirely and builds
everything into `local/`, for a hermetic tree.

## Build

```bash
make -C virtual_platform vp NPROC=$(nproc)
```

The binary lands at `tt-oca-harness-model/vp/build/bin/sep-vp`. Rebuilding after
a change to the model is incremental -- CMake only, no dependency work.

`vp-clean` wipes the build tree and reconfigures without touching `local/`;
`clean` also discards the dependency builds, which is rarely what you want.

Two checks worth knowing when a build looks wrong:

```bash
./virtual_platform/tt-oca-harness-model/vp/build/bin/sep-vp --help
ldd  ./virtual_platform/tt-oca-harness-model/vp/build/bin/sep-vp | grep -E 'boost|ssl|crypto'
```

`ldd` shows which Boost and OpenSSL were actually linked, which is how to catch
an environment that silently picked up the system copies.

## The harness suite

```bash
make -C virtual_platform vp-test
make -C virtual_platform vp-test PYTEST_ARGS="-q -k 'fuses or drift'"
```

**It has two tiers, and the split decides what you can run without a RISC-V
toolchain.** `tests/test_fuses.py` and `tests/test_efuse_map_drift.py` are pure
Python: they parse the model's headers and fuse maps, need no firmware, and
finish in well under a second. They are the fastest signal on an eFuse or
register-map change, and the drift guard fails loudly when the model falls
behind the RDL.

Everything under `tests/bootcode/`, `tests/fw/` and `tests/sim/` boots real
firmware. Those need the SEP boot ROM, which compiles against **picolibc**, so a
bare `riscv64-unknown-elf-gcc` is not enough. Without one, `fw_make` falls back
to the container; with no container either, those tests fail on the firmware
build rather than on anything under test.

**The requirement is a `riscv64-unknown-elf` toolchain that can compile against
picolibc**, i.e. one where this succeeds:

```bash
echo 'int main(void){return 0;}' |
  riscv64-unknown-elf-gcc --specs=picolibc.specs -x c -c - -o /dev/null
```

Debian and Ubuntu package both halves; other distributions vary, and a
self-built toolchain needs picolibc added explicitly:

```bash
sudo apt install gcc-riscv64-unknown-elf picolibc-riscv64-unknown-elf
```

Point `RISCV_TOOLCHAIN` at the directory holding those binaries -- a *bin
directory*, not an install prefix. `RISCV_PREFIX` then resolves itself from what
it finds there:

```bash
make -C virtual_platform vp-test RISCV_TOOLCHAIN=/path/to/toolchain/bin
```

`RISCV_TOOLCHAIN` is what the bootrom Makefile branches on. Leave it unset and
`toolchain-images` dispatches to `docker-run.sh run-here` even when a usable
toolchain is on `PATH`. Where no toolchain can be installed, `docker-run.sh`
documents its own container and sandbox options in its header.

A firmware-build failure names the bootrom Makefile rather than a test, which is
how to tell it apart from a real defect.

**A build directory older than the source layout fails confusingly.** The
bootrom compiles with `-MMD -MP` and re-reads the generated `.d` files, so a
build tree predating a file's move still lists the old path and make reports a
missing prerequisite that was never yours:

```
No rule to make target 'src/key_digests.c', needed by 'build/key_digests.o'
```

`key_digests.c` is generated into the build directory now, not tracked under
`src/`. Delete the build directory and rebuild; nothing in it is authored.
Suspect this whenever a prerequisite names a path that does not exist in the
tree. The same reasoning covers a toolchain change -- see the stale-object note
in `AGENTS.md`.

**A boot ROM and a VP from different dates will fail in ways neither is
responsible for.** The suites assert on status messages, so a ROM built before
a model change can hang against a newer `sep-vp` and report a timeout rather
than a mismatch. Rebuild the ROM before believing a boot failure.

### Driving a boot directly

If a boot ROM ELF is already built -- from an earlier container build, or copied
from a CI artifact -- the boot path can be exercised without rebuilding it. No
ELF is checked in, so this only helps when one is already present:

```bash
cd virtual_platform
SEP_VP_BIN=<abs path to sep-vp> python -m sepvp.cli \
  --bin ../hw/sys/sep/bootrom/prod/build/boot_rom.elf \
  --boot primary --until SEP_MSG_FUSE_SBOOT_DIS
```

It exits non-zero on any production ERROR status, or on failing to reach the
named one, so it is a quick check that a reset or register-map change did not
break boot.

## The model's own firmware suite

`tt-oca-harness-model/sw/sep-vp-tests/` is a separate suite: bare-metal RV32
firmware run directly on `sep-vp`. It is where peripheral regressions surface --
OTBN, CSRNG, EDN, key manager, mailbox, HMAC, SPI -- and the harness `vp-test`
suite covers none of it.

**It needs no picolibc.** Unlike the boot ROM it builds `-ffreestanding
-nostdlib` with its own startup and `printf`, so any RV32-capable toolchain
works:

```bash
export PATH=/path/to/riscv-toolchain/bin:$PATH
```

**Pass `VP` explicitly.** The runner's auto-detection does not work on Linux. It
ranks candidate binaries by modification time with

```sh
stat -f %m "${c}" 2>/dev/null || stat -c %Y "${c}" 2>/dev/null || echo 0
```

which assumes `stat -f %m` produces nothing useful outside BSD. Under GNU
coreutils `-f` means *file system* status: `%m` is rejected, but the command
still prints six lines of filesystem information to stdout before exiting
non-zero. The fallback does run, and its output is appended to that, so the
captured value begins `  File: "..."` rather than a number. The numeric
comparison then errors, every candidate is discarded -- including the `sep-vp`
just built -- and the runner reports `sep-vp binary not found` and builds its
own, quietly ignoring yours.

`VP` is the documented override, so this is the supported knob rather than a
workaround -- but without it the suite does the wrong thing silently instead of
failing:

```bash
cd virtual_platform/tt-oca-harness-model
export VP="$PWD/vp/build/bin/sep-vp"
cd sw/sep-vp-tests
./run_sep_vp_tests.sh                 # the whole suite
./run_sep_vp_tests.sh <test-name>     # one test
```

## Testing a model branch

The model is a submodule, so a branch can be tested without touching the pin:

```bash
git -C virtual_platform/tt-oca-harness-model fetch origin
git -C virtual_platform/tt-oca-harness-model checkout <branch-or-sha>
make -C virtual_platform vp NPROC=$(nproc)
make -C virtual_platform vp-test
```

The pin only needs updating to land the change. The submodule reads as modified
in `git status` meanwhile, which is expected.

## If something goes wrong

**`check-cxx` fails.** The newer compiler is not active. `$CXX --version` should
report the version you activated, not the system default.

**Boost or OpenSSL resolve to `will build from source` unexpectedly.** The
variables are not exported, or point at a prefix without the compiled libraries.
`deps-info` names what it chose and why.

**The build succeeds but the VP fails on a missing symbol.** Check `ldd`: mixing
headers from one prefix with libraries from another is the usual cause.

**A test fails while building firmware rather than on an assertion.** That is the
RISC-V toolchain gap above, not a defect in what you changed.

**`make: execvp: .../accellera_config.ini: Permission denied`.** `VP` expanded
empty, so make took the ini as the command. Export it as above.

**`run_sep_vp_tests.sh` reports `sep-vp binary not found` and starts building
one** although the binary exists. Same cause. The giveaway is a
`[: File: "..."` error immediately above the warning: that is the failed numeric
comparison, not a missing file.
