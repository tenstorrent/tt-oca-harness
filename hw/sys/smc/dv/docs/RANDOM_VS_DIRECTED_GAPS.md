<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC / SMU cocotb — should-random but written directed

**Repo:** `tt-oca-harness`  
**Recorded:** 2026-08-13  
**Updated:** 2026-08-13 (fixes landed; see §7)  
**Scope:** enrolled cocotb tests under `hw/sys/smc/dv` and `hw/sys/smu/dv`  
**Criterion:** contract/docs/source claim **RANDOMIZED** (or randomized stimulus), but test+seq have **no stimulus RNG** (`random.Random` / `randint` / `choice` / `getrandbits`, etc.).  
Base-only `randomize_timing(seed)` does **not** count as stimulus random.

---

## 1. Confirmed gaps (should random → written directed)

> **Status 2026-08-13:** items in §1 were fixed (seeded knobs from `RANDOM_SEED`). Historical table kept for audit trail; live status in §7.

### SMC

| Test | Testlist | Evidence it should be random | Actual implementation |
|------|----------|------------------------------|------------------------|
| `smc_clk_multi_window_test` | `testlists/clock.toml` | `docs/smc_oss_execution_guide.md`: *picks 8 random window sizes per seed*; inventory `CG-CTRL-PARAMS.S1` / `S3` `method: RANDOMIZED` (`tb/SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md`) | Fixed `HYST_MIN/MID/MAX = 8/31/63` in `seq_lib/smc_clk_multi_window_test_seq.py` |
| `smc_dma_cg_activity_test` | `testlists/clock.toml` | Seq emits `"method": "RANDOMIZED"` coverage report; inventory `DMA-CG.S2` / `S4` (+ `CG-CTRL-PARAMS.S3`) `method: RANDOMIZED` | Fixed gap sweep `[0,1,32,63,64]` + fixed race hyst in `seq_lib/smc_dma_cg_activity_test_seq.py` |

### SMU fabric (arch says randomized traffic)

| Test | Testlist | Evidence | Actual |
|------|----------|----------|--------|
| `smu_axi_external_port_connectivity_test` | `testlists/fabric.toml` | `docs/SMU_TB_ARCH.md` Stimulus Strategy: *Fabric = Directed + randomized …* | Directed fixed addr/ID in seq |
| `smu_axi_id_width_conversion_test` | `testlists/fabric.toml` | same | Directed |
| `smu_axi_crossbar_error_handling_test` | `testlists/fabric.toml` | same | Directed |
| `smu_axi_atomic_operation_test` | `testlists/fabric.toml` | same | Directed |

### SMU infrastructure (timing random claimed, not delivered)

| Item | Evidence | Actual |
|------|----------|--------|
| Bare `--dut smu` `SmuEnvCfg.randomize_timing` | `cocotb/tests/smu_base_test.py` calls it; wrapper cfg **does** randomize | `cocotb/env/smu_env_cfg.py` is a **no-op** (`_ = seed`, Phase-1 placeholder) |

Bare enrolled tests with **no stimulus RNG** (also no timing random due to no-op):  
`smu_axi_*` (4), `smu_dtp_jtag_smoke_test`, `smu_dft_dtp_boot_stall_test`, `smu_dft_gpio_boot_stall_test`, `smu_clock_stop_coordination_test`, `smu_xtrig_ctm_remap_test`, `smu_sep_smoke_test`, `smu_jtag_reset_override_test`, `smu_boot_stall_jtag_cold_reset_matrix_test`, `smu_ic_reset_smc_multi_domain_test`, `smu_ic_reset_dual_domain_illegal_test`, `smu_boot_stall_vs_ic_reset_priority_test`, `smu_xtrig_ctm_illegal_phase_test`, `smu_ic_reset_ss_domain_matrix_test`, `smu_smc_smoke_test`, `smu_no_sep_configuration_test`, `smu_ext_boot_seq_gate_test`, `smc_reset_ctrl_test`, `smc_mailbox_int_test`, `smc_security_demote_pm_test` (23 total).

> Note: most of the 23 are **intentionally directed** scenarios; the infra gap is that seed/timing variety never applies. Only the fabric four + inventory/CG tests above are “should be random stimulus”.

---

## 2. OK reference (has stimulus RNG)

