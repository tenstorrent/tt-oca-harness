UART Wrapper DV
===============

IP-level cocotb bench for the UART wrapper, running on the unified DV flow
(`tools/dv/run_dv.py`, DUT name `uart_wrap`).

Layout
------

* `uart_wrap_sim_cfg.toml` — flow configuration (build recipe, cocotb
  framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`uart_wrap_tb_top`): the wrapper's
  AXI4-Lite CSR port (`axil_*`) and shared 64-bit log-fetch master port
  (`log_fetch_*`) are exposed flattened for the shared AXI VIP; each UART's
  serial line is its own `uart_rx_<i>`/`uart_tx_<i>` pin pair, and the other
  per-UART pins stay packed one bit per instance. The window bases the tb
  passes to the wrapper come from the generated header in `../regs/gen/svh/`.
* `cocotb/tests/` — test modules; `uart_wrap_base_test.py` carries the shared
  bench helpers: the VIP master, the VIP memory responder on the fetch port,
  one shared UART VIP line driver and sampler per instance, and per-instance
  programming sequences. The instance count, window bases, register
  addresses, field layouts and reset values come from the generated RDL
  header in `../regs/gen/py/`.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `uart` Bender target plus the shared
`axi_rtl`/`common_cells_rtl` dependency targets.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut uart_wrap

# Everything
python3 tools/dv/run_dv.py --dut uart_wrap --items all

# One test with waves
python3 tools/dv/run_dv.py --dut uart_wrap --items uart_wrap_line_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `uart_wrap_sanity_test` — reset defaults in every instance window, a
  cross-instance write/read law (aliasing guard), each `CTRL.UART_EN` on its
  own `uart_en` bit, and the error responders inside and past the instance
  windows.
* `uart_wrap_line_test` — per instance: THR to its own tx pin with the other
  lines idle, rx pin to its own RBR and interrupt bit, and each log engine
  driving its own UART through the shared fetch port.

Expected behavior is taken from the register maps under `../regs/` and the
embedded IPs' documentation. The wrapper is the SMC's UART block
(`--dut smc`, the `smc_uart_*` scenarios).
