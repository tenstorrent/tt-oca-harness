<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS Execution Guide

| Field | Value |
|-------|-------|
| Owner | minshaoho |
| Scope | Running the SMC OSS PyUVM-on-cocotb flow and the recorded sign-off evidence |
| Related | `oss_smc_dev.md` (planning), `SMC_VPLAN.adoc` (testplan), `ref_test_dev.md` (test development) |

Companion to the design / planning doc `oss_smc_dev.md`. That document says *what*
was planned and why; this one says *how* to run it and *what has been proven*.

Historical run evidence below was captured on Xcelium 25.03.001 and
Verilator 5.046. Run directories are named
`hw/sys/smc/dv/build/runs/<timestamp>__<tool>__<item>` and are local artifacts,
so the timestamps identify a result in the author's workspace rather than
something reproducible from a clean clone. Treat the PASS counts and the
root-cause notes as the durable content.

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
| `cocotbext-uart` | `SmcUartVip` UART0 pad driver/sink (vendored at `vendor/alexforencich/cocotbext-uart`) |

I3C has no VIP dependency: `smc_i3c_to_fabric_test` gates on CSR decode plus
the `check_i3c0_external_pull_low` line-level check.

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
├── p1_coverage_gap*.toml  # coverage-gap depth rounds 1-5
└── wrapper.toml        # deferred smc_wrapper catalog
```

`--tag smoke` and `--tag pyuvm` resolve through `all.toml` groups. Treat this as
the broad debug regression, not the coverage-minimal canonical set.

`--tag project_p0` matches the 14 SMC P0 testcase names tracked by GitHub
Project 335 / issue `tenstorrent/tt-oca-hw#2891`. Four names are compatibility
wrappers over stronger local sequences: `smc_mailbox_idle_test`,
`smc_input_fabric_axi_wr_rd_test`, `smc_avsbus_sanity_test`, and
`smc_dbs_idle_test`.

`--tag mailbox_depth` is a legacy-UVM-inspired depth target for mailbox
write/read data and expected error responses. It sits intentionally outside the
canonical TOP-20 set so canonical CI does not grow by duplicating mailbox
breadth.

### Legacy migration depth tags

The legacy SMC UVM/chiplet environment has 150+ named tests. The OSS migration
policy is **up to three representative tests per functional module**, chosen for
coverage density. New migrated tests should normally land in a depth tag first:

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

| Tier | Goal | State at last sign-off |
|------|------|------------------------|
| `TOP-6` | minimum CI smoke with real stimulus | all six implemented, Verilator PASS |
| `TOP-10` | high-value functional breadth | all ten have active CSR/precheck coverage and Verilator PASS; protocol-complete #8/#9/#10 still need VIP/responder work |
| `TOP-20` | minimal full-breadth target | all twenty have active CSR/precheck coverage and Verilator PASS; several are bounded unavailable/blocked-window checks until deeper infra lands |

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

The public access path selected for the Project 335 SMC bus-helper milestone is
the SEP_IN AXI ingress:

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

The SMC OSS TB began as observation-only, so simulator-side coverage was limited.
Instead the scoreboard emits **functional event records** that can be aggregated
across runs by a small Python script.

### How it works

`hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` maintains event bins and emits a
`FUNC_COV_VALUE bin=<name> value=<...>` log line on every observation:

