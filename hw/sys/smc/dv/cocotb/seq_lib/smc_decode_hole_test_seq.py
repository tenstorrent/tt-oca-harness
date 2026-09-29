# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Accesses to the unmapped tail of three block apertures.

The generated memory map gives the miscellaneous block a 2 KiB aperture, the
GPIO interfaces 4 KiB and the DMA controller 512 B, and each a smaller decoded
extent: misc_wrap's ``SIZE``, ``GPIO_INTF_TOTAL_SIZE`` and the DMA's ``SIZE``.
The crossbars decode each block to that extent, so an address in the tail
between the extent and the end of the aperture reaches no block and the
fabric's error slave answers it (``memmap.adoc``: the fabric refuses an address
past a unit's decoded extent).

For each aperture the leaf seeds a live register near the start of the block,
writes and reads the word halfway through the unmapped tail, and requires the
read to answer DECERR and the write to be refused with an error response, the
live register to still hold its seed and the unmapped read not to return it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    LOCAL_BASE_RESET,
    generated_decoded_extent,
    generated_unit_at,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
AXI_RESP_SLVERR = 2
AXI_RESP_DECERR = 3
# The write refusal the crossbars give: DECERR from the local crossbar, SLVERR
# from the AXI-Lite peripheral and internal crossbars.
_REFUSED = (AXI_RESP_SLVERR, AXI_RESP_DECERR)
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


@dataclass(frozen=True)
class Hole:
    """An unmapped word in a block aperture's tail and a live register below it."""

    name: str
    live_addr: int
    seed: int
    mapped_end: int
    aperture_end: int
    #: Bits of the live register software owns; status fields driven by
    #: hardware are left out of the compares.
    mask: int = 0xFFFF_FFFF

    @property
    def dead_addr(self) -> int:
        """The word halfway through ``[mapped_end, aperture_end)``."""
        return (self.mapped_end + (self.aperture_end - self.mapped_end) // 2) & ~0x3

    def check(self) -> None:
        assert self.live_addr < self.mapped_end <= self.dead_addr < self.aperture_end, (
            f"{self.name}: live 0x{self.live_addr:08x}, mapped end 0x{self.mapped_end:08x}, "
            f"dead 0x{self.dead_addr:08x}, aperture end 0x{self.aperture_end:08x} are out of "
            f"order; the probe definition is wrong, not the DUT"
        )
        assert generated_unit_at(self.dead_addr - LOCAL_BASE_RESET) is None, (
            f"{self.name}: 0x{self.dead_addr:08x} lies inside a unit's decoded extent in the "
            f"generated memory map; the probe definition is wrong, not the DUT"
        )


def _aperture_end(unit: str) -> int:
    return LOCAL_BASE_RESET + generated_window(unit)[1] + 1


def _holes() -> tuple[Hole, ...]:
    misc_base = smc_addr("SMC_TOP_SMC_MISC_WRAP_BASE_ADDR")
    gpio_base = smc_indexed_addr("SMC_TOP_GPIO_INTF_BASE_ADDR", 0)
    dma_base = smc_addr("SMC_TOP_DMA_CTRL_BASE_ADDR")
    assert generated_decoded_extent("smc_misc_wrap") == smc_addr("SMC_TOP_SMC_MISC_WRAP_SIZE")
    assert generated_decoded_extent("dma_ctrl") == smc_addr("SMC_TOP_DMA_CTRL_SIZE")
    return (
        Hole(
            "MISC",
            smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0),
            0x5A5A_5A5A,
            misc_base + smc_addr("SMC_TOP_SMC_MISC_WRAP_SIZE"),
            _aperture_end("smc_misc_wrap"),
        ),
        Hole(
            "GPIO",
            smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 64),
            0x1,
            gpio_base + smc_addr("SMC_TOP_GPIO_INTF_TOTAL_SIZE"),
            _aperture_end("gpio_intf"),
            mask=0x1,
        ),
        Hole(
            "DATA_ACCEL",
            smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR"),
            0x5A5A_5A58,
            dma_base + smc_addr("SMC_TOP_DMA_CTRL_SIZE"),
            _aperture_end("dma_ctrl"),
        ),
    )


