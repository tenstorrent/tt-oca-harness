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
| `ocah_path_plusargs` | none | file-path plusarg guard: every present `+<name>=<path>` in a bench's list is opened at time 0 and a missing file ends the run with one line naming the plusarg |

`uvm/` is the SystemVerilog realization (`ocah_lib_pkg`, entered through
`uvm/sources.toml` ahead of the protocol VIP manifests). `cocotb/` is the
PyUVM realization with the same basenames, one module per base; the Python
class takes the basename in CamelCase with acronyms written as words
(`ocah_test` is `OcahTest`, `ocah_rng` is `OcahRng`), and the package root
re-exports every class, so a bench writes `from ocah_lib import OcahTest`.
The `ocah-dv` package finds it under `hw/common/dv/vip/` with the protocol
VIPs; a DUT sim config reaches it through the same `python_paths` entry. The
reference bench is `hw/sys/dtp/dv/`.

The two realizations differ only where the language forces it:

| Aspect | cocotb (`cocotb/`) | SV-UVM (`uvm/`) |
|---|---|---|
| Knob transport | environment variables (`OcahKnobs`) | plusargs (`ocah_knobs`) |
| File-path plusarg guard | `require_file_plusargs(names)`, first statement of the bench base test's `build_phase` | `ocah_require_file_plusargs(names)` from an undelayed `initial` in the bench top, which `` `include ``s `ocah_path_plusargs.svh` |
| Seed source | `RANDOM_SEED`, read once by `OcahTest.base_seed` | `+ntb_random_seed`, read once by `ocah_test::base_seed` |
| Per-pass randomness | `OcahSequence.rng(label)`: one `random.Random` per helper, seeded by `OcahRng.salted_seed` | `seed_scenario_rng()` seeds the `body()` process once; helpers draw from `$urandom` |
| Looped scenario | `run_looped_scenario()` over the same hooks, plus `start_looped_seq(seq_cls, ...)` since a class is a value | `run_looped_scenario()` over `create_scenario_seq()` |
| Scoreboard verdict | a mismatch or an unpaired item folds into the feature's `CHK-SB-*` record, which fails `check_phase` through `OcahChecker.finalize` | a mismatch or an unpaired item is a `uvm_error` at once |
| Run verdict | an exception escaping a phase; `results.xml`; no banner from test code | `UVM_ERROR`/`UVM_FATAL` counts plus `UVM TEST PASSED` from `report_phase` |

Knob names, feature names, `CHK-SB-*` IDs, the loop-count resolution order,
`MIN_DEFAULT_LOOPS`, the salt formula, and the directed pattern prefix are
identical; `cocotb/examples/example_ocah_lib_selftest.py` pins the shared
values and exercises the scoreboard pairing contract without a simulator:

```bash
PYTHONPATH=hw/common/dv/vip python3 -m ocah_lib.cocotb.examples.example_ocah_lib_selftest
```
