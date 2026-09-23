# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""KM mailbox as a SEP-side register surface: status, overflow/underflow, flush.

no_cpu / +skip_fuse_sense. RANDCFG. KM stays in software reset.

The command-set leaf uses the mailbox as a transport. A well-formed exchange
never reads an empty outbound FIFO or overruns a full inbound one, so it
cannot grade STATUS depth/full, the sticky error bits, IRQ_STATUS, or
SEP_CTRL's response modes and flush. Those accesses smash a frame in flight
and do not compose with a command stream.

KM is held (SW_RESET_N bit 0 = 0, the reset default). The SEP-facing mailbox
lives on cold reset, so the FIFOs and SEP registers stay alive while the KM
CPU cannot consume inbound words or push outbound ones. Fill, overflow and
underflow are then deterministic, and firmware cannot flush or fault the
mailbox under the host. A SEP_CTRL write after a deliberate underflow is a
register-block access, independent of the FIFO error path, and must stay
OKAY. The write is a 32-bit beat: a 64-bit beat at SEP_CTRL (offset 0x18)
spans past the 0x1C mailbox window and the fabric refuses it.

Checkers:
  CHK-HELD     SW_RESET_N bit 0 reads 0: KM is held, so no firmware peer
  CHK-IDLE     reset STATUS and IRQ_STATUS match the empty golden
  CHK-UFL      empty SEP_READ_DATA -> SLVERR, data 0, outbound_underflow
               latches in STATUS and IRQ_STATUS
  CHK-CTRL     a SEP_CTRL write immediately after that underflow is OKAY
               and reads back; the register is not the FIFO error path
  CHK-UFL-RESP SEP_CTRL.outbound_underflow_resp turns the same empty read
               into OKAY; the sticky bits stay set
  CHK-UFL-W1C  write-1-to-clear drops both sticky copies
  CHK-FILL     16 seeded writes fill inbound; STATUS depth/full/empty and
               IRQ_STATUS.inbound_write_space_avail track the golden
  CHK-OVR      a 17th write -> SLVERR, inbound_overflow latches, depth stays 16
  CHK-OVR-RESP SEP_CTRL.inbound_overflow_resp turns the next overrun into
               OKAY; the sticky bit stays; depth stays 16 (drop)
  CHK-IRQ      enabling the two error IRQs raises aggregator [14]; clearing
               the enable drops the pin while IRQ_STATUS stays; W1C drops both
  CHK-FLUSH    CTRL.FLUSH empties both FIFOs, self-clears, and does not
               clear the sticky error bits

Scope deltas:
  * inbound_underflow, outbound_overflow, and flushed_by_km need the KM CPU
    as the peer. They are graded on the KM IP mailbox vehicles, not here.
  * STATUS.inbound_separator updates only when the KM pops inbound;
    STATUS.outbound_separator only when the SEP pops a KM-pushed word.
  * outbound_read_data_avail stays 0 because KM never pushes.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_km_mailbox_seq import (
    KM_CTRL_FLUSH,
    KM_CTRL_INBOUND_OVERFLOW_RESP,
    KM_CTRL_OUTBOUND_UNDERFLOW_RESP,
    KM_IRQ_EN_INBOUND_OVERFLOW,
    KM_IRQ_EN_OUTBOUND_UNDERFLOW,
    KM_IRQ_INBOUND_OVERFLOW,
    KM_IRQ_INBOUND_SPACE_AVAIL,
    KM_IRQ_OUTBOUND_UNDERFLOW,
    KM_MBOX_DEPTH,
    KM_MBOX_IRQ_AGG,
    KM_STATUS_INBOUND_DEPTH_LSB,
    KM_STATUS_INBOUND_DEPTH_MASK,
    KM_STATUS_INBOUND_EMPTY,
    KM_STATUS_INBOUND_FULL,
    KM_STATUS_INBOUND_OVERFLOW,
    KM_STATUS_LOW_MASK,
    KM_STATUS_OUTBOUND_DEPTH_LSB,
    KM_STATUS_OUTBOUND_DEPTH_MASK,
    KM_STATUS_OUTBOUND_EMPTY,
    KM_STATUS_OUTBOUND_FULL,
    KM_STATUS_OUTBOUND_UNDERFLOW,
    RESP_OKAY,
    RESP_SLVERR,
    SepKmMailbox,
)
from seq_lib.sep_sw_reset_seq import SW_RESET_N_BIT, SepSwReset

