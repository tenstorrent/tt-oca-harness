<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# ocah_lib — shared DV framework library

The framework layer every OCAH bench class extends, so the seed and loop
policy, the knob transport, the pass banner, the scoreboard feature registry,
and the evidence plumbing are written once. Each base takes the UVM class name
with `uvm_` replaced by `ocah_`; utilities with no UVM ancestor take `ocah_`
plus a noun.

| Basename | UVM parent | Provides |
|---|---|---|
| `ocah_test` | `uvm_test` | seed accessor, knob accessor, loop policy, `run_looped_scenario`, pass banner |
| `ocah_env` | `uvm_env` | composition base for `<dut>_env` |
| `ocah_sequence #(REQ)` | `uvm_sequence` | per-pass seed, loop index, seeded pattern helpers, step logging |
| `ocah_sequencer #(REQ)` | `uvm_sequencer` | base of `<dut>_virtual_sequencer` |
| `ocah_sequence_item` | `uvm_sequence_item` | timestamp and evidence context for DUT-local items |
| `ocah_agent`, `ocah_driver`, `ocah_monitor` | `uvm_agent`, `uvm_driver`, `uvm_monitor` | bases for a DUT-local agent |
| `ocah_scoreboard` | `uvm_scoreboard` | feature registry, in-order pairing of each feature's observed and expected streams, per-feature counters, zero-comparison rejection, `CHK-SB-*` evidence; holds no prediction |
| `ocah_subscriber #(T)` | `uvm_subscriber` | always-on invariant checker with an evidence handle |
| `ocah_ref_model #(OBS, EXP)` | `uvm_subscriber` | per-feature predictor: observed stream in, expected items out on `expected_ap`; no comparison, no verdict |
| `ocah_test_cfg`, `ocah_env_cfg` | `uvm_object` | the two configuration levels |
| `ocah_knobs`, `ocah_rng` | none | plusarg accessor; seed salting and directed patterns |

`uvm/` is the SystemVerilog realization (`ocah_lib_pkg`, entered through
`uvm/sources.toml` ahead of the protocol VIP manifests). The cocotb realization
carries the same basenames under `cocotb/` when it lands. The reference bench is
`hw/sys/dtp/dv/`.
