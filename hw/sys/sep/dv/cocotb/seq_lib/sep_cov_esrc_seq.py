# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared frontdoor driver for the ESRC coverage-stimulus tests.

Stimulus only. Nothing here asserts a design contract: it issues legal 32-bit
AXI register accesses on the ESRC aperture and hands back the raw read value.
The only failure it can report is an AXI response that is not OKAY.

Register addresses and field layouts come from the generated SystemRDL export
via ``cocotb/env/sep_reg_meta.py``; no address is retyped here.

Several fields are ``swwel``-gated by ``FIPS_LOCK.LOCK``
(``hw/ip/entropy_source/rtl/entropy_source.sv:757-814``), so a sweep of
``MIN_ENTROPY_H``, ``CTRL``, ``RING_OSC_CTRL`` or
``GENERATOR_n_SAMPLE_CLK_CONFIG`` runs before ``FIPS_LOCK`` is written.
``bring_up_esrc_generators`` deliberately stops short of
``SepEsrcEnableEdnSeq``, which is what writes ``FIPS_LOCK``.
"""

from __future__ import annotations

from sep_reg_meta import ENTROPY_SOURCE, sym

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import SepEsrcConfigSeq, SepEsrcEnableGeneratorsSeq

ESRC_CTRL = sym("ENTROPY_SOURCE_CTRL_REG_ADDR")
ESRC_FIFO_STATUS = sym("ENTROPY_SOURCE_FIFO_STATUS_REG_ADDR")
ESRC_FIFO_RDATA = sym("ENTROPY_SOURCE_FIFO_RDATA_REG_ADDR")
ESRC_RING_OSC_CTRL = sym("ENTROPY_SOURCE_RING_OSC_CTRL_REG_ADDR")
ESRC_MIN_ENTROPY_H = sym("ENTROPY_SOURCE_MIN_ENTROPY_H_REG_ADDR")
ESRC_RECOMMENDED_THRESHOLDS = sym("ENTROPY_SOURCE_RECOMMENDED_THRESHOLDS_REG_ADDR")
ESRC_BIW_OBS_CTRL = sym("ENTROPY_SOURCE_BIW_OBS_CTRL_REG_ADDR")
ESRC_BIW_OBS_STATUS = sym("ENTROPY_SOURCE_BIW_OBS_STATUS_REG_ADDR")
ESRC_BIW_OBS_RDATA = sym("ENTROPY_SOURCE_BIW_OBS_RDATA_REG_ADDR")
ESRC_NOISE_OBS_CTRL = sym("ENTROPY_SOURCE_NOISE_OBS_CTRL_REG_ADDR")
ESRC_NOISE_OBS_STATUS = sym("ENTROPY_SOURCE_NOISE_OBS_STATUS_REG_ADDR")
ESRC_NOISE_OBS_RDATA = sym("ENTROPY_SOURCE_NOISE_OBS_RDATA_REG_ADDR")


# entropy_sampler_clocks has one lane per ring oscillator, and the register
# export carries one GENERATOR_<n>_SAMPLE_CLK_CONFIG per lane. The count comes
# from the export, so a sweep cannot silently cover a subset if the array
# grows.
def _generator_sample_clk_addrs() -> tuple[int, ...]:
    addrs: list[int] = []
    while True:
        name = f"ENTROPY_SOURCE_GENERATOR_{len(addrs)}_SAMPLE_CLK_CONFIG_REG_ADDR"
        try:
            addrs.append(sym(name))
        except (AttributeError, KeyError):
            break
    if not addrs:
        raise KeyError("no GENERATOR_<n>_SAMPLE_CLK_CONFIG registers in the generated export")
    return tuple(addrs)


GENERATOR_SAMPLE_CLK = _generator_sample_clk_addrs()
NUM_LANES = len(GENERATOR_SAMPLE_CLK)

_MIN_ENTROPY_H = ENTROPY_SOURCE.fields("MIN_ENTROPY_H")["H"]
MIN_ENTROPY_H_VALUES = 1 << _MIN_ENTROPY_H["bw"]

_SAMPLE_CLK_DIVIDE = ENTROPY_SOURCE.fields("GENERATOR_0_SAMPLE_CLK_CONFIG")["SAMPLE_CLK_DIVIDE"]
SAMPLE_CLK_DIVIDE_MAX = (1 << _SAMPLE_CLK_DIVIDE["bw"]) - 1

_SAMPLE_CLK_SELECT = ENTROPY_SOURCE.fields("RING_OSC_CTRL")["SAMPLE_CLK_SELECT"]
SAMPLE_CLK_SELECT_ALL = _SAMPLE_CLK_SELECT["bm"]

_OBS_LEVEL = ENTROPY_SOURCE.fields("NOISE_OBS_STATUS")["LEVEL"]
OBS_FIFO_DEPTH = _OBS_LEVEL["bm"]


def obs_level(status: int) -> int:
    """LEVEL field of a NOISE_OBS_STATUS / BIW_OBS_STATUS read."""
    return (status & _OBS_LEVEL["bm"]) >> _OBS_LEVEL["bp"]


def fifo_level(status: int) -> int:
    """LEVEL field of a FIFO_STATUS read."""
    meta = ENTROPY_SOURCE.fields("FIFO_STATUS")["LEVEL"]
    return (status & meta["bm"]) >> meta["bp"]


def noise_obs_ctrl(*, raw_enable: int = 0, flush: int = 0, lane: int = 0) -> int:
    """NOISE_OBS_CTRL value built from the generated field metadata."""
    return ENTROPY_SOURCE.value("NOISE_OBS_CTRL", RAW_ENABLE=raw_enable, FLUSH=flush, LANE_SEL=lane)


class SepCovEsrc(SepAxiRegDriver):
    """32-bit frontdoor register access on the ESRC aperture."""

    _DRIVER_TAG = "COVESRC"

    async def wr(self, addr: int, data: int) -> None:
        await self._wr(addr, data)

    async def rd(self, addr: int) -> int:
        return await self._rd(addr)

    async def drain_obs_fifo(self, status_addr: int, rdata_addr: int) -> int:
        """Pop every word the observe FIFO reports. Returns the pop count.

        The LEVEL read is flow control: it says how many pops the FIFO can
        accept without underflow. The popped values are not inspected.
        """
        level = obs_level(await self._rd(status_addr))
        for _ in range(min(level, OBS_FIFO_DEPTH)):
            await self._rd(rdata_addr)
        return min(level, OBS_FIFO_DEPTH)

    async def drain_entropy_fifo(self) -> int:
        """Pop every word FIFO_STATUS.LEVEL reports, so the FIFO cannot stall."""
        level = fifo_level(await self._rd(ESRC_FIFO_STATUS))
        for _ in range(level):
            await self._rd(ESRC_FIFO_RDATA)
        return level


async def bring_up_esrc_generators(test):
    """Bring SEP up (CPU held off), drive raw noise, configure ESRC, start the
    ring-oscillator generators, and return the noise-driver task.

    Stops before ``SepEsrcEnableEdnSeq``: that sequence writes ``FIPS_LOCK``,
    which turns on ``swwel`` for every certified-configuration field a coverage
    sweep needs to write. The caller kills the returned task before the test
    ends.
    """
    await test.bring_up_no_cpu()
    noise_task = test.start_esrc_noise_driver()
    await test.start_seq(SepEsrcConfigSeq("esrc_config"))
    await test.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
    return noise_task