| Test | Notes |
|------|--------|
| `smu_dtp_bsr_extest_loopback_test` | Seeded `random.Random(seed ^ 0x0B52)` patterns on top of directed set |
| SMU wrapper `smu_wrapper_elaboration_*` | Uses `rng` for hold cycles; wrapper `randomize_timing` is live |
| SMC base path | All SMC tests get **timing** random via `SmcEnvCfg.randomize_timing` (not stimulus) |

---

## 3. Scan method (re-run)

```text
Enrolled = non-deferred [[tests]] in hw/sys/{smc,smu}/dv/testlists/*.toml
Stimulus RNG = import random / Random() / randint|choice|getrandbits in test.py or *_seq.py
“Should random” evidence =
  - inventory/docs method: RANDOMIZED or “randomized …” tied to test
  - source emits "method": "RANDOMIZED"
```

No additional enrolled cocotb test beyond §1 had RANDOMIZED/source claims without stim RNG (as of this record).

---

## 4. Out of scope / not gaps

- Names like `*_multi_sample_*`, `*_sweep_*`, `*_matrix_*` → usually **directed matrices**, not RNG contracts.
- Testlist `seed = 1` everywhere (no `reseed`) → runner default for single-sim; orthogonal to body RNG. SEP uses `reseed = 3` on some leaves; SMC/SMU do not.
- `testlists/deferred.toml` bodies not graded here.

---

## 5. Suggested fix order (completed 2026-08-13)

1. ~~`smc_clk_multi_window_test`~~ — seed-driven 8 windows (band min/mid/max + extras).
2. ~~`smc_dma_cg_activity_test`~~ — keep required gaps; add seed extras + race knobs; `RANDOM_SEED` in coverage JSON.
3. ~~SMU bare `randomize_timing`~~ — live clock/JTAG/settle from seed (was no-op).
4. ~~Fabric four~~ — seeded AXI IDs / wdata / settle timing.

---

## 6. Related paths

- SMC inventory: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md`
- SMC guide: `hw/sys/smc/dv/docs/smc_oss_execution_guide.md`
- SMU arch: `hw/sys/smu/dv/docs/SMU_TB_ARCH.md`
- SMU bare cfg: `hw/sys/smu/dv/cocotb/env/smu_env_cfg.py`
- SMU wrapper cfg: `hw/sys/smu/dv/cocotb_wrapper/env/smu_env_cfg.py`

---

## 7. Fix status + sim evidence (2026-08-13)

**Env:** `verilator/5.050` + `gcc/13.2.1` (5.046 fails nested PeakRDL codegen).

| Test | Seed | Result | Seed-driven proof in log |
|------|------|--------|---------------------------|
| `smc_clk_multi_window_test` | 1 | PASS | `min/mid/max=12/40/54 extras=[17,29,31,45,46]` |
| `smc_clk_multi_window_test` | 2 | PASS | `min/mid/max=9/45/63 extras=[15,16,43,48,53]` |
| `smc_dma_cg_activity_test` | 1 | PASS | `sweep=(0,1,32,63,64,62,36,14) race_hyst=32` |
| `smc_dma_cg_activity_test` | 2 | PASS | `sweep=(0,1,32,63,64,7,45,34) race_hyst=48` |
| `smu_axi_external_port_connectivity_test` | 1 | PASS | `WRITE_ID=0xd8` + timing `periph=12ns jtag=32ns` |
| `smu_axi_external_port_connectivity_test` | 2 | PASS | `WRITE_ID=0x56` + timing `periph=8ns jtag=40ns` |
| `smu_axi_id_width_conversion_test` | 1 | PASS | `arids=['0x5c','0x20','0x26']` |
| `smu_axi_atomic_operation_test` | 1 | PASS | `arid=0x6d` |
| `smu_axi_crossbar_error_handling_test` | 1 | PASS | `post_reset_cycles=57 jtag_period_ns=32` |

**Reproduce (single leaf):**
```bash
source setup_env.sh
module unload verilator; module load verilator/5.050 gcc/13.2.1
unset VERILATOR_ROOT
python3 tools/dv/run_dv.py --dut smc_wrapper --items smc_clk_multi_window_test \
  --tool verilator --stage flist --stage sim --seed 1
python3 tools/dv/run_dv.py --dut smu --items smu_axi_external_port_connectivity_test \
  --tool verilator --stage flist --stage sim --seed 2
```
