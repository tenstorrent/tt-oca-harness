<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC functional-coverage plan

Every point below is a `required_cells` entry from a scenario's coverage record in the frozen feature list, so each one traces to a spec section, not to RTL and not to an existing test. A cell is the unit that becomes a real coverage bin or cover property; the seed count is not part of this contract — `required_cells` is what binds.

| Features | Scenarios | Coverage cells | DIRECTED scenarios | RANDOMIZED scenarios | Contested-state scenarios |
|---:|---:|---:|---:|---:|---:|
| 127 | 543 | 1156 | 402 | 141 | 67 |

## Carriers named by the plan

| `coverage_artifact` | Scenarios | What it means for collection |
|---|---:|---|
| `covergroup` | 337 | a SystemVerilog covergroup with the cells as bins; mergeable on VCS/Xcelium, Verilator has no covergroup support so these need a `cover property` per bin there |
| `cover-property` | 132 | a `cover property` — lands in the tool's `user` family and merges with the line/toggle database; the only carrier the coverage policy can gate on |
| `assertion-cover` | 70 | a `cover` on an assertion property — same `user` family as a cover property; on Verilator it must be written with the `OCAH_FCOV_COVER` macro form, since `assert ... cover` is not a coverage point there |
| `toggle-report` | 4 | read off the structural toggle database rather than a functional point — only meaningful where toggle collection is enabled for that hierarchy |

## Coverage points by feature

`Blocked by` names an open spec finding whose answer changes what the cell must observe; implement those last, or against the assumption the finding records.

### `SMC-CLK-SMC` — SMC clock domain distribution

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `cpu-retires-on-clk-smc` | `SMC-CLK-SMC.S1` | the CPU cluster and its cache hierarchies advance on clk_smc_i | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §SMC Clock Domain (+1) | — |
| `fabric-transfer-on-clk-smc` | `SMC-CLK-SMC.S2` | the AXI crossbar and interconnect move data on clk_smc_i | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §SMC Clock Domain | — |
| `remap-filter-clocked-by-clk-smc` | `SMC-CLK-SMC.S3` | the address remap engines and filtering logic are clocked in this domain | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `clk_rst.adoc#The` §SMC Clock Domain | — |

### `SMC-CLK-REF` — Reference clock domain

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `clint-tick-on-clk-ref` | `SMC-CLK-REF.S1` | CLINT and the OCTS system timer advance on the reference clock | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| `octs-tick-on-clk-ref` | `SMC-CLK-REF.S1` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `rdc-sync-anchored-on-clk-ref` | `SMC-CLK-REF.S2` | the reference domain is the synchronization anchor for reset domain crossings | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| `jtag-access-with-clk-smc-stopped` | `SMC-CLK-REF.S3` | debug and JTAG operate on the reference clock independently of system operational state | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| `clk-ref-reaches-pll-wrapper` | `SMC-CLK-REF.S4` | the reference clock is consumed as the PLL reference for frequency synthesis | DIRECTED | — | `toggle-report` | `CONNECTIVITY` | `clk_rst.adoc#The` §Reference Clock Domain | — |

### `SMC-CLK-PERIPH` — Peripheral clock domain

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `avsbus-on-clk-periph` | `SMC-CLK-PERIPH.S1` | AVSBus, I2C, UART 16550 and I3C operate on clk_periph_i | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | — |
| `i2c-on-clk-periph` | `SMC-CLK-PERIPH.S1` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `uart-on-clk-periph` | `SMC-CLK-PERIPH.S1` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `i3c-on-clk-periph` | `SMC-CLK-PERIPH.S1` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `clk-periph-at-minimum-100mhz` | `SMC-CLK-PERIPH.S2` | the domain operates at the stated 100 MHz minimum frequency | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | SF-041 |
| `periph-clk-slower-than-smc` | `SMC-CLK-PERIPH.S3` | **[contested]** [BOUNDED-LIVENESS] the peripheral clock is scaled independently of clk_smc and traffic still completes or errors within a bound | RANDOMIZED | `clk_periph_period`, `clk_smc_period` | `covergroup` | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | SF-041 |
| `periph-clk-faster-than-smc` | `SMC-CLK-PERIPH.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `periph-clk-ratio-non-integer` | `SMC-CLK-PERIPH.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-CLK-TELEM` — Telemetry clock domain

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `atb-capture-on-clk-telemetry` | `SMC-CLK-TELEM.S1` | incoming ATB telemetry data is captured on clk_telemetry_i with no dedicated SMC PLL | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §Telemetry Clock Domain | — |
| `telemetry-reset-asserted` | `SMC-CLK-TELEM.S2` | rst_telemetry_ni resets the telemetry receiver logic | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#rst_telemetry_ni@f2cb50de | — |
| `telemetry-reset-released` | `SMC-CLK-TELEM.S2` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |

### `SMC-PERIPH-CDC` — Peripheral register crossing into the peripheral clock

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `crossbar-decode-on-clk-smc` | `SMC-PERIPH-CDC.S1` | the peripheral register crossbar decodes and routes at SMC clock speed, not peripheral clock speed | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | — |
| `axil-cdc-bridge-read` | `SMC-PERIPH-CDC.S2` | each master port targeting a peripheral-domain block delivers the access through its own AXI-Lite CDC bridge | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain | SF-041 |
| `axil-cdc-bridge-write` | `SMC-PERIPH-CDC.S2` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `cdc-access-inflight-at-periph-reset` | `SMC-PERIPH-CDC.S3` | **[contested]** [BOUNDED-LIVENESS] a register access in flight across the CDC bridge when the peripheral reset asserts completes or errors within a bound | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#The` §Peripheral Clock Domain (+1) | — |
| `cdc-access-terminates-bounded` | `SMC-PERIPH-CDC.S3` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |

### `SMC-CLKGATE` — Activity-based clock gating

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `module-gate-enabled` | `SMC-CLKGATE.S1` | an individually disabled module has its clock gated off | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | SF-013 |
| `module-gate-disabled` | `SMC-CLKGATE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `activity-detected-clock-restored` | `SMC-CLKGATE.S2` | per-module activity detection re-enables a gated clock | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | — |
| `hysteresis-min-value` | `SMC-CLKGATE.S3` | the 6-bit programmable hysteresis prevents gating oscillation under varying load | RANDOMIZED | `hysteresis_value`, `activity_burst_pattern` | `covergroup` | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | SF-013 |
| `hysteresis-max-value` | `SMC-CLKGATE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hysteresis-mid-value` | `SMC-CLKGATE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-gate-toggle-within-hysteresis` | `SMC-CLKGATE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `threshold-delay-observed` | `SMC-CLKGATE.S4` | the configurable enable threshold delays gating after activity ceases | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | SF-013 |
| `activity-during-hysteresis-countdown` | `SMC-CLKGATE.S5` | **[contested]** [BOUNDED-LIVENESS] activity arriving while the hysteresis countdown is in progress restores the clock without a glitch and without losing the request | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Clock` §Gating Control Parameters | — |
| `no-clock-glitch-on-restore` | `SMC-CLKGATE.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-RST-POR` — Power-on reset root

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `powergood-rise-stretched` | `SMC-RST-POR.S1` | BP_POWERGOOD is stretched into powergood_stable | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Reset` §Architecture | SF-045 |
| `cold-reset-gated-before-powergood` | `SMC-RST-POR.S2` | the SMC functional cold reset path stays gated until powergood_stable is asserted | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Primary` §Reset Activation Sources | — |
| `cold-reset-released-after-powergood` | `SMC-RST-POR.S2` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `powergood-stable-out-asserted` | `SMC-RST-POR.S3` | powergood_stable_o presents the debounced power-good to external systems | DIRECTED | — | `toggle-report` | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#powergood_stable_o@f2cb50de | — |
| `powergood-drop-during-operation` | `SMC-RST-POR.S4` | **[contested]** [BOUNDED-LIVENESS] power-good deasserting mid-operation drives the SMC back into full initialization within a bound | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#SMC` §Reset Sources and Characteristics | — |
| `full-init-reentered-bounded` | `SMC-RST-POR.S4` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |

### `SMC-RST-TAP` — TAP and TDR reset from power-good

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `trst-low-powergood-high` | `SMC-RST-TAP.S1` | the effective TAP reset is the AND of TRSTN and pwr_on_rst_ni | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Reset` §Architecture | — |
| `trst-high-powergood-low` | `SMC-RST-TAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `both-high` | `SMC-RST-TAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `both-low` | `SMC-RST-TAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `tap-reset-forced-by-powergood-loss` | `SMC-RST-TAP.S2` | loss of power-good forces TAP and TDR logic into reset even with TRST released | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Reset` §Architecture | — |
| `tdr-state-preserved-across-primary-reset` | `SMC-RST-TAP.S3` | JTAG and TDR reset state survives rst_primary_no asserted alone | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |

### `SMC-RST-COLD` — Functional cold reset

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `cold-reset-async-assert` | `SMC-RST-COLD.S1` | asserting the cold reset input asserts rst_primary_no with asynchronous assertion and synchronous deassertion | DIRECTED | — | `assertion-cover` | `LIVE` | hw/sys/smc/doc/port_table.adoc#rst_cold_ni@f2cb50de (+1) | SF-045 |
| `cold-reset-sync-deassert` | `SMC-RST-COLD.S1` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `tdr-not-reset-by-cold-reset` | `SMC-RST-COLD.S2` | the cold reset path excludes the JTAG/TDR reset state | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Primary` §Reset Activation Sources | — |

### `SMC-RST-PRIMARY` — Primary reset scope

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `cores-held-in-primary-reset` | `SMC-RST-PRIMARY.S1` | CPU cores and cache hierarchies are held while rst_primary_no is asserted | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| `fabric-held-in-primary-reset` | `SMC-RST-PRIMARY.S2` | fabric infrastructure is held while rst_primary_no is asserted | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| `peripherals-held-in-primary-reset` | `SMC-RST-PRIMARY.S3` | peripheral controllers and interfaces are held while rst_primary_no is asserted | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| `config-registers-at-reset-value` | `SMC-RST-PRIMARY.S4` | SMC control and configuration registers return to their reset values after primary reset | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) | — |
| `reset-with-read-inflight` | `SMC-RST-PRIMARY.S5` | **[contested]** [BOUNDED-LIVENESS] primary reset asserted with fabric transactions in flight terminates them within a bound and leaves no bus hung | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Primary` §Reset (rst_primary_no) (+1) | — |
| `reset-with-write-inflight` | `SMC-RST-PRIMARY.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `no-outstanding-after-reset` | `SMC-RST-PRIMARY.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-RST-COOL` — Cool reset with selective isolation

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `cool-reset-asserts-primary` | `SMC-RST-COOL.S1` | an externally initiated cool reset drives the primary reset path | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Primary` §Reset Activation Sources | SF-011 |
| `cool-reset-from-gpio-pin-61` | `SMC-RST-COOL.S2` | rst_cool_n_from_pin_i on GPIO pin 61 initiates the cool reset sequence | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#rst_cool_n_from_pin_i@f2cb50de | — |
| `isolation-asserted-with-cool-reset` | `SMC-RST-COOL.S3` | selective subsystem isolation accompanies the cool reset | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#SMC` §Reset Sources and Characteristics (+1) | SF-011 |

### `SMC-RST-WARM` — Warm reset scope and activation

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `warm-cascaded-from-primary` | `SMC-RST-WARM.S1` | warm reset is cascaded from primary reset | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources | — |
| `warm-from-internal-wdt` | `SMC-RST-WARM.S2` | an internal or external watchdog timeout activates warm reset | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources | SF-046 |
| `warm-from-external-wdt` | `SMC-RST-WARM.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `warm-from-debug-reset` | `SMC-RST-WARM.S3` | a debug-interface initiated reset activates warm reset | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources | SF-046 |
| `warm-scope-includes-plic-clint-wdt-beu` | `SMC-RST-WARM.S4` | warm reset holds cores, private caches, PLIC, CLINT, per-core watchdogs and bus error units and nothing wider | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Warm` §Reset (rst_warm_no) | SF-046 |
| `warm-scope-excludes-fabric-and-peripherals` | `SMC-RST-WARM.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `warm-during-primary-deassert` | `SMC-RST-WARM.S5` | **[contested]** [BOUNDED-LIVENESS] warm reset asserted while primary reset is deasserting settles to a single defined post-reset state | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Warm` §Reset Activation Sources (+1) | — |
| `single-defined-post-reset-state` | `SMC-RST-WARM.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-RST-SYNC` — Reset synchronization across clock domains

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `async-assert-observed` | `SMC-RST-SYNC.S1` | reset assertion is asynchronous to the target clock | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |
| `sync-deassert-observed` | `SMC-RST-SYNC.S2` | reset deassertion is synchronous to the target clock | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |
| `multi-stage-sync-present` | `SMC-RST-SYNC.S3` | the multi-stage synchronizer provides metastability protection on the deassertion edge | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity | — |
| `rst-primary-smc-clk` | `SMC-RST-SYNC.S4` | all four named synchronized reset signals reach their declared target domains | DIRECTED | — | `covergroup` | `CONNECTIVITY` | `clk_rst.adoc#Reset` §Synchronization Domains (+1) | SF-042 |
| `rst-warm-smc-clk` | `SMC-RST-SYNC.S4` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `rst-primary-ref-clk` | `SMC-RST-SYNC.S4` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `rst-primary-periph-clk` | `SMC-RST-SYNC.S4` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `reset-assert-with-clock-stopped` | `SMC-RST-SYNC.S5` | **[contested]** [BOUNDED-LIVENESS] a reset asserted while the target clock is gated or stopped still takes effect, and deassertion is held until the clock returns | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Reset` §Synchronization and Timing Integrity (+1) | — |
| `deassert-held-until-clock-returns` | `SMC-RST-SYNC.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-ISOLATE-CTRL` — Subsystem isolation request aggregation

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sw-isolate-per-subsystem` | `SMC-ISOLATE-CTRL.S1` | a software write to ISOLATE_REQ_REG asserts isolation for the selected subsystem | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| `pin-isolate-enabled` | `SMC-ISOLATE-CTRL.S2` | isolate_req_pin_i asserts isolation for subsystems enabled in ISOLATE_REQ_PINEN_REG | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| `pin-isolate-disabled` | `SMC-ISOLATE-CTRL.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `flr-isolate-enabled` | `SMC-ISOLATE-CTRL.S3` | FLR detection asserts isolation for subsystems enabled in ISOLATE_REQ_SMCEN_REG | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| `flr-isolate-disabled` | `SMC-ISOLATE-CTRL.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `or-sw-only` | `SMC-ISOLATE-CTRL.S4` | the final per-subsystem isolation state is the OR of all three sources | RANDOMIZED | `isolate_req_reg`, `isolate_req_pin`, `flr_active`, `pinen_mask`, `smcen_mask` | `covergroup` | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| `or-pin-only` | `SMC-ISOLATE-CTRL.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `or-flr-only` | `SMC-ISOLATE-CTRL.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `or-two-sources` | `SMC-ISOLATE-CTRL.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `or-all-three-sources` | `SMC-ISOLATE-CTRL.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `or-none` | `SMC-ISOLATE-CTRL.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `flr-assert-concurrent-sw-clear` | `SMC-ISOLATE-CTRL.S5` | **[contested]** [BOUNDED-LIVENESS] FLR isolation asserting while software isolation is being cleared keeps the subsystem isolated, with a bounded settle | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Isolation` §Control Architecture | — |
| `isolation-held-through-race` | `SMC-ISOLATE-CTRL.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-FLR-SEQ` — FLR programmable reset timing sequence

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `pre-delay-min` | `SMC-FLR-SEQ.S1` | the pre-reset delay from FLR trigger to cool reset assertion equals ISOLATE_REQ_FLR_COUNTER_VALUE | RANDOMIZED | `isolate_req_flr_counter_value` | `covergroup` | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing | SF-033 |
| `pre-delay-max` | `SMC-FLR-SEQ.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `pre-delay-mid` | `SMC-FLR-SEQ.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hold-min` | `SMC-FLR-SEQ.S2` | the cool reset hold time equals ISOLATE_REQ_FLR_RESET_COUNTER_VALUE | RANDOMIZED | `isolate_req_flr_reset_counter_value` | `covergroup` | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing | SF-033 |
| `hold-max` | `SMC-FLR-SEQ.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hold-mid` | `SMC-FLR-SEQ.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `same-ref-cycle-count-at-two-smc-frequencies` | `SMC-FLR-SEQ.S3` | the sequence is timed in the reference clock domain independently of the SMC clock frequency | RANDOMIZED | `clk_smc_period` | `covergroup` | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing | SF-033 |
| `flr-during-pre-delay` | `SMC-FLR-SEQ.S4` | **[contested]** [BOUNDED-LIVENESS] a second FLR request arriving during an in-progress sequence reaches a bounded defined outcome rather than restarting indefinitely | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Programmable` §Reset Timing (+1) | — |
| `flr-during-hold` | `SMC-FLR-SEQ.S4` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `sequence-completes-bounded` | `SMC-FLR-SEQ.S4` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-FLR-CDC` — FLR trigger clock domain crossing

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `flr-sync-into-clk-smc` | `SMC-FLR-CDC.S1` | the FLR active signal is synchronized into the SMC clock domain | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | SF-025 |
| `flr-sync-into-clk-ref` | `SMC-FLR-CDC.S2` | the FLR active signal is synchronized into the reference clock domain | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | SF-025 |
| `single-sequence-per-rising-edge` | `SMC-FLR-CDC.S3` | rising-edge detection on the synchronized signal initiates the sequence exactly once per trigger | DIRECTED | — | `assertion-cover` | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | — |
| `no-sequence-on-level-hold` | `SMC-FLR-CDC.S3` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `pcie-faster-than-smc` | `SMC-FLR-CDC.S4` | **[contested]** [BOUNDED-LIVENESS] operation is reliable regardless of the PCIe-to-SMC clock frequency relationship, including a trigger near the synchronizer sampling edge | RANDOMIZED | `pcie_clk_period`, `flr_assert_phase` | `covergroup` | `LIVE` | `clk_rst.adoc#Clock` §Domain Crossing and Synchronization | SF-025 |
| `pcie-slower-than-smc` | `SMC-FLR-CDC.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `trigger-near-sampling-edge` | `SMC-FLR-CDC.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-REPAIR-BYPASS` — Memory repair bypass control

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `skip-repair-from-flr-isolation` | `SMC-REPAIR-BYPASS.S1` | FLR-triggered isolation asserts skip_mem_repair_o | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Memory` §Test Bypass | — |
| `skip-repair-from-pin-isolation` | `SMC-REPAIR-BYPASS.S2` | pin-based isolation asserts skip_mem_repair_o | DIRECTED | — | `cover-property` | `LIVE` | `clk_rst.adoc#Memory` §Test Bypass | — |
| `strap-13-set-bypasses` | `SMC-REPAIR-BYPASS.S3` | the BYPASS_SRAM_REPAIR strap on GPIO pin 13 bypasses the repair logic | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| `strap-13-clear-runs-repair` | `SMC-REPAIR-BYPASS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cold-reset-executes-repair` | `SMC-REPAIR-BYPASS.S4` | a normal cold reset sequence executes repair when no bypass is asserted | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Memory` §Repair | — |

### `SMC-RST-RETAIN` — Advanced reset retention and forcing features

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ref-clock-forced-during-reset` | `SMC-RST-RETAIN.S1` | a stable reference clock is forced during resets for timing reliability | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |
| `config-held-across-reset` | `SMC-RST-RETAIN.S2` | selected configuration is retained across a reset for fast recovery | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |
| `sram-contents-preserved` | `SMC-RST-RETAIN.S3` | memory contents are kept intact across the reset events that select SRAM preservation | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |
| `debug-state-preserved` | `SMC-RST-RETAIN.S4` | debug and signal state is maintained through the reset | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `clk_rst.adoc#Advanced` §Reset Features | SF-012 |

### `SMC-RST-OVERRIDE` — DTP reset override through JTAG

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `override-enable-forces-reset-low` | `SMC-RST-OVERRIDE.S1` | an asserted override enable forces the corresponding SMC reset to the supplied active-low value | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#jtag_reset_ctrl_i@f2cb50de | SF-021 |
| `override-enable-forces-reset-high` | `SMC-RST-OVERRIDE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `all-overrides-disabled-baseline` | `SMC-RST-OVERRIDE.S2` | with every override enable tied to zero the functional reset behaviour is unchanged | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#jtag_reset_ctrl_i@f2cb50de | SF-021 |

### `SMC-SSRST` — Subsystem reset control and completion

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ss-reset-ctrl-per-subsystem` | `SMC-SSRST.S1` | ss_reset_ctrl_o drives the per-subsystem reset control for all 32 subsystems | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#ss_reset_ctrl_o@f2cb50de | SF-020 |
| `ss-config-driven` | `SMC-SSRST.S2` | ss_config_o carries the per-subsystem configuration | DIRECTED | — | `toggle-report` | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#ss_config_o@f2cb50de | — |
| `complete-all-ones-default` | `SMC-SSRST.S3` | ss_reset_complete_i is consumed and its default all-ones value permits the sequence to advance | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#ss_reset_complete_i@f2cb50de | SF-020 |
| `complete-observed-per-subsystem` | `SMC-SSRST.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `completion-withheld-one-subsystem` | `SMC-SSRST.S4` | **[contested]** [BOUNDED-LIVENESS] a subsystem that never returns completion leaves the sequencer in a bounded and observable state rather than hung silently | DIRECTED | — | `assertion-cover` | `LIVE` | hw/sys/smc/doc/port_table.adoc#ss_reset_complete_i@f2cb50de | SF-020 |
| `sequencer-state-observable-bounded` | `SMC-SSRST.S4` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-SYNC-BIT` — Global synchronisation bit

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sync-bit-set` | `SMC-SYNC-BIT.S1` | a software write to SYNC_REG.sync is reflected on sync_irq_o | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#sync_irq_o@f2cb50de | — |
| `sync-bit-cleared` | `SMC-SYNC-BIT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sync-out-unaffected-by-interrupts` | `SMC-SYNC-BIT.S2` | sync_irq_o does not aggregate any interrupt source | DIRECTED | — | `cover-property` | `DECODE` | hw/sys/smc/doc/port_table.adoc#sync_irq_o@f2cb50de | SF-047 |

### `SMC-PWRSEQ-GATE` — External boot sequence gating of reset release

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `reset-held-before-boot-seq-done` | `SMC-PWRSEQ-GATE.S1` | reset release is withheld until ext_boot_seq_done_i asserts | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#ext_boot_seq_done_i@f2cb50de | SF-039 |
| `reset-released-after-boot-seq-done` | `SMC-PWRSEQ-GATE.S1` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `boot-seq-done-withheld` | `SMC-PWRSEQ-GATE.S2` | **[contested]** [BOUNDED-LIVENESS] ext_boot_seq_done_i never asserting leaves the reset held in an observable state rather than releasing on an undefined path | DIRECTED | — | `assertion-cover` | `LIVE` | hw/sys/smc/doc/port_table.adoc#ext_boot_seq_done_i@f2cb50de | SF-039 |
| `reset-remains-held-observable` | `SMC-PWRSEQ-GATE.S2` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-CPU-EXEC` — Four-core RV64GC execution

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `core0-retire` | `SMC-CPU-EXEC.S1` | all four cores fetch and retire instructions after reset release | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Processor` §Core Overview | SF-036 |
| `core1-retire` | `SMC-CPU-EXEC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `core2-retire` | `SMC-CPU-EXEC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `core3-retire` | `SMC-CPU-EXEC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-i` | `SMC-CPU-EXEC.S2` | the I, M, A, F, D and C extensions of RV64GC execute correctly | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Processor` §Core Overview | — |
| `ext-m` | `SMC-CPU-EXEC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-a` | `SMC-CPU-EXEC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-f` | `SMC-CPU-EXEC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-d` | `SMC-CPU-EXEC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-c` | `SMC-CPU-EXEC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `priv-m` | `SMC-CPU-EXEC.S3` | machine, supervisor and user privilege levels are all reachable and enforced | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Processor` §Core Overview | — |
| `priv-s` | `SMC-CPU-EXEC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `priv-u` | `SMC-CPU-EXEC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `addr-below-4gib` | `SMC-CPU-EXEC.S4` | a 56-bit physical address issued by a core reaches a system-facing destination | RANDOMIZED | `physical_address` | `covergroup` | `LIVE` | `cpu.adoc#Processor` §Core Overview (+1) | — |
| `addr-above-4gib` | `SMC-CPU-EXEC.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `addr-at-56bit-max` | `SMC-CPU-EXEC.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-CPU-RSTVEC` — Per-core reset and programmable reset vector

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `core-reset-independent-per-core` | `SMC-CPU-RSTVEC.S1` | rst_core_N_ni resets core N independently of the other cores | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization | — |
| `vector-rom-base` | `SMC-CPU-RSTVEC.S2` | reset_vector_N_i sets the 56-bit first fetch address of core N | RANDOMIZED | `reset_vector_value`, `core_index` | `covergroup` | `LIVE` | `cpu.adoc#Processor` §Core Overview | SF-036 |
| `vector-sram-region` | `SMC-CPU-RSTVEC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `vector-nondefault-per-core` | `SMC-CPU-RSTVEC.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `first-fetch-at-c0040000` | `SMC-CPU-RSTVEC.S3` | the cold-reset CPU vector is 0xC004_0000 | DIRECTED | — | `cover-property` | `LIVE` | `rom.adoc#Boot` §ROM | SF-036 |
| `one-core-reset-others-run` | `SMC-CPU-RSTVEC.S4` | **[contested]** [BOUNDED-LIVENESS] one core held in reset while the others execute leaves the running cores undisturbed | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization | — |

