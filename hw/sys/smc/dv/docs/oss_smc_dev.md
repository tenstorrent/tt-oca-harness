<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS Test Porting Master Plan

| Field | Value |
|-------|-------|
| Scope | `hw/sys/smc/dv/cocotb/` (PyUVM-on-cocotb, DTP three-layer pattern) |
| Related | `SMC_VPLAN.adoc`, `smc_oss_execution_guide.md`, `ref_test_dev.md` |

This is the planning half of the SMC OSS bring-up. It records the module-to-test
mapping, the shared-infrastructure roadmap, and the design rules the ported tests
follow. For how to run the resulting suite and for per-slate sign-off evidence,
see `smc_oss_execution_guide.md`.

---

## 1. Scope & Goal

For each functional module, select representative scenarios that follow the DTP
test architecture (`env/` + `seq_lib/` + `tests/`) and share reusable
infrastructure.

---

## 2. Design Principles (hard rules)

| Rule | Source | Consequence |
|------|--------|-------------|
| PyUVM-on-cocotb only; no SV UVM tests | DTP / SEP pattern | Tests use the common Python environment |
| No prebuilt firmware binary dependency | Reproducible builds | Firmware-driven behavior uses source-built images or BFM-driven Python tests |
| All stimulus goes through BFM agents | DTP rule | One agent per external interface (I2C / JTAG / AXI / GPIO / OCTS / AVSBus / …) |
| `tb_top` flattens and lifts internal signals to top-level | SEP rule | Internal observables exposed by `assign` XMR; BFMs hang off top-level ports |
| Commercial sim is the live verification target; Verilator is best-effort | Pragmatic | Until the upstream Verilator codegen bug is fixed, live PASS via Xcelium / VCS |
| Testlists split per module + aggregated by `all.toml` | DTP rule | `--tag` / `--items` filtering works cleanly |
| Prefer reusing existing `ocah_*_vip` BFMs | DTP / SEP | New OCAH-local BFMs only when no shared wrapper exists |

---

## 3. Starting Point

Already in place at the time this plan was written:

- `cocotb/env/`     `SmcEnvCfg`, `SmcEnv`, `SmcI2cAgent`, `SmcI2cItem`, `SmcScoreboard`
- `cocotb/seq_lib/` `smc_base_test_seq`, `smc_i2c_cg_sanity_test_seq`
- `cocotb/tests/`   `smc_base_test`, `smc_i2c_cg_sanity_test`, plus existing flat
                    `test_smc_oss_reset_sanity`, `test_smc_oss_i2c_cg_sanity`
- `tb/tb_top.sv`    clocks / reset / powergood + I2C observability outputs
- `testlists/smoke.toml` groups: `smoke`, `i2c`, `pyuvm`
- `smc_sim_cfg.toml` `SYNTHESIS` define present
- `pyuvm 4.0.1` for Python 3.11

Known blocker at that time:

- Verilator + PeakRDL nested-struct codegen bug blocked live execution on
  Verilator 5.030 / 5.036 / 5.046. The same bug affected SEP / DTP. Live PASS
  required an upstream fix, a commercial simulator, or PeakRDL re-generation.

---

## 4. Module → Representative Testcase Mapping

### Batch A — Observation class (no new BFM; reuses base bring-up)

| # | Module | Legacy test | OSS testcase | Agent | New tb_top port |
|---|--------|-------------|--------------|-------|------------------|
| 1 | Reset (cold) | flat `test_smc_oss_reset_sanity` | `smc_cold_reset_test` (PyUVM) | `SmcResetAgent` | none (already exposed) |
| 2 | Reset (warm handshake) | `reset_warm_reset_handshake_test` | `smc_warm_reset_handshake_test` | `SmcResetAgent` | warm reset observe |
| 3 | Cool reset interaction | `smc_cool_reset_x_cool_reset_test` | `smc_cool_reset_intersection_test` | `SmcResetObserver` | cool reset signals |
| 4 | Clock glitch-free | `clk_glitch_free_test` | `smc_clk_glitch_free_test` | `SmcClockObserver` | clk mux select |
| 5 | Clock force ref | `clk_force_refclk_test` | `smc_clk_force_refclk_test` | `SmcClockObserver` | ref/smc select |
| 6 | PLL observability | `pll_gpio_observe_test` | `smc_pll_observe_test` | `SmcGpioObserver` | PLL lock + GPIO |
| 7 | GPIO strap sanity | `smc_gpio_strap_sanity_test` | `smc_gpio_strap_sanity_test` | `SmcGpioAgent` | gpio_i/o, strap |
| 8 | I2C clock-gate | already built | `smc_i2c_cg_sanity_test` ✓ | `SmcI2cAgent` (observer) | already in tb_top |
| 9 | Hang detector | `smc_hang_detector_sanity_test` | `smc_hang_detector_sanity_test` | `SmcInterruptObserver` | hang IRQ |
| 10 | External interrupts | `smc_external_interrupts_test` | `smc_ext_irq_sanity_test` | `SmcInterruptAgent` | IRQ in/out |