# Sticky copies live in both STATUS and IRQ_STATUS; flush must not clear them.
_STICKY_STATUS = (1 << KM_STATUS_INBOUND_OVERFLOW) | (1 << KM_STATUS_OUTBOUND_UNDERFLOW)
_STICKY_IRQ = (1 << KM_IRQ_INBOUND_OVERFLOW) | (1 << KM_IRQ_OUTBOUND_UNDERFLOW)
_IRQ_EN_ERR = (1 << KM_IRQ_EN_INBOUND_OVERFLOW) | (1 << KM_IRQ_EN_OUTBOUND_UNDERFLOW)


def _pack_status(
    *,
    inbound_depth: int,
    outbound_depth: int = 0,
    inbound_overflow: int = 0,
    outbound_underflow: int = 0,
) -> int:
    inbound_empty = int(inbound_depth == 0)
    inbound_full = int(inbound_depth >= KM_MBOX_DEPTH)
    outbound_empty = int(outbound_depth == 0)
    outbound_full = int(outbound_depth >= KM_MBOX_DEPTH)
    return (
        (inbound_empty << KM_STATUS_INBOUND_EMPTY)
        | (inbound_full << KM_STATUS_INBOUND_FULL)
        | (outbound_empty << KM_STATUS_OUTBOUND_EMPTY)
        | ((inbound_depth & KM_STATUS_INBOUND_DEPTH_MASK) << KM_STATUS_INBOUND_DEPTH_LSB)
        | ((outbound_depth & KM_STATUS_OUTBOUND_DEPTH_MASK) << KM_STATUS_OUTBOUND_DEPTH_LSB)
        | (inbound_overflow << KM_STATUS_INBOUND_OVERFLOW)
        | (outbound_underflow << KM_STATUS_OUTBOUND_UNDERFLOW)
        | (outbound_full << KM_STATUS_OUTBOUND_FULL)
    )


def _pack_irq(
    *,
    inbound_depth: int,
    inbound_overflow: int = 0,
    outbound_underflow: int = 0,
    outbound_depth: int = 0,
) -> int:
    space = int(inbound_depth < KM_MBOX_DEPTH)
    data_avail = int(outbound_depth > 0)
    return (
        (data_avail << 0)
        | (space << KM_IRQ_INBOUND_SPACE_AVAIL)
        | (inbound_overflow << KM_IRQ_INBOUND_OVERFLOW)
        | (outbound_underflow << KM_IRQ_OUTBOUND_UNDERFLOW)
    )


