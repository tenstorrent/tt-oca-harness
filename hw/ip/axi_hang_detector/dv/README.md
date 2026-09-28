AXI Hang Detector DV
====================

IP-level cocotb bench for the AXI Hang Detector, running on the unified DV flow
(`tools/dv/run_dv.py`, DUT name `axi_hang_detector`).

Layout
------

* `axi_hang_detector_sim_cfg.toml` — flow configuration (build recipe, cocotb
  framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`axi_hang_detector_tb_top`). The IP
  has no CSR block of its own, so the configuration fields and the AXI snoop
  probes are exposed directly as pins for cocotb stimulus and observation; the
  bench needs no bus VIP.
* `cocotb/tests/` — test modules; `ahd_base_test.py` carries the shared bench
  helpers (clock/reset bring-up, the config drivers, and the snoop stimulus).
* `testlists/all.toml` — testlist and groups (`smoke`, `all`).

The RTL closure is `axi_hang_detector.sv` plus the `prim_axi_snoop.sv` it
instantiates, from the `axi_hang_detector` Bender target. There is no register
model: the detector's config fields live in `cpu_ctrl` at the SMC level, and the
bench drives them as wires.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut axi_hang_detector

# Everything
python3 tools/dv/run_dv.py --dut axi_hang_detector --items all

# One test with waves
python3 tools/dv/run_dv.py --dut axi_hang_detector --items ahd_sanity_test --waves
```

Verilator is the default tool; VCS and Xcelium are available where licensed.

Tests
-----

* `ahd_sanity_test` — core datapath walk: read hang fires at the threshold and
  holds (`irq_o` is a level, not a pulse), a completion drops it, an outstanding
  write fires the same way, and reset clears it.
* `ahd_config_corners_test` — `threshold = 0` disables timeout detection,
  `threshold = 1` fires on a single stalled cycle, and `irq_en = 0` runs the
  counter with `irq_o` gated low.
* `ahd_threshold_latch_test` — the threshold is latched when a stall window
  starts, so a mid-window write fires at the latched value and takes effect only
  on the next window.
* `ahd_threshold_zero_rearm_test` — re-arming out of `threshold = 0`, where the
  fired condition comes from the armed latch rather than the counter, plus
  `irq_test` staying live while detection is off.
* `ahd_bus_progress_test` — negative control: a busy bus with a completion every
  fewer-than-threshold cycles never times out.

Expected behaviour is taken from `../README.md`.

Scope
-----

This suite covers the timeout-counter datapath, which is hard to reproduce at the
system level. The `cpu_ctrl` configuration path, real bus stalls on the SMC
fabrics, the OR into the safety-island fault line, and the PLIC route are covered
by the `smc_hang_detector_*` tests in `hw/sys/smc/dv/testlists/irq.toml`.
