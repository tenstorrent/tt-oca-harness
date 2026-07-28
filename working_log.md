Open Tree — tt-oca-harness/hw
1. Production Boot ROM ported in (hw/sys/smc/bootrom/prod/)
The entire directory is new — ported from tt-oca-hw and cleaned up for open-source:

Makefile — standalone build, no -include nonfree/... reference. Exposes a NONFREE_DRIVER_SOURCES ?= hook variable so a downstream build can inject a strong-symbol driver without touching this file.
src/main.c — added #include <stdint.h> (picolibc IWYU hygiene) and an _exit stub (while(1) wfi) because picolibc, unlike newlib+libgloss, intentionally provides no _exit.
drivers/src/i3c_target_driver.c — open weak stub for the I3C target driver. Returns NULL/no-ops. The nonfree Cadence driver overrides this at link time.
drivers/include/i3c_target_driver.h — the interface contract any replacement driver must satisfy.
README.adoc — Hardware Integration section updated to describe the weak-hook architecture; all Cadence IP references and UG paths removed.
README.md — deleted (superseded by README.adoc).
2. OCCP DV firmware ported to the open tree (hw/sys/smc/dv/fw/)
Previously all OCCP code lived in nonfree/ because of its dependency on the Cadence I3C master driver. The separation is now clean:

New common/occp/ directory:

occp_commands.c/h — OCCP protocol command handlers
occp_interfaces.c — register access layer, fully cleaned: OCH-era naming shims removed, hardcoded 0x0u offsets replaced with static const uint32_t named constants, uses native open-tree register names (gpio_intf__DATA_CTRL_t, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0))
status_decode.c/h, sep_ring_buffer_model.c/h — supporting protocol utilities
i2c_controller_driver.h/.c — abstract I2C vtable interface + weak stub (__attribute__((weak)) I2C_GetDriverInstance)
i3c_controller_driver_stub.c — weak stub for the I3C master side (DV BFM tests)
occp_test_common.h — common test header wired to the open I3C interface header
New include/ headers:

i2c_controller_driver.h, i3c_controller_driver.h — abstract vtable interfaces
smc_defines.h — aggregates generated register headers; a comment */ glob-pattern bug that caused a C parse error was also fixed here
New startup/exit_stub.c — _exit stub for ROM-mode DV tests (content extracted from the old nonfree dv_rom_support.c).

New test directories moved from dv_rom/:

tests/occp_sanity/main.c
tests/occp_master/*.c
Both updated: SMC_CPU_CTRL_SCRATCH_0__REG_ADDR → SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0)
3. hw/sys/smc/dv/fw/fw.mk updated
OCCP source files added to FW_C_SRCS
startup/exit_stub.c added
common/occp and bootrom/prod/include added to FW_INCLUDES
FW_TEST_MODE_occp_sanity := rom and FW_TEST_MODE_occp_master := rom — OCCP tests declared as ROM-mode builds
FW_TEST_LDFLAGS_rom and FW_TEST_ARCHIVE_LINK_rom defined so ROM-mode uses --whole-archive to pull in crt0.S and _exit, while SRAM-mode keeps -Wl,-e,main -nostartfiles
The standalone dv_rom/Makefile was deleted — OCCP tests are now first-class entries in the standard ocah-dv-fw-tests TARGET=smc flow.

4. ocah.mk fixed
OCAH_ROOT changed from a lazy ?= assignment to a ifndef guard with := (immediate evaluation). This prevented OCAH_ROOT from being silently re-evaluated to a subdirectory path when ocah.mk was re-included from deep within the nonfree tree, which was corrupting all downstream path resolution.

5. README.md updated
Documented the OCCP tests as part of the standard dispatcher flow and clarified the ROM vs SRAM build modes.

Nonfree Repo
6. Cadence I3C target driver added (hw/sys/smc/bootrom/prod/drivers/src/i3c_target_driver_cdns.c)
The proprietary strong-symbol implementation that overrides the open weak stub at link time. Injected into the prod ROM build via NONFREE_DRIVER_SOURCES=.

7. dv_rom/Makefile reworked
exit_stub.c sourced from open tree ($(OPEN_SMC_FW_DIR)/startup/exit_stub.c) instead of the now-deleted dv_rom_support.c
OCCP test discovery updated to $(OPEN_SMC_FW_DIR)/tests/occp_*/main.c (new locations)
Links nonfree Cadence I3C master driver as strong symbol override of the open DV BFM stub
8. dv_rom/dv_rom_support.c deleted
Its only content (_exit stub) was promoted to hw/sys/smc/dv/fw/startup/exit_stub.c in the open tree.

