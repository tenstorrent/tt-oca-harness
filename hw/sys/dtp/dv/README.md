<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->
# DTP DV

## Overview

DV environment for DTP (Debug & Test Ports), the subsystem that hosts the
primary JTAG TAP (IEEE 1149.1), the JTAG2AXI debug bridges, the iJTAG networks
(IEEE 1687), and the cross-trigger network (CTP/CTM). It is one scenario set in
two realizations of the same testbench top (`tb/tb_top.sv`): PyUVM on cocotb,
run on Verilator, and SystemVerilog UVM, run on VCS. Both compose the shared
OCAH VIPs from [`hw/common/dv/vip`](../../../common/dv/vip) and drive the same
scenarios, knobs, evidence, and coverage modules.

## Prerequisites

| Need | Why | Notes |
| --- | --- | --- |
| `uv` on `PATH` | every `run_dv.py` command | The launcher runs itself again through `uv run --locked --group dv` against the root `uv.lock`, which provides cocotb, pyuvm, and the shared DV packages |
| Python 3.11 to 3.13 | the launcher | `requires-python` in the root `pyproject.toml` |
| The `tt-oca-manifest` submodule | every `run_dv.py` command | A member of the root `uv` workspace: without it `uv` cannot resolve the project and the launcher stops before any stage runs. Check it out once with `git submodule update --init hw/sys/sep/bootrom/prod/tools/tt-oca-manifest` |
| Verilator 5.052 | the cocotb realization | The release CI builds (`.github/actions/dv-run/action.yml`); the doctor rejects a release older than 5.036 |
| Bender | the filelist stage | Must be on `PATH` |
| VCS | `--framework uvm` | A licensed simulator; the runner's `uvm` framework runs on VCS only |
| SymbiYosys (`sby`) | `--mode formal` | Yosys with the yosys-slang frontend and an SMT solver on the same `PATH` |

Once `uv` and the submodule are in place,
`python3 tools/dv/run_dv.py --doctor --dut dtp` checks the Python environment
and the simulators the cocotb flow can use; add `--framework uvm` to check for
VCS or `--mode formal` to check for `sby`. It does not probe Bender.
[`doc/starting/src/setup.adoc`](../../../../doc/starting/src/setup.adoc)
covers cloning, every submodule, and the toolchain container.

## Getting Started

```bash
python3 tools/dv/run_dv.py --dut dtp --build-only                    # filelist and Verilator build
python3 tools/dv/run_dv.py --dut dtp --items smoke                   # one basic scenario per feature area
python3 tools/dv/run_dv.py --dut dtp --items all                     # every scenario, cocotb on Verilator
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items smoke    # the same scenarios, SV-UVM on VCS
python3 tools/dv/run_dv.py --dut dtp --mode formal                   # the formal smoke group
```

`--items` takes a scenario name or a testlist group (`smoke`, `basic_jtag`,
`debug_tdr`, `jtag2axi`, `scan`, `xtrig`, `dbg_disable`, `functional`, `all`);
the same name selects the same scenario in either realization. The runner's
options, the loop and seed knobs, and the site layer are described in
[`tools/dv/doc/run-dv.adoc`](../../../../tools/dv/doc/run-dv.adoc); the
`smoke` and `all` commands above are the pull-request gate and the nightly
regression, and "Continuous integration" in the same guide describes the
workflows that run them.

| Document | What it covers |
| --- | --- |
| [`docs/DTP_VPLAN.adoc`](docs/DTP_VPLAN.adoc) | Every scenario with its procedure, checkers, and pass criteria; the formal verification plan; the verification scope, the requirement-to-test matrix, the regression groups, and known limitations |
| [`docs/DTP_TB_ARCH.adoc`](docs/DTP_TB_ARCH.adoc) | Testbench hierarchy, VIP selection and DUT-local model ownership, environment components, stimulus, checking (with the negative-validation knobs), and coverage strategies, the SV-UVM realization and its differences from cocotb, adding a scenario, overlaying a commercial VIP |
| [`docs/DTP_FCOV.adoc`](docs/DTP_FCOV.adoc) | Functional coverage plan, coverage targets, and closure policy |
| [`doc/integrator/src/defines.adoc`](../../../../doc/integrator/src/defines.adoc) | Project defines chapter of the Integrator Guide: the view, tool, assertion and DV defines a DTP compile reads |
| [`../doc/index.adoc`](../doc/index.adoc) | Design specification, with the JTAG and cross-trigger IP chapters |
| [`hw/common/dv/README.md`](../../../common/dv/README.md) | Shared VIPs, BFM ownership, and the promotion checklist |
| [`hw/common/dv/docs/formal-property-style.adoc`](../../../common/dv/docs/formal-property-style.adoc) | Property style the `formal/` modules implement |

## Layout

| Path | Contents |
| --- | --- |
| `tb/` | `dtp_uvm_top` (`tb_top.sv`), the framework-neutral core both realizations share, with the `dtp_tb_if`, `dtp_scan_if`, and `dtp_xtrig_if` interfaces; the bench configuration table that elaborates the DUT (`dtp_dv_cfg_pkg.sv`); the JTAG2AXI bridge state-flag decoder (`dtp_j2a_state_flags.sv`); and the bench SVA (`dtp_stap_host_sva.sv`, `dtp_axi_data_known_sva.sv`) |
| `cocotb/` | PyUVM realization: `env/`, `seq_lib/`, `tests/` |
| `uvm/` | SV-UVM realization: `env/`, `seq_lib/`, `tests/` |
| `cov/` | Functional coverage modules (`sv/`) and the coverage configuration (`config/`): the Verilator and VCS coverage policies, the VCS compile-time coverage scope, and the URG exclusion lists |
| `formal/` | Property modules and binds (`props/`), SymbiYosys tasks (`fpv/sby/`) |
| `testlists/` | TOML testlists for simulation and formal |
| `docs/` | The documents above |
| `dtp_sim_cfg.toml`, `dtp_formal_cfg.toml` | Simulation and formal configuration |

## Contributing

Read [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) for the pull-request
process, SPDX headers, and the lint and format commands. A new scenario is one
framework-neutral test case with a realization in `cocotb/` and one in `uvm/`.
To add one:

1. Add the cocotb test module under `cocotb/tests/`. Its scenario is either a
   case of the family's test sequence in `cocotb/seq_lib/`, selected by the
   `scenario` string the test passes, or a sequence of its own there on the
   family's base sequence.
2. Add a `[[tests]]` entry for it to the area's list under `testlists/`, list
   the name in every group it belongs to, and raise each of those groups'
   `expected_count`.
3. Add the SV-UVM twin; "Adding a Scenario to the SV-UVM Realization" in
   [`docs/DTP_TB_ARCH.adoc`](docs/DTP_TB_ARCH.adoc) is its checklist, and its
   Testlist step binds the twin in the entry from step 2.
4. Add the scenario's Test Procedure, summary row, and matrix row to
   [`docs/DTP_VPLAN.adoc`](docs/DTP_VPLAN.adoc), and check that the VPLAN to
   FCOV Traceability table in [`docs/DTP_FCOV.adoc`](docs/DTP_FCOV.adoc)
   names the covergroups it drives.
