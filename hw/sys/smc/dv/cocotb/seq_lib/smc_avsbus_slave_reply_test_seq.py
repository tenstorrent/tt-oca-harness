# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An AVSBus slave that answers bit by bit, and the replies no level on sdata can give.

Every other AVSBus leaf holds the sdata pad at a level, so the controller only
ever receives all-zero replies (acknowledge 0, frame valid, CRC 000) or
all-one replies (frame not valid). This leaf puts a minimal responder on the
pad instead: it watches the master subframes the DUT drives on mdata and,
during the subframe that follows each one, shifts out a reply word chosen by
the leg, one bit per AVS clock, most significant first. The frame format is
`interface.adoc` "AVSBus Slave Subframe": acknowledge in [31:30], frame valid
(0 = valid) in [29], status in [28:24], data in [23:8], reserved [7:3] and a
CRC-3 in [2:0].

No document in this tree gives the CRC-3 polynomial. The responder does not
need it: `architecture.adoc` says a reply that fails the check does not
update `AVS_LATEST_SLAVE_SUBFRAME`, and with `MAX_RETRIES` at 0 the failing
reply is still delivered to the readback FIFO. So each reply shape is sent
once with each of the eight CRC codes, and the DUT names the one it accepts:
exactly one of the eight must update `AVS_LATEST_SLAVE_SUBFRAME`, and the
other seven must reach `AVS_READBACK` without doing so. The accepted code is
then used for the legs that need a reply the controller believes.

Reply shapes and what each leg requires:

* **Good, acknowledge 0**: `AVS_READBACK`, `AVS_LATEST_SLAVE_SUBFRAME` and
  `AVS_SLAVE_STATUS` all carry the word the responder sent.
* **Acknowledge 1 (resource unavailable), every time**: with `MAX_RETRIES` at
  2 the controller sends the same command three times, `TOTAL_RETRIES` rises
  by 2 and `MAX_RETRIES_ATTEMPTED_INT` is raised -- with every other source
  masked, so it is the only interrupt contributing to the pin.
* **Acknowledge 2 (bad CRC), then good**: one retry, then the good reply is
  delivered and no retry interrupt is raised.
* **Acknowledge 3 (bad data)**: not a retry code; delivered at once, with
  `AVS_SLAVE_STATUS` showing acknowledge 3.
* **Frame not valid**: `SLAVE_UNRESPONSIVE_INT`, again the only source
  unmasked.
* **A buffered reply**: two commands back to back, the first acknowledged 1,
  so its retry is made while the second one's reply waits. With the reply
  that waited good, the controller delivers it after the retry. With it
  acknowledged 1 and `MAX_RETRIES` cleared while the retry is on the wire,
  the controller has no budget left for it and delivers it as it is.
* **A full readback FIFO**: `architecture.adoc` says the master launches no
  further commands while the readback FIFO is full. With every reply left
  unread, the commands queued after it must wait with no subframe on the
  wire; a forced slave resync is requested while they wait, and after one pop
  every command must complete with its reply intact.
* **A slave interrupt**: sdata held low while the bus is idle raises
  `AVS_SLAVE_ISSUED_INTERRUPT`, the only source unmasked, and the clear
  register clears it.
* **A command launched during a slave interrupt**: sdata is held low long
  enough to raise the interrupt, and a command queued while it is still low
  has to launch and read back its reply intact.
* **A readback overflow**: with one readback slot left, a retried pair's
  good retry reply takes it and the reply that waited behind the retry meets
  a full FIFO. `READBACK_OVERFLOW_INT` has to set, the interrupt line has to
  follow its mask alone, and the waiting reply is the one dropped.
* **The duty-cycle numerator alone**: the divider defaults are written as real
  values, then only the numerator changes, to a quarter and back, and the
  clock at the pad has to follow.
* **A resync requested while busy**: a slave resync is forced while commands
  are still going out and more are queued behind it, and with the replies
  drained as they come every command must be answered intact. `AVS_READBACK` read with the FIFO empty must then be refused.
* **Three FIFO interrupts, one at a time**: with both FIFOs full and one
  `AVS_CMD` write more, which is refused, `READBACK_FIFO_FULL`,
  `CMD_FIFO_FULL` and `CMD_FIFO_OVERFLOW` are all set. The AVSBus interrupt
  line has to be low with every source masked and high with each of the
  three unmasked on its own, and every reply then drains intact.