9. Orphaned nonfree OCCP directory deleted
nonfree/hw/sys/smc/dv/fw/common/occp/ — this was the old proprietary copy of the OCCP files. With the open-tree migration complete, it was a dead duplicate and removed entirely.

10. project_smc_chiplet.yaml updated
DESIGNWARE_HOME/DESIGNWARE_PROJECT: ker → qsr — the root fix for the DesignWare VIP V-2024.03 path mismatch (the qsr project directory has amba_svt/V-2024.03 installed; ker does not)
cgen_cmd: uses make -f ocah.mk, passes NONFREE_DRIVER_SOURCES with the Docker-internal /work/nonfree/... path
FW_BOOT_ROM_BUILD_ROOT added to variables
11. setup_env.sh reworked
DESIGNWARE_HOME/DESIGNWARE_PROJECT unconditionally set to qsr (not :- default, so re-sourcing always wins)
VCS_HOME, VERDI_HOME explicitly exported, their bin/ directories prepended to PATH for the flist step
Loads python/3.9.18 (ships cerberus, gitlab, psutil — all ttem runtime deps)
Loads bender/0.28.1-tenstorrent8-mr_fixes and soc_tools
12. ROM_README.md added (nonfree/hw/sys/smc/bootrom/prod/)
Documents the full architecture: weak/strong symbol mechanism, what the open tree provides vs nonfree, standalone ROM Makefile paths, how NONFREE_DRIVER_SOURCES injection works, and how the regression eventually runs with the built ROM.

CI Pipeline — unblocking the SMC chiplet cgen + flist stages
The pipeline reached cgen but firmware compilation failed with `riscv64-unknown-elf-gcc: fatal error: cannot read spec file 'picolibc.specs'`. Root cause: the FW build uses --specs=picolibc.specs everywhere, and picolibc is only provided by the ocah-toolchain Docker image (Debian picolibc-riscv64-unknown-elf). None of the system RISC-V toolchains on the runners ship picolibc, and the Docker wrapper had been stripped from cgen_cmd earlier. Fix = build firmware inside the ocah-toolchain container, made self-provisioning so runners don't need registry access.

13. scripts/docker-run.sh — run-here subcommand
New firmware-image counterpart to eda-run: runs in ocah-toolchain but mounts the repo at its own host-absolute path (via run_image_1to1) instead of /work, so commands using absolute $OCH_ROOT / $NONFREE_ROOT paths (the TTEM cgen `make -C $OCH_ROOT ...` chain) resolve inside the container.

14. scripts/docker-run.sh — self-provisioning image cache (ensure/build)
The ocah-toolchain image is built locally and published to no registry, so a bare `run` on a fresh runner tried (and failed) to pull it: `docker.io/library/ocah-toolchain: requested access to the resource is denied`. Added:
ensure_image: reuse a matching local image (verified by an ocah.dockerfile.sha label) → else load a tarball from shared NFS → else build and publish. Auto-run by run/run-here/shell/verify, so `run` works on a fresh host with no registry access.
build_image: builds with the Dockerfile-hash label and publishes the tarball to the shared cache (publish failure is a warning, not a build failure).
Cache dir OCAH_DOCKER_CACHE_DIR (default /proj_soc_scratch_ps/socinfra/ocah-docker-cache), keyed by Dockerfile hash so a Dockerfile change forces a rebuild/new entry. Seeded the cache tarball from a dev build and set it group soc_users + setgid so any teammate/runner can re-publish. New `ensure` subcommand exposed; `build` case now routes through build_image.

15. project_smc_chiplet.yaml — cgen_cmd wrapped in the container
Each of the five make steps (ocah-dv-fw-tests, bootrom/dummy, bootrom/prod with NONFREE_DRIVER_SOURCES, ocah-nonfree-dv-fw-tests, dv_rom) is prefixed with `$OCH_ROOT/scripts/docker-run.sh run-here`, so firmware compiles pick up --specs=picolibc.specs from the image. Uses the committed docker-run.sh helper (not the phantom fw-toolchain-docker.sh the old cgen artifact referenced). With cgen passing, the pipeline advanced to flist.

