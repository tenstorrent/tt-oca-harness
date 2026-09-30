# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Write bursts that run past a block's extent, for sep_fabric_burst_wrap_test.

``hw/sys/sep/doc/memory_map.adoc`` says the fabric refuses an address past
the extent a unit allocates, and that such an access never reaches a unit.
AXI routes a burst on its first address only. A write burst that starts in a
block's last live word is routed wholly to that block, and its later beats
land past ``REG_MAP_SIZE``. Those beats must not reach the unit, so no live
register in the block may change.

Each anchor names one block and one writable target register from the
generated SystemRDL export. The burst starts on the last live word and ends
at ``base + span + offset(target)``, where ``span`` is the smallest power of
two above the allocated size. The final beat carries a value that differs
from the target's current value; every other beat past the extent carries
zero, and every beat inside the extent writes back the value it read. A
correct fabric therefore leaves every watched register as it was, whatever
the response. The anchor is stimulus only: the verdict compares the block's
own registers before and after, so it does not depend on how the block
decodes addresses.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import SEP_RESET_CTRL, WDT_TIMER, RegBlock, block_size, sym

from seq_lib.sep_axi_access_seq import (
    SepAxiAccessSeq,
    capture_addr_handshake,
    take_handshake,
)
from seq_lib.sep_fabric_deadspace_seq import DeadWindow, SepDeadspace, _sep_watch

RESP_OKAY = 0
RESP_DECERR = 3
BURST_INCR = 1

SECURE_DMA = RegBlock("SECURE_DMA")


@dataclass(frozen=True)
class WrapAnchor:
    """One write burst from a block's last live word past its extent."""

    window: DeadWindow
    target: str  # RDL register name inside the block
    target_addr: int
    flip_mask: int  # software-writable bits the final beat toggles
    size: int  # AxSIZE

    @property
    def beat_bytes(self) -> int:
        return 1 << self.size

    @property
    def span(self) -> int:
        """Smallest power of two above the allocated size."""
        return 1 << self.window.alloc.bit_length()

    @property
    def start(self) -> int:
        return self.window.base + self.window.alloc - self.beat_bytes

    @property
    def end_addr(self) -> int:
        """Address of the final beat."""
        return self.window.base + self.span + (self.target_addr - self.window.base)

    @property
    def beats(self) -> int:
        return (self.end_addr - self.start) // self.beat_bytes + 1


def _window(name: str, block: str) -> DeadWindow:
    base = sym(f"{block}_REG_MAP_BASE_ADDR")
    alloc = block_size(block)
    # Window end is the 4 KB aperture memory_map.adoc gives each of these blocks.
    return DeadWindow(name, base, base + 0x1000, alloc, _sep_watch(base, alloc))


def wrap_anchors() -> tuple[WrapAnchor, ...]:
    rst = _window("sep_reset_ctrl", "SEP_RESET_CTRL")
    wdt = _window("wdt_timer", "WDT_TIMER")
    dma = _window("secure_dma", "SECURE_DMA")
    return (
        # SW_RESET_N is one 64-bit register; the burst uses full-width beats.
        # The final beat toggles only the AES reset request, which this test
        # does not need, and restore() puts it back.
        WrapAnchor(
            rst,
            "SW_RESET_N",
            SEP_RESET_CTRL.addr("SW_RESET_N"),
            SEP_RESET_CTRL.field_mask("SW_RESET_N", "aes_sw_rst_n"),
            3,
        ),
        # WKUP_THOLD_HI is a plain threshold with the wakeup timer disabled.
        WrapAnchor(
            wdt,
            "WKUP_THOLD_HI",
            WDT_TIMER.addr("WKUP_THOLD_HI"),
            WDT_TIMER.mask32("WKUP_THOLD_HI"),
            2,
        ),
        # SRC_ADDR_LO is a plain address register with no DMA started.
        WrapAnchor(
            dma,
            "SRC_ADDR_LO",
            SECURE_DMA.addr("SRC_ADDR_LO"),
            SECURE_DMA.mask32("SRC_ADDR_LO"),
            2,
        ),
    )


