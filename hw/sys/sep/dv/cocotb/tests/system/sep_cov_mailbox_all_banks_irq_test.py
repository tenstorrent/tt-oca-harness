# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every mailbox bank driven, outbound and inbound (coverage stimulus).

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AXIL_MAILBOX_OUTBOUND_0, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter, SepInboundFilterCfg

# One aperture symbol per bank from the generated export, so the walk cannot
# silently cover a subset if the bank count changes.
NUM_BANKS = 8
OUTBOUND_BASE = tuple(
    sym(f"AXIL_MAILBOX_OUTBOUND_MAILBOX_{n}_REG_MAP_BASE_ADDR") for n in range(NUM_BANKS)
)
INBOUND_BASE = tuple(
    sym(f"AXIL_MAILBOX_INBOUND_MAILBOX_{n}_REG_MAP_BASE_ADDR") for n in range(NUM_BANKS)
)
# The inbound apertures interleave with the outbound ones at a 0x800 offset
# inside each 0x1000 bank, so one allow window from the first inbound aperture
# to the top of the last bank spans every inbound bank.
BANK_STRIDE = OUTBOUND_BASE[1] - OUTBOUND_BASE[0]
INBOUND_WINDOW_END = OUTBOUND_BASE[NUM_BANKS - 1] + BANK_STRIDE - 1

WRITE_DATA = AXIL_MAILBOX_OUTBOUND_0.offset("WRITE_DATA")
READ_DATA = AXIL_MAILBOX_OUTBOUND_0.offset("READ_DATA")
STATUS = AXIL_MAILBOX_OUTBOUND_0.offset("STATUS")
WIRQT = AXIL_MAILBOX_OUTBOUND_0.offset("WIRQT")
IRQS = AXIL_MAILBOX_OUTBOUND_0.offset("IRQS")
IRQEN = AXIL_MAILBOX_OUTBOUND_0.offset("IRQEN")
CTRL = AXIL_MAILBOX_OUTBOUND_0.offset("CTRL")
IRQEN_ALL = AXIL_MAILBOX_OUTBOUND_0.mask32("IRQEN")
CTRL_WFLUSH = AXIL_MAILBOX_OUTBOUND_0.field_mask("CTRL", "wflush")
# One entry is enough to make the write-threshold interrupt reachable with the
# two words this walk pushes.
WIRQT_ONE = 1

_WORDS_PER_BANK = 2


@pyuvm.test()
class sep_cov_mailbox_all_banks_irq_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    The suite otherwise drives mailbox bank 0 only, so the
    ``axi_lite_mailbox_unit`` demux never selects a master port above 1 and
    ``outbound_interrupt_o[7:1]`` never moves. This walks every bank: it arms
    the write threshold (``WIRQT``), enables the interrupts (``IRQEN``),
    pushes two 64-bit words into the TX FIFO (``WRITE_DATA``), reads back
    ``STATUS`` and ``IRQS``, then flushes the FIFO through ``CTRL.wflush``.

    Outbound apertures are driven from the CPU-LSU master. The inbound
    apertures are reachable only from the SMN-inbound external master, which
    the inbound filter blocks by default, so one filter entry opens the whole
    mailbox block for read and write first.

    A bank's RX FIFO has no peer driving it here, so a ``READ_DATA`` pop
    returns the documented empty-FIFO sentinel with SLVERR. ``allow_error``
    tells the agent that a non-OKAY response is the documented outcome; no
    response code and no read value is scored.

    Payload words come from ``SepSeededRng``, so the stimulus is a pure
    function of the run seed.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _run(self, seq, *, external: bool) -> None:
        if external:
            await self.start_ext_seq(seq)
        else:
            await self.start_seq(seq)

    async def _wr32(self, addr: int, data: int, *, external: bool) -> None:
        seq = SepAxiAccessSeq(
            f"mbox_cov_wr32_0x{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            length=4,
            size=2,
            allow_unverified_write_resp=True,
        )
        await self._run(seq, external=external)

    async def _rd32(self, addr: int, *, external: bool) -> None:
        seq = SepAxiAccessSeq(
            f"mbox_cov_rd32_0x{addr:08x}",
            op=SepAxiOp.READ,
            addr=addr,
            length=4,
            size=2,
        )
        await self._run(seq, external=external)

    async def _push64(self, addr: int, value: int, *, external: bool) -> None:
        seq = SepAxiAccessSeq(
            f"mbox_cov_push_0x{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=value,
            length=8,
            size=3,
            allow_unverified_write_resp=True,
        )
        await self._run(seq, external=external)

    async def _pop64(self, addr: int, *, external: bool) -> None:
        seq = SepAxiAccessSeq(
            f"mbox_cov_pop_0x{addr:08x}",
            op=SepAxiOp.READ,
            addr=addr,
            length=8,
            size=3,
            allow_error=True,
        )
        await self._run(seq, external=external)

    async def _drive_bank(self, base: int, rng: SepSeededRng, *, external: bool) -> None:
        await self._wr32(base + WIRQT, WIRQT_ONE, external=external)
        await self._wr32(base + IRQEN, IRQEN_ALL, external=external)
        for _ in range(_WORDS_PER_BANK):
            await self._push64(base + WRITE_DATA, rng.getrandbits(64), external=external)
        await self._rd32(base + STATUS, external=external)
        await self._rd32(base + IRQS, external=external)
        await self._pop64(base + READ_DATA, external=external)
        await self._wr32(base + CTRL, CTRL_WFLUSH, external=external)

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())

        for bank in range(1, NUM_BANKS):
            await self._drive_bank(OUTBOUND_BASE[bank], rng, external=False)
            self.logger.info("cov stimulus: drove outbound mailbox bank %d", bank)

        filt = SepInboundFilter(self)
        rule = SepInboundFilterCfg(entry=0, allow_addr=INBOUND_BASE[0])
        await filt.program_rule(
            rule, read_allowed=True, write_allowed=True, end_addr=INBOUND_WINDOW_END
        )
        self.logger.info(
            "cov stimulus: inbound filter entry 0 opens 0x%08x..0x%08x r+w",
            INBOUND_BASE[0],
            INBOUND_WINDOW_END,
        )
        for bank in range(NUM_BANKS):
            await self._drive_bank(INBOUND_BASE[bank], rng, external=True)
            self.logger.info("cov stimulus: drove inbound mailbox bank %d", bank)