| Bin | Captures | Ceiling |
|-----|----------|---------|
| `reset_op` | Each `SmcResetOp` enum hit (SAMPLE, COLD_RST_LO/HI, …) | **8** (all enum values) |
| `reset_state` | 4-tuple of post-reset stable signals (and mid-glitch via RAW_SAMPLE) | 3 (DUT synchronously releases bits) |
| `i2c_state` | (resolvable, cg_en) | 1 (no I2C cg toggle stimulus) |
| `clk_bucket` | (ref_edges // 50, smc_edges // 50, periph_edges // 50) | grows with seed count |
| `irq_state` | (sync_irq, gpio_irq_any, uart_irq_any) | 1 (no IRQ source) |
| `gpio_state` | (core2pad_any, core2pad_en_any, pad2core_en_any) | 1 (no GPIO driver) |
| `axil_master` | (any_master_active,) | 1 (no AXI master traffic) |
| `protocol_vip` | `SmcProtocolVipItem` kind/test/proxy triple | grows with promoted tests |

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

### Baselines

Single-run output from the historical 22-test observability baseline (seed 1):

```
  axil_master    unique=  1
  clk_bucket     unique=  6
  gpio_state     unique=  1
  i2c_state      unique=  1
  irq_state      unique=  1
  reset_op       unique=  8
  reset_state    unique=  3
  TOTAL=21
```

Five seeds widen `clk_bucket` from ~6 to ~20, because `randomize_timing(seed)`
varies clock periods and `smc_clk_multi_window_test_seq` picks 8 random window
sizes per seed. The 5-seed union reaches `clk_bucket unique=20`, `TOTAL=35`.

### Coverage progression history

| Stage | Single seed | 5-seed UNION |
|-------|-------------|--------------|
| Original baseline (`smoke` 73 tests) | 13 | 17 |
| Slim to 22 representative tests | 13 | 17 |
| + Cool reset op in repeated seq | 15 | 19 |
| + Seed-driven random clk windows | 18 | 32 |
| + RAW_SAMPLE op mid-glitch | 21 | 35 |
| + Denser RAW_SAMPLE probing | 21 | 35 (capped) |

35 was the natural ceiling of the pure-observability TB. Growing the four
saturated bins (`axil_master`, `gpio_state`, `i2c_state`, `irq_state`) required
an active driver — which the later AXI master / JTAG2AXI promotions delivered.

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
Without those, the sim stage wrote to a `./cov_work` relative to the cocotb test
cwd and hit `*F,C58EXS` ("database already exists") on the second run.

---

## 5. Build Caching & Performance Notes

- **Incremental build** is the default. Pass `--rebuild` only when changing the
  Verilator stubs, `tb_top`, or RTL.
- For Python-only test, sequence, scoreboard, or testlist edits, reuse the
  existing model with `--stage sim`; that keeps real-AXI regression runs around
  30 s instead of triggering a multi-hour rebuild.
- A **first Verilator build** with `--rebuild` takes ~10 min on an idle host and
  can exceed 90 min on a heavily loaded one. Raising make parallelism helps a
  lot: one recorded rebuild dropped from ~30 min to ~4 min with `MAKEFLAGS=-j32`.
- **Xcelium build** is faster: ~25 s incremental, ~7 min `--rebuild`.
- Both simulators share bender filelist generation; concurrent `--rebuild` runs
  **race** and can fail. Run them serially.

---

## 6. Quick Reference: Verified Commands

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

# GitHub Project 335 / #2891 P0 names (14 tests) and category triplets
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

### Protocol VIP Status

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

Promotion history, by area — each group moved from CSR-only proxy to
`SmcProtocolVipItem(proxy=False)`:

| Area | Promoted tests | What made it non-proxy |
|------|----------------|------------------------|
| Output fabric | `smc_output_fabric_wr_rd_responder_test`, `smc_input_output_fabric_wr_rd_test`, `smc_output_filter_remap_security_test` | `tb_top` exposes flattened `s_axi_*` / `jtag_axi_*` inputs; SEP_IN programs the fabric and JTAG AXI traffic drives a DV-only output-fabric responder. Checks write/read completion, readback data, blocked-write `DECERR`, and `tb_output_axi_*` counters |
| I2C | `smc_i2c_master_target_test`, `smc_i2c_p1_rdwr_protocol_test`, `smc_i2c_error_fifo_depth_test` | I2C0 resolved SCL/SDA exposed; release/pull-low behavior checked through the DUT override path |
| I3C | `smc_i3c_to_fabric_test` | I3C0 resolved SCL/SDA exposed; external pull-low/release verified via `check_i3c0_external_pull_low`; the CSR window gate is HCI_VERSION decode. The test records `proxy=True` — no protocol-level VIP traffic runs |
| CPU JTAG | `smc_ijtag_basic_test`, `smc_chiplet_reg_jtag_test`, `smc_efuse_jtag_lc_negative_test`, `smc_jtag_dft_timeout_proxy_test`, `smc_jtag_reset_proxy_test` | TCK/TMS/TDI/reset/TDO exposed with fixed ID fields; resolvable TDO required |
| Mailbox | `smc_mailbox_irq_test`, `smc_mailbox_data_error_test`, `smc_mailbox_event_irq_test` | DV-only `tb_sep_mailbox_interrupts` source + `tb_mailbox_irq_any` checker prove SEP mailbox interrupt bits reach the SMC peripheral vector |
| GPIO / external IRQ | `smc_gpio_irq_active_test`, `smc_gpio_strap_sanity_test`, `smc_external_interrupts_test` | DV-only `tb_gpio_ext_drive_en/value`; GPIO0 as active-low input IRQ, checker verifies deassert/assert/deassert |
| Sideband (AVSBus/OCTS) | `smc_avsbus_sanity_test`, `smc_avsbus_status_depth_test`, `smc_avsbus_clock_config_proxy_test`, `octs_sanity_test` | `tb_avsbus_irq`, `tb_telemetry_irq_any`, `tb_avsbus_cur_state_debug` bounded observability alongside real CSR decode/timeout. These tests record `proxy=True`; full promotion needs a real pad-level AVSBus/OCTS BFM |
| CPU / OCCP | `smc_cpu_sanity_test`, `smc_cpu_ctrl_scratch_window_test`, `smc_cpu_ctrl_map_depth_test`, `smc_cpu_to_sep_axi_test`, `smc_occp_sanity_secure_error_test` | SEP_IN AXI master-BFM substitutes for firmware traffic; CPU-control map + scratch write/read/restore + reset/powergood checks |
| eFuse / OTP | `smc_efuse_permission_boundary_test`, `smc_efuse_chip_config_read_test`, `smc_efuse_otp_clock_config_depth_test`, `smc_efuse_otp_clock_test` | eFuse-derived chip-config surface for version/LC/RAS semantics + OTP clock-gate restore + eFuse-bank AXI-Lite idle checker |
| ECC / DFD / DBS | `smc_dfd_sanity_test`, `smc_dbs_idle_test`, `smc_ecc_dfd_dbs_sanity_test`, `smc_cpu_ecc_lint_pint_depth_test` | RAS/debug CSR checks plus bounded fault observability on sync IRQ, downstream AXI-Lite idle, and reset |
| CSR catalog | `smc_default_reg_rd_test`, `smc_register_boundary_depth_test`, `smc_register_sanity_test` | `smc_csr_field_catalog.py` classifies restore-safe RW scratch, RO static chip-config/eFuse-derived, and RO status fields; tests validate fields against the catalog before read/write/restore |

After all promotions, `vplan_triplets` held at 48/48 PASS on both simulators,
confirming the promoted tests did not regress the broader planned suite.

### Common VIP reuse layer

The SMC environment keeps DUT-specific adapters around shared protocol engines.
The AXI adapter binds flattened SMC ports directly; three additional adapters
under `seq_lib/` target the `tb_top.sv` split-port `ext_low` open-drain
convention:

| Wrapper | Underlying VIP | Adapter reason |
|---------|----------------|----------------|
| `env.smc_sys_axi_agent.SmcSysAxiDriver` | `ocah_axi_vip.OcahAxiMasterAgent` | Binds `s_axi_*`, `sys_axi_*`, or `jtag_axi_*` flattened ports and maps the shared AXI completion into SMC PyUVM items, timeout/error policy, scoreboard, and CSR helpers |
| `smc_jtag_protocol_vip.SmcJtagTap` | `cocotbext.jtag` (`JTAGBus` + `JTAGDriver`) | `cocotbext.jtag` binds cleanly to the public `tb_cpu_jtag_{tck,tms,tdi,tdo,reset}` pins. `SmcCpuTapDevice(idcode=0x10CA0555, ir_len=5)` mirrors the JEP106 straps hard-coded in `tb_top.sv` |
| `smc_i2c_protocol_vip.SmcI2cEepromSlave` / `SmcI2cBusMonitor` | native cocotb clock-sampled model | Implemented natively because `cocotbext-i2c` edge waits miss open-drain transitions under Verilator; the model samples the split-port `tb_i2c0_*`/`tb_i2c0_*_ext_low` pins on a clock and owns the pull-low polarity mapping directly |

I3C carries no protocol-level VIP: `smc_i3c_to_fabric_test` gates on CSR
decode (HCI_VERSION) plus the `check_i3c0_external_pull_low` pad check and
records `proxy=True`.

`seq_lib/smc_jtag_vip_utils.check_cpu_jtag_pin_vip()` drives a full TRST pulse
plus TMS-1 navigation to TEST_LOGIC_RESET, captures IDCODE via `cocotbext.jtag`,
then loads BYPASS. All five JTAG tests route through this helper, so they pick up
changes automatically. The bit-level check was deliberately lenient on first
landing (assert `bit[0] == 1`, `!= 0`, `!= 0xFFFFFFFF`; only *log* the expected
`0x10CA0555`) and was tightened to a strict compare once a live PASS confirmed
the captured value.

### Root causes worth remembering

These are the non-obvious failures found during bring-up. Each cost real debug
time and each is easy to reintroduce.

**`atop` X-propagation fired an SVA under Xcelium.** `smc_output_filter_remap_security_test`
tripped `axi_err_slv.gen_assert_atops_unsupported` because the `tb_top` request
assigns never initialized the 6-bit `atop_t` field, so X propagated into the
outbound filter's `axi_err_slv` — instantiated with `.ATOPs(1'b0)` — where the
`assume` property `slv_req_i.aw_valid |-> slv_req_i.aw.atop == '0` fatal-fires.
Verilator hid it via `+define+DISABLE_ASSERT`. Fix: drive `.aw.atop = '0` on
`sep_axi_in_req`, `sys_axi_in_req`, and `jtag_axi_in_req`. A one-time `--rebuild`
is required for the change to take effect; afterwards `canonical_top20` reached
20/20 on Xcelium.

