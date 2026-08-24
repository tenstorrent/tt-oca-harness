<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->
# SMC DV Port Plan — local nonfree2 → local oss2

**Date:** 2026-08-19  
**Workspace roots (local only):**

| Role | Absolute path |
|------|---------------|
| Source tree | `/proj_soc/user_dev/minshaoho/tryrun/nonfree2` |
| Destination tree | `/proj_soc/user_dev/minshaoho/tryrun/oss2` |

**Sources compared:**

| Side | Path | Role |
|------|------|------|
| Commercial / nonfree2 | `/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smc/dv/tb/tb_uvm/yaml/testlist_smc_chiplet.yaml` | Chiplet catalog + Jenkins gates |
| Commercial cocotb | `/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smc/dv/tb/tb_uvm/cocotb_tests/` | ~172 Python tests (often FW-assisted) |
| Commercial fw | `/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smc/dv/fw/tests/` | ROM/CPU-driven scenarios |
| Local enrolled | `/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smc/dv/testlists/all.toml` (+ leaf tomls) | Reportable PASS surface |
| Local deferred | `/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smc/dv/testlists/deferred.toml` | Named but not enrollable PASS |
| Local live | `cd /proj_soc/user_dev/minshaoho/tryrun/oss2 && python3 tools/dv/run_dv.py --dut smc --list` | Runnable modules |

**Related local docs (do not replace):**

- `hw/sys/smc/dv/docs/oss_smc_dev.md` — older module→representative port map
- `hw/sys/smc/dv/docs/ref_test_dev.md` — how to rebuild a test (env / seq / checkers)
- `hw/sys/smc/dv/docs/smc_oss_execution_guide.md` — run recipes + sign-off evidence
- `hw/sys/smc/dv/README.md` — green policy (real DUT RTL only)

**Local OSS policy (binding):** claim only real DUT RTL paths; no Cadence-only
VIP as sole PASS; no TB placeholder / fake BFM / hardcoded glue demos as enrolled
PASS; `deferred.toml` never reports as enrolled PASS. Prefer BFM / frontdoor
cocotb over commercial firmware binaries when rebuilding. See README green
policy and `testlists/deferred.toml` blocker tags.

Related pin notes: [`port_table.adoc`](port_table.adoc).

---

## 1. Scale snapshot

| Metric | Count |
|--------|------:|
| nonfree2 chiplet leaf `name: *_test` | ~227 |
| nonfree2 `Main_SMC_Chiplet_Nightly_Regression` (primary green) | 126 |
| nonfree2 `Main_SMC_Chiplet_Sanity_Regression` | 2 |
| nonfree2 `I2C_Regression` | 24 |
| nonfree2 `UART_Log_Engine_Regression` | 16 |
| nonfree2 `Main_SMC_BL0_Regression` (OCCP / master_bfm) | 32 |
| Local cocotb `tests/*.py` | ~118 |
| Local enrolled `[[tests]]` names (excl. deferred) | ~143 |
| Local `smoke` group | 36 |
| Local `deferred.toml` catalog | ~11 |

**Nightly (126) vs local disposition (conservative: exact name or documented rename only):**

| Bucket | Count | Meaning |
|--------|------:|---------|
| Already LIVE in local oss2 | ~21 | Same name or intentional rename already enrolled |
| Named / blocked in deferred | ~0–few | PLL/PVT / I3C DAT / fake BFM / tb_glue family |
| Missing intent or depth vs Nightly | ~105 | Primary rebuild candidates (Tier A–D below) |

Local also has deepeners **not** on commercial Nightly (observability multi-agent,
`p1_coverage_gap*`, mailbox field sweeps, zeroer CG matrix, …). Keep those;
they are local-ahead progress, not gaps.

**Important asymmetry vs SMU:** commercial SMC Nightly is largely **firmware +
preload** driven; local policy rebuilds intent as **PyUVM cocotb + OCAH VIP**.
Do not copy `.c` FW images as the enrolled PASS mechanism unless the local
`dv/fw/` flow is the deliberate vehicle for that scenario.

---

## 2. Commercial gates to track