### `SMC-CPU-L1CACHE` — Per-core L1 cache hierarchy

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `icache-hit` | `SMC-CPU-L1CACHE.S1` | the L1 instruction cache is 4 KiB organized as 32 sets by 2 ways | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| `icache-miss` | `SMC-CPU-L1CACHE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `icache-way0-fill` | `SMC-CPU-L1CACHE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `icache-way1-fill` | `SMC-CPU-L1CACHE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `icache-set-wrap` | `SMC-CPU-L1CACHE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dcache-hit` | `SMC-CPU-L1CACHE.S2` | the L1 data cache is 4 KiB organized as 32 sets by 2 ways | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| `dcache-miss` | `SMC-CPU-L1CACHE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dcache-way0-fill` | `SMC-CPU-L1CACHE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dcache-way1-fill` | `SMC-CPU-L1CACHE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dcache-set-wrap` | `SMC-CPU-L1CACHE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `icache-write-through-observed` | `SMC-CPU-L1CACHE.S3` | the instruction cache is write-through | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| `dcache-dirty-line` | `SMC-CPU-L1CACHE.S4` | the data cache is write-back, so a dirty line reaches memory only on eviction | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| `dcache-writeback-on-evict` | `SMC-CPU-L1CACHE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `icache-cfg-applied` | `SMC-CPU-L1CACHE.S5` | cache size and associativity follow the icache and dcache tag/data configuration inputs | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `cpu.adoc#Cache` §and Memory Hierarchy (+1) | — |
| `dcache-cfg-applied` | `SMC-CPU-L1CACHE.S5` | ″ | ″ | ″ | `cover-property` | `CONNECTIVITY` | ″ | ″ |

### `SMC-CPU-ECC` — Cluster memory error protection

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `icache-parity-error-detected` | `SMC-CPU-ECC.S1` | an instruction cache parity error is detected | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | SF-022 |
| `dcache-single-error-corrected` | `SMC-CPU-ECC.S2` | a single-bit data cache error is corrected by SECDED | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | SF-022 |
| `spm-single-error-corrected` | `SMC-CPU-ECC.S3` | a single-bit scratchpad error is corrected by SECDED | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | SF-022 |
| `double-error-detected` | `SMC-CPU-ECC.S4` | a double error is detected and reported on cluster_ded_o | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#cluster_ded_o@f2cb50de (+1) | SF-022 |
| `cluster-ded-asserted` | `SMC-CPU-ECC.S4` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |

### `SMC-SPM` — Shared scratchpad memory

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `spm-access-cold-cache` | `SMC-SPM.S1` | scratchpad access latency is deterministic and independent of cache state | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| `spm-access-warm-cache` | `SMC-SPM.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `spm-latency-equal` | `SMC-SPM.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `bank-first` | `SMC-SPM.S2` | every scratchpad bank is reachable through its own request and response interface | RANDOMIZED | `bank_index`, `access_offset` | `covergroup` | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#scratch_ram_intf_req_o@f2cb50de | SF-002 |
| `bank-last` | `SMC-SPM.S2` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `bank-crossing-access` | `SMC-SPM.S2` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `bank-power-gated` | `SMC-SPM.S3` | per-bank power gating is applied without corrupting the contents of active banks | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Cache` §and Memory Hierarchy | — |
| `active-bank-contents-intact` | `SMC-SPM.S3` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `spm-write-then-read` | `SMC-SPM.S4` | the scratchpad region decodes in the SMC memory map and is readable and writable by a core | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#SMC` §Component Address Map | SF-002 |
| `spm-region-base` | `SMC-SPM.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `spm-region-top` | `SMC-SPM.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-SRAM-INIT` — Automatic SRAM initialization

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sram-auto-init-runs` | `SMC-SRAM-INIT.S1` | SRAM is initialized automatically by hardware after reset | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization | — |
| `auto-init-disabled` | `SMC-SRAM-INIT.S2` | disable_sram_auto_init_i suppresses the automatic initialization | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#disable_sram_auto_init_i@f2cb50de | — |
| `auto-init-enabled` | `SMC-SRAM-INIT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `init-done-low-during-init` | `SMC-SRAM-INIT.S3` | init_mem_done_o asserts exactly when memory is ready for use | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#init_mem_done_o@f2cb50de | — |
| `init-done-high-after-init` | `SMC-SRAM-INIT.S3` | ″ | ″ | ″ | `cover-property` | `LIVE` | ″ | ″ |
| `access-before-init-done` | `SMC-SRAM-INIT.S4` | **[contested]** [BOUNDED-LIVENESS] a CPU access attempted before init_mem_done_o reaches a bounded defined outcome rather than returning indeterminate data | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Reset,` §Boot, and Initialization (+1) | — |
| `bounded-defined-response` | `SMC-SRAM-INIT.S4` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-MEMREPAIR` — BIRA memory repair in the boot sequence

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `repair-triggered-by-fuse-sense-done` | `SMC-MEMREPAIR.S1` | fuse_sense_done_o assertion triggers the repair operation | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Memory` §Repair (+1) | — |
| `repair-data-read-from-bira` | `SMC-MEMREPAIR.S2` | repair data is read from the 16-kilobit eFuse BIRA repair_data field and applied to the arrays | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| `redundant-element-configured` | `SMC-MEMREPAIR.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mem-repair-done-clear-then-set` | `SMC-MEMREPAIR.S3` | the mem_repair_done bit reports repair completion in the DFX control status register | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Memory` §Repair | SF-001 |
| `mem-repair-success-set` | `SMC-MEMREPAIR.S4` | the mem_repair_success bit reports whether the repair succeeded | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Memory` §Repair | SF-001 |
| `mem-repair-success-clear` | `SMC-MEMREPAIR.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mbist-after-repair-complete` | `SMC-MEMREPAIR.S5` | MBIST operations begin only after repair completes or is bypassed | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| `mbist-after-repair-bypassed` | `SMC-MEMREPAIR.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cluster-held-until-repair-and-mbist` | `SMC-MEMREPAIR.S6` | **[contested]** [BOUNDED-LIVENESS] the CPU cluster reset is not released until both repair and MBIST complete, so no core touches SRAM before repair | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Memory` §Repair | SF-039 |
| `no-sram-access-before-repair` | `SMC-MEMREPAIR.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-TL2AXI` — Cluster boundary protocol bridging

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `tl-to-axi4-read` | `SMC-TL2AXI.S1` | an internal TileLink transaction appears as a well-formed AXI4 transaction on the L2 frontend | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#System` §Interfaces | — |
| `tl-to-axi4-write` | `SMC-TL2AXI.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `tl-to-axi4-burst` | `SMC-TL2AXI.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `tl-to-axil-read` | `SMC-TL2AXI.S2` | an internal TileLink MMIO access appears as a well-formed AXI4-Lite transaction with 56-bit addressing | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#System` §Interfaces | — |
| `tl-to-axil-write` | `SMC-TL2AXI.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-CLUSTER-ISO` — Cluster AXI boundary isolation

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `drain-zero-outstanding` | `SMC-CLUSTER-ISO.S1` | up to four outstanding transactions on each wrapped AXI port are drained before isolation completes | RANDOMIZED | `outstanding_count`, `read_write_mix` | `covergroup` | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| `drain-one-outstanding` | `SMC-CLUSTER-ISO.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `drain-four-outstanding` | `SMC-CLUSTER-ISO.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `l2fe-new-txn-while-isolated-blocked` | `SMC-CLUSTER-ISO.S2` | **[contested]** [BOUNDED-LIVENESS] a new transaction presented to the isolated L2 frontend slave port is blocked rather than terminated | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| `mmio-read-while-isolated-slverr` | `SMC-CLUSTER-ISO.S3` | **[contested]** [BOUNDED-LIVENESS] a new transaction presented to the isolated MMIO master port is terminated with an SLVERR response | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| `mmio-write-while-isolated-slverr` | `SMC-CLUSTER-ISO.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-x-on-boundary-during-isolation` | `SMC-CLUSTER-ISO.S4` | no X value propagates from the cluster boundary into the fabric during the isolation window | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| `wb-pc-valid-clamped` | `SMC-CLUSTER-ISO.S5` | the non-AXI status crossings wb_pc_valid, wb_reg_pc and the per-core wdt_reset are clamped to constants over the isolation window | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| `wb-reg-pc-clamped` | `SMC-CLUSTER-ISO.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `wdt-reset-clamped` | `SMC-CLUSTER-ISO.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `self-isolated-at-cold-boot` | `SMC-CLUSTER-ISO.S6` | the boundary self-isolates on cold boot | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| `release-requires-init-done` | `SMC-CLUSTER-ISO.S7` | isolation releases only once SRAM initialization completes and the cores and uncore are out of reset | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Cluster` §Boundary Isolation | — |
| `release-requires-cores-out-of-reset` | `SMC-CLUSTER-ISO.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `release-requires-uncore-out-of-reset` | `SMC-CLUSTER-ISO.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-ISO-DRAIN` — Cluster isolation drain handshake

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `isolate-req-on-pending-sw-reset` | `SMC-ISO-DRAIN.S1` | isolate_req_i is asserted whenever a software reset of the cluster is pending | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Drain` §Handshake | — |
| `drained-requires-both-instances` | `SMC-ISO-DRAIN.S2` | drained_o asserts only once both axi_isolate instances have drained and isolated their ports | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Drain` §Handshake | — |
| `reset-withheld-until-drained` | `SMC-ISO-DRAIN.S3` | the control logic does not apply the reset before drained_o asserts | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Drain` §Handshake | — |
| `reset-req-with-read-inflight` | `SMC-ISO-DRAIN.S4` | **[contested]** [BOUNDED-LIVENESS] a reset requested with transactions in flight drains and then resets within a bound, leaving no fabric response outstanding | RANDOMIZED | `inflight_pattern`, `request_phase` | `covergroup` | `LIVE` | `cpu.adoc#Drain` §Handshake (+1) | — |
| `reset-req-with-write-inflight` | `SMC-ISO-DRAIN.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reset-req-with-four-outstanding` | `SMC-ISO-DRAIN.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-orphan-response` | `SMC-ISO-DRAIN.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-ISO-RDC` — Isolate-control reset-domain crossing

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `warm-reset-crossing-window` | `SMC-ISO-RDC.S1` | **[contested]** [BOUNDED-LIVENESS] an asynchronous watchdog warm reset crossing into axi_isolate leaves the boundary in a defined state and is followed by a cold reset | RANDOMIZED | `warm_reset_phase` | `covergroup` | `LIVE` | `cpu.adoc#Reset-Domain` §Crossing | — |
| `boundary-defined-after-crossing` | `SMC-ISO-RDC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cold-reset-follows` | `SMC-ISO-RDC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `csr-reset-path-synchronous` | `SMC-ISO-RDC.S2` | the CPU CSR reset-control write path is synchronous and crosses no reset domain | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Reset-Domain` §Crossing | — |

### `SMC-WDT` — Per-core watchdog timers

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `wdt0-decode` | `SMC-WDT.S1` | each of the four watchdog instances decodes at its own offset | DIRECTED | — | `covergroup` | `DECODE` | `interrupts.adoc#Interrupt` §controllers (MMIO) (+1) | SF-003 |
| `wdt1-decode` | `SMC-WDT.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `wdt2-decode` | `SMC-WDT.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `wdt3-decode` | `SMC-WDT.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `timeout-min` | `SMC-WDT.S2` | a programmed timeout expires after the configured interval | RANDOMIZED | `timeout_value`, `kick_pattern` | `covergroup` | `LIVE` | `cpu.adoc#Watchdog` §Timer System | — |
| `timeout-max` | `SMC-WDT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `timeout-mid` | `SMC-WDT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `kick-prevents-timeout` | `SMC-WDT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `warning-before-reset` | `SMC-WDT.S3` | the staged warning is delivered before the reset stage, allowing software intervention | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Watchdog` §Timer System (+1) | — |
| `software-intervention-prevents-reset` | `SMC-WDT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `first-timeout-to-reset-unit` | `SMC-WDT.S4` | wdt_first_timeout_o reaches the reset unit and wdt_second_timeout_o reaches external systems | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#wdt_first_timeout_o@f2cb50de | — |
| `second-timeout-to-external` | `SMC-WDT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `wdt-disabled-in-debug` | `SMC-WDT.S5` | watchdog monitoring is disabled during debugging so no false trigger occurs | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Watchdog` §Timer System | — |
| `no-timeout-while-halted` | `SMC-WDT.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `second-timeout-unserviced-warning` | `SMC-WDT.S6` | **[contested]** [BOUNDED-LIVENESS] a second timeout arriving while the first warning is unserviced escalates to reset within a bound instead of stalling | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#SMC` §interrupt sources (+1) | — |
| `escalation-to-reset-bounded` | `SMC-WDT.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-BEU` — Per-core bus error capture

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `beu0-decode` | `SMC-BEU.S1` | each of the four bus error units decodes at its own offset | DIRECTED | — | `covergroup` | `DECODE` | `interrupts.adoc#Interrupt` §controllers (MMIO) (+1) | — |
| `beu1-decode` | `SMC-BEU.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `beu2-decode` | `SMC-BEU.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `beu3-decode` | `SMC-BEU.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `beu-decode-error-classified` | `SMC-BEU.S2` | a decode error is captured and classified as such | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| `beu-slave-error-classified` | `SMC-BEU.S3` | a slave error is captured and classified as such | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| `beu-timeout-error-classified` | `SMC-BEU.S4` | a timeout error is captured and classified as such | DIRECTED | — | `cover-property` | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| `captured-address-matches` | `SMC-BEU.S5` | the error address and transaction context are preserved for fault analysis | RANDOMIZED | `error_address`, `error_transaction_type` | `covergroup` | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | — |
| `captured-transaction-attrs-match` | `SMC-BEU.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `second-error-before-read` | `SMC-BEU.S6` | **[contested]** [BOUNDED-LIVENESS] a second bus error arriving while the first capture is unread reaches a defined and observable outcome | DIRECTED | — | `assertion-cover` | `LIVE` | `cpu.adoc#Advanced` §Bus Infrastructure Monitoring and Error Management | SF-026 |
| `capture-state-defined` | `SMC-BEU.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-BEU-NMI` — Bus error NMI delivery

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `beu-irq-direct-to-core` | `SMC-BEU-NMI.S1` | a bus error unit interrupt reaches its core without passing through the PLIC | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Bus` §Error Unit interrupts | SF-026 |
| `beu-irq-absent-from-plic-sources` | `SMC-BEU-NMI.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `beu-irq-with-plic-disabled` | `SMC-BEU-NMI.S2` | delivery is immediate regardless of PLIC configuration or interrupt masking | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Bus` §Error Unit interrupts (+1) | SF-026 |
| `beu-irq-with-threshold-max` | `SMC-BEU-NMI.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-CPU-DEBUG` — Per-core debug access

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `debug-reg-read` | `SMC-CPU-DEBUG.S1` | the debug module aperture decodes and the debugger reads and writes per-core registers | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de (+1) | SF-055 |
| `debug-reg-write` | `SMC-CPU-DEBUG.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `debug-per-core-select` | `SMC-CPU-DEBUG.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `debug-mem-read` | `SMC-CPU-DEBUG.S2` | the debugger reads and writes memory through the debug path | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| `debug-mem-write` | `SMC-CPU-DEBUG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hw-breakpoint-hit` | `SMC-CPU-DEBUG.S3` | a hardware breakpoint halts the targeted core | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| `sw-breakpoint-hit` | `SMC-CPU-DEBUG.S4` | a software breakpoint halts the targeted core | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| `debug-access-across-functional-reset` | `SMC-CPU-DEBUG.S5` | debug capability continues to function across a functional reset | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |
| `debug-reset-vector-override` | `SMC-CPU-DEBUG.S6` | the debugger overrides the reset vector so a core restarts at a chosen address | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/cpu.adoc#Debug@f2cb50de | — |

### `SMC-ROM-MAP` — Boot ROM aperture

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `rom-base-read` | `SMC-ROM-MAP.S1` | the 128 KiB region from 0xC004_0000 through 0xC005_FFFF decodes to the ROM | DIRECTED | — | `covergroup` | `DECODE` | `rom.adoc#Boot` §ROM | — |
| `rom-top-read` | `SMC-ROM-MAP.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `rom-just-above-top-not-rom` | `SMC-ROM-MAP.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `rom-write-attempt` | `SMC-ROM-MAP.S2` | the region is read-only, so a write does not modify its contents | DIRECTED | — | `covergroup` | `LIVE` | `rom.adoc#Boot` §ROM | — |
| `rom-contents-unchanged` | `SMC-ROM-MAP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-ROM-INTF` — ROM macro interface

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `rom-req-issued` | `SMC-ROM-INTF.S1` | a CPU ROM access is converted into a rom_intf_req_o request | DIRECTED | — | `cover-property` | `LIVE` | `rom.adoc#ROM` §Architecture | — |
| `word-addr-zero` | `SMC-ROM-INTF.S2` | the request carries clock, enable and a 14-bit 64-bit-word address | RANDOMIZED | `rom_word_address` | `covergroup` | `LIVE` | `rom.adoc#ROM` §Architecture | — |
| `word-addr-max` | `SMC-ROM-INTF.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `word-addr-mid` | `SMC-ROM-INTF.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `rom-write-controls-inactive` | `SMC-ROM-INTF.S3` | the write controls are tied to read mode so no write ever reaches the macro | DIRECTED | — | `assertion-cover` | `CONNECTIVITY` | `rom.adoc#ROM` §Architecture | — |
| `one-word-per-request` | `SMC-ROM-INTF.S4` | the response returns exactly one 64-bit word per request | DIRECTED | — | `assertion-cover` | `LIVE` | `rom.adoc#ROM` §Architecture | — |
| `rom-path-distinct-from-axil` | `SMC-ROM-INTF.S5` | the ROM macro boundary is not AXI-Lite and is separate from the CPU MMIO and peripheral AXI-Lite paths | DIRECTED | — | `cover-property` | `DECODE` | `rom.adoc#ROM` §Architecture | — |
| `rom-cfg-zero` | `SMC-ROM-INTF.S6` | the 11-bit rom_cfg_i value is forwarded unchanged to the ROM macro configuration input | RANDOMIZED | `rom_cfg_value` | `covergroup` | `CONNECTIVITY` | `rom.adoc#ROM` §Hardware Configuration | — |
| `rom-cfg-all-ones` | `SMC-ROM-INTF.S6` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `rom-cfg-random-pattern` | `SMC-ROM-INTF.S6` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |

### `SMC-ROM-ENDIAN` — ROM response endianness control

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `endian-flip-asserted-word-reversed` | `SMC-ROM-ENDIAN.S1` | with the control asserted the eight bytes of each 64-bit word are returned in reversed order | DIRECTED | — | `cover-property` | `LIVE` | `rom.adoc#ROM` §Hardware Configuration | — |
| `endian-flip-deasserted-word-unchanged` | `SMC-ROM-ENDIAN.S2` | with the control deasserted the word passes through unchanged | DIRECTED | — | `cover-property` | `LIVE` | `rom.adoc#ROM` §Hardware Configuration | — |
| `endian-control-from-efuse-shadow` | `SMC-ROM-ENDIAN.S3` | the control is sourced from the ROM endianness bit of the eFuse shadow-register output | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `rom.adoc#ROM` §Hardware Configuration | — |

### `SMC-FAB-AXI4` — High-performance AXI4 network

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `cpu-to-sram-read` | `SMC-FAB-AXI4.S1` | the CPU cluster reaches SRAM over the AXI4 network | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Network` §Characteristics | — |
| `cpu-to-sram-write` | `SMC-FAB-AXI4.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-in-to-sram` | `SMC-FAB-AXI4.S2` | an external AXI input port reaches a local AXI4 subordinate | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | SF-003 |
| `ext-in-to-plic` | `SMC-FAB-AXI4.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-in-to-clint` | `SMC-FAB-AXI4.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `full-64bit-beat` | `SMC-FAB-AXI4.S3` | the 64-bit data width is preserved end to end on the AXI4 network | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Dual-Network` §Architecture (+1) | — |
| `partial-strobe-beat` | `SMC-FAB-AXI4.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `two-managers-same-subordinate` | `SMC-FAB-AXI4.S4` | **[contested]** [BOUNDED-LIVENESS] two managers targeting one subordinate concurrently both complete within a bound with no response mis-delivery | RANDOMIZED | `manager_mix`, `issue_phase` | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers (+1) | — |
| `three-managers-same-subordinate` | `SMC-FAB-AXI4.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `responses-match-originators` | `SMC-FAB-AXI4.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-FAB-AXIL` — AXI4-Lite peripheral and configuration network

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `mmio-read-peripheral` | `SMC-FAB-AXIL.S1` | a CPU MMIO access reaches a peripheral register block over AXI4-Lite | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Network` §Characteristics | — |
| `mmio-write-peripheral` | `SMC-FAB-AXIL.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `config-reg-read` | `SMC-FAB-AXIL.S2` | fabric configuration registers are reachable over the AXI4-Lite network | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | — |
| `config-reg-write` | `SMC-FAB-AXIL.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `axil-32bit-full-strobe` | `SMC-FAB-AXIL.S3` | internal AXI4-Lite peripheral paths using a 32-bit data width carry a 4-bit strobe | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#AXI` §Interface Widths | — |
| `axil-32bit-partial-strobe` | `SMC-FAB-AXIL.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-FAB-WIDTHS` — AXI signal and ID widths across fabric stages

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sys-addr-low` | `SMC-FAB-WIDTHS.S1` | system-facing external ports carry a 56-bit address | RANDOMIZED | `system_address` | `covergroup` | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| `sys-addr-high` | `SMC-FAB-WIDTHS.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sys-addr-bit55-set` | `SMC-FAB-WIDTHS.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `internal-addr-low` | `SMC-FAB-WIDTHS.S2` | SMC-internal interfaces carry a 32-bit address | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| `internal-addr-high` | `SMC-FAB-WIDTHS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `strobe-all-bytes` | `SMC-FAB-WIDTHS.S3` | the 8-bit write strobe selects bytes within the 64-bit data beat | RANDOMIZED | `write_strobe` | `covergroup` | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| `strobe-single-byte` | `SMC-FAB-WIDTHS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `strobe-non-contiguous` | `SMC-FAB-WIDTHS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `user-zero` | `SMC-FAB-WIDTHS.S4` | the 12-bit user sideband is carried on all AXI4 channels | RANDOMIZED | `user_value` | `covergroup` | `LIVE` | `fabric.adoc#AXI` §Common Signal Widths | — |
| `user-all-ones` | `SMC-FAB-WIDTHS.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `user-preserved-to-subordinate` | `SMC-FAB-WIDTHS.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sys-id-min` | `SMC-FAB-WIDTHS.S5` | the inbound port ID widths of 6, 2 and 6 bits are accepted at the system, JTAG and SEP inputs | RANDOMIZED | `inbound_id` | `covergroup` | `LIVE` | `fabric.adoc#AXI` §ID Widths by Fabric Stage | — |
| `sys-id-max` | `SMC-FAB-WIDTHS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `jtag-id-min` | `SMC-FAB-WIDTHS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `jtag-id-max` | `SMC-FAB-WIDTHS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep-id-min` | `SMC-FAB-WIDTHS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep-id-max` | `SMC-FAB-WIDTHS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `input-fabric-4bit` | `SMC-FAB-WIDTHS.S6` | the ID widens through the declared stages of 4, 6 and 8 bits as crossbars prepend originating-port bits | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#AXI` §ID Widths by Fabric Stage | — |
| `local-output-fabric-6bit` | `SMC-FAB-WIDTHS.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `crossbar-master-8bit` | `SMC-FAB-WIDTHS.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `output-port-8bit` | `SMC-FAB-WIDTHS.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `response-id-matches-request-port` | `SMC-FAB-WIDTHS.S7` | a response returns on the ID of the port that originated the request | DIRECTED | — | `assertion-cover` | `LIVE` | `fabric.adoc#AXI` §ID Widths by Fabric Stage | — |