16. project_smc_chiplet.yaml — flist stage decoupled from cocotb
flist failed with `make: *** No rule to make target 'filelist'`. The $TB_ROOT/Makefile symlink resolves to tb_wrap_cocotb/Makefile, which unconditionally `include`s cocotb's Makefile.sim; that runs find_libpython at parse time and aborts before the filelist target can run — cocotb is neither present nor needed just to generate a filelist. Changed the flist command from `cd $TB_ROOT && make filelist` to call ocah.mk generate_filelist directly (same bender EXTRA_TARGETS and FLIST_OUT=$TB_ROOT/tt_smc.f). Output is byte-identical to the committed tt_smc.f; regenerating leaves git status clean.

17. hw/sys/smc/bootrom/prod/Makefile — prod ROM disassembly step
With the prod ROM now built inside the container (container binutils 2.44 instead of the system riscv-gnu-toolchain), the DIS step crashed: `objdump -DCSsx prod_rom.elf` → Aborted (core dumped), Error 134, failing cgen. Isolated to the `-D` flag (disassemble ALL sections): `-d` and even `-dCSsx` exit 0, every `-D` combination aborts. binutils 2.44 objdump chokes on prod_rom.elf's NOBITS/.stack layout (same ELF that emits the harmless `section .stack/.bss can't be allocated in segment 4` linker warnings). Changed the DISASM recipe from -DCSsx to -dCSsx — disassembles code sections only (data-as-instructions is noise anyway) and avoids the crash. Full 5-step cgen chain then passes end-to-end in the container.
Follow-up (not blocking): the `.stack`/`.bss` "can't be allocated in segment 4" linker warnings point to a prod ROM linker-script PHDRS/segment issue worth cleaning up separately.

Note: items 13-14 and 17-18 (scripts/docker-run.sh, tools/docker/README.md, bootrom/prod/Makefile) live in the harness repo (branch nboettcher/enable_dv_env); items 15-16 and 19 (project_smc_chiplet.yaml) live in the nonfree repo (branch nboettcher/populate_smc_dv). Both repos must be committed for a green pipeline.

18. scripts/docker-run.sh — rootless podman CI-account-safe (runtime dir + --user)
CI cgen failed with `mkdir /run/user/<uid>: permission denied` (podman can't init on non-login CI accounts) and would next hit `setgroups: invalid argument` from `--user uid:gid`. Fixed in docker-run.sh: when `/run/user/<uid>` is unwritable, redirect XDG_RUNTIME_DIR/XDG_DATA_HOME to `/tmp/ocah-podman-<uid>`; default OCAH_DOCKER_UIDGID empty for podman (rootless already maps output ownership; `--user` trips runc on RHEL8), caller uid:gid for docker. Validated with faithful CI-account simulation — verify exit 0.

19. project_smc_chiplet.yaml — tt_smc.f path alignment for flist + compile
After cgen/flist passed, compile failed: VCS `Unable to open './tt_smc.f'`. Root cause: path confusion across stages — flist used a folded YAML block (`flist: >` with multiple lines) that could leave embedded newlines in the TTEM flist script, so `make` sometimes ran without FLIST_OUT and wrote `./tt_smc.f` under $OCH_ROOT instead of `$TB_ROOT/tt_smc.f`; compile then ran from `$OUT/compile_smc_chiplet` and resolved `./tt_smc.f` relative to that dir (not where flist wrote). Fix: (1) single-line flist command; (2) use `$NONFREE_ROOT/hw/sys/smc/dv/tb/tb_uvm/tt_smc.f` instead of `$TB_ROOT/tt_smc.f` in FLIST_OUT and compile filelists (NONFREE_ROOT always exported by setup_env.sh); (3) set `OUT: $NONFREE_ROOT/hw/sys/smc/dv/tb/tb_uvm/out` explicitly so compile artifacts land where ci.yml expects them.

20. project_smc_chiplet.yaml — PYTHONPATH for smc_dv_paths / cocotb
Sim failed: `ModuleNotFoundError: No module named 'smc_dv_paths'` loading MODULE=smc_cocotb. TTEM sim scripts export variables in alphabetical order; `PYTHONPATH=$TB_ROOT:...` was emitted before `TB_ROOT`, so on CI (when paths aren't fully pre-expanded into the script) `$TB_ROOT` expanded empty and tb_uvm dropped off PYTHONPATH — `smc_dv_paths.py` lives in tb_uvm/. Fix: `PYTHONPATH: $NONFREE_ROOT/hw/sys/smc/dv/tb/tb_uvm:$NONFREE_ROOT/hw/sys/smc/dv/tb/tb_wrap_cocotb` (NONFREE_ROOT exports before PYTHONPATH alphabetically, and is always set by setup_env.sh).

---

## SMC Regression Failure Triage (tt-oca-harness adaptation)

**Context:** When the SMC DV infrastructure was ported from `tt-oca-hw` to `tt-oca-harness`, 20/20 regression tests failed on first run. Root cause analysis identified three independent bugs in the testbench/bootrom adaptation — none in RTL. `tt-oca-hw` ran clean because it does not use `picolibc`, uses a different crt0, and its loader hardcodes the reset vector at the SRAM load base (which happened to be the correct entry point in that repo's linker configuration). The three changes below explain why each fix was needed *here* but not *there*.

---

### 21. smc_api.py — scratch register handle fix (`fix-handle`)

**File:** `nonfree/hw/sys/smc/dv/tb/tb_wrap_cocotb/common/smc_api.py`  
**Lines touched:** 766, 1093, 1097, 1106

**Root cause — vacuous ROM-pass sentinel:**
`init_and_reset()` and `load_and_run_binary()` both need to zero `scratch_0` before starting the CPU so that `monitor_test` does not immediately return `True` upon seeing the stale `0x77777777` written by the previous ROM boot. The clearing code was present but inoperative because the four scratch register assignments each appended `.value` to the `dut` hierarchy path before storing back:

```python
# BUG: evaluates the *integer* value of the signal, then assigns an int to a local
smc_scratch0_register = self.dut.u_smc_wrapper.u_smc_top.u_reg_block.SCRATCH[0].data.value
smc_scratch0_register.value = 0   # this mutates a Python int, not the simulator handle
```

Removing `.value` from the right-hand side gives a cocotb `LogicObject` handle; `.value = 0` on *that* object drives the simulator signal:

```python
# FIX: captures the handle, not the sampled integer
smc_scratch0_register = self.dut.u_smc_wrapper.u_smc_top.u_reg_block.SCRATCH[0].data
smc_scratch0_register.value = 0
```

**Why `tt-oca-hw` was unaffected:** The `tt-oca-hw` DV infra did not contain this `.value` pattern — the scratch handle was assigned directly without the extra `.value` dereference.

---

### 22. rom.c — remove custom `secondary_main` (`rom-hart`)

**File:** `hw/sys/smc/bootrom/dummy/rom.c`

**Root cause — all harts writing ROM-pass sentinel:**
`tt-oca-harness` links the boot ROM with `picolibc`, which ships its own `crt0.S` (from the SiFive Freedom Metal tree). That `crt0.S` calls `secondary_main()` for **every** hart (not just secondary harts) via the `_skip_init` branch. The dummy `rom.c` had a strong-symbol `secondary_main()` that unconditionally called `main()` → `test_rom_pass()` → wrote `0x77777777` to `scratch_0`. All four SMC harts therefore raced to write the sentinel, and the last write was whichever hart won — no ordering guarantee.

`tt-oca-hw` used a different (pre-picolibc, newlib-based) crt0 where `secondary_main` was called only for secondary harts; the boot hart went straight to `main()`. The semantics were therefore reversed and the dummy `rom.c` pattern happened to be correct in that environment.

**Fix:** Deleted the entire `secondary_main()` definition from `rom.c`. The `crt0.S` weak-default `secondary_main` dispatches only the boot hart (`mhartid == __metal_boot_hart`, which equals 1 on the SMC) to `main()` and sends all other harts to `wfi`. With the strong-symbol override gone, only one hart writes the sentinel.

```c
// rom.c after fix — no secondary_main() at all
int main(void) {
    /*
     * Only the boot hart (mhartid == __metal_boot_hart) reaches here.
     * The crt0.S weak-default secondary_main dispatches the boot hart to
     * main() and sends all other harts directly to wfi, so scratch_0 is
     * written exactly once and never re-dirtied.
     */
    test_rom_pass(0);
    return 0;
}
```

---

### 23. smc_utils.py / smc_binary_loader.py — ELF reset-vector fix (`harden-loader` / `pll-debug`)

**Files:** `nonfree/hw/sys/smc/dv/tb/tb_wrap_cocotb/common/smc_utils.py`  
         `nonfree/hw/sys/smc/dv/tb/tb_wrap_cocotb/tests/smc_binary_loader.py`

**Root cause — CPU entering infinite trap loop instead of `main()`:**
After fixes 21 and 22, `smc_pll_init_test` (and any SRAM-mode firmware test) still failed with a `SimTimeoutError`. Instruction traces showed all harts looping at `pc=0xc0060000` — the very first instruction of the SRAM region — instead of executing `pll_init`'s `main()`.

The mismatch comes from how SRAM-mode firmware is linked in this repo:

```makefile
# hw/sys/smc/dv/fw/fw.mk  (SRAM mode)
FW_TEST_LDFLAGS = ... -Wl,-e,main -nostartfiles ...
```

`-Wl,-e,main` sets `main` as the ELF entry point (`e_entry`). `-nostartfiles` suppresses `crt0`. The linker script still places `.text.metal.init.trapvec` (the `early_trap_vector` function from the Metal startup archive) at `SRAM_BASE` (0xc0060000) because it comes first in the section-ordering rules of `common.ldh`. `main()` is placed **after** that stub, typically at `SRAM_BASE + 0x300` = `0xc0060300`.

The testbench was calling:
```python
await tb.pulse_core_reset(cycles=18, reset_vector=sram_addr)   # 0xc0060000
```

The CPU reset vector was pointing at `early_trap_vector`, an infinite loop (`j early_trap_vector`). The firmware never reached `main()`.

**Why `tt-oca-hw` was unaffected:** In `tt-oca-hw`, the SRAM linker script does not include the Metal startup archive at all; `main` is the very first symbol in the `.text` section and therefore lands at `SRAM_BASE` itself. `reset_vector = sram_addr` is correct there.

**Fix:** Added a helper `elf64_entry(bin_path)` that reads the `e_entry` field (byte offset 24 in a little-endian ELF64 header) from the `.elf` counterpart of the `.bin` file. Both loaders now use that address as the reset vector:

```python
def elf64_entry(bin_path: str):
    """Return the ELF64 e_entry address, or None if the ELF can't be read."""
    elf_path = bin_path[:-4] + ".elf" if bin_path.endswith(".bin") else None
    if not elf_path or not os.path.exists(elf_path):
        return None
    try:
        with open(elf_path, "rb") as f:
            f.seek(24)   # ELF64 e_entry offset (little-endian)
            return struct.unpack("<Q", f.read(8))[0]
    except (OSError, struct.error):
        return None