Effort: ~5 days tests + 3 days shared infra = **8 days**

### Batch B — AXI / CSR class (needs AXI-Lite master agent)

| # | Module | Legacy test | OSS testcase | Agent |
|---|--------|-------------|--------------|-------|
| 11 | Register access | `register_test` | `smc_register_sanity_test` | `SmcAxiLiteCsrAgent` |
| 12 | AXI-Lite extension | `smc_external_test` | `smc_external_test` | `SmcAxiLiteCsrAgent` |
| 13 | AXI timeout | `smc_axi_timeout_sanity_test` | `smc_axi_timeout_sanity_test` | `SmcAxiMasterAgent` + stall inject |
| 14 | Mailbox register | `smc_mailbox_register_test` | `smc_mailbox_register_test` | `SmcMailboxAgent` |
| 15 | Default reg read | `smc_default_reg_rd_test` | `smc_default_reg_rd_test` | `SmcAxiLiteCsrAgent` |
| 16 | ECAM | `smc_ecam_sanity_test` | `smc_ecam_sanity_test` | `SmcAxiLiteCsrAgent` (ECAM space) |
| 17 | ECC | `smc_ecc_test` | `smc_ecc_sanity_test` | `SmcAxiMasterAgent` + ECC inject |
| 18 | AVSBus | `smc_avsbus_sanity_test` | `smc_avsbus_sanity_test` | `SmcAvsBusAgent` (new) |
| 19 | DBS sanity | `smc_dbs_sanity_test` | `smc_dbs_sanity_test` | `SmcAxiLiteCsrAgent` + DBS BFM |
| 20 | DFD sanity | `smc_dfd_sanity_test` | `smc_dfd_sanity_test` | `SmcAxiLiteCsrAgent` + DFD observe |

Effort: ~12 days tests + 7 days BFM infra = **19 days**

### Batch C — Standard protocol class (mostly reuses existing OCAH VIP)

| # | Module | Legacy test | OSS testcase | OCAH VIP |
|---|--------|-------------|--------------|----------|
| 21 | I2C controller↔target | `smc_i2c_sanity_test` | `smc_i2c_master_target_test` | `smc_i2c_protocol_vip` (SMC-local) |
| 22 | I2C target only | `smc_i2c_target_sanity_test` | `smc_i2c_target_sanity_test` | `smc_i2c_protocol_vip` (SMC-local) |
| 23 | Dual I2C | `dual_i2c_test` | `smc_dual_i2c_test` | `smc_i2c_protocol_vip` (SMC-local) |
| 24 | iJTAG | `smc_basic_ijtag_test` | `smc_ijtag_basic_test` | `ocah_jtag_vip` |
| 25 | I3C → fabric | `smc_input_fabric_i3c_to_output_wr_rd_test` | `smc_i3c_to_fabric_test` | proxy CSR + pad checks (no I3C VIP) |
| 26 | OCTS | `octs_sanity_test` | `smc_octs_sanity_test` | new OCAH-local BFM |
| 27 | ATB | `atb_sanity_test` | `smc_atb_sanity_test` | new OCAH-local BFM |
| 28 | eFuse OTP | `smc_efuse_otp_clock_config_test` | `smc_efuse_otp_clock_test` | OTP responder (SEP-derived) |

Effort: ~12 days tests + 4 days new BFM = **16 days**