The leg order is fixed and every expectation follows from the documents; the
responder's reply queue is consumed one word per master subframe it sees.
"""

from __future__ import annotations

from collections import deque

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_avsbus_protocol_utils import (
    AVS_CFG_0,
    AVS_CFG_1,
    AVS_CMD,
    AVS_FIFOS_STATUS,
    AVS_INTERRUPT,
    AVS_INTERRUPT_CLEAR,
    AVS_INTERRUPT_MASK,
    AVS_NORMAL_STATUS,
    CMD_FIFO_EMPTY_BM,
    CMD_TYPE_READ,
    MASTER_IS_RETRYING_BM,
    MAX_RETRIES_ATTEMPTED_BM,
    MAX_RETRIES_BM,
    MAX_RETRIES_BP,
    RB_FIFO_DEPTH,
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
    READ_CMD_DATA,
    READBACK_HAS_DATA_BM,
    SLAVE_UNRESPONSIVE_BM,
    TOTAL_RETRIES_BM,
    TOTAL_RETRIES_BP,
    avs_field,
    build_avs_cmd,
    expected_master_subframe,
    fifo_field,
)
from .smc_avsbus_protocol_utils import AVS_READBACK as AVS_READBACK_REG
from .smc_csr_seq_utils import SmcCsrSeq

AVS_LATEST = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_LATEST_SLAVE_SUBFRAME_BASE_ADDR")
AVS_SLAVE_STATUS = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_SLAVE_STATUS_BASE_ADDR")

SLAVE_ACK_BM = avs_field("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_ACK_bm")
SLAVE_ACK_BP = avs_field("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_ACK_bp")
SLAVE_STATUS_BM = avs_field("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_STATUS_RESPONSE_bm")
SLAVE_STATUS_BP = avs_field("AVSBUS_CONTROLLER__AVS_SLAVE_STATUS__AVS_SLAVE_STATUS_RESPONSE_bp")
#: The AVS_READBACK fields, in the slave subframe's own bit positions.
READBACK_FIELDS = (
    avs_field("AVSBUS_CONTROLLER__AVS_READBACK__SLAVE_ACK_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__STATUS_RESPONSE_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CMD_DATA_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CRC_bm")
)
MASK_ALL = 0x1FF
MASK_KEEP_MAX_RETRIES = MASK_ALL & ~avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_MASK__DISABLE_MAX_RETRIES_ATTEMPTED_INT_bm"
)
MASK_KEEP_UNRESPONSIVE = MASK_ALL & ~avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_MASK__DISABLE_SLAVE_UNRESPONSIVE_INT_bm"
)
MASK_KEEP_SLAVE_ISSUED = MASK_ALL & ~avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_MASK__DISABLE_AVS_SLAVE_ISSUED_INTERRUPT_bm"
)
SLAVE_ISSUED_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__AVS_SLAVE_ISSUED_INTERRUPT_bm")
READBACK_FIFO_FULL_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__READBACK_FIFO_FULL_bm")
FORCE_RESYNC_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__FORCE_SLAVE_RESYNC_OPERATION_bm")
CLEAR_ALL = 0x1FF
CMD_FIFO_DEPTH = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_VACANT_SLOTS_reset")
CMD_FIFO_FULL_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__CMD_FIFO_FULL_bm")
INT_RB_FULL = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__READBACK_FIFO_FULL_INT_bm")
INT_CMD_FULL = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__CMD_FIFO_FULL_INT_bm")
INT_CMD_OVERFLOW = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__CMD_FIFO_OVERFLOW_INT_bm")
DISABLE_RB_FULL = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_MASK__DISABLE_READBACK_FIFO_FULL_INT_bm"
)
DISABLE_CMD_FULL = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT_MASK__DISABLE_CMD_FIFO_FULL_INT_bm")
DISABLE_CMD_OVERFLOW = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_MASK__DISABLE_CMD_FIFO_OVERFLOW_INT_bm"
)
INT_RB_OVERFLOW = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__READBACK_OVERFLOW_INT_bm")
DISABLE_RB_OVERFLOW = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_MASK__DISABLE_READBACK_OVERFLOW_INT_bm"
)
NUMERATOR_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_DUTY_CYCLE_NUMERATOR_bm")
DIVIDER_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_VALUE_bm")
DIVIDER_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_VALUE_bp")
#: The hardware-default divisor `interface.adoc` names for the reset sentinel.
DEFAULT_DIVISOR = 4
NUMERATOR_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__CLK_DIVIDER_DUTY_CYCLE_NUMERATOR_bp")
PREMUX_OFF_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__TURN_OFF_ALL_PREMUX_CLOCKS_bm")
#: High fraction in 1/256 units (`interface.adoc`): a quarter, and the 50% the
#: RDL names as the hardware default.
QUARTER_NUMERATOR = 0x40
HALF_NUMERATOR = 0x80
DUTY_PERIODS = 8
#: The AVSBus interrupt line crosses into the SMC clock domain before the pin.
IRQ_SETTLE_CYCLES = 40
#: Commands queued behind a full readback FIFO.
STALL_EXTRA = 2
STALL_WAIT_CYCLES = 3000
#: Commands queued before the forced resync, so frames are on the wire when it lands.
BUSY_COMMANDS = 4
#: How long sdata is held low with the bus idle to signal a slave interrupt.
SLAVE_INT_CYCLES = 2000

# --- Slave subframe, transcribed from interface.adoc ------------------------
SUBFRAME_BITS = 32
ACK_BP = 30
FRAME_INVALID_BIT = 29
STATUS_BP = 24
DATA_BP = 8
CRC_CODES = 8
ACK_GOOD, ACK_UNAVAILABLE, ACK_BAD_CRC, ACK_BAD_DATA = 0, 1, 2, 3


def reply(ack: int, status: int, data: int, crc: int = 0, invalid: bool = False) -> int:
    return (
        (ack << ACK_BP)
        | (int(invalid) << FRAME_INVALID_BIT)
        | ((status & 0x1F) << STATUS_BP)
        | ((data & 0xFFFF) << DATA_BP)
        | (crc & 0x7)
    )


SHAPES = {
    "GOOD": reply(ACK_GOOD, 0x10, 0x1234),
    "UNAVAILABLE": reply(ACK_UNAVAILABLE, 0x00, 0x5678),
    "BAD_CRC": reply(ACK_BAD_CRC, 0x08, 0x9ABC),
    "BAD_DATA": reply(ACK_BAD_DATA, 0x04, 0xDEF0),
    "GOOD_2": reply(ACK_GOOD, 0x11, 0x2468),
}
#: A reply whose frame-valid bit says the slave did not respond.
NOT_VALID = reply(ACK_GOOD, 0x00, 0x0000, invalid=True)

CMD_A = build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x3, READ_CMD_DATA)
CMD_B = build_avs_cmd(CMD_TYPE_READ, 0, 0xE, 0x5, READ_CMD_DATA)

POLL_CYCLES = 50
POP_SETTLE_CYCLES = 40
POLL_LIMIT = 400


class AvsReplyDriver:
    """Answers each master subframe on mdata with the next queued reply on sdata.

    A master subframe opens with the preamble's low bit; the line idles high,
    and a subframe that follows another without a gap starts on the boundary
    32 clocks after it. The reply to the subframe starting on clock `n` is
    shifted out on clocks `n + 32` to `n + 63`, one bit after each rising
    edge, so the controller's falling-edge capture sees it one subframe later,
    as `architecture.adoc` describes. Outside a reply sdata is held at `idle`:
    high, unless a leg pulls it low to signal a slave interrupt, which the
    controller reads as two low bits while the bus is idle.
    """

    def __init__(self, default: int) -> None:
        self.replies: deque[int] = deque()
        self.default = default
        self.idle = 1
        self.masters: list[int] = []
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        self._task.cancel()
        cocotb.top.tb_avs_sdata_ext.value = 1

    async def _run(self) -> None:
        top = cocotb.top
        clk = top.tb_avs_clk_from_dut
        mdata = top.tb_avs_mdata_from_dut
        sdata = top.tb_avs_sdata_ext
        sdata.value = 1
        edge = 0
        prev = 1
        frame_end = 0
        frame_start = -1
        frame_word = 0
        schedule: list[tuple[int, int]] = []
        while True:
            await RisingEdge(clk)
            await Timer(1, unit="ns")
            raw = mdata.value
            level = int(raw) if raw.is_resolvable else 1
            if edge >= frame_end:
                if frame_start >= 0:
                    self.masters.append(frame_word)
                    frame_start = -1
                starts = level == 0 and (prev == 1 or edge == frame_end)
                if starts:
                    frame_start = edge
                    frame_end = edge + SUBFRAME_BITS
                    frame_word = 0
                    word = self.replies.popleft() if self.replies else self.default
                    schedule.append((edge + SUBFRAME_BITS, word))
            if frame_start >= 0:
                frame_word = (frame_word << 1) | level
            out = self.idle
            for start, word in schedule:
                if start <= edge < start + SUBFRAME_BITS:
                    out = (word >> (SUBFRAME_BITS - 1 - (edge - start))) & 1
            sdata.value = out
            schedule = [(s, w) for s, w in schedule if edge < s + SUBFRAME_BITS]
            prev = level
            edge += 1


class smc_avsbus_slave_reply_test_seq(SmcCsrSeq):
    """Drive shaped slave replies and check how the controller treats each."""

    def __init__(self, name: str = "smc_avsbus_slave_reply_test_seq") -> None:
        super().__init__(name)
        self.driver: AvsReplyDriver | None = None
        self.good_crc: dict[str, int] = {}
        self.cfg0 = 0

    def _word(self, shape: str) -> int:
        return SHAPES[shape] | self.good_crc[shape]

    async def _set_retries(self, label: str, budget: int) -> None:
        want = (self.cfg0 & ~MAX_RETRIES_BM) | ((budget << MAX_RETRIES_BP) & MAX_RETRIES_BM)
        await self.csr_write(f"{label}_CFG0", AVS_CFG_0, want)
        await self.csr_read(f"{label}_CFG0_RB", AVS_CFG_0, expected=want)

    async def _retries(self, label: str) -> int:
        status = await self.csr_read(f"{label}_NORMAL", AVS_NORMAL_STATUS)
        return fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)

    async def _occupancy(self, label: str) -> int:
        fifos = await self.csr_read(f"{label}_FIFOS", AVS_FIFOS_STATUS)
        return fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)

    async def _await_replies(self, label: str, count: int) -> None:
        occupied = 0
        for _ in range(POLL_LIMIT):
            occupied = await self._occupancy(label)
            if occupied >= count:
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: {occupied} of {count} replies reached the readback FIFO")

    async def _pop(self, label: str) -> int:
        await self._await_data(label)
        word = await self.csr_read(f"{label}_READBACK", AVS_READBACK_REG)
        # A pop reaches the FIFO status a few register-clock cycles after its read
        # completes; a status read issued sooner still counts the entry popped, and a
        # second pop of it would be refused on the bus.
        await ClockCycles(cocotb.top.clk_smc_i, POP_SETTLE_CYCLES)
        return word

    async def _has_data(self, label: str) -> bool:
        status = await self.csr_read(f"{label}_NORMAL", AVS_NORMAL_STATUS)
        return bool(status & READBACK_HAS_DATA_BM)

    async def _await_data(self, label: str) -> None:
        for _ in range(POLL_LIMIT):
            if await self._has_data(label):
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: AVS_NORMAL_STATUS.READBACK_HAS_DATA never set")

    async def _drain(self, label: str) -> None:
        # READBACK_HAS_DATA, not the FIFO occupancy, says whether AVS_READBACK has a
        # word to return: a read with nothing to return is refused on the bus.
        for _ in range(16):
            if not await self._has_data(f"{label}_DRAIN"):
                return
            await self._pop(f"{label}_DRAIN")
        raise AssertionError(f"{label}: the readback FIFO did not empty")

    async def _await_idle(self, label: str) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, 400)
        await self._drain(label)

    def _send(self, *words: int) -> None:
        assert self.driver is not None
        self.driver.replies.extend(words)

    async def _learn_crc(self, shape: str) -> None:
        """Send `shape` with each CRC code; exactly one must be accepted."""
        label = f"CRC_{shape}"
        accepted: list[int] = []
        for code in range(CRC_CODES):
            word = SHAPES[shape] | code
            before = await self.csr_read(f"{label}{code}_LATEST_BEFORE", AVS_LATEST)
            self._send(word)
            await self.csr_write(f"{label}{code}_CMD", AVS_CMD, CMD_A)
            await self._await_replies(f"{label}{code}", 1)
            got = await self._pop(f"{label}{code}")
            assert got & READBACK_FIELDS == word & READBACK_FIELDS, (
                f"{label}: with MAX_RETRIES at 0 the reply 0x{word:08x} reached AVS_READBACK "
                f"as 0x{got:08x}"
            )
            latest = await self.csr_read(f"{label}{code}_LATEST", AVS_LATEST)
            if latest == word:
                accepted.append(code)
            else:
                assert latest == before, (
                    f"{label}: CRC code {code} was not accepted, yet AVS_LATEST_SLAVE_SUBFRAME "
                    f"changed from 0x{before:08x} to 0x{latest:08x}"
                )
        assert len(accepted) == 1, (
            f"{label}: {len(accepted)} of the eight CRC codes were accepted for 0x"
            f"{SHAPES[shape]:08x} ({accepted}); a 3-bit check accepts exactly one"
        )
        self.good_crc[shape] = accepted[0]

    async def _good_leg(self) -> None:
        label = "GOOD"
        word = self._word("GOOD")
        self._send(word)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_B)
        await self._await_replies(label, 1)
        got = await self._pop(label)
        latest = await self.csr_read(f"{label}_LATEST", AVS_LATEST)
        status = await self.csr_read(f"{label}_SLAVE_STATUS", AVS_SLAVE_STATUS)
        ack = (status & SLAVE_ACK_BM) >> SLAVE_ACK_BP
        resp = (status & SLAVE_STATUS_BM) >> SLAVE_STATUS_BP
        assert got & READBACK_FIELDS == word & READBACK_FIELDS and latest == word, (
            f"{label}: sent 0x{word:08x}; AVS_READBACK 0x{got:08x}, LATEST 0x{latest:08x}"
        )
        assert (ack, resp) == (ACK_GOOD, 0x10), (
            f"{label}: AVS_SLAVE_STATUS shows acknowledge {ack} and status 0x{resp:02x}, not "
            f"the 0 and 0x10 sent"
        )

    async def _exhaust_leg(self) -> None:
        label = "EXHAUST"
        assert self.driver is not None
        await self._set_retries(label, 2)
        await self.csr_write(f"{label}_MASK", AVS_INTERRUPT_MASK, MASK_KEEP_MAX_RETRIES)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        retries = await self._retries(f"{label}_BEFORE")
        masters = len(self.driver.masters)
        word = self._word("UNAVAILABLE")
        self._send(word, word, word)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_A)
        await self._await_replies(label, 1)
        got = await self._pop(label)
        after = await self._retries(f"{label}_AFTER")
        intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        sent = [m & ~0x7 for m in self.driver.masters[masters:]]
        assert got & READBACK_FIELDS == word & READBACK_FIELDS, (
            f"{label}: after the budget ran out AVS_READBACK holds 0x{got:08x}, not the last "
            f"reply 0x{word:08x}"
        )
        assert after - retries == 2 and intr & MAX_RETRIES_ATTEMPTED_BM, (
            f"{label}: TOTAL_RETRIES rose by {after - retries} and AVS_INTERRUPT=0x{intr:08x}; "
            f"a budget of 2 against three unavailable replies retries twice and raises "
            f"MAX_RETRIES_ATTEMPTED_INT"
        )
        assert sent[:3] == [expected_master_subframe(CMD_A)] * 3, (
            f"{label}: the master subframes were {[hex(s) for s in sent]}; the same command "
            f"has to go out three times"
        )
        await self.csr_write(f"{label}_CLEAR_END", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        await self.csr_write(f"{label}_MASK_END", AVS_INTERRUPT_MASK, MASK_ALL)
        await self._await_idle(label)

    async def _recover_leg(self) -> None:
        label = "RECOVER"
        await self._set_retries(label, 2)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        retries = await self._retries(f"{label}_BEFORE")
        good = self._word("GOOD_2")
        self._send(self._word("BAD_CRC"), good)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_B)
        await self._await_replies(label, 1)
        got = await self._pop(label)
        after = await self._retries(f"{label}_AFTER")
        intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        assert got & READBACK_FIELDS == good & READBACK_FIELDS, (
            f"{label}: AVS_READBACK holds 0x{got:08x}, not the good reply 0x{good:08x} that "
            f"answered the retry"
        )
        assert after - retries == 1 and not intr & MAX_RETRIES_ATTEMPTED_BM, (
            f"{label}: TOTAL_RETRIES rose by {after - retries}, AVS_INTERRUPT=0x{intr:08x}; "
            f"one bad-CRC acknowledge then a good reply is one retry and no exhaustion"
        )
        await self._await_idle(label)

    async def _bad_data_leg(self) -> None:
        label = "BAD_DATA"
        retries = await self._retries(f"{label}_BEFORE")
        word = self._word("BAD_DATA")
        self._send(word)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_A)
        await self._await_replies(label, 1)
        got = await self._pop(label)
        after = await self._retries(f"{label}_AFTER")
        status = await self.csr_read(f"{label}_SLAVE_STATUS", AVS_SLAVE_STATUS)
        ack = (status & SLAVE_ACK_BM) >> SLAVE_ACK_BP
        assert got & READBACK_FIELDS == word & READBACK_FIELDS and after == retries, (
            f"{label}: AVS_READBACK 0x{got:08x} (sent 0x{word:08x}), TOTAL_RETRIES "
            f"{retries}->{after}; acknowledge 3 is not a retry code"
        )
        assert ack == ACK_BAD_DATA, f"{label}: AVS_SLAVE_STATUS shows acknowledge {ack}, not 3"
        await self._await_idle(label)

    async def _not_valid_leg(self) -> None:
        label = "NOT_VALID"
        await self._set_retries(label, 0)
        await self.csr_write(f"{label}_MASK", AVS_INTERRUPT_MASK, MASK_KEEP_UNRESPONSIVE)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        self._send(NOT_VALID)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_B)
        await self._await_replies(label, 1)
        intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        assert intr & SLAVE_UNRESPONSIVE_BM, (
            f"{label}: a reply with the frame-valid bit set left SLAVE_UNRESPONSIVE_INT clear "
            f"(AVS_INTERRUPT=0x{intr:08x})"
        )
        await self.csr_write(f"{label}_CLEAR_END", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        await self.csr_write(f"{label}_MASK_END", AVS_INTERRUPT_MASK, MASK_ALL)
        await self._await_idle(label)

    async def _buffered_leg(self, label: str, second: int, clear_budget: bool) -> list[int]:
        await self._set_retries(label, 1)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        unavailable = self._word("UNAVAILABLE")
        good = self._word("GOOD")
        self._send(unavailable, second, good)
        await self.csr_write(f"{label}_CMD_A", AVS_CMD, CMD_A)
        await self.csr_write(f"{label}_CMD_B", AVS_CMD, CMD_B)
        if clear_budget:
            for _ in range(POLL_LIMIT):
                status = await self.csr_read(f"{label}_RETRYING", AVS_NORMAL_STATUS)
                if status & MASTER_IS_RETRYING_BM:
                    break
            else:
                raise AssertionError(f"{label}: the controller never started the retry")
            await self._set_retries(f"{label}_NO_BUDGET", 0)
        await self._await_replies(label, 2)
        got = [await self._pop(f"{label}_{i}") for i in range(2)]
        await self._await_idle(label)
        return got

    async def _stall_leg(self) -> None:
        """Fill the readback FIFO, queue more, force a resync, then drain."""
        assert self.driver is not None
        label = "STALL"
        await self._set_retries(label, 0)
        good = self._word("GOOD")
        total = RB_FIFO_DEPTH + STALL_EXTRA
        self._send(*([good] * total))
        masters = len(self.driver.masters)
        for index in range(RB_FIFO_DEPTH):
            await self.csr_write(f"{label}_CMD{index}", AVS_CMD, CMD_A)
        await self._await_replies(label, RB_FIFO_DEPTH)
        for index in range(STALL_EXTRA):
            await self.csr_write(f"{label}_EXTRA{index}", AVS_CMD, CMD_B)
        await ClockCycles(cocotb.top.clk_smc_i, STALL_WAIT_CYCLES)
        status = await self.csr_read(f"{label}_STALLED", AVS_NORMAL_STATUS)
        launched = len(self.driver.masters) - masters
        assert status & READBACK_FIFO_FULL_BM and not status & CMD_FIFO_EMPTY_BM, (
            f"{label}: AVS_NORMAL_STATUS=0x{status:08x}; with {RB_FIFO_DEPTH} replies unread "
            f"the readback FIFO is full and the {STALL_EXTRA} later commands wait"
        )
        assert launched == RB_FIFO_DEPTH, (
            f"{label}: {launched} master subframes went out with the readback FIFO full after "
            f"{RB_FIFO_DEPTH}; the master launches no further commands while it is full"
        )
        cfg1 = await self.csr_read(f"{label}_CFG1", AVS_CFG_1)
        await self.csr_write(f"{label}_FORCE_RESYNC", AVS_CFG_1, cfg1 | FORCE_RESYNC_BM)
        got = [await self._pop(f"{label}_FIRST")]
        await self._await_replies(f"{label}_REST", RB_FIFO_DEPTH)
        for index in range(total - 1):
            got.append(await self._pop(f"{label}_DRAIN{index}"))
        assert all(w & READBACK_FIELDS == good & READBACK_FIELDS for w in got), (
            f"{label}: the {total} replies drained were {[hex(w) for w in got]}"
        )
        assert len(self.driver.masters) - masters == total, (
            f"{label}: {len(self.driver.masters) - masters} master subframes for {total} commands"
        )
        await self._await_idle(label)
        cocotb.log.info(
            "CHK-AVS-SLAVE-STALL: with %d replies unread the readback FIFO filled and the %d "
            "commands queued after it waited with no subframe launched; after a forced slave "
            "resync and one pop all %d commands completed and every reply read back intact",
            RB_FIFO_DEPTH,
            STALL_EXTRA,
            total,
        )

    async def _slave_interrupt_leg(self) -> None:
        assert self.driver is not None
        label = "SLAVE_INT"
        await self.csr_write(f"{label}_MASK", AVS_INTERRUPT_MASK, MASK_KEEP_SLAVE_ISSUED)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        intr = await self.csr_read(f"{label}_BEFORE", AVS_INTERRUPT)
        assert not intr & SLAVE_ISSUED_BM, f"{label}: set before the pull (0x{intr:08x})"
        self.driver.idle = 0
        await ClockCycles(cocotb.top.clk_smc_i, SLAVE_INT_CYCLES)
        self.driver.idle = 1
        intr = await self.csr_read(f"{label}_AFTER", AVS_INTERRUPT)
        assert intr & SLAVE_ISSUED_BM, (
            f"{label}: sdata held low with the bus idle left AVS_SLAVE_ISSUED_INTERRUPT clear "
            f"(AVS_INTERRUPT=0x{intr:08x})"
        )
        # The clear crosses into the AVS clock domain, so the bit falls some cycles later.
        await self.csr_write(f"{label}_CLEAR_END", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        for _ in range(POLL_LIMIT):
            intr = await self.csr_read(f"{label}_CLEARED", AVS_INTERRUPT)
            if not intr & SLAVE_ISSUED_BM:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(f"{label}: the clear never took (0x{intr:08x})")
        await self.csr_write(f"{label}_MASK_END", AVS_INTERRUPT_MASK, MASK_ALL)
        cocotb.log.info(
            "CHK-AVS-SLAVE-INTERRUPT: sdata held low while the bus was idle raised "
            "AVS_SLAVE_ISSUED_INTERRUPT as the only unmasked source, and the clear register "
            "cleared it"
        )

    async def _interrupt_launch_leg(self) -> None:
        """Signal a slave interrupt, then launch a command while sdata is still low."""
        assert self.driver is not None
        label = "INT_LAUNCH"
        await self._set_retries(label, 0)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        word = self._word("GOOD_2")
        self._send(word)
        self.driver.idle = 0
        await ClockCycles(cocotb.top.clk_smc_i, SLAVE_INT_CYCLES)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_A)
        got = await self._pop(label)
        self.driver.idle = 1
        intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        assert intr & SLAVE_ISSUED_BM, (
            f"{label}: sdata held low with the bus idle left AVS_SLAVE_ISSUED_INTERRUPT clear "
            f"(0x{intr:08x})"
        )
        assert got & READBACK_FIELDS == word & READBACK_FIELDS, (
            f"{label}: the command launched while sdata was low read back 0x{got:08x}, not "
            f"0x{word:08x}"
        )
        await self.csr_write(f"{label}_CLEAR_END", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        await self._await_idle(label)
        cocotb.log.info(
            "CHK-AVS-SLAVE-INTERRUPT-LAUNCH: with sdata held low long enough to raise "
            "AVS_SLAVE_ISSUED_INTERRUPT, a command queued while it was still low launched and "
            "its reply read back intact"
        )

    async def _avs_cmd_refused(self, label: str, word: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = AVS_CMD
        item.length = 4
        item.wdata = word
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: the write got no response"
        return item.resp_code

    async def _mask_leg(self) -> None:
        """Raise three FIFO interrupts together and unmask each one on its own."""
        assert self.driver is not None
        label = "MASKS"
        await self._set_retries(label, 0)
        await self.csr_write(f"{label}_MASK_ALL", AVS_INTERRUPT_MASK, MASK_ALL)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        good = self._word("GOOD")
        total = RB_FIFO_DEPTH + CMD_FIFO_DEPTH
        self._send(*([good] * total))
        for index in range(RB_FIFO_DEPTH):
            await self.csr_write(f"{label}_FILL{index}", AVS_CMD, CMD_A)
        await self._await_replies(label, RB_FIFO_DEPTH)
        for index in range(CMD_FIFO_DEPTH):
            await self.csr_write(f"{label}_QUEUE{index}", AVS_CMD, CMD_B)
        status = await self.csr_read(f"{label}_QUEUED", AVS_NORMAL_STATUS)
        assert status & CMD_FIFO_FULL_BM and status & READBACK_FIFO_FULL_BM, (
            f"{label}: AVS_NORMAL_STATUS=0x{status:08x}; both FIFOs must be full"
        )
        resp = await self._avs_cmd_refused(f"{label}_OVERFLOW", CMD_A)
        intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        wanted = INT_RB_FULL | INT_CMD_FULL | INT_CMD_OVERFLOW
        assert intr & wanted == wanted, (
            f"{label}: AVS_INTERRUPT=0x{intr:08x} after filling both FIFOs and one write more; "
            f"READBACK_FIFO_FULL, CMD_FIFO_FULL and CMD_FIFO_OVERFLOW must all be set"
        )
        await ClockCycles(cocotb.top.clk_smc_i, IRQ_SETTLE_CYCLES)
        assert int(cocotb.top.tb_avsbus_irq.value) == 0, (
            f"{label}: the AVSBus interrupt line is high with every source masked"
        )
        for name, disable in (
            ("READBACK_FIFO_FULL", DISABLE_RB_FULL),
            ("CMD_FIFO_FULL", DISABLE_CMD_FULL),
            ("CMD_FIFO_OVERFLOW", DISABLE_CMD_OVERFLOW),
        ):
            await self.csr_write(f"{label}_ONLY_{name}", AVS_INTERRUPT_MASK, MASK_ALL & ~disable)
            await ClockCycles(cocotb.top.clk_smc_i, IRQ_SETTLE_CYCLES)
            assert int(cocotb.top.tb_avsbus_irq.value) == 1, (
                f"{label}: with only {name} unmasked the AVSBus interrupt line stayed low"
            )
            await self.csr_write(f"{label}_REMASK_{name}", AVS_INTERRUPT_MASK, MASK_ALL)
            await ClockCycles(cocotb.top.clk_smc_i, IRQ_SETTLE_CYCLES)
            assert int(cocotb.top.tb_avsbus_irq.value) == 0, (
                f"{label}: the AVSBus interrupt line stayed high once {name} was masked again"
            )
        for index in range(total):
            got = await self._pop(f"{label}_DRAIN{index}")
            assert got & READBACK_FIELDS == good & READBACK_FIELDS, (
                f"{label}: reply {index} read back 0x{got:08x}"
            )
        await self.csr_write(f"{label}_CLEAR_END", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        await self._await_idle(label)
        cocotb.log.info(
            "CHK-AVS-SLAVE-MASKS: with both FIFOs full and one AVS_CMD write refused "
            "(response %d), READBACK_FIFO_FULL, CMD_FIFO_FULL and CMD_FIFO_OVERFLOW were all "
            "set; the interrupt line was low with every source masked and high with each of "
            "the three unmasked on its own, and all %d replies then drained intact",
            resp,
            total,
        )

    async def _overflow_leg(self) -> None:
        """Push a buffered reply into a readback FIFO that the retried one filled."""
        assert self.driver is not None
        label = "RB_OVERFLOW"
        await self._set_retries(label, 1)
        await self.csr_write(f"{label}_MASK_ALL", AVS_INTERRUPT_MASK, MASK_ALL)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        good = self._word("GOOD")
        prefill = RB_FIFO_DEPTH - 1
        self._send(*([good] * prefill))
        for index in range(prefill):
            await self.csr_write(f"{label}_PREFILL{index}", AVS_CMD, CMD_A)
        await self._await_replies(label, prefill)
        # The first command of the pair is answered unavailable, so its retry goes out
        # while the second one's reply waits; the retry's good reply takes the last
        # slot and the waiting reply then meets a full FIFO.
        retried = self._word("GOOD_2")
        self._send(self._word("UNAVAILABLE"), self._word("BAD_DATA"), retried)
        await self.csr_write(f"{label}_CMD_A", AVS_CMD, CMD_A)
        await self.csr_write(f"{label}_CMD_B", AVS_CMD, CMD_B)
        intr = 0
        for _ in range(POLL_LIMIT):
            intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
            if intr & INT_RB_OVERFLOW:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: READBACK_OVERFLOW_INT never set (AVS_INTERRUPT=0x{intr:08x})"
            )
        await ClockCycles(cocotb.top.clk_smc_i, IRQ_SETTLE_CYCLES)
        assert int(cocotb.top.tb_avsbus_irq.value) == 0, (
            f"{label}: the AVSBus interrupt line is high with every source masked"
        )
        await self.csr_write(
            f"{label}_ONLY_OVERFLOW", AVS_INTERRUPT_MASK, MASK_ALL & ~DISABLE_RB_OVERFLOW
        )
        await ClockCycles(cocotb.top.clk_smc_i, IRQ_SETTLE_CYCLES)
        assert int(cocotb.top.tb_avsbus_irq.value) == 1, (
            f"{label}: with only READBACK_OVERFLOW unmasked the AVSBus interrupt line stayed low"
        )
        await self.csr_write(f"{label}_REMASK", AVS_INTERRUPT_MASK, MASK_ALL)
        got = [await self._pop(f"{label}_DRAIN{index}") for index in range(RB_FIFO_DEPTH)]
        await self._await_idle(label)
        want = [good & READBACK_FIELDS] * prefill + [retried & READBACK_FIELDS]
        assert [w & READBACK_FIELDS for w in got] == want, (
            f"{label}: the FIFO drained {[hex(w) for w in got]}; the prefill and the retried "
            f"command's good reply fill it, and the waiting reply is the one dropped"
        )
        await self.csr_write(f"{label}_CLEAR_END", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        cocotb.log.info(
            "CHK-AVS-SLAVE-RB-OVERFLOW: with one readback slot left, a retried command's good "
            "reply took it and the reply that waited behind the retry raised "
            "READBACK_OVERFLOW_INT; the interrupt line was low masked and high with only that "
            "source unmasked, and the FIFO drained the %d replies it held, the waiting one "
            "dropped",
            RB_FIFO_DEPTH,
        )

    async def _numerator_leg(self) -> None:
        """Change the AVS clock duty-cycle numerator and nothing else."""
        label = "NUMERATOR"
        reset_cfg1 = await self.csr_read(f"{label}_CFG1", AVS_CFG_1)
        # Both divider fields reset to 0, a sentinel that leaves the divider on its
        # hardware defaults (`interface.adoc`), so those defaults are first written as
        # real values; after that only the numerator field differs between the
        # settings written, so the divider sees a numerator change with the divisor
        # unchanged.
        cfg1 = (
            reset_cfg1 & ~(NUMERATOR_BM | DIVIDER_BM)
            | ((HALF_NUMERATOR << NUMERATOR_BP) & NUMERATOR_BM)
            | ((DEFAULT_DIVISOR << DIVIDER_BP) & DIVIDER_BM)
        )
        await self.csr_write(f"{label}_BASE_OFF", AVS_CFG_1, reset_cfg1 | PREMUX_OFF_BM)
        await self.csr_write(f"{label}_BASE_SET_OFF", AVS_CFG_1, cfg1 | PREMUX_OFF_BM)
        await self.csr_write(f"{label}_BASE", AVS_CFG_1, cfg1)
        await ClockCycles(cocotb.top.clk_smc_i, 200)
        before = await self._duty(f"{label}_BEFORE")
        changed = (cfg1 & ~NUMERATOR_BM) | ((QUARTER_NUMERATOR << NUMERATOR_BP) & NUMERATOR_BM)
        await self.csr_write(f"{label}_OFF", AVS_CFG_1, cfg1 | PREMUX_OFF_BM)
        await self.csr_write(f"{label}_SET_OFF", AVS_CFG_1, changed | PREMUX_OFF_BM)
        await self.csr_write(f"{label}_SET", AVS_CFG_1, changed)
        await self.csr_read(f"{label}_SET_RB", AVS_CFG_1, expected=changed)
        await ClockCycles(cocotb.top.clk_smc_i, 200)
        after = await self._duty(f"{label}_AFTER")
        assert abs(after - QUARTER_NUMERATOR / 256) <= 0.05 and abs(before - 0.5) <= 0.05, (
            f"{label}: the AVS clock was {100 * before:.1f}% high before and "
            f"{100 * after:.1f}% after a numerator of 0x{QUARTER_NUMERATOR:02x}"
        )
        restored = (changed & ~NUMERATOR_BM) | ((HALF_NUMERATOR << NUMERATOR_BP) & NUMERATOR_BM)
        await self.csr_write(f"{label}_BACK_OFF", AVS_CFG_1, changed | PREMUX_OFF_BM)
        await self.csr_write(f"{label}_BACK_SET_OFF", AVS_CFG_1, restored | PREMUX_OFF_BM)
        await self.csr_write(f"{label}_BACK", AVS_CFG_1, restored)
        await ClockCycles(cocotb.top.clk_smc_i, 200)
        back = await self._duty(f"{label}_RESTORED")
        assert abs(back - 0.5) <= 0.05, (
            f"{label}: the AVS clock was {100 * back:.1f}% high after the numerator went back "
            f"to 0x{HALF_NUMERATOR:02x}"
        )
        cocotb.log.info(
            "CHK-AVS-SLAVE-NUMERATOR: with only AVS_CFG_1.CLK_DIVIDER_DUTY_CYCLE_NUMERATOR "
            "changing, the AVS clock at the pad went from %.1f%% to %.1f%% high and back to "
            "%.1f%% at 0x%02x",
            100 * before,
            100 * after,
            100 * back,
            HALF_NUMERATOR,
        )

    async def _duty(self, label: str) -> float:
        """The high fraction of the AVS clock at the pad over several periods."""
        clk = cocotb.top.tb_avs_clk_from_dut
        for _ in range(4):
            await RisingEdge(clk)
        high = 0.0
        start = get_sim_time("ns")
        rose = start
        for _ in range(DUTY_PERIODS):
            await FallingEdge(clk)
            high += get_sim_time("ns") - rose
            await RisingEdge(clk)
            rose = get_sim_time("ns")
        assert rose > start, f"{label}: the AVS clock did not run"
        return high / (rose - start)

    async def _resync_busy_leg(self) -> None:
        """Request a slave resync while commands are still going out."""
        assert self.driver is not None
        label = "RESYNC_BUSY"
        await self._set_retries(label, 0)
        good = self._word("GOOD")
        count = 2 * BUSY_COMMANDS
        self._send(*([good] * count))
        masters = len(self.driver.masters)
        for index in range(BUSY_COMMANDS):
            await self.csr_write(f"{label}_CMD{index}", AVS_CMD, CMD_A)
        cfg1 = await self.csr_read(f"{label}_CFG1", AVS_CFG_1)
        await self.csr_write(f"{label}_FORCE", AVS_CFG_1, cfg1 | FORCE_RESYNC_BM)
        for index in range(BUSY_COMMANDS, count):
            await self.csr_write(f"{label}_MORE{index}", AVS_CMD, CMD_B)
        got = [await self._pop(f"{label}_DRAIN{index}") for index in range(count)]
        await self._await_idle(label)
        assert all(w & READBACK_FIELDS == good & READBACK_FIELDS for w in got), (
            f"{label}: the replies drained were {[hex(w) for w in got]}"
        )
        assert len(self.driver.masters) - masters == count, (
            f"{label}: {len(self.driver.masters) - masters} master subframes for {count} commands"
        )
        empty = await self._readback_refused(f"{label}_EMPTY")
        assert empty != 0, (
            f"{label}: AVS_READBACK read with the FIFO empty was answered OKAY; the block "
            f"refuses it"
        )
        cocotb.log.info(
            "CHK-AVS-SLAVE-RESYNC-BUSY: a slave resync forced while %d commands were still "
            "going out, with %d more queued behind it and the replies drained as they came, "
            "left all %d commands answered intact; AVS_READBACK read empty was then refused "
            "(response %d)",
            BUSY_COMMANDS,
            BUSY_COMMANDS,
            count,
            empty,
        )

    async def _readback_refused(self, label: str) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = AVS_READBACK_REG
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: the read got no response"
        return item.resp_code

    async def body(self) -> None:
        self.cfg0 = await self.csr_read("AVS_CFG_0_SAVE", AVS_CFG_0)
        await self.csr_write("MASK_ALL", AVS_INTERRUPT_MASK, MASK_ALL)
        self.driver = AvsReplyDriver(default=reply(ACK_GOOD, 0, 0))
        await self._set_retries("LEARN", 0)
        await self._await_idle("START")

        for shape in SHAPES:
            await self._learn_crc(shape)
        cocotb.log.info(
            "CHK-AVS-SLAVE-CRC-ONE-GOOD: for each of %d reply shapes exactly one of the eight "
            "CRC-3 codes updated AVS_LATEST_SLAVE_SUBFRAME (%s); the other seven reached "
            "AVS_READBACK with MAX_RETRIES at 0 and left it unchanged",
            len(SHAPES),
            ", ".join(f"{k}={v}" for k, v in self.good_crc.items()),
        )

        await self._good_leg()
        cocotb.log.info(
            "CHK-AVS-SLAVE-READBACK: a good reply 0x%08x reached AVS_READBACK and "
            "AVS_LATEST_SLAVE_SUBFRAME unchanged, and AVS_SLAVE_STATUS showed its acknowledge "
            "and status",
            self._word("GOOD"),
        )
        await self._exhaust_leg()
        await self._recover_leg()
        cocotb.log.info(
            "CHK-AVS-SLAVE-RETRY-CODES: three unavailable replies against a budget of 2 sent "
            "the same command three times, raised TOTAL_RETRIES by 2 and "
            "MAX_RETRIES_ATTEMPTED_INT as the only unmasked source; a bad-CRC acknowledge "
            "followed by a good reply cost one retry and delivered the good one"
        )
        await self._bad_data_leg()
        await self._not_valid_leg()
        cocotb.log.info(
            "CHK-AVS-SLAVE-NO-RETRY: acknowledge 3 was delivered at once with no retry and "
            "shown in AVS_SLAVE_STATUS, and a reply with the frame-valid bit set raised "
            "SLAVE_UNRESPONSIVE_INT as the only unmasked source"
        )

        good = self._word("GOOD")
        kept = await self._buffered_leg("BUFFER_GOOD", self._word("GOOD_2"), False)
        assert [w & READBACK_FIELDS for w in kept] == [
            good & READBACK_FIELDS,
            self._word("GOOD_2") & READBACK_FIELDS,
        ], (
            f"BUFFER_GOOD: the readback order was {[hex(w) for w in kept]}; the retried "
            f"command's good reply comes first, then the one that waited"
        )
        unavailable = self._word("UNAVAILABLE")
        spent = await self._buffered_leg("BUFFER_SPENT", unavailable, True)
        assert [w & READBACK_FIELDS for w in spent] == [
            good & READBACK_FIELDS,
            unavailable & READBACK_FIELDS,
        ], (
            f"BUFFER_SPENT: the readback order was {[hex(w) for w in spent]}; with MAX_RETRIES "
            f"cleared during the retry, the reply that waited is delivered unretried"
        )
        cocotb.log.info(
            "CHK-AVS-SLAVE-BUFFERED: with two commands back to back and the first retried, "
            "the second's reply waited and was delivered after the retry's good reply when "
            "it was good, and delivered as it was, unavailable, when MAX_RETRIES was cleared "
            "during the retry"
        )

        await self._stall_leg()
        await self._slave_interrupt_leg()
        await self._interrupt_launch_leg()
        await self._mask_leg()
        await self._overflow_leg()
        await self._resync_busy_leg()
        await self._numerator_leg()
        self.driver.stop()
        await self.csr_write("AVS_CFG_0_RESTORE", AVS_CFG_0, self.cfg0)
