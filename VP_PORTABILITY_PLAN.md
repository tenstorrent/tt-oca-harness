# Remove internal tooling paths from the SEP VP build (arbitrary-environment support)

**Two supported modes** (user decision): the **native build** (system-or-local deps,
guarded toolset — Steps 1–5) remains the default; a **containerized build+run mode**
(Steps 6–9) is added for users whose only capability is running containers.

## Context

The SEP virtual-platform build must work outside internal build servers. Exploration
(verified against the working tree, branch `inmcm/remove_internal_path_dependencies`)
shows Boost/OpenSSL are *not* actually resolved from `/tools_soc` in code — they build
from source into `virtual_platform/local/` by default. The real blockers:

1. **`ACTIVATE := source /opt/rh/$(GCC_TOOLSET)/enable`** (unguarded, first line of every
   recipe under `.ONESHELL` + `-ec`) — hard-fails on any non-RHEL host.
2. **No version floors anywhere**: tt-oca-sim needs OpenSSL ≥ 3.0 (`openssl/core_names.h`,
   EVP_MAC in hmac/kmac) and a C++20-clean Boost (RHEL8's 1.66 breaks); nothing checks,
   so old system libs are silently accepted (`configure_vp.sh` probes `/usr` first) and
   fail late with cryptic compile errors.
3. `/tools_soc` RISC-V toolchain defaults in `Makefile` and `sepvp/paths.py` (all uses
   guarded; firmware ROM/DV builds already fall back to the ocah-toolchain container).

tt-oca-sim's own Ubuntu CI (`ci.yml`) proves distro `libboost-{iostreams,program_options}-dev`
+ `libssl-dev` satisfy the build with `/usr` roots. sep-vp needs only Boost `iostreams` +
`program_options` compiled components (+ headers), and both `libssl` and `libcrypto`.
The repo's own `tools/dv/check_no_vendor_paths.yaml:58` already declares `/tools_soc` a
forbidden internal prefix.

**Decisions confirmed with user:**
- Boost/OpenSSL: prefer adequate host-installed libraries, else download+build locally.
- RISC-V toolchain: **strip `/tools_soc` entirely** (PATH + `RISCV_TOOLCHAIN` env only).
- **Harden `configure_vp.sh`** in tt-oca-sim too (commit on `cmccoy/harness_repo_port_fixups`).
- **No internal tooling paths AT ALL in the open repo — `/opt/rh` included.** A native
  builder is expected to provide a C++20-capable GCC themselves (activated in their
  shell / `CXX=`). SCL-toolset convenience becomes a Tenstorrent-internal-only wrapper
  script living in internal documentation, never in this repo.

## Critical files

- `virtual_platform/Makefile` — steps 1–4 (the bulk)
- `virtual_platform/sepvp/paths.py`, `sepvp/pytest_plugin.py` — RISC-V default mirror
- `virtual_platform/README.md` — requirements rewrite
- `virtual_platform/tt-oca-sim/vp/configure_vp.sh` (+ sw run scripts, README) — submodule commit

## Step 1 — Remove the SCL toolset entirely; ambient compiler + check-cxx (Makefile + sepvp)

**Delete** `GCC_TOOLSET`, `ACTIVATE`, and every `$(ACTIVATE)` recipe line: recipes use
the ambient `$(CXX)`/PATH. Native builders bring their own C++20-capable GCC (their
shell activates it; internal users get a TT-internal wrapper script via internal docs —
NOT shipped in this repo; draft text in the "Internal-docs deliverable" section below).

New `.PHONY: check-cxx` target: probe
`echo 'int main(){return 0;}' | $(CXX) -std=c++$(CXX_STD) -x c++ - -o /dev/null`;
on failure print the effective compiler (`command -v $(CXX)`, `--version | head -1`)
and distro-generic fixes: install g++ ≥ 10 (`apt install g++`; on RHEL install and
activate a gcc-toolset in your shell, e.g. `scl enable gcc-toolset-12 bash` — no
`/opt/rh` literal anywhere), or `CXX=/path/to/g++`, or build in the container
(`make vp VP_CONTAINER=1`). GCC 8.5 rejects `-std=c++20` → correct failure on bare
RHEL8. Attach `check-cxx` as an **order-only** prereq to the four dep sentinel recipes,
the configure sentinel, and `vp-build`. Keep the GCC-13/14 VeeR-ISS caveat as a
version-based (not SCL-based) comment.

**Ripple into sepvp (all `/opt/rh` and toolset plumbing removed):**
- `paths.py`: `vp_env()` loses the `gcc_toolset` parameter and the
  `/opt/rh/.../lib64` LD_LIBRARY_PATH insurance — it returns `dict(os.environ)`
  (the caller's activated environment is the contract now).
- `pytest_plugin.py`: drop the `--gcc-toolset` option; `SepVpHarness(...)` call and
  `vp` fixture lose the `gcc_toolset` argument.
- `sepvp_harness.py` / `harness.py` / `cli.py`: remove the `gcc_toolset` parameter and
  any `--gcc-toolset` CLI arg end-to-end.
- `tests/sim/test_spi_*.py`, `tests/bootcode/test_bootcode_ot_negative.py`: their
  `_env(request)` helpers call `paths.vp_env()` with no argument.
- `ENV_SCRIPT_BODY` (generated setup_environment.sh): remove the `/opt/rh` sourcing
  block — the script now documents "activate your C++ toolchain before sourcing" in a
  comment instead.

## Step 2 — Boost/OpenSSL prefix resolution (Makefile)

Precedence per dep: **explicit override** (`BOOST_ROOT`/`OPENSSL_ROOT` env/cmdline; set
EMPTY to force re-resolution) → **complete existing `local/` install** (keeps CCI↔Boost
ODR pairing; keeps existing checkouts no-op) → **adequate system `/usr`** (only with
`VP_SYS_DEPS=auto`, the default; `VP_SYS_DEPS=0` forces hermetic) → **build into `local/`**.
On a fresh clone on a capable host, system libs win — the user's intent. SystemC/CCI:
always `local/` unless overridden.

Mechanics (GNU-make semantics validated by the Plan agent):
- Branch on `ifeq ($(strip $(BOOST_ROOT)),)` — NOT `$(origin)` — and assign with
  `override BOOST_ROOT :=` so `make vp BOOST_ROOT=` (command-line-empty) re-resolves
  instead of leaving garbage paths. `$(origin)` used only for the "why" label.
- Adequacy probes live inside the not-local+auto conditional branch → untaken branches
  aren't expanded, so a built checkout (this box) runs **zero** `$(shell)` probes.
  - OpenSSL: `/usr/include/openssl/{ssl.h,core_names.h}` both exist (the actual ≥3.0 test).
  - Boost: `sed` BOOST_VERSION from `/usr/include/boost/version.hpp` ≥ `BOOST_MIN ?= 107400`
    (1.74, oldest accepted C++20-clean) AND link test
    `echo 'int main(){return 0;}' | $(CXX) -x c++ - -lboost_iostreams -lboost_program_options -o /dev/null`.
  - Escape `#` as `\#` in non-recipe lines; `$$` for sed anchors/shell vars.
- **Sentinels**: local prefixes use the last-installed artifact
  (`lib/libboost_program_options.a`, `lib64/libssl.a` — robust vs kill-9 corpses; verified
  both exist on this box and predate `vp/build/Makefile`, so no spurious rebuild);
  explicit/system prefixes keep probe-file sentinels (`include/...`).
- **`/usr` hazard fix**: tarballs + `$(LOCAL_DIR)` become **order-only** prereqs of every
  dep sentinel (pure existence semantics) so a `/usr` sentinel can never be "out of date"
  vs a fresh tarball and trigger `b2 install --prefix=/usr`. Same for CCI's
  SystemC/Boost sentinel prereqs. Optional belt-and-braces: dep recipes refuse `/usr`.
- **`deps-info`** target + `DEPS_INFO` define echoing each resolved prefix with its why
  (`already built in local/` / `system install (...)` / `will build from source (...)` /
  `explicit (environment|command line)`); also echoed by the configure recipe.
- **Config stamp + auto-wipe**: `.vp-config-stamp` (content = the 4 prefixes + CXX_STD +
  the effective compiler fingerprint `$(CXX)-$(shell $(CXX) -dumpversion 2>/dev/null)` +
  STATUS_VALUES_PATH, rewritten only on change, `FORCE`-driven) becomes a
  normal prereq of the configure sentinel; recipe wipes `vp/build` before reconfiguring
  when the cache exists. Migration branch: if no stamp but `vp/build/Makefile` exists,
  write the stamp with `touch -r vp/build/Makefile` (equal mtime ⇒ no retrigger — make
  rebuilds only on strictly-newer). `clean` also removes the stamp.

## Step 3 — RISC-V toolchain: strip `/tools_soc` (Makefile + sepvp)

- `RISCV_TOOLCHAIN ?=` (empty default) with comment: leave unset when
  `riscv64-unknown-elf-gcc` is already on PATH; ROM/DV builds fall back to the
  ocah-toolchain container regardless.
- **Fix the empty-value guard bug** in all three consumers (`FW_ENV`, `ENV_SCRIPT_BODY`,
  `smoke`): with an empty var, `[ -d "$(RISCV_TOOLCHAIN)/bin" ]` tests `/bin` (exists!)
  and prepends `/bin`. Change to `if [ -n "$(RISCV_TOOLCHAIN)" ] && [ -d ".../bin" ]`.
- `sepvp/paths.py`: drop `DEFAULT_RISCV_TOOLCHAIN`; add
  `default_riscv_toolchain() -> str: return os.environ.get("RISCV_TOOLCHAIN", "")`.
- `sepvp/pytest_plugin.py`: `--riscv-toolchain` default = `paths.default_riscv_toolchain()`
  (gains env-var support the Python side lacked); `_fw_env` guards empty:
  `tc = ...getoption(...); if tc and (Path(tc)/"bin").is_dir(): prepend`.

## Step 4 — Small fixes while touching (Makefile/README)

- Boost recipe: add `cxxflags=-fPIC cflags=-fPIC \` (matches tt-oca-sim ci-rhel8.yml).
- Help text: `/tools_soc` example → generic `/path/to/...`; document `deps-info`,
  `VP_SYS_DEPS`, `BOOST_MIN`, `BOOST_ROOT=` (empty = re-resolve), `RISCV_TOOLCHAIN`.
- `README.md` requirements rewrite: a C++20-capable compiler on PATH (g++ ≥ 10;
  activate it yourself — e.g. a RHEL gcc-toolset via `scl enable`; 13/14 VeeR-ISS
  caveat; or use `VP_CONTAINER=1`); Boost ≥ 1.74
  (iostreams, program_options) and OpenSSL ≥ 3.0 from the system when adequate, else
  built into `local/` automatically (`VP_SYS_DEPS=0` = hermetic); SystemC/CCI always
  local; RISC-V via PATH or `RISCV_TOOLCHAIN`; no internal mounts required.

## Step 5 — Submodule hardening (tt-oca-sim, own commit on `cmccoy/harness_repo_port_fixups`)

`vp/configure_vp.sh`: `find_prefix` gains an adequacy-check function argument
(SystemC/CCI pass `true`):
- `vp_boost_ok PREFIX`: only when `CMAKE_CXX_STANDARD == 20`, require
  `BOOST_VERSION >= ${VP_BOOST_MIN:-107400}` from `version.hpp` (17-standard builds keep
  old behavior).
- `vp_openssl_ok PREFIX`: `-e $1/include/openssl/core_names.h`.
Apply to both the env-provided value (warn with found-vs-floor, keep "probing anyway"
behavior) and the candidate loop (skip inadequate candidates; error text gains
"need Boost >= 1.74 (C++20) / OpenSSL >= 3.0"). Harness configure recipe additionally
exports `VP_BOOST_MIN=$(BOOST_MIN)` so the floors can't drift.

Same commit (consistent with "strip /tools_soc"): remove the `/tools_soc` probe entries
from `sw/sep-vp-tests/run_sep_vp_tests.sh:92` and `sw/smc-vp-tests/run_smc_vp_tests.sh:96`
(PATH + the other portable probes remain), and fix `README.md:622`'s
`/tools_soc` export example to a generic path.

## Step 6 — docker-run.sh bug fixes (prerequisites for the container mode)

Three verified bugs in `scripts/docker-run.sh`:
1. `PODMAN_RUN_FLAGS = ""` (spaces around `=`) in the docker branch is not a bash
   assignment — under `set -euo pipefail` the script aborts on **docker-only hosts**
   (exactly the "user with container ability" audience). Fix: `PODMAN_RUN_FLAGS=""`.
2. `ensure_image()` runs `"$ENGINE" ... image ${PODMAN_RUN_FLAGS} inspect ...` →
   `podman image --userns=keep-id inspect`, rejected; with `2>/dev/null` the label check
   always mismatches → image re-loaded/rebuilt every invocation. Fix: drop the run flag
   from the inspect call.
3. `bwrap_run` lacks `--die-with-parent` — a pexpect `terminate()` of the outer bwrap
   can orphan a never-terminating `sep-vp` holding the pty. Fix: add `--die-with-parent`.

## Step 7 — `ocah-vp-toolchain` image (new Dockerfile, second image)

The existing `ocah-toolchain` image has NO C++ compiler/cmake/git/wget; extending it
would invalidate its dockerfile-sha and force firmware rebuilds for everyone
(AGENTS.md warns about this). So: **new** `tools/docker/Dockerfile.vp` → image
`ocah-vp-toolchain`, same `debian:trixie-slim` base, containing:
- Native C++ toolchain: `g++` — try trixie default (g++ 14) first at implementation
  time (tt-oca-sim's Ubuntu CI passes on g++ 13, so the VeeR-ISS 13/14 breakage may be
  RHEL-SCL-specific); if VeeR-ISS fails, fall back to `g++-13`/`g++-12` from the archive
  with `CXX` set in the image. `cmake`, `make`, `autoconf` (SystemC configure).
- Deps from apt (adequate per Step-2 checks: Boost 1.83 ≥ 1.74, OpenSSL 3.5 ≥ 3.0):
  `libboost-iostreams-dev libboost-program-options-dev libboost-log-dev libssl-dev
  zlib1g-dev`. SystemC/CCI still build from source in-container (into the tagged
  local dir, Step 8); hence `wget ca-certificates git`.
- RISC-V firmware toolchain (same as the fw image): `gcc-riscv64-unknown-elf
  picolibc-riscv64-unknown-elf` — so in-container pytest can build the boot ROM
  natively (the plugin's `_native_fw_toolchain` probe then passes inside → no nested
  container; composes cleanly).
- Runner Python from apt (host `.venv` is unusable in-container — dangling
  `/usr/bin/python3.11` symlink): `python3 python3-pexpect python3-pytest python3-yaml
  python3-pyelftools python3-toml`, plus `python3-cryptography python3-ruamel.yaml`
  for the tt-boot-manifest packer (uv-less PACK_RUN fallback, Step 9).

`scripts/docker-run.sh`: add `vp-run` / `vp-shell` (and image build/ensure) subcommands
that select `IMAGE=ocah-vp-toolchain` + `Dockerfile.vp` — generalize `ensure_image`/
`build` minimally over (image, dockerfile). bwrap gate: `OCAH_VP_TOOLCHAIN_ROOTFS`
(probe `usr/bin/g++` instead of riscv gcc) so engine-broken hosts (like this one,
keep-id busted) get the engine-less path for the VP image too.

## Step 8 — Environment-tagged artifacts + `VP_CONTAINER=1` routing (Makefile)

Container-built and host-built artifacts must not mix (glibc 2.41 vs 2.28; libstdc++
ABI; CMake cache pins compiler paths; `local/*.so` RUNPATHs). Partition by tag:
- `VP_ENV_TAG ?= $(if $(wildcard /run/.containerenv /.dockerenv),ctr,)` (auto-detect,
  explicitly overridden by the routing wrapper anyway). Native default = empty tag →
  paths unchanged (`local/`, `vp/build`) — zero impact on existing checkouts.
- `LOCAL_DIR := $(VP_DIR)/local$(VP_TAG_SUFFIX)`; `VP_BUILD_DIR :=
  $(VP_SRC_DIR)/build$(VP_TAG_SUFFIX)`; config stamp, ENV_SCRIPT similarly tagged.
  `DOWNLOAD_DIR` stays shared (tarballs are host-independent).
- `VP_BUILD_DIR` override requires the submodule one-liner in `configure_vp.sh`:
  `BUILD_DIR="${BUILD_DIR:-${VP_DIR}/build}"` (env-honoring; its .gitignore already
  lists `build_17/build_20/build_smc` — multi-build-dir usage is anticipated). Lands
  in the same submodule commit as Step 5. Harness configure recipe exports
  `BUILD_DIR=$(VP_BUILD_DIR)`.
- **`VP_CONTAINER=1`** knob (explicit opt-in, native stays default): top of Makefile,
  when set and not already inside a container, re-invoke the same goal via
  `$(DOCKER_RUN) vp-run make -C virtual_platform $(MAKECMDGOALS) VP_ENV_TAG=ctr
  PYTHON=/usr/bin/python3 ...` (make vars passed on the command line — podman forwards
  NO environment). Applies to `vp`, `deps`, `vp-test`, `boot-run`, `fw-run`, `smoke`,
  `vp-clean`. `check-cxx`'s error message gains the hint: "or build in the container:
  make vp VP_CONTAINER=1". vp.mk targets pass `VP_CONTAINER`/vars through (MAKEFLAGS
  propagation covers command-line vars).

## Step 9 — Runner-in-container wiring

With build+run both in-container, pexpect runs INSIDE (no pty/buffering issue — that
only afflicts host-pexpect→podman-child). The repo's single 1:1 bind covers all Python
dirs, SEP sources, ELFs, and `virtual_platform/logs/` (the user's "mounted volumes").
- `vp-test`/`boot-run`/`fw-run` recipes export `SEP_VP_BIN=$(SEP_VP_BIN)` before
  invoking python/pytest — `paths.sep_vp_bin()` already honors it, so the tagged
  `build-ctr/bin/sep-vp` is found without touching paths.py logic.
- In-container `PYTHON=/usr/bin/python3` (apt deps replace the venv); `vp-py-deps`
  (uv sync) skipped when the import-check passes — existing recipe logic already does
  this. `_fw_env`'s venv-bin PATH prepend is harmless in-container.
- `secure_boot_preload` (uv-based packer): bootrom Makefile's `PACK_RUN` gains a
  guarded uv-less fallback (`command -v uv` absent → `PYTHONPATH=<tt-boot-manifest>
  python3 -m tt_boot_manifest.pack_images`, exact layout verified at implementation;
  apt `python3-cryptography`/`python3-ruamel.yaml` supply its deps). If that proves
  fragile, fallback position: the fixture's existing graceful skip in-container,
  documented.
- README: new "Containerized build & run" section — `./scripts/docker-run.sh vp-run
  make -C virtual_platform vp` / `make vp VP_CONTAINER=1` / `vp-shell`;
  `OCAH_VP_TOOLCHAIN_ROOTFS` for engine-less hosts; note container-built binaries are
  container-only (glibc), artifacts live in `local-ctr/`/`build-ctr/`.

## Commit structure

1. tt-oca-sim (submodule, on `cmccoy/harness_repo_port_fixups`): configure_vp.sh
   adequacy checks + BUILD_DIR override + `/tools_soc` removals (Steps 5, 8).
2. Harness: docker-run.sh bug fixes (Step 6) — standalone, independently revertable.
3. Harness: Makefile native portability (Steps 1, 2, 4) — guarded ACTIVATE, check-cxx,
   prefix resolution, deps-info, stamp, fPIC, help/README.
4. Harness: RISC-V default strip (Step 3, Makefile + sepvp).
5. Harness: container mode (Steps 7–9) — Dockerfile.vp, docker-run.sh vp-* subcommands,
   VP_ENV_TAG partitioning, VP_CONTAINER routing, PACK_RUN fallback, README.
6. Harness: submodule pin bump to the Step-1 commit (only after it is pushed).

## Verification

1. **This box (must stay a no-op, from a toolset-activated shell — e.g.
   `scl enable gcc-toolset-11 bash` or `CXX=` pointing at it, which is now the user's
   responsibility)**: `make -C virtual_platform deps-info` → all four `local/...` with
   `[already built in local/]`; `make vp` → stamp-adoption fires once, no reconfigure,
   nothing rebuilds; `make ocah-vp-test` → 36 passed / 1 skipped.
   Also grep-gate: `grep -rn "/tools_soc\|/opt/rh" virtual_platform/ --include='*' `
   (excluding tt-oca-sim/) returns **zero** hits after the change.
2. **Bare-environment compiler check**: from a NON-activated shell (ambient g++ 8.5),
   `make -C virtual_platform check-cxx` → fails the `-std=c++20` probe with the clear
   distro-generic error (install g++ ≥ 10 / CXX= / VP_CONTAINER=1).
   Decision-logic check without building: in a scratch copy without `local/`,
   `make deps-info BOOST_MIN=100000` → Boost flips to `/usr` (1.66 ≥ floor) while
   OpenSSL stays "build from source" (no core_names.h) — both branches exercised.
3. **Arbitrary-env proof (Ubuntu 24.04 container, podman non-keep-id works here)**:
   rsync repo copy (exclude `local/`, `downloads/`, `vp/build`; include `.git`);
   `apt-get install g++ cmake make git wget ca-certificates libboost-iostreams-dev
   libboost-program-options-dev libssl-dev zlib1g-dev`; `make deps-info` → Boost/OpenSSL
   = `/usr` (system), SystemC/CCI local; `make systemc cci` (only two tarballs download);
   `make vp`; run `bin/sep-vp --help` (exercises program_options) + `ldd` shows system
   `libboost_*`/`libssl`. Fallback if container networking blocks apt: rely on
   tt-oca-sim's ci.yml precedent + verification 2's decision-logic checks.
4. configure_vp.sh hardening: in the container (or with env roots unset on this box),
   standalone `./configure_vp.sh` on RHEL8 must now reject `/usr` Boost 1.66 /
   OpenSSL 1.1.1 with the clear floor message instead of accepting them.
5. **Container mode (this box, bwrap backend — podman keep-id is broken here)**:
   `./scripts/docker-run.sh vp-run true` via podman fails as expected → extract the
   vp image rootfs, set `OCAH_VP_TOOLCHAIN_ROOTFS`, then:
   `make -C virtual_platform vp VP_CONTAINER=1` → inside the sandbox `deps-info` shows
   Boost/OpenSSL = `/usr` (trixie apt), SystemC/CCI → `local-ctr/`; builds
   `build-ctr/bin/sep-vp`; native `local/`+`vp/build` untouched (`git status` clean,
   host `make vp` still a no-op afterward).
   `make -C virtual_platform vp-test VP_CONTAINER=1` → pytest runs in-container on apt
   python3.13, `SEP_VP_BIN` resolves to `build-ctr`, boot ROM builds with the image's
   riscv toolchain; expect ≥ the native pass set (secure-boot negative suite passes via
   the PACK_RUN fallback, or skips gracefully if the fallback was deferred).
   Then verify host-mode isolation: native `make ocah-vp-test` still 36 passed/1 skipped.
6. docker-run.sh bug fixes: `bash -n` + shellcheck pass; `ensure_image` no longer
   re-loads on every call (second invocation is a fast no-op); docker-only path parses
   (simulate: `PATH` without podman → script reaches docker branch without aborting).

## Internal-docs deliverable (NOT shipped in the repo)

Hand this wrapper to internal documentation for TT build servers (replaces the removed
in-repo SCL logic); users run `tt-vp-env make -C virtual_platform vp` or activate once
per shell:

```bash
#!/bin/bash
# tt-vp-env — Tenstorrent-internal: run a command under the SCL GCC toolset and
# with the site RISC-V toolchain. Lives in internal docs only.
set -euo pipefail
source /opt/rh/${TT_GCC_TOOLSET:-gcc-toolset-11}/enable
export RISCV_TOOLCHAIN=${RISCV_TOOLCHAIN:-/tools_soc/opensrc/riscv-gnu-toolchain/2025.01.20-rhel-8.10}
exec "$@"
```

## Notes / future work (do not implement now)

- `Boost_NO_BOOST_CMAKE=ON` vs `CMP0167 NEW` — latent break on CMake ≥ 3.30/4.x.
- Local OpenSSL recipe pins `linux-x86_64` (non-x86_64 hosts get system-OpenSSL path only).
- `clean`/`scratch-build` may flip a capable host from local to system deps — intended,
  loudly reported by `deps-info`/configure echo.

---

## OUTCOME (2026-08-20) — implemented and verified

Harness commits (branch `inmcm/remove_internal_path_dependencies`):
`625c7c5c` docker-run.sh bug fixes · `67e43464` ambient toolchain + system-or-local
Boost/OpenSSL · `30e37eca` RISC-V strip (incl. compile.mk prefix/tools-dir unification and
bwrap RISCV_TOOLCHAIN unset) · `59d451b3` containerized build & run mode.
tt-oca-sim commits (branch `cmccoy/harness_repo_port_fixups`, **unpushed**):
`6c77c04` configure_vp.sh adequacy checks + BUILD_DIR override + /tools_soc removals ·
`d1a6b69` VeeR-ISS Memory.hpp `<string>` include.

Verified:
- Grep-gate: zero `/tools_soc` or `/opt/rh` hits in the harness VP flow.
- Native (this box, toolset-activated shell): deps-info all-local, `make vp` no-op with
  stamp adoption, check-cxx fails clearly on bare g++ 8.5, suite 36 passed / 1 skipped.
- Resolution branches: system Boost accepted at lowered floor while OpenSSL correctly
  rejected (RHEL8); VP_SYS_DEPS=0 hermetic; standalone configure_vp.sh now rejects
  /usr Boost 1.66 / OpenSSL 1.1.1 with floor-naming errors.
- Container mode (bwrap backend; keep-id podman broken on this box): ocah-vp-toolchain
  builds (2.44 GB, Debian trixie); `VP_CONTAINER=1` builds sep-vp against apt Boost
  1.83/OpenSSL 3.5 (SystemC/CCI in local-ctr/); **in-container suite 36 passed /
  1 skipped — parity with native**, including the boot ROM via the image's riscv
  toolchain and the negative suite via the uv-less PACK_RUN fallback; native trees
  untouched (native suite still 36/1 afterward). The trixie container doubles as the
  arbitrary-environment proof (distro packages, ambient g++ 14).
- BONUS: the historic g++ 13/14 VeeR-ISS failure is fixed at the root (Memory.hpp
  `<string>`); Tlb.cpp verified compiling under RHEL gcc-toolset-13 AND -14 — the
  compiler constraint is now simply g++ >= 10.

Remaining, in order:
1. Push tt-oca-sim `6c77c04` + `d1a6b69` to origin/cmccoy/harness_repo_port_fixups.
2. Commit the submodule pin bump in the harness (gitlink currently uncommitted).
3. Hand the `tt-vp-env` wrapper (above) to internal documentation.
