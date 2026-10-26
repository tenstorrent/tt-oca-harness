# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus command-to-response transaction set over the protocol pins.

Three AVS_CMD words are queued over the SEP_IN AXI path while the bench holds
the AVSBus sdata pad low. ``hw/ip/avsbus_controller/doc/interface.adoc``
"AVSBus Slave Subframe" gives the reply that level presents: slave
acknowledgment 0 (action performed), frame valid bit 0 (the target did
respond), and ``architecture.adoc`` "CRC Verification Engine" states the check
instance "reports a good check when the result is zero" -- which the all-zero
subframe satisfies, a CRC being linear over the frame it is appended to. So
the controller must take the accept path: no retry, a response pushed into the
readback FIFO per command, and a return to idle.

Four DUT-produced observables carry the proof, none of them the stimulus:

* the FSM debug bus walks the main command path, from the resync through the
  first, mid and last subframe shifts,
* the serial master subframe on the AVSBus pads matches the queued AVS_CMD
  words bit for bit outside the hardware CRC-3,
* the command FIFO drains to empty and the readback FIFO fills to exactly one
  entry per command, then empties one entry per AVS_READBACK read,
* the retry and unresponsive indicators stay clear, which
  ``smc_avsbus_retry_exhaust_test`` drives to 1 on the same registers.

``AVS_CFG_1.STOP_AVS_CLOCK_ON_IDLE`` is set so the launch is deterministic:
``architecture.adoc`` "Clock Generation and Management" states that
"restarting a gated AVS clock always begins with a slave resync", so
the first command leaves idle through the resync and the post-resync launch
state instead of racing an unsolicited resync interval.

The response *word* is not compared. The readback register returns 0 both for
the all-zero subframe and for an empty FIFO, so a data compare there would not
discriminate; the discriminating observables are the AXI response code (the
empty-FIFO read is an error termination, checked by
``smc_sideband_protocol_smoke_test``) and the occupancy counts.

After those legs the sdata pad is handed to ``AvsReplyDriver``, the
bit-by-bit responder of ``smc_avsbus_slave_reply_test``, with
``AVS_CFG_0.MAX_RETRIES`` at 0:

* two CmdGroup 1 writes and one CmdGroup 0 write with non-zero CMD_DATA go out
  and each captured master subframe must carry the ``2'b01`` preamble and the
  written AVS_CMD bits [29:3]; their CRC-3 bits are logged only, since no
  pinned source gives the polynomial (SF-030),
* a reply with StatusResponse bit 1 is sent with each of the eight CRC codes:
  ``architecture.adoc`` "CRC Verification Engine" lets exactly one pass the
  check, and only that one may update ``AVS_LATEST_SLAVE_SUBFRAME`` and
  ``AVS_SLAVE_STATUS``; ``AVS_SLAVE_ISSUED_INTERRUPT`` is logged only (SF-028),
* a StatusResponse-0 reply is swept over the codes until one is accepted, which
  must clear ``AVS_SLAVE_STATUS`` bit 1,
* with ``MAX_RETRIES`` at 1 a rejected code is answered by one retry of the
  same subframe, and only the accepted retry reply updates the status latch.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_avsbus_protocol_utils import (
    AVS_BUS_IS_IDLE_BM,
    AVS_CFG_0,
    AVS_CFG_1,
    AVS_CMD,
    AVS_FIFOS_STATUS,
    AVS_INTERRUPT,
    AVS_INTERRUPT_CLEAR,
    AVS_NORMAL_STATUS,
    AVS_READBACK,
    CMD_FIFO_DEPTH,
    CMD_FIFO_EMPTY_BM,
    CMD_FIFO_OCCUPIED_BM,
    CMD_FIFO_OCCUPIED_BP,
    CMD_FIFO_VACANT_BM,
    CMD_FIFO_VACANT_BP,
    CMD_TYPE_READ,
    MASTER_IS_RETRYING_BM,
    MAX_RETRIES_ATTEMPTED_BM,
    MAX_RETRIES_BM,
    MAX_RETRIES_BP,
    RB_FIFO_DEPTH,
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
    RB_FIFO_VACANT_BM,
    RB_FIFO_VACANT_BP,
    READ_CMD_DATA,
    READBACK_HAS_DATA_BM,
    SLAVE_UNRESPONSIVE_BM,
    STOP_AVS_CLOCK_ON_IDLE_BM,
    TOTAL_RETRIES_BM,
    TOTAL_RETRIES_BP,
    AvsFsmMonitor,
    AvsMdataMonitor,
    avs_field,
    build_avs_cmd,
    expected_master_subframe,
    fifo_field,
    set_avs_sdata,
)
from .smc_avsbus_slave_reply_test_seq import AvsReplyDriver, reply
from .smc_csr_seq_utils import SmcCsrSeq

# interface.adoc "AVSBus Command Codes (Command Group 0)": 0x2 rail current,
# 0x3 temperature and 0xF AVSBus version are read-only data types, so all three
# commands are reads. Distinct rail selects keep the three master subframes
# distinguishable from one another on the wire.
AVS_COMMANDS = [
    ("RAIL_CURRENT", build_avs_cmd(CMD_TYPE_READ, 0, 0x2, 0x1, READ_CMD_DATA)),
    ("TEMPERATURE", build_avs_cmd(CMD_TYPE_READ, 0, 0x3, 0x2, READ_CMD_DATA)),
    ("AVSBUS_VERSION", build_avs_cmd(CMD_TYPE_READ, 0, 0xF, 0x4, READ_CMD_DATA)),
]
COMMAND_COUNT = len(AVS_COMMANDS)