### `SMC-FAB-OUTSTANDING` — Fabric outstanding-transaction limits

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `outstanding-1` | `SMC-FAB-OUTSTANDING.S1` | the output fabric allows up to MaxTrans of 32 outstanding transactions per AXI ID | RANDOMIZED | `outstanding_depth`, `axi_id` | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| `outstanding-31` | `SMC-FAB-OUTSTANDING.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outstanding-32` | `SMC-FAB-OUTSTANDING.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `crossbar-at-limit` | `SMC-FAB-OUTSTANDING.S2` | the fabric crossbars allow up to FABRIC_MAX_TRANS of 32 outstanding transactions per AXI ID | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| `axil-4-writes-outstanding` | `SMC-FAB-OUTSTANDING.S3` | the AXI4-Lite crossbar allows up to four outstanding writes and four outstanding reads | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| `axil-4-reads-outstanding` | `SMC-FAB-OUTSTANDING.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `err-slv-at-32-outstanding` | `SMC-FAB-OUTSTANDING.S4` | the error slave allows up to ERR_SLV_MAX_TRANS of 32 outstanding transactions across all IDs | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| `backpressure-asserted` | `SMC-FAB-OUTSTANDING.S5` | **[contested]** [BOUNDED-LIVENESS] reaching an outstanding limit backpressures the manager and every accepted transaction still completes within a bound | RANDOMIZED | `issue_rate`, `id_spread` | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| `all-accepted-complete` | `SMC-FAB-OUTSTANDING.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-request-dropped` | `SMC-FAB-OUTSTANDING.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-FAB-MGR-CPU` — CPU cluster manager routing paths

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `local-to-sram` | `SMC-FAB-MGR-CPU.S1` | the local path reaches SRAM, PLIC, CLINT and the watchdog timers with minimal latency | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | SF-003 |
| `local-to-plic` | `SMC-FAB-MGR-CPU.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `local-to-clint` | `SMC-FAB-MGR-CPU.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `local-to-wdt` | `SMC-FAB-MGR-CPU.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cpu-external-path-filtered` | `SMC-FAB-MGR-CPU.S2` | the external path carries CPU traffic through filtering and remapping | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| `cpu-external-path-remapped` | `SMC-FAB-MGR-CPU.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mmio-privileged-access` | `SMC-FAB-MGR-CPU.S3` | the MMIO interface carries register access with privilege-based control | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| `mmio-unprivileged-access` | `SMC-FAB-MGR-CPU.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `l2-coherent-read` | `SMC-FAB-MGR-CPU.S4` | the L2 coherent path carries cache-coherent high-bandwidth operations | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| `l2-coherent-write` | `SMC-FAB-MGR-CPU.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-FAB-MGR-ALIASPATH` — Alias-remapped manager path for DMA, JTAG2AXI and the log engine

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `dma-remapped` | `SMC-FAB-MGR-ALIASPATH.S1` | DMA traffic is alias-remapped and filtered before reaching its destination | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers (+1) | — |
| `dma-filtered` | `SMC-FAB-MGR-ALIASPATH.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `jtag2axi-remapped` | `SMC-FAB-MGR-ALIASPATH.S2` | JTAG2AXI bridge traffic is alias-remapped and filtered before reaching its destination | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| `jtag2axi-filtered` | `SMC-FAB-MGR-ALIASPATH.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `logengine-remapped` | `SMC-FAB-MGR-ALIASPATH.S3` | log engine traffic is alias-remapped and filtered before reaching its destination | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| `logengine-filtered` | `SMC-FAB-MGR-ALIASPATH.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `two-managers-concurrent` | `SMC-FAB-MGR-ALIASPATH.S4` | **[contested]** [BOUNDED-LIVENESS] all three managers active concurrently on the shared remap and filter path all complete or error within a bound | RANDOMIZED | `manager_activity_mix`, `arrival_phase` | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Managers | — |
| `three-managers-concurrent` | `SMC-FAB-MGR-ALIASPATH.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `all-complete-bounded` | `SMC-FAB-MGR-ALIASPATH.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-FAB-ERRSLV` — Error slave for invalid addresses

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `axi4-unmapped-read-decode-error` | `SMC-FAB-ERRSLV.S1` | an unmapped address on the AXI4 network returns a decode error | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | SF-031 |
| `axi4-unmapped-write-decode-error` | `SMC-FAB-ERRSLV.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `axil-unmapped-read-decode-error` | `SMC-FAB-ERRSLV.S2` | an unmapped address on the AXI4-Lite network returns a decode error | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Traffic Subordinates | — |
| `axil-unmapped-write-decode-error` | `SMC-FAB-ERRSLV.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `err-slv-saturated` | `SMC-FAB-ERRSLV.S3` | **[contested]** [BOUNDED-LIVENESS] more unmapped requests arriving than the error slave outstanding limit are backpressured and each still receives its error response | RANDOMIZED | `error_request_rate` | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters | — |
| `every-request-answered` | `SMC-FAB-ERRSLV.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-FAB-ALIAS` — Alias address remapping

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `alias-region-0-configured` | `SMC-FAB-ALIAS.S1` | eight independently configurable regions are present and addressable | DIRECTED | — | `covergroup` | `DECODE` | `fabric.adoc#Alias` §Remapping (+1) | — |
| `alias-region-7-configured` | `SMC-FAB-ALIAS.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `addr-at-region-base` | `SMC-FAB-ALIAS.S2` | an address inside a region's configured input range selects that region | RANDOMIZED | `region_base`, `region_size`, `transaction_address` | `covergroup` | `LIVE` | `fabric.adoc#Alias` §Remapping | — |
| `addr-at-region-top` | `SMC-FAB-ALIAS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `addr-just-below-region` | `SMC-FAB-ALIAS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `addr-just-above-region` | `SMC-FAB-ALIAS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `offset-zero` | `SMC-FAB-ALIAS.S3` | the region's remap offset translates the outgoing address | RANDOMIZED | `remap_offset` | `covergroup` | `LIVE` | `fabric.adoc#Alias` §Remapping | — |
| `offset-positive` | `SMC-FAB-ALIAS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `offset-crosses-4gib` | `SMC-FAB-ALIAS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cacheable-set` | `SMC-FAB-ALIAS.S4` | the region's cacheable flag is applied to the locally initiated transaction | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Alias` §Remapping (+1) | — |
| `cacheable-clear` | `SMC-FAB-ALIAS.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `transparent-at-reset` | `SMC-FAB-ALIAS.S5` | at reset the remap logic is transparent and the local alias base 0xC000_0000 addresses local resources | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Alias` §Remapping | — |
| `local-alias-base-reaches-local-resource` | `SMC-FAB-ALIAS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reprogram-during-inflight` | `SMC-FAB-ALIAS.S6` | **[contested]** [BOUNDED-LIVENESS] reprogramming a region while a matching transaction is in flight leaves that transaction with a single defined translation and a bounded completion | DIRECTED | — | `assertion-cover` | `LIVE` | `fabric.adoc#Alias` §Remapping | — |
| `single-translation-applied` | `SMC-FAB-ALIAS.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `completion-bounded` | `SMC-FAB-ALIAS.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-FAB-PRIVREMAP` — Privilege-controlled output remapping

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `mmode-region-base` | `SMC-FAB-PRIVREMAP.S1` | the M-mode remap region is based at MmodeBaseAddr 0x100_0000 relative to the SMC base | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters (+1) | SF-043, SF-055 |
| `mmode-region-top` | `SMC-FAB-PRIVREMAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `xvisor-region-base` | `SMC-FAB-PRIVREMAP.S2` | the Xvisor remap region is based at XvisorBaseAddr 0x180_0000 relative to the SMC base | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Fabric` §Configuration Parameters (+1) | SF-055 |
| `xvisor-region-top` | `SMC-FAB-PRIVREMAP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mmode-master-uses-mmode-remap` | `SMC-FAB-PRIVREMAP.S3` | the translation applied is selected by the originating master's privilege level | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Privilege-Controlled` §Remapping | — |
| `xvisor-master-uses-xvisor-remap` | `SMC-FAB-PRIVREMAP.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `noremap-configuration` | `SMC-FAB-PRIVREMAP.S4` | with NoRemap set the remapping is disabled | DIRECTED | — | `cover-property` | `DECODE` | `fabric.adoc#Fabric` §Configuration Parameters | — |

### `SMC-FAB-APERTURE` — SMC aperture CSRs

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `region-size-reset-16mib` | `SMC-FAB-APERTURE.S1` | REGION_SIZE resets to 0x0100_0000 | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access (+1) | — |
| `region-size-smaller` | `SMC-FAB-APERTURE.S2` | reprogramming REGION_SIZE resizes the local-alias window and the global aperture by the same amount | RANDOMIZED | `region_size_value` | `covergroup` | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | SF-032 |
| `region-size-larger` | `SMC-FAB-APERTURE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `windows-equal-after-reprogram` | `SMC-FAB-APERTURE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `global-base-readable` | `SMC-FAB-APERTURE.S3` | GLOBAL_BASE and LOCAL_BASE describe the aperture and are readable by firmware | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access (+1) | — |
| `local-base-readonly-c0000000` | `SMC-FAB-APERTURE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `region-size-zero` | `SMC-FAB-APERTURE.S4` | programming REGION_SIZE to zero collapses both windows and routes SMC CPU accesses to its own resources out through the output fabric | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | SF-032 |
| `local-access-leaves-through-output-fabric` | `SMC-FAB-APERTURE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reprogram-region-size-inflight` | `SMC-FAB-APERTURE.S5` | **[contested]** [BOUNDED-LIVENESS] REGION_SIZE reprogrammed with a transaction in flight leaves that transaction with one defined routing and a bounded completion | DIRECTED | — | `assertion-cover` | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | — |
| `single-routing-applied` | `SMC-FAB-APERTURE.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `completion-bounded` | `SMC-FAB-APERTURE.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-FILT-IN` — Inbound traffic filtering

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `inbound-entry-0` | `SMC-FILT-IN.S1` | sixteen independent inbound filter entries are present and individually configurable | DIRECTED | — | `covergroup` | `DECODE` | `fabric.adoc#Inbound` §Filtering (+1) | — |
| `inbound-entry-15` | `SMC-FILT-IN.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `addr-at-zone-base` | `SMC-FILT-IN.S2` | a transaction inside a configured address zone is admitted | RANDOMIZED | `zone_base`, `zone_size`, `inbound_address` | `covergroup` | `LIVE` | `fabric.adoc#Inbound` §Filtering | SF-014 |
| `addr-at-zone-top` | `SMC-FILT-IN.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `addr-outside-zone` | `SMC-FILT-IN.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `srcid-match-admitted` | `SMC-FILT-IN.S3` | source ID authorization admits a trusted originator and blocks an untrusted one | RANDOMIZED | `source_id`, `srcid_match_config` | `covergroup` | `LIVE` | `fabric.adoc#Inbound` §Filtering | SF-015 |
| `srcid-mismatch-blocked` | `SMC-FILT-IN.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `prot-secure` | `SMC-FILT-IN.S4` | protection attribute filtering distinguishes secure from non-secure and privileged from user transactions | RANDOMIZED | `axi_prot` | `covergroup` | `LIVE` | `fabric.adoc#Inbound` §Filtering (+1) | — |
| `prot-nonsecure` | `SMC-FILT-IN.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `prot-user` | `SMC-FILT-IN.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `prot-privileged` | `SMC-FILT-IN.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `inbound-no-match-blocked` | `SMC-FILT-IN.S5` | inbound traffic matching no entry is blocked | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Traffic` §Filtering | SF-014, SF-030 |
| `default-blocks-all-external` | `SMC-FILT-IN.S6` | the default inbound configuration blocks all external transactions until firmware programs an access policy | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Inbound` §Filtering | SF-030 |
| `first-policy-opens-one-zone` | `SMC-FILT-IN.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `entry-reprogram-during-inflight` | `SMC-FILT-IN.S7` | **[contested]** [BOUNDED-LIVENESS] reprogramming an entry while a matching inbound transaction is in flight yields one defined admit-or-block decision within a bound | DIRECTED | — | `assertion-cover` | `LIVE` | `fabric.adoc#Inbound` §Filtering | — |
| `single-decision-applied` | `SMC-FILT-IN.S7` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-FILT-OUT` — Outbound traffic filtering

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `outbound-entry-0` | `SMC-FILT-OUT.S1` | sixteen independent outbound filter entries are present, each a 32-byte control block on AXI4-Lite | DIRECTED | — | `covergroup` | `DECODE` | `fabric.adoc#Outbound` §Traffic Filter Control Registers (+1) | — |
| `outbound-entry-15` | `SMC-FILT-OUT.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `outbound-entry-stride-32b` | `SMC-FILT-OUT.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `dest-in-allowed-range` | `SMC-FILT-OUT.S2` | destination address matching permits or blocks the outbound access | RANDOMIZED | `dest_address`, `entry_range` | `covergroup` | `LIVE` | `fabric.adoc#Outbound` §Filtering | SF-014 |
| `dest-in-blocked-range` | `SMC-FILT-OUT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outbound-ns-secure` | `SMC-FILT-OUT.S3` | the NS security attribute participates in the outbound match | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Outbound` §Filtering | — |
| `outbound-ns-nonsecure` | `SMC-FILT-OUT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outbound-srcid-match` | `SMC-FILT-OUT.S4` | source ID participates in the outbound match | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Outbound` §Filtering | SF-015 |
| `outbound-srcid-mismatch` | `SMC-FILT-OUT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outbound-no-match-permitted` | `SMC-FILT-OUT.S5` | outbound traffic matching no entry is permitted | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Traffic` §Filtering | SF-014, SF-031 |
| `filter-sees-remapped-address` | `SMC-FILT-OUT.S6` | outbound filtering is applied after any privilege remap stage, on the remapped address | DIRECTED | — | `assertion-cover` | `LIVE` | `fabric.adoc#Outbound` §Filtering | — |

### `SMC-FILT-NS` — Non-secure bit equality matching

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `allow-ns-0-matches-secure` | `SMC-FILT-NS.S1` | an entry with allow_ns cleared matches only secure transactions | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | — |
| `allow-ns-0-skips-nonsecure` | `SMC-FILT-NS.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `allow-ns-1-matches-nonsecure` | `SMC-FILT-NS.S2` | an entry with allow_ns set matches only non-secure transactions | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | — |
| `allow-ns-1-skips-secure` | `SMC-FILT-NS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `fallthrough-to-later-entry` | `SMC-FILT-NS.S3` | an entry whose allow_ns does not match does not deny; the transaction falls through to the remaining entries | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | SF-014 |
| `later-entry-admits` | `SMC-FILT-NS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `one-entry-covers-one-state` | `SMC-FILT-NS.S4` | covering both security states over one address range requires two entries | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | SF-014 |
| `two-entries-cover-both-states` | `SMC-FILT-NS.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `write-prot-mismatch-decode-error` | `SMC-FILT-NS.S5` | a transaction no entry admits is routed to the error slave and receives a decode error response | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Non-Secure` §Bit Filtering (AXI4 Filters) | SF-031 |
| `read-prot-mismatch-decode-error` | `SMC-FILT-NS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-FILT-AXIL-PROT` — AXI-Lite full protection matching

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `awprot-exact-match` | `SMC-FILT-AXIL-PROT.S1` | a write whose prot equals awprot_requirement is allowed through | RANDOMIZED | `awprot_requirement`, `transaction_awprot` | `covergroup` | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| `awprot-one-bit-off` | `SMC-FILT-AXIL-PROT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `arprot-exact-match` | `SMC-FILT-AXIL-PROT.S2` | a read whose prot equals arprot_requirement is allowed through | RANDOMIZED | `arprot_requirement`, `transaction_arprot` | `covergroup` | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| `arprot-one-bit-off` | `SMC-FILT-AXIL-PROT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `write-filter-enabled` | `SMC-FILT-AXIL-PROT.S3` | the write and read filter enables individually gate the filtering | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| `write-filter-disabled` | `SMC-FILT-AXIL-PROT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `read-filter-enabled` | `SMC-FILT-AXIL-PROT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `read-filter-disabled` | `SMC-FILT-AXIL-PROT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `nonmatching-write-error` | `SMC-FILT-AXIL-PROT.S4` | a transaction whose protection value does not match receives an error response | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) | — |
| `nonmatching-read-error` | `SMC-FILT-AXIL-PROT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `gpio-poc-access-filtered` | `SMC-FILT-AXIL-PROT.S5` | the filter guards the GPIO PoC and PBias control block | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Full` §3-Bit Protection Matching (AXI-Lite) (+1) | SF-054 |

### `SMC-FAB-PROT-PASS` — Protection bit pass-through

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `awprot-all-eight-values-preserved` | `SMC-FAB-PROT-PASS.S1` | aw.prot reaches the downstream slave unmodified | RANDOMIZED | `awprot_value` | `covergroup` | `LIVE` | `fabric.adoc#Protection` §Bit Pass-Through | — |
| `arprot-all-eight-values-preserved` | `SMC-FAB-PROT-PASS.S2` | ar.prot reaches the downstream slave unmodified | RANDOMIZED | `arprot_value` | `covergroup` | `LIVE` | `fabric.adoc#Protection` §Bit Pass-Through | — |

### `SMC-FAB-SRCID` — Outbound source ID and traffic path selection

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `srcid-smc-id-on-direct-path` | `SMC-FAB-SRCID.S1` | direct-to-NoC traffic carries SMC_ID | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Source` §ID by Traffic Path | SF-015 |
| `srcid-other-id-on-xvisor-path` | `SMC-FAB-SRCID.S2` | Xvisor-remapped traffic carries OTHER_ID | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Source` §ID by Traffic Path | SF-015 |
| `srcid-mmode-id-on-mmode-path` | `SMC-FAB-SRCID.S3` | M-mode-remapped traffic carries MMODE_ID | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Source` §ID by Traffic Path | SF-015 |
| `shared-resource-through-xvisor-remap` | `SMC-FAB-SRCID.S4` | traffic for shared resources passes through the appropriate privilege-controlled remap stage | DIRECTED | — | `covergroup` | `LIVE` | `fabric.adoc#Outbound` §Traffic Flow | — |
| `shared-resource-through-mmode-remap` | `SMC-FAB-SRCID.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `private-traffic-bypasses-remap` | `SMC-FAB-SRCID.S5` | traffic for private memory or memory-mapped I/O bypasses the remap stages and goes directly to the system NoC | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Outbound` §Traffic Flow | — |