class smc_decode_hole_test_seq(SmcCsrSeq):
    """Write and read the unmapped tail of three block apertures."""

    def __init__(self, name: str = "smc_decode_hole_test_seq") -> None:
        super().__init__(name)
        self.results: list[str] = []

    async def _xfer(self, label: str, op: SmcSysAxiOp, addr: int, data: int = 0) -> SmcSysAxiItem:
        item = SmcSysAxiItem(label)
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item

    async def _okay(self, label: str, op: SmcSysAxiOp, addr: int, data: int = 0) -> int:
        item = await self._xfer(label, op, addr, data)
        assert item.resp_code == AXI_RESP_OKAY, (
            f"{label}: 0x{addr:08x} answered {_RESP_NAME.get(item.resp_code, item.resp_code)}; "
            f"it is a mapped register"
        )
        return item.rdata & 0xFFFF_FFFF

    async def _probe(self, hole: Hole) -> None:
        hole.check()
        label = hole.name
        original = await self._okay(f"{label}_LIVE_ORIG", SmcSysAxiOp.READ, hole.live_addr)
        await self._okay(f"{label}_SEED", SmcSysAxiOp.WRITE, hole.live_addr, hole.seed)
        seeded = await self._okay(f"{label}_SEED_RB", SmcSysAxiOp.READ, hole.live_addr)
        seeded &= hole.mask
        payload = ~hole.seed & 0xFFFF_FFFF
        assert seeded == hole.seed, (
            f"{label}: live register 0x{hole.live_addr:08x} reads 0x{seeded:08x} after a write "
            f"of 0x{hole.seed:08x}, so its later readback could not show a stray write"
        )
        dead_wr = await self._xfer(f"{label}_DEAD_WR", SmcSysAxiOp.WRITE, hole.dead_addr, payload)
        dead_rd = await self._xfer(f"{label}_DEAD_RD", SmcSysAxiOp.READ, hole.dead_addr)
        after = await self._okay(f"{label}_LIVE_AFTER", SmcSysAxiOp.READ, hole.live_addr)
        after &= hole.mask
        dead_data = dead_rd.rdata & 0xFFFF_FFFF
        assert dead_rd.resp_code == AXI_RESP_DECERR and dead_wr.resp_code in _REFUSED, (
            f"{label}: unmapped 0x{hole.dead_addr:08x}, past the decoded extent ending "
            f"0x{hole.mapped_end:08x}, answered write "
            f"{_RESP_NAME.get(dead_wr.resp_code, dead_wr.resp_code)} and read "
            f"{_RESP_NAME.get(dead_rd.resp_code, dead_rd.resp_code)}; the fabric decodes no "
            f"block there, so the read has to be DECERR and the write refused"
        )
        assert after == seeded, (
            f"{label}: a write of 0x{payload:08x} to unmapped 0x{hole.dead_addr:08x} changed live "
            f"0x{hole.live_addr:08x} from 0x{seeded:08x} to 0x{after:08x}"
        )
        assert not (dead_rd.resp_code == AXI_RESP_OKAY and dead_data & hole.mask == seeded), (
            f"{label}: unmapped 0x{hole.dead_addr:08x} read back live 0x{hole.live_addr:08x}'s "
            f"seed 0x{seeded:08x}"
        )
        await self._okay(f"{label}_RESTORE", SmcSysAxiOp.WRITE, hole.live_addr, original)
        self.results.append(
            f"{label} dead=0x{hole.dead_addr:08x} "
            f"wr={_RESP_NAME.get(dead_wr.resp_code, dead_wr.resp_code)} "
            f"rd={_RESP_NAME.get(dead_rd.resp_code, dead_rd.resp_code)}/0x{dead_data:08x} "
            f"live=0x{hole.live_addr:08x} held 0x{after:08x}"
        )
        cocotb.log.info(
            "CHK-DECODE-HOLE-%s: an unmapped write and read at 0x%08x, past the decoded "
            "extent ending 0x%08x and inside the aperture ending 0x%08x, were refused and left "
            "live 0x%08x holding its seed 0x%08x without reading it back (write %s, read %s "
            "0x%08x)",
            label,
            hole.dead_addr,
            hole.mapped_end,
            hole.aperture_end,
            hole.live_addr,
            after,
            _RESP_NAME.get(dead_wr.resp_code, dead_wr.resp_code),
            _RESP_NAME.get(dead_rd.resp_code, dead_rd.resp_code),
            dead_data,
        )

    async def body(self) -> None:
        holes = _holes()
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.update(h.dead_addr for h in holes)
        for hole in holes:
            await self._probe(hole)