| Jenkins / regression | Compile | Notes for local port |
|----------------------|---------|----------------------|
| `Main_SMC_Chiplet_Sanity_Regression` | `compile_smc_chiplet` | 2-test smoke gate |
| `Main_SMC_Chiplet_Nightly_Regression` | `compile_smc_chiplet` | **Primary port source** (126) |
| `I2C_Regression` / `I2C_P2_Regression` | often `*_with_i2c_model` | I2C / SMBus depth |
| `UART_Log_Engine_Regression` | chiplet | UART log-engine cluster |
| `Main_SMC_Chiplet_Register_Regression` | chiplet | Register / boundary |
| `Main_SMC_BL0_Regression` | `compile_w_master_bfm` | OCCP + Cadence master BFM — **not Phase-1 local enroll** |
| `Main_SMC_Chiplet_Performance_*` | chiplet | Perf — out of local density scope |

Commercial constructs that do **not** port as enrolled PASS:

- Cadence I3C master_bfm / `INSTANTIATE_SMC_MASTER_BFM` (BL0 / OCCP path)
- Commented-out OCA↔Cadence I3C Nightly entries (Yayoi stub note in yaml)
- FW-only green that cannot be expressed with product pins / OCAH VIP
- PLL/PVT OKAY-wrap-only exercises → local `rtl_placeholder`

---

## 3. Port tiers (rebuild, do not blind-copy)

### Rebuild rule (every test)

1. Read commercial intent (yaml entry + cocotb and/or `fw/tests/`).
2. Map to local TB pins on `hw/sys/smc/dv/tb/tb_top.sv` (`smc_wrapper`).
3. Rewrite under `cocotb/{tests,seq_lib}/` with honest checkers.
4. Inventory in `deferred.toml` if blockers remain; enroll leaf toml only after
   Verilator (or documented commercial-sim) PASS with real DUT evidence.
5. Never enroll toggle-as-sole-PASS, fake BFM, or TB-glue demos.

Commercial reference sources:

```text
/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smc/dv/tb/tb_uvm/cocotb_tests/
/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smc/dv/fw/tests/
```

Local landing zones:

```text
/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smc/dv/cocotb/tests/
/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smc/dv/cocotb/seq_lib/
/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smc/dv/testlists/
/proj_soc/user_dev/minshaoho/tryrun/oss2/hw/sys/smc/dv/fw/tests/   # only when FW is the chosen vehicle
```

### Tier A — Protocol depth (highest local value)

Nightly has depth that local smoke only partially covers. Rebuild with OCAH VIP;
strip Cadence / Force / deposit.

| Cluster | Commercial examples | Local action |
|---------|---------------------|--------------|
| I2C P0 matrix | `smc_i2c_p0_rdwr/nack/multictrl/fifo/timeout/stretch/cfifo/conti` | **LIVE** in `i2c.toml` (BFM + `+smc_i2c_shared_bus`); `nack_tc1/tc2` → `covered_by_live` |
| I2C FIFO CSR | `smc_i2c_fifo_full_test` | **LIVE** CSR-only FMT/TX full + RX/ACQ empty |
| SMBus | `smc_smbus_alert_suspend_test`, `smc_i2c_target_smbus_test` | **LIVE**: DUT-internal ALERT/ARA/SUSPEND; VIP ARA + ext SMBSUS pad40 |
| I2C rw/sanity | `smc_i2c_rw_test`, `read/write_sanity` | `covered_by_live` ≈ `p0_rdwr` + `p0_conti` |
| UART depth | **LIVE** in `uart.toml`: fifo / irq / error / baud / extremes / sanity; `engine_sanity` → covered_by log-engine + sanity | — |
| Fabric split | wr/rd/error/`filter_no_remap` | `covered_by_live` ≈ responder / slverr / `smc_output_filter_remap_security_test` |

**Suggested first rebuilds (2–3):**

1. `smc_i2c_p0_rdwr_test` (commercial cocotb exists; clear VIP path)
2. `smc_output_fabric_wr_rd_error_test` (negative fabric path)
3. `smc_uart_fifo_basic_trigger_reset_test` (UART depth beyond loopback)

### Tier B — Already LIVE or intentionally renamed (do not re-port)

Track coverage honesty; deepen only if local PASS is thinner than commercial intent.

