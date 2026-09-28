UART 16550 DV
=============

IP-level cocotb bench for the UART 16550, running on the unified DV flow
(`tools/dv/run_dv.py`, DUT name `uart_16550`).

Layout
------

* `uart_16550_sim_cfg.toml` — flow configuration (build recipe, cocotb
  framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`uart_16550_tb_top`): the DUT's
  AXI4-Lite CSR port is exposed as flattened `axil_*` pins for the shared AXI
  VIP's AXI4-Lite master; the serial line, modem, DMA-ready, error and
  interrupt pins are exposed directly.
* `cocotb/tests/` — test modules; `uart_16550_base_test.py` carries the shared
  bench helpers: the line format model, the shared UART VIP's line driver on
  `rx` and sampler on `tx`, and the register access surface. Register
  addresses, field layouts and reset values come from the generated RDL
  headers in `../regs/gen/py/`.
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).
* `lint/` — Verilator and lint waivers for the UART RTL.

The RTL closure comes from the `uart` Bender target plus the shared
`axi_rtl`/`common_cells_rtl` dependency targets.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut uart_16550

# Everything
python3 tools/dv/run_dv.py --dut uart_16550 --items all

# One test with waves
python3 tools/dv/run_dv.py --dut uart_16550 --items uart_16550_fifo_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `uart_16550_sanity_test` — reset defaults, scratch register write/read law,
  TX and RX bring-up through the line engines, system loopback with a random
  line format including the modem fold-back, and the interrupt test register
  raising every source.
* `uart_16550_fifo_test` — TX and RX FIFO bursts, and DMA-ready pacing in
  mode 0 and mode 1 through the loopback.
* `uart_16550_modem_test` — modem control outputs, modem status and delta
  bits, and line loopback of the serial line and modem pins.
* `uart_16550_interrupt_test` — layered interrupt priority with the RX
  trigger level and reception timeout, and receiver line errors (stick parity,
  break).

Expected behavior is taken from `../doc/architecture.adoc` and the three
register maps under `../regs/`. The UART is also exercised inside the SMC
(`--dut smc`, the `smc_uart_*` scenarios).
