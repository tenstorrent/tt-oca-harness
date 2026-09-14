# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import random

import cocotb
from cocotb.triggers import RisingEdge

from test.test_base import *
from test.test_config import DEFAULT_CONFIG


@cocotb.test()
async def test_apb_random(dut):
    """
    Perform random APB write/read transactions with configurable parameters.

    Address constraints:
      - avoid page register and keep word-aligned
      - range from config: addr_min..addr_max step addr_step

    Configuration (from DEFAULT_CONFIG):
      - Decorrelator Mode: DECOR_29 (29-deep XOR decorrelator, spec default)
      - APB Clock: 100 MHz
      - RO Sample Clock: 142.9 MHz
      - RO Model Injection: ENABLED (default)
      - Random Iterations: configurable via cfg.apb_random_iterations

    Configuration Flow:
      1. init() configures all models from test_config.py
      2. ro_model_randomize_all() sets per-lane RO parameters
      3. Test enables RO model and observes decorrelator outputs
    """
    cfg = DEFAULT_CONFIG

    dut._log.info("=" * 70)
    dut._log.info(
        f"Test Config: APB {cfg.clock.apb_freq_mhz:.1f} MHz, RO {cfg.clock.rosc_freq_mhz:.1f} MHz, "
        f"RO Inject: {'ON' if cfg.ro.inject_enabled else 'OFF'}"
    )
    dut._log.info("=" * 70)

    # Initialize with default clocks and reset (configures all models from cfg)
    apb, mon = await init(dut, config=cfg)

    # Configure all RO lanes with randomized parameters
    await ro_model_randomize_all(dut, config=cfg)

    # Perform random APB transactions within implemented RTL address range
    for i in range(cfg.apb_random_iterations):
        # Use addr_max (inclusive) with exclusive upper bound = addr_max + step
        upper_excl = cfg.apb.addr_max + cfg.apb.addr_step
        addr = random.randrange(cfg.apb.addr_min, upper_excl, cfg.apb.addr_step)
        data = random.getrandbits(cfg.apb.data_width)
        await apb_write(apb, addr, data)
        await apb_compare(dut, apb, addr, data)

    # Enable RO model free-run and observe decorrelator outputs for a while
    await ro_model_enable(dut, True)
    dut._log.info("Enabled RO model free-run; observing decorrelator output...")

    # If decorrelator is present, log a few HW bytes for observation
    if hasattr(dut, "entropy_bytes_vld") and hasattr(dut, "entropy_bytes_flat"):
        # Drop first pulse to align PY/HW sampling windows
        await RisingEdge(dut.entropy_bytes_vld)
        for _ in range(cfg.decorrelator_samples):
            await RisingEdge(dut.entropy_bytes_vld)
            try:
                packed = int(dut.entropy_bytes_flat.value)
                hw_bytes = [(packed >> (8 * i)) & 0xFF for i in range(cfg.ro.num_lanes)]
            except Exception:
                hw_bytes = []
            dut._log.info(
                "Decorrelator HW bytes: [" + ", ".join(f"0x{b:02X}" for b in hw_bytes) + "]"
            )
    else:
        # Fallback: just wait on the RO sample clock for some cycles
        for _ in range(cfg.fallback_wait_cycles):
            await RisingEdge(dut.rosc_sample_clk)