| Commercial | Local stand-in | Notes |
|------------|----------------|-------|
| `smc_cpu_sanity_test` | same | Keep |
| `smc_register_test` (+ cold/warm) | `smc_register_sanity_test` / `smc_multi_reset_csr_persistence_test` | Cold/warm may still need dedicated local cases |
| `smc_i2c_sanity_test` / target | `smc_i2c_master_target_test` | Local is representative, not full P0 matrix |
| `smc_cpu_traffic_sep_axi_test` | `smc_cpu_to_sep_axi_test` | Ext / sep+ext still MISS |
| `smc_efuse_otp_clock_config_test` | `smc_efuse_otp_clock_test` | |
| `smc_mailbox_int_test` | `smc_mailbox_irq_test` | Local has deeper mailbox suite already |
| `smc_output_fabric_wr_rd_test` | `smc_input_output_fabric_wr_rd_test` | |
| `smc_output_fabric_filter_test` | `smc_output_filter_remap_security_test` | no-remap sibling still MISS |
| `smc_flr_sanity_test`, `smc_dma_sanity_test`, `smc_dfd_sanity_test`, `smc_zeroer_sanity_test`, `smc_avsbus_sanity_test`, `smc_uart_log_engine_reg_rw_test`, `smc_uart_loopback_basic_test`→`smc_uart_loopback_test`, `smc_external_interrupts_test`, `smc_efuse_jtag_lc_negative_test` | same / rename | Audit checkers before claiming parity |

### Tier C — Reset / boot / CPU traffic (port after Tier A pilots)

| Cluster | Commercial examples | Blockers / notes |
|---------|---------------------|------------------|
| Cool-reset matrix | `smc_cool_reset_from_{pcie,primary_chiplet,bmc}_test`, `*_x_cold_*`, `*_x_cool_*` | Needs cool-reset pin / source modeling on local TB (`rst_cool_ni` already in `smc_cold_reset_test` S6; extra sources still MISS). `smc_ndm_reset_test` **LIVE** (pin + PROCESS CSR; no Force/FW) |
| Boot stall | `smc_jtag_boot_stall_sanity_test`, `smc_gpio_boot_stall_*`, `smc_mixed_boot_stall_*` | **LIVE** BFM: pad 57 sticky + JTAG ovrd + mixed val=1 lockout (`+smc_hold_cpu_boot`) |
| CPU traffic | `smc_cpu_traffic_test`, `*_ext_axi_*`, `*_sep_plus_ext_*`, `smc_mem_boundary_test` | `smc_spm_mem_boundary_test` **LIVE** (SPM edges via SEP_IN AXI). Ext / sep+ext still MISS |
| Hang / GPIO P0 | `smc_hang_detector_sanity_test`, `smc_gpio_p0_{int,mux}_test` | **LIVE** BFM: hang irq_test + per-source OR; GPIO edge IRQ + register/LSIO mux |

### Tier D — eFuse / ROM / reg-boundary / PLL-PVT

| Cluster | Action |
|---------|--------|
| eFuse Nightly depth (~17 MISS) | **Diff done.** Local LIVE covers map/permission/JTAG-LC/clock/burn-shadow/locked-access IRQ/boundary ext_boot/`smc_efuse_read_program_timeout_test` (timeout CSR). Remainder in `deferred.toml` (`covered_by_live` / `no_force` / `needs_fw_boot`). Do not copy 17 commercial leaves. |
| `smc_reg_boundary_test_GROUP_*` | Commercial FW sharding; local `smc_register_boundary_depth_test` **LIVE** — GROUP_* tagged `covered_by_live` |
| ROM dummy rewrite | Local FW/ROM flow if needed; else CSR-visible ROM window via AXI |
| PLL / PVT / DVFS / combined PVT | Keep in `deferred.toml` (`rtl_placeholder`) until adopter macros are real |

### Do not port (or keep hold)

| Class | Examples | Reason |
|-------|----------|--------|
| BL0 / OCCP / master_bfm | `Main_SMC_BL0_Regression`, `smc_occp_*` | Cadence BFM + secure-boot surface; separate track |
| Cadence↔OCA I3C | commented Nightly I3C OCA entries | Vendor VIP; local I3C full CCC → `needs_i3c_dat_dct` |
| Perf | `Main_SMC_Chiplet_Performance_*` | Not density PASS |
| Placeholder PLL/PVT | `smc_pll_*`, `smc_pvt_*` OKAY-wrap only | `rtl_placeholder` |
| Fake BFM | AVSBus/OCTS fake | `fake_bfm` |
| TB glue | `smc_dfd_dbs_fault_inject_test` (hardcoded token class) | `tb_glue` / `not_dut_rtl` |
| SV UVM-only | 24 commercial UVM tests | Rebuild as PyUVM if intent still needed |

