# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy-pool aperture driver (sep_entropy_pool_aperture_test).

64-bit AXI-Lite drain of the fabric Entropy Pool target
(``memory_map.adoc`` EPOOL). Live offsets: status ``0x00``, irq-cause
``0x08``, pop ``0x10``; every other in-window offset and every write is
SLVERR (``fabric.adoc``).
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import agg_from_pic, window
from sep_reg_meta import ENTROPY_SOURCE

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import EDN_CTRL, EDN_CTRL_AUTO, ESRC_CTRL

# Aperture from memory_map.adoc EPOOL. Occupancy and pool_low are graded
# from the live status / aggregator flags, not from a FIFO watermark.
POOL_BASE = window("EPOOL").base
POOL_STATUS = POOL_BASE + 0x00
POOL_IRQ_CAUSE = POOL_BASE + 0x08
POOL_POP = POOL_BASE + 0x10
FIFO_DEPTH = 32
STALL_THRESH = 4096

RESP_OKAY = 0
RESP_SLVERR = 2

IRQ_POOL_LOW = agg_from_pic("Entropy pool low")
IRQ_FILL_STALL = agg_from_pic("Entropy pool fill stall")

# Offsets that alias a live register if the decode drops high address bits
# (the defect the 16-bit unique-case exists to catch). A seed that only
# probes 0x18 never sees that class: 0x18 is the unused [4:3]=11 code.
_ALIAS_UNMAPPED = (
    0x20,  # -> status  0x00 if [4:0] only
    0x28,  # -> irq     0x08 if [4:0] only
    0x30,  # -> pop     0x10 if [4:0] only
    0x100,  # -> status  0x00 if [7:0] only
    0x1000,  # -> status  0x00 if [11:0] only
    0x8000,  # -> status  0x00 if [14:0] only
)
# Unique-dead extras: SLVERR even under a 2-bit [4:3] decode. All three are
# walked every seed -- 0x18 is the unused [4:3]=11 code and catches a class the
# other two do not, so a seeded pick of one could miss it.
_UNIQUE_DEAD = (0x18, 0x40, 0x80)

# Legal disable: MODULE_ENABLE=0, every other CTRL field at its reset (including
# SHA256_WHITENING_ENABLE=1). A hand-cleared multi-bit field is an alert.
ESRC_CTRL_DISABLE = ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=0)
# EDN_CTRL mubi4: True=0x6, False=0x9. AUTO bring-up is 0x9666 (ENABLE=T).
# MODULE_ENABLE=0 does not drop AUTO-mode EDN acks while CSRNG still has a
# seed, so fill-stall needs EDN_ENABLE=False to leave the pool request
# outstanding without ack.
EDN_CTRL_DISABLE = (EDN_CTRL_AUTO & ~0xF) | 0x9


class SepEntropyPoolCfg:
    """RANDCFG: extra accepted pops, plus one unique-dead offset.

    Every seed walks ``alias_offs`` (high-bit mirrors of the live
    registers). The seed only picks the extra unique-dead offset.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.extra_pops = rng.randrange(1, 5)
        self.alias_offs = _ALIAS_UNMAPPED
        self.unmapped_offs = _UNIQUE_DEAD

    def summary(self) -> str:
        aliases = ",".join(f"0x{o:x}" for o in self.alias_offs)
        return (
            f"seed={self.seed} extra_pops={self.extra_pops} "
            f"alias=[{aliases}] "
            f"extra_dead=[{','.join(f'0x{o:x}' for o in self.unmapped_offs)}]"
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
    assert STALL_THRESH == 4096
    cfg = SepEntropyPoolCfg(1)
    assert cfg.alias_offs == _ALIAS_UNMAPPED
    assert cfg.unmapped_offs == (0x18, 0x40, 0x80)
    assert 1 <= cfg.extra_pops <= 4
    # The three pinned testlist seeds must all still walk the alias set.
    for pinned in (1, 2, 3):
        pinned_cfg = SepEntropyPoolCfg(pinned)
        assert pinned_cfg.alias_offs == _ALIAS_UNMAPPED
    # Disable keeps whitening at reset-1 and only clears MODULE_ENABLE.
    assert ENTROPY_SOURCE.value("CTRL") & ~0x2 == ESRC_CTRL_DISABLE
    assert EDN_CTRL_DISABLE == 0x9669
    assert (EDN_CTRL_DISABLE & ~0xF) == (EDN_CTRL_AUTO & ~0xF)


_selftest()