class SepBurstWrap:
    """Control write, then the burst, then the block's registers compared."""

    def __init__(self, test) -> None:
        self.test = test
        self.dead = SepDeadspace(test)

    async def _access(self, op: SepAxiOp, addr: int, *, wdata: int = 0, length: int = 4):
        seq = SepAxiAccessSeq(
            f"wrap_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=length,
            size=2 if length == 4 else None,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & ((1 << (8 * length)) - 1), seq.timed_out

    async def snapshot(self, a: WrapAnchor) -> dict[int, int]:
        return await self.dead.snapshot(a.window)

    async def control(self, a: WrapAnchor, snap: dict[int, int]) -> str | None:
        """The target register stores a single-beat write and reads it back.

        Without this the no-change compare would also pass on a register that
        cannot change. The original value is written back before returning.
        """
        old = snap[a.target_addr]
        marker = old ^ a.flip_mask
        resp_w, _d, to_w = await self._access(SepAxiOp.WRITE, a.target_addr, wdata=marker)
        resp_r, got, to_r = await self._access(SepAxiOp.READ, a.target_addr)
        await self._access(SepAxiOp.WRITE, a.target_addr, wdata=old)
        resp_b, back, to_b = await self._access(SepAxiOp.READ, a.target_addr)
        if to_w or to_r or to_b or resp_w != RESP_OKAY or resp_r != RESP_OKAY:
            return (
                f"{a.target} control access failed: write resp={resp_w} read "
                f"resp={resp_r} timed_out={to_w or to_r or to_b}"
            )
        if got != marker:
            return (
                f"{a.target} single-beat write of 0x{marker:08x} read back "
                f"0x{got:08x}; the register cannot show a change"
            )
        if resp_b != RESP_OKAY or back != old:
            return f"{a.target} did not return to 0x{old:08x} (read 0x{back:08x})"
        return None

    def burst_data(self, a: WrapAnchor, snap: dict[int, int]) -> bytes:
        """In-extent beats write back what they read; past it, zero; the last beat toggles."""
        out = bytearray()
        bb = a.beat_bytes
        for i in range(a.beats):
            addr = a.start + i * bb
            if addr < a.window.dead_lo:
                word = 0
                for lane in range(0, bb, 4):
                    word |= snap.get(addr + lane, 0) << (8 * lane)
            elif i == a.beats - 1:
                word = snap[a.target_addr] ^ a.flip_mask
            else:
                word = 0
            out += word.to_bytes(bb, "little")
        return bytes(out)

    async def burst(self, a: WrapAnchor, snap: dict[int, int]) -> tuple[int, bool, str | None]:
        """BRESP, timeout flag, and a stimulus miss (None when the pins match)."""
        data = self.burst_data(a, snap)
        mon = self.test.env.axi_monitor
        # One BRESP covers the burst. Credit it in case the fabric refuses with
        # DECERR, and hand the credit back when it does not.
        mon.arm_expected_decerr(1)
        aw_task = cocotb.start_soon(capture_addr_handshake("aw"))
        seq = SepAxiAccessSeq(
            f"wrap_burst_0x{a.start:08x}",
            op=SepAxiOp.WRITE,
            addr=a.start,
            wdata=int.from_bytes(data, "little"),
            length=len(data),
            size=a.size,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        if seq.timed_out or seq.resp_code != RESP_DECERR:
            mon.release_expected_decerr(1)
        aw = take_handshake(aw_task)
        want = {"addr": a.start, "len": a.beats - 1, "size": a.size, "burst": BURST_INCR}
        if aw is None:
            miss = "no AW handshake seen on the port"
        elif aw != want:
            miss = f"AW carried {aw}, expected {want}"
        else:
            miss = None
        return seq.resp_code, seq.timed_out, miss

    async def changed(self, a: WrapAnchor, snap: dict[int, int]) -> tuple[dict, list[str]]:
        """Watched registers whose value moved, and any that could not be read."""
        moved: dict[int, tuple[int, int]] = {}
        unread: list[str] = []
        for addr, old in snap.items():
            resp, val, to = await self._access(SepAxiOp.READ, addr)
            if to or resp != RESP_OKAY:
                unread.append(f"+0x{addr - a.window.base:x} resp={resp} timed_out={to}")
            elif val != old:
                moved[addr] = (old, val)
        return moved, unread

    async def restore(self, a: WrapAnchor, snap: dict[int, int]) -> None:
        await self.dead.restore(a.window, snap)


def _selftest() -> None:
    anchors = wrap_anchors()
    assert {a.window.name for a in anchors} == {"sep_reset_ctrl", "wdt_timer", "secure_dma"}
    for a in anchors:
        w = a.window
        assert w.base <= a.target_addr < w.dead_lo, f"{a.target} is outside {w.name}'s extent"
        assert a.start < w.dead_lo <= a.end_addr, f"{w.name} burst does not cross its extent"
        assert a.end_addr - a.start < 0x1000 - (a.start & 0xFFF), f"{w.name} burst crosses 4 KB"
        assert 2 <= a.beats <= 256, f"{w.name} burst has {a.beats} beats"
        assert a.flip_mask != 0, f"{a.target} has no writable bit to toggle"
        assert a.target_addr in w.watch, f"{a.target} is not in {w.name}'s watch set"


_selftest()