# In load_and_run_binary / smc_binary_loader:
reset_vector = elf64_entry(bin_path) or sram_addr
await tb.pulse_core_reset(cycles=18, reset_vector=reset_vector)
```

`elf64_entry` returns `None` for ROM-mode binaries (no paired `.elf`) or any binary whose `.elf` can't be parsed; the `or sram_addr` fallback keeps ROM-mode tests working unchanged.

**Implementation note — `import *` and the underscore convention:**
The function was initially named `_elf64_entry` (private by convention). Python's `from module import *` does **not** export names with a leading underscore unless `__all__` is defined. Because `smc_binary_loader.py` imports `from common.smc_utils import *`, `_elf64_entry` was silently unavailable there, resulting in a `NameError` at runtime. The function was renamed to `elf64_entry` (no underscore) so it is exported by the star-import. Lesson: shared helper functions used across modules via star-imports must not carry a leading underscore.

**Verification result (`smc_pll_init_test`, 2026-07-28):**
With the renamed `elf64_entry` fix applied, the test completed with `TESTS=3 PASS=3 FAIL=0`. The ELF entry was resolved to `0xc0060300` and the CPU reset to `main()` correctly. All five PLL output clocks hit their target frequencies:

| Clock | Target | Measured | Δ |
|---|---|---|---|
| `smu_clk` | 800 MHz | 798.2 MHz | 0.22% |
| `smn_clk` | 400 MHz | 399.2 MHz | 0.21% |
| `noc_clk` | 1500 MHz | 1499.5 MHz | 0.03% |
| `periph_clk` | 200 MHz | 199.9 MHz | 0.07% |
| `dm_clk` | 2000 MHz | 2000.2 MHz | 0.01% |

---

### Redundant guards removed (harden-loader cleanup)

Two guards added during initial triage were later confirmed redundant once fixes 21 and 22 were in place and were removed to keep the code clean:

1. **Extra `scratch_0` clear in `load_and_run_binary`** — `init_and_reset()` (fix 21) already clears `scratch_0` via the corrected handle before `load_and_run_binary` is called. A second clear added to `load_and_run_binary` was redundant.
2. **`require_transition` parameter in `monitor_test`** — this guard prevented `monitor_test` from returning `True` if `scratch_0` already contained `TEST_ROM_PASS` before firmware execution started. Fix 21 makes `scratch_0` zero at that point, so the transition guard is unnecessary. It was removed and the logic is documented in `docs/smc_dv_future_improvements.md` for potential re-introduction if the sentinel-clearing invariant is ever broken.

---

### 24. PVT register model — real vendor RDL, vendor-aligned layout (`regen-pvt`)

**Files:** `nonfree/hw/sys/smc/dv/shims/regs/vendor/samsung/pvt/rdl/*.rdl` (wired in)  
        `nonfree/hw/sys/smc/dv/shims/regs/pvt_wrap.rdl` (deleted placeholder)  
        `nonfree/hw/sys/smc/dv/shims/regs/vendor/alpha_solutions/ts/temp_sensor.rdl` (moved)  
        `nonfree/hw/sys/smc/regs/gen/**` (regenerated)

**Root cause — 29 PVT/DROOP/TEMP mismatches in `smc_register_test`:**
The JSON register model was generated from a placeholder `pvt_wrap.rdl` that declared every register as `sw=rw; hw=r; value=0x0`. The RTL (`tt_combined_pvt_sensor_wrap.sv`) instantiates the real Samsung PROMISE / Movellus Droop / Alpha Solutions IP, whose registers have narrower writable fields and non-trivial reset values. The clearest example is `PROCESS_CTRL` at the PVT base: the placeholder modelled a full 32-bit RW register, while the real `combined_pvt_ctrl` map has only `process_enable[0]` and `process_sensor_sel[9:4]` — a writable mask of `0x3f1`, which is exactly the value the failing run read back.

**Fix:** Replaced the placeholder with the real vendor RDL and reorganised the shim tree so each map sits under its owning vendor:

| RDL | Owner | Location |
| --- | --- | --- |
| `pvt_wrap`, `combined_pvt_ctrl`, `temp_sensor_wrap`, `temp_sensor_ctrl` | TT-authored integration | `vendor/samsung/pvt/rdl/` |
| `droop` | Movellus | `vendor/movellus/droop/` |
| `temp_sensor` (`TS_remote`) | Alpha Solutions | `vendor/alpha_solutions/ts/` |

A byte-identical duplicate `droop.rdl` under `vendor/samsung/pvt/rdl/` was deleted. Both `droop.rdl` and `temp_sensor.rdl` are pulled in by bare `` `include ``, so they resolve through the `-I` search path and the move needs no source edits. Removing the duplicate also disambiguates `vendor/movellus/awm/awm_wrap.rdl`, which includes `droop.rdl` by the same bare name.

**Include-path precedence:** `generate_register_files.sh` collects include dirs sorted by path length descending (`awk '{print length, $0}' | sort -rn`), so the deep vendor path is searched before the shallow open-tree shim. The vendor `pvt_wrap.rdl` (staged `inc_2`) therefore wins over the open-tree placeholder still present at `hw/sys/smc/dv/shims/regs/pvt_wrap.rdl` (staged `inc_77`). This is deterministic but implicit — worth keeping in mind when adding shims.

**Verification after regeneration:**

- `smc_pvt_wrap` @ `0xc0007000`, size `0x948`, with `combined_pvt_ctrl@0x0`, `droop@0x400`, `temp_sensor_wrap@0x800` (and `temp_sensor_ctrl@0x900` nested inside).
- Generated absolute addresses in `smc_top_reg.svh` equal PVT base plus the relative offsets in the committed vendor `pvt_wrap_reg.svh` used by the RTL APB decode.
- `PROCESS_CTRL` writable mask is `0x3f1`, matching the RTL and the value observed in the failing run.
- PVT window now models 114 registers (was 73 placeholder entries); the mock `PVT_CTRL` name is gone.
- The `vendor/samsung/pvt/gen/sv` regblock RTL matches this RDL — `combined_pvt_ctrl_reg_pkg.sv` declares `PROCESS_CTRL__process_enable` as 1 bit and `PROCESS_CTRL__process_sensor_sel` as `logic [5:0]`.

The `rdlpyhdr.py` warning for `smc_top_addr.py` is pre-existing and flagged non-critical by the script itself.

**Regression result:** all three register tests pass with `UVM_ERROR: 0` / `UVM_FATAL: 0`, clearing the 29 PVT/DROOP/TEMP mismatches.

| Test | Result | Runtime |
| --- | --- | --- |
| `smc_register_test` | Pass | 3m01s |
| `smc_register_test_cold` | Pass | 5m21s |
| `smc_register_test_warm` | Pass | 3m10s |

56 distinct addresses in the PVT window were exercised, including `PROCESS_CTRL`; the remainder are read-only and are skipped by a write/read test ("no writable fields"), plus `combined_pvt_ctrl.DROOP_CTRL_STATUS` and `droop.SAMPLE_STROBE` which are on the explicit skip list.

Two notes for anyone repeating this:

1. **Run the tests sequentially.** Every `ttem` invocation in a given testbench directory writes the same `out/yaml/base_notab.yaml`. Launching the three tests in parallel concatenates three documents into that file and every run dies with `ComposerError: expected a single document in the stream`.
2. **The first pass ran against the pre-existing `compile_smc_chiplet` model.** The cocotb `register_test` reads `smc_top.json` at runtime, so the regenerated JSON takes effect without a recompile, and the RTL APB decode uses the committed vendor `pvt_wrap_reg.svh` that this change does not touch. That made the first run a clean comparison of new expectations against unchanged RTL.

**Fresh compile verification:** because the regenerated `smc_top_reg.svh` is compiled into the UVM testbench, `--stack flist,compile_smc_chiplet` was re-run from scratch. It passed in 3m16s with no errors and no PVT-, `smc_top_reg`-, `droop`- or `temp_sensor`-related warnings, confirming the new PVT constants elaborate cleanly. `smc_register_test` was then re-run against that fresh model and passed again (`UVM_ERROR: 0`, `UVM_FATAL: 0`, 56 PVT-window addresses exercised), closing the loop end to end.

---

### 25. Bucket 3 (`smc_rom_efuse*` hangs) — already fixed by 23, no new change needed

**Files:** none changed. Triage outcome only.

The four `smc_rom_efuse*` runs were bucketed separately from Bucket 1 because their ROM-wait legitimately completed (~166 µs of real BL0 ROM) before `load_and_run_binary` timed out on the full 10 ms. That made it look like the SRAM firmware was stalling for its own reason.

It was not. `rom_efuse_bits.sram.elf` puts `.rodata` first, **at** `SRAM_BASE`, and `.text` only at `SRAM_BASE + 0x40`:

```
Idx Name        Size      VMA
  0 .rodata     00000040  00000000c0060000   <- start_range_data / end_range_data
  1 .text       000000ba  00000000c0060040   <- main
start address                 0xc0060040
```

So the pre-fix `reset_vector = sram_addr` pointed the core at the two `const uint64_t[4]` lookup tables and it executed them as instructions. Sram images are linked `-nostartfiles -Wl,-e,main`, so there is no trap vector for the resulting exception to reach, and the core hung silently rather than reporting anything — a 10 ms timeout with no cocotb error.

This is the same root cause as fix 23 with a different offending section (`pll_init` had `.text.metal.init.trapvec` at `SRAM_BASE`; this test has `.rodata`). It is the reason `elf64_entry` reading the ELF `e_entry` is the right general fix instead of special-casing a section name — any image whose first section is not `main` hits this.

**Verification:** all three distinct tests pass against the fresh compile, ~2.5 min each.

| Test | eFuse bits | Result |
| --- | --- | --- |
| `smc_rom_efuse_bits_0_test` | 0 | Pass |
| `smc_rom_efuse_bits_1_test` | 1 | Pass |
| `smc_rom_efuse_test` | 0 (random seed) | Pass |

The firmware publishes each bank's start word low half through `scratch_1`, logged as `FW Status`: `0xcafed00d`, `0xf99bccdd`, `0xb4a59687`, matching `start_range_data[1..3]`. All three ROM banks read back correctly. The `bits=1` run returns the same un-swapped values as `bits=0`, so the hardware endian flip is working and the test is genuinely exercising it rather than passing trivially.

The ROM-side generation was also checked independently by running `rom_efuse_hex.py` by hand for both bit settings: the bank-boundary words land at hex word addresses `@1000/@1FFF`, `@2000/@2FFF`, `@3000/@3FFF`, which at 8 bytes per word are byte offsets `0x8000`/`0xFFF8`, `0x10000`/`0x17FF8`, `0x18000`/`0x1FFF8` — exactly the `bank_size * i` and `bank_size * (i+1) - 8` addresses the C code reads. SPM ROM is `0xC0040000` + `0x20000`, i.e. exactly four 32 KB banks, so every access is in range.

One latent hazard was found and left alone (it is recorded as item 6 in `docs/smc_dv_future_improvements.md`): this firmware writes ROM payload data into `scratch_0..3`, all four of which the testbench reserves — `scratch_0` is the terminal-status sentinel, `scratch_2` drives the virtual console. It passes today only because none of the payload values collide with a sentinel.

---

## combined_pvt_sanity firmware bugs (commit 75b36eb)

`smc_combined_pvt_sanity_test` (and `smc_security_demote_pm_test`, which also runs `combined_pvt_sanity.sram.bin`) failed with two overlapping issues.  Both were pre-existing firmware bugs that had been hidden by the earlier compile failures.

### Bug 1 – `prim_ag_clk_mux` CheckMutualExclusion RTL assertion at 1521268500000 fs

**Symptom:** VCS reported `CheckMutualExclusionClk0` / `CheckMutualExclusionClk1` both firing at the exact same sim time inside `u_tt_combined_pvt_sensor_wrap.process_obs_clk_postdiv.postdiv_mux`.

**Root cause:** The RTL path is:
```
PROCESS_CLK_OBS_CTRL.postdiv_use_postdiv (bit 12, reset-default = 1)
  → process_obs_postdiv_use_postdiv
    → prim_prog_clk_div_posedge.use_clk_div_i
      → prim_ag_clk_mux.i_sel
```
`prim_ag_clk_mux` (`prim_prog_clk_div_posedge.postdiv_mux`) selects between the undivided `process_obs_clk` (clk0) and a divided derivative (clk1).  Its `SelectOnReset=0` parameter means both synchronizer chains reset to "clk0 selected".  The `postdiv_use_postdiv` HW reset default of 1 means `i_sel=1` (select clk1) immediately after reset, so both `sel_sync_clk0` and `sel_sync_clk1` are transiently 1 during the initial switch.

The firmware exacerbated this by writing `0x1` and `0x3` to `PROCESS_CLK_OBS_CTRL`, which cleared bit 12 from 1 to 0, driving an *additional* unintended mux switch mid-operation.

**Fix:** Write `0x1001` / `0x1003` (preserving bit 12 = `postdiv_use_postdiv = 1`) so no spurious mux transition is triggered by the firmware.

### Bug 2 – DROOP_CTRL_STATUS register layout mismatch → infinite polling loop

**Symptom:** Firmware wrote post-code `0xc10c4` then timed out with `SimTimeoutError` at ~2017910 ns, stuck in the droop-ready polling loop.

**Root cause:** The `DROOP_CTRL_STATUS` RDL bit layout was misread in the original firmware:

| Bit | Field | SW access | Reset | Actual meaning |
|-----|-------|-----------|-------|----------------|
| 0 | `droop_reset_n_n0_scan` | rw | 0 | Active-low reset for droop detector |
| 4 | `droop_ready` | r (hw=w) | 0 | 1 once detector is active |
| 8 | `droop_underflow` | r (hw=w) | 0 | |
| 12 | `droop_overflow` | r (hw=w) | 0 | |

The original firmware had two mistakes:
1. Wrote `0x1000` as the "deassert reset" value — bit 0 was 0, so it **re-asserted** the droop reset
2. Polled `(status & 0x1u) == 0u` — checking `droop_reset_n_n0_scan` (bit 0) instead of `droop_ready` (bit 4, mask `0x10u`)

**Fix:** Corrected init sequence:
1. Write `0x0` → assert reset (bit 0 = 0)
2. Write droop `CONFIG_SETTING_*` registers
3. Write `DROOP_ENABLES = 0x1`
4. Write `0x1` to `DROOP_CTRL_STATUS` → deassert reset (bit 0 = 1)
5. Poll `(status & 0x10u)` for `droop_ready` (bit 4)