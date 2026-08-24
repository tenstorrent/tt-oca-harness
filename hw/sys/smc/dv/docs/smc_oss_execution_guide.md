<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS Execution Guide

| Field | Value |
|-------|-------|
| Scope | Running the SMC OSS PyUVM-on-cocotb flow |
| Related | `SMC_VPLAN.adoc` (testplan), `ref_test_dev.md` (test development) |

`ref_test_dev.md` describes how tests are structured; `SMC_VPLAN.adoc` says what
each test verifies; this document says how to run the suite.

---

## 1. Environment Setup

`tools/dv/run_dv.py` bootstraps its own Python environment: it locates the
repository root, re-executes inside the locked uv-managed environment
(root `uv.lock`, dependency group `dv`), and puts the generated namespace
bridge on `PYTHONPATH`. There is nothing to source.

```bash
python3 tools/dv/run_dv.py --list          # confirm the DUT resolves
python3 tools/dv/run_dv.py --doctor --dut smc   # confirm simulators/licenses
```

Set `OCAH_DV_SKIP_UV=1` only when running inside a pre-provisioned environment
that already supplies the `dv` group.

Simulators are not provisioned by the repo. Put `verilator`, `xrun`, or `vcs` on
`PATH` yourself, with whatever license configuration your site requires, then use
`--doctor` to confirm what is visible.

### Python VIP dependencies

`hw/common/dv/pyproject.toml` declares the cocotb extensions the SMC VIPs need:

| Package | Backs |
|---------|-------|
| `cocotbext-axi` | SEP_IN / SYS_IN / JTAG AXI masters and monitors |
| `cocotbext-jtag` | `SmcJtagTap` CPU TAP driver |
| `cocotbext-i2c` | `SmcI2cMasterVip` / `SmcI2cEepromSlave` / `SmcI2cBusMonitor` |

Two extensions are **not** declared and degrade rather than hard-fail:

- `cocotbext-i3c` — `smc_i3c_vip_utils` catches the import error and records a
  diagnostic, so I3C tests fall back to line-level checks. Upstream ships it as a
  bundled submodule rather than a PyPI release, which is why it is not pinned.
- `cocotbext-uart` — needed by `SmcUartVip`; shared uv ownership is still
  deferred, so `smc_uart_loopback_test` cannot reach its byte-level proof.

---

## 2. Running Tests

### Full smoke

```bash
python3 tools/dv/run_dv.py --dut smc --tag smoke --tool xcelium
python3 tools/dv/run_dv.py --dut smc --tag smoke --tool verilator
```

Reference timings: Xcelium ~80 s incremental / ~430 s with `--rebuild`;
Verilator ~150 s incremental, and a cold `--rebuild` can exceed an hour on a
loaded host.

### Common flags

| Purpose | Flag |
|---------|------|
| Single test | `--items smc_cold_reset_test` |
| Feature subset | `--tag reset` / `axil` / `clock` / `i2c` / `irq` / `gpio` / `combined` / `batch_b` / `batch_c` / `batch_d` / `project_p0` / `mailbox_depth` |
| Multi-seed | `--seed N` (exported as `RANDOM_SEED` → `randomize_timing(seed)`) |
| Force clean rebuild | `--rebuild` |
| List tests / DUTs | `--list` (combine with `--dut smc` for SMC details) |
| Validate configs | `--validate-configs` |
| Dry-run | `--dry-run` |
| Coverage | `--cov` |
| Waves | `--waves [fst\|vcd]` |

### Testlist layout

```
hw/sys/smc/dv/testlists/
├── all.toml            # aggregator (includes = [...]) + smoke / pyuvm groups
├── reset.toml          # reset family
├── i2c.toml
├── clock.toml
├── irq.toml
├── gpio.toml
├── axil.toml
├── combined.toml       # combined / canonical observer tests
├── batch_b.toml        # real SEP_IN AXI CSR tests + AXI timeout/mailbox depth
├── batch_c.toml        # active I2C/iJTAG CSR prechecks + I3C CSR smoke
├── batch_d.toml        # FLR + TOP-20 CSR/precheck representatives
├── vplan_triplets.toml # 16 functional modules x 3 tests
├── p1_coverage_gap*.toml  # coverage-gap depth rounds
└── wrapper.toml        # deferred smc_wrapper catalog
```

