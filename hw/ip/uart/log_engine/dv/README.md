Log Engine DV
=============

IP-level cocotb bench for the Log Engine, running on the unified DV flow
(`tools/dv/run_dv.py`, DUT name `log_engine`).

Layout
------

* `log_engine_sim_cfg.toml` — flow configuration (build recipe, cocotb
  framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`log_engine_tb_top`): the DUT's
  AXI4-Lite CSR port (`axil_*`), 64-bit log-fetch master port (`log_fetch_*`)
  and 32-bit log-write master port (`log_write_*`) are exposed flattened for
  the shared AXI VIP; the `uart_tx_ready` pacing input and the `irq` output
  are exposed directly.
* `cocotb/tests/` — test modules; `log_engine_base_test.py` carries the shared
  bench helpers: the VIP master on the CSR port, the VIP memory responder that
  holds the log region on the fetch port, the responder and monitor that
  capture the byte stream on the write port, and the slot geometry derived
  from the region size. Register addresses, field layouts and reset values
  come from the generated RDL header in `../regs/gen/py/`.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `uart` Bender target plus the shared
`axi_rtl`/`common_cells_rtl` dependency targets.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut log_engine

# Everything
python3 tools/dv/run_dv.py --dut log_engine --items all

# One test with waves
python3 tools/dv/run_dv.py --dut log_engine --items log_engine_transfer_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `log_engine_sanity_test` — reset defaults, write/read law with an
  aliasing guard over every writable register, and a single-byte transfer
  through slot 0 to the UART sink address.
* `log_engine_transfer_test` — multi-beat transfers with a partial last
  beat, every slot armed back to back (whole-log ordering on the write port),
  random `uart_tx_ready` pacing, length clamping to the slot capacity, and an
  unaligned region size.
* `log_engine_interrupt_test` — the interrupt test register,
  write-one-to-clear, enable gating, and real fetch and write bus errors
  injected by the responders with recovery through a disable/enable cycle.

Expected behavior is taken from `../doc/architecture.adoc`,
`../doc/programming.adoc` and `../regs/log_engine.rdl`. The engine is also
exercised inside the UART wrappers (`--dut uart_log_engine_wrap`,
`--dut uart_wrap`) and the SMC (`--dut smc`).