---

## 4. Nightly (126) checklist vs local oss2

Legend: **LIVE** = local runnable (exact or documented rename) · **DEF** = deferred policy · **MISS** = rebuild candidate · **PARTIAL** = local smoke exists but thinner than Nightly intent.

### 4.1 LIVE / rename (do not re-invent)

| Commercial | Local | Notes |
|------------|-------|-------|
| `smc_cpu_sanity_test` | LIVE | |
| `smc_register_test` | LIVE→`smc_register_sanity_test` | |
| `smc_register_test_cold` | PARTIAL→register sanity | Dedicated cold still optional |
| `smc_register_test_warm` | PARTIAL→`smc_multi_reset_csr_persistence_test` | |
| `smc_i2c_sanity_test` | LIVE→`smc_i2c_master_target_test` | P0 matrix still MISS |
| `smc_i2c_target_sanity_test` | LIVE→same | |
| `smc_uart_log_engine_reg_rw_test` | LIVE | |
| `smc_uart_loopback_basic_test` | LIVE→`smc_uart_loopback_test` | |
| `smc_flr_sanity_test` | LIVE | |
| `smc_dma_sanity_test` | LIVE | |
| `smc_dfd_sanity_test` | LIVE | |
| `smc_zeroer_sanity_test` | LIVE | |
| `smc_avsbus_sanity_test` | LIVE | |
| `smc_mailbox_int_test` | LIVE→`smc_mailbox_irq_test` | |
| `smc_cpu_traffic_sep_axi_test` | LIVE→`smc_cpu_to_sep_axi_test` | |
| `smc_output_fabric_wr_rd_test` | LIVE→`smc_input_output_fabric_wr_rd_test` | |
| `smc_output_fabric_filter_test` | LIVE→`smc_output_filter_remap_security_test` | |
| `smc_efuse_otp_clock_config_test` | LIVE→`smc_efuse_otp_clock_test` | |
| `smc_efuse_jtag_lc_negative_test` | LIVE | |
| `smc_external_interrupts_test` | LIVE | |
| `smc_static_cg_sanity_test` | LIVE in `clock.toml` **and** listed in deferred group | Resolve policy: placeholder → deferred only |

### 4.2 MISS buckets (rebuild inventory)

| Bucket | Approx. | Priority |
|--------|--------:|----------|
| I2C / SMBus depth | 16 | Tier A |
| eFuse depth | 17 | Tier D (diff local first) |
| reg_boundary GROUP_* | 17 | Tier D (collapse to one suite) |
| UART depth | 7 | Tier A |
| Fabric split / error / no-remap | 6 | Tier A |
| Cool-reset | 5 | Tier C |
| PLL/PVT | 5 | DEF / placeholder |
| Boot stall / hang / GPIO P0 | 6 | Tier C |
| CPU traffic / mem boundary | 4 | Tier C |
| I3C / xtrigger / mutex / misc | ~6+ | Tier C/D or DEF |
| Sanity siblings (chiplet/plic/cla/gpio/mailbox_sanity/…) | ~10 | Often covered by local smoke under other names — **audit before port** |

Full Nightly name list: extract with

```bash
python3 - <<'PY'
import re, pathlib
p=pathlib.Path('/proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smc/dv/tb/tb_uvm/yaml/testlist_smc_chiplet.yaml')
t=p.read_text(); a=t.find('Main_SMC_Chiplet_Nightly_Regression:'); b=t.find('Main_SMC_BL0_Regression:', a)
for line in t[a:b].splitlines():
    if line.lstrip().startswith('#'): continue
    m=re.search(r'<<: \*([A-Za-z0-9_]+)', line)
    if m: print(m.group(1))
PY
```

---

## 5. Recommended local migration sequence

All writes land under `/proj_soc/user_dev/minshaoho/tryrun/oss2`. Commercial
sources are read-only under `/proj_soc/user_dev/minshaoho/tryrun/nonfree2`.