### `SMC-FAB-EXTPORT` — External AXI ports

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sys-axi-in-read` | `SMC-FAB-EXTPORT.S1` | sys_axi_in accepts a transaction with a 6-bit ID, 56-bit address, 64-bit data and 12-bit user | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#sys_axi_in_req_i@f2cb50de | — |
| `sys-axi-in-write` | `SMC-FAB-EXTPORT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `jtag-axi-in-read` | `SMC-FAB-EXTPORT.S2` | jtag_axi_in accepts a transaction with a 2-bit ID | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#jtag_axi_in_req_i@f2cb50de | — |
| `jtag-axi-in-write` | `SMC-FAB-EXTPORT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep-axi-in-read` | `SMC-FAB-EXTPORT.S3` | sep_axi_in accepts a transaction with a 6-bit ID | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#sep_axi_in_req_i@f2cb50de | — |
| `sep-axi-in-write` | `SMC-FAB-EXTPORT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `output-axi-read` | `SMC-FAB-EXTPORT.S4` | output_axi presents filtered and remapped traffic with an 8-bit ID | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#output_axi_req_o@f2cb50de | — |
| `output-axi-write` | `SMC-FAB-EXTPORT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `output-axi-id-8bit` | `SMC-FAB-EXTPORT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `unused-port-tied-idle` | `SMC-FAB-EXTPORT.S5` | an unused inbound port tied to zero introduces no fabric activity | DIRECTED | — | `assertion-cover` | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#sys_axi_in_req_i@f2cb50de | — |

### `SMC-FAB-HANGDET` — AXI hang detection and reporting

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sys-axi-hang-detected` | `SMC-FAB-HANGDET.S1` | a stalled sys_axi master raises its hang detector interrupt | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `sep-axi-hang-detected` | `SMC-FAB-HANGDET.S2` | a stalled sep_axi master raises its hang detector interrupt | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `data-accel-hang-detected` | `SMC-FAB-HANGDET.S3` | a stalled data_accel master raises its hang detector interrupt | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `or-asserted-single-detector` | `SMC-FAB-HANGDET.S4` | the interrupt asserts while any of the three detectors is high | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `or-asserted-multiple-detectors` | `SMC-FAB-HANGDET.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `or-deasserted-none` | `SMC-FAB-HANGDET.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `identify-sys-axi` | `SMC-FAB-HANGDET.S5` | software identifies the stalled master by reading the per-path hang detector control registers | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map (+1) | — |
| `identify-sep-axi` | `SMC-FAB-HANGDET.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `identify-data-accel` | `SMC-FAB-HANGDET.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hang-condition-cleared` | `SMC-FAB-HANGDET.S6` | the condition is cleared through the same hang detector control registers | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `interrupt-deasserts-after-clear` | `SMC-FAB-HANGDET.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `second-hang-during-first` | `SMC-FAB-HANGDET.S7` | **[contested]** [BOUNDED-LIVENESS] a second detector asserting while the first is still asserted keeps the aggregate interrupt high and both remain individually identifiable | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `both-identifiable` | `SMC-FAB-HANGDET.S7` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `clear-one-leaves-other-asserted` | `SMC-FAB-HANGDET.S7` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-DMA-REGIF` — DMA control register interface

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `dma-aperture-base` | `SMC-DMA-REGIF.S1` | the 512-byte aperture from 0xC003_8000 through 0xC003_81FF decodes to the DMA controller | DIRECTED | — | `covergroup` | `DECODE` | `dma.adoc#DMA` §Controller Integration (+1) | — |
| `dma-aperture-top` | `SMC-DMA-REGIF.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `dma-just-above-top-not-dma` | `SMC-DMA-REGIF.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `dma-reg-read` | `SMC-DMA-REGIF.S2` | AXI4-Lite reads and writes of 64-bit data within the 9-bit address space complete correctly | RANDOMIZED | `register_offset`, `write_data` | `covergroup` | `LIVE` | `dma.adoc#Control` §Interface | SF-008 |
| `dma-reg-write` | `SMC-DMA-REGIF.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dma-reg-readback-matches` | `SMC-DMA-REGIF.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `atomic-command-submit` | `SMC-DMA-REGIF.S3` | command submission and status reading are atomic | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Control` §Interface | — |
| `atomic-status-read` | `SMC-DMA-REGIF.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-XFER` — DMA transfer types

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `len-one-byte` | `SMC-DMA-XFER.S1` | a linear source-to-destination transfer moves the programmed byte count correctly | RANDOMIZED | `src_address`, `dst_address`, `transfer_length` | `covergroup` | `LIVE` | `dma.adoc#Transfer` §Capabilities | SF-008 |
| `len-single-beat` | `SMC-DMA-XFER.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `len-multi-burst` | `SMC-DMA-XFER.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dest-contents-match` | `SMC-DMA-XFER.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `src-stride-equal-width` | `SMC-DMA-XFER.S2` | a 2D transfer applies the programmed source stride | RANDOMIZED | `src_stride`, `row_count` | `covergroup` | `LIVE` | `dma.adoc#Transfer` §Capabilities (+1) | SF-008 |
| `src-stride-greater` | `SMC-DMA-XFER.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `src-stride-zero` | `SMC-DMA-XFER.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dst-stride-equal-width` | `SMC-DMA-XFER.S3` | a 2D transfer applies the programmed destination stride | RANDOMIZED | `dst_stride`, `row_count` | `covergroup` | `LIVE` | `dma.adoc#Transfer` §Capabilities | SF-008 |
| `dst-stride-greater` | `SMC-DMA-XFER.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dst-stride-zero` | `SMC-DMA-XFER.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `repeat-one` | `SMC-DMA-XFER.S4` | the programmed repeat count is executed | RANDOMIZED | `repeat_count` | `covergroup` | `LIVE` | `dma.adoc#Transfer` §Capabilities (+1) | — |
| `repeat-many` | `SMC-DMA-XFER.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `repeat-boundary` | `SMC-DMA-XFER.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sg-two-segments` | `SMC-DMA-XFER.S5` | a scatter-gather transfer moves non-contiguous regions using hardware descriptor parsing | RANDOMIZED | `segment_count`, `segment_sizes` | `covergroup` | `LIVE` | `dma.adoc#Transfer` §Capabilities (+1) | — |
| `sg-many-segments` | `SMC-DMA-XFER.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sg-descriptor-parsed-in-hw` | `SMC-DMA-XFER.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `src-unaligned` | `SMC-DMA-XFER.S6` | unaligned source and destination addresses are handled automatically | RANDOMIZED | `src_alignment`, `dst_alignment` | `covergroup` | `LIVE` | `dma.adoc#Transfer` §Parameters | — |
| `dst-unaligned` | `SMC-DMA-XFER.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `both-unaligned` | `SMC-DMA-XFER.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `both-aligned` | `SMC-DMA-XFER.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reset-during-address-phase` | `SMC-DMA-XFER.S7` | **[contested]** [BOUNDED-LIVENESS] a reset asserted mid-transfer terminates the transfer within a bound and leaves no AXI response outstanding | RANDOMIZED | `reset_phase` | `covergroup` | `LIVE` | `dma.adoc#Response` §Path (+1) | — |
| `reset-during-data-phase` | `SMC-DMA-XFER.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-outstanding-after-reset` | `SMC-DMA-XFER.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-STREAM0` — Stream 0 transfer launch and tracking

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `next-id-0-launches-transfer` | `SMC-DMA-STREAM0.S1` | reading NEXT_ID_0 launches a transfer from the shared source, destination, length, stride and repetition registers | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Stream` §Support | — |
| `shared-registers-consumed` | `SMC-DMA-STREAM0.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `next-id-0-nonzero-on-valid-setup` | `SMC-DMA-STREAM0.S2` | the launched transfer is tagged with stream index 0 and NEXT_ID_0 returns a non-zero identifier for a correctly set-up command | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Stream` §Support | SF-034 |
| `next-id-0-zero-on-invalid-setup` | `SMC-DMA-STREAM0.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `status0-busy-during` | `SMC-DMA-STREAM0.S3` | STATUS_0 and DONE_0 track the launched transfer through to completion | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Stream` §Support (+1) | — |
| `done0-set-on-completion` | `SMC-DMA-STREAM0.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `done0-cleared-after-read` | `SMC-DMA-STREAM0.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `next-id-read-while-busy` | `SMC-DMA-STREAM0.S4` | **[contested]** [BOUNDED-LIVENESS] a NEXT_ID_0 read while a transfer is already in flight reaches a bounded defined outcome without corrupting the in-flight transfer | DIRECTED | — | `assertion-cover` | `LIVE` | `dma.adoc#Stream` §Support (+1) | — |
| `inflight-transfer-uncorrupted` | `SMC-DMA-STREAM0.S4` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-DMA-STREAM-RSVD` — Reserved DMA stream banks

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `next-id-1-read` | `SMC-DMA-STREAM-RSVD.S1` | reading NEXT_ID_1 through NEXT_ID_15 starts no transfer, returns zero and produces no bus error | RANDOMIZED | `stream_index` | `covergroup` | `LIVE` | `dma.adoc#Stream` §Support | SF-034 |
| `next-id-15-read` | `SMC-DMA-STREAM-RSVD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-transfer-started` | `SMC-DMA-STREAM-RSVD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-bus-error` | `SMC-DMA-STREAM-RSVD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `returns-zero` | `SMC-DMA-STREAM-RSVD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `status-reserved-zero-idle` | `SMC-DMA-STREAM-RSVD.S2` | STATUS_1 through STATUS_15 are tied to zero and never update | RANDOMIZED | `stream_index` | `covergroup` | `LIVE` | `dma.adoc#Stream` §Support | — |
| `status-reserved-zero-during-stream0-transfer` | `SMC-DMA-STREAM-RSVD.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `done-reserved-zero-idle` | `SMC-DMA-STREAM-RSVD.S3` | DONE_1 through DONE_15 are tied to zero and never update | RANDOMIZED | `stream_index` | `covergroup` | `LIVE` | `dma.adoc#Stream` §Support | — |
| `done-reserved-zero-after-stream0-completion` | `SMC-DMA-STREAM-RSVD.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `all-16-banks-decode` | `SMC-DMA-STREAM-RSVD.S4` | every stream bank decodes normally regardless of the configured stream count | DIRECTED | — | `covergroup` | `DECODE` | `dma.adoc#Stream` §Support (+1) | — |
| `reserved-read-during-stream0-busy` | `SMC-DMA-STREAM-RSVD.S5` | **[contested]** [BOUNDED-LIVENESS] a reserved-bank read while stream 0 is busy completes within a bound and does not disturb the active transfer | DIRECTED | — | `assertion-cover` | `LIVE` | `dma.adoc#Stream` §Support | — |
| `stream0-unaffected` | `SMC-DMA-STREAM-RSVD.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-DMA-BURST` — DMA burst optimization

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `burst-len-1` | `SMC-DMA-BURST.S1` | burst lengths are calculated to move the request efficiently | RANDOMIZED | `transfer_length`, `start_offset` | `covergroup` | `LIVE` | `dma.adoc#Performance` §Features | — |
| `burst-len-max` | `SMC-DMA-BURST.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `burst-len-mid` | `SMC-DMA-BURST.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `burst-crosses-page-fragmented` | `SMC-DMA-BURST.S2` | a burst that would cross a page boundary is fragmented at that boundary | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Performance` §Features | — |
| `burst-within-page-not-fragmented` | `SMC-DMA-BURST.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `unaligned-head-handled` | `SMC-DMA-BURST.S3` | an unaligned start address is aligned before burst issue without losing or duplicating data | RANDOMIZED | `start_offset`, `transfer_length` | `covergroup` | `LIVE` | `dma.adoc#AXI4` §Master Characteristics | — |
| `unaligned-tail-handled` | `SMC-DMA-BURST.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `byte-count-exact` | `SMC-DMA-BURST.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-OUTSTANDING` — DMA outstanding transaction management

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `outstanding-1` | `SMC-DMA-OUTSTANDING.S1` | **[contested]** up to DMA_MST_MAX_TXNS of 16 AXI transactions are concurrently outstanding per master interface | RANDOMIZED | `memory_response_latency` | `covergroup` | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| `outstanding-15` | `SMC-DMA-OUTSTANDING.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outstanding-16` | `SMC-DMA-OUTSTANDING.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `in-order-responses` | `SMC-DMA-OUTSTANDING.S2` | the internal re-order buffer of depth 3 restores in-order data delivery | RANDOMIZED | `response_order` | `covergroup` | `LIVE` | `dma.adoc#AXI4` §Master Characteristics | — |
| `out-of-order-responses-reordered` | `SMC-DMA-OUTSTANDING.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reorder-buffer-full` | `SMC-DMA-OUTSTANDING.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `raw-coupling-enabled` | `SMC-DMA-OUTSTANDING.S3` | read and write address coupling is enabled by default | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| `raw-coupling-disabled` | `SMC-DMA-OUTSTANDING.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `limit-reached-backpressure` | `SMC-DMA-OUTSTANDING.S4` | **[contested]** [BOUNDED-LIVENESS] at the outstanding limit the backend is backpressured and every issued transaction still completes within a bound | RANDOMIZED | `memory_stall_pattern` | `covergroup` | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| `all-issued-complete` | `SMC-DMA-OUTSTANDING.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-FIFO` — DMA frontend and midend buffering

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `f2m-empty` | `SMC-DMA-FIFO.S1` | the depth-4 frontend-to-midend FIFO pipelines commands | RANDOMIZED | `command_issue_rate` | `covergroup` | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| `f2m-partially-full` | `SMC-DMA-FIFO.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `f2m-full` | `SMC-DMA-FIFO.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `m2b-passthrough-no-buffering` | `SMC-DMA-FIFO.S2` | the midend-to-backend stage with depth zero passes requests through with no FIFO | DIRECTED | — | `cover-property` | `LIVE` | `dma.adoc#DMA` §Configuration Parameters | — |
| `sustained-backpressure` | `SMC-DMA-FIFO.S3` | **[contested]** [BOUNDED-LIVENESS] back-pressure from a system overload is absorbed without losing a command | RANDOMIZED | `backpressure_duration`, `command_burst_size` | `covergroup` | `LIVE` | `dma.adoc#Command` §Processing | — |
| `command-count-preserved` | `SMC-DMA-FIFO.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-command-dropped` | `SMC-DMA-FIFO.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-ARB` — DMA request manager routing and arbitration

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `single-intf-passthrough` | `SMC-DMA-ARB.S1` | with a single control interface and a single master interface the manager is a passthrough with no arbitration overhead | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#DMA` §Request Manager (+1) | — |
| `no-arbitration-latency` | `SMC-DMA-ARB.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `round-robin-order-observed` | `SMC-DMA-ARB.S2` | with multiple interfaces each master arbiter selects among pending control interface requests round robin | RANDOMIZED | `pending_request_pattern` | `covergroup` | `LIVE` | `dma.adoc#Request` §Arbitration | — |
| `no-starvation` | `SMC-DMA-ARB.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `request-masked-after-accept` | `SMC-DMA-ARB.S3` | once a master accepts a request, that request is masked from other masters until completion | DIRECTED | — | `assertion-cover` | `LIVE` | `dma.adoc#Request` §Arbitration | — |
| `no-duplicate-execution` | `SMC-DMA-ARB.S3` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `tracking-fifo-one-entry` | `SMC-DMA-ARB.S4` | the depth-4 tracking FIFO records which control interface originated each accepted request | RANDOMIZED | `concurrent_request_count` | `covergroup` | `LIVE` | `dma.adoc#Request` §Tracking | — |
| `tracking-fifo-full` | `SMC-DMA-ARB.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `response-routed-to-originator` | `SMC-DMA-ARB.S5` | on completion the tracked ID is popped and the response is routed back to the originating control interface | DIRECTED | — | `assertion-cover` | `LIVE` | `dma.adoc#Response` §Routing | — |
| `response-buffer-occupied` | `SMC-DMA-ARB.S6` | the single-entry response buffer decouples master and control interface timing | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Response` §Routing | — |
| `response-buffer-drained` | `SMC-DMA-ARB.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `simultaneous-responses` | `SMC-DMA-ARB.S7` | **[contested]** [BOUNDED-LIVENESS] simultaneous responses to one control interface are resolved by second-level round robin and all are delivered without deadlock | RANDOMIZED | `response_collision_pattern` | `covergroup` | `LIVE` | `dma.adoc#Response` §Routing | — |
| `all-responses-delivered` | `SMC-DMA-ARB.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-deadlock` | `SMC-DMA-ARB.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-CTRL` — DMA configuration lock and transfer abort

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `config-locked-during-transfer` | `SMC-DMA-CTRL.S1` | the configuration lock prevents modification while a transfer is active | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Control` §Interface | SF-016 |
| `config-writable-when-idle` | `SMC-DMA-CTRL.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `locked-write-attempted` | `SMC-DMA-CTRL.S2` | **[contested]** [BOUNDED-LIVENESS] a configuration write attempted while locked reaches a bounded defined outcome and does not corrupt the active transfer | DIRECTED | — | `assertion-cover` | `LIVE` | `dma.adoc#Control` §Interface | SF-016 |
| `active-transfer-uncorrupted` | `SMC-DMA-CTRL.S2` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `write-outcome-defined` | `SMC-DMA-CTRL.S2` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `abort-stops-transfer` | `SMC-DMA-CTRL.S3` | an abort request stops the transfer safely | DIRECTED | — | `cover-property` | `LIVE` | `dma.adoc#Status` §Monitoring and Control | SF-017 |
| `state-readable-after-abort` | `SMC-DMA-CTRL.S4` | transfer state is preserved across the abort for software inspection | DIRECTED | — | `cover-property` | `LIVE` | `dma.adoc#Status` §Monitoring and Control | SF-017 |
| `abort-during-address-phase` | `SMC-DMA-CTRL.S5` | **[contested]** [BOUNDED-LIVENESS] an abort raised while AXI beats are in flight settles within a bound with no orphaned outstanding response | RANDOMIZED | `abort_phase`, `outstanding_count` | `covergroup` | `LIVE` | `dma.adoc#Status` §Monitoring and Control (+1) | SF-017 |
| `abort-during-data-phase` | `SMC-DMA-CTRL.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-orphan-outstanding` | `SMC-DMA-CTRL.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-ERR` — DMA error reporting and classification

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `read-error-recorded` | `SMC-DMA-ERR.S1` | an AXI error response during a transfer is recorded in the error status | RANDOMIZED | `error_beat_index`, `error_type` | `covergroup` | `LIVE` | `dma.adoc#Status` §Monitoring and Control | — |
| `write-error-recorded` | `SMC-DMA-ERR.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `error-visible-before-completion` | `SMC-DMA-ERR.S2` | the error classification is visible to software immediately rather than only at completion | DIRECTED | — | `cover-property` | `LIVE` | `dma.adoc#Control` §Interface | — |
| `second-error-before-status-read` | `SMC-DMA-ERR.S3` | **[contested]** [BOUNDED-LIVENESS] a second AXI error arriving while the first is still unread reaches a defined and observable status | DIRECTED | — | `assertion-cover` | `LIVE` | `dma.adoc#Status` §Monitoring and Control | — |
| `status-defined-after-two-errors` | `SMC-DMA-ERR.S3` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-DMA-IRQ` — DMA completion interrupt

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `pulse-on-busy-falling-edge` | `SMC-DMA-IRQ.S1` | the completion pulse is generated on the falling edge of the DMA busy output | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| `no-pulse-while-busy-high` | `SMC-DMA-IRQ.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `bit-322-asserted-on-completion` | `SMC-DMA-IRQ.S2` | the completion pulse appears at cpu_interrupts_o bit 322 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| `interrupt-enabled` | `SMC-DMA-IRQ.S3` | interrupt generation is configurable and maskable | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Status` §Monitoring and Control | — |
| `interrupt-masked` | `SMC-DMA-IRQ.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DMA-CG` — DMA clock gating

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `all-three-blocks-gated-together` | `SMC-DMA-CG.S1` | one gater gates the frontend, request manager and backend together | DIRECTED | — | `cover-property` | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| `enable-from-frontend-wakeup` | `SMC-DMA-CG.S2` | the clock is enabled when the frontend wakes or the backend is busy | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| `enable-from-backend-busy` | `SMC-DMA-CG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `gated-when-neither` | `SMC-DMA-CG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hysteresis-0` | `SMC-DMA-CG.S3` | the 6-bit hysteresis delays gating by the configured number of cycles | RANDOMIZED | `cg_hysteresis_value` | `covergroup` | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| `hysteresis-63` | `SMC-DMA-CG.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hysteresis-mid` | `SMC-DMA-CG.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cg-enabled` | `SMC-DMA-CG.S4` | cg_enable_i enables and disables clock gating | DIRECTED | — | `covergroup` | `LIVE` | `dma.adoc#Clock` §Gating Configuration | — |
| `cg-disabled-clock-free-running` | `SMC-DMA-CG.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `test-mode-bypasses-gating` | `SMC-DMA-CG.S5` | clock gating is bypassed during test mode | DIRECTED | — | `cover-property` | `LIVE` | `dma.adoc#Clock` §Gating Configuration (+1) | — |

### `SMC-ZERO-REGIF` — Zeroer register interface and trigger

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `zeroer-aperture-base` | `SMC-ZERO-REGIF.S1` | the 512-byte aperture from 0xC003_8200 through 0xC003_83FF decodes to the zeroer | DIRECTED | — | `covergroup` | `DECODE` | `zeroer.adoc#Memory` §Zeroer Integration (+1) | — |
| `zeroer-aperture-top` | `SMC-ZERO-REGIF.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `zeroer-distinct-from-dma-aperture` | `SMC-ZERO-REGIF.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `dest-addr-readback` | `SMC-ZERO-REGIF.S2` | the 64-bit DEST_ADDR and 64-bit SIZE registers are programmed and read back | RANDOMIZED | `dest_address`, `size_value` | `covergroup` | `LIVE` | `zeroer.adoc#Configuration` §and Control | SF-009 |
| `size-readback` | `SMC-ZERO-REGIF.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `trigger-write-starts-operation` | `SMC-ZERO-REGIF.S3` | a write to the control and status register triggers the operation and the busy status reflects it | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Operation` §Flow | — |
| `busy-set-on-start` | `SMC-ZERO-REGIF.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `busy-cleared-on-completion` | `SMC-ZERO-REGIF.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `valid-config-accepted` | `SMC-ZERO-REGIF.S4` | hardware validates the configuration parameters before starting | RANDOMIZED | `dest_address`, `size_value` | `covergroup` | `LIVE` | `zeroer.adoc#Configuration` §and Control | SF-009, SF-018 |
| `invalid-config-rejected` | `SMC-ZERO-REGIF.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-ZERO-FSM` — Zeroer three-state operation

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `idle-state-no-axi-activity` | `SMC-ZERO-FSM.S1` | ST_IDLE waits for configuration and trigger and issues nothing | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#State` §Machine States | SF-018 |
| `address-phase-issues-aw` | `SMC-ZERO-FSM.S2` | ST_ISSUE_ADDR issues the calculated AXI write addresses | DIRECTED | — | `cover-property` | `LIVE` | `zeroer.adoc#State` §Machine States (+1) | — |
| `data-phase-beat-count-matches-addresses` | `SMC-ZERO-FSM.S3` | ST_ISSUE_DATA streams zero data matching the issued address beats | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#State` §Machine States | — |
| `return-to-idle` | `SMC-ZERO-FSM.S4` | the machine returns to idle with a status update once the operation completes | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Operation` §Flow | — |
| `completion-status-updated` | `SMC-ZERO-FSM.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `abort-returns-to-idle` | `SMC-ZERO-FSM.S5` | an in-progress operation can be aborted safely | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Data` §Generation and Control | SF-019 |
| `memory-left-in-defined-state` | `SMC-ZERO-FSM.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `trigger-while-busy` | `SMC-ZERO-FSM.S6` | **[contested]** [BOUNDED-LIVENESS] a trigger written while the zeroer is busy reaches a bounded defined outcome and does not corrupt the running operation | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#Operation` §Flow (+1) | — |
| `running-operation-uncorrupted` | `SMC-ZERO-FSM.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `outcome-defined` | `SMC-ZERO-FSM.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `reset-in-address-phase` | `SMC-ZERO-FSM.S7` | **[contested]** [BOUNDED-LIVENESS] a reset asserted mid-burst returns the machine to idle within a bound with no AXI response outstanding | RANDOMIZED | `reset_phase` | `covergroup` | `LIVE` | `zeroer.adoc#State` §Machine (+1) | — |
| `reset-in-data-phase` | `SMC-ZERO-FSM.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `idle-after-reset` | `SMC-ZERO-FSM.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-outstanding-after-reset` | `SMC-ZERO-FSM.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `abort-with-outstanding-responses` | `SMC-ZERO-FSM.S8` | **[contested]** [BOUNDED-LIVENESS] an abort raised with write responses still outstanding settles within a bound | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#Data` §Generation and Control (+1) | SF-019 |
| `settles-bounded` | `SMC-ZERO-FSM.S8` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-ZERO-AXI` — Zeroer AXI master interface

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `zeroer-addr-56bit` | `SMC-ZERO-AXI.S1` | the master presents a 56-bit address, 64-bit data, 4-bit ID and 12-bit user field | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | SF-009 |
| `zeroer-data-64bit` | `SMC-ZERO-AXI.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `zeroer-id-4bit` | `SMC-ZERO-AXI.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `zeroer-user-12bit` | `SMC-ZERO-AXI.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `burst-1-beat` | `SMC-ZERO-AXI.S2` | bursts of up to 255 beats are issued | RANDOMIZED | `size_value` | `covergroup` | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |
| `burst-255-beats` | `SMC-ZERO-AXI.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `burst-mid-length` | `SMC-ZERO-AXI.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `single-burst-covers-region` | `SMC-ZERO-AXI.S3` | burst sizing is calculated automatically for the programmed region | RANDOMIZED | `size_value`, `dest_address` | `covergroup` | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |
| `multi-burst-region` | `SMC-ZERO-AXI.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `unaligned-start` | `SMC-ZERO-AXI.S4` | an unaligned start address is handled without writing outside the programmed region | RANDOMIZED | `dest_address` | `covergroup` | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |
| `aligned-start` | `SMC-ZERO-AXI.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-write-outside-region` | `SMC-ZERO-AXI.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `region-crosses-page-boundary` | `SMC-ZERO-AXI.S5` | a burst is fragmented automatically at a page boundary | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#AXI4` §Master Characteristics | — |
| `fragmented-at-boundary` | `SMC-ZERO-AXI.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-ZERO-DATA` — Zeroer data generation, strobes and size tracking

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `every-beat-is-zero` | `SMC-ZERO-DATA.S1` | zero data is generated for every beat | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| `partial-first-beat-strobe` | `SMC-ZERO-DATA.S2` | byte strobes are correct for a partial transfer | RANDOMIZED | `size_value`, `dest_address` | `covergroup` | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| `partial-last-beat-strobe` | `SMC-ZERO-DATA.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `full-strobe-middle-beats` | `SMC-ZERO-DATA.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `unaligned-head-strobe-masked` | `SMC-ZERO-DATA.S3` | byte strobes are correct for an unaligned start address | RANDOMIZED | `dest_address` | `covergroup` | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| `neighbouring-bytes-untouched` | `SMC-ZERO-DATA.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `wlast-on-final-beat` | `SMC-ZERO-DATA.S4` | the last-beat signal is asserted on the final beat of each burst | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| `no-wlast-on-earlier-beats` | `SMC-ZERO-DATA.S4` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `remaining-size-monotonic` | `SMC-ZERO-DATA.S5` | the remaining size is tracked accurately throughout the operation | RANDOMIZED | `size_value` | `covergroup` | `LIVE` | `zeroer.adoc#Data` §Generation and Control | — |
| `remaining-size-zero-at-end` | `SMC-ZERO-DATA.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `size-overflow-detected` | `SMC-ZERO-DATA.S6` | a size overflow is detected and handled rather than silently wrapping | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Data` §Generation and Control | SF-009 |
| `no-silent-wrap` | `SMC-ZERO-DATA.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-ZERO-OUTSTANDING` — Zeroer outstanding transaction management

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `counter-increments-on-issue` | `SMC-ZERO-OUTSTANDING.S1` | in-flight writes are tracked by the counter | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |
| `counter-decrements-on-response` | `SMC-ZERO-OUTSTANDING.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outstanding-1` | `SMC-ZERO-OUTSTANDING.S2` | **[contested]** up to 32 concurrent AXI transactions are permitted | RANDOMIZED | `memory_response_latency` | `covergroup` | `LIVE` | `zeroer.adoc#Memory` §Zeroer Integration | — |
| `outstanding-31` | `SMC-ZERO-OUTSTANDING.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outstanding-32` | `SMC-ZERO-OUTSTANDING.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `backpressure-at-max` | `SMC-ZERO-OUTSTANDING.S3` | **[contested]** [BOUNDED-LIVENESS] at the maximum, flow control applies back-pressure until resources free and the operation still completes within a bound | RANDOMIZED | `memory_stall_pattern` | `covergroup` | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |
| `resumes-after-response` | `SMC-ZERO-OUTSTANDING.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `operation-completes-bounded` | `SMC-ZERO-OUTSTANDING.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `multiple-aw-before-first-bresp` | `SMC-ZERO-OUTSTANDING.S4` | multiple write addresses are pipelined ahead of their responses | DIRECTED | — | `cover-property` | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |
| `data-continues-with-responses-delayed` | `SMC-ZERO-OUTSTANDING.S5` | the zero data stream continues independently of response timing | DIRECTED | — | `cover-property` | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management | — |

### `SMC-ZERO-ERR` — Zeroer AXI error handling

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `error-on-first-beat` | `SMC-ZERO-ERR.S1` | an AXI error response is detected and reported in the error status | RANDOMIZED | `error_response_index` | `covergroup` | `LIVE` | `zeroer.adoc#Status` §Features | — |
| `error-on-last-beat` | `SMC-ZERO-ERR.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `error-status-set` | `SMC-ZERO-ERR.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `two-errors-pending` | `SMC-ZERO-ERR.S2` | **[contested]** [BOUNDED-LIVENESS] a second error arriving while the first is still pending leaves a defined observable status and a bounded completion | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#Outstanding` §Transaction Management (+1) | — |
| `status-defined` | `SMC-ZERO-ERR.S2` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `operation-terminates-bounded` | `SMC-ZERO-ERR.S2` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-ZERO-IRQ` — Zeroer completion interrupt

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `pulse-on-busy-falling-edge` | `SMC-ZERO-IRQ.S1` | the pulse is generated on the falling edge of the zeroer busy output | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| `no-pulse-while-busy-high` | `SMC-ZERO-IRQ.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `bit-323-asserted-on-completion` | `SMC-ZERO-IRQ.S2` | the pulse appears at cpu_interrupts_o bit 323 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-035 |
| `interrupt-enabled` | `SMC-ZERO-IRQ.S3` | the completion interrupt is optional and gated by its enable | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Configuration` §and Control | — |
| `interrupt-disabled-no-assertion` | `SMC-ZERO-IRQ.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-ZERO-CG` — Zeroer dual-domain clock gating

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `axi-clk-on-disable-cg` | `SMC-ZERO-CG.S1` | the AXI clock is enabled by disable_cg, the busy indication or the reset state and gated otherwise | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Clock` §Gating Control | — |
| `axi-clk-on-busy` | `SMC-ZERO-CG.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `axi-clk-on-reset` | `SMC-ZERO-CG.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `axi-clk-gated-when-idle` | `SMC-ZERO-CG.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reg-clk-on-disable-cg` | `SMC-ZERO-CG.S2` | the register clock is enabled by disable_cg, register activity or the reset state and gated otherwise | DIRECTED | — | `covergroup` | `LIVE` | `zeroer.adoc#Clock` §Gating Control | — |
| `reg-clk-on-activity` | `SMC-ZERO-CG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reg-clk-on-reset` | `SMC-ZERO-CG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `reg-clk-gated-when-idle` | `SMC-ZERO-CG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-glitch-on-gate-enable` | `SMC-ZERO-CG.S3` | the gating is glitch-free on both enable and disable | DIRECTED | — | `assertion-cover` | `LIVE` | `zeroer.adoc#Clock` §Gating Control | — |
| `no-glitch-on-gate-disable` | `SMC-ZERO-CG.S3` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `test-enable-overrides-gating` | `SMC-ZERO-CG.S4` | the test enable overrides the gating for manufacturing test | DIRECTED | — | `cover-property` | `LIVE` | `zeroer.adoc#Clock` §Gating Control (+1) | — |

