<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC OSS DV

Open-source DV environment for the SMC (System Management Controller) subsystem.
Flow = cocotb/PyUVM on Verilator (functional backend) and VCS/Xcelium (coverage),
driven by `tools/dv/run_dv.py`. See `docs/index.adoc` for the chapter set:
`docs/SMC_TB_ARCH.adoc` for test development, environment setup and run
recipes, `docs/SMC_VPLAN.adoc` for the verification plan,
`docs/SMC_FCOV.adoc` for the coverage pipeline, and
`docs/SMC_SCOPE_TRACEABILITY.adoc` for the candidate v0.5.0
requirement-to-test matrix (unsigned; #496),
`docs/SMC_CANONICAL_BRINGUP_SIGNOFF.adoc` for the canonical bring-up /
CSR signoff record (#498),
`docs/SMC_FABRIC_PERIPH_SIGNOFF.adoc` for the fabric / peripheral
honesty record (#500),
`docs/SMC_RELEASE_MATRIX.adoc` for the v0.5.0 release regression
matrix (#502), and
`docs/SMC_RESET_CLOCK_IRQ_SIGNOFF.adoc` for the reset / clock / IRQ
signoff record (#499).

**Green / signoff policy:** only claim **real DUT RTL paths**.
I3C CCC/IBI / real-core protocol, adopter PLL/PVT OKAY wraps, and TB-glue
demos (e.g. hardcoded DFD capture token) are not ported
— not reportable as feature PASS. `smc_i3c_to_fabric_test` is
**decode only** (fabric → real OCA core `HCI_VERSION`) and is **not**
in `smoke` or `project_p0`. Run it via `i3c_depth`
or by name. Checklist:

**`allow_timeout` review gate:** default `False`. New `allow_timeout=True`
call sites need a one-line rationale comment at the call (what hangs without
it, and why that is still a real DUT path). Inventory: `smc_*_utils.py` /
cluster helpers — do not add silently in PRs.

## Present but not enrolled

These modules exist under `cocotb/tests/` and are not in `testlists/all.toml`.
The blocker tag lives in each file's docstring (`# deferred: <reason>`). SMU's
matching catalog is `hw/sys/smu/dv/cocotb/tests_deferred/`.

| Test | Reason |
|------|--------|
| `smc_i3c_ccc_ibi_full_test` | `needs_i3c_dat_dct` — no TB DAT/DCT RAM |
| `smc_macro_axil_routing_test` | `needs_dtp_csr_sub` / `rtl_placeholder` — DTP CSR idle; pll/pvt OKAY wraps |
| `smc_pll_pvt_clock_config_test` | `rtl_placeholder` |
| `smc_pll_dvfs_depth_test` | `rtl_placeholder` |
| `smc_pll_cgm_awm_config_test` | `rtl_placeholder` |
| `smc_pll_awm_freq_sweep_test` | `rtl_placeholder` |
| `smc_pvt_analog_sensor_test` | `rtl_placeholder` |
| `smc_pvt_droop_test` | `rtl_placeholder` |
| `smc_sideband_avsbus_octs_bfm_test` | `fake_bfm` — no pad BFM |
| `smc_dfd_dbs_fault_inject_test` | `tb_glue` — hardcoded capture token, not `smc_dfd_wrap` |

Two enrolled carve-outs keep their measured reason next to the stimulus:
`HYST_LEGAL_LO` in `smc_clk_multi_window_test_seq.py` (0..7) and the
`smc_clint_csr_test` docstring (cluster-local fold).

## Single DUT

**Launch entry: `--dut smc`** (discovered by the runner's directory
convention from `smc_sim_cfg.toml`). `tb/tb_top.sv` (`smc_uvm_top`) instantiates
`hw/top/smc_wrapper.sv` (`smc` + `smc_ip_integration` + `smc_cpu_mem_integration`),
so the bare DUT name selects the wrapper-based TB.

| | |
|---|---|
| select | `--dut smc` |
| config | `smc_sim_cfg.toml` |
| TB top | `smc_uvm_top` (`tb/tb_top.sv`) |
| DUT | `smc_wrapper` |
| cocotb | `cocotb/` (`SmcEnv`) |
| testlist | `testlists/all.toml` |
| macros | inside `smc_ip_integration` (pll/pvt/efuse/pads/I3C DAT-DCT-RLT) |
| CPU mem | inside wrapper via `smc_cpu_mem_integration` |
| in TB | SYS_OUT=`axi_sim_mem` (pulp VIP); DTP CSR **idle** on `smc_wrapper` (no TB terminator; DTP CSR is a smc_wrapper-only boundary) |

## Verilator stubs policy

`tb/verilator_stubs/` may contain **tooling shims only** (`prim_sync2` /
`prim_sync3` for OSS prim port remap + X-init). Product-module overrides
(`smc_reset_*`, `smc_dfx_*`, …) are forbidden.

| Concern | Handling |
|---------|----------|
| PeakRDL nested hwif structs break Verilator C++ codegen | `disable_public_flat_rw` + `smc_public_scope.vlt`; the real RTL compiles |
| Product `och_prim` `prim_sync2/3` use private `.i_CK` ports, unlike the OSS OT-style cells | DV `prim_sync*` tooling stubs remap them; product RTL is untouched |

## Layout

```
hw/sys/smc/dv/
├── cocotb/                 # PyUVM env, seq_lib, tests
├── uvm/                    # SV-UVM env, seq_lib, tests (--framework uvm, VCS)
├── models/                 # pll/pvt PeakRDL wraps (adopter placeholders)
├── tb/                     # tb_top.sv (cocotb + UVM shapes), smc_tb_signal_list.svh,
│                           # smc_tb_if.sv, verilator_stubs/
├── testlists/
├── assets/                 # preloaded memory/fuse images the testlists pass by
│                           # plusarg (ROM hex, eFuse shadow, scratch stripes)
├── fw/                     # C firmware the CPU-boot scenarios execute; built by
│                           # the toolchain container, not by the DV runner
├── cov/                    # functional-coverage collection and merge inputs
├── docs/                   # VPLAN, FCOV and TB architecture
└── smc_sim_cfg.toml        # both frameworks: [frameworks.cocotb] + [frameworks.uvm]
```

`assets/`, `fw/`, `models/` and `uvm/` are outside the five directories the DV
sign-off checklist names at 6.1, and are held here deliberately:

* `assets/` — a preload image is an input to a scenario, so it belongs beside
  the testlist that names it rather than in a shared pool where a rebuild for
  one subsystem would move another's expectations.
* `fw/` — the CPU-boot scenarios need firmware whose source is versioned with
  the tests that run it; it is built by the toolchain container and consumed as
  a ROM image, never compiled by the DV runner.
* `models/` — bus terminators and register stand-ins, each declared in
  `models/README.md` with what it replaces and why the shared component does
  not fit.
* `uvm/` — the SV-UVM shape of the same scenarios, selected by
  `--framework uvm`; it shares `tb/tb_top.sv` with the cocotb shape.

`tb/tb_top.sv` is ONE module with two shapes: the cocotb pin port list by
default, and under the bare `+define+UVM` (set by the native profile's
`[frameworks.uvm]` overlay) a self-contained SV-UVM harness that `include`s
`uvm/tests/smc_tests.sv`. Every TB signal is declared once in
`tb/smc_tb_signal_list.svh`. The SV-UVM realization is described in
`docs/SMC_TB_ARCH.adoc` ("SystemVerilog UVM Realization"); the framework
conventions it follows are in `hw/common/dv/docs/uvm-framework.adoc`.

`cocotb/env/smc_cpu_trace_monitor.py` is the passive hart-0 processor-state
monitor (symbolized call stack, trap records, hang watch) that both the
single-instance and the dual bench run; a failing test ends with its dump in
the log. `cocotb/env/smc_virt_console.py` decodes the firmware virtual console
on scratch register 2 for both benches.

## Run

```bash
module load verilator/5.050 gcc/13.2.1   # C++20 for cocotb -fcoroutines; 5.050 fixes bad C++ init of nested unpacked structs seen with 5.046
PY=tools/dv/run_dv.py
python3 $PY --dut smc --items smoke --tool verilator
python3 $PY --dut smc --items smc_cold_reset_test --stage flist --stage hdl_compile --stage sim
python3 $PY --dut smc --items all --stage sim --regress
```

### SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM view shares this DV root, sim config, and testlist with the cocotb
flow: `smc_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay (same
Bender RTL recipe), and `--dut smc --framework uvm` selects it. A testlist
scenario carries both implementations in its `module` binding map
(`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). Selecting a scenario with no `uvm` entry
errors; `--skip-unimplemented` runs a group's UVM-implemented subset instead.
VCS only: Verilator has no SV-UVM support. The bench architecture is in
`docs/SMC_TB_ARCH.adoc` ("SystemVerilog UVM Realization"); the framework
conventions it follows are in `hw/common/dv/docs/uvm-framework.adoc`.

The first bound scenario is `smc_register_sanity_test`:
SEP_IN AXI4 idle-read / write / readback / restore of the `SCRATCH_COLD` and
`SCRATCH_COLD_WARM` registers over 16 seeded passes, every scratch read
predicted by `smc_scratch_csr_ref_model` and paired by the always-on
`smc_scoreboard`, and every access recorded as named `CHK-*` evidence
(`CHECKER_SUMMARY name=smc_csr`).

```bash
# SV-UVM build only (VCS). --skip-unimplemented (or an --items selection) is required:
# without it the runner selects the cocotb-only scenarios and stops before compiling.
python3 tools/dv/run_dv.py --dut smc --framework uvm --build-only --skip-unimplemented

# Full regression: every test this package defines.
python3 tools/dv/run_dv.py --dut smc --items all --tool verilator --regress

# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut smc --items smc_register_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test --seed 1

# Smoke group, UVM-implemented subset
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smoke --skip-unimplemented

# Scoreboard negative validation: a corrupted scratch readback prediction
# must FAIL the run
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test \
  --plusarg +SMC_CSR_SCOREBOARD_NEGATIVE

# Loop-count knobs, resolved specific-first (per test, per group, suite-wide);
# every looped test runs at least 16 seeded passes by default
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smc_register_sanity_test \
  --plusarg +SMC_REGISTER_SANITY_TEST_LOOPS=4
python3 tools/dv/run_dv.py --dut smc --framework uvm --items smoke --skip-unimplemented \
  --plusarg +SMC_TEST_LOOPS=1
```

To port another cocotb scenario: add `uvm/seq_lib/<name>_seq.svh` on
`smc_base_test_seq` (CSR accesses through `csr_write` / `csr_read`, named
evidence through `attach_evidence` / `check_evidence` / `finalize_evidence`),
add `uvm/tests/<name>.svh` on `smc_base_test` (override
`create_scenario_seq()`, the loop-knob hooks, and `configure_test_cfg()` for
the scoreboard features it requires), add both `include`s to the package and
the manifest, and change the scenario's testlist entry to the binding map. A
pin the scenario needs that the harness ties off is promoted into
`tb/smc_tb_if.sv` first.

PASS/FAIL is classified by the global parser registry
(`hw/common/dv/configs/parsers.toml`). The cocotb flow requires positive
evidence from `results.xml`; a clean simulator exit alone is not enough.
