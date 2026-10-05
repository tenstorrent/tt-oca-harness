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
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_avsbus_protocol_utils import (
    AVS_BUS_IS_IDLE_BM,
    AVS_CFG_1,
    AVS_CMD,
    AVS_FIFOS_STATUS,
    AVS_INTERRUPT,
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
    build_avs_cmd,
    expected_master_subframe,
    fifo_field,
    set_avs_sdata,
)
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


class smc_avsbus_frame_transaction_test_seq(SmcCsrSeq):
    """Queue three AVSBus commands against a responding target and collect them."""

    def __init__(self, name: str = "smc_avsbus_frame_transaction_test_seq") -> None:
        super().__init__(name)
        self.fsm = AvsFsmMonitor()
        self.mdata = AvsMdataMonitor()
        self.frames_matched = 0

    async def body(self) -> None:
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
