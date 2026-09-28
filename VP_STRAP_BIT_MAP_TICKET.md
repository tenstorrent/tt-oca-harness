# Drive the SEP boot straps to the bits the ROM reads

**Status:** proposed
**Area:** tt-oca-harness-model — `vp/platform/sep/src/sep_platform.cpp:351-355`, `vp/platform/sep/sep_platform.hpp:379`
**Raised:** 2026-09-22, from three failing `virtual_platform/tests/bootcode` tests

## Summary

The SEP VP writes three of the five modelled boot straps to the wrong strap
register bit, so the ROM never observes them. A test can set `boot_recovery` or
`rotate_update`, the VP will accept the parameter, and the ROM will read zero.

The ROM is self-consistent and the harness emits the right parameters; only the
VP's mapping disagrees.

## The mismatch

The ROM's map is documented in `hw/sys/sep/bootrom/prod/include/boot_straps.h`
and read in `boot_straps.c:23`; the VP drives the registers in
`sep_platform.cpp:351-355`.

| strap | ROM reads | VP drives | |
|---|---|---|---|
| `primary_chiplet` | `STRAPS_LO[25]` | `straps_lo |= 1u << 25` | correct |
| `status_report_disable` | `STRAPS_LO[21]` | `straps_lo |= 1u << 21` | correct |
| `boot_recovery` | `STRAPS_LO[19]` | `straps_hi |= 1u << 23` | **wrong register and bit** |
| `bl0_pll_clk` | `STRAPS_LO[20]` | `straps_hi |= 1u << 24` | **wrong register and bit** |
| `rotate_update` | `STRAPS_HI[26]` | `straps_hi |= 1u << 29` | **wrong bit** |

`sep_platform.hpp:379` also annotates `strap_boot_recovery` as `STRAPS_HI[23]`,
so the VP's comment and the ROM's header disagree in writing as well as in code.
`boot_straps.h` is the authority: it derives from the GPIO map, where
`STRAPS_HI[N]` is GPIO N+32.

## What it breaks

Three tests, all reproducible locally in ~3.5 minutes:

```
tests/bootcode/test_bootcode.py::test_recovery_strap
tests/bootcode/test_bootcode_oca.py::test_rotate_update_strap_selects_backup_first
tests/bootcode/test_bootcode_oca.py::test_smc_sram_recovery_strap_boots
```

`test_recovery_strap` shows the mechanism most clearly. The overlay sets both
straps:

```ini
och_sep_ss1.smc.primary_chiplet : true
och_sep_ss1.smc.boot_recovery   : true
```

`primary_chiplet` lands correctly, `boot_recovery` does not, so
`rom_main.c:764`'s `straps.primary_chiplet && straps.boot_recovery` is false.
The ROM takes the SPI branch instead, and `SEP_MSG_BOOT_RECOVERY` never appears
in the log (0 occurrences). The test stages no flash image — it has no reason to,
since recovery takes the manifest from SMC SRAM — so the SPI path then fails:

```
BL0 INFO   0x0212 SEP_MSG_MANIFEST_LOAD_START
BL0 WARN   0x0006 SEP_MSG_INVALID_MANIFEST_ID
BL0 INFO   0x0212 SEP_MSG_MANIFEST_LOAD_START
BL0 WARN   0x0006 SEP_MSG_INVALID_MANIFEST_ID
BL0 ERROR  0x0006 SEP_MSG_INVALID_MANIFEST_ID
BL0 ERROR  0x0213 SEP_MSG_MANIFEST_LOAD_FAILED
```

The harness aborts on the ERROR status while waiting for `BOOT_RECOVERY`, which
is why the failure reads as a status-pattern mismatch rather than a strap fault.

`rotate_update` fails the same way one level on: slot selection never rotates, so
`MANIFEST_BACKUP` never arrives and the test times out at 180 s.

`bl0_pll_clk` is mismapped too but nothing asserts it today. `test_rotate_update_strap`
passes only because, as its own docstring says, the ROM reports
`SEP_MSG_ROTATE_UPDATE` unconditionally and "the strap VALUE itself is not
asserted" — it proves the report point is reached, not that the strap took effect.

## Ruled out

- **Not the recent model bump.** The same three fail identically at `ecf862fb`
  and at `bc60912e`, with the ROM, OCA images and harness held fixed and only the
  VP binary rebuilt.
- **Not environmental.** Identical results on CI native, CI container, and a
  local host: 3 failed, 56-57 passed, 0 errors.
- **Not the fuse-preload error** that appears in these logs
  (`fuse_preload_file: cannot open ...`). It is present in all 59 run
  directories, including every passing one. Unrelated noise, though worth fixing
  separately so it stops looking like a cause.
- **Not the test setup.** The overlay `.ini` carries the correct
  `och_sep_ss1.smc.*` parameters; the VP accepts them and drives the wrong bits.

## Reproduce

```bash
cd virtual_platform
uv run --project .. --group vp --locked python3 -m pytest \
  tests/bootcode/test_bootcode.py::test_recovery_strap \
  tests/bootcode/test_bootcode_oca.py::test_rotate_update_strap_selects_backup_first \
  tests/bootcode/test_bootcode_oca.py::test_smc_sram_recovery_strap_boots \
  -q --no-build
```

Needs a built `sep-vp` and a built boot ROM. Inspect
`virtual_platform/logs/sepvp/boot_recovery/` for the overlay and the VP log.

## Fix

Move the three straps to the bits `boot_straps.h` documents: `boot_recovery` to
`STRAPS_LO[19]`, `bl0_pll_clk` to `STRAPS_LO[20]`, `rotate_update` to
`STRAPS_HI[26]`, and correct the `STRAPS_HI[23]` annotation on
`sep_platform.hpp:379`.

Worth deriving the VP's bit positions from a single shared definition rather than
restating them, since the two halves have now drifted silently. The ROM's
constants live in `hw/sys/sep/bootrom/prod/include/sep_smc_interface.h`
(`SMC_STRAP_*_BIT`), which is the natural source.

The three tests above are the acceptance check; they need no new coverage.