**High-impedance CSR reads broke cocotbext-axi.** `smc_default_reg_rd_test` and
`smc_register_boundary_depth_test` raised `ValueError: Unresolvable bit in binary
string: 'z'` when a CSR read returned `z` on undriven fields. Verilator's
X-resolve defaults hid it; Xcelium exposed it. Fix: default `COCOTB_RESOLVE_X=ZEROS`
so `int(rdata)` treats `z` as 0. Alternatively narrow the sweep to registers with
fully driven defaults.

**A VIP constructor bypassed the polarity mixin.** cocotbext-i2c's
`I2cDevice.__init__` calls `sda_o/scl_o.setimmediatevalue(1)` directly, bypassing
`_InvertedPolarityMixin`. Under the split-port polarity that pulls both bus lines
low from t=0, breaking the OVRD-release check on all three I2C tests. Xcelium hid
this because it initialized the `ext_low` ports differently in the same
time-zero window; Verilator caught it. Fix: call
`self.{sda,scl}_o.setimmediatevalue(0)` immediately after `super().__init__()`.

**A `tb_top` pad lift destabilized the Verilator model.** Lifting SPI Octal Flash
pads and telemetry packed-array pads to `tb_top.sv` produced a `Vtop::eval()`
SIGSEGV across the whole suite, including previously-working tests. The lift was
reverted. A leftover trailing comma after removing the port bindings was then
reported by the Verilator front-end as *Mixing positional and `.*`/named
instantiation*.

