# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy-pool aperture driver (sep_entropy_pool_aperture_test).

64-bit AXI-Lite drain of ``sep_entropy_fifo`` at the local-xbar
``entropy_fifo.main`` window. Offsets from ``hw/sys/sep/rtl/sep_entropy_fifo.sv``:
status ``0x00``, irq-cause ``0x08``, pop ``0x10``; every other in-window offset
and every write is SLVERR. Depth=32, LowWatermark=8, StallThresh=4096.
"""

from __future__ import annotations

import re
from pathlib import Path

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from sep_reg_meta import ENTROPY_SOURCE

from seq_lib.sep_esrc_bringup_seq import EDN_CTRL, EDN_CTRL_AUTO, ESRC_CTRL

_XBAR = Path(__file__).resolve().parents[3] / "rtl" / "crossbars" / "sep_local_axi_xbar.sv"
_FIFO = Path(__file__).resolve().parents[3] / "rtl" / "sep_entropy_fifo.sv"


def _xbar_entropy_fifo_base() -> int:
    text = _XBAR.read_text()
    m = re.search(r"entropy_fifo\.main:\s*0x([0-9A-Fa-f]+)", text)
    if not m:
        raise RuntimeError(f"entropy_fifo.main base not found in {_XBAR}")
    return int(m.group(1), 16)


def _fifo_param(name: str) -> int:
    text = _FIFO.read_text()
    m = re.search(rf"parameter int unsigned {name}\s*=\s*(\d+)", text)
    if not m:
        raise RuntimeError(f"{name} not found in {_FIFO}")
    return int(m.group(1))


POOL_BASE = _xbar_entropy_fifo_base()
POOL_STATUS = POOL_BASE + 0x00
POOL_IRQ_CAUSE = POOL_BASE + 0x08
POOL_POP = POOL_BASE + 0x10
FIFO_DEPTH = _fifo_param("FifoDepth")
LOW_WATERMARK = _fifo_param("LowWatermark")
STALL_THRESH = _fifo_param("StallThresh")

RESP_OKAY = 0
RESP_SLVERR = 2

IRQ_POOL_LOW = 36
IRQ_FILL_STALL = 37

# 8-byte-aligned in-window offsets that are not the three live registers.
_UNMAPPED = (0x18, 0x20, 0x28, 0x40, 0x80, 0x100, 0x1000, 0x8000)

# Legal disable: MODULE_ENABLE=0, every other CTRL field at its reset (including
# SHA256_WHITENING_ENABLE=1). A hand-cleared multi-bit field is an alert.
ESRC_CTRL_DISABLE = ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=0)
# EDN_CTRL mubi4: True=0x6, False=0x9. AUTO bring-up is 0x9666 (ENABLE=T).
# MODULE_ENABLE=0 does not drop AUTO-mode EDN acks while CSRNG still has a
# seed, so fill-stall needs EDN_ENABLE=False to leave the pool request
# outstanding without ack.
EDN_CTRL_DISABLE = (EDN_CTRL_AUTO & ~0xF) | 0x9


class SepEntropyPoolCfg:
    """RANDCFG: extra accepted pops past the watermark, and the unmapped offset."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.extra_pops = rng.randrange(1, 5)
        self.unmapped_off = rng.choice(_UNMAPPED)

    def summary(self) -> str:
        return (
            f"seed={self.seed} extra_pops={self.extra_pops} "
            f"unmapped=0x{self.unmapped_off:x}"
        )


class SepEntropyPool(SepAxiRegDriver):
    """64-bit beats on the pool aperture; ESRC_CTRL writes stay 32-bit."""

    _DRIVER_TAG = "POOL"

    async def access(
        self,
        addr: int,
        *,
        write: bool = False,
        wdata: int = 0,
        expect_error: bool = False,
    ) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(
            f"pool_{'wr' if write else 'rd'}_0x{addr:08x}",
            op=SepAxiOp.WRITE if write else SepAxiOp.READ,
            addr=addr,
            wdata=wdata,
            length=8,
            size=None,
            expect_error=expect_error,
        )
        await self.test.start_seq(seq)
        return seq

    async def status(self) -> int:
        seq = await self.access(POOL_STATUS)
        if seq.resp_code != RESP_OKAY:
            raise AssertionError(f"pool status resp={seq.resp_code}, expected OKAY")
        return seq.rdata

    async def irq_cause(self) -> int:
        seq = await self.access(POOL_IRQ_CAUSE)
        if seq.resp_code != RESP_OKAY:
            raise AssertionError(f"pool irq-cause resp={seq.resp_code}, expected OKAY")
        return seq.rdata

    async def disable_esrc(self) -> None:
        await self._wr(ESRC_CTRL, ESRC_CTRL_DISABLE)

    async def enable_esrc(self) -> None:
        await self._wr(ESRC_CTRL, ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=1))

    async def disable_edn(self) -> None:
        await self._wr(EDN_CTRL, EDN_CTRL_DISABLE)

    async def enable_edn(self) -> None:
        await self._wr(EDN_CTRL, EDN_CTRL_AUTO)


def _selftest() -> None:
    assert POOL_BASE == 0x1095_0000
    assert FIFO_DEPTH == 32
    assert LOW_WATERMARK == 8
    assert STALL_THRESH == 4096
    cfg = SepEntropyPoolCfg(1)
    assert cfg.unmapped_off in _UNMAPPED
    assert 1 <= cfg.extra_pops <= 4
    # Disable keeps whitening at reset-1 and only clears MODULE_ENABLE.
    assert ENTROPY_SOURCE.value("CTRL") & ~0x2 == ESRC_CTRL_DISABLE
    assert EDN_CTRL_DISABLE == 0x9669
    assert (EDN_CTRL_DISABLE & ~0xF) == (EDN_CTRL_AUTO & ~0xF)


_selftest()
