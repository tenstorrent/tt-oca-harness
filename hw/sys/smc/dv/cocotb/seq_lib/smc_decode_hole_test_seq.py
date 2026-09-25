# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Accesses to the unmapped tail of three block windows.

The peripheral crossbar hands the miscellaneous block the 2 KB from
0xC000_2800 and the GPIO padring the 4 KB from 0xC000_3000, and the local
crossbar hands the data accelerator the 4 KB from 0xC003_8000. The generated
map fills only the start of each: the miscellaneous registers end with
`NDM_RESET` at 0xC000_2A0C, the 65 GPIO interfaces at 0xC000_3410, and the
zeroer registers after the DMA's at 0xC003_8218. Each block decodes its own
window again, and no enrolled leaf reaches the part beyond the last mapped
register, where each of those decodes chooses its default.

For each window the leaf seeds a live register near the start of the block,
writes and reads an address in the unmapped tail, and requires the live
register to still hold its seed and the unmapped read not to return it. The
responses to the unmapped accesses are recorded, not asserted: no document
fixes which error, if any, an unmapped offset inside a block window returns.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

AXI_RESP_OKAY = 0
_RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}


#: The data accelerator sends every address outside its zeroer registers to
#: the DMA, whose register port keeps nine address bits, so a tail address
#: reaches the DMA at its offset modulo 0x200. This one lands at 0x138, past
#: the DMA's last register, rather than on a live DMA register (issue #585
#: covers the aliasing).
DATA_ACCEL_HOLE_OFFSET = 0x338


@dataclass(frozen=True)
class Hole:
    """An unmapped address inside a block window and a live register below it."""

    name: str
    live_addr: int
    seed: int
    dead_addr: int
    mapped_end: int
    window_end: int
    #: Bits of the live register software owns; status fields driven by
    #: hardware are left out of the compares.
    mask: int = 0xFFFF_FFFF

    def check(self) -> None:
        assert self.live_addr < self.mapped_end <= self.dead_addr < self.window_end, (
            f"{self.name}: live 0x{self.live_addr:08x}, mapped end 0x{self.mapped_end:08x}, "
            f"dead 0x{self.dead_addr:08x}, window end 0x{self.window_end:08x} are out of order; "
            f"the probe definition is wrong, not the DUT"
        )


def _holes() -> tuple[Hole, ...]:
    misc_base = smc_addr("SMC_TOP_SMC_MISC_WRAP_BASE_ADDR")
    gpio_base = smc_indexed_addr("SMC_TOP_GPIO_INTF_BASE_ADDR", 0)
    dma_base = smc_addr("SMC_TOP_DMA_CTRL_BASE_ADDR")
    return (
        Hole(
            "MISC",
            smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0),
            0x5A5A_5A5A,
            misc_base + 0x400,
            misc_base + smc_addr("SMC_TOP_SMC_MISC_WRAP_SIZE"),
            misc_base + 0x800,
        ),
        Hole(
            "GPIO",
            smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 64),
            0x1,
            gpio_base + 0x800,
            gpio_base + smc_addr("SMC_TOP_GPIO_INTF_TOTAL_SIZE"),
            gpio_base + 0x1000,
            mask=0x1,
        ),
        Hole(
            "DATA_ACCEL",
            smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR"),
            0x5A5A_5A58,
            dma_base + DATA_ACCEL_HOLE_OFFSET,
            smc_addr("SMC_TOP_ZEROER_CTRL_BASE_ADDR") + smc_addr("SMC_TOP_ZEROER_CTRL_SIZE"),
            dma_base + 0x1000,
        ),
    )


class smc_decode_hole_test_seq(SmcCsrSeq):
    """Write and read the unmapped tail of three block windows."""

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
            "CHK-DECODE-HOLE-%s: an unmapped write and read at 0x%08x, past the last mapped "
            "register at 0x%08x and inside the block window ending 0x%08x, left live "
            "0x%08x holding its seed 0x%08x and did not read it back (write %s, read %s "
            "0x%08x)",
            label,
            hole.dead_addr,
            hole.mapped_end,
            hole.window_end,
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