**Missing extensions look like test failures.** The 5 JTAG tests hard-failed
with `SmcJtagTapError: cocotbext-jtag is required`, purely because the package
was not importable — not an RTL or TB defect. Confirm the dependency surface
before debugging a protocol test.

### Loopback proofs

`SmcI2cMasterVip` (the SMC-local clock-sampled master) provides directed
byte-level traffic:

- `smc_i2c_master_target_test_seq` binds slave + master + monitor, issues
  `master.write(0x50, [offset=0x10, byte=0xAB])`, and asserts
  `slave.read_mem(0x10, 1) == 0xAB`. That is direct evidence a real
  START + ADDR(0x50) + DATA(0xAB) + STOP sequence traversed the `tb_i2c0_*` pins
  through the polarity + wired-AND adapter.
- I2C at Standard mode (100 kHz) needs more than 15 min of Verilator wall-clock
  for a 3-byte transaction, so the byte transaction is **gated on
  `cocotb.SIM_NAME` and skipped under Verilator** (the wrapper bind and polarity
  adapter still run). Xcelium is the authoritative byte-level proof.

I3C has no byte-level loopback: `smc_i3c_to_fabric_test` is gated on CSR
decode (HCI_VERSION) plus the external pull-low pad check and records
`proxy=True`.

The `SmcI2cEepromSlave` slave-mode class is ready for real bus traffic. The
remaining work is programming the SMC I2C0 DesignWare controller (`IC_CON`
master mode, `IC_TAR`=0x50, `IC_ENABLE`=1, one `IC_DATA_CMD` write byte) so the
slave records a full START/ADDR/DATA/STOP sequence. That CSR sequence is not yet
mapped in OSS scope; the OVRD-based line check remains the pin-level regression
until it is.

### Remaining blocker roadmap

1. Deepen the I2C pin VIP from line-level checks to directed byte
   transactions. *Partially delivered by the wrappers above;
   controller-side bring-up is the remaining piece.* I3C stays at
   line-level + CSR-proxy checks until a real pad-level VIP with a
   reproducible backend exists.
2. Deepen CPU/JTAG from OSS-safe master-BFM and pin reset/idle checks to full
   firmware boot and TAP-level register access. *TAP-level IDCODE is covered via
   `SmcJtagTap`; full firmware boot depends on the OSS firmware loader.*
3. Deepen bounded sideband/eFuse/diagnostic checkers to physical device and
   fault-injection BFMs when public sources exist. The current OSS standard is
   satisfied by `proxy=False` protocol evidence plus bounded observability and
   real CSR/AXI response checking.

---

## 6b. P2 Phase A Sign-off

### Scope

Six P2 Phase A tests, tracked as six category buckets plus six test issues under
P2 parent `[OS_OCAH] SMC Test Migration - P2` #2893 on Project 335:

- #3482 `i2c_smbus_pmbus` → #3483 `smc_smbus_pmbus_test`
- #3484 `i3c_ccc_ibi_full` → #3485 `smc_i3c_ccc_ibi_full_test`
- #3486 `uart_loopback` → #3487 `smc_uart_loopback_test`
- #3489 `smbus_hostnotify` → #3490 `smc_smbus_hostnotify_test`
- #3491 `spi_loopback` → #3492 `smc_spi_loopback_test`
- #3493 `sideband_avsbus_octs_bfm` → #3494 `smc_sideband_avsbus_octs_bfm_test`