class SepKmMboxProtoCfg:
    """Single source of truth: seeded inbound fill words for one run."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        words = []
        while len(words) < KM_MBOX_DEPTH:
            w = rng.getrandbits(32)
            if w not in words:
                words.append(w)
        self.fill_words = tuple(words)
        self.overflow_word = rng.getrandbits(32)

    def summary(self) -> str:
        return (
            f"seed={self.seed} depth={KM_MBOX_DEPTH} "
            f"fill0=0x{self.fill_words[0]:08x} overflow=0x{self.overflow_word:08x}"
        )


@pyuvm.test()
class sep_km_mailbox_protocol_rand_test(sep_base_test):
    """Grade the SEP-side KM mailbox registers, not the command stream."""

    async def run_scenario(self) -> None:
        cfg = SepKmMboxProtoCfg(self.random_seed())
        self.logger.info("km mailbox protocol: %s", cfg.summary())

        await self.bring_up_no_cpu()
        self.mb = SepKmMailbox(self)
        self.swrst = SepSwReset(self)

        rst = await self.swrst.read_back()
        assert (rst & (1 << SW_RESET_N_BIT["km"])) == 0, (
            f"CHK-HELD FAIL: KM released (SW_RESET_N=0x{rst:08x}); "
            "this leaf needs the KM CPU held so it cannot drain the FIFOs"
        )
        self.logger.info("CHK-HELD PASS: KM held, SW_RESET_N=0x%02x", rst)

        await self._chk_idle()
        await self._chk_underflow()
        await self._chk_fill(cfg)
        await self._chk_overflow(cfg)
        await self._chk_irq()
        await self._chk_flush()

    def _irq_agg(self) -> int:
        vec = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, mask=1 << KM_MBOX_IRQ_AGG)
        return (vec >> KM_MBOX_IRQ_AGG) & 1

    async def _expect_status(self, where: str, **fields) -> None:
        got = await self.mb.read_status()
        exp = _pack_status(**fields)
        assert got == exp, f"{where}: STATUS 0x{got:08x} != golden 0x{exp:08x}"

    async def _expect_irq(self, where: str, **fields) -> None:
        got = await self.mb.read_irq_status()
        exp = _pack_irq(**fields)
        assert got == exp, f"{where}: IRQ_STATUS 0x{got:08x} != golden 0x{exp:08x}"

    async def _chk_idle(self) -> None:
        await self._expect_status("CHK-IDLE", inbound_depth=0)
        await self._expect_irq("CHK-IDLE", inbound_depth=0)
        assert self._irq_agg() == 0, "CHK-IDLE FAIL: aggregator [14] set at reset"
        self.logger.info(
            "CHK-IDLE PASS: empty STATUS/IRQ_STATUS match the golden; aggregator [14]=0"
        )

    async def _chk_underflow(self) -> None:
        resp, data = await self.mb.read_data_raw(expect_error=True)
        assert resp == RESP_SLVERR and not data, (
            f"CHK-UFL FAIL: empty READ_DATA resp={resp} data=0x{data:08x}, expected SLVERR and 0"
        )
        await self._expect_status("CHK-UFL", inbound_depth=0, outbound_underflow=1)
        await self._expect_irq("CHK-UFL", inbound_depth=0, outbound_underflow=1)
        self.logger.info("CHK-UFL PASS: empty READ_DATA -> SLVERR + 0, outbound_underflow latched")

        # Register-block write, not a FIFO pop: must stay OKAY after underflow.
        await self.mb.write_ctrl(1 << KM_CTRL_OUTBOUND_UNDERFLOW_RESP)
        ctrl = await self.mb.read_ctrl()
        assert ctrl & (1 << KM_CTRL_OUTBOUND_UNDERFLOW_RESP), (
            f"CHK-CTRL FAIL: outbound_underflow_resp did not stick (CTRL=0x{ctrl:08x})"
        )
        self.logger.info(
            "CHK-CTRL PASS: SEP_CTRL write immediately after underflow is OKAY and reads back"
        )

        resp, data = await self.mb.read_data_raw()
        assert resp == RESP_OKAY and not data, (
            f"CHK-UFL-RESP FAIL: empty READ_DATA with resp-mode=OKAY returned "
            f"resp={resp} data=0x{data:08x}"
        )
        await self._expect_status("CHK-UFL-RESP", inbound_depth=0, outbound_underflow=1)
        await self._expect_irq("CHK-UFL-RESP", inbound_depth=0, outbound_underflow=1)
        self.logger.info(
            "CHK-UFL-RESP PASS: resp-mode=OKAY on the same empty read; sticky bits still set"
        )

        await self.mb.write_ctrl(0)
        await self.mb.write_status(1 << KM_STATUS_OUTBOUND_UNDERFLOW)
        await self.mb.write_irq_status(1 << KM_IRQ_OUTBOUND_UNDERFLOW)
        await self._expect_status("CHK-UFL-W1C", inbound_depth=0)
        await self._expect_irq("CHK-UFL-W1C", inbound_depth=0)
        self.logger.info("CHK-UFL-W1C PASS: both sticky copies clear")

    async def _chk_fill(self, cfg: SepKmMboxProtoCfg) -> None:
        for i, word in enumerate(cfg.fill_words, start=1):
            resp = await self.mb.write_data_raw(word)
            assert resp == RESP_OKAY, f"CHK-FILL FAIL: write {i} resp={resp}, expected OKAY"
            await self._expect_status("CHK-FILL", inbound_depth=i)
            await self._expect_irq("CHK-FILL", inbound_depth=i)
        self.logger.info(
            "CHK-FILL PASS: %d seeded writes filled inbound; STATUS and space-avail tracked",
            KM_MBOX_DEPTH,
        )

    async def _chk_overflow(self, cfg: SepKmMboxProtoCfg) -> None:
        resp = await self.mb.write_data_raw(cfg.overflow_word, expect_error=True)
        assert resp == RESP_SLVERR, f"CHK-OVR FAIL: write-to-full resp={resp}, expected SLVERR"
        await self._expect_status("CHK-OVR", inbound_depth=KM_MBOX_DEPTH, inbound_overflow=1)
        await self._expect_irq("CHK-OVR", inbound_depth=KM_MBOX_DEPTH, inbound_overflow=1)
        self.logger.info(
            "CHK-OVR PASS: 17th write -> SLVERR, inbound_overflow latched, depth stays %d",
            KM_MBOX_DEPTH,
        )

        await self.mb.write_ctrl(1 << KM_CTRL_INBOUND_OVERFLOW_RESP)
        resp = await self.mb.write_data_raw(cfg.overflow_word)
        assert resp == RESP_OKAY, (
            f"CHK-OVR-RESP FAIL: write-to-full with resp-mode=OKAY returned {resp}"
        )
        await self._expect_status("CHK-OVR-RESP", inbound_depth=KM_MBOX_DEPTH, inbound_overflow=1)
        await self._expect_irq("CHK-OVR-RESP", inbound_depth=KM_MBOX_DEPTH, inbound_overflow=1)
        self.logger.info(
            "CHK-OVR-RESP PASS: resp-mode=OKAY on the next overrun; depth still %d",
            KM_MBOX_DEPTH,
        )
        await self.mb.write_ctrl(0)

    async def _chk_irq(self) -> None:
        # Overflow sticky is still set from CHK-OVR. Underflow is clear.
        # Enable only the error IRQs so space-avail cannot hold the pin.
        await self.mb.write_irq_enable(_IRQ_EN_ERR)
        await ClockCycles(cocotb.top.clk_i, 2)
        assert self._irq_agg() == 1, (
            "CHK-IRQ FAIL: aggregator [14] stayed 0 with overflow sticky and enable set"
        )
        irq_held = await self.mb.read_irq_status()
        await self.mb.write_irq_enable(0)
        await ClockCycles(cocotb.top.clk_i, 2)
        irq_after = await self.mb.read_irq_status()
        assert self._irq_agg() == 0, "CHK-IRQ FAIL: aggregator [14] stayed 1 after IRQ_ENABLE=0"
        assert irq_after == irq_held, (
            f"CHK-IRQ FAIL: IRQ_STATUS changed when enable cleared "
            f"(0x{irq_held:08x} -> 0x{irq_after:08x})"
        )
        await self.mb.write_irq_enable(_IRQ_EN_ERR)
        await ClockCycles(cocotb.top.clk_i, 2)
        assert self._irq_agg() == 1, "CHK-IRQ FAIL: aggregator [14] did not return with enable"

        await self.mb.write_status(_STICKY_STATUS)
        await self.mb.write_irq_status(_STICKY_IRQ)
        await self.mb.write_irq_enable(0)
        await ClockCycles(cocotb.top.clk_i, 2)
        await self._expect_status("CHK-IRQ-W1C", inbound_depth=KM_MBOX_DEPTH)
        await self._expect_irq("CHK-IRQ-W1C", inbound_depth=KM_MBOX_DEPTH)
        assert self._irq_agg() == 0, "CHK-IRQ FAIL: aggregator [14] stayed after W1C"
        self.logger.info(
            "CHK-IRQ PASS: enable raises aggregator [14], disable drops the pin "
            "with IRQ_STATUS held, W1C clears both"
        )

    async def _chk_flush(self) -> None:
        # Re-latch overflow so flush can be shown not to clear it.
        resp = await self.mb.write_data_raw(0xA5A5_A5A5, expect_error=True)
        assert resp == RESP_SLVERR, "CHK-FLUSH setup: write-to-full was not SLVERR"
        await self.mb.write_ctrl(1 << KM_CTRL_FLUSH)
        for _ in range(16):
            if (await self.mb.read_ctrl() & (1 << KM_CTRL_FLUSH)) == 0:
                break
            await ClockCycles(cocotb.top.clk_i, 1)
        else:
            raise AssertionError("CHK-FLUSH FAIL: CTRL.flush did not self-clear")

        st = await self.mb.read_status()
        assert st & (1 << KM_STATUS_INBOUND_OVERFLOW), (
            f"CHK-FLUSH FAIL: flush cleared inbound_overflow (STATUS=0x{st:08x})"
        )
        assert (st & KM_STATUS_LOW_MASK) == (
            (1 << KM_STATUS_INBOUND_EMPTY) | (1 << KM_STATUS_OUTBOUND_EMPTY)
        ), f"CHK-FLUSH FAIL: FIFOs not empty after flush (STATUS=0x{st:08x})"
        assert ((st >> KM_STATUS_INBOUND_DEPTH_LSB) & KM_STATUS_INBOUND_DEPTH_MASK) == 0, (
            f"CHK-FLUSH FAIL: inbound_depth not 0 after flush (STATUS=0x{st:08x})"
        )

        await self.mb.write_status(1 << KM_STATUS_INBOUND_OVERFLOW)
        await self.mb.write_irq_status(1 << KM_IRQ_INBOUND_OVERFLOW)
        await self._expect_status("CHK-FLUSH", inbound_depth=0)
        await self._expect_irq("CHK-FLUSH", inbound_depth=0)
        self.logger.info(
            "CHK-FLUSH PASS: flush emptied both FIFOs, self-cleared, and left the "
            "overflow sticky set until W1C"
        )