### Batch D — Fabric / CPU traffic class (multi-agent integration)

| # | Module | Legacy test | OSS testcase | Agents |
|---|--------|-------------|--------------|--------|
| 29 | Input fabric WR/RD | `smc_local_fabric_input_axi_wr_rd_test` | `smc_input_fabric_axi_wr_rd_test` | AxiMaster + AxiSlave |
| 30 | Output fabric WR/RD | `smc_output_fabric_wr_rd_test` | `smc_output_fabric_wr_rd_test` | AxiMaster + AxiSlave |
| 31 | Local fabric internal | `smc_local_fabric_internal_reg_xbar_wr_rd_test` | `smc_local_fabric_internal_test` | AxiMaster + AxiLiteCsr |
| 32 | Binary loader (no CPU) | `smc_binary_loader_test` | `smc_binary_loader_test` | AxiMaster backdoor |
| 33 | CPU → SEP AXI | `smc_cpu_traffic_sep_axi_test` | `smc_cpu_to_sep_axi_test` | AxiMaster + CPU-LSU force-splice |
| 34 | FLR | `smc_flr_sanity_test` | `smc_flr_sanity_test` | AxiLite + ResetObserver |

Effort: ~18 days tests + 6 days infra = **24 days**

### Batch X — Out of scope

| Item | Reason |
|------|--------|
| `smc_sep_load_and_run_binary_test` | SEP OSS already covers (`sep_hello_world_test`) |
| `smc_i2c_smbus_*`, `smc_i2c_pmbus_*` | High-level on top of I2C; phase 2 |
| `smc_efuse_jtag_*` variants | Needs full iJTAG + eFuse env; phase 2 |
| `smc_cpu_perf_loader_test` | OSS scope is not aimed at performance |
| `*_p1_*`, `*_p2_*` variants | p0 / sanity already represent the module |

---

## 5. Shared Infrastructure Roadmap

| # | Component | Depends on | Reuse | Effort |
|---|-----------|------------|-------|--------|
| I1 | `SmcResetAgent` / `SmcResetObserver` | cocotb | base bring-up | 0.5 |
| I2 | `SmcClockObserver` | cocotb | — | 0.5 |
| I3 | `SmcGpioAgent` / `SmcGpioObserver` | cocotb | — | 1.0 |
| I4 | `SmcInterruptObserver` | cocotb | — | 0.5 |
| I5 | `SmcAxiMasterAgent` | `ocah_axi_vip` | DTP `DtpAxiAgent` template | 1.0 |
| I6 | `SmcAxiLiteCsrAgent` | `ocah_axi_vip` AXI-Lite | I5 variant | 1.0 |
| I7 | `SmcMailboxAgent` | `ocah_axi_vip` AXI-Lite | I6 variant | 1.0 |
| I8 | `SmcI2cMasterTargetAgent` | `smc_i2c_protocol_vip` (SMC-local) | upgrades observer | 1.5 |
| I9 | `SmcJtagAgent` | `ocah_jtag_vip` | copy from DTP | 0.5 |
| I10 | `SmcI3cAgent` | none (no I3C VIP ships) | same | 1.0 |
| I11 | `SmcOtpResponderAgent` | SEP OTP shim | copy from SEP | 1.0 |
| I12 | `SmcAvsBusAgent` (new BFM) | — | — | 2.0 |
| I13 | `SmcOctsAgent` (new BFM) | — | — | 2.0 |
| I14 | `SmcAtbAgent` (new BFM) | — | — | 1.5 |
| I15 | CPU-LSU force-splice + scratch helper | SEP tb_top | copy from SEP | 2.0 |
| I16 | Scoreboard multi-stream dispatch | already minimal | refactor | 1.0 |

Total shared infra: ~17.5 days.

---

## 6. tb_top Expansion Plan (per batch)

Incremental, never all-at-once.

| Stage | New tb_top top-level ports |
|-------|----------------------------|
| After A | warm / cool reset observe, clock mux select, all GPIO, all IRQ, hang detector IRQ |
| After B | s_axil_csr_*, s_axil_ext_*, m_axi_*, mailbox AXIL, AVSBus, ECAM AXIL, ECC injection |
| After C | I2C SCL/SDA × N, I3C SDA/SCL, iJTAG TCK/TMS/TDI/TDO, OCTS pads, ATB, OTP IF |
| After D | SEP AXI splice, CPU LSU force probe, internal xbar observation |