# The command path the three queued commands must walk, named per
# architecture.adoc "Protocol State Machine". The first command leaves idle
# through the resync, the second overlaps transmit with receive in the mid
# states, and the third drains as the last subframe.
#
# Only the states that last a whole subframe are listed. The debug bus crosses
# two handshake data synchronizers on its way to the bench -- avs_clk to the
# register clock inside the controller, then to the SMC clock -- and a
# handshake sync forwards the value it holds when a transfer opens, so a state
# occupying one AVS clock can pass between two transfers and never appear. The
# single-cycle end-of-subframe states are therefore not directly observable
# here; what stands in for them is their effect, since the spec's state graph
# reaches each shift state only through the end state before it, and each
# end-of-subframe state is what pushes a response into the readback FIFO.
MAIN_PATH_STATES = (
    "AVS_IDLE",
    "AVS_SLAVE_RESYNC",
    "AVS_SHIFT_1ST_SUBFRAME",
    "AVS_SHIFT_MID_SUBFRAME",
    "AVS_SHIFT_LAST_SUBFRAME",
)

# Poll bound for the whole transaction set. A subframe is 32 AVS clocks and the
# AVS clock is the reference divided by four, so three commands plus a resync
# cost a few microseconds; expiry is a failure, never a pass.
SETTLE_POLL_CYCLES = 200
SETTLE_POLL_LIMIT = 60

AVS_LATEST = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_LATEST_SLAVE_SUBFRAME_BASE_ADDR")
AVS_SLAVE_STATUS = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_SLAVE_STATUS_BASE_ADDR")
SLAVE_ISSUED_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__AVS_SLAVE_ISSUED_INTERRUPT_bm")
RB_STATUS_BM = avs_field("AVSBUS_CONTROLLER__AVS_READBACK__STATUS_RESPONSE_bm")
RB_STATUS_BP = avs_field("AVSBUS_CONTROLLER__AVS_READBACK__STATUS_RESPONSE_bp")
READBACK_FIELDS = (
    avs_field("AVSBUS_CONTROLLER__AVS_READBACK__SLAVE_ACK_bm")
    | RB_STATUS_BM
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CMD_DATA_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CRC_bm")
)
CLEAR_ALL = 0x1FF
CLEAR_SLAVE_ISSUED = 0x1

# The AVS_CMD words of the contract: CmdGroup 1 commit and hold writes of
# CMD_DATA 0xA5C3, then a CmdGroup 0 commit write of CMD_DATA 0x5A3C.
GRP1_COMMANDS = (("GRP1_COMMIT", 0x08052E18), ("GRP1_HOLD", 0x18052E18))
GRP1_DATA = 0xA5C3
GRP0_COMMAND = 0x0002D1E0
GRP0_DATA = 0x5A3C
# The command each slave-reply leg launches: a commit write broadcast to every
# rail (RAIL_SEL 0xF), with the CmdGroup 0 data.
REPLY_LEG_COMMAND = build_avs_cmd(0, 0, 0x0, 0xF, GRP0_DATA)

# Slave subframes, laid out per interface.adoc "AVSBus Slave Subframe": slave
# acknowledgment 0, frame valid, data 0xFFFF (the master issued a write).
STATUS_BIT1 = 0b00010
STATUS_BIT1_REPLY = reply(0, STATUS_BIT1, 0xFFFF)
STATUS_ZERO_REPLY = reply(0, 0b00000, 0xFFFF)
# AVS_SLAVE_STATUS after the status-bit-1 reply: AVS_SLAVE_ACK 0, response 0b00010.
SLAVE_STATUS_BIT1 = 0x00000002
CRC_CODES = 8
CRC3_MASK = 0x7


