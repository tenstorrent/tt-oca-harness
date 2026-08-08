<!-- SPDX-License-Identifier: Apache-2.0 -->
# KM sideload KATs — parked pending a KM firmware fix

Parked 2026-08-04. Four tests are excluded from the `all` and `cpu` regression
groups in `testlists/all.toml`:

- `sep_km_otbn_sideload_kat_test`
- `sep_km_aes_sideload_kat_test`
- `sep_km_hmac_sideload_kat_test`
- `sep_km_kmac_sideload_kat_test`

Their leaf entries in `testlists/km.toml` are deliberately **kept**, so each test
still runs on demand:

```bash
python3 tools/dv/run_dv.py --dut sep --items sep_km_aes_sideload_kat_test
```

## Symptom

All four fail identically at `CMD_KEY_TRANSFER returned rc=-1`
(`ROM_KM_RC_FAILURE`, the generic code). This is **not** a scoreboard or CHK5
problem — the tests abort on a hard assert in `run_scenario` before `report()`
runs, so no scoreboard summary is produced.

## Root cause (KM firmware, not DV)

The KM never receives a single DRBG entropy beat — measured 0
`km_entropy tvalid && tready` handshakes over 200k cycles.

`rom_transfer_key` ends in `rom_<engine>_write_key(..., &rom_prng_state)`, which
needs 12 DRBG mask words via `rom_drbg_get_block()`. That function sets
`CFG.prefetch = 1` and then performs **blocking** `ROM_DRBG_DATA_REG` reads while
leaving `CFG.TIMEOUT` at its 256-cycle reset value. First entropy in this
integration takes roughly 78k cycles, so the read aborts long before a seed
arrives.

The contrast case is in-tree and confirms the mechanism: the hand-assembled
`cocotb/tests/km_fw/km_rom_entropy.S` disables the timeout by writing `CFG = 0`
first, and consequently **does** get KM beats.

## Where the fix has to go

The KM ROM firmware **is now in this repository** — `hw/ip/key_manager/dv/fw/`
arrived with the SEP/SMU/KM DV collateral port, and the offending function is
`hw/ip/key_manager/dv/fw/drivers/rom_drbg.c:59`:

```c
cfg.w = DRBG_CFG.w;
cfg.f.prefetch = 1;
DRBG_CFG.w = cfg.w;                    /* TIMEOUT left at its 256-cycle reset */
for (uint8_t i = 0; i < count; i++)
    buf[i] = ROM_DRBG_DATA_REG.w;      /* blocking */
```

(An earlier revision of this note said the fix could not be made from this tree.
That was true before the collateral port and is no longer true.)

**A SEP-side workaround is not available.** The obvious one — make sure entropy is
flowing before `CMD_KEY_TRANSFER` — is already done: each KAT calls
`bring_up_entropy()` and then asserts `wait_genbits()` before issuing the
transfer, so CSRNG genbits provably exist by that point. The stall is downstream
of that: the EDN→KM sampler only advances on a KM-CPU `DATA` read or an enabled
prefetch, so the first KM-side word still arrives far later than the 256-cycle
window the firmware leaves open. Nothing the SEP testbench drives can shorten it.

That leaves the firmware change: clear or raise `CFG.TIMEOUT` for the duration of
the blocking read, restoring it afterwards. **It needs KM-owner sign-off** — KM
ships `tests/test_drbg_timeout` and `tests/test_drbg_timeout_boundary` against
exactly this behavior, so the current timeout may be deliberate.

## Re-enable checklist

1. Confirm the KM firmware fix has landed and the rebuilt `rom_main.rom.parhex`
   is what the tests load.
2. Run each of the four tests individually by name on Verilator.
3. Confirm the KM entropy handshake is non-zero and the scoreboard reaches
   `report()` (CHK1–CHK4 strict, CHK5_km in `observe` mode — bit-exact CHK5_km is
   infeasible against `rom_main`).
4. Restore the four commented lines in both the `all` and `cpu` groups in
   `testlists/all.toml`, and delete this document.