Each batch close-out: re-run `--validate-configs` + dry-run for the new and
all prior tests, and a regression dry-run on `reset_sanity` and
`i2c_cg_sanity_test` to catch tb_top breakage early.

---

## 7. Testlist Reorganization (DTP-style)

```
testlists/
├── all.toml              (includes everything, defines smoke/functional/full)
├── smoke.toml            (Batch A sanity subset)
├── reset.toml            (Batch A reset family)
├── clock.toml            (Batch A clock / PLL)
├── gpio_irq.toml         (Batch A GPIO / IRQ)
├── csr.toml              (Batch B register / AXIL / AVSBus / ECAM)
├── ecc.toml              (Batch B ECC / AXI timeout)
├── i2c.toml              (Batch C I2C family)
├── i3c.toml              (Batch C I3C)
├── ijtag.toml            (Batch C iJTAG)
├── octs.toml             (Batch C OCTS)
├── atb.toml              (Batch C ATB)
├── efuse.toml            (Batch C eFuse)
├── fabric.toml           (Batch D fabric)
└── cpu_traffic.toml      (Batch D CPU traffic)
```

`smc_sim_cfg.toml [testlist].path` → `all.toml`.

---

## 8. Phased Milestones

| Phase | Work | Effort | Cumulative |
|-------|------|--------|------------|
| P0 | DONE: env scaffold + i2c_cg_sanity | — | 0 |
| P1 | Shared infra I1–I9 (first 9 components) | 7 | 7 |
| P2 | Batch A: 10 observation tests | 5 | 12 |
| P3 | Shared infra I5–I7 + Batch B: 10 tests | 12 | 24 |
| P4 | Shared infra I8–I14 + Batch C: 8 tests | 14 | 38 |
| P5 | Shared infra I15–I16 + Batch D: 6 tests | 17 | 55 |
| P6 | testlist reorg + commercial sim full run | 3 | 58 |
| P7 | docs (`SMC_TB_ARCH.md`, `SMC_VPLAN.adoc`) | 2 | 60 |

Total: ~60 person-days, single mid-level engineer.

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Verilator + PeakRDL codegen bug | All live Verilator runs blocked | Accept static + dry-run + commercial sim as verification; file a minimal upstream repro |
| Missing OCAH BFMs (OCTS / ATB / AVSBus) | Some Batch B / C tests gated | Write OCAH-local simplified models (I12 / I13 / I14 in shared infra) |
| CPU-LSU splice complexity | Batch D CPU tests hard | Copy the SEP `initial force` + XMR-read pattern verbatim |
| Firmware-only test behavior | May need a BFM-driven equivalent | Express the hardware action, such as an IRQ trigger or CSR write, through the appropriate BFM |
| `tb_top` port growth → bender filelist breakage | Batch C / D risk | Validate after every batch; stub immediately if any new Verilator surface fails |

---

## 10. Acceptance Criteria

Per testcase:

- [ ] `--validate-configs` smc OK
- [ ] `--dut smc --list` shows the new test in the right group / tag
- [ ] `--items <name> --tool verilator --dry-run` 4 stages PASS
- [ ] Static import of all new `env` / `seq_lib` modules succeeds
- [ ] `--items <name> --tool xcelium` (if licensed) live PASS
- [ ] `result.json` `status=PASS` + `results.xml` testcase PASS

Per batch:

- [ ] Entire batch group dry-run PASS
- [ ] `reset_sanity` and prior PyUVM tests still dry-run PASS
- [ ] Any new OCAH-local BFM has README + example

---

## 11. Execution Order

1. **First**: build one representative test (`smc_cold_reset_test`) to validate the
   porting workflow end-to-end including a second agent in the env.
2. After it passes: build the remaining Batch A tests (Phase P1 + P2 in parallel).
3. Batch B onward proceeds linearly.

---

## 12. Working Execution Recipe (verified end-to-end PASS)

