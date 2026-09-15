<!-- SPDX-License-Identifier: Apache-2.0 -->
# I3C core wrapper block DV

Block-level cocotb TB for `i3ccore_wrapper` (`tb_i3ccore`). The launcher is
`tools/dv/run_dv.py --dut i3ccore_wrap` (Verilator default; VCS/Xcelium also
allowed).

## Layout

```
hw/ip/i3ccore_wrap/dv/
├── cocotb/
│   ├── env/                 # i3c_api, test base, constrained-random layers
│   └── tests/               # cocotb test modules
├── docs/                    # TB guide and bring-up notes
├── tb/                      # SV top + coverage interface
├── testlists/               # native TOML (all.toml + block.toml)
├── i3ccore_wrap_sim_cfg.toml
├── build/                   # generated filelists + models (gitignored)
└── README.md
```

Tests import the shared layers through the `env` package, for example
`from env.i3c_test_base import make_env`.

`--dut i3ccore_wrap` is discovered by directory convention
(`hw/ip/i3ccore_wrap/dv/i3ccore_wrap_sim_cfg.toml`); it is not in `duts.toml`.

## Run

Needs Verilator on PATH and a C++20 toolchain (g++ ≥10; e.g.
`source /opt/rh/gcc-toolset-11/enable` on RHEL-8). The launcher bootstraps the
uv `dv` group itself.

```bash
PY=tools/dv/run_dv.py

# List tests / groups
python3 $PY --dut i3ccore_wrap --list

# Smoke subset
python3 $PY --dut i3ccore_wrap --items smoke --tool verilator --stage flist --stage sim

# Full test set
python3 $PY --dut i3ccore_wrap --items all --tool verilator --stage sim

# One module
python3 $PY --dut i3ccore_wrap --items i3c_write_read_sanity --tool verilator --stage sim
```

`test_i3ccore` surveys the whole address map, including unwritten DAT/DCT SRAM
that powers up undefined. cocotb raises on an X read by default, so the module
sets `COCOTB_RESOLVE_X=ZEROS` before importing cocotb. The `xresolve` group
selects that module:

```bash
python3 $PY --dut i3ccore_wrap --items xresolve --tool verilator --stage sim
```

`test_i3ccore` passes on Verilator. `i3c_error_target_abort` (`sre=0`, a
suspected DUT issue) remains the known non-passing item in `--items all`. See
Test Gaps item 9 in `docs/I3C_DV_GUIDE.md`.

Waves come from the launcher rather than a per-TB switch: `--waves` dumps every
selected test, `--waves-on-fail` reruns only the non-passing ones. To view a
dump, use the `viewer_commands` entry the launcher records in the run's
`result.json`, e.g.:

```bash
gtkwave hw/ip/i3ccore_wrap/dv/build/runs/<run>/<module>/waves/<module>.fst
```
