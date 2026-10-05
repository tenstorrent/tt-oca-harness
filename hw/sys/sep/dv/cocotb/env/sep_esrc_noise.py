# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raw noise driver for the SEP entropy source.

`+esrc_noise_force` (tb_top.sv) forces each decorrelator's `noise_i` from the
`esrc_noise_ext_i` port -- it does NOT generate anything. The port is an input,
and `sep_base_test` pins it to 0, so the plusarg on its own supplies a constant
zero: the repetition health test trips on the first window, `MAIN_SM_STATUS.ALERT`
latches, and `BOOT_PHASE_DONE` never asserts. A ROM that brings the entropy chain
up correctly then correctly refuses to boot.

`SepDrbgScoreboard` also drives this port, but no ROM test instantiates it (it
brings a bit-exact golden chain that a ROM boot cannot predict). This
module is the small piece those tests actually need: the same
`EntropyNoiseModel` generator, driven into the port, with no golden and no checking.

Update rate: the decorrelator samples `noise_i` on its divided sample clock, so
the port only has to change faster than that to look random downstream. The ROM
programs `SAMPLE_CLK_DIV` to divide by 64 (`sep_entropy.c`), so an update every
`interval` cycles with `interval` well under 64 gives every sample a fresh value.
At the default interval of 8, driving every cycle costs 8x the Python callbacks.
"""

from __future__ import annotations

from cocotb.triggers import ClockCycles
from models.entropy_noise_model import EntropyNoiseModel

# Comfortably under the ROM's /64 decorrelator sample period, so each sample sees
# a value the previous one did not.
DEFAULT_INTERVAL = 8


async def esrc_noise_task(
    dut,
    *,
    mode: str = "unbiased",
    seed_base: int = 0x1234_5678,
    interval: int = DEFAULT_INTERVAL,
    logger=None,
):
    """Drive `esrc_noise_ext_i` with reproducible pseudo-random noise, forever.

    Runs until the test ends (start with `cocotb.start_soon`). `seed_base` makes
    it deterministic: the same seed replays the same noise, so a health-test
    failure is reproducible rather than a new sequence each run.
    """
    if not hasattr(dut, "esrc_noise_ext_i"):
        if logger:
            logger.warning("no esrc_noise_ext_i port; entropy source will see no noise")
        return

    gen = EntropyNoiseModel()
    gen.configure(mode, seed_base=seed_base)
    if logger:
        logger.info(
            "ESRC noise: mode=%s seed_base=0x%08x every %d cycles", mode, seed_base, interval
        )

    while True:
        dut.esrc_noise_ext_i.value = gen.step_all()
        await ClockCycles(dut.clk_i, interval)