First green run :  `smc_cold_reset_test` on Xcelium 25.03.001
Run dir         :  `hw/sys/smc/dv/build/runs/20260615_081028__xcelium__smc_cold_reset_test`
Result          :  `top status: PASS` ;  cocotb `TESTS=1 PASS=1` at 4152 ns sim time

Xcelium must be on `PATH` with a license configured for your site; see
`smc_oss_execution_guide.md` §1 for the current environment setup.

```bash
python3 tools/dv/run_dv.py --dut smc --items smc_cold_reset_test --tool xcelium
```

### Eleven fixes that landed the first green run

| # | Fix | Reason |
|---|-----|--------|
| 1 | Use Xcelium 25.03.001 (instead of Verilator) | Verilator hit a PeakRDL nested-struct C++ codegen bug; Xcelium does not |
| 2 | `[build.xcelium].extra_build_args = ["-ALLOWREDEFINITION", "-timescale", "1ns/1ps"]` | DUPUNI duplicate-module errors + CUMSTS missing-timescale errors |
| 3 | Rewrote `tb/verilator_stubs/prim_sync2.sv` as a behavioral two-stage flop with `initial = 0` | The original stub tied `rst_ni = 1'b1`, leaving the synchronizer first stage at X forever |
| 4 | `tb_top.sv` ties `.test_mode_i(1'b0)` and `.scan_rst_n_i(1'b1)` on the `smc` instance | Those two top-level inputs feed `prim_sync_reset`'s test-mode mux; X on them masked the cold-reset chain |
| 5 | Tightened `parsers.toml` `$fatal` pattern to `\\*F[,:].*\\$fatal\\b` | The Xcelium STRINT warning echoes RTL source containing `$fatal`; the old pattern false-positived ERROR |
| 6 | `SmcEnvCfg.post_reset_settle_cycles = 500` | The SMC reset chain has a 255-cycle stretcher; 100 cycles was too few |
| 7 | Move `self.ap = self.driver.ap` from `build_phase` to `connect_phase` in `SmcI2cAgent` / `SmcResetAgent` | Under pyuvm 4 the child `driver.build_phase` runs only after the parent agent returns, so the driver's `ap` does not exist yet when the agent's `build_phase` runs |
| 8 | `SmcScoreboard` inherits from `uvm_subscriber` (not `uvm_component`) | `uvm_subscriber` provides the `analysis_export` + `write()` forwarding; a bare `uvm_component` with a manual `uvm_analysis_export` cannot terminate the analysis-port chain |
| 9 | Type-dispatched `write()` (`_check_i2c` / `_check_reset`) | Multiple agents broadcast into one scoreboard; dispatch by item type |
| 10 | Stricter scoreboard checks (resolvable + expected reset-released values) | Beyond the original `is_resolvable`-only check, lock in the reset post-release state |
| 11 | Install `pyuvm` for Python 3.11 | `pyuvm` shipped only with the system Python 3.9, but the runner needs 3.11 for `from datetime import UTC` |

### `tb_top` minimum drive set (at first green run)

| Port | Value | Why |
|------|-------|-----|
| `test_mode_i` | `1'b0` | functional (not scan) mode |
| `scan_rst_n_i` | `1'b1` | scan reset released |

SMC has ~88 input ports total; the rest stayed unconnected because the
cold-reset sanity path does not touch them. As later tests add stimulus on
JTAG / AXI / GPIO / I2C / OCTS / ATB they need their own port wiring
(captured in the `tb_top` expansion plan, §6).

### Validated Python lifecycle pattern (pyuvm 4)

```python
class SmcXxxAgent(uvm_agent):
    def build_phase(self):
        self.cfg = ConfigDB().get(self, "", "cfg")
        self.sequencer = uvm_sequencer("sequencer", self)
        self.driver = SmcXxxDriver("driver", self)
        # NOTE: do NOT touch self.driver.ap here

    def connect_phase(self):
        self.driver.seq_item_port.connect(self.sequencer.seq_item_export)
        self.ap = self.driver.ap


class SmcScoreboard(uvm_subscriber):
    def build_phase(self):
        self.samples_seen_by_type = {}

    def write(self, item):
        if isinstance(item, SmcXxxItem):
            self._check_xxx(item)
```

Replicate this skeleton for every new agent + scoreboard hook.
