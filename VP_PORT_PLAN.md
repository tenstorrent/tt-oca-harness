# Port `feature/sep_virtual_platform` from tt-oca-hw → tt-oca-harness

## Context

`tt-oca-hw` (`/localdev/cmccoy/dev/tt-oca-hw`) is locked; development moved to `tt-oca-harness`
(`/localdev/cmccoy/dev/tt-oca-harness`), which holds the same code reorganized. The
`feature/sep_virtual_platform` branch in the old repo adds an integrated SEP virtual platform:
the `tt-oca-sim` submodule, a Makefile-based VP build (SystemC/Boost/OpenSSL/CCI + CMake `sep-vp`),
the `sepvp` Python runner package, and pytest suites (SEP boot ROM, OT-SPI negative, SPI mux/DMA,
fuse-map units). Porting it lets the new repo use the functional model for SW dev and testing.

**Branch inventory (verified):** 14 commits, 31 files, ~3900 lines — all new files except one
`-MMD` dep-tracking hunk in the old bootcode Makefile. Port the tip state, not the 14 commits.
Target branch `feature/sep_virtual_platform` already exists in tt-oca-harness at `main` (072c42cd);
`virtual_platform/` exists untracked with a stub README.

**Decisions confirmed with user:**
- All pytest suites centralize under `virtual_platform/tests/` (single rootdir).
- Python deps via root `pyproject.toml` `[dependency-groups] vp`; `sepvp` stays un-installed
  (sys.path bootstrap — the "no pip install -e" lock from `VP_RELOCATION_PLAN.md` carries over).
- `test_fw_sep.py` ports against the DV fw engine's `hello_world` (xfail if VP coupling mismatches).
- Status table = checked-in `hw/sys/sep/bootrom/prod/include/status_values.h` (tt-oca-sim's
  decoder accepts C `#defines` — verified in `sep/peripherals/sep_scratch_cold/CMakeLists.txt:161`).
  Do NOT port `meta/status/`.
- `ocah.mk` integration via `-include` (user-specified, nonfree pattern).
- Drop `build_sep_vp_scratch.sh` (superseded reference script) and `requirements.txt`.

## Target layout (old → new)

| Old (tt-oca-hw branch) | New (tt-oca-harness) |
|---|---|
| `fw/deps/tt-oca-sim` submodule | `virtual_platform/tt-oca-sim`, pinned `ea90afa3c95c8cdecbafd8a45d956620de65650d` |
| `fw/tools/virtual_platform/Makefile` | `virtual_platform/Makefile` (re-anchored) |
| `fw/tools/virtual_platform/.gitignore` | `virtual_platform/.gitignore` (verbatim) |
| `fw/tools/virtual_platform/sepvp/*` (9 files) | `virtual_platform/sepvp/*` (paths.py + pytest_plugin.py edited; rest prose-only fixes) |
| `fw/tools/virtual_platform/tests/{test_fuses.py,fuse_maps/}` | `virtual_platform/tests/{test_fuses.py,fuse_maps/}` (verbatim) |
| `fw/sep/bootcode/tests/{test_bootcode.py,test_bootcode_ot_negative.py,shared.py}` | `virtual_platform/tests/bootcode/` |
| `fw/sep/tests/{test_spi_mux_flash.py,test_spi_dma_stream.py}` | `virtual_platform/tests/sim/` (verbatim — paths derive from SIM_DIR) |
| `fw/sep/tests/test_fw_sep.py` | `virtual_platform/tests/fw/test_fw_sep.py` (repointed at DV engine) |
| 2× conftest.py + 2× pytest.ini | one `virtual_platform/conftest.py` + `virtual_platform/pytest.ini` |
| `fw/sep/bootcode/Makefile` `-MMD` hunk | re-applied to `hw/sys/sep/bootrom/prod/Makefile` |
| — | new `virtual_platform/vp.mk` fragment + `-include` in `ocah.mk` |

No `__init__.py` in tests dirs (preserves bare `import shared` via pytest prepend import mode).

## Implementation steps / commit series

Work in `/localdev/cmccoy/dev/tt-oca-harness` on `feature/sep_virtual_platform`.

### Commit 1 — `[VP] Add tt-oca-sim submodule and virtual-platform build system`