class smc_avsbus_frame_transaction_test_seq(SmcCsrSeq):
    """Queue three AVSBus commands against a responding target and collect them."""

    def __init__(self, name: str = "smc_avsbus_frame_transaction_test_seq") -> None:
        super().__init__(name)
        self.fsm = AvsFsmMonitor()
        self.mdata = AvsMdataMonitor()
        self.frames_matched = 0
        self.driver: AvsReplyDriver | None = None
        self.frame_mon = AvsMdataMonitor()
        self.waits: list[tuple[str, int, str]] = []
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []
        self.cfg0 = 0

    async def body(self) -> None:
        await self._three_command_legs()
        await self._subframe_and_status_legs()

    async def _three_command_legs(self) -> None:
        set_avs_sdata(0)
        self.fsm.start()
        self.mdata.start()

        cfg1 = await self.csr_read("AVS_CFG_1_SAVE", AVS_CFG_1)
        gated_idle = cfg1 | STOP_AVS_CLOCK_ON_IDLE_BM
        await self.csr_write("AVS_CFG_1_STOP_ON_IDLE", AVS_CFG_1, gated_idle)
        await self.csr_read("AVS_CFG_1_STOP_ON_IDLE_RB", AVS_CFG_1, expected=gated_idle)

        entry = await self.csr_read("AVS_FIFOS_STATUS_ENTRY", AVS_FIFOS_STATUS)
        assert fifo_field(entry, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP) == 0, (
            f"readback FIFO already holds "
            f"{fifo_field(entry, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)} entries before any "
            f"AVS_CMD was written (AVS_FIFOS_STATUS=0x{entry:08x})"
        )

        for name, word in AVS_COMMANDS:
            await self.csr_write(f"AVS_CMD_{name}", AVS_CMD, word)

        occupied = await self._wait_readback_occupancy(COMMAND_COUNT)
        self.fsm.stop()
        self.mdata.stop()

        status = await self.csr_read("AVS_NORMAL_STATUS_DONE", AVS_NORMAL_STATUS)
        fifos = await self.csr_read("AVS_FIFOS_STATUS_DONE", AVS_FIFOS_STATUS)
        self._check_fsm_path()
        self._check_master_subframes()
        self._check_cmd_fifo_drained(status, fifos)
        self._check_readback_filled(status, fifos, occupied)
        await self._check_readback_pops()
        await self._check_no_retry(status)

        await self.csr_write("AVS_CFG_1_RESTORE", AVS_CFG_1, cfg1)
        await self.csr_read("AVS_CFG_1_RESTORE_RB", AVS_CFG_1, expected=cfg1)
        set_avs_sdata(1)

    async def _wait_readback_occupancy(self, wanted: int, label: str = "FILL") -> int:
        """Poll AVS_FIFOS_STATUS until the readback FIFO holds ``wanted`` entries.

        The occupancy fields cross from the AVS clock to the register clock
        through a handshake data synchronizer, so the count settles some cycles
        after the event that moved it. Expiry is a failure, never a pass.
        """
        occupied = -1
        for _ in range(SETTLE_POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_POLL_CYCLES)
            word = await self.csr_read(f"AVS_FIFOS_STATUS_POLL_{label}", AVS_FIFOS_STATUS)
            occupied = fifo_field(word, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)
            if occupied == wanted:
                return occupied
        raise AssertionError(
            f"readback FIFO settled at {occupied} entries, expected {wanted} ({label}), after "
            f"{SETTLE_POLL_LIMIT * SETTLE_POLL_CYCLES} clk_smc_i cycles"
        )

    def _check_fsm_path(self) -> None:
        missing = self.fsm.missing(MAIN_PATH_STATES)
        assert not missing, (
            f"AVSBus FSM debug bus never held {', '.join(missing)} over two consecutive "
            f"clk_periph_i samples while {COMMAND_COUNT} commands were in flight; "
            f"states seen: {sorted(self.fsm.names())}"
        )
        assert self.fsm.samples > 0, "AVSBus FSM debug bus produced no resolvable sample"
        cocotb.log.info(
            "CHK-AVS-FRAME-FSM-MAIN-PATH: cur_state_debug held every one of the %d "
            "command-path states %s over two consecutive samples across %d samples "
            "(bit order transcribed from architecture.adoc 'Protocol State Machine')",
            len(MAIN_PATH_STATES),
            ", ".join(MAIN_PATH_STATES),
            self.fsm.samples,
        )

    def _check_master_subframes(self) -> None:
        frames = self.mdata.subframes()
        expected = [expected_master_subframe(word) for _, word in AVS_COMMANDS]
        assert self.mdata.clock_edges > 0, (
            "no AVS clock edge reached the bench on tb_avs_clk_from_dut, so no master "
            "subframe could be captured"
        )
        assert len(frames) == COMMAND_COUNT, (
            f"captured {len(frames)} master subframes on the AVSBus pads for "
            f"{COMMAND_COUNT} queued commands: {[f'0x{f:08x}' for f in frames]}"
        )
        for index, (frame, want) in enumerate(zip(frames, expected, strict=True)):
            name = AVS_COMMANDS[index][0]
            assert frame == want, (
                f"master subframe {index} ({name}) went out as 0x{frame:08x}, expected "
                f"0x{want:08x}: preamble 2'b01 in [31:30] and AVS_CMD[29:3] in their own bit "
                f"positions (interface.adoc 'AVSBus Master Subframe'; CRC-3 [2:0] excluded)"
            )
            self.frames_matched += 1
        cocotb.log.info(
            "CHK-AVS-MASTER-SUBFRAME: all %d master subframes on avs_mdata_o matched the "
            "queued AVS_CMD words outside the hardware CRC-3 (%s), sampled on %d DUT AVS "
            "clock edges",
            self.frames_matched,
            ", ".join(f"0x{f:08x}" for f in frames),
            self.mdata.clock_edges,
        )

    def _check_cmd_fifo_drained(self, status: int, fifos: int) -> None:
        occupied = fifo_field(fifos, CMD_FIFO_OCCUPIED_BM, CMD_FIFO_OCCUPIED_BP)
        vacant = fifo_field(fifos, CMD_FIFO_VACANT_BM, CMD_FIFO_VACANT_BP)
        assert occupied == 0, (
            f"command FIFO still holds {occupied} entries after all {COMMAND_COUNT} responses "
            f"arrived (AVS_FIFOS_STATUS=0x{fifos:08x})"
        )
        assert vacant == CMD_FIFO_DEPTH, (
            f"command FIFO reports {vacant} vacant slots, expected the full depth "
            f"{CMD_FIFO_DEPTH} from the generated AVS_FIFOS_STATUS reset"
        )
        assert status & CMD_FIFO_EMPTY_BM, (
            f"AVS_NORMAL_STATUS.CMD_FIFO_EMPTY clear with an empty command FIFO (0x{status:08x})"
        )
        assert status & AVS_BUS_IS_IDLE_BM, (
            f"AVS_NORMAL_STATUS.AVS_BUS_IS_IDLE clear after the last response (0x{status:08x})"
        )
        cocotb.log.info(
            "CHK-AVS-CMD-FIFO-DRAIN: %d queued commands left the command FIFO at 0 occupied / "
            "%d vacant with CMD_FIFO_EMPTY and AVS_BUS_IS_IDLE set (AVS_FIFOS_STATUS=0x%08x, "
            "AVS_NORMAL_STATUS=0x%08x)",
            COMMAND_COUNT,
            CMD_FIFO_DEPTH,
            fifos,
            status,
        )

    def _check_readback_filled(self, status: int, fifos: int, polled: int) -> None:
        occupied = fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)
        vacant = fifo_field(fifos, RB_FIFO_VACANT_BM, RB_FIFO_VACANT_BP)
        assert occupied == COMMAND_COUNT, (
            f"readback FIFO holds {occupied} responses for {COMMAND_COUNT} commands "
            f"(poll saw {polled}, AVS_FIFOS_STATUS=0x{fifos:08x})"
        )
        assert vacant == RB_FIFO_DEPTH - COMMAND_COUNT, (
            f"readback FIFO reports {vacant} vacant slots, expected "
            f"{RB_FIFO_DEPTH - COMMAND_COUNT} with {COMMAND_COUNT} of {RB_FIFO_DEPTH} occupied"
        )
        assert status & READBACK_HAS_DATA_BM, (
            f"AVS_NORMAL_STATUS.READBACK_HAS_DATA clear with {occupied} responses queued "
            f"(0x{status:08x})"
        )
        cocotb.log.info(
            "CHK-AVS-READBACK-FIFO-FILL: exactly %d of %d readback slots occupied after %d "
            "commands, %d vacant, READBACK_HAS_DATA set (AVS_FIFOS_STATUS=0x%08x)",
            occupied,
            RB_FIFO_DEPTH,
            COMMAND_COUNT,
            vacant,
            fifos,
        )

    async def _check_readback_pops(self) -> None:
        for index in range(COMMAND_COUNT):
            await self.csr_read(f"AVS_READBACK_POP{index}", AVS_READBACK)
            await self._wait_readback_occupancy(COMMAND_COUNT - index - 1, f"POP{index}")
        status = await self.csr_read("AVS_NORMAL_STATUS_DRAINED", AVS_NORMAL_STATUS)
        assert not status & READBACK_HAS_DATA_BM, (
            f"AVS_NORMAL_STATUS.READBACK_HAS_DATA still set after all {COMMAND_COUNT} "
            f"responses were popped (0x{status:08x})"
        )
        cocotb.log.info(
            "CHK-AVS-READBACK-POP: %d AVS_READBACK reads each returned OKAY on a non-empty "
            "FIFO and advanced the occupancy %d -> 0, one entry per read, clearing "
            "READBACK_HAS_DATA (AVS_NORMAL_STATUS=0x%08x)",
            COMMAND_COUNT,
            COMMAND_COUNT,
            status,
        )

    async def _check_no_retry(self, status: int) -> None:
        retries = fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)
        assert retries == 0, (
            f"AVS_NORMAL_STATUS.TOTAL_RETRIES is {retries} after {COMMAND_COUNT} commands the "
            f"target acknowledged with a valid frame (0x{status:08x})"
        )
        assert not status & MASTER_IS_RETRYING_BM, (
            f"AVS_NORMAL_STATUS.AVS_MASTER_IS_RETRYING set once the bus returned to idle "
            f"(0x{status:08x})"
        )
        interrupt = await self.csr_read("AVS_INTERRUPT_DONE", AVS_INTERRUPT)
        raised = interrupt & (SLAVE_UNRESPONSIVE_BM | MAX_RETRIES_ATTEMPTED_BM)
        assert raised == 0, (
            f"AVS_INTERRUPT raised 0x{raised:02x} of SLAVE_UNRESPONSIVE_INT / "
            f"MAX_RETRIES_ATTEMPTED_INT against a target that acknowledged every command "
            f"(0x{interrupt:08x})"
        )
        cocotb.log.info(
            "CHK-AVS-VALID-ACK-NO-RETRY: TOTAL_RETRIES == 0, AVS_MASTER_IS_RETRYING clear and "
            "neither SLAVE_UNRESPONSIVE_INT nor MAX_RETRIES_ATTEMPTED_INT raised across %d "
            "acknowledged commands (AVS_NORMAL_STATUS=0x%08x, AVS_INTERRUPT=0x%08x); "
            "smc_avsbus_retry_exhaust_test drives all three to 1 on the same registers",
            COMMAND_COUNT,
            status,
            interrupt,
        )

    # ------------------------------------------------------------------
    # Subframe content and slave status legs (S1-S7)
    # ------------------------------------------------------------------

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))

    def _chk(self, term: str, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, term, int(get_sim_time("ps"))))

    @staticmethod
    def _raw_frames(bits: list[int]) -> list[int]:
        """Every complete 32-bit master subframe in ``bits``, CRC-3 included.

        Bits are taken most significant first, so the first wire bit lands in
        bit 31; a frame starts at each low bit outside a frame, as in
        ``AvsMdataMonitor.subframes``, and a window holding X/Z fails.
        """
        frames: list[int] = []
        index = 0
        while index + 32 <= len(bits):
            if bits[index] != 0:
                index += 1
                continue
            window = bits[index : index + 32]
            assert all(bit >= 0 for bit in window), (
                f"master subframe starting at AVS clock {index} carries X/Z on avs_mdata_o: "
                f"{window}"
            )
            word = 0
            for bit in window:
                word = (word << 1) | bit
            frames.append(word)
            index += 32
        return frames

    async def _wait_occupancy(self, label: str, wanted: int) -> None:
        bound = SETTLE_POLL_LIMIT * SETTLE_POLL_CYCLES
        occupied = await self._wait_readback_occupancy(wanted, label)
        self.waits.append((f"readback_poll_{label}", bound, f"occupied={occupied}"))

    async def _pop_one(self, label: str) -> int:
        """Wait for one readback entry, pop it, and wait for the FIFO to read empty."""
        await self._wait_occupancy(f"{label}_FILL", 1)
        word = await self.csr_read(f"{label}_READBACK", AVS_READBACK)
        await self._wait_occupancy(f"{label}_POP", 0)
        return word

    async def _set_max_retries(self, label: str, budget: int) -> None:
        want = (self.cfg0 & ~MAX_RETRIES_BM) | ((budget << MAX_RETRIES_BP) & MAX_RETRIES_BM)
        await self.csr_write(f"{label}_CFG0", AVS_CFG_0, want)
        await self.csr_read(f"{label}_CFG0_RB", AVS_CFG_0, expected=want)

    async def _total_retries(self, label: str) -> int:
        status = await self.csr_read(f"{label}_NORMAL", AVS_NORMAL_STATUS)
        return fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)

    def _replies_consumed(self, label: str) -> None:
        assert self.driver is not None
        assert not self.driver.replies, (
            f"{label}: {len(self.driver.replies)} queued slave replies were never asked for; "
            f"the controller sent fewer master subframes than commands and retries"
        )

    async def _capture_commands(self, label: str, words: list[tuple[str, int]]) -> list[int]:
        """Launch ``words`` against the default reply and return their raw subframes."""
        mon = AvsMdataMonitor()
        mon.start()
        for name, word in words:
            await self.csr_write(f"{label}_{name}", AVS_CMD, word)
        await self._wait_occupancy(f"{label}_FILL", len(words))
        mon.stop()
        for index in range(len(words)):
            await self.csr_read(f"{label}_READBACK{index}", AVS_READBACK)
            await self._wait_occupancy(f"{label}_POP{index}", len(words) - index - 1)
        frames = self._raw_frames(mon.bits)
        assert mon.clock_edges > 0, f"{label}: no AVS clock edge reached tb_avs_clk_from_dut"
        assert len(frames) == len(words), (
            f"{label}: captured {len(frames)} full 32-bit master subframes for {len(words)} "
            f"commands: {[f'0x{f:08x}' for f in frames]}"
        )
        return frames

    @staticmethod
    def _check_subframe(label: str, frame: int, word: int, grp: int, data: int) -> None:
        assert frame & ~CRC3_MASK == expected_master_subframe(word), (
            f"{label}: master subframe 0x{frame:08x} differs from the preamble 2'b01 and "
            f"AVS_CMD[29:3] of 0x{word:08x} (expected 0x{expected_master_subframe(word):08x} "
            f"outside CRC-3)"
        )
        assert (frame >> 30) & 0x3 == 0b01, f"{label}: preamble bits 31:30 of 0x{frame:08x}"
        assert (frame >> 27) & 0x1 == grp, f"{label}: bit 27 of 0x{frame:08x} is not {grp}"
        assert (frame >> 3) & 0xFFFF == data, (
            f"{label}: bits 18:3 of 0x{frame:08x} are not CMD_DATA 0x{data:04x}"
        )

    async def _send_and_pop(self, label: str, word: int) -> tuple[int, int, int, int, int]:
        """Answer one command with ``word``; return LATEST/STATUS before and after, READBACK."""
        assert self.driver is not None
        latest_before = await self.csr_read(f"{label}_LATEST_BEFORE", AVS_LATEST)
        status_before = await self.csr_read(f"{label}_SLAVE_STATUS_BEFORE", AVS_SLAVE_STATUS)
        self.driver.replies.append(word)
        await self.csr_write(f"{label}_CMD", AVS_CMD, REPLY_LEG_COMMAND)
        readback = await self._pop_one(label)
        self._replies_consumed(label)
        latest = await self.csr_read(f"{label}_LATEST", AVS_LATEST)
        status = await self.csr_read(f"{label}_SLAVE_STATUS", AVS_SLAVE_STATUS)
        return latest_before, status_before, latest, status, readback

    async def _subframe_and_status_legs(self) -> None:
        # S1: responder on sdata, MAX_RETRIES 0, interrupt status cleared.
        self.cfg0 = await self.csr_read("S1_CFG0_SAVE", AVS_CFG_0)
        self.driver = AvsReplyDriver(default=reply(0, 0, 0))
        await self._set_max_retries("S1", 0)
        await self.csr_write("S1_INTR_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        self._stamp("BRINGUP")

        # S2: CmdGroup 1 commit and hold writes.
        grp1 = await self._capture_commands("S2", list(GRP1_COMMANDS))
        for (name, word), frame in zip(GRP1_COMMANDS, grp1, strict=True):
            self._check_subframe(f"S2_{name}", frame, word, 1, GRP1_DATA)
        assert [(f >> 28) & 0x3 for f in grp1] == [0, 1], (
            f"S2: command type bits 29:28 of {[f'0x{f:08x}' for f in grp1]} are not 0 then 1"
        )
        self._chk(
            "AVS_GRP1_SUBFRAME",
            "CHK-AVS-GRP1-SUBFRAME",
            "subframes %s for AVS_CMD %s carry 31:30=01, bit27=1, 18:3=0x%04x, 29:28=0 then 1, "
            "and bits 29:3 equal AVS_CMD[29:3]; shift_order=msb_first (first wire bit is bit 31) "
            "measured, LINKED-ISSUE SF-030"
            % (
                ",".join(f"0x{f:08x}" for f in grp1),
                ",".join(f"0x{w:08x}" for _, w in GRP1_COMMANDS),
                GRP1_DATA,
            ),
        )
        self._stamp("AVS_GRP1_SUBFRAME")

        # S3: CmdGroup 0 commit write; CRC-3 of all three subframes logged.
        (grp0,) = await self._capture_commands("S3", [("GRP0_COMMIT", GRP0_COMMAND)])
        self._check_subframe("S3_GRP0_COMMIT", grp0, GRP0_COMMAND, 0, GRP0_DATA)
        self._chk(
            "AVS_GRP0_SUBFRAME",
            "CHK-AVS-GRP0-SUBFRAME",
            "subframe 0x%08x for AVS_CMD 0x%08x carries 31:30=01, bit27=0, 18:3=0x%04x and bits "
            "29:3 equal AVS_CMD[29:3], shifted msb first" % (grp0, GRP0_COMMAND, GRP0_DATA),
        )
        crcs = [
            (name, frame & CRC3_MASK)
            for name, frame in zip(
                [n for n, _ in GRP1_COMMANDS] + ["GRP0_COMMIT"], grp1 + [grp0], strict=True
            )
        ]
        self._chk(
            "AVS_GRP0_SUBFRAME",
            "CHK-AVS-SUBFRAME-CRC-OBS",
            "%s (32 bits captured per subframe; measure and log, no CRC model compared; "
            "LINKED-ISSUE SF-030)" % ", ".join(f"crc3_{n}=0b{c:03b}" for n, c in crcs),
        )
        self._stamp("AVS_GRP0_SUBFRAME")

        # S4: status-bit-1 reply with each CRC code.
        accepted: list[int] = []
        rejected_s4: list[int] = []
        intr_set = intr_cleared = -1
        for code in range(CRC_CODES):
            word = STATUS_BIT1_REPLY | code
            label = f"S4_C{code}"
            latest_before, status_before, latest, status, readback = await self._send_and_pop(
                label, word
            )
            intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
            cocotb.log.info(
                "%s: reply 0x%08x -> LATEST 0x%08x (was 0x%08x), AVS_SLAVE_STATUS 0x%08x "
                "(was 0x%08x), AVS_READBACK 0x%08x, AVS_INTERRUPT 0x%08x",
                label,
                word,
                latest,
                latest_before,
                status,
                status_before,
                readback,
                intr,
            )
            if latest == word:
                accepted.append(code)
                assert status == SLAVE_STATUS_BIT1, (
                    f"{label}: AVS_SLAVE_STATUS 0x{status:08x} after the accepted status-bit-1 "
                    f"reply, expected 0x{SLAVE_STATUS_BIT1:08x}"
                )
                assert (latest >> 25) & 1, f"{label}: LATEST bit 25 clear in 0x{latest:08x}"
                assert (readback & RB_STATUS_BM) >> RB_STATUS_BP == STATUS_BIT1, (
                    f"{label}: AVS_READBACK 0x{readback:08x} bits 28:24 are not 0b00010"
                )
                assert readback & READBACK_FIELDS == word & READBACK_FIELDS, (
                    f"{label}: AVS_READBACK 0x{readback:08x} is not the accepted reply 0x{word:08x}"
                )
                intr_set = intr
                await self.csr_write(f"{label}_INTR_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_SLAVE_ISSUED)
                intr_cleared = await self.csr_read(f"{label}_INTR_AFTER_CLEAR", AVS_INTERRUPT)
            else:
                rejected_s4.append(code)
                assert (latest, status) == (latest_before, status_before), (
                    f"{label}: rejected CRC code {code} changed LATEST 0x{latest_before:08x} -> "
                    f"0x{latest:08x} or AVS_SLAVE_STATUS 0x{status_before:08x} -> 0x{status:08x}"
                )
        assert len(accepted) == 1, (
            f"S4: {len(accepted)} of the eight CRC codes ({accepted}) updated "
            f"AVS_LATEST_SLAVE_SUBFRAME for reply 0x{STATUS_BIT1_REPLY:08x}; exactly one passes"
        )
        good = accepted[0]
        self._chk(
            "AVS_SLAVE_BIT1",
            "CHK-AVS-SLAVE-INT-OBS",
            "avs_slave_issued_interrupt_after_accept=%d avs_interrupt=0x%08x; "
            "avs_slave_issued_interrupt_after_clear=%d avs_interrupt=0x%08x (measure and log; "
            "LINKED-ISSUE SF-028)"
            % (
                int(bool(intr_set & SLAVE_ISSUED_BM)),
                intr_set,
                int(bool(intr_cleared & SLAVE_ISSUED_BM)),
                intr_cleared,
            ),
        )
        self._stamp("AVS_SLAVE_BIT1")

        # S5: status-0 reply swept until one code is accepted.
        cleared_code = -1
        cleared_status = -1
        rejected_s5: list[int] = []
        for code in range(CRC_CODES):
            word = STATUS_ZERO_REPLY | code
            label = f"S5_C{code}"
            latest_before, status_before, latest, status, _ = await self._send_and_pop(label, word)
            if latest == word:
                cleared_code, cleared_status = code, status
                break
            rejected_s5.append(code)
            assert (latest, status) == (latest_before, status_before), (
                f"{label}: rejected CRC code {code} changed LATEST 0x{latest_before:08x} -> "
                f"0x{latest:08x} or AVS_SLAVE_STATUS 0x{status_before:08x} -> 0x{status:08x}"
            )
        assert cleared_code >= 0, (
            f"S5: none of the eight CRC codes updated AVS_LATEST_SLAVE_SUBFRAME for reply "
            f"0x{STATUS_ZERO_REPLY:08x}"
        )
        assert not cleared_status & 0x2, (
            f"S5: AVS_SLAVE_STATUS 0x{cleared_status:08x} keeps bit 1 after the accepted "
            f"status-0 reply 0x{STATUS_ZERO_REPLY | cleared_code:08x}"
        )
        self._chk(
            "AVS_SLAVE_BIT1_CLEAR",
            "CHK-AVS-SLAVE-STATUS-BIT1",
            "exactly one of 8 codes (crc=%d) latched reply 0x%08x into AVS_LATEST_SLAVE_SUBFRAME "
            "(bit 25=1) with AVS_SLAVE_STATUS=0x%08x and AVS_READBACK[28:24]=0b00010; the "
            "status-0 reply 0x%08x (crc=%d) was accepted and AVS_SLAVE_STATUS read 0x%08x "
            "(bit 1=0)"
            % (
                good,
                STATUS_BIT1_REPLY | good,
                SLAVE_STATUS_BIT1,
                STATUS_ZERO_REPLY | cleared_code,
                cleared_code,
                cleared_status,
            ),
        )
        self._stamp("AVS_SLAVE_BIT1_CLEAR")

        # S6: one retry, the rejected first reply followed by the accepted retry reply.
        bad = (good + 1) % CRC_CODES
        first = STATUS_BIT1_REPLY | bad
        second = STATUS_BIT1_REPLY | good
        await self._set_max_retries("S6", 1)
        retries_before = await self._total_retries("S6_BEFORE")
        latest_before = await self.csr_read("S6_LATEST_BEFORE", AVS_LATEST)
        mon = AvsMdataMonitor()
        mon.start()
        self.driver.replies.extend((first, second))
        await self.csr_write("S6_CMD", AVS_CMD, REPLY_LEG_COMMAND)
        latest = latest_before
        for _ in range(SETTLE_POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_POLL_CYCLES)
            latest = await self.csr_read("S6_LATEST_POLL", AVS_LATEST)
            if latest == second:
                break
        else:
            normal = await self.csr_read("S6_NORMAL_EXPIRED", AVS_NORMAL_STATUS)
            raise AssertionError(
                f"S6: AVS_LATEST_SLAVE_SUBFRAME stayed 0x{latest:08x}, not the retry reply "
                f"0x{second:08x}, after {SETTLE_POLL_LIMIT * SETTLE_POLL_CYCLES} clk_smc_i cycles "
                f"(AVS_NORMAL_STATUS=0x{normal:08x}, replies left {len(self.driver.replies)})"
            )
        self.waits.append(
            (
                "retry_completion_S6",
                SETTLE_POLL_LIMIT * SETTLE_POLL_CYCLES,
                f"latest=0x{latest:08x}",
            )
        )
        await self._wait_readback_occupancy_at_least("S6_FILL", 1)
        popped = await self._drain("S6")
        mon.stop()
        self._replies_consumed("S6")
        retries_after = await self._total_retries("S6_AFTER")
        status = await self.csr_read("S6_SLAVE_STATUS", AVS_SLAVE_STATUS)
        frames = self._raw_frames(mon.bits)
        assert latest_before != second, f"S6: LATEST already held 0x{second:08x} before S6"
        assert retries_after - retries_before == 1, (
            f"S6: TOTAL_RETRIES {retries_before} -> {retries_after}; one rejected CRC with "
            f"MAX_RETRIES=1 costs exactly one retry"
        )
        assert len(frames) == 2 and frames[0] == frames[1], (
            f"S6: master subframes {[f'0x{f:08x}' for f in frames]}; the command and its one "
            f"retry are two identical subframes"
        )
        assert frames[0] & ~CRC3_MASK == expected_master_subframe(REPLY_LEG_COMMAND), (
            f"S6: master subframe 0x{frames[0]:08x} is not AVS_CMD 0x{REPLY_LEG_COMMAND:08x}"
        )
        assert status == SLAVE_STATUS_BIT1, (
            f"S6: AVS_SLAVE_STATUS 0x{status:08x} after the accepted retry reply, expected "
            f"0x{SLAVE_STATUS_BIT1:08x}"
        )
        self._chk(
            "AVS_SLAVE_BAD_CRC",
            "CHK-AVS-SLAVE-BAD-CRC",
            "%d rejected replies (S4 codes %s, S5 codes %s) left AVS_LATEST_SLAVE_SUBFRAME and "
            "AVS_SLAVE_STATUS at their prior values; with MAX_RETRIES=1 the rejected code %d "
            "cost one retry (TOTAL_RETRIES %d -> %d, subframes %s identical) and the accepted "
            "retry (code %d, found by the one-of-eight rule) set LATEST 0x%08x -> 0x%08x, "
            "AVS_SLAVE_STATUS=0x%08x; readback popped %s"
            % (
                len(rejected_s4) + len(rejected_s5),
                ",".join(str(c) for c in rejected_s4),
                ",".join(str(c) for c in rejected_s5) or "none",
                bad,
                retries_before,
                retries_after,
                ",".join(f"0x{f:08x}" for f in frames),
                good,
                latest_before,
                latest,
                status,
                ",".join(f"0x{w:08x}" for w in popped),
            ),
        )
        self._stamp("AVS_SLAVE_BAD_CRC")

        await self._set_max_retries("END", fifo_field(self.cfg0, MAX_RETRIES_BM, MAX_RETRIES_BP))
        await self.csr_write("END_INTR_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        self.driver.stop()

        # S7: every bounded wait above, with its bound and last observed state.
        self._chk(
            "TIMEOUT",
            "CHK-TIMEOUT-PATHS",
            "%d bounded waits, each raising AssertionError with its last observed state on "
            "expiry (bounds in clk_smc_i cycles): %s"
            % (len(self.waits), "; ".join(f"{n} bound={b} last={s}" for n, b, s in self.waits)),
        )
        self._check_fence()

    async def _wait_readback_occupancy_at_least(self, label: str, wanted: int) -> int:
        occupied = -1
        bound = SETTLE_POLL_LIMIT * SETTLE_POLL_CYCLES
        for _ in range(SETTLE_POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_POLL_CYCLES)
            word = await self.csr_read(f"AVS_FIFOS_STATUS_POLL_{label}", AVS_FIFOS_STATUS)
            occupied = fifo_field(word, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)
            if occupied >= wanted:
                self.waits.append((f"readback_poll_{label}", bound, f"occupied={occupied}"))
                return occupied
        raise AssertionError(
            f"{label}: readback FIFO settled at {occupied} entries, expected at least {wanted}, "
            f"after {bound} clk_smc_i cycles"
        )

    async def _drain(self, label: str) -> list[int]:
        """Pop the readback FIFO to empty, one entry per read, each pop confirmed by a poll."""
        popped: list[int] = []
        for index in range(RB_FIFO_DEPTH + 1):
            fifos = await self.csr_read(f"{label}_DRAIN_FIFOS{index}", AVS_FIFOS_STATUS)
            occupied = fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)
            if occupied == 0:
                return popped
            popped.append(await self.csr_read(f"{label}_DRAIN_READBACK{index}", AVS_READBACK))
            await self._wait_occupancy(f"{label}_DRAIN{index}", occupied - 1)
        raise AssertionError(f"{label}: the readback FIFO did not empty after {len(popped)} pops")

    def _check_fence(self) -> None:
        terms = [t for t, _ in self.stamps]
        order = [
            "BRINGUP",
            "AVS_GRP1_SUBFRAME",
            "AVS_GRP0_SUBFRAME",
            "AVS_SLAVE_BIT1",
            "AVS_SLAVE_BIT1_CLEAR",
            "AVS_SLAVE_BAD_CRC",
        ]
        assert terms == order, f"fence terms {terms} out of order, expected {order}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"fence stamps not strictly increasing: {times}"
        )
        stamp_of = dict(self.stamps)
        for chk_id, term, when in self.chk_lines:
            if term not in stamp_of:
                continue
            index = order.index(term)
            assert when <= stamp_of[term], f"{chk_id} printed after its fence term {term}"
            assert when > stamp_of[order[index - 1]], f"{chk_id} printed before its step ran"
        ids = [c for c, _, _ in self.chk_lines]
        cocotb.log.info(
            "CHK-NONVAC: ordered fence existing legs (CHK-AVS-VALID-ACK-NO-RETRY) < %s; "
            "checker lines %s; stamps %s",
            " < ".join(order),
            ",".join(ids),
            ",".join(f"{t}={s}" for t, s in self.stamps),
        )