### `SMC-INT-VECTOR` — CPU interrupt vector assembly

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ext-range-255-0` | `SMC-INT-VECTOR.S1` | each of the four source groups occupies exactly its declared bit range with no overlap | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#SMC` §CPU Interrupt Vector Map | — |
| `periph-range-287-256` | `SMC-INT-VECTOR.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mailbox-range-319-288` | `SMC-INT-VECTOR.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `internal-range-323-320` | `SMC-INT-VECTOR.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-cross-group-aliasing` | `SMC-INT-VECTOR.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `num-ext-interrupts-256` | `SMC-INT-VECTOR.S2` | the vector is sized by the declared external and total interrupt counts | DIRECTED | — | `covergroup` | `DECODE` | `interrupts.adoc#SMC` §CPU Interrupt Vector Map | SF-048 |
| `num-cpu-interrupts-328` | `SMC-INT-VECTOR.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `bit-287-zero-with-all-periph-active` | `SMC-INT-VECTOR.S3` | reserved peripheral bit 287 stays zero under all peripheral activity | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-005 |
| `tail-bits-324-327-zero` | `SMC-INT-VECTOR.S4` | reserved tail bits 327 down to 324 stay zero | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-005 |

### `SMC-INT-EXTSYNC` — External interrupt synchronization

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ext-bit-0` | `SMC-INT-EXTSYNC.S1` | each external interrupt input appears at the corresponding vector bit | RANDOMIZED | `external_interrupt_index` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `ext-bit-255` | `SMC-INT-EXTSYNC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-bit-random` | `SMC-INT-EXTSYNC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `one-hot-mapping-verified` | `SMC-INT-EXTSYNC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `three-stage-latency-observed` | `SMC-INT-EXTSYNC.S2` | the input is synchronized through three stages into the SMC clock domain | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `pulse-shorter-than-window` | `SMC-INT-EXTSYNC.S3` | **[contested]** [BOUNDED-LIVENESS] an external pulse narrower than the synchronizer sampling window reaches a defined outcome rather than an intermediate value on the vector | RANDOMIZED | `pulse_width`, `pulse_phase` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `pulse-equal-to-window` | `SMC-INT-EXTSYNC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `pulse-longer-than-window` | `SMC-INT-EXTSYNC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `vector-bit-never-x` | `SMC-INT-EXTSYNC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-INT-PERIPHMAP` — Peripheral interrupt bit map

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sep-mbx-ch0-bit256` | `SMC-INT-PERIPHMAP.S1` | SEP mailbox interrupt channels 0 through 7 drive bits 256 through 263 | RANDOMIZED | `sep_mailbox_channel` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map (+1) | — |
| `sep-mbx-ch7-bit263` | `SMC-INT-PERIPHMAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep-mbx-one-hot-mapping` | `SMC-INT-PERIPHMAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `telem0-bit264` | `SMC-INT-PERIPHMAP.S2` | telemetry receiver instances 0 through 2 drive bits 264 through 266 | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-006 |
| `telem1-bit265` | `SMC-INT-PERIPHMAP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `telem2-bit266` | `SMC-INT-PERIPHMAP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ndm-request-bit267` | `SMC-INT-PERIPHMAP.S3` | the OR-reduced synchronized NDM reset request drives bit 267 | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `ndm-or-reduction` | `SMC-INT-PERIPHMAP.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `i3c-bits-268-273-zero` | `SMC-INT-PERIPHMAP.S4` | I3C interrupt sources map to bits 268 through 273, which read as zero while the peripheral-domain sources are tied low | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-029, SF-037 |
| `uart-irq-contributes` | `SMC-INT-PERIPHMAP.S5` | the combined UART IRQ, UART error and log-engine interrupt for instances 0 through 3 drives bits 274 through 277 | RANDOMIZED | `uart_instance`, `uart_source_kind` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `uart-error-contributes` | `SMC-INT-PERIPHMAP.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `log-engine-contributes` | `SMC-INT-PERIPHMAP.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `uart-instance-0-bit274` | `SMC-INT-PERIPHMAP.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `uart-instance-3-bit277` | `SMC-INT-PERIPHMAP.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `avsbus-bit278` | `SMC-INT-PERIPHMAP.S6` | the AVSBus interrupt drives bit 278 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `i2c0-bit279` | `SMC-INT-PERIPHMAP.S7` | I2C controller instances 0 through 2 drive bits 279 through 281 | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `i2c1-bit280` | `SMC-INT-PERIPHMAP.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `i2c2-bit281` | `SMC-INT-PERIPHMAP.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `sep-wdt-low-sets-bit282` | `SMC-INT-PERIPHMAP.S8` | the SEP watchdog reset indication drives bit 282 with inverted polarity | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map (+1) | — |
| `sep-wdt-high-clears-bit282` | `SMC-INT-PERIPHMAP.S8` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `locked-field-access-bit283` | `SMC-INT-PERIPHMAP.S9` | the eFuse locked-field access violation interrupt drives bit 283 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `gpio-lower-single-source` | `SMC-INT-PERIPHMAP.S10` | the OR of the lower half of the bonded GPIO interrupt sources drives bit 284 | RANDOMIZED | `gpio_lower_source_index` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-004 |
| `gpio-lower-multiple-sources` | `SMC-INT-PERIPHMAP.S10` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `gpio-lower-none` | `SMC-INT-PERIPHMAP.S10` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `gpio-upper-single-source` | `SMC-INT-PERIPHMAP.S11` | the OR of the upper half of the bonded GPIO interrupt sources drives bit 285 | RANDOMIZED | `gpio_upper_source_index` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-004 |
| `gpio-upper-multiple-sources` | `SMC-INT-PERIPHMAP.S11` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `gpio-upper-none` | `SMC-INT-PERIPHMAP.S11` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `hang-or-bit286` | `SMC-INT-PERIPHMAP.S12` | the OR of the three AXI hang detectors drives bit 286 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-004 |
| `bit-287-never-set` | `SMC-INT-PERIPHMAP.S13` | bit 287 is an unused peripheral slot tied to zero | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `two-sources-same-or-bit` | `SMC-INT-PERIPHMAP.S14` | **[contested]** [BOUNDED-LIVENESS] two sources feeding the same OR-reduced bit asserting simultaneously keep the bit asserted and stay individually identifiable through the source status registers | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map (+1) | — |
| `bit-stays-asserted` | `SMC-INT-PERIPHMAP.S14` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `both-identified-from-status` | `SMC-INT-PERIPHMAP.S14` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `clear-one-leaves-bit-asserted` | `SMC-INT-PERIPHMAP.S14` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-INT-MBX-SMC` — SMC mailbox interrupt range

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `mbx-ch0-bit288` | `SMC-INT-MBX-SMC.S1` | each mailbox channel's inbound interrupt appears at its own vector bit | RANDOMIZED | `mailbox_channel` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-038 |
| `mbx-ch31-bit319` | `SMC-INT-MBX-SMC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mbx-one-hot-mapping` | `SMC-INT-MBX-SMC.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-mailbox-bit-aliasing` | `SMC-INT-MBX-SMC.S2` | the 32 channels map to 32 distinct bits with no aliasing | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map (+1) | — |
| `two-channels-concurrent` | `SMC-INT-MBX-SMC.S3` | **[contested]** [BOUNDED-LIVENESS] several mailbox channels asserting concurrently all remain visible on their own bits | RANDOMIZED | `concurrent_channel_mask` | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `all-channels-concurrent` | `SMC-INT-MBX-SMC.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-INT-INTERNAL` — Internal interrupt bits

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `cla-clock-stop-bit320` | `SMC-INT-INTERNAL.S1` | the CLA clock-stop status drives bit 320 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `cla-interrupt-bit321` | `SMC-INT-INTERNAL.S2` | the CLA debug interrupt drives bit 321 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | SF-010 |
| `dma-complete-bit322` | `SMC-INT-INTERNAL.S3` | the DMA completion pulse drives bit 322 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `zeroer-complete-bit323` | `SMC-INT-INTERNAL.S4` | the zeroer completion pulse drives bit 323 | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-INT-PLICID` — PLIC source identification and aperture

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `bit0-source1` | `SMC-INT-PLICID.S1` | the PLIC source ID of an SMC-driven interrupt equals its raw vector bit index plus one | RANDOMIZED | `vector_bit_index` | `covergroup` | `LIVE` | `interrupts.adoc#SMC` §CPU Interrupt Vector Map | — |
| `bit323-source324` | `SMC-INT-PLICID.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `arbitrary-bit-plus-one` | `SMC-INT-PLICID.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `indices-328-331-absent-from-raw-vector` | `SMC-INT-PLICID.S2` | the per-core cluster-bound global sources at indices 328 through 331 do not appear on the raw vector | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#SMC` §interrupt vector (`cpu_interrupts_o`) | SF-051 |
| `indices-328-331-present-at-plic` | `SMC-INT-PLICID.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `plic-base-access` | `SMC-INT-PLICID.S3` | the PLIC aperture from 0xC400_0000 through 0xC43F_FFFF decodes over 4 MB | DIRECTED | — | `covergroup` | `DECODE` | `interrupts.adoc#RISC-V` §PLIC (+1) | SF-003 |
| `plic-top-access` | `SMC-INT-PLICID.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `just-above-plic-not-plic` | `SMC-INT-PLICID.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `source-index-1` | `SMC-INT-PLICID.S4` | 332 global sources indexed 0 through 331 are addressable in the PLIC register space | RANDOMIZED | `plic_source_index` | `covergroup` | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-005, SF-051 |
| `source-index-331` | `SMC-INT-PLICID.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `source-index-random` | `SMC-INT-PLICID.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-PLIC-PRIO` — PLIC per-source priority

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `higher-priority-wins` | `SMC-PLIC-PRIO.S1` | of two pending sources the higher-priority one is delivered first | RANDOMIZED | `priority_a`, `priority_b`, `source_pair` | `covergroup` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `equal-priority-resolved-deterministically` | `SMC-PLIC-PRIO.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `priority-zero-not-delivered` | `SMC-PLIC-PRIO.S2` | a source left at priority zero is never delivered | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#RISC-V` §PLIC (+1) | — |
| `priority-nonzero-delivered` | `SMC-PLIC-PRIO.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-PLIC-ENABLE` — PLIC per-core and per-context enables

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `enabled-source-delivered` | `SMC-PLIC-ENABLE.S1` | an enabled source is delivered to the enabled context | RANDOMIZED | `source_index`, `context_index` | `covergroup` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `disabled-source-not-delivered` | `SMC-PLIC-ENABLE.S2` | a disabled source is not delivered to that context | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `per-core-enable-isolation` | `SMC-PLIC-ENABLE.S3` | enabling a source for one core does not deliver it to another core | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Multi-Core` §Interrupt Distribution and Load Management | — |

### `SMC-PLIC-THRESHOLD` — PLIC threshold filtering

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `priority-below-threshold` | `SMC-PLIC-THRESHOLD.S1` | a pending source whose priority does not exceed the threshold is not delivered | RANDOMIZED | `threshold_value`, `source_priority` | `covergroup` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `priority-equal-threshold` | `SMC-PLIC-THRESHOLD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `priority-above-threshold` | `SMC-PLIC-THRESHOLD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `source-masked-by-threshold` | `SMC-PLIC-THRESHOLD.S2` | **[contested]** [BOUNDED-LIVENESS] lowering the threshold while a source is pending releases that source for delivery within a bound | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `threshold-lowered` | `SMC-PLIC-THRESHOLD.S2` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `source-delivered-bounded` | `SMC-PLIC-THRESHOLD.S2` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-PLIC-CLAIM` — PLIC atomic claim and completion

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `claim-returns-highest-priority` | `SMC-PLIC-CLAIM.S1` | a claim returns the highest-priority pending enabled source ID | RANDOMIZED | `pending_source_set`, `priority_assignment` | `covergroup` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `claim-returns-zero-when-none-pending` | `SMC-PLIC-CLAIM.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `completion-rearms-source` | `SMC-PLIC-CLAIM.S2` | completion re-arms the source so a later assertion is delivered again | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `reassertion-delivered-after-completion` | `SMC-PLIC-CLAIM.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `simultaneous-claim-two-cores` | `SMC-PLIC-CLAIM.S3` | **[contested]** [BOUNDED-LIVENESS] two cores claiming the same source concurrently produce exactly one delivery, with the loser receiving no duplicate | RANDOMIZED | `claim_phase_offset` | `covergroup` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `exactly-one-winner` | `SMC-PLIC-CLAIM.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `loser-gets-no-duplicate` | `SMC-PLIC-CLAIM.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `assert-between-claim-and-complete` | `SMC-PLIC-CLAIM.S4` | **[contested]** [BOUNDED-LIVENESS] a new assertion arriving inside the claim and completion window is not lost and is delivered within a bound | RANDOMIZED | `assert_phase` | `covergroup` | `LIVE` | `interrupts.adoc#Advanced` §PLIC Management and Adaptive Priority Control | — |
| `assert-at-completion-cycle` | `SMC-PLIC-CLAIM.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `interrupt-not-lost` | `SMC-PLIC-CLAIM.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-PLIC-INIT` — PLIC and mie software initialization obligation

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `priority-written-to-zero` | `SMC-PLIC-INIT.S1` | the PLIC priority and enable registers are writable to known values after reset | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-044 |
| `enables-written-to-disabled` | `SMC-PLIC-INIT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `readback-matches` | `SMC-PLIC-INIT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `delivery-after-full-initialization` | `SMC-PLIC-INIT.S2` | external interrupts are deliverable once the registers are initialized and the global enable is set | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-044 |
| `mie-cleared-first` | `SMC-PLIC-INIT.S3` | the mie CSR is cleared and initialized before individual enable bits and the global machine interrupt enable are set | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#RISC-V` §PLIC | SF-044 |
| `mie-bits-set-then-mstatus-mie` | `SMC-PLIC-INIT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-PLIC-CONTEXT` — PLIC multi-context and per-core independence

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `mmode-context-enable` | `SMC-PLIC-CONTEXT.S1` | the machine-mode context has its own enables and threshold | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Multi-Context` §Architecture and Privilege Level Integration | — |
| `mmode-context-threshold` | `SMC-PLIC-CONTEXT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `smode-context-enable` | `SMC-PLIC-CONTEXT.S2` | the supervisor-mode context has its own enables and threshold | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Multi-Context` §Architecture and Privilege Level Integration | — |
| `smode-context-threshold` | `SMC-PLIC-CONTEXT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `context-isolation-across-privilege` | `SMC-PLIC-CONTEXT.S3` | configuring one context does not change delivery for another privilege context | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Multi-Context` §Architecture and Privilege Level Integration | — |
| `delivery-core0` | `SMC-PLIC-CONTEXT.S4` | interrupts are delivered independently to each of the four cores | RANDOMIZED | `target_core`, `source_index` | `covergroup` | `LIVE` | `interrupts.adoc#Multi-Core` §Interrupt Distribution and Load Management | — |
| `delivery-core1` | `SMC-PLIC-CONTEXT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `delivery-core2` | `SMC-PLIC-CONTEXT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `delivery-core3` | `SMC-PLIC-CONTEXT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `one-core-masked-other-delivered` | `SMC-PLIC-CONTEXT.S5` | per-core masking lets software suppress delivery to one core while another still receives the source | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Multi-Core` §Interrupt Distribution and Load Management | — |