1. Add submodule:
   ```
   git submodule add git@github.com:tenstorrent/tt-oca-sim.git virtual_platform/tt-oca-sim
   git -C virtual_platform/tt-oca-sim fetch origin cmccoy/sep_status_code_build_time_support
   git -C virtual_platform/tt-oca-sim checkout ea90afa3c95c8cdecbafd8a45d956620de65650d
   git -C virtual_platform/tt-oca-sim submodule update --init --recursive
   ```
   Record `branch = cmccoy/sep_status_code_build_time_support` in `.gitmodules` — the pin is on an
   unmerged upstream branch (a landing prerequisite to note in the commit message / PR).
2. Port `virtual_platform/Makefile` from `fw/tools/virtual_platform/Makefile` with re-anchoring:
   - `OCAH_ROOT := $(abspath $(VP_DIR)/..)` (was `OCH_ROOT`, 3 levels up)
   - `SIM_DIR := $(VP_DIR)/tt-oca-sim` (submodule now inside VP dir)
   - `PYTHON ?= $(OCAH_ROOT)/.venv/bin/python` (was `venv/`); add `UV ?= uv`
   - `BOOTCODE_DIR := $(OCAH_ROOT)/hw/sys/sep/bootrom/prod`
   - `STATUS_VALUES_PATH ?= $(BOOTCODE_DIR)/include/status_values.h` → passed as
     `-DSEP_SCRATCH_COLD_STATUS_VALUES_PATH` in the configure rule
   - `FW_ENV`: drop `OCH_ROOT`/`RV_ROOT`/`SNAPSHOT` exports (nothing in the harness consumes them —
     verified: bootrom Makefile and bl1_pass_test are self-contained); keep venv-bin + RISC-V
     toolchain PATH prepends
   - `boot-build:` → `$(MAKE) -C $(BOOTCODE_DIR) ot-toolchain-images` (NOT `all` — `pack-images`
     needs uv + tt-boot-manifest submodule the ELF doesn't need)
   - new `boot-secure-image:` → `$(MAKE) -C $(BOOTCODE_DIR) secure_boot_spi`
   - `fw-run:` builds via `$(MAKE) -C $(OCAH_ROOT) dv-fw-tests TARGET=sep TEST=$(FW_TEST)` and runs
     `hw/sys/sep/dv/fw/build/tests/$(FW_TEST)/$(FW_TEST).tcm.elf`
   - `vp-py-deps:` → `cd $(OCAH_ROOT) && $(UV) sync --inexact --group vp` (`--inexact` so a prior
     dv-group sync isn't stripped)
   - `vp-test:` single pytest invocation: `cd $(VP_DIR) && $(PYTHON) -m pytest tests $(PYTEST_ARGS)`
   - `submodule-init:` → `git -C $(OCAH_ROOT) submodule update --init --recursive virtual_platform/tt-oca-sim`;
     `check-tt-oca-sim` tests `$(SIM_DIR)/vp/configure_vp.sh` (empty dir ≠ initialized) and points
     at `make ocah-vp-init`
   - Drop `BUILD_TYPE` plumbing to the ROM make (new ROM Makefile hardcodes `-DTEST_BUILD=1 -DDEBUG`;
     passing it only churns the flags stamp). Keep gcc-toolset-11 sourcing, dep-build targets,
     sentinels, overridable `SYSTEMC_HOME/BOOST_ROOT/OPENSSL_ROOT/CCI_HOME` as-is.
3. Port `.gitignore` verbatim; flesh out `virtual_platform/README.md` from `sepvp/README.md` content
   with updated paths/commands.

### Commit 2 — `[VP] Add the sepvp runner package and pytest harness plugin`

4. Copy `sepvp/` package; edit `sepvp/paths.py`:
   ```python
   VP_DIR = SEPVP_DIR.parent                 # .../virtual_platform
   OCAH_ROOT = VP_DIR.parent                 # repo root (was OCH_ROOT, 3 parents)
   SIM_DIR = VP_DIR / "tt-oca-sim"
   BOOTCODE_DIR = OCAH_ROOT / "hw" / "sys" / "sep" / "bootrom" / "prod"
   BOOTCODE_ELF = BOOTCODE_DIR / "build_ot" / "boot_rom.elf"
   SECURE_BOOT_PRELOAD = BOOTCODE_DIR / "build" / "secure_boot.spi_preload"   # generated, was prebuilt/
   FW_TEST_BUILD_DIR = OCAH_ROOT / "hw" / "sys" / "sep" / "dv" / "fw" / "build" / "tests"
   def fw_test_elf(name): return FW_TEST_BUILD_DIR / name / f"{name}.tcm.elf"
   ```
   Drop `FW_SEP_DIR`; downstream (`VP_BUILD_DIR`, `CONFIG_DIR`, `DEFAULT_BASE_INI`, `VEERISS_CONFIG`,
   `LOGS_DIR`) derives automatically. Grep-verified: no other module references `OCH_ROOT`.
5. Edit `sepvp/pytest_plugin.py`:
   - `_fw_env`: drop `OCH_ROOT/RV_ROOT/SNAPSHOT`; keep venv-bin + `--riscv-toolchain` PATH prepends
   - `bootcode_elf` fixture builds `ot-toolchain-images`
   - new session fixture `secure_boot_preload`: builds `secure_boot_spi`, skips with a clear message
     if tt-boot-manifest submodule/uv missing, returns `paths.SECURE_BOOT_PRELOAD`
   - `fw_test_builder` builds via `-C <OCAH_ROOT> dv-fw-tests TARGET=sep TEST=<n>`, returns
     `paths.fw_test_elf(n)`
   - keep `--build-type` option/marker gating; stop passing `BUILD_TYPE=` to make
6. New `virtual_platform/conftest.py` (rootdir-level):
   ```python
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path(__file__).resolve().parent))
   pytest_plugins = ["sepvp.pytest_plugin"]
   ```
   New `virtual_platform/pytest.ini`: `[pytest]` / `addopts = -ra -v` / `log_cli = false`.
7. Root `pyproject.toml`: add group
   ```toml
   vp = ["pexpect>=4.8", "pyyaml>=6.0", "pytest>=7.0", "toml>=0.10", "pyelftools>=0.29"]
   ```
   Regenerate `uv.lock` (`uv sync --inexact --group vp`).

### Commit 3 — `[VP] Port the VP pytest suites`

8. Copy suites per the layout table. Edits:
   - `test_bootcode_ot_negative.py`: replace module-level `PRELOAD = ...prebuilt...` with the
     `secure_boot_preload` fixture; validate tamper offsets (`OFF_PAYLOAD_LEN=600`,
     `OFF_PAYLOAD_OFFSET=1160`, slots 0x1000/0x41000) against
     `hw/sys/sep/bootrom/prod/configs/secure_boot_test.yaml` on first run
   - `test_fw_sep.py`: `VP_SAFE_TESTS` → DV-engine `hello_world` + its actual banner string
     (read the source under `hw/sys/sep/dv/fw/tests/hello_world/` for the exact printf);
     xfail with a follow-up note if the VP mailbox/TCM coupling mismatches at runtime
   - drop dead `sys.path.insert` shims in moved tests; fix stale path prose (e.g. `shared.py`
     docstring's `meta/status/...` reference → the bootrom header)

### Commit 4 — `[SEP ROM] Add header dependency tracking to the prod boot ROM build`

9. `hw/sys/sep/bootrom/prod/Makefile` (only shared-file change; equivalent of old 2e0281984):
   add `-MMD -MP` to `CFLAGS`, and `-include $(OBJS:.o=.d)` after the `$(OBJS): $(FLAGS_STAMP)` rule.

### Commit 5 — `[VP] Hook the virtual platform into ocah.mk as an optional fragment`

10. New `virtual_platform/vp.mk` — thin delegation fragment (the standalone Makefile uses
    `.ONESHELL`/`.DEFAULT_GOAL`/`SHELL` overrides that must not leak into root make context):
    - `ifndef ocah_vp_mk` guard; `## @section SEP Virtual Platform` help comments
    - targets `ocah-vp-init` (submodule update --init --recursive), `ocah-vp-deps`, `ocah-vp-build`,
      `ocah-vp-test`, `ocah-vp-boot-run`, `ocah-vp-clean` — each `$(MAKE) -C $(OCAH_ROOT)/virtual_platform <target>`
    - `OCAH_PHONY += ...` (root Makefile auto-generates short aliases `vp-build` etc.)
11. `ocah.mk`: after the `include .../fw.mk` line, before `help.mk`:
    ```make
    -include $(OCAH_ROOT)/virtual_platform/vp.mk
    ```

## Verification (end-to-end, in order)

1. `git submodule status virtual_platform/tt-oca-sim` → ` ea90afa3...` (initialized at pin).
2. **VP build, fast bring-up:** reuse old repo's built deps:
   `make -C virtual_platform vp SYSTEMC_HOME=/localdev/cmccoy/dev/tt-oca-hw/fw/tools/virtual_platform/local/systemc-3.0.2 BOOST_ROOT=.../boost-1.84.0 OPENSSL_ROOT=.../openssl-3.3.2 CCI_HOME=.../cci-1.0.2`
   → check configure log echoes `SEP_SCRATCH_COLD_STATUS_VALUES_PATH: .../status_values.h`; binary at
   `virtual_platform/tt-oca-sim/vp/build/bin/sep-vp`.
3. `uv sync --inexact --group vp`; then from `virtual_platform/`:
   `../.venv/bin/python -c "from sepvp import paths; print(paths.OCAH_ROOT, paths.SIM_DIR, paths.BOOTCODE_ELF)"`.
4. **Fuses units first** (cheap plumbing check): `../.venv/bin/python -m pytest tests/test_fuses.py` → 18 pass.
5. **Boot ROM:** `git submodule update --init hw/sys/sep/bootrom/prod/tools/tt-boot-manifest`;
   with riscv toolchain + `.venv/bin` on PATH: `make -C hw/sys/sep/bootrom/prod ot-toolchain-images`
   and `secure_boot_spi`.
6. **Boot-run smoke:** `make -C virtual_platform boot-run BOOT_ARGS="--boot primary"` — decoded
   `SEP_MSG_*` names prove the status table baked (`SEP_MSG_UNKNOWN` ⇒ reconfigure via `vp-clean`).
7. **Full suite:** `make ocah-vp-test` (through the fragment). Expected: bootcode 6 pass + 1 skip
   (`test_full_boot_to_bl1`), negative 5 pass, spi mux 2 + dma 1 pass, fw_sep 1 pass (or xfail),
   fuses 18 pass. `make help` shows the `SEP Virtual Platform` section.
8. **Final clean validation:** copy the 4 dep tarballs from the old `downloads/` (wget may be
   firewalled), then `make -C virtual_platform scratch-build` (~1–2 h) so `local/` is self-contained —
   the bring-up overrides would otherwise leave sep-vp's RPATH pointing into the locked repo. Re-run
   step 7.

## Known risks

- **Submodule pin `ea90afa3` is only on unmerged `cmccoy/sep_status_code_build_time_support`** —
  fresh clones/CI fail to init until it merges upstream. Mitigated by `branch =` in `.gitmodules`
  and a PR note; merging that tt-oca-sim branch is a landing prerequisite.
- Negative-suite tamper offsets may differ under the new packer config — fix constants from
  `configs/secure_boot_test.yaml` if the first run fails.
- `test_fw_sep.py` DV-engine ELF on the VP is unvalidated (mailbox address / TCM link layout) —
  degrade to skip/xfail, never a red run.
- gcc-toolset-11 required (13/14 break VeeR-ISS compile); present on this box.

## Key reference files

- Source of truth for old content: `git show feature/sep_virtual_platform:<path>` in tt-oca-hw
- `tt-oca-hw/VP_RELOCATION_PLAN.md` — prior locked decisions
- `tt-oca-harness/ocah.mk` — fragment/include conventions; `help.mk` scraping
- `tt-oca-harness/hw/sys/sep/bootrom/prod/Makefile` — ROM build contract (`ot-toolchain-images`,
  `secure_boot_spi`, `ensure-pack-deps` submodule guard to imitate in `check-tt-oca-sim`)
- `tt-oca-harness/hw/common/dv/fw/fw.mk` — DV fw engine dispatcher (`dv-fw-tests TARGET=sep`)

---

## OUTCOME (2026-08-19) — port complete

7 commits on `feature/sep_virtual_platform` (8a639e48..91e4b5b8). Final verification:
`make ocah-vp-test` → **35 passed, 1 skipped** (test_full_boot_to_bl1, needs a staged
PTOC manifest), **1 xfailed** in 1:49. Boot-run smoke reaches SEP_MSG_PRIMARY_CHIPLET
with fully decoded status names. sep-vp built against fresh local/ deps (self-contained,
no old-repo RPATH). fw_sep's DV-engine hello_world runs and PASSES on the VP.

Deviations / discoveries vs the plan:

1. **picolibc**: the harness ROM + DV fw engine compile with --specs=picolibc.specs,
   which /tools_soc toolchains lack. Firmware builds now auto-fall back to the
   ocah-toolchain container (scripts/docker-run.sh run-here) in both the VP Makefile
   (fw_make) and sepvp.pytest_plugin (_make). On this box rootless podman's
   --userns=keep-id is broken (three distinct failures), so the image rootfs was
   extracted to /localdev/cmccoy/ocah-toolchain-rootfs and OCAH_TOOLCHAIN_ROOTFS
   selects docker-run.sh's engine-less bwrap backend. Export it in your shell:
   `export OCAH_TOOLCHAIN_ROOTFS=/localdev/cmccoy/ocah-toolchain-rootfs`
   (~/.config/containers/storage.conf also gained an explicit driver="overlay").
2. **Generated secure_boot.spi_preload ships a valid backup slot** (old prebuilt had an
   erased one) — both_bad/payload_too_large crafters now corrupt the backup too.
3. **Strap-layout gap (follow-up needed in tt-oca-sim)**: the VP @ ea90afa3 drives
   recovery LO[19] / bl0_pll_clk LO[20] / rotate HI[26] (internal post-reorg layout);
   the open ROM reads HI[23]/HI[24]/HI[29]. Only primary_chiplet + status_report_disable
   are plumbed. test_recovery_strap is a strict xfail until tt-oca-sim matches the open
   ROM (or makes the bits configurable).
4. **Landing prerequisite**: the tt-oca-sim pin ea90afa3 lives only on the unmerged
   upstream branch cmccoy/sep_status_code_build_time_support (recorded as `branch =`
   in .gitmodules) — merge it upstream before CI/fresh clones rely on submodule init.

### Strap-gap fix (2026-08-19, later)

Fixed in tt-oca-sim locally: commit `97280a4` on `cmccoy/sep_status_code_build_time_support`
(on top of origin's `b718844`) flips recovery/pll/rotate back to HI[23]/HI[24]/HI[29] in
vp/platform/sep/{src/sep_platform.cpp,sep_platform.hpp} — undoing the 3bac66aa remap by hand
(a literal revert can't apply; the code moved out of och_sep_ss.hpp in the platform-layout
refactor). Rebuilt sep-vp; full suite now **36 passed, 1 skipped** (xfail removed from
test_recovery_strap in the working tree).

Pending, in order: (1) push tt-oca-sim `97280a4` to origin; (2) commit in tt-oca-harness the
submodule pin bump (ea90afa3 -> 97280a4) together with the test_bootcode.py xfail removal.
Do not commit the pin bump before the push — it would reference an unpushed SHA.

### Resolution (2026-08-19, final)

Strap fix pushed as tt-oca-sim `0fd65a3` on `cmccoy/harness_repo_port_fixups`; harness
pin bumped (`e21b6b68`), xfail removed, negative-test fixups landed (`c9d9bec3`), and
`.gitmodules` branch hint repointed at the fixups branch (`f0f7b529`). Full suite at the
committed state: **36 passed, 1 skipped**. Remaining: merge `cmccoy/harness_repo_port_fixups`
into tt-oca-sim main before CI/fresh clones depend on the pin.

---

## Outcome — repo rename to `tt-oca-harness-model`, pinned to `main` (2026-08-25)

The VP submodule moved from `github.com/tenstorrent/tt-oca-sim` to
`github.com/tenstorrent/tt-oca-harness-model`. GitHub still redirects the old URL, but the
submodule was re-registered under the new name rather than left on the redirect.

### Wiring
- `.git/modules/virtual_platform/tt-oca-sim` moved to `.../tt-oca-harness-model` (86 MB of
  objects preserved, no re-clone); `core.worktree` and `remote.origin.url` rewritten, plus
  the nested `sep/utils/csml` module's `core.worktree`.
- Old gitlink `git rm --cached`'d, stale `submodule.virtual_platform/tt-oca-sim.*` config
  dropped, new gitlink staged at `main` = `5fbff5d1`.
- Path references renamed in `virtual_platform/{Makefile,vp.mk,README.md}`,
  `sepvp/{paths,config,harness,sepvp_harness}.py`, `tests/sim/*`. `check-tt-oca-sim` target
  is now `check-tt-oca-harness-model`. Zero `tt-oca-sim` hits remain outside these plan files.

### `main` vs the old pin `6168b3e5`
All four port fixups landed in `main` (rebased, so different SHAs): `48fea68b` configure_vp.sh
hardening, `7dbe3bf3` boot straps, `ea90afa3` build-time status table, `6168b3e5` VeeR-ISS
`<string>`. **The strap-layout gap is closed** — `984f91ed` aligns the model's SW strap bits
with this repo's ROM (`boot_recovery` HI[23], `bl0_pll_clk` HI[24], `rotate_update` HI[29],
matching `sep_smc_interface.h`), and `test_recovery_strap` now passes on its own merits.
New since the pin: the Adams Bridge SEP model (builds clean; `enable_language(C)` for PQClean).

### Regression found and fixed: the SPI backdoor became opt-in
`3ad3cce2` replaced the implicit raw-binary fallback

    if (spiPreload non-empty) {...} else { load_memory_from_file(); }  // data/flash_memory.bin

with an explicit `spiBackdoorFile` CCI param — `load_memory_from_file()` now *requires* a
path. The harness relied on the implicit default: it commented `spiPreload` out of the staged
base config and dropped the image at `<run_dir>/data/flash_memory.bin`. Under `main` the
flash was therefore **never loaded**, so every manifest read hit erased 0xFF.

That broke 3 tests and, worse, made 2 others pass for the wrong reason
(`both_bad` / `payload_too_large` expect `MANIFEST_LOAD_FAILED`, which is also what an empty
flash produces). Fixes:
- `sepvp_harness.py::_abs_path_overrides` now emits `och_sep_ss1.spiBackdoorFile` (absolute)
  whenever `SimConfig.flash_image` is set; stale docstrings corrected.
- `test_spi_mux_flash.py`: the unstaged case asserted a `"not found"` no-op line that no
  longer exists (the loader isn't called at all). Now asserts the loader logged *nothing*,
  which is the same assertion against current behaviour.

Verified: `ot_neg_hash_tamper` loads 275472 bytes and reports `SEP_MSG_INVALID_MANIFEST_HASH`;
`payload_overlap` reports `SEP_MSG_PAYLOAD_OVERLAPS_MANIFEST`.

### Suite status
Native, gcc-toolset-11, `OCAH_TOOLCHAIN_ROOTFS` bwrap backend, host RISC-V toolchain
`/tools_soc/opensrc/riscv-gnu-toolchain/2025.01.20-rhel-8.10`:

| model pin | result |
|---|---|
| `main` before the fix | 4 failed, 32 passed, 1 skipped |
| old pin `6168b3e5` | **1 failed, 35 passed, 1 skipped** |
| `main` after the fix | **1 failed, 35 passed, 1 skipped** — parity |

`main` is exonerated: the sole remaining failure reproduces identically at the old pin.

### Remaining (not model-attributable)
1. `test_ot_manifest_negative[rotate_to_backup]` fails at **both** model pins: the rotate and
   backup-slot selection work, then RSA verification rejects the slot —
   `RSA_PKCS1_FAIL` / `RSA_VERIFY_FAIL` / `CRYPTO_FAIL=0x0003000c` /
   `SEP_MSG_REVOKED_KEY`. This case is the one that needs a genuinely valid signature, so it
   points at ROM/manifest signing on `inmcm/uprev_sep_rom_dependencies`, not at the model.
   Also fails with `tt-boot-manifest` rolled back to its committed pin `b2d628fa`, so it is
   not the manifest-spec uprev either.
2. `secure_boot_spi` needs a **host** RISC-V toolchain (`container_ok=False`), unlike the boot
   ROM, which uses the toolchain container. Without one, 5 OT-negative tests skip rather than
   fail — a silent coverage hole worth closing.
3. The submodule pin bump is staged but uncommitted, as is the `.gitmodules` rename.
