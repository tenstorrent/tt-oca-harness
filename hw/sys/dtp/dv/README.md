<!-- SPDX-License-Identifier: Apache-2.0 -->
# DTP DV

## Overview

DV environment for DTP (Debug & Test Ports), the subsystem that hosts the
primary JTAG TAP (IEEE 1149.1), the JTAG2AXI debug bridges, the iJTAG networks
(IEEE 1687), and the cross-trigger network (CTP/CTM). It is one scenario set in
two realizations of the same testbench top (`tb/tb_top.sv`): PyUVM on cocotb,
run on Verilator, and SystemVerilog UVM, run on VCS. Both compose the shared
OCAH VIPs from [`hw/common/dv/vip`](../../../common/dv/vip) and drive the same
scenarios, knobs, evidence, and coverage modules.

## Getting Started

```bash
python3 tools/dv/run_dv.py --dut dtp --build-only                    # filelist and Verilator build
python3 tools/dv/run_dv.py --dut dtp --items smoke                   # TAP FSM and IDCODE gate
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
| `tb/` | `dtp_uvm_top` (`tb_top.sv`), the framework-neutral core both realizations share, with the `dtp_tb_if`, `dtp_scan_if`, and `dtp_xtrig_if` interfaces |
| `cocotb/` | PyUVM realization: `env/`, `seq_lib/`, `tests/` |
| `uvm/` | SV-UVM realization: `env/`, `seq_lib/`, `tests/` |
| `cov/` | Functional coverage modules |
| `formal/` | Property modules and binds (`props/`), SymbiYosys tasks (`fpv/sby/`) |
| `testlists/` | TOML testlists for simulation and formal |
| `docs/` | The documents above |
| `dtp_sim_cfg.toml`, `dtp_formal_cfg.toml` | Simulation and formal configuration |

## Contributing

Read [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md) for the pull-request
process, SPDX headers, and the lint and format commands. A new scenario is one
framework-neutral test case with a realization in `cocotb/` and one in `uvm/`;
"Adding a Scenario to the SV-UVM Realization" in
[`docs/DTP_TB_ARCH.adoc`](docs/DTP_TB_ARCH.adoc) is the checklist.