### `SMC-CLINT` — CLINT timer and software interrupts

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `clint-base-access` | `SMC-CLINT.S1` | the CLINT aperture from 0xC800_0000 through 0xC800_FFFF decodes over 64 KiB | DIRECTED | — | `covergroup` | `DECODE` | `interrupts.adoc#RISC-V` §CLINT and Precise System Management Timing (+1) | SF-003 |
| `clint-top-access` | `SMC-CLINT.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `just-above-clint-not-clint` | `SMC-CLINT.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `timer-monotonic` | `SMC-CLINT.S2` | the shared 64-bit timer counter advances monotonically and is readable by every core | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Precision` §Timer Management and Inter-Core Coordination | — |
| `timer-same-value-across-cores` | `SMC-CLINT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `timer-upper-word-rollover` | `SMC-CLINT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `compare-near-term` | `SMC-CLINT.S3` | a per-core compare value raises that core's timer interrupt when the counter reaches it | RANDOMIZED | `compare_value`, `target_core` | `covergroup` | `LIVE` | `interrupts.adoc#Precision` §Timer Management and Inter-Core Coordination | — |
| `compare-far-term` | `SMC-CLINT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `per-core-independent-compare` | `SMC-CLINT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `swi-core0-to-core1` | `SMC-CLINT.S4` | a core raises a software interrupt on another core | RANDOMIZED | `source_core`, `target_core` | `covergroup` | `LIVE` | `interrupts.adoc#RISC-V` §CLINT and Precise System Management Timing | — |
| `swi-core-to-self` | `SMC-CLINT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `swi-cleared` | `SMC-CLINT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `clint-irq-not-a-plic-source` | `SMC-CLINT.S5` | CLINT interrupts are delivered directly to the core, bypassing the PLIC | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#RISC-V` §CLINT and Precise System Management Timing | — |
| `compare-write-with-pending-irq` | `SMC-CLINT.S6` | **[contested]** [BOUNDED-LIVENESS] a compare value written while that core's timer interrupt is already pending reaches a defined pending state within a bound | DIRECTED | — | `assertion-cover` | `LIVE` | `interrupts.adoc#Precision` §Timer Management and Inter-Core Coordination | — |
| `pending-state-defined` | `SMC-CLINT.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `irq-cleared-when-compare-advanced` | `SMC-CLINT.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-PERIPH-DECODE` — Peripheral aperture decode and instance counts

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `gpio-interface-decode` | `SMC-PERIPH-DECODE.S1` | each peripheral block decodes at its mapped base offset | RANDOMIZED | `peripheral_offset` | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-053 |
| `i3c-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `avsbus-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `i2c-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `uart-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `efuse-map-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `efuse-interface-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `telemetry-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `octs-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `dtp-ctrl-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `dfx-status-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `reset-unit-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `misc-wrap-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `cla-decode` | `SMC-PERIPH-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `gpio-instance-0` | `SMC-PERIPH-DECODE.S2` | the declared instance count of each multi-instance peripheral is reachable at its instance stride | RANDOMIZED | `instance_index` | `covergroup` | `DECODE` | `periphs.adoc#SMC` §Peripheral Summary (+1) | SF-006, SF-029, SF-053 |
| `gpio-instance-64` | `SMC-PERIPH-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `i3c-instance-0` | `SMC-PERIPH-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `i3c-instance-5` | `SMC-PERIPH-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `mailbox-pair-0` | `SMC-PERIPH-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `mailbox-pair-31` | `SMC-PERIPH-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `wdt-instance-3` | `SMC-PERIPH-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `beu-instance-3` | `SMC-PERIPH-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `axil-only-peripheral-access` | `SMC-PERIPH-DECODE.S3` | each peripheral responds on the bus protocol its summary entry declares | DIRECTED | — | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary (+1) | — |
| `apb4-capable-peripheral-access` | `SMC-PERIPH-DECODE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `beyond-last-instance-errors` | `SMC-PERIPH-DECODE.S4` | **[contested]** [BOUNDED-LIVENESS] an access to an instance index beyond the populated count terminates with an error rather than hanging | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#SMC` §Component Address Map (+1) | SF-053 |
| `access-terminates-bounded` | `SMC-PERIPH-DECODE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-PERIPH-PARAM` — SMC peripheral parameter overrides

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `mailbox-count-32` | `SMC-PERIPH-PARAM.S1` | 32 mailboxes are instantiated with a FIFO depth of 2 | DIRECTED | — | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| `mailbox-depth-2-full-at-two-entries` | `SMC-PERIPH-PARAM.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `i2c-target-rx-fifo-64-entries` | `SMC-PERIPH-PARAM.S2` | the I2C target receive FIFO depth is 64 | DIRECTED | — | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| `i2c-target-rx-fifo-full-at-64` | `SMC-PERIPH-PARAM.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `i3c-count-6` | `SMC-PERIPH-PARAM.S3` | six I3C controller instances are configured | DIRECTED | — | `cover-property` | `DECODE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | SF-029 |
| `gpio-two-outstanding` | `SMC-PERIPH-PARAM.S4` | the GPIO maximum outstanding transaction parameter is 2 | DIRECTED | — | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| `gpio-third-request-backpressured` | `SMC-PERIPH-PARAM.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `default-input-count-62` | `SMC-PERIPH-PARAM.S5` | the GPIO default direction map sets 62 of 65 instances to input and the remaining 3 to output | DIRECTED | — | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| `default-output-count-3` | `SMC-PERIPH-PARAM.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `per-instance-default-matches-map` | `SMC-PERIPH-PARAM.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-GPIO-PAD` — GPIO pad data path

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `pad-input-high` | `SMC-GPIO-PAD.S1` | a pad input transition is captured and readable through the GPIO registers | RANDOMIZED | `gpio_wrap_index`, `pad_value` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#pad2core_i@f2cb50de | — |
| `pad-input-low` | `SMC-GPIO-PAD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `input-per-wrap` | `SMC-GPIO-PAD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `pad-output-high` | `SMC-GPIO-PAD.S2` | a software write to a GPIO output register drives the pad | RANDOMIZED | `gpio_wrap_index`, `output_value` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#core2pad_o@f2cb50de | — |
| `pad-output-low` | `SMC-GPIO-PAD.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `output-per-wrap` | `SMC-GPIO-PAD.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `wrap-input-enabled` | `SMC-GPIO-PAD.S3` | the pad-to-core and core-to-pad enables set the direction of each wrap | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#pad2core_en_o@f2cb50de | — |
| `wrap-output-enabled` | `SMC-GPIO-PAD.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `wrap-both-disabled` | `SMC-GPIO-PAD.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `lsio-select-per-wrap` | `SMC-GPIO-PAD.S4` | lsio_interface_select_o selects the interface for each GPIO wrap | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#lsio_interface_select_o@f2cb50de | — |
| `wrap-switched-input-to-output` | `SMC-GPIO-PAD.S5` | dual-mode operation is exercised on the same wrap in both directions | DIRECTED | — | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `wrap-switched-output-to-input` | `SMC-GPIO-PAD.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-GPIO-IRQ` — GPIO interrupt reporting

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `gpio-irq-bit-first` | `SMC-GPIO-IRQ.S1` | each GPIO wrap drives its own bit of the raw interrupt vector | RANDOMIZED | `gpio_wrap_index` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de | — |
| `gpio-irq-bit-last` | `SMC-GPIO-IRQ.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `gpio-irq-one-hot-mapping` | `SMC-GPIO-IRQ.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `status-identifies-source` | `SMC-GPIO-IRQ.S2` | software identifies the interrupting wrap by reading the GPIO status registers | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de | — |
| `status-cleared-deasserts-irq` | `SMC-GPIO-IRQ.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `two-wraps-same-half` | `SMC-GPIO-IRQ.S3` | **[contested]** [BOUNDED-LIVENESS] two wraps in the same OR-reduced half asserting together keep the aggregate bit high and both remain identifiable | DIRECTED | — | `assertion-cover` | `LIVE` | hw/sys/smc/doc/port_table.adoc#gpio_interrupt_o@f2cb50de (+1) | SF-004 |
| `aggregate-stays-high` | `SMC-GPIO-IRQ.S3` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `both-identifiable-from-status` | `SMC-GPIO-IRQ.S3` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-GPIO-STRAPS` — Cold-reset GPIO strap capture

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `straps-all-zero` | `SMC-GPIO-STRAPS.S1` | the bonded pad values are latched at cold reset | RANDOMIZED | `strap_pattern` | `covergroup` | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | — |
| `straps-all-ones` | `SMC-GPIO-STRAPS.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `straps-mixed-pattern` | `SMC-GPIO-STRAPS.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `straps-lo-read` | `SMC-GPIO-STRAPS.S2` | the captured straps are readable at the low and high strap registers and are read-only to software | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | SF-007, SF-054 |
| `straps-hi-read` | `SMC-GPIO-STRAPS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `strap-write-has-no-effect` | `SMC-GPIO-STRAPS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `strap-13-captured-set` | `SMC-GPIO-STRAPS.S3` | the BYPASS_SRAM_REPAIR strap on GPIO pin 13 is captured and reaches the repair bypass control | DIRECTED | — | `covergroup` | `LIVE` | `cpu.adoc#Memory` §Repair | — |
| `strap-13-captured-clear` | `SMC-GPIO-STRAPS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `strap-25-primary` | `SMC-GPIO-STRAPS.S4` | the chiplet-is-primary strap on strap 25 is captured and reaches the system timer | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#chiplet_is_primary_i@f2cb50de | — |
| `strap-25-secondary` | `SMC-GPIO-STRAPS.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `pad-changes-after-capture` | `SMC-GPIO-STRAPS.S5` | **[contested]** [BOUNDED-LIVENESS] a pad value changing after the capture window leaves the captured strap value unchanged | DIRECTED | — | `assertion-cover` | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | — |
| `captured-value-stable` | `SMC-GPIO-STRAPS.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-GPIO-EXTCTRL` — GPIO clock observation and pad control apertures

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `pll-obs-enabled-drives-pad` | `SMC-GPIO-EXTCTRL.S1` | the PLL clock observation input is muxed onto the padring under its enable | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#pll_clk_obs_i@f2cb50de | — |
| `pll-obs-disabled-does-not-drive` | `SMC-GPIO-EXTCTRL.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `pvt-obs-enabled-drives-pad` | `SMC-GPIO-EXTCTRL.S2` | the PVT process monitor clock observation input is muxed onto the padring under its enable | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#pvt_process_clk_obs_i@f2cb50de | — |
| `pvt-obs-disabled-does-not-drive` | `SMC-GPIO-EXTCTRL.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `pll-obs-intf-decode` | `SMC-GPIO-EXTCTRL.S3` | the clock observation interface and control apertures decode at their mapped offsets | DIRECTED | — | `covergroup` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| `pll-obs-ctrl-decode` | `SMC-GPIO-EXTCTRL.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `pvt-obs-intf-decode` | `SMC-GPIO-EXTCTRL.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `pvt-obs-ctrl-decode` | `SMC-GPIO-EXTCTRL.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `gpio-poc-pbias-decode` | `SMC-GPIO-EXTCTRL.S4` | the power-on and pad bias control block and the reference clock GPIO control block decode at their mapped offsets | DIRECTED | — | `covergroup` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| `gpio-refclk-ctrl-decode` | `SMC-GPIO-EXTCTRL.S4` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `per-pad-instance-0` | `SMC-GPIO-EXTCTRL.S5` | all 65 per-pad control register blocks decode at their instance stride | RANDOMIZED | `pad_instance_index` | `covergroup` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| `per-pad-instance-64` | `SMC-GPIO-EXTCTRL.S5` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `per-pad-stride-0x20` | `SMC-GPIO-EXTCTRL.S5` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |

### `SMC-PVT` — PVT digital control and status interface

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `pvt-wrapper-decode` | `SMC-PVT.S1` | the PVT wrapper aperture decodes at its mapped offset | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| `cat-therm-asserted` | `SMC-PVT.S2` | cat_therm_i reaches the PVT wrapper | DIRECTED | — | `covergroup` | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#cat_therm_i@f2cb50de | SF-024 |
| `cat-therm-deasserted` | `SMC-PVT.S2` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `pvt-status-read` | `SMC-PVT.S3` | PVT status is readable through the digital interface | DIRECTED | — | `cover-property` | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-024 |

### `SMC-TELEM-RX` — Telemetry receiver ATB ingress

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `atb-transfer-accepted` | `SMC-TELEM-RX.S1` | an ATB transfer with valid high and ready high is accepted | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_atvalid_i@f2cb50de | — |
| `receiver-0-decode` | `SMC-TELEM-RX.S2` | the ATB data and ID are decoded per receiver instance | RANDOMIZED | `receiver_index`, `atb_id`, `atb_data` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_atid_i@f2cb50de | SF-006 |
| `receiver-1-decode` | `SMC-TELEM-RX.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `receiver-2-decode` | `SMC-TELEM-RX.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `distinct-atid-values` | `SMC-TELEM-RX.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `flush-requested` | `SMC-TELEM-RX.S3` | the flush handshake completes with the flush valid output and the flush ready input | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_afvalid_o@f2cb50de | — |
| `flush-acknowledged` | `SMC-TELEM-RX.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ready-low-stall` | `SMC-TELEM-RX.S4` | **[contested]** [BOUNDED-LIVENESS] valid held with ready low backpressures the source and no telemetry data is lost once ready returns | RANDOMIZED | `stall_duration`, `stall_phase` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_atready_o@f2cb50de | — |
| `data-held-during-stall` | `SMC-TELEM-RX.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-data-lost-after-resume` | `SMC-TELEM-RX.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `flush-during-active-transfer` | `SMC-TELEM-RX.S5` | **[contested]** [BOUNDED-LIVENESS] a flush requested while data transfers are active reaches a bounded completion without dropping accepted data | DIRECTED | — | `assertion-cover` | `LIVE` | hw/sys/smc/doc/port_table.adoc#telemetry_afvalid_o@f2cb50de | — |
| `accepted-data-retained` | `SMC-TELEM-RX.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `flush-completes-bounded` | `SMC-TELEM-RX.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-OCTS` — System timer OCTS

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `octs-count-advances` | `SMC-OCTS.S1` | the 64-bit count advances on the reference clock | DIRECTED | — | `covergroup` | `LIVE` | `clk_rst.adoc#The` §Reference Clock Domain | — |
| `octs-count-monotonic` | `SMC-OCTS.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `timer-count-out-matches-register` | `SMC-OCTS.S2` | timer_count_o presents the full 64-bit count to external systems | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#timer_count_o@f2cb50de | SF-023 |
| `timer-count-upper-word-rollover` | `SMC-OCTS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `octs-primary-mode` | `SMC-OCTS.S3` | an asserted chiplet-is-primary input selects PRIMARY mode | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#chiplet_is_primary_i@f2cb50de (+1) | SF-023 |
| `octs-secondary-mode` | `SMC-OCTS.S4` | a deasserted chiplet-is-primary input selects SECONDARY mode | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#chiplet_is_primary_i@f2cb50de (+1) | SF-023 |
| `octs-aperture-decode` | `SMC-OCTS.S5` | the OCTS aperture decodes at its mapped offset over APB4 and AXI4-Lite | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#SMC` §Component Address Map (+1) | SF-053 |

### `SMC-UART` — UART 16550 integration

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `uart-instance-0` | `SMC-UART.S1` | the four UART instances are reachable behind the UART wrapper aperture | RANDOMIZED | `uart_instance` | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map (+1) | SF-053 |
| `uart-instance-3` | `SMC-UART.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `tx-single-char` | `SMC-UART.S2` | a character written to a UART is transmitted on its serial output | RANDOMIZED | `tx_data`, `baud_divisor` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `tx-multi-char` | `SMC-UART.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `tx-fifo-partially-full` | `SMC-UART.S3` | FIFO operation buffers transmit and receive data | RANDOMIZED | `fifo_fill_level` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `tx-fifo-full` | `SMC-UART.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `rx-fifo-partially-full` | `SMC-UART.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `rx-fifo-full` | `SMC-UART.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `uart-irq-per-instance` | `SMC-UART.S4` | uart_interrupt_o presents one raw interrupt bit per instance in the peripheral clock domain | RANDOMIZED | `uart_instance` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#uart_interrupt_o@f2cb50de | — |
| `uart-irq-cleared` | `SMC-UART.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-LOGENG` — Log engine

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `logengine-instance-0` | `SMC-LOGENG.S1` | four log engine instances are present and individually addressable | DIRECTED | — | `covergroup` | `DECODE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `logengine-instance-3` | `SMC-LOGENG.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `log-short-message` | `SMC-LOGENG.S2` | a submitted log message is transferred to the UART without CPU copying | RANDOMIZED | `message_length` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `log-long-message` | `SMC-LOGENG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `message-reaches-uart` | `SMC-LOGENG.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `logengine-irq-sets-combined-bit` | `SMC-LOGENG.S3` | the log engine interrupt contributes to the combined UART interrupt bit for its instance | DIRECTED | — | `cover-property` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |

### `SMC-I2C` — I2C controller integration

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `i2c-instance-0` | `SMC-I2C.S1` | the three I2C instances are reachable behind the I2C wrapper aperture | DIRECTED | — | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map (+1) | SF-053 |
| `i2c-instance-1` | `SMC-I2C.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `i2c-instance-2` | `SMC-I2C.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `controller-write` | `SMC-I2C.S2` | a controller-mode transfer reads and writes an external target device | RANDOMIZED | `target_address`, `byte_count` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `controller-read` | `SMC-I2C.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `controller-repeated-start` | `SMC-I2C.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `target-write-received` | `SMC-I2C.S3` | a target-mode transfer accepts data from an external controller | RANDOMIZED | `own_address`, `byte_count` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `target-read-served` | `SMC-I2C.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `smbus-transaction-completed` | `SMC-I2C.S4` | SMBus protocol operation is supported | DIRECTED | — | `cover-property` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `pmbus-transaction-completed` | `SMC-I2C.S5` | PMBus protocol operation is supported | DIRECTED | — | `cover-property` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `rx-fifo-full-at-64` | `SMC-I2C.S6` | **[contested]** [BOUNDED-LIVENESS] a target receive FIFO filled to its 64-entry depth backpressures the bus without silently dropping bytes | RANDOMIZED | `incoming_byte_count`, `drain_rate` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| `backpressure-or-defined-overflow-status` | `SMC-I2C.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-silent-byte-loss` | `SMC-I2C.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-AVSBUS` — AVSBus controller integration

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `avsbus-aperture-decode` | `SMC-AVSBUS.S1` | the AVSBus aperture decodes at its mapped offset | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-053 |
| `avs-command-sent` | `SMC-AVSBUS.S2` | a voltage-rail command is transmitted and its response is captured | RANDOMIZED | `rail_index`, `command_code` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `avs-response-captured` | `SMC-AVSBUS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `avsbus-irq-raised` | `SMC-AVSBUS.S3` | the AVSBus interrupt is raised and reaches the peripheral interrupt vector | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `avsbus-irq-cleared` | `SMC-AVSBUS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-MBX` — Mailbox communication channels

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `inbound-pair-0` | `SMC-MBX.S1` | the 32 inbound and 32 outbound mailboxes decode across the mailbox aperture | RANDOMIZED | `mailbox_pair_index` | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map | — |
| `inbound-pair-31` | `SMC-MBX.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `outbound-pair-0` | `SMC-MBX.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `outbound-pair-31` | `SMC-MBX.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `single-entry-message` | `SMC-MBX.S2` | a message written into a channel is read back in order through its FIFO | RANDOMIZED | `message_word_count`, `mailbox_pair_index` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `two-entry-message` | `SMC-MBX.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `fifo-order-preserved` | `SMC-MBX.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `inbound-irq-raised` | `SMC-MBX.S3` | the per-channel inbound interrupt is raised when a message arrives | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `inbound-irq-cleared-after-read` | `SMC-MBX.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-mailbox-irq-per-channel` | `SMC-MBX.S4` | the external mailbox interrupt outputs signal the 32 channels to external targets | RANDOMIZED | `mailbox_channel` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#ext_mailbox_interrupts_o@f2cb50de | SF-038 |
| `write-to-full-fifo` | `SMC-MBX.S5` | **[contested]** [BOUNDED-LIVENESS] a write to a channel whose depth-2 FIFO is already full reaches a bounded defined outcome without silently discarding a message | DIRECTED | — | `assertion-cover` | `LIVE` | `periphs.adoc#SMC` §Peripheral Parameter Overrides | — |
| `no-silent-message-loss` | `SMC-MBX.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `outcome-observable-in-status` | `SMC-MBX.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `concurrent-in-and-out` | `SMC-MBX.S6` | **[contested]** [BOUNDED-LIVENESS] concurrent inbound and outbound activity on the same mailbox pair both complete within a bound and do not corrupt each other | RANDOMIZED | `mailbox_pair_index`, `interleave_pattern` | `covergroup` | `LIVE` | `periphs.adoc#SMC` §Peripheral Summary | — |
| `both-complete` | `SMC-MBX.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-cross-corruption` | `SMC-MBX.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-EFUSE-IF` — eFuse controller interfaces

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `efuse-map-decode` | `SMC-EFUSE-IF.S1` | the eFuse map and eFuse interface apertures decode at their mapped offsets | DIRECTED | — | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-053 |
| `efuse-interface-decode` | `SMC-EFUSE-IF.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `bank-ctrl-read` | `SMC-EFUSE-IF.S2` | the bank control AXI-Lite request reaches the eFuse SHIM and its response returns | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#efuse_bank_ctrl_req_o@f2cb50de | — |
| `bank-ctrl-write` | `SMC-EFUSE-IF.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `bank-ctrl-response-returned` | `SMC-EFUSE-IF.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `shim-command-issued` | `SMC-EFUSE-IF.S3` | a fuse command request is issued to the SHIM and its response is consumed | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#efuse_shim_command_req_o@f2cb50de | — |
| `shim-response-consumed` | `SMC-EFUSE-IF.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `shadow-regs-reflect-sensed-values` | `SMC-EFUSE-IF.S4` | the shadow register output presents the sensed fuse map to its consumers | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#shadow_regs_o@f2cb50de | — |
| `jtag-otp-read` | `SMC-EFUSE-IF.S5` | the OTP JTAG AXI-Lite path reaches the eFuse controller and returns a response | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#axil_smc_otp_jtag_req_i@f2cb50de | — |
| `jtag-otp-write` | `SMC-EFUSE-IF.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `fuse-sense-done-asserted` | `SMC-EFUSE-IF.S6` | fuse sense completion and the delayed fuse reset are presented on their outputs | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#fuse_sense_done_o@f2cb50de | SF-040 |
| `fuse-reset-delayed-16-stages` | `SMC-EFUSE-IF.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-EFUSE-LOCKS` — eFuse lock enforcement

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `locks-cleared-access-permitted` | `SMC-EFUSE-LOCKS.S1` | LOCKS is the only enforcement point for read and write access control over the entire fuse map | DIRECTED | — | `covergroup` | `LIVE` | `scan_protection.adoc#eFuse` §Shadow Register Scan Protection | SF-050 |
| `locks-set-access-refused` | `SMC-EFUSE-LOCKS.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `write-locked-field-unchanged` | `SMC-EFUSE-LOCKS.S2` | a write to a write-locked field does not change the field | RANDOMIZED | `fuse_field_index`, `locks_pattern` | `covergroup` | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | SF-050 |
| `write-unlocked-field-updated` | `SMC-EFUSE-LOCKS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `read-locked-field-masked` | `SMC-EFUSE-LOCKS.S3` | a read of a read-locked field does not return the field contents | RANDOMIZED | `fuse_field_index`, `locks_pattern` | `covergroup` | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | SF-050 |
| `read-unlocked-field-returned` | `SMC-EFUSE-LOCKS.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `lock-decision-same-cycle` | `SMC-EFUSE-LOCKS.S4` | the lock decision is purely combinational with no intermediate state element between the shadow words and the gated paths | DIRECTED | — | `assertion-cover` | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | — |
| `no-stale-lock-decision-after-locks-change` | `SMC-EFUSE-LOCKS.S4` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `violation-interrupt-on-locked-write` | `SMC-EFUSE-LOCKS.S5` | an attempted locked-field access raises the locked-field access violation interrupt | DIRECTED | — | `covergroup` | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path (+1) | — |
| `violation-interrupt-on-locked-read` | `SMC-EFUSE-LOCKS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-interrupt-on-permitted-access` | `SMC-EFUSE-LOCKS.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `locked-and-permitted-concurrent` | `SMC-EFUSE-LOCKS.S6` | **[contested]** [BOUNDED-LIVENESS] a locked-field access concurrent with a permitted access leaves the permitted access unaffected and both terminate within a bound | DIRECTED | — | `assertion-cover` | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | — |
| `permitted-access-unaffected` | `SMC-EFUSE-LOCKS.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `both-terminate-bounded` | `SMC-EFUSE-LOCKS.S6` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-LCSTATE` — Lifecycle state input

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `lc-state-readback-matches-input` | `SMC-LCSTATE.S1` | the 8-bit differentially encoded lifecycle state reaches the SMC internal registers | RANDOMIZED | `lc_state_value` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#lc_state_i@f2cb50de | SF-052 |
| `lc-state-test-dev-tie` | `SMC-LCSTATE.S2` | the unused tie value encoding TEST_DEV is accepted | DIRECTED | — | `cover-property` | `DECODE` | hw/sys/smc/doc/port_table.adoc#lc_state_i@f2cb50de | SF-052 |

### `SMC-NDM-RST` — NDM reset control block

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `ndm-reset-block-decode` | `SMC-NDM-RST.S1` | the NDM reset register block decodes within the miscellaneous wrapper aperture | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#Spare` §SMC Register Blocks (+1) | — |
| `ndm-request-synchronized` | `SMC-NDM-RST.S2` | an NDM reset request is synchronized into the SMC clock domain and OR-reduced onto its interrupt bit | DIRECTED | — | `covergroup` | `LIVE` | `interrupts.adoc#Exact` §Indexed Map | — |
| `ndm-or-reduced-to-bit267` | `SMC-NDM-RST.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ndm-request-cleared` | `SMC-NDM-RST.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-DFD-DBGBUS` — Programmable debug bus

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `debug-bus-sampled-each-cycle` | `SMC-DFD-DBGBUS.S1` | the debug bus is sampled every cycle | DIRECTED | — | `assertion-cover` | `LIVE` | `dfd.adoc#Debug` §Bus | SF-027 |
| `selection-a-observed` | `SMC-DFD-DBGBUS.S2` | software selects a different observed signal set without an RTL change and the bus value follows | RANDOMIZED | `debug_bus_selection` | `covergroup` | `LIVE` | `dfd.adoc#Debug` §Bus | — |
| `selection-b-observed` | `SMC-DFD-DBGBUS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `selection-changed-at-runtime` | `SMC-DFD-DBGBUS.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `ext-debug-lane-first` | `SMC-DFD-DBGBUS.S3` | the 512-bit external debug bus input reaches the debug bus aggregator on its 16-bit aligned lanes | RANDOMIZED | `ext_debug_lane_index` | `covergroup` | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#ext_debug_bus_i@f2cb50de | — |
| `ext-debug-lane-last` | `SMC-DFD-DBGBUS.S3` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `ext-debug-lane-random` | `SMC-DFD-DBGBUS.S3` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |

### `SMC-CLA-EVENT` — CLA event engine

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `match-hit` | `SMC-CLA-EVENT.S1` | a signal-match event fires when the masked debug bus equals the programmed value | RANDOMIZED | `match_mask`, `match_value`, `debug_bus_stimulus` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | SF-027 |
| `match-miss-one-bit` | `SMC-CLA-EVENT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `mask-excludes-differing-bit` | `SMC-CLA-EVENT.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `rising-edge-fires` | `SMC-CLA-EVENT.S2` | an edge event fires on a rising or falling edge of the selected debug-bus signals | DIRECTED | — | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `falling-edge-fires` | `SMC-CLA-EVENT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `steady-level-does-not-fire` | `SMC-CLA-EVENT.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `a-to-b-fires` | `SMC-CLA-EVENT.S3` | a transition event fires when a masked subset moves from the programmed value A to the programmed value B | RANDOMIZED | `transition_a`, `transition_b`, `transition_mask` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `b-to-a-does-not-fire` | `SMC-CLA-EVENT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `a-to-other-does-not-fire` | `SMC-CLA-EVENT.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `count-equal-fires` | `SMC-CLA-EVENT.S4` | a ones-count event fires when the population count of a masked subset equals the programmed value | RANDOMIZED | `ones_count_target`, `ones_count_mask` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `count-below-does-not-fire` | `SMC-CLA-EVENT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `count-above-does-not-fire` | `SMC-CLA-EVENT.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `change-inside-mask-fires` | `SMC-CLA-EVENT.S5` | an any-change event fires when any signal within a masked subset changes | DIRECTED | — | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `change-outside-mask-does-not-fire` | `SMC-CLA-EVENT.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `time-match-fires-at-value` | `SMC-CLA-EVENT.S6` | a time-match event fires when the internal time counter reaches the programmed value | RANDOMIZED | `time_match_value` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `time-match-not-before` | `SMC-CLA-EVENT.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `counter-fires-at-count` | `SMC-CLA-EVENT.S7` | a counter event counts cycles following an event match and fires when the programmed count is reached | RANDOMIZED | `counter_target`, `match_arrival_pattern` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | SF-027 |
| `counter-does-not-fire-early` | `SMC-CLA-EVENT.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `counter-restarts-on-new-match` | `SMC-CLA-EVENT.S7` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `two-events-same-cycle` | `SMC-CLA-EVENT.S8` | **[contested]** [BOUNDED-LIVENESS] two event types satisfied in the same cycle both register without one masking the other | RANDOMIZED | `event_type_pair` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `both-registered` | `SMC-CLA-EVENT.S8` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-CLA-EAP` — CLA event-action pairing and trigger status

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `single-event-single-action` | `SMC-CLA-EAP.S1` | a pair binds one or more events to one or more actions and fires those actions when the events occur | RANDOMIZED | `event_binding`, `action_binding` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | SF-027 |
| `multi-event-single-action` | `SMC-CLA-EAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `single-event-multi-action` | `SMC-CLA-EAP.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `global-enable-arms-all-pairs` | `SMC-CLA-EAP.S2` | pairs are enabled together once programming is complete | DIRECTED | — | `cover-property` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `partial-programming-no-trigger` | `SMC-CLA-EAP.S3` | a partially programmed pairing never triggers | DIRECTED | — | `assertion-cover` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `completed-programming-triggers` | `SMC-CLA-EAP.S3` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `status-names-firing-pair` | `SMC-CLA-EAP.S4` | the status flag records which pair triggered and the snapshot register latches the debug-bus value at the trigger moment | RANDOMIZED | `firing_pair_index` | `covergroup` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `snapshot-matches-trigger-cycle-value` | `SMC-CLA-EAP.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `two-pairs-same-cycle` | `SMC-CLA-EAP.S5` | **[contested]** [BOUNDED-LIVENESS] two pairs firing in the same cycle both set their status flags and the snapshot holds a single defined debug-bus value | DIRECTED | — | `assertion-cover` | `LIVE` | `dfd.adoc#Core` §Logic Analyzer | — |
| `both-status-flags-set` | `SMC-CLA-EAP.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `snapshot-value-defined` | `SMC-CLA-EAP.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-CLA-ACTION` — CLA actions

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `debug-interrupt-raised` | `SMC-CLA-ACTION.S1` | the debug interrupt action raises an interrupt to the CPU | DIRECTED | — | `covergroup` | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering (+1) | SF-010 |
| `debug-interrupt-cleared` | `SMC-CLA-ACTION.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `clocks-stopped-by-action` | `SMC-CLA-ACTION.S2` | the clock stop action halts clocks to freeze the design for inspection | DIRECTED | — | `covergroup` | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| `clocks-resumed` | `SMC-CLA-ACTION.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `cla-gpio-enable-asserted` | `SMC-CLA-ACTION.S3` | the GPIO toggle action drives the externally observable enable output | DIRECTED | — | `cover-property` | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering (+1) | — |
| `xtrigger-out-driven-on-action` | `SMC-CLA-ACTION.S4` | the cross-trigger out action signals other debug blocks that a local event occurred | DIRECTED | — | `cover-property` | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| `trace-capture-triggered` | `SMC-CLA-ACTION.S5` | the trace capture action hands the event to the trace subsystem | DIRECTED | — | `cover-property` | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| `custom-action-output-driven` | `SMC-CLA-ACTION.S6` | the reserved custom action outputs are driven for design-specific use | DIRECTED | — | `toggle-report` | `CONNECTIVITY` | `dfd.adoc#Actions` §and Cross-Triggering | — |
| `clock-stop-with-trace-write-inflight` | `SMC-CLA-ACTION.S7` | **[contested]** [BOUNDED-LIVENESS] a clock stop asserted while a trace write is in flight over the fabric leaves the trace write in a bounded defined state | DIRECTED | — | `assertion-cover` | `LIVE` | `dfd.adoc#Actions` §and Cross-Triggering (+1) | — |
| `trace-write-state-defined` | `SMC-CLA-ACTION.S7` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `no-corrupted-trace-packet` | `SMC-CLA-ACTION.S7` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-CLA-XTRIG` — CLA cross-triggering

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `xtrigger-in-arms-action` | `SMC-CLA-XTRIG.S1` | a cross-trigger input arms or fires a local action | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#xtrigger_ss_i@f2cb50de (+1) | — |
| `xtrigger-in-fires-action` | `SMC-CLA-XTRIG.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `xtrigger-out-propagates-local-event` | `SMC-CLA-XTRIG.S2` | a local event propagates outward on the cross-trigger output | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#xtrigger_ss_o@f2cb50de | — |

### `SMC-CLA-CLKSTOP` — CLA clock-stop enable and status

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `clock-stop-enabled-takes-effect` | `SMC-CLA-CLKSTOP.S1` | with the enable asserted a CLA clock stop takes effect | DIRECTED | — | `cover-property` | `LIVE` | hw/sys/smc/doc/port_table.adoc#tdr_dbg_ctrl_clock_stop_en_i@f2cb50de | — |
| `halt-status-asserted` | `SMC-CLA-CLKSTOP.S2` | the halt status output reports that the CLA has stopped clocks | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#tdr_dbg_ctrl_clocks_stopped_by_cla_o@f2cb50de | — |
| `halt-status-cleared` | `SMC-CLA-CLKSTOP.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `clock-stop-disabled-no-halt` | `SMC-CLA-CLKSTOP.S3` | with the enable deasserted the CLA does not stop clocks | DIRECTED | — | `assertion-cover` | `LIVE` | hw/sys/smc/doc/port_table.adoc#tdr_dbg_ctrl_clock_stop_en_i@f2cb50de | — |

### `SMC-DFD-TRACE` — Trace capture and streaming

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `sample-packet-emitted` | `SMC-DFD-TRACE.S1` | samples and events are encoded and packetized | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |
| `event-packet-emitted` | `SMC-DFD-TRACE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `single-source-merge` | `SMC-DFD-TRACE.S2` | packets from multiple sources are merged through the trace network | RANDOMIZED | `active_trace_source_mask` | `covergroup` | `LIVE` | hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |
| `multi-source-merge` | `SMC-DFD-TRACE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `trace-write-issued` | `SMC-DFD-TRACE.S3` | the trace master writes packets to memory over the trace memory interface | RANDOMIZED | `trace_ram_instance` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#trace_mem_req_o@f2cb50de | — |
| `trace-write-response-consumed` | `SMC-DFD-TRACE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `trace-instance-first` | `SMC-DFD-TRACE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `trace-instance-last` | `SMC-DFD-TRACE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `timestamp-monotonic` | `SMC-DFD-TRACE.S4` | a global timestamp with a synchronization mechanism places trace from different sources on a common time base | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/dfd.adoc#Trace@63552821 | — |
| `two-sources-alignable-after-capture` | `SMC-DFD-TRACE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `trace-mem-backpressure` | `SMC-DFD-TRACE.S5` | **[contested]** [BOUNDED-LIVENESS] trace memory backpressure stalls the trace master within a bound without corrupting a packet | RANDOMIZED | `backpressure_duration` | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#trace_mem_resp_i@f2cb50de (+1) | — |
| `trace-master-stalls` | `SMC-DFD-TRACE.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `no-partial-packet-written` | `SMC-DFD-TRACE.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-SCAN-CLASS1` — LOCKS shadow scan exclusion

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `locks-flops-absent-from-scan-chains` | `SMC-SCAN-CLASS1.S1` | the LOCKS shadow words appear on no scan chain | DIRECTED | — | `covergroup` | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | — |
| `class3-flops-present-on-scan-chains` | `SMC-SCAN-CLASS1.S1` | ″ | ″ | ″ | `covergroup` | `CONNECTIVITY` | ″ | ″ |
| `not-dumpable-per-lc-state` | `SMC-SCAN-CLASS1.S2` | the LOCKS shadow words are not dumpable in any lifecycle state | RANDOMIZED | `lc_state_value` | `covergroup` | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | SF-028, SF-052 |
| `not-dumpable-per-debug-grant` | `SMC-SCAN-CLASS1.S3` | the LOCKS shadow words are not dumpable under any debug grant | RANDOMIZED | `debug_grant_level` | `covergroup` | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | SF-028 |

### `SMC-SCAN-RANGEMAP` — Class 1 shadow range derivation

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `range-derived-from-metadata` | `SMC-SCAN-RANGEMAP.S1` | the Class 1 range is derived from the generated register map metadata, not from hard-coded word indices | DIRECTED | — | `cover-property` | `DECODE` | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | — |
| `locks-resolves-to-words-0-and-1` | `SMC-SCAN-RANGEMAP.S2` | LOCKS at fuse-map offset zero and 64 bits wide resolves to shadow words 0 and 1 | DIRECTED | — | `cover-property` | `DECODE` | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | — |
| `class1-word-count-2` | `SMC-SCAN-RANGEMAP.S3` | the 768-word fuse map splits into 2 Class 1 words and 766 Class 3 words | DIRECTED | — | `covergroup` | `DECODE` | `scan_protection.adoc#SMC` §shadow word allocation | — |
| `class3-word-count-766` | `SMC-SCAN-RANGEMAP.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `total-word-count-768` | `SMC-SCAN-RANGEMAP.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `wellformed-range-accepted` | `SMC-SCAN-RANGEMAP.S4` | an ill-formed, overlapping or out-of-array range map is rejected at elaboration rather than silently losing protection | DIRECTED | — | `assertion-cover` | `DECODE` | hw/sys/smc/doc/scan_protection.adoc#Implementation@2ecc7b22 | — |
| `overlapping-range-rejected` | `SMC-SCAN-RANGEMAP.S4` | ″ | ″ | ″ | `assertion-cover` | `DECODE` | ″ | ″ |
| `out-of-array-range-rejected` | `SMC-SCAN-RANGEMAP.S4` | ″ | ″ | ″ | `assertion-cover` | `DECODE` | ″ | ″ |

### `SMC-SCAN-DOWNSTREAM` — Downstream lock path has no scannable state

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `no-intermediate-flop-on-lock-path` | `SMC-SCAN-DOWNSTREAM.S1` | there is no state element between the Class 1 shadow words and the gated APB paths | DIRECTED | — | `assertion-cover` | `CONNECTIVITY` | `scan_protection.adoc#Downstream` §Lock Path | — |
| `violation-event-does-not-encode-locks-value` | `SMC-SCAN-DOWNSTREAM.S2` | the only sequential consumer carries an access-violation event and does not reveal or alter the lock state | DIRECTED | — | `covergroup` | `LIVE` | `scan_protection.adoc#Downstream` §Lock Path | — |
| `violation-event-does-not-change-locks` | `SMC-SCAN-DOWNSTREAM.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-SCAN-NOSECRET` — Absence of SMC confidentiality and secret-bearing assets

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `secure-tm-tied-inactive` | `SMC-SCAN-NOSECRET.S1` | the secure test-mode input is tied inactive so no secret disconnection occurs | DIRECTED | — | `cover-property` | `CONNECTIVITY` | `scan_protection.adoc#SMC` §eFuse Asset Classification | — |
| `secret-shadow-ranges-empty` | `SMC-SCAN-NOSECRET.S2` | the secret shadow range parameter is empty so no word is masked for confidentiality | DIRECTED | — | `covergroup` | `DECODE` | `scan_protection.adoc#SMC` §eFuse Asset Classification | SF-028 |
| `no-word-confidentiality-masked` | `SMC-SCAN-NOSECRET.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `lc-completion-handles-constant` | `SMC-SCAN-NOSECRET.S3` | the lifecycle state change completion handles are driven constant in the SMC instance and hold no SMC state | DIRECTED | — | `assertion-cover` | `CONNECTIVITY` | `scan_protection.adoc#Notes` §for DFT | — |

### `SMC-DFT-TESTMODE` — DFT test mode and scan reset

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `gater-test-port-driven` | `SMC-DFT-TESTMODE.S1` | the test enable reaches the clock-gater test ports so gated clocks run in test mode | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#test_en_i@f2cb50de | — |
| `gated-clock-runs-in-test-mode` | `SMC-DFT-TESTMODE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `axi-cell-test-input-driven` | `SMC-DFT-TESTMODE.S2` | the test enable reaches the AXI cell test inputs | DIRECTED | — | `cover-property` | `CONNECTIVITY` | hw/sys/smc/doc/port_table.adoc#test_en_i@f2cb50de | — |
| `scan-reset-bypasses-synchronizer` | `SMC-DFT-TESTMODE.S3` | the scan reset bypasses the reset synchronizers during DFT | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#scan_rst_ni@f2cb50de (+1) | — |
| `functional-reset-path-unused-in-scan` | `SMC-DFT-TESTMODE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-MAP-DECODE` — SMC component address decode

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `wdt-region` | `SMC-MAP-DECODE.S1` | each declared functional region routes to its component | RANDOMIZED | `target_region` | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Address Space Layout | SF-001, SF-002, SF-043, SF-053, SF-055 |
| `debug-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `system-control-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `gpio-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `i3c-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `peripheral-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `security-timing-dft-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `fabric-control-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `mailbox-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `data-processing-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `memory-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `cla-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `axil-external-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `remap-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `plic-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `timer-buserror-region` | `SMC-MAP-DECODE.S1` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `region-base-decodes` | `SMC-MAP-DECODE.S2` | each region's base and top address both decode to the same component and the address immediately beyond does not | RANDOMIZED | `target_region` | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-007, SF-053, SF-055 |
| `region-top-decodes` | `SMC-MAP-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `beyond-region-does-not` | `SMC-MAP-DECODE.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `cla-base-decodes` | `SMC-MAP-DECODE.S3` | the CLA aperture decodes over its declared 36 KB extent | DIRECTED | — | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map (+1) | SF-055 |
| `cla-top-decodes` | `SMC-MAP-DECODE.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `gap-access-errors` | `SMC-MAP-DECODE.S4` | **[contested]** [BOUNDED-LIVENESS] an access to a gap between declared regions terminates with an error rather than hanging | RANDOMIZED | `gap_address` | `covergroup` | `LIVE` | `memmap.adoc#SMC` §Address Space Layout (+1) | SF-043, SF-053, SF-055 |
| `gap-access-terminates-bounded` | `SMC-MAP-DECODE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

### `SMC-MAP-DUALBASE` — Local alias and global base addressing

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `local-base-reads-c0000000` | `SMC-MAP-DUALBASE.S1` | the local base is fixed read-only at 0xC000_0000 | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#Memory` §Map | — |
| `local-base-write-has-no-effect` | `SMC-MAP-DUALBASE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `global-base-programmed` | `SMC-MAP-DUALBASE.S2` | the global base is programmable by firmware | RANDOMIZED | `global_base_value` | `covergroup` | `LIVE` | `memmap.adoc#Memory` §Map | — |
| `global-base-readback-matches` | `SMC-MAP-DUALBASE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `same-resource-via-local-alias` | `SMC-MAP-DUALBASE.S3` | a resource reached at its local alias address and at its global address behaves identically | RANDOMIZED | `target_component` | `covergroup` | `LIVE` | `memmap.adoc#Memory` §Map | — |
| `same-resource-via-global` | `SMC-MAP-DUALBASE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `identical-read-data` | `SMC-MAP-DUALBASE.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `outside-aperture-not-local` | `SMC-MAP-DUALBASE.S4` | an access outside the relevant aperture is not routed to the local resource | DIRECTED | — | `cover-property` | `LIVE` | `memmap.adoc#Memory` §Map (+1) | — |
| `global-address-leaves-local-view-after-reconfig` | `SMC-MAP-DUALBASE.S5` | after global aperture reconfiguration, global addresses are usable for accesses that leave the local SMC view | DIRECTED | — | `cover-property` | `LIVE` | `fabric.adoc#Local` §and Remote Resource Access | — |

### `SMC-MAP-IFSTD` — Register interface standards

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `axil-32bit-address` | `SMC-MAP-IFSTD.S1` | AXI4-Lite register accesses use a 32-bit address and 64-bit data | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |
| `axil-64bit-data` | `SMC-MAP-IFSTD.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `apb4-32bit-address` | `SMC-MAP-IFSTD.S2` | APB4 register accesses use a 32-bit address and 32-bit data | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |
| `apb4-32bit-data` | `SMC-MAP-IFSTD.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `aligned-32bit-access` | `SMC-MAP-IFSTD.S3` | 32-bit registers sit on 4-byte boundaries and 64-bit registers on 8-byte boundaries | RANDOMIZED | `register_offset`, `access_size` | `covergroup` | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |
| `aligned-64bit-access` | `SMC-MAP-IFSTD.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `misaligned-access-outcome-defined` | `SMC-MAP-IFSTD.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `little-endian-byte-lane-mapping` | `SMC-MAP-IFSTD.S4` | byte ordering is little-endian throughout | DIRECTED | — | `assertion-cover` | `LIVE` | `memmap.adoc#Register` §Interface Standards | — |

### `SMC-EXTWIN-MAND` — Mandatory adopter external window

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `mandatory-region-base-decodes` | `SMC-EXTWIN-MAND.S1` | the mandatory region decodes at the external window base | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#AXI-Lite` §External Window | — |
| `per-pad-block-first` | `SMC-EXTWIN-MAND.S2` | the 65 per-pad control blocks decode at their declared stride | RANDOMIZED | `pad_block_index` | `covergroup` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| `per-pad-block-last` | `SMC-EXTWIN-MAND.S2` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `pll-wrapper-decodes` | `SMC-EXTWIN-MAND.S3` | the PLL wrapper decodes at its declared offset | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| `pvt-wrapper-decodes` | `SMC-EXTWIN-MAND.S4` | the PVT wrapper decodes at its declared offset | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |
| `efuse-shim-decodes` | `SMC-EXTWIN-MAND.S5` | the eFuse SHIM decodes at its declared offset | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#SMC` §AXI-Lite External Window — Mandatory Region | SF-054 |

### `SMC-EXTWIN-SUPP` — Supplementary external window and passthrough

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `supplementary-region-base-decodes` | `SMC-EXTWIN-SUPP.S1` | the supplementary region decodes at its declared base | DIRECTED | — | `cover-property` | `DECODE` | `memmap.adoc#AXI-Lite` §External Window | — |
| `identical-handling-both-regions` | `SMC-EXTWIN-SUPP.S2` | hardware treats the mandatory and supplementary regions identically, the split being organizational only | DIRECTED | — | `cover-property` | `LIVE` | `memmap.adoc#AXI-Lite` §External Window | — |
| `straps-lo-decodes` | `SMC-EXTWIN-SUPP.S3` | the captured GPIO strap registers are readable in the supplementary region | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#SMC` §AXI-Lite External Window — Supplementary Region (optional) | SF-007, SF-054 |
| `straps-hi-decodes` | `SMC-EXTWIN-SUPP.S3` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `remainder-access-passed-through` | `SMC-EXTWIN-SUPP.S4` | the unallocated remainder of the window is passed through to the chip-level adopter external port | RANDOMIZED | `remainder_offset` | `covergroup` | `LIVE` | `memmap.adoc#AXI-Lite` §External Window | — |
| `no-responder-access` | `SMC-EXTWIN-SUPP.S5` | **[contested]** [BOUNDED-LIVENESS] an access to the passthrough remainder with no adopter responder terminates with an error rather than hanging the bus | DIRECTED | — | `assertion-cover` | `LIVE` | `memmap.adoc#AXI-Lite` §External Window (+1) | — |
| `error-response-returned` | `SMC-EXTWIN-SUPP.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |
| `bus-not-hung` | `SMC-EXTWIN-SUPP.S5` | ″ | ″ | ″ | `assertion-cover` | `LIVE` | ″ | ″ |

### `SMC-MAP-SPARE` — System and spare register blocks

| Cell | Scenario | Intent | Method | Random knobs | Carrier | Proof | Spec ref | Blocked by |
|---|---|---|---|---|---|---|---|---|
| `chip-config-read` | `SMC-MAP-SPARE.S1` | the chip config block is readable and writable at its mapped offset | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#Chip` §Config, Scratch, NDM Reset, and Misc Wrap | — |
| `chip-config-write` | `SMC-MAP-SPARE.S1` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `scratch-write-readback` | `SMC-MAP-SPARE.S2` | the general-purpose scratch registers retain written values | RANDOMIZED | `scratch_register_index`, `scratch_value` | `covergroup` | `LIVE` | `memmap.adoc#Chip` §Config, Scratch, NDM Reset, and Misc Wrap | — |
| `scratch-all-zeros` | `SMC-MAP-SPARE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `scratch-all-ones` | `SMC-MAP-SPARE.S2` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `misc-wrap-base-decodes` | `SMC-MAP-SPARE.S3` | the miscellaneous wrapper aperture decodes over its declared extent | DIRECTED | — | `covergroup` | `DECODE` | `memmap.adoc#SMC` §Component Address Map | SF-055 |
| `misc-wrap-top-decodes` | `SMC-MAP-SPARE.S3` | ″ | ″ | ″ | `covergroup` | `DECODE` | ″ | ″ |
| `base-config-read` | `SMC-MAP-SPARE.S4` | the SMC base config block is accessible and carries the hang detector controls | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#Base` §Config, DFX Status, and GPIO POC/PBias (+1) | — |
| `hang-det-control-fields-present` | `SMC-MAP-SPARE.S4` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `dfx-status-read` | `SMC-MAP-SPARE.S5` | the DFX control and status block is accessible and carries the memory repair status | DIRECTED | — | `covergroup` | `LIVE` | `memmap.adoc#Base` §Config, DFX Status, and GPIO POC/PBias (+1) | SF-001, SF-053 |
| `repair-status-fields-present` | `SMC-MAP-SPARE.S5` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |
| `region-size-out-matches-csr` | `SMC-MAP-SPARE.S6` | the region size output presents the configured SMC address region size to external systems | DIRECTED | — | `covergroup` | `LIVE` | hw/sys/smc/doc/port_table.adoc#smc_region_size_o@f2cb50de | — |
| `region-size-out-updates-on-reprogram` | `SMC-MAP-SPARE.S6` | ″ | ″ | ″ | `covergroup` | `LIVE` | ″ | ″ |

## Contested-state scenarios — the ones least likely to be exercised today

Each demands bounded completion-or-error, not just the happy path. A coverage point on these that never fires is a finding about stimulus, not something to waive.