### 5.1 Path map (what moves where)

| Artifact | From (nonfree2) | To (local oss2) |
|----------|-----------------|-----------------|
| Test intent / catalog | `…/yaml/testlist_smc_chiplet.yaml` | `hw/sys/smc/dv/testlists/{deferred,i2c,axil,…}.toml` |
| Cocotb body | `…/cocotb_tests/<test>.py` | `hw/sys/smc/dv/cocotb/tests/<test>.py` (**rewrite**) |
| Sequence / helpers | commercial seq / env | `hw/sys/smc/dv/cocotb/seq_lib/` (+ env agent if needed) |
| FW scenario | `…/fw/tests/<name>/` | Prefer BFM rewrite; else `hw/sys/smc/dv/fw/tests/` via shared fw engine |
| Do **not** copy | Cadence VIP, UVM env, Jenkins yaml, Force/deposit, master_bfm | — |

### 5.2 Per-test rebuild checklist

1. Diff commercial intent vs local TB (`tb_top.sv`, VIP bindings, wrapper idle ports).
2. Choose vehicle: **cocotb BFM** (default) vs **local fw** (only if CPU/ROM is the DUT path under test).
3. Strip Force / Cadence / fake BFM; product-pin / OCAH VIP only.
4. Implement `tests/` + `seq_lib/`; SPDX headers; follow `ref_test_dev.md`.
5. Add to `deferred.toml` first if any blocker tag applies; else enroll leaf toml.
6. Keep commercial re-sim log under `$TMPDIR` for A/B; do not commit logs.
7. Confirm `results.xml` positive evidence (clean sim exit alone is not PASS).

### 5.3 Phase order

1. **Baseline** — Freeze local `smoke` PASS list under `$TMPDIR` (do not regress density).
2. **Inventory** — Add Tier A Nightly MISS names to `deferred.toml` with tags
   (`i2c`,`uart`,`fabric`,`depth`,`needs_*`).
3. **Pilot rebuild** — Implement 2–3 Tier A tests; Verilator green + honest checkers.
4. **Enroll** — Move pilots into `i2c.toml` / fabric-related leaf / optional smoke
   only if density gate intentionally expands.
5. **Tier C** — Cool-reset / boot-stall / CPU traffic after pin readiness.
6. **Tier D** — eFuse depth + collapsed reg-boundary; PLL/PVT stay deferred until real macros.
7. **Do not** enroll BL0/OCCP or Cadence I3C into reportable PASS.

### Local commands (oss2 destination)

```bash
cd /proj_soc/user_dev/minshaoho/tryrun/oss2
cd "$(pwd -P)"
source nonfree/setup_env.sh   # if companion present
export TMPDIR="${TMPDIR:?set TMPDIR to large scratch}"
mkdir -p "$TMPDIR"
module unload verilator; module load verilator/5.050 gcc/13.2.1

python3 tools/dv/run_dv.py --dut smc --doctor
python3 tools/dv/run_dv.py --dut smc --items smoke --tool verilator --regress
python3 tools/dv/run_dv.py --dut smc --items <new_test> --tool verilator --seed 1
```

### Commercial reference re-sim (local nonfree2)

```bash
cd /proj_soc/user_dev/minshaoho/tryrun/nonfree2/hw/sys/smc/dv/tb/tb_uvm
ttem --config ../../ yaml/testlist_smc_chiplet.yaml <TEST> \
  --stack sim --no-lsf --seed=1 -c compile_smc_chiplet
```

---

## 6. Success criteria

| Gate | Definition |
|------|------------|
| Inventory complete | Tier A Nightly MISS names present in local `deferred.toml` with tags |
| Pilot complete | ≥2 Tier A rebuilds LIVE, Verilator PASS, no Force/Cadence-only, enrolled under feature toml |
| Density preserved | Existing local `smoke` remains green (or documented intentional growth) |
| Policy clean | No new fake BFM / placeholder PLL-PVT / TB-glue / `allow_timeout` without rationale |
| Rename ledger | Every LIVE-rename pair recorded (this doc §4.1) so Nightly diffs stay auditable |

---

## 7. Revision