`--tag smoke` and `--tag pyuvm` resolve through `all.toml` groups. Treat this as
the broad debug regression, not the coverage-minimal canonical set.

`--tag project_p0` matches the 14 SMC P0 testcase names of the P0 slate (see
`SMC_VPLAN.adoc`, SMC P0 Verification Test Cases). Four names are compatibility
wrappers over stronger local sequences: `smc_mailbox_idle_test`,
`smc_input_fabric_axi_wr_rd_test`, `smc_avsbus_sanity_test`, and
`smc_dbs_idle_test`.

`--tag mailbox_depth` is a depth target for mailbox write/read data and expected
error responses. It sits intentionally outside the canonical TOP-20 set so
canonical CI does not grow by duplicating mailbox breadth.

### Migration depth tags

The OSS suite carries representative tests migrated from a larger pre-existing
UVM environment, at **up to three representative tests per functional module**,
chosen for coverage density. New migrated tests should normally land in a depth
tag first:

| Depth tag | Purpose | First candidates |
|-----------|---------|------------------|
| `depth_reg` | Register default, boundary, retained/non-retained behavior | `smc_register_boundary_depth_test`, deeper `smc_default_reg_rd_test` |
| `depth_fabric` | Local fabric CSR ranges and remap/filter programming | `smc_local_fabric_csr_depth_test`, deeper `smc_output_filter_remap_security_test` |
| `mailbox_depth` | Mailbox data FIFO and expected error responses | `smc_mailbox_data_error_test` |
| `depth_efuse` | eFuse/OTP clock and permission/boundary CSR behavior | `smc_efuse_otp_clock_config_depth_test` |
| `depth_uart_log` | UART/SPI/log-engine register and error-boundary coverage | `smc_uart_log_engine_reg_rw_test` |

Do not add depth tests to `canonical_top20` just because they pass. Canonical
groups stay coverage-minimal; a depth test enters canonical only if it replaces
an older representative with strictly better coverage.

### Canonical planning tiers

The SMC plan follows the SEP OSS VPLAN structure: define a coverage universe,
choose the fewest high-density tests, and track the infrastructure each selected
test needs. The canonical set is cumulative:

| Tier | Goal |
|------|------|
| `TOP-6` | minimum CI smoke with real stimulus |
| `TOP-10` | high-value functional breadth |
| `TOP-20` | minimal full-breadth target |

Do not add a test to a `canonical_top*` group until it has active stimulus and at
least one Verilator PASS. Keep weak SAMPLE-only variants under the broad
`smoke`/feature groups for debug.

### Fast real-AXI loop

After the one-time Verilator model build for the `tb_top` AXI bridge, Python-only
edits to sequences, scoreboards, or testlists should use `--stage sim`:

```bash
python3 tools/dv/run_dv.py --dut smc --tag canonical_top6  --tool verilator --stage sim
python3 tools/dv/run_dv.py --dut smc --tag canonical_top20 --tool verilator --stage sim
python3 tools/dv/run_dv.py --dut smc --tag project_p0      --tool verilator --stage sim
python3 tools/dv/run_dv.py --dut smc --tag mailbox_depth   --tool verilator --stage sim
```

Use `--rebuild` only after changing SystemVerilog TB/stubs, Bender/filelist
inputs, RTL, or generated hardware files.

### Public bus/register helper

The public access path selected for the SMC bus helper is the SEP_IN AXI
ingress:

```text
smc_output_filter_remap_security_test
  -> SmcCsrSeq / SmcSysAxiItem / SmcSysAxiDriver
  -> ocah_axi_vip.OcahAxiMasterAgent
  -> tb_top.sv s_axi_*
  -> smc.sep_axi_in_req_i
  -> SMC filter/remap CSRs
```