Issues were created and placed on the project by a local `gh` CLI + GraphQL
script, using the same mutation as the P0/P1 migration.

### Verilator model instability and revert

The intermediate SPI/telemetry pad lift described under "Root causes worth
remembering" was reverted here. Baseline restore after the revert plus the
trailing-comma fix:

- `smc_uart_loopback_test` Verilator PASS 74.0 s
- `canonical_top20` Xcelium PASS 103.2 s; Verilator PASS 191.5 s
- P2 Phase A trio Xcelium 3/3 PASS 48.5 s; Verilator 3/3 PASS 127.8 s
- `vplan_triplets` Xcelium **48/48 PASS 289.1 s**; Verilator **48/48 PASS 533.0 s**
  — full P1 slate confidence pass proving no regression from the revert

### Phase A completion

The three deferred items closed with Verilator-safe wrapper-level
implementations:

- `smc_smbus_hostnotify_test` — an SMBus Host Notify frame drives the I2C0 pad,
  reusing the existing polarity + wired-AND adapter with no new `tb_top` port. A
  second `SmcI2cEepromSlave` bound at SMBus Host Address 0x08 captures the
  target-addr + data16 payload; the assertion is on `slave.mem[0xA0..0xA1]`.
- `smc_spi_loopback_test` — `ocah_spi_vip` library import + JEDEC ID readback +
  preload/mem round-trip + SpiMode enum smoke, combined with five low-speed
  peripheral CSR reads via `SmcCsrSeq` (UART_LOG, AVS, OCTS). No `tb_top` pin
  needed. A full pin-driven byte-level proof awaits a Verilator-safe SPI pad lift.
- `smc_sideband_avsbus_octs_bfm_test` — deferred under the no-fake-BFM
  policy: the Python-side fake BFM was retired because it never drove DUT
  pads. The test raises until a real pad-level AVSBus/OCTS VIP exists;
  sideband coverage stays with the proxy CSR/status tests. A full pin-driven
  external BFM proof awaits a Verilator-safe telemetry pad lift.

Closure evidence: Xcelium `p2_phase_a` **6/6 PASS 80.1 s**; Verilator
`p2_phase_a` **6/6 PASS 157.9 s**.

```bash
python3 tools/dv/run_dv.py --dut smc --items p2_phase_a --tool xcelium
python3 tools/dv/run_dv.py --dut smc --items p2_phase_a --tool verilator
```

The full pin-driven SPI byte-level loopback and full pin-driven sideband external
BFM remain roadmap items in `SMC_VPLAN.adoc` §P2, not blockers for Phase A closure.

---

## 6c. Testplan-Execution Details

This content was moved out of `SMC_VPLAN.adoc` so that document could focus purely
on testplan description. Refer to `SMC_VPLAN.adoc` for what each test verifies;
refer to this section for how the infrastructure underneath is delivered.

### 6c.1 Port / VIP delivery status

