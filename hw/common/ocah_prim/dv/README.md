<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

AXI-Lite Address Demux DV
=========================

IP-level cocotb bench for `hw/common/ocah_prim/rtl/prim_axil_addr_demux.sv`,
running on the unified DV flow (`tools/dv/run_dv.py`, DUT name
`prim_axil_addr_demux`). The DV root sits outside the `hw/ip/<name>/dv`
convention, so the DUT is registered in `hw/common/dv/configs/duts.toml`.

Layout
------

* `prim_axil_addr_demux_sim_cfg.toml` — flow configuration (build recipe,
  cocotb framework view, run modes). The build makes Verilator's `USERERROR`
  an error, so a range the demux's static checks reject stops the build.
* `tb/tb_top.sv` — pin-level testbench top (`prim_axil_addr_demux_tb_top`).
  One demux holds five ranges in the 4 KiB page at `0xC000_C000`, and its
  AXI4-Lite slave port is exposed as `axil_*` for the shared AXI VIP's
  AXI4-Lite master. Each range is answered by a `prim_axi_lite_err_slv` set to
  OKAY whose read data names the range, and `range_aw_count[i]` counts the
  write addresses range `i` accepts, so a test sees which range a write
  reached:

  | Range | Offset | Size    | Read data     |
  |-------|--------|---------|---------------|
  | 0     | 0x000  | 0x80    | `0x5107_0000` |
  | 1     | 0x080  | 0x80    | `0x5107_0001` |
  | 2     | 0x100  | 0x100   | `0x5107_0002` |
  | 3     | 0x200  | 0x10    | `0x5107_0003` |
  | 4     | 0x800  | 0x200   | `0x5107_0004` |

  Each range is an aligned power of two. Ranges 0 and 1 are back to back,
  range 2 is twice their size, range 3 is small and range 4 sits past a gap.
  Every other address must reach the demux's own responder: DECERR, read data
  `0xBADCAB1E`, and no range counts the write.
* `cocotb/tests/` — test modules; `addr_demux_base_test.py` carries the range
  table, the expected response and range for any address, and the clock,
  reset and VIP bring-up.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `prim_axil_addr_demux` Bender target plus the
shared `axi_rtl`/`common_cells_rtl` dependency targets.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut prim_axil_addr_demux

# Everything
python3 tools/dv/run_dv.py --dut prim_axil_addr_demux --items all --tool verilator
```

Each test's log and `results.xml` land in the `logs/` and `results/`
directories under `build/runs/<run>/<test>@default/seed_<seed>/attempt_<n>/`.

Tests
-----

Every write is checked for its response and for the range that counted it.
Each test issues all its writes to a set of addresses before reading them
back, so neither channel's decode can pass on the address the other channel
last carried.

* `addr_demux_smoke_test` — the first and last word of every range (OKAY, the
  range's read data), the words on either side of every range and the last
  word of the page, which include the first and last word of every gap (OKAY
  where that word is in another range, otherwise DECERR with read data
  `0xBADCAB1E`).
* `addr_demux_sweep_test` — every word of the ranges' page and of the pages
  either side of it, then 512 random words across the 32-bit space; the
  testlist runs it with three seeds.
