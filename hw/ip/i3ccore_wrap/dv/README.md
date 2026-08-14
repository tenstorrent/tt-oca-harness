<!-- SPDX-License-Identifier: Apache-2.0 -->
# I3C core wrapper block DV

Block-level cocotb TB for `i3ccore_wrapper` (`tb_i3ccore`). Tests live in
`tb/` and are the same modules the VCS `tb/Makefile` runs. The OSS launcher is
`tools/dv/run_dv.py --dut i3ccore_wrap` (Verilator default; VCS/Xcelium also
allowed).

## Layout

```
hw/ip/i3ccore_wrap/dv/
├── tb/                      # SV top + cocotb tests (existing Makefile flow)
├── testlists/               # native TOML (all.toml + block.toml)
├── i3ccore_wrap_sim_cfg.toml
├── build/                   # generated filelists + models (gitignored)
└── README.md
```

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

# Full ALL_TEST_MODULES set
python3 $PY --dut i3ccore_wrap --items all --tool verilator --stage sim

# One module (same name as Makefile MODULE=)
python3 $PY --dut i3ccore_wrap --items i3c_write_read_sanity --tool verilator --stage sim
```

`test_i3ccore` reads unwritten DAT/DCT SRAM. Match the Makefile default:

```bash
COCOTB_RESOLVE_X=ZEROS python3 $PY --dut i3ccore_wrap --items test_i3ccore --tool verilator --stage sim
```

The VCS Makefile (`tb/Makefile`, `make all_tests`) is unchanged and remains
valid for local VCS iteration.