| Date | Change |
|------|--------|
| 2026-08-19 | Initial local port plan: nonfree2 Nightly (126) vs local oss2 enrolled/deferred; rebuild tiers A–D |
| 2026-08-19 | Tier A inventory in `deferred.toml` (`deferred_nightly_tier_a`); fabric error ≈ local `smc_output_fabric_slverr_inject_test`; TB `+smc_i2c_shared_bus`; pilot `smc_i2c_p0_rdwr_test` BFM enrolled under `i2c.toml` (not smoke) |
| 2026-08-19 | Pilot `smc_i2c_p0_nack_test` BFM (allow-path + `SmcI2cNackSlave` TC1/TC2) enrolled under `i2c.toml`; Verilator PASS |
| 2026-08-19 | TB `+smc_i2c_shared_bus` covers I2C0/1/2; pilots `smc_i2c_p0_multictrl_test`, `smc_i2c_p0_fifo_test` enrolled |
| 2026-08-20 | I2C P0 matrix complete under `i2c.toml`: `timeout` (MODE=0 stretch), `stretch` (TX_PENDING), `cfifo` (FMT thresh), `conti` (alt WR/RD); `nack_tc1/tc2` remain inventory aliases of combined nack body |
| 2026-08-20 | UART depth pilot `smc_uart_fifo_basic_trigger_reset_test` LIVE in `uart.toml` (MCR.LOOP FCR trigger 1B/4B + RX/TX FIFO reset); Verilator PASS |
| 2026-08-20 | UART `smc_uart_irq_sources_priority_test` LIVE (IER gating / natural clears / ITR priority); Verilator PASS |
| 2026-08-20 | UART `smc_uart_error_conditions_test` LIVE (PE via `+smc_uart_cross_3to0`, OE/BI loopback); TB UART3→UART0 RX short; Verilator PASS |
| 2026-08-20 | UART `smc_uart_baud_word_parity_format_test` LIVE (32 MCR.LOOP divisor×frame combos); Verilator PASS |
| 2026-08-20 | UART Tier A depth closed in `uart.toml`: extremes (SCR/idle), sanity (0↔3/1↔2 via `+smc_uart_cross_3to0`); `engine_sanity` deferred as covered_by LIVE |
| 2026-08-20 | **SMC Nightly Tier A depth closed** — I2C/SMBus/UART/fabric LIVE or `covered_by_live`; remaining deferred = product/policy blockers only (`rtl_placeholder`, `needs_i3c_dat_dct`, `fake_bfm`, `tb_glue`, `needs_dtp_csr_sub`) |
| 2026-08-20 | Tier C BFM rebuilds: `smc_hang_detector_sanity_test` (irq_test, no FW); `smc_gpio_p0_int_test` (edge IRQ); `smc_gpio_p0_mux_test` (interface_enable vs lsio_select); `smc_gpio_boot_stall_test` + `smc_jtag_boot_stall_sanity_test` (pad 57 sticky / JTAG ovrd); `smc_spm_mem_boundary_test` (SPM edges). Real hang-stall + cool-reset-from-{pcie,bmc} + CPU ext AXI still MISS |
| 2026-08-20 | Implementable Nightly remainder closed: `smc_mixed_boot_stall_test` (val=1 lockout); `smc_reset_unit_sanity_test` (`tb_sep_wdt_reset_n`); `smc_mutex_semaphore_test` (MUTEX[0] take/release); `smc_gpio_filter_access_sep_test` (ACCESS_FILTER AxPROT). Remaining Nightly names catalogued in `deferred.toml` (`covered_by_live` / `needs_*` / `no_force` / `rtl_placeholder`). |
| 2026-08-21 | Honest follow-on: `smc_efuse_locked_access_interrupt_test` LIVE (`tb_efuse_locked_access_irq` bit 28; CHIPLET_ID unlock-write silent / write-lock pulse / read-lock `0xBADCAB1E`). `smc_ndm_reset_test` LIVE (request pin → REQUEST/IRQ[11] → PROCESS CSR → process_o, 4 clusters). Remaining = cool-reset sources / ext AXI / hang timeout / xtrigger / PLL / FW. |
| 2026-08-21 | `smc_efuse_boundary_signals_test` LIVE (`+smc_hold_ext_boot`: sense completes while delayed `tb_fuse_reset_n` stays 0 past the 16-stage pipe; MAP LOCKS readable; release raises fuse_reset_n). `smc_cpu_reset_source_test` LIVE (SW `RESET_CTRL.core0_reset_n` → `RESET_TIMEOUT.reset_applied`; no Force `drained_i`; wrapper `isolate_req_o[31:0]` is FLR/cool, not claimed). |
| 2026-08-21 | `smc_efuse_read_program_timeout_test` LIVE (`timeout_enable\|0` aborts PROGRAM/READ before shim APB completes; default timeout recovers OTP bit0). `smc_reference_counter_test` LIVE (CPU_CTRL `REFERENCE_COUNTER` advances on `clk_ref_i`; not OCTS). |
| 2026-08-21 | `smc_temp_interrupt_test` LIVE (`temp_interrupt_i` → `peripheral_interrupts[27]` 0→1→0; analog PVT stays `rtl_placeholder`). `smc_ext_interrupts_pin_test` LIVE (`ext_interrupts_i[0]` through `prim_sync3`; unique vs GPIO `smc_external_interrupts_test`). |
| 2026-08-21 | `smc_cool_reset_from_pcie_test` LIVE (product `cfg_flr_pf_active_i`, not `rst_cool_ni` / `smc_flr_sanity` proxy: zero-counter isolate CSR + no cool; programmed delay/hold `rst_cool_no` 1→0→1; SMCEN gates `isolate_req_o`). BMC / primary-chiplet cool sources still MISS. Remaining = ext AXI / hang stall / xtrigger Force pads / pre-sense Force / PLL analog / FW. |
| 2026-08-21 | `smc_captured_straps_test` LIVE (`captured_straps_i` → `STRAPS_LO/HI`; unique vs GPIO `smc_gpio_strap_sanity_test`). `smc_ss_reset_complete_test` LIVE (`ss_reset_complete_i` bits 0/31 through `prim_sync3` + SW `SS_WARM_RESET_N` SS0 → `ss_reset_ctrl_o[0].warm_reset_n`; not FW handshake). Remaining = ext AXI / hang stall / xtrigger Force pads / JTAG reset_ctrl struct / BMC Force cool / PLL analog / FW. |
| 2026-08-21 | `smc_jtag_reset_ctrl_test` LIVE (packed `jtag_reset_ctrl_i`: cool ovrd drops `rst_cool_no` with `rst_cool_ni=1`/`cfg_flr=0`; SS0 warm ovrd drops pin while `SS_WARM_RESET_N` CSR stays all-1). Unique vs boot-stall JTAG, `smc_jtag_reset_proxy_test` (`rst_cool_ni`), FLR, and SW SS0. Remaining = ext AXI / hang stall / xtrigger Force pads / BMC Force cool / PLL analog / FW. |
| 2026-08-22 | Review: hang real stall = implement; FLR×cold overlap = new intent; `sep_security_disable_i` stays `no_force`. `smc_hang_detector_timeout_test` LIVE (SEP outstanding via `tb_sep_axi_r_hold`; not `irq_test`). `smc_cool_reset_x_cold_reset_test` LIVE (FLR held then `rst_cold_ni`; cold wins isolate/`rst_cool_no`; `rst_cool_ni` stays 1). BMC cool / cool×cool / `sep_security_disable` remain deferred. |
| 2026-08-22 | Implementable remainder: `smc_hang_detector_sys_timeout_test` LIVE (SYS_IN `tb_sys_axi_r_hold`; unique vs SEP timeout). `smc_dfx_status_abort_test` LIVE (`mem_repair_abort_i` / `mbist_abort_i` → `STATUS_SMU` sticky; unique vs DEBUG_CTRL reset reads). Remaining = BMC Force / ext AXI / xtrigger pads+FW / pre-sense Force / PLL analog / FW / DATA hang (needs DMA stall). |
| 2026-08-22 | `smc_hang_detector_data_timeout_test` LIVE (DATA_ACCEL via DMA + `tb_output_axi_resp_hold` on SYS_OUT R/B; unique vs SEP/SYS stall and `irq_test`). Remaining unique-pin set closed; leftover = BMC Force / ext AXI / xtrigger+CLA / pre-sense Force / PLL analog / FW. |