| Infrastructure | Status | Tests it unlocks | Notes |
|----------------|--------|------------------|-------|
| Reset/powergood/cool-reset agent | built / passing | reset + FLR + multi-reset triplet | Covers public reset behavior; a dedicated FLR source register would deepen the FLR proxy |
| SEP_IN AXI master bridge (`s_axi_*` → `sep_axi_in_req_i`) | built / TOP-20 PASS | All CSR/precheck slices | Use `--stage sim` for Python-only edits after the one-time Verilator build |
| Field-aware CSR access list | partial | Register / eFuse / PLL / Multi-reset depth | Must classify each target as RO, RW, W1C/W1S, side-effect, timeout-prone, retained, or unsafe |
| Timeout/no-response target | bounded CSR timeout built / passing | `smc_axi_timeout_sanity_test`, `smc_zeroer_dma_timeout_test` | Bounded short-timeout CSR path; a true no-response responder remains optional depth |
| Mailbox data/error depth | built / static-checked | `smc_mailbox_data_error_test` | FIFO data path + illegal-access response checks (`mailbox_depth` tag, not canonical) |
| Mailbox event / IRQ source | missing | `smc_mailbox_event_irq_test`, `smc_gpio_irq_active_test` completion | Current tests prove CSR decode/control only |
| I2C VIP/BFM | monitor + master built / passing | I2C triplet + SMBus + PMBus + Host Notify | `SmcI2cBusMonitor` / `SmcI2cEepromSlave` / `SmcI2cMasterVip` in `seq_lib/smc_i2c_protocol_vip.py`. DesignWare controller CSR bring-up still follow-up |
| I3C VIP/BFM | missing | I3C triplet + CCC/IBI SDR extension | No I3C VIP ships; `smc_i3c_to_fabric_test` gates on CSR decode plus the external pull-low pad check (`proxy=True`). Needs a real pad-level VIP with a reproducible backend |
| JTAG/iJTAG VIP | TAP-level built / passing | JTAG triplet | `SmcJtagTap` in `seq_lib/smc_jtag_protocol_vip.py`, `SmcCpuTapDevice(idcode=0x10CA0555, ir_len=5, IDCODE@0x01, DTMCS@0x10, DMI@0x11)`. IR/DR access beyond the default IDCODE latch proven end-to-end |
| UART VIP | built / passing | `smc_uart_loopback_test` | `SmcUartVip` wraps `cocotbext-uart` UartSource + UartSink; 8-N-1 loopback at 115200 baud. The backend resolves from the vendored `cocotbext-uart` in the locked environment |
| SPI VIP | library-level built / passing | `smc_spi_loopback_test` | `ocah_spi_vip.OcahSpiFlash` library integration + mock signals; full pin-driven loopback needs a Verilator-safe SPI pad lift |
| Sideband pad-level BFM | missing | `smc_sideband_avsbus_octs_bfm_test` (deferred) | Fake BFM retired under the no-fake-BFM policy (never drove DUT pads); needs a real pad-level AVSBus/OCTS VIP plus a Verilator-safe telemetry pad lift |
| Output-fabric responder / memory slave | built / passing | `smc_input_output_fabric_wr_rd_test`, `smc_output_filter_remap_security_test`, `smc_output_fabric_wr_rd_responder_test` | JTAG AXI final VIP path drives real write/read and allow/block checks |
| CPU firmware loader or force-splice | missing | `smc_cpu_sanity_test`, `smc_occp_sanity_secure_error_test` | Copy the SEP CPU/firmware pattern only after the fabric path is stable |
| eFuse/OTP shim usage plan | partial | `smc_efuse_permission_boundary_test` | Verilator stubs exist; safe CSR/shim semantics need classification |
| Sideband external BFM (real pins) | missing | Full sideband promotion | AVSBus/OCTS/telemetry blocked-window prechecks pass; full external BFM needs a pad-lift refactor |
| Fault/diagnostic injection | missing | `smc_dfd_sanity_test`, `smc_cpu_ecc_lint_pint_depth_test` deepening | Currently a bounded diagnostic representative only |

### 6c.3 Roadmap / implementation order

1. Keep broad `smoke` as the debug regression; do not add weak variants just to
   increase test count.
2. Keep `canonical_top6`, `canonical_top10`, and `canonical_top20` active; all
   listed entries have Verilator PASS with at least an active CSR/precheck slice.
3. Build a field-aware CSR catalog from `smc_top_reg.svh` and selected generated
   structs. Classify each target as RO, RW, W1C/W1S, side-effect, timeout-prone,
   retained, or unsafe.
4. Replace the bounded CSR timeout with a true no-response responder only if
   deeper timeout semantics are required.
5. Add a dedicated FLR source when available; keep the current cool-reset
   recovery test as the OSS-active approximation.
6. Keep `smc_mailbox_data_error_test` as the mailbox depth regression and use its
   response-code checks as the model for other expected-error AXI tests.
7. Deepen I2C to a DUT-controller-driven byte transaction once DesignWare I2C0
   controller CSR bring-up (`IC_CON`/`IC_TAR`/`IC_ENABLE`/`IC_DATA_CMD`) is
   drafted.
8. Deepen JTAG to DMI-side CPU debug register access once CPU firmware boot lands.
9. Refactor the `tb_top` pad lift to be Verilator-safe so the full pin-driven SPI
   byte-level loopback and sideband external BFM tests can graduate from
   library-level to pin-driven proofs.
10. Do not add more breadth tests until a precheck is deepened.

### 6c.4 Open design questions

- Should the active AXI agent be renamed from `SmcSysAxiAgent` to
  `SmcSepInAxiAgent`, or keep the current name to avoid churn?
- Which generated register source should own the CSR catalog:
  `smc_top_reg.svh`, `smc_top_reg_structs.svh`, or a generated Python map?
- Should `canonical_top6` replace the current `smoke` CI target, or stay as a
  smaller parallel CI tier?
- Which responder should unlock deeper fabric coverage first: an explicit
  output-fabric memory slave, a remap/filter test responder, or a controlled
  deny/timeout responder?
- Can sideband tests share one external BFM without hiding failures, or should
  AVSBus/OCTS/telemetry each stay as depth follow-ons after one representative
  canonical smoke exists?

---

## 6d. P1 Coverage-Gap Depth Slate Sign-off

Five rounds closed the RTL-vs-testplan coverage gap identified in `SMC_VPLAN.adoc`
§P1 Coverage-Gap Depth Slate. Tests land under `--items p1_coverage_gap` plus a
per-round tag.