| Scenario | Intent | Cells | Proof | Blocked by |
|---|---|---|---|---|
| `SMC-CLK-PERIPH.S3` | [BOUNDED-LIVENESS] the peripheral clock is scaled independently of clk_smc and traffic still completes or errors within a bound | `periph-clk-slower-than-smc`, `periph-clk-faster-than-smc`, `periph-clk-ratio-non-integer` | `LIVE` | SF-041 |
| `SMC-PERIPH-CDC.S3` | [BOUNDED-LIVENESS] a register access in flight across the CDC bridge when the peripheral reset asserts completes or errors within a bound | `cdc-access-inflight-at-periph-reset`, `cdc-access-terminates-bounded` | `LIVE` | — |
| `SMC-CLKGATE.S5` | [BOUNDED-LIVENESS] activity arriving while the hysteresis countdown is in progress restores the clock without a glitch and without losing the request | `activity-during-hysteresis-countdown`, `no-clock-glitch-on-restore` | `LIVE` | — |
| `SMC-RST-POR.S4` | [BOUNDED-LIVENESS] power-good deasserting mid-operation drives the SMC back into full initialization within a bound | `powergood-drop-during-operation`, `full-init-reentered-bounded` | `LIVE` | — |
| `SMC-RST-PRIMARY.S5` | [BOUNDED-LIVENESS] primary reset asserted with fabric transactions in flight terminates them within a bound and leaves no bus hung | `reset-with-read-inflight`, `reset-with-write-inflight`, `no-outstanding-after-reset` | `LIVE` | — |
| `SMC-RST-WARM.S5` | [BOUNDED-LIVENESS] warm reset asserted while primary reset is deasserting settles to a single defined post-reset state | `warm-during-primary-deassert`, `single-defined-post-reset-state` | `LIVE` | — |
| `SMC-RST-SYNC.S5` | [BOUNDED-LIVENESS] a reset asserted while the target clock is gated or stopped still takes effect, and deassertion is held until the clock returns | `reset-assert-with-clock-stopped`, `deassert-held-until-clock-returns` | `LIVE` | — |
| `SMC-ISOLATE-CTRL.S5` | [BOUNDED-LIVENESS] FLR isolation asserting while software isolation is being cleared keeps the subsystem isolated, with a bounded settle | `flr-assert-concurrent-sw-clear`, `isolation-held-through-race` | `LIVE` | — |
| `SMC-FLR-SEQ.S4` | [BOUNDED-LIVENESS] a second FLR request arriving during an in-progress sequence reaches a bounded defined outcome rather than restarting indefinitely | `flr-during-pre-delay`, `flr-during-hold`, `sequence-completes-bounded` | `LIVE` | — |
| `SMC-FLR-CDC.S4` | [BOUNDED-LIVENESS] operation is reliable regardless of the PCIe-to-SMC clock frequency relationship, including a trigger near the synchronizer sampling edge | `pcie-faster-than-smc`, `pcie-slower-than-smc`, `trigger-near-sampling-edge` | `LIVE` | SF-025 |
| `SMC-SSRST.S4` | [BOUNDED-LIVENESS] a subsystem that never returns completion leaves the sequencer in a bounded and observable state rather than hung silently | `completion-withheld-one-subsystem`, `sequencer-state-observable-bounded` | `LIVE` | SF-020 |
| `SMC-PWRSEQ-GATE.S2` | [BOUNDED-LIVENESS] ext_boot_seq_done_i never asserting leaves the reset held in an observable state rather than releasing on an undefined path | `boot-seq-done-withheld`, `reset-remains-held-observable` | `LIVE` | SF-039 |
| `SMC-CPU-RSTVEC.S4` | [BOUNDED-LIVENESS] one core held in reset while the others execute leaves the running cores undisturbed | `one-core-reset-others-run` | `LIVE` | — |
| `SMC-SRAM-INIT.S4` | [BOUNDED-LIVENESS] a CPU access attempted before init_mem_done_o reaches a bounded defined outcome rather than returning indeterminate data | `access-before-init-done`, `bounded-defined-response` | `LIVE` | — |
| `SMC-MEMREPAIR.S6` | [BOUNDED-LIVENESS] the CPU cluster reset is not released until both repair and MBIST complete, so no core touches SRAM before repair | `cluster-held-until-repair-and-mbist`, `no-sram-access-before-repair` | `LIVE` | SF-039 |
| `SMC-CLUSTER-ISO.S2` | [BOUNDED-LIVENESS] a new transaction presented to the isolated L2 frontend slave port is blocked rather than terminated | `l2fe-new-txn-while-isolated-blocked` | `LIVE` | — |
| `SMC-CLUSTER-ISO.S3` | [BOUNDED-LIVENESS] a new transaction presented to the isolated MMIO master port is terminated with an SLVERR response | `mmio-read-while-isolated-slverr`, `mmio-write-while-isolated-slverr` | `LIVE` | — |
| `SMC-ISO-DRAIN.S4` | [BOUNDED-LIVENESS] a reset requested with transactions in flight drains and then resets within a bound, leaving no fabric response outstanding | `reset-req-with-read-inflight`, `reset-req-with-write-inflight`, `reset-req-with-four-outstanding`, `no-orphan-response` | `LIVE` | — |
| `SMC-ISO-RDC.S1` | [BOUNDED-LIVENESS] an asynchronous watchdog warm reset crossing into axi_isolate leaves the boundary in a defined state and is followed by a cold reset | `warm-reset-crossing-window`, `boundary-defined-after-crossing`, `cold-reset-follows` | `LIVE` | — |
| `SMC-WDT.S6` | [BOUNDED-LIVENESS] a second timeout arriving while the first warning is unserviced escalates to reset within a bound instead of stalling | `second-timeout-unserviced-warning`, `escalation-to-reset-bounded` | `LIVE` | — |
| `SMC-BEU.S6` | [BOUNDED-LIVENESS] a second bus error arriving while the first capture is unread reaches a defined and observable outcome | `second-error-before-read`, `capture-state-defined` | `LIVE` | SF-026 |
| `SMC-FAB-AXI4.S4` | [BOUNDED-LIVENESS] two managers targeting one subordinate concurrently both complete within a bound with no response mis-delivery | `two-managers-same-subordinate`, `three-managers-same-subordinate`, `responses-match-originators` | `LIVE` | — |
| `SMC-FAB-OUTSTANDING.S5` | [BOUNDED-LIVENESS] reaching an outstanding limit backpressures the manager and every accepted transaction still completes within a bound | `backpressure-asserted`, `all-accepted-complete`, `no-request-dropped` | `LIVE` | — |
| `SMC-FAB-MGR-ALIASPATH.S4` | [BOUNDED-LIVENESS] all three managers active concurrently on the shared remap and filter path all complete or error within a bound | `two-managers-concurrent`, `three-managers-concurrent`, `all-complete-bounded` | `LIVE` | — |
| `SMC-FAB-ERRSLV.S3` | [BOUNDED-LIVENESS] more unmapped requests arriving than the error slave outstanding limit are backpressured and each still receives its error response | `err-slv-saturated`, `every-request-answered` | `LIVE` | — |
| `SMC-FAB-ALIAS.S6` | [BOUNDED-LIVENESS] reprogramming a region while a matching transaction is in flight leaves that transaction with a single defined translation and a bounded completion | `reprogram-during-inflight`, `single-translation-applied`, `completion-bounded` | `LIVE` | — |
| `SMC-FAB-APERTURE.S5` | [BOUNDED-LIVENESS] REGION_SIZE reprogrammed with a transaction in flight leaves that transaction with one defined routing and a bounded completion | `reprogram-region-size-inflight`, `single-routing-applied`, `completion-bounded` | `LIVE` | — |
| `SMC-FILT-IN.S7` | [BOUNDED-LIVENESS] reprogramming an entry while a matching inbound transaction is in flight yields one defined admit-or-block decision within a bound | `entry-reprogram-during-inflight`, `single-decision-applied` | `LIVE` | — |
| `SMC-FAB-HANGDET.S7` | [BOUNDED-LIVENESS] a second detector asserting while the first is still asserted keeps the aggregate interrupt high and both remain individually identifiable | `second-hang-during-first`, `both-identifiable`, `clear-one-leaves-other-asserted` | `LIVE` | — |
| `SMC-DMA-XFER.S7` | [BOUNDED-LIVENESS] a reset asserted mid-transfer terminates the transfer within a bound and leaves no AXI response outstanding | `reset-during-address-phase`, `reset-during-data-phase`, `no-outstanding-after-reset` | `LIVE` | — |
| `SMC-DMA-STREAM0.S4` | [BOUNDED-LIVENESS] a NEXT_ID_0 read while a transfer is already in flight reaches a bounded defined outcome without corrupting the in-flight transfer | `next-id-read-while-busy`, `inflight-transfer-uncorrupted` | `LIVE` | — |
| `SMC-DMA-STREAM-RSVD.S5` | [BOUNDED-LIVENESS] a reserved-bank read while stream 0 is busy completes within a bound and does not disturb the active transfer | `reserved-read-during-stream0-busy`, `stream0-unaffected` | `LIVE` | — |
| `SMC-DMA-OUTSTANDING.S1` | up to DMA_MST_MAX_TXNS of 16 AXI transactions are concurrently outstanding per master interface | `outstanding-1`, `outstanding-15`, `outstanding-16` | `LIVE` | — |
| `SMC-DMA-OUTSTANDING.S4` | [BOUNDED-LIVENESS] at the outstanding limit the backend is backpressured and every issued transaction still completes within a bound | `limit-reached-backpressure`, `all-issued-complete` | `LIVE` | — |
| `SMC-DMA-FIFO.S3` | [BOUNDED-LIVENESS] back-pressure from a system overload is absorbed without losing a command | `sustained-backpressure`, `command-count-preserved`, `no-command-dropped` | `LIVE` | — |
| `SMC-DMA-ARB.S7` | [BOUNDED-LIVENESS] simultaneous responses to one control interface are resolved by second-level round robin and all are delivered without deadlock | `simultaneous-responses`, `all-responses-delivered`, `no-deadlock` | `LIVE` | — |
| `SMC-DMA-CTRL.S2` | [BOUNDED-LIVENESS] a configuration write attempted while locked reaches a bounded defined outcome and does not corrupt the active transfer | `locked-write-attempted`, `active-transfer-uncorrupted`, `write-outcome-defined` | `LIVE` | SF-016 |
| `SMC-DMA-CTRL.S5` | [BOUNDED-LIVENESS] an abort raised while AXI beats are in flight settles within a bound with no orphaned outstanding response | `abort-during-address-phase`, `abort-during-data-phase`, `no-orphan-outstanding` | `LIVE` | SF-017 |
| `SMC-DMA-ERR.S3` | [BOUNDED-LIVENESS] a second AXI error arriving while the first is still unread reaches a defined and observable status | `second-error-before-status-read`, `status-defined-after-two-errors` | `LIVE` | — |
| `SMC-ZERO-FSM.S6` | [BOUNDED-LIVENESS] a trigger written while the zeroer is busy reaches a bounded defined outcome and does not corrupt the running operation | `trigger-while-busy`, `running-operation-uncorrupted`, `outcome-defined` | `LIVE` | — |
| `SMC-ZERO-FSM.S7` | [BOUNDED-LIVENESS] a reset asserted mid-burst returns the machine to idle within a bound with no AXI response outstanding | `reset-in-address-phase`, `reset-in-data-phase`, `idle-after-reset`, `no-outstanding-after-reset` | `LIVE` | — |
| `SMC-ZERO-FSM.S8` | [BOUNDED-LIVENESS] an abort raised with write responses still outstanding settles within a bound | `abort-with-outstanding-responses`, `settles-bounded` | `LIVE` | SF-019 |
| `SMC-ZERO-OUTSTANDING.S2` | up to 32 concurrent AXI transactions are permitted | `outstanding-1`, `outstanding-31`, `outstanding-32` | `LIVE` | — |
| `SMC-ZERO-OUTSTANDING.S3` | [BOUNDED-LIVENESS] at the maximum, flow control applies back-pressure until resources free and the operation still completes within a bound | `backpressure-at-max`, `resumes-after-response`, `operation-completes-bounded` | `LIVE` | — |
| `SMC-ZERO-ERR.S2` | [BOUNDED-LIVENESS] a second error arriving while the first is still pending leaves a defined observable status and a bounded completion | `two-errors-pending`, `status-defined`, `operation-terminates-bounded` | `LIVE` | — |
| `SMC-INT-EXTSYNC.S3` | [BOUNDED-LIVENESS] an external pulse narrower than the synchronizer sampling window reaches a defined outcome rather than an intermediate value on the vector | `pulse-shorter-than-window`, `pulse-equal-to-window`, `pulse-longer-than-window`, `vector-bit-never-x` | `LIVE` | — |
| `SMC-INT-PERIPHMAP.S14` | [BOUNDED-LIVENESS] two sources feeding the same OR-reduced bit asserting simultaneously keep the bit asserted and stay individually identifiable through the source status registers | `two-sources-same-or-bit`, `bit-stays-asserted`, `both-identified-from-status`, `clear-one-leaves-bit-asserted` | `LIVE` | — |
| `SMC-INT-MBX-SMC.S3` | [BOUNDED-LIVENESS] several mailbox channels asserting concurrently all remain visible on their own bits | `two-channels-concurrent`, `all-channels-concurrent` | `LIVE` | — |
| `SMC-PLIC-THRESHOLD.S2` | [BOUNDED-LIVENESS] lowering the threshold while a source is pending releases that source for delivery within a bound | `source-masked-by-threshold`, `threshold-lowered`, `source-delivered-bounded` | `LIVE` | — |
| `SMC-PLIC-CLAIM.S3` | [BOUNDED-LIVENESS] two cores claiming the same source concurrently produce exactly one delivery, with the loser receiving no duplicate | `simultaneous-claim-two-cores`, `exactly-one-winner`, `loser-gets-no-duplicate` | `LIVE` | — |
| `SMC-PLIC-CLAIM.S4` | [BOUNDED-LIVENESS] a new assertion arriving inside the claim and completion window is not lost and is delivered within a bound | `assert-between-claim-and-complete`, `assert-at-completion-cycle`, `interrupt-not-lost` | `LIVE` | — |
| `SMC-CLINT.S6` | [BOUNDED-LIVENESS] a compare value written while that core's timer interrupt is already pending reaches a defined pending state within a bound | `compare-write-with-pending-irq`, `pending-state-defined`, `irq-cleared-when-compare-advanced` | `LIVE` | — |
| `SMC-PERIPH-DECODE.S4` | [BOUNDED-LIVENESS] an access to an instance index beyond the populated count terminates with an error rather than hanging | `beyond-last-instance-errors`, `access-terminates-bounded` | `LIVE` | SF-053 |
| `SMC-GPIO-IRQ.S3` | [BOUNDED-LIVENESS] two wraps in the same OR-reduced half asserting together keep the aggregate bit high and both remain identifiable | `two-wraps-same-half`, `aggregate-stays-high`, `both-identifiable-from-status` | `LIVE` | SF-004 |
| `SMC-GPIO-STRAPS.S5` | [BOUNDED-LIVENESS] a pad value changing after the capture window leaves the captured strap value unchanged | `pad-changes-after-capture`, `captured-value-stable` | `LIVE` | — |
| `SMC-TELEM-RX.S4` | [BOUNDED-LIVENESS] valid held with ready low backpressures the source and no telemetry data is lost once ready returns | `ready-low-stall`, `data-held-during-stall`, `no-data-lost-after-resume` | `LIVE` | — |
| `SMC-TELEM-RX.S5` | [BOUNDED-LIVENESS] a flush requested while data transfers are active reaches a bounded completion without dropping accepted data | `flush-during-active-transfer`, `accepted-data-retained`, `flush-completes-bounded` | `LIVE` | — |
| `SMC-I2C.S6` | [BOUNDED-LIVENESS] a target receive FIFO filled to its 64-entry depth backpressures the bus without silently dropping bytes | `rx-fifo-full-at-64`, `backpressure-or-defined-overflow-status`, `no-silent-byte-loss` | `LIVE` | — |
| `SMC-MBX.S5` | [BOUNDED-LIVENESS] a write to a channel whose depth-2 FIFO is already full reaches a bounded defined outcome without silently discarding a message | `write-to-full-fifo`, `no-silent-message-loss`, `outcome-observable-in-status` | `LIVE` | — |
| `SMC-MBX.S6` | [BOUNDED-LIVENESS] concurrent inbound and outbound activity on the same mailbox pair both complete within a bound and do not corrupt each other | `concurrent-in-and-out`, `both-complete`, `no-cross-corruption` | `LIVE` | — |
| `SMC-EFUSE-LOCKS.S6` | [BOUNDED-LIVENESS] a locked-field access concurrent with a permitted access leaves the permitted access unaffected and both terminate within a bound | `locked-and-permitted-concurrent`, `permitted-access-unaffected`, `both-terminate-bounded` | `LIVE` | — |
| `SMC-CLA-EVENT.S8` | [BOUNDED-LIVENESS] two event types satisfied in the same cycle both register without one masking the other | `two-events-same-cycle`, `both-registered` | `LIVE` | — |
| `SMC-CLA-EAP.S5` | [BOUNDED-LIVENESS] two pairs firing in the same cycle both set their status flags and the snapshot holds a single defined debug-bus value | `two-pairs-same-cycle`, `both-status-flags-set`, `snapshot-value-defined` | `LIVE` | — |
| `SMC-CLA-ACTION.S7` | [BOUNDED-LIVENESS] a clock stop asserted while a trace write is in flight over the fabric leaves the trace write in a bounded defined state | `clock-stop-with-trace-write-inflight`, `trace-write-state-defined`, `no-corrupted-trace-packet` | `LIVE` | — |
| `SMC-DFD-TRACE.S5` | [BOUNDED-LIVENESS] trace memory backpressure stalls the trace master within a bound without corrupting a packet | `trace-mem-backpressure`, `trace-master-stalls`, `no-partial-packet-written` | `LIVE` | — |
| `SMC-MAP-DECODE.S4` | [BOUNDED-LIVENESS] an access to a gap between declared regions terminates with an error rather than hanging | `gap-access-errors`, `gap-access-terminates-bounded` | `LIVE` | SF-043, SF-053, SF-055 |
| `SMC-EXTWIN-SUPP.S5` | [BOUNDED-LIVENESS] an access to the passthrough remainder with no adopter responder terminates with an error rather than hanging the bus | `no-responder-access`, `error-response-returned`, `bus-not-hung` | `LIVE` | — |

## Interaction points

An interaction checker proves every feature it crosses from one joint observation, so each feature it names must also carry its own single-feature cell above.

| Key | Intent | Features | Cells | Method |
|---|---|---|---|---|
| `INT-POR-BOOT` | the cold boot chain runs in order - power-good stable, fuse sense, memory repair, MBIST, then cluster reset release and the first fetch at the ROM vector | `SMC-RST-POR`, `SMC-MEMREPAIR`, `SMC-CPU-RSTVEC`, `SMC-ROM-MAP` | `ordered-powergood-fusesense-repair-mbist-release`, `first-fetch-at-rom-vector`, `no-step-out-of-order` | DIRECTED |
| `INT-ISO-RESET` | a pending cluster software reset isolates and drains both AXI ports before the reset is applied | `SMC-ISO-DRAIN`, `SMC-CLUSTER-ISO` | `isolate-then-drain-then-reset`, `no-reset-before-drained`, `no-orphan-fabric-response` | DIRECTED |
| `INT-FLR-COOL` | an FLR trigger crosses into the SMC and reference domains, asserts isolation, waits the pre-reset delay, asserts cool reset for the hold time and bypasses memory repair | `SMC-FLR-CDC`, `SMC-ISOLATE-CTRL`, `SMC-FLR-SEQ`, `SMC-RST-COOL`, `SMC-REPAIR-BYPASS` | `flr-edge-to-isolation`, `isolation-to-cool-reset-delay`, `cool-reset-hold-observed`, `repair-bypassed-during-flr` | DIRECTED |
| `INT-OUTBOUND-PATH` | outbound traffic is alias remapped, then privilege remapped, then filtered on the remapped address, and leaves carrying the source ID of the path it took | `SMC-FAB-ALIAS`, `SMC-FAB-PRIVREMAP`, `SMC-FILT-OUT`, `SMC-FAB-SRCID` | `alias-then-privilege-then-filter-order`, `filter-sees-remapped-address`, `srcid-matches-path-taken` | DIRECTED |
| `INT-FILTER-ERRSLV` | an inbound transaction no filter entry admits is routed to the error slave and the initiator receives a decode error | `SMC-FILT-IN`, `SMC-FILT-NS`, `SMC-FAB-ERRSLV` | `unmatched-inbound-to-error-slave`, `decode-error-returned-to-initiator`, `protected-resource-untouched` | DIRECTED |
| `INT-DMA-FILTER` | a DMA transfer is subject to the fabric alias remap and filtering mechanisms on its way to the destination | `SMC-DMA-XFER`, `SMC-FAB-MGR-ALIASPATH`, `SMC-FILT-OUT` | `dma-transfer-permitted-by-filter`, `dma-transfer-blocked-by-filter`, `dma-error-reported-on-block` | DIRECTED |
| `INT-DMA-IRQ-PLIC` | a DMA completion pulse reaches its vector bit, becomes the corresponding PLIC source and is claimed by a core | `SMC-DMA-IRQ`, `SMC-INT-INTERNAL`, `SMC-INT-PLICID`, `SMC-PLIC-CLAIM` | `dma-completion-to-vector-bit`, `vector-bit-to-plic-source`, `source-claimed-and-completed` | DIRECTED |
| `INT-ZERO-IRQ-PLIC` | a zeroer completion pulse reaches its vector bit, becomes the corresponding PLIC source and is claimed by a core | `SMC-ZERO-IRQ`, `SMC-INT-INTERNAL`, `SMC-INT-PLICID`, `SMC-PLIC-CLAIM` | `zeroer-completion-to-vector-bit`, `vector-bit-to-plic-source`, `source-claimed-and-completed` | DIRECTED |
| `INT-CLA-CLKSTOP-IRQ` | a CLA clock-stop action drives the halt status which in turn drives the CLA clock-stop interrupt bit | `SMC-CLA-ACTION`, `SMC-CLA-CLKSTOP`, `SMC-INT-INTERNAL` | `action-to-halt-status`, `halt-status-to-interrupt-bit`, `deassert-propagates` | DIRECTED |
| `INT-WDT-WARM` | a watchdog timeout asserts the warm reset, which crosses asynchronously into the cluster isolate logic and is followed by a cold reset | `SMC-WDT`, `SMC-RST-WARM`, `SMC-ISO-RDC` | `wdt-timeout-to-warm-reset`, `warm-reset-crossing-observed`, `cold-reset-follows` | DIRECTED |
| `INT-EFUSE-LOCK-IRQ` | an attempted locked-field access raises the violation interrupt which reaches its declared peripheral interrupt bit | `SMC-EFUSE-LOCKS`, `SMC-INT-PERIPHMAP` | `locked-access-to-violation-event`, `violation-event-to-vector-bit`, `permitted-access-raises-nothing` | DIRECTED |
| `INT-HANGDET-CLEAR` | a hang interrupt is identified and cleared only through the base config hang detector control registers | `SMC-FAB-HANGDET`, `SMC-MAP-SPARE` | `hang-identified-via-base-config`, `hang-cleared-via-base-config`, `interrupt-deasserts-after-clear` | DIRECTED |
| `INT-ROM-ENDIAN-FUSE` | the eFuse shadow ROM endianness bit determines the byte order of every ROM word the CPU reads | `SMC-ROM-ENDIAN`, `SMC-EFUSE-IF` | `fuse-bit-set-word-reversed`, `fuse-bit-clear-word-unchanged` | DIRECTED |
| `INT-STRAP-REPAIR` | the strap captured at cold reset on the bypass pin determines whether memory repair runs in that boot | `SMC-GPIO-STRAPS`, `SMC-REPAIR-BYPASS` | `strap-set-repair-bypassed`, `strap-clear-repair-executed` | DIRECTED |
| `INT-STRAP-OCTS` | the chiplet-is-primary strap captured at cold reset selects the OCTS primary or secondary mode | `SMC-GPIO-STRAPS`, `SMC-OCTS` | `strap-primary-selects-primary-mode`, `strap-secondary-selects-secondary-mode` | DIRECTED |
| `INT-APERTURE-DECODE` | the region size CSR sizes the local alias window and the global aperture together, so reprogramming it moves both decodes at once | `SMC-FAB-APERTURE`, `SMC-MAP-DUALBASE` | `both-windows-resize-together`, `local-and-global-remain-equal-size` | DIRECTED |
| `INT-CDC-PERIPH-IRQ` | an interrupt raised by a peripheral in the peripheral clock domain crosses into the SMC clock domain and appears on its declared vector bit | `SMC-PERIPH-CDC`, `SMC-INT-PERIPHMAP`, `SMC-CLK-PERIPH` | `periph-domain-irq-crosses-cdc`, `appears-on-declared-vector-bit`, `deassert-crosses-back` | DIRECTED |
| `INT-SCAN-LOCKPATH` | the lock protection holds only jointly - the LOCKS flops are off every scan chain and no scannable flop downstream re-derives the decision | `SMC-SCAN-CLASS1`, `SMC-SCAN-DOWNSTREAM` | `locks-off-scan-chains`, `no-scannable-downstream-lock-state`, `protection-holds-jointly` | DIRECTED |

---
*Derived from:* feature list revision 1, `content_sha256` `d0c28f7ecce6f290`; spec audit `de1443444744b135`.
