# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""
ocah_entropy_vip — OCAH AXI-Stream entropy BFM for SEP TRNG DV.

This package provides a configurable entropy stream driver and a passive
monitor for the SEP external TRNG AXI-Stream path.

Primary exports
---------------
OcahEntropySource
    Drives ``ext_trng_axis_req_i`` / ``ext_trng_axis_rsp_o`` and can assert
    ``ext_trng_irq_i`` / ``ext_trng_alarm_i``.
    Deterministic by default; random mode requires an explicit ``enable_random()``
    call with a fixed seed.

OcahEntropyMonitor
    Passive observer that counts handshakes and records entropy words, IRQ, and
    alarm events from the same signals.

Quick-start — deterministic mode (default)
------------------------------------------
::

    from ocah_entropy_vip import OcahEntropySource, OcahEntropyMonitor

    @cocotb.test()
    async def test_entropy_consumed(dut):
        clk = Clock(dut.clk_i, 10, units="ns")
        cocotb.start_soon(clk.start())

        src = OcahEntropySource(
            dut.clk_i,
            dut=dut,                 # uses standard ext_trng_axis_req_i_* names
            name="entropy_src",
        )
        mon = OcahEntropyMonitor(
            dut.clk_i,
            dut=dut,
            name="entropy_mon",
        )

        src.init_signals()            # drives tvalid=0, tdata=0xDEAD_BEEF, irq=0, alarm=0
        await src.start()
        await mon.start()

        # ... run DUT and wait for entropy to be consumed ...

        await src.stop()
        await mon.stop()

        words = mon.get_words()
        assert 0xDEAD_BEEF in words   # default deterministic word was consumed

Quick-start — PRNG mode (opt-in)
---------------------------------
::

        src.enable_random(seed=0xA5A5_0001)  # explicit seed required
        await src.start()

Quick-start — IRQ / alarm injection
-------------------------------------
::

        await src.inject_irq(duration_cycles=4)
        await src.inject_alarm(duration_cycles=1)

See ``examples/example_deterministic_entropy.py`` for a more complete example.

Plusargs
--------
``+sep_entropy_word=<hex>``
    32-bit hex word used as the default entropy value.  Default ``0xDEAD_BEEF``.
    Sampled at construction time.
``+sep_entropy_seed=<N>``
    If present, ``enable_random()`` is called automatically during ``start()``
    with this seed.  Takes precedence over the default single-word mode.
``+sep_entropy_pattern=<file>``
    Path to a text file containing one hex word per line.  If present,
    ``set_pattern()`` is called automatically with the file contents during
    ``start()``.

Note: the BFM reads these plusargs from ``COCOTB_PLUSARG_*`` environment
variables (the standard cocotb plusarg forwarding convention).  When a
simulator runner does not forward plusargs as environment variables, pass
the values programmatically through the Python API instead.
"""

from .ocah_entropy_source import OcahEntropySource, OcahEntropySourceError
from .ocah_entropy_monitor import OcahEntropyMonitor

__all__ = [
    "OcahEntropySource",
    "OcahEntropyMonitor",
    "OcahEntropySourceError",
]

__version__ = "0.1.0"
