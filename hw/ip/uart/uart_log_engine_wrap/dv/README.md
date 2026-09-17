UART and Log Engine Wrapper DV
==============================

IP-level cocotb bench for the UART and Log Engine wrapper, running on the
unified DV flow (`tools/dv/run_dv.py`, DUT name `uart_log_engine_wrap`).

Layout
------

* `uart_log_engine_wrap_sim_cfg.toml` — flow configuration (build recipe,
  cocotb framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`uart_log_engine_wrap_tb_top`):
  the wrapper's AXI4-Lite CSR port (`axil_*`) and 64-bit log-fetch master port
  (`log_fetch_*`) are exposed flattened for the shared AXI VIP; the serial
  line, `uart_en`, modem, DMA-ready, error and interrupt pins are exposed
  directly. The window bases the tb passes to the wrapper come from the
  generated header in `../regs/gen/svh/`.
* `cocotb/tests/` — test modules; `uart_log_engine_wrap_base_test.py` carries
  the shared bench helpers: the VIP master, the VIP memory responder on the
  fetch port, the shared UART VIP's line driver and sampler, and the
  programming sequences for the embedded UART and log engine. Register
  addresses, field layouts and reset values come from the generated RDL header
  in `../regs/gen/py/`.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure comes from the `uart` Bender target plus the shared
`axi_rtl`/`common_cells_rtl` dependency targets.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut uart_log_engine_wrap

# Everything
python3 tools/dv/run_dv.py --dut uart_log_engine_wrap --items all

# One test with waves
python3 tools/dv/run_dv.py --dut uart_log_engine_wrap --items uart_log_engine_wrap_log_path_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `uart_log_engine_wrap_sanity_test` — reset defaults in every window, a
  cross-window write/read law (aliasing guard), `CTRL.UART_EN` on the
  `uart_en` pin, and the error responder on unmapped addresses.
* `uart_log_engine_wrap_log_path_test` — logs fetched over the fetch port and
  written by the embedded log engine into the embedded UART leave the wrapper
  on `uart_tx` byte-exact, alone, under concurrent CSR traffic on the UART
  port, and from several slots.

Expected behavior is taken from `../doc/uart_log_engine_wrap.adoc` and the
register maps under `../regs/`. The wrapper is also exercised inside the UART
wrapper (`--dut uart_wrap`) and the SMC (`--dut smc`).
