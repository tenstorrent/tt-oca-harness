# sepvp — SEP virtual-platform firmware test harness

A Python runner + pytest harness for running SEP firmware on the `sep-vp` SystemC virtual
platform, with friendly control over boot straps, OTP fuses, and the SPI flash image, and a
pexpect-style `expect()` API over the platform's decoded stdout.

## Layout

```
sepvp/                 importable runner library
  paths.py             locate sep-vp, base config, firmware trees
  inifile.py           generate the per-run overlay .ini (stage base + override)
  fuses.py             fuse-map (YAML or RTL .toml) -> sep_efuse.* / lc_ctrl.lc_state overrides
  config.py            SimConfig (ELF, straps, OTP, SPI, channel toggles)
  harness.py           Harness base: expect / expect_status / finish
  sepvp_harness.py     SepVpHarness backend (overlay-gen, SPI staging, pexpect spawn)
  cli.py               `python -m sepvp.cli` interactive entry point
  pytest_plugin.py     shared pytest fixtures/options/markers (loaded by the test suites)
tests/                 all pytest suites: test_fuses (units) + fuse_maps/, bootcode/, sim/, fw/
```

All suites live under `virtual_platform/tests/` (one pytest rootdir), wired to this
harness via `sepvp.pytest_plugin` from the bootstrap `virtual_platform/conftest.py`:
boot ROM tests in `tests/bootcode/`, OT SPI mux/DMA tests in `tests/sim/`, DV-engine
firmware runs in `tests/fw/`.

## Quick start (from `virtual_platform/`)

```bash
make vp-py-deps                              # one-time: uv sync --inexact --group vp

# Bootcode on the production SEP_STATUS path:
make boot-run BOOT_ARGS="--boot primary --until SEP_MSG_PRIMARY_CHIPLET"
make boot-run BOOT_ARGS="--boot secondary --timeout 30"

# A hw/sys/sep/dv/fw test image (printf + VP PASS/FAIL marker):
make fw-run FW_TEST=hello_world

# The pytest suite:
make vp-test                                 # builds firmware, runs everything
make vp-test PYTEST_ARGS="--no-build -k bootcode"
```

Or drive the CLI directly:

```bash
python -m sepvp.cli --bin <elf> [--boot primary|secondary] [--recovery] [--rotate-update] \
    [--spi flash.bin] [--otp fuses.yaml] [--no-sep-status] [--until SEP_MSG_NAME] \
    [--timeout N] [--ini-only]
```

## Two decoded status channels (both land on sep-vp stdout)

- **`[SEP_STATUS]`** — production status (`report_status` → SMC-SRAM ring), always on, symbolic:
  `BL0 INFO 0x0044 SEP_MSG_BOOTROM_START`, with a leading
  `[<t>] [INFO 2] [SEP_STATUS] - ` or without it depending on the model
  generation -- the harness matches either. Assert with
  `harness.expect_status("SEP_MSG_...", type=..., fwid=...)`. Prefer this for stable boot-flow
  and error assertions. The symbolic names come from the checked-in bootrom header
  `hw/sys/sep/bootrom/prod/include/status_values.h`, baked into sep-vp at configure time.
- **`[SIM_OUT]`** — `simput*` debug console, **DEBUG firmware builds only**
  (`--build-type test`). Gate SIM_OUT-dependent tests behind the `needs_debug` marker.

Firmware test images print via firmware stdout; the VP decodes their pass/fail mailbox magic
to `[VP] SIMULATION OF THE TEST PASSED` / `... FAILED`.

## How control reaches the VP

`sep-vp <ini> [<elf>]` is the only CLI — no arbitrary param overrides. The harness writes a
per-run overlay `.ini` that `@include`s the staged base `accellera_config.ini` and then
re-states straps, fuses, channel toggles, and absolute `targets`/`names_tsv`/`configFile`
(the CSML parser chdir()s to the ini's dir, so those base-relative paths must be absolute).
Straps are `och_sep_ss1.smc.*` bools; OTP is translated from a fuse-map into
`och_sep_ss1.sep_efuse.*` (with the `lc_ctrl.lc_state` mirror); the SPI image is staged to
`<run_dir>/data/flash_memory.bin`. Each run gets its own dir under `logs/sepvp/<name>/`.

### Fuse-maps: `--otp` accepts two formats

`--otp` (and `SimConfig.otp`) dispatches on file extension:

- **`*.yaml` / `*.yml`** — the VP-native, hand-friendly map keyed by sep-vp field name
  (`lc_state: PROD`, `sboot_dis: 0`, `chiplet_uid: [1,...,8]`); see `tests/fuse_maps/`.
- **`*.toml`** — the same RTL/UVM eFuse config format the SEP testbench's efuse-preload
  generator consumes (keyed by hardware REGISTER, with `fields.<name>.value` and
  per-register `write_locked`/`read_locked`), so a single config can drive both RTL sim
  (`.preload` binary) and the VP (CCI params):

  ```bash
  python -m sepvp.cli --bin <elf> --otp <efuse_config>.toml
  ```

  The `.toml` path handles the RTL↔VP encoding differences automatically: LC_STATE is
  decoded from its differential byte (PROD `0xE1` → `0x1`), 64-bit `SiP_DIS`/`SYS_DIS`
  split into `*_lo`/`*_hi`, 256-bit tokens/keys split into little-endian 8-word arrays, and
  `locks_lo` is reconstructed from the per-register lock flags. Requires the `toml` package
  (in the `vp` dependency group; `make vp-py-deps`). Registers with no VP counterpart
  (`RESERVED_*`) are ignored.