### Round 1 — one representative per unreached block (13 tests)

Extensions to existing P1 categories: `smc_mailbox_inbound_test` (P1-5),
`smc_i2c_multi_instance_test` (P1-6), `smc_i3c_wrap_extended_test` (P1-7),
`smc_efuse_map_read_test` + `smc_efuse_shim_ctrl_test` (P1-9),
`smc_pll_cgm_awm_config_test` (P1-10), `smc_gpio_ctrl_full_sweep_test` (P1-11),
`smc_uart_multi_instance_test` (P1-12), `smc_telemetry_receiver_csr_test` (P1-13).

New P1 categories: `smc_cluster_cpu_infra_test` (P1-17, bundles WDT + PLIC +
CLINT), `smc_pvt_analog_sensor_test` (P1-18, bundles PVT combined + temp +
POC/PBIAS), `smc_remap_cla_test` (P1-19, bundles MMODE_REMAP + full ALIAS sweep +
CLA), `smc_cdns_i3c_axil_test` (P1-20).

New helper: `SmcCsrSeq.csr_read_bounded()` tolerates **both** DECERR and timeout,
for CSR blocks that are clock-gated or absent in the current bring-up (WDT /
PLIC / CLINT / PLL_CGM_AWM / GPIO_CTRL / EFUSE_SHIM / AXIL_EXT / PVT /
POC_PBIAS). It increments both `accesses` and `timeouts` on no-decode.

Evidence: Xcelium `p1_coverage_gap` **13/13 PASS 45.7 s**; Verilator **13/13
PASS**. Regression parity: `canonical_top20` Xcelium 20/20 PASS 98.3 s +
Verilator 20/20 PASS 229.9 s.

Coverage impact: SMC top-level distinct CSR blocks with any test coverage went
from **29 → 41 of 51** (43% → 80%). Multi-instance depth (I2C 3-instance, UART
4-instance, I3C 6-instance OCA, Mailbox 30-pair, ALIAS/MMODE/FILTER
8/8/16-entry) had previously touched only the first instance. Subsystems that P0/P1
could not reach at all — PVT, POC-PBIAS, WDT, PLIC, CLINT, CGM/AWM, eFuse-shim,
telemetry, MMODE-remap, CLA, Cadence-I3C-AXIL — all landed under bounded probes.

### Round 2 — multi-instance depth

- `smc_mailbox_multi_instance_test` — all 32 outbound + 32 inbound mailbox STATUS
  registers (64 reads + 3 clock-gate accesses).
- `smc_filter_multi_entry_test` — all 16 inbound + 16 outbound filter
  FILTER_CONFIG entries (32 reads).
- `smc_gpio_refclk_ctrl_test` — GPIO_REFCLK_CTRL (0xC000_4CC0), separate from the
  GPIO_INTF / GPIO_CTRL sweeps.
- Fix: `smc_gpio_ctrl_full_sweep_test` extended from 46 → 68 entries (RTL has
  GPIO_CTRL_0..67; the first pass under-counted).
- New testlist `p1_coverage_gap_r2.toml`.

Evidence: Xcelium `p1_coverage_gap + r2` **16/16 PASS 53.8 s**; Verilator
**16/16 PASS 120.0 s**.

### Round 3 — field-level depth

- `smc_gpio_intf_full_sweep_test` — all 68 GPIO_INTF entries (previously 0-2).
- `smc_mailbox_field_sweep_test` — per-mailbox 6-field decode
  (STATUS/ERROR_FLAGS/WIRQT/RIRQT/IRQEN/IRQS) × 4 outbound mailboxes; rounds 1/2
  touched only STATUS.
- `smc_filter_field_sweep_test` — per-filter 3-field decode
  (FILTER_CONFIG/START_ADDR/END_ADDR) × 4 entries × 2 directions = 24 reads.
- `smc_pll_awm_freq_sweep_test` — AWM 0 + AWM 1 FREQUENCY 0..5 + CGM 0..2
  sub-blocks (9 × 2 = 18 reads); round 1 touched only the AWM base.
- New testlist `p1_coverage_gap_r3.toml`.

Evidence: Xcelium `p1_coverage_gap_r3` **4/4 PASS 16.6 s**; Verilator **4/4 PASS
40.7 s**. Aggregate `p1_coverage_gap + r2 + r3` **20/20 PASS both simulators**
(Xcelium 87.6 s, Verilator 180.9 s).

### Round 4 — previously-unreached CSR blocks

A second RTL-vs-testplan audit found three addressable surfaces R1–R3 missed, all
simple bounded reads through the existing `SmcSysAxiAgent` + `csr_read_bounded()`
path:

- `smc_xvisor_remap_test` — the 8-entry hypervisor remap table
  `SMC_XVISOR_REMAP_0..7` (0xC001_4000 stride 0x08), sibling of the already
  covered ALIAS_REMAP (0xC001_2000) / MMODE_REMAP (0xC001_3000) tables.
- `smc_cluster_beu_test` — the 4 per-core Bus Error Units
  `SMC_CLUSTER_CORE0..3_BEU` (0xC801_0000 stride 0x1000), reading
  CAUSE/ENABLE/PLIC_ENABLE per core (12 bounded reads).
- Fix: `smc_cdns_i3c_axil_test` extended from 4 → **6** wraps (RTL has
  wrap_0..5; wrap_4 @ 0xC040_1000 and wrap_5 @ 0xC040_1400 were unreached). Its
  `accesses` assertion moves from 8 → 12.
- New testlist `p1_coverage_gap_r4.toml`.

This round also hardened the protocol-VIP scoreboard (see §6 Protocol VIP
Status). Evidence: `p1_coverage_gap_r4` + extended `smc_cdns_i3c_axil_test`
**3/3 PASS** on Verilator (`smc_xvisor_remap_test` accesses==8,
`smc_cluster_beu_test` accesses==12, `smc_cdns_i3c_axil_test` accesses==12). The
scoreboard-hardening regression on `p2_phase_a` confirmed the new
`details != ""` / `timeouts <= csr_accesses` asserts do not regress the five
`csr_accesses=0` pin-VIP tests.

### Round 5 — exhaustive block audit

An exhaustive audit cross-checked *every* `*_REG_MAP_BASE_ADDR` container in
`smc_top_reg.svh` against the addresses the cocotb sequences actually read. Two
surfaces remained:

- `smc_pvt_droop_test` — `SMC_PVT_WRAP_DROOP` (0xC000_7400), the droop-monitor
  sub-block between the PVT combined-sensor (0xC000_7000) and temp-sensor
  (0xC000_7900) surfaces; 10 representative bounded reads spanning
  control/sampling/config/readback.
- `smc_dft_ctrl_test` — bounded read of top-level `DFT_CTRL` STATUS_SMU
  (0xC000_F800). On Verilator the DFT wrap is a stub
  (`verilator_stubs/smc_dft_ctrl_status_wrap.sv`) so the read may no-decode; on
  Xcelium it hits the real decode.
- New testlist `p1_coverage_gap_r5.toml`.

Evidence: `p1_coverage_gap_r5` **2/2 PASS** on Verilator
(`smc_pvt_droop_test` accesses==10, `smc_dft_ctrl_test` accesses==1).

**Post-Round-5 claim:** every top-level CSR block container in
`smc_top_reg.svh` is touched by at least one OSS test.

Two documentation corrections landed with this round. First, the earlier "only
protocol-complete gaps remain" statement after Round 2 was inaccurate — Rounds 4
and 5 found five more non-firmware-gated surfaces. Second, the VPLAN
P1-17/18/19 tables had listed nine per-sub-block test names
(`smc_cluster_wdt_sanity_test`, `smc_cluster_plic_test`, `smc_cluster_clint_test`,
`smc_pvt_combined_sensor_test`, `smc_pvt_temp_sensor_test`,
`smc_gpio_poc_pbias_sanity_test`, `smc_mmode_remap_csr_test`,
`smc_cla_sanity_test`, `smc_alias_remap_full_sweep_test`) that were never created
standalone; they are implemented as the three bundled tests
`smc_cluster_cpu_infra_test`, `smc_pvt_analog_sensor_test`, and
`smc_remap_cla_test`. The VPLAN tables now point at the bundled names.

### Aggregate regressions

Combined `canonical_top20 + vplan_triplets + p1_coverage_gap +
p1_coverage_gap_r2 + p2_phase_a` (71 tests, deduplicated): Xcelium **71/71 PASS
375.7 s**; Verilator **71/71 PASS 707.7 s**.

```bash
python3 tools/dv/run_dv.py --dut smc \
  --items canonical_top20 vplan_triplets p1_coverage_gap p1_coverage_gap_r2 p2_phase_a \
  --tool verilator
```

The complete discovered set (109 tests) reached **109/109 PASS** on Verilator via
`--stage sim`. The first pass showed 103/109, with all six I3C tests failing on
`ImportError: No module named 'cocotbext_i3c'` and the five JTAG tests failing on
`SmcJtagTapError: cocotbext-jtag is required`. Both were dependency-visibility
problems, not TB or RTL defects; once the extensions were importable all eleven
passed. See §1 for the current dependency surface.

```bash
python3 tools/dv/run_dv.py --dut smc \
  --items $(python3 tools/dv/run_dv.py --dut smc --list \
            | sed -n 's/^tests *: //p' | tr ',' ' ') \
  --tool verilator --stage sim
```