This is active stimulus, not an observation-only proxy. The scenario programs
the filter/remap CSRs through SEP_IN, then uses the public JTAG AXI injection
port to prove an allowed write/read with golden-memory comparison and a blocked
write that returns exact DECERR without corrupting the retained data. The
flattened public buses are AXI4 with a 56-bit address and 64-bit data path; the
local helper supports 1-, 2-, 4-, and 8-byte single-beat CSR accesses.

`SmcSysAxiDriver` bounds every access with `SmcEnvCfg.axi_timeout_ns` (50,000 ns
by default). A normal access fails on timeout or a non-OKAY response. A negative
test may explicitly allow an error response, but an expected SLVERR/DECERR must
complete; `expect_error` rejects both an incorrect OKAY response and a timeout.

The Python attribute names are historical: `env.sys_axi_agent` drives the
`s_axi_*` SEP_IN bridge above. The separate `env.sys_in_axi_agent` drives
`sys_axi_*` into `sys_axi_in_req_i`; this scenario does not exercise that SYS_IN
path. Its direct `jtag_axi_*` injection is an AXI fabric path, not proof of
serial JTAG-to-AXI conversion.

The AXI protocol engine remains shared in `ocah_axi_vip`. The
`SmcSysAxiDriver` and `SmcCsrSeq` adapters stay DUT-local because they carry
PyUVM sequencing, SMC address/catalog policy, SMC error signatures, and
SMC-specific register-to-pin helpers. Promote a register helper to shared DV
only after a second DUT needs the same protocol-neutral API with those policies
removed.

Focused validation:

```bash
python3 tools/dv/run_dv.py --dut smc \
  --items smc_output_filter_remap_security_test --tool verilator --seed 1
```

---

## 3. Functional Coverage Pipeline

Alongside simulator-side coverage, the scoreboard emits **functional event
records** that can be aggregated across runs by a small Python script.

### How it works

`hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` maintains event bins and emits a
`FUNC_COV_VALUE bin=<name> value=<...>` log line on every observation:

| Bin | Captures |
|-----|----------|
| `reset_op` | Each `SmcResetOp` enum hit (SAMPLE, COLD_RST_LO/HI, …) |
| `reset_state` | 4-tuple of post-reset stable signals (and mid-glitch via RAW_SAMPLE) |
| `i2c_state` | (resolvable, cg_en) |
| `clk_bucket` | (ref_edges // 50, smc_edges // 50, periph_edges // 50) |
| `irq_state` | (sync_irq, gpio_irq_any, uart_irq_any) |
| `gpio_state` | (core2pad_any, core2pad_en_any, pad2core_en_any) |
| `axil_master` | (any_master_active,) |
| `protocol_vip` | `SmcProtocolVipItem` kind/test/proxy triple |

Multi-seed runs widen `clk_bucket`, because `randomize_timing(seed)` varies
clock periods and `smc_clk_multi_window_test_seq` picks random window sizes per
seed. The observation-only bins (`axil_master`, `gpio_state`, `i2c_state`,
`irq_state`) grow only with active-driver stimulus.

### Aggregator script

Scans one or more run dirs and reports unique events per bin plus the union
across runs.

```python
#!/usr/bin/env python3
"""Aggregate SMC OSS functional coverage events across run dirs.

Usage:
    python3 aggregate_cov.py <run_dir> [<run_dir> ...]
    # Lists per-run + UNION counts of FUNC_COV_VALUE events.
"""
import sys
import re
import glob
from collections import defaultdict


def collect(run_dir: str) -> dict[str, set[str]]:
    bins: dict[str, set[str]] = defaultdict(set)
    for log in glob.glob(f"{run_dir}/**/*.log", recursive=True):
        try:
            with open(log) as f:
                for line in f:
                    m = re.search(r"FUNC_COV_VALUE bin=(\S+) value=(.+)$", line.rstrip())
                    if m:
                        bins[m.group(1)].add(m.group(2))
        except OSError:
            pass
    return bins


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    union: dict[str, set[str]] = defaultdict(set)
    for run_dir in argv[1:]:
        bins = collect(run_dir)
        print(f"=== {run_dir} ===")
        for b in sorted(bins):
            print(f"  {b:14s} unique={len(bins[b]):3d}")
            union[b] |= bins[b]
        print(f"  TOTAL={sum(len(v) for v in bins.values())}")
        print()

    if len(argv) > 2:
        print("=== UNION ===")
        for b in sorted(union):
            print(f"  {b:14s} unique={len(union[b]):3d}  sample={sorted(union[b])[:4]}")
        print(f"  TOTAL={sum(len(v) for v in union.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

---

## 4. Simulator-Side Coverage

With `--cov` on Xcelium the runner instructs `xrun` to emit UCIS coverage data
per test under `<run_dir>/<test>/coverage/scope/`:

```
coverage/scope/icc_<hash>.ucm        # design model
coverage/scope/test/icc_<hash>.ucd   # per-test data
```

The `cov_merge` / `cov_report` stages call Cadence IMC. Where IMC is not
installed, both stages report ERROR while the per-test `.ucd` files remain on
disk for offline merge.

The runner passes `-covworkdir <abs path>` and `-covoverwrite` to `xrun -R`.
Without those, the sim stage writes to a `./cov_work` relative to the cocotb
test cwd and hits `*F,C58EXS` ("database already exists") on the second run.

---

## 5. Build Caching & Performance Notes

- **Incremental build** is the default. Pass `--rebuild` only when changing the
  Verilator stubs, `tb_top`, or RTL.
- For Python-only test, sequence, scoreboard, or testlist edits, reuse the
  existing model with `--stage sim`; that keeps real-AXI regression runs around
  30 s instead of triggering a multi-hour rebuild.
- A **first Verilator build** with `--rebuild` takes ~10 min on an idle host and
  can exceed 90 min on a heavily loaded one. Raising make parallelism helps a
  lot (`MAKEFLAGS=-j32`).
- **Xcelium build** is faster: ~25 s incremental, ~7 min `--rebuild`.
- Both simulators share bender filelist generation; concurrent `--rebuild` runs
  **race** and can fail. Run them serially.

---

## 6. Quick Reference

```bash
# Validate sim_cfg + list testlists
python3 tools/dv/run_dv.py --validate-configs
python3 tools/dv/run_dv.py --dut smc --list

# Single test, either simulator
python3 tools/dv/run_dv.py --dut smc --items smc_cold_reset_test --tool xcelium
python3 tools/dv/run_dv.py --dut smc --items smc_cold_reset_test --tool verilator

# Feature subset / full smoke
python3 tools/dv/run_dv.py --dut smc --tag reset --tool xcelium
python3 tools/dv/run_dv.py --dut smc --tag smoke --tool verilator

# Canonical tiers (sim-only after the one-time model build)
python3 tools/dv/run_dv.py --dut smc --tag canonical_top6  --tool verilator --stage sim
python3 tools/dv/run_dv.py --dut smc --tag canonical_top20 --tool verilator --stage sim

# P0 slate names (14 tests) and category triplets
python3 tools/dv/run_dv.py --dut smc --tag project_p0 --tool verilator --stage sim
python3 tools/dv/run_dv.py --dut smc --items project_p0_triplets --tool verilator --stage sim

# VPLAN migration triplets (16 functional modules x 3 tests) and gap slate
python3 tools/dv/run_dv.py --dut smc --items vplan_triplets --tool verilator --stage sim
python3 tools/dv/run_dv.py --dut smc --items vplan_gaps --tool verilator --stage sim

# Static checks before running any sim
python3 -m py_compile \
  hw/sys/smc/dv/cocotb/seq_lib/<changed_seq>.py \
  hw/sys/smc/dv/cocotb/tests/<changed_test>.py
python3 tools/dv/run_dv.py --validate-configs
```

---

## 7. Protocol VIP Evidence

SMC follows the DTP/SEP PyUVM VIP pattern for runnable protocol evidence:

- `SmcProtocolVipItem` describes high-level protocol intent.
- `SmcProtocolVipAgent` completes the item and broadcasts it on an analysis port.
- `SmcScoreboard` checks the item and emits `FUNC_COV_VALUE bin=protocol_vip`.
- `smc_base_test` records protocol VIP evidence automatically for VPLAN/proxy
  tests that still use direct SEP_IN AXI CSR stimulus.
- `SmcScoreboard._check_protocol_vip` additionally asserts `details != ""` and the
  invariant `timeouts <= csr_accesses`, so a mis-wired scenario cannot log
  empty or inconsistent protocol-VIP coverage. `SmcProtocolVipItem.passed` is a
  scenario-completion flag; the real protocol checks are the in-sequence asserts.

### Non-proxy protocol evidence, by area

Each group below carries `SmcProtocolVipItem(proxy=False)` evidence rather than
a CSR-only proxy:

| Area | Tests | What makes it non-proxy |
|------|-------|-------------------------|
| Output fabric | `smc_output_fabric_wr_rd_responder_test`, `smc_input_output_fabric_wr_rd_test`, `smc_output_filter_remap_security_test` | `tb_top` exposes flattened `s_axi_*` / `jtag_axi_*` inputs; SEP_IN programs the fabric and JTAG AXI traffic drives a DV-only output-fabric responder. Checks write/read completion, readback data, blocked-write `DECERR`, and `tb_output_axi_*` counters |
| I2C | `smc_i2c_master_target_test`, `smc_i2c_p1_rdwr_protocol_test`, `smc_i2c_error_fifo_depth_test` | I2C0 resolved SCL/SDA exposed; release/pull-low behavior checked through the DUT override path |
| I3C | `smc_i3c_to_fabric_test`, `smc_i3c_oca_write_read_sanity_test`, `smc_i3c_ibi_ccc_depth_test` | I3C0 resolved SCL/SDA exposed; external pull-low/release verified |
| CPU JTAG | `smc_ijtag_basic_test`, `smc_chiplet_reg_jtag_test`, `smc_efuse_jtag_lc_negative_test`, `smc_jtag_dft_timeout_proxy_test`, `smc_jtag_reset_proxy_test` | TCK/TMS/TDI/reset/TDO exposed with fixed ID fields; resolvable TDO required |
| Mailbox | `smc_mailbox_irq_test`, `smc_mailbox_data_error_test`, `smc_mailbox_event_irq_test` | DV-only `tb_sep_mailbox_interrupts` source + `tb_mailbox_irq_any` checker prove SEP mailbox interrupt bits reach the SMC peripheral vector |
| GPIO / external IRQ | `smc_gpio_irq_active_test`, `smc_gpio_strap_sanity_test`, `smc_external_interrupts_test` | DV-only `tb_gpio_ext_drive_en/value`; GPIO0 as active-low input IRQ, checker verifies deassert/assert/deassert |
| Sideband (AVSBus/OCTS) | `smc_avsbus_sanity_test`, `smc_avsbus_status_depth_test`, `smc_avsbus_clock_config_proxy_test`, `octs_sanity_test` | `tb_avsbus_irq`, `tb_telemetry_irq_any`, `tb_avsbus_cur_state_debug` bounded observability alongside real CSR decode/timeout |
| CPU / OCCP | `smc_cpu_sanity_test`, `smc_cpu_ctrl_scratch_window_test`, `smc_cpu_ctrl_map_depth_test`, `smc_cpu_to_sep_axi_test`, `smc_occp_sanity_secure_error_test` | SEP_IN AXI master-BFM substitutes for firmware traffic; CPU-control map + scratch write/read/restore + reset/powergood checks |
| eFuse / OTP | `smc_efuse_permission_boundary_test`, `smc_efuse_chip_config_read_test`, `smc_efuse_otp_clock_config_depth_test`, `smc_efuse_otp_clock_test` | eFuse-derived chip-config surface for version/LC/RAS semantics + OTP clock-gate restore + eFuse-bank AXI-Lite idle checker |
| ECC / DFD / DBS | `smc_dfd_sanity_test`, `smc_dbs_idle_test`, `smc_ecc_dfd_dbs_sanity_test`, `smc_cpu_ecc_lint_pint_depth_test` | RAS/debug CSR checks plus bounded fault observability on sync IRQ, downstream AXI-Lite idle, and reset |
| CSR catalog | `smc_default_reg_rd_test`, `smc_register_boundary_depth_test`, `smc_register_sanity_test` | `smc_csr_field_catalog.py` classifies restore-safe RW scratch, RO static chip-config/eFuse-derived, and RO status fields; tests validate fields against the catalog before read/write/restore |

### Common VIP reuse layer

The SMC environment keeps DUT-specific adapters around shared protocol engines.
The AXI adapter binds flattened SMC ports directly; three additional adapters
under `seq_lib/` target the `tb_top.sv` split-port `ext_low` open-drain
convention:

| Wrapper | Underlying VIP | Adapter reason |
|---------|----------------|----------------|
| `env.smc_sys_axi_agent.SmcSysAxiDriver` | `ocah_axi_vip.OcahAxiMasterAgent` | Binds `s_axi_*`, `sys_axi_*`, or `jtag_axi_*` flattened ports and maps the shared AXI completion into SMC PyUVM items, timeout/error policy, scoreboard, and CSR helpers |
| `smc_jtag_protocol_vip.SmcJtagTap` | `cocotbext.jtag` (`JTAGBus` + `JTAGDriver`) | `ocah_jtag_vip` depends on an uninstalled `jtag_vip` package; `cocotbext.jtag` binds cleanly to the public `tb_cpu_jtag_{tck,tms,tdi,tdo,reset}` pins. `SmcCpuTapDevice(idcode=0x10CA0555, ir_len=5)` mirrors the JEP106 straps hard-coded in `tb_top.sv` |
| `smc_i2c_protocol_vip.SmcI2cEepromSlave` / `SmcI2cBusMonitor` | `cocotbext.i2c` (`I2cMemory` / `I2cDevice`) | `ocah_i2c_vip.OcahI2cMaster` uses an older single-signal 2-arg form that cannot bind to the split-port TB. `cocotbext.i2c` exposes 4-arg `sda/sda_o/scl/scl_o`; an `_InvertedPolarityMixin` overrides `_set_sda/_set_scl` because `sda_o=0` (VIP: pull low) maps to `tb_i2c0_sda_ext_low=1` (TB: pull low) |
| `smc_i3c_protocol_vip.SmcI3cSlaveVip` | `cocotbext_i3c.I3CTarget` | Upstream ships as a bundled submodule rather than a PyPI package, so the wrapper augments `sys.path` at import time and degrades gracefully when absent. Overrides the `sda`/`scl` property setters with the same polarity inversion |

`seq_lib/smc_jtag_vip_utils.check_cpu_jtag_pin_vip()` drives a full TRST pulse
plus TMS-1 navigation to TEST_LOGIC_RESET, captures IDCODE via `cocotbext.jtag`,
then loads BYPASS. All five JTAG tests route through this helper, so they pick up
changes automatically. The IDCODE check is a strict compare against the expected
value (`0x10CA0555`).

### Loopback checks

`SmcI2cMasterVip` (a `cocotbext.i2c.I2cMaster` subclass with the same polarity
flip and open-drain wired-AND set) and `SmcI3cControllerVip` (a
`cocotbext_i3c.I3cController` subclass with the shared polarity mixin) provide
directed byte-level traffic:

- `smc_i2c_master_target_test_seq` binds slave + master + monitor, issues
  `master.write(0x50, [offset=0x10, byte=0xAB])`, and asserts
  `slave.read_mem(0x10, 1) == 0xAB`. That is direct evidence a real
  START + ADDR(0x50) + DATA(0xAB) + STOP sequence traversed the `tb_i2c0_*` pins
  through the polarity + wired-AND adapter.
- `smc_i3c_to_fabric_test_seq` binds target + controller and issues
  `ctrl.i3c_write(addr=0x50, data=[0x5A])`; the target's
  `TARGET:::Performing write at 0, data: [90]` log line confirms the byte
  arrived. A T-bit ACK is not required for the proof, since a proper ACK needs
  prior DAA/SETDASA enrolment, which is out of scope.
- The directed I3C SDR write lives in
  `smc_i3c_vip_utils.i3c_directed_sdr_write_proof`, called from
  `check_i3c0_external_pull_low` (which every I3C test reaches) plus
  `smc_i3c_multi_controller_csr_test`.
- I2C at Standard mode (100 kHz) needs more than 15 min of Verilator wall-clock
  for a 3-byte transaction, so the byte transaction is **gated on
  `cocotb.SIM_NAME` and skipped under Verilator** (the wrapper bind and polarity
  adapter still run). Xcelium is the authoritative byte-level proof. The I3C
  loopback is fast enough to run unconditionally on both.

The `SmcI2cEepromSlave` slave-mode class is ready for real bus traffic. The
DUT-controller-driven byte sequence (programming the SMC I2C0 DesignWare
controller: `IC_CON` master mode, `IC_TAR`=0x50, `IC_ENABLE`=1, one
`IC_DATA_CMD` write byte) is not yet mapped in OSS scope; the OVRD-based line
check remains the pin-level regression until it is.

### Known pitfalls

Non-obvious failure modes that are easy to reintroduce:

- **Undriven `atop` X-propagation fires an SVA under Xcelium.** The `tb_top`
  request assigns must drive `.aw.atop = '0'` on `sep_axi_in_req`,
  `sys_axi_in_req`, and `jtag_axi_in_req`; otherwise X propagates into the
  outbound filter's `axi_err_slv` — instantiated with `.ATOPs(1'b0)` — whose
  `assume` property `slv_req_i.aw_valid |-> slv_req_i.aw.atop == '0`
  fatal-fires. Verilator hides it via `+define+DISABLE_ASSERT`. A one-time
  `--rebuild` is required after changing the drive set.
- **High-impedance CSR reads break cocotbext-axi.** A CSR read returning `z` on
  undriven fields raises `ValueError: Unresolvable bit in binary string: 'z'`.
  Verilator's X-resolve defaults hide it; Xcelium exposes it. Default
  `COCOTB_RESOLVE_X=ZEROS` so `int(rdata)` treats `z` as 0, or narrow register
  sweeps to registers with fully driven defaults.
- **cocotbext-i2c's constructor bypasses the polarity mixin.**
  `I2cDevice.__init__` calls `sda_o/scl_o.setimmediatevalue(1)` directly. Under
  the split-port polarity that pulls both bus lines low from t=0, breaking
  OVRD-release checks. Call `self.{sda,scl}_o.setimmediatevalue(0)` immediately
  after `super().__init__()`, as `SmcI3cSlaveVip` does.
- **`tb_top` pad lifts can destabilize the Verilator model.** Lifting the SPI
  Octal Flash pads and telemetry packed-array pads to `tb_top.sv` produces a
  `Vtop::eval()` SIGSEGV across the whole suite; a Verilator-safe pad-lift
  refactor is required before those pins can be exposed. Also note: a leftover
  trailing comma after removing port bindings is reported by the Verilator
  front-end as *Mixing positional and `.*`/named instantiation*.
- **The I3C target needs a settle window.** Insert a 1 us timer between
  slave/controller bind and the first `i3c_write` so the target `_run`
  coroutine reaches its edge-wait state; without it the first SDR frame can
  slip past target init.
- **Missing extensions look like test failures.** The JTAG tests hard-fail with
  `SmcJtagTapError: cocotbext-jtag is required`, and the I3C tests with
  `ImportError: No module named 'cocotbext_i3c'`, when the optional packages
  are not importable. Neither is an RTL or TB defect. Confirm the dependency
  surface (§1) before debugging a protocol test.
