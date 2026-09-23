# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raising each AVSBus FIFO interrupt source and clearing it through the write-1 register.

`AVS_INTERRUPT_CLEAR` is write-only and single-pulse, so writing a bit is only
worth anything with the matching source already raised: a write with nothing
pending clears nothing and proves nothing. The retry sources are covered by
`smc_avsbus_retry_exhaust_test`; the FIFO sources are what this leaf raises.

The mechanisms come from `hw/ip/avsbus_controller/doc/architecture.adoc`
"Command and Response FIFO System" and "Error Handling and Diagnostics":

* a write to `AVS_CMD` when the command FIFO is full "is dropped and raises
  `CMD_FIFO_OVERFLOW_INT`", and `AVS_NORMAL_STATUS.CMD_FIFO_FULL` reports the
  full condition that `CMD_FIFO_FULL_INT` accompanies,
* a response pushed while the readback FIFO is full is "dropped and raises
  `READBACK_OVERFLOW_INT`", with `READBACK_FIFO_FULL_INT` for the full
  condition and `READBACK_HAS_DATA_INT` for a response waiting to be read,
* and "read of an empty readback FIFO" raises `READBACK_UNDERFLOW_INT`.

Each source is raised, observed in `AVS_INTERRUPT`, cleared through
`AVS_INTERRUPT_CLEAR`, and observed gone. Observing it gone is what gives the
write-only register a measurable effect.

The command FIFO is filled with the AVS clock gated off, so nothing drains it
while it fills and the full condition does not depend on winning a race
against the protocol engine. Depths come from the generated register header's
reset values for the vacant-slot fields, not from the design.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr
from .smc_avsbus_protocol_utils import (
    AVS_CFG_1,
    AVS_CMD,
    AVS_FIFOS_STATUS,
    AVS_INTERRUPT,
    AVS_INTERRUPT_CLEAR,
    AVS_NORMAL_STATUS,
    AVS_READBACK,
    CMD_FIFO_DEPTH,
    CMD_FIFO_OCCUPIED_BM,
    CMD_FIFO_OCCUPIED_BP,
    CMD_TYPE_READ,
    RB_FIFO_DEPTH,
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
    READ_CMD_DATA,
    avs_field,
    build_avs_cmd,
    fifo_field,
    set_avs_sdata,
)
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

CMD_FIFO_FULL_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__CMD_FIFO_FULL_INT_bm")
CMD_FIFO_OVERFLOW_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__CMD_FIFO_OVERFLOW_INT_bm")
READBACK_FIFO_FULL_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__READBACK_FIFO_FULL_INT_bm")
READBACK_UNDERFLOW_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__READBACK_UNDERFLOW_INT_bm")
READBACK_HAS_DATA_INT_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__READBACK_HAS_DATA_INT_bm")

CLEAR_CMD_FIFO_FULL_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_CMD_FIFO_FULL_INT_bm"
)
CLEAR_CMD_FIFO_OVERFLOW_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_CMD_FIFO_OVERFLOW_INT_bm"
)
CLEAR_READBACK_FIFO_FULL_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_READBACK_FIFO_FULL_INT_bm"
)
CLEAR_READBACK_UNDERFLOW_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_READBACK_UNDERFLOW_INT_bm"
)
CLEAR_READBACK_HAS_DATA_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_READBACK_HAS_DATA_INT_bm"
)

TURN_OFF_PREMUX_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__TURN_OFF_ALL_PREMUX_CLOCKS_bm")
CMD_FIFO_FULL_STATUS_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__CMD_FIFO_FULL_bm")
READBACK_FIFO_FULL_STATUS_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__READBACK_FIFO_FULL_bm"
)


# One command word per queue slot, distinguishable on the wire.
def _cmd(rail: int) -> int:
    return build_avs_cmd(CMD_TYPE_READ, 0, 0x2, rail & 0xF, READ_CMD_DATA)


POLL_CYCLES = 200
POLL_LIMIT = 200
SETTLE_CYCLES = 200


class smc_avsbus_interrupt_sources_test_seq(SmcCsrSeq):
    """Raise each AVSBus FIFO interrupt source and clear it through the write-1 register."""

    def __init__(self, name: str = "smc_avsbus_interrupt_sources_test_seq") -> None:
        super().__init__(name)
        self.raised: list[str] = []
        self.cmd_depth_seen = 0
        self.rb_depth_seen = 0

    async def _interrupt(self, label: str) -> int:
        return await self.csr_read(f"AVS_INTR_{label}", AVS_INTERRUPT)

    async def _clear_and_check(self, label: str, clear_bm: int, source_bm: int) -> int:
        """Write the clear bit, then require the source to read back gone."""
        await self.csr_write(f"AVS_CLR_{label}", AVS_INTERRUPT_CLEAR, clear_bm)
        after = 0
        for _ in range(POLL_LIMIT):
            after = await self._interrupt(f"{label}_CLEARED")
            if not after & source_bm:
                return after
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        raise AssertionError(
            f"{label}: AVS_INTERRUPT still reports 0x{after & source_bm:03x} after "
            f"AVS_INTERRUPT_CLEAR <= 0x{clear_bm:03x} (AVS_INTERRUPT=0x{after:08x})"
        )

    async def _wait_interrupt(self, label: str, source_bm: int, what: str) -> int:
        value = 0
        for _ in range(POLL_LIMIT):
            value = await self._interrupt(label)
            if value & source_bm:
                return value
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        raise AssertionError(
            f"{label}: AVS_INTERRUPT never raised 0x{source_bm:03x} after {what} "
            f"(AVS_INTERRUPT=0x{value:08x})"
        )

    # --- command FIFO full, then overflow ---------------------------------
    async def _command_fifo(self) -> None:
        cfg1 = await self.csr_read("AVS_CFG_1_SAVE", AVS_CFG_1)
        gated = cfg1 | TURN_OFF_PREMUX_BM
        await self.csr_write("AVS_CFG_1_CLK_OFF", AVS_CFG_1, gated)
        await self.csr_read("AVS_CFG_1_CLK_OFF_RB", AVS_CFG_1, expected=gated)
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)

        for slot in range(CMD_FIFO_DEPTH):
            await self.csr_write(f"AVS_CMD_FILL_{slot}", AVS_CMD, _cmd(slot))
        fifos = await self.csr_read("AVS_FIFOS_STATUS_CMD_FULL", AVS_FIFOS_STATUS)
        self.cmd_depth_seen = fifo_field(fifos, CMD_FIFO_OCCUPIED_BM, CMD_FIFO_OCCUPIED_BP)
        assert self.cmd_depth_seen == CMD_FIFO_DEPTH, (
            f"command FIFO holds {self.cmd_depth_seen} of the {CMD_FIFO_DEPTH} commands "
            f"written with the AVS clock gated off (AVS_FIFOS_STATUS=0x{fifos:08x})"
        )
        status = await self.csr_read("AVS_NORMAL_STATUS_CMD_FULL", AVS_NORMAL_STATUS)
        assert status & CMD_FIFO_FULL_STATUS_BM, (
            f"AVS_NORMAL_STATUS.CMD_FIFO_FULL clear with {self.cmd_depth_seen} of "
            f"{CMD_FIFO_DEPTH} slots occupied (0x{status:08x})"
        )
        await self._wait_interrupt(
            "CMD_FULL", CMD_FIFO_FULL_BM, f"{CMD_FIFO_DEPTH} commands filled the command FIFO"
        )
        self.raised.append("CMD_FIFO_FULL_INT")

        # One more write than the FIFO can take. The block refuses it on the
        # bus as well as flagging it, so the access itself is an observable of
        # the full condition.
        await self.csr_write_expect_error("AVS_CMD_OVERFLOW", AVS_CMD, _cmd(CMD_FIFO_DEPTH))
        await self._wait_interrupt(
            "CMD_OVERFLOW",
            CMD_FIFO_OVERFLOW_BM,
            "a further AVS_CMD write against a full command FIFO",
        )
        fifos = await self.csr_read("AVS_FIFOS_STATUS_CMD_OVERFLOW", AVS_FIFOS_STATUS)
        still = fifo_field(fifos, CMD_FIFO_OCCUPIED_BM, CMD_FIFO_OCCUPIED_BP)
        assert still == CMD_FIFO_DEPTH, (
            f"command FIFO holds {still} entries after a write against a full FIFO, which the "
            f"documentation says is dropped (AVS_FIFOS_STATUS=0x{fifos:08x})"
        )
        self.raised.append("CMD_FIFO_OVERFLOW_INT")
        await self._clear_and_check(
            "CMD_OVERFLOW", CLEAR_CMD_FIFO_OVERFLOW_BM, CMD_FIFO_OVERFLOW_BM
        )
        cocotb.log.info(
            "CHK-AVS-CMD-FIFO-OVERFLOW-INT: a further AVS_CMD write against the full FIFO was "
            "refused on the bus and dropped -- the occupancy stayed at %d -- and raised "
            "CMD_FIFO_OVERFLOW_INT, which AVS_INTERRUPT_CLEAR then removed",
            CMD_FIFO_DEPTH,
        )

        # Let the queued commands drain against a responding pad. The full
        # flag follows the full condition, so it only clears once that
        # condition has gone.
        await self.csr_write("AVS_CFG_1_CLK_ON", AVS_CFG_1, cfg1)
        await self.csr_read("AVS_CFG_1_CLK_ON_RB", AVS_CFG_1, expected=cfg1)
        status = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read("AVS_NORMAL_STATUS_CMD_DRAIN", AVS_NORMAL_STATUS)
            if not status & CMD_FIFO_FULL_STATUS_BM:
                break
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        else:
            raise AssertionError(
                f"command FIFO never left the full condition after the AVS clock was restored "
                f"(AVS_NORMAL_STATUS=0x{status:08x})"
            )
        await self._clear_and_check("CMD_FULL", CLEAR_CMD_FIFO_FULL_BM, CMD_FIFO_FULL_BM)
        cocotb.log.info(
            "CHK-AVS-CMD-FIFO-FULL-INT: %d commands queued with the AVS clock gated filled "
            "the command FIFO, raising CMD_FIFO_FULL_INT with AVS_NORMAL_STATUS.CMD_FIFO_FULL "
            "set; once the clock was restored and the FIFO drained, AVS_INTERRUPT_CLEAR "
            "removed the flag",
            CMD_FIFO_DEPTH,
        )

    # --- readback FIFO has data, then full --------------------------------
    async def _readback_fifo(self) -> None:
        await self._wait_interrupt(
            "RB_HAS_DATA",
            READBACK_HAS_DATA_INT_BM,
            "the queued commands were answered by the responding pad",
        )
        self.raised.append("READBACK_HAS_DATA_INT")

        fifos = 0
        for _ in range(POLL_LIMIT):
            fifos = await self.csr_read("AVS_FIFOS_STATUS_RB", AVS_FIFOS_STATUS)
            self.rb_depth_seen = fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)
            if self.rb_depth_seen >= RB_FIFO_DEPTH:
                break
            await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        assert self.rb_depth_seen >= RB_FIFO_DEPTH, (
            f"readback FIFO reached {self.rb_depth_seen} of {RB_FIFO_DEPTH} entries with "
            f"nothing reading AVS_READBACK (AVS_FIFOS_STATUS=0x{fifos:08x})"
        )
        status = await self.csr_read("AVS_NORMAL_STATUS_RB_FULL", AVS_NORMAL_STATUS)
        assert status & READBACK_FIFO_FULL_STATUS_BM, (
            f"AVS_NORMAL_STATUS.READBACK_FIFO_FULL clear with {self.rb_depth_seen} of "
            f"{RB_FIFO_DEPTH} readback slots occupied (0x{status:08x})"
        )
        await self._wait_interrupt(
            "RB_FULL", READBACK_FIFO_FULL_BM, "the readback FIFO filled with responses"
        )
        self.raised.append("READBACK_FIFO_FULL_INT")

        # Drain it before clearing: like the command side, the full flag
        # follows the condition and will not clear while it holds.
        for entry in range(self.rb_depth_seen):
            await self.csr_read(f"AVS_READBACK_POP{entry}", AVS_READBACK)
        await self._clear_and_check("RB_FULL", CLEAR_READBACK_FIFO_FULL_BM, READBACK_FIFO_FULL_BM)
        cocotb.log.info(
            "CHK-AVS-READBACK-FIFO-FULL-INT: %d responses filled the readback FIFO with "
            "AVS_NORMAL_STATUS.READBACK_FIFO_FULL set, raising READBACK_FIFO_FULL_INT; once "
            "the entries were read out, AVS_INTERRUPT_CLEAR removed the flag",
            self.rb_depth_seen,
        )

        await self._clear_and_check(
            "RB_HAS_DATA", CLEAR_READBACK_HAS_DATA_BM, READBACK_HAS_DATA_INT_BM
        )
        cocotb.log.info(
            "CHK-AVS-READBACK-HAS-DATA-INT: responses from the queued commands raised "
            "READBACK_HAS_DATA_INT; once the readback FIFO was emptied, AVS_INTERRUPT_CLEAR "
            "removed the flag"
        )

    # --- readback underflow ------------------------------------------------
    async def _readback_underflow(self) -> None:
        await self.csr_read_decerr_zero("AVS_READBACK_EMPTY", AVS_READBACK)
        await self._wait_interrupt(
            "RB_UNDERFLOW", READBACK_UNDERFLOW_BM, "AVS_READBACK was read with the FIFO empty"
        )
        self.raised.append("READBACK_UNDERFLOW_INT")
        await self._clear_and_check(
            "RB_UNDERFLOW", CLEAR_READBACK_UNDERFLOW_BM, READBACK_UNDERFLOW_BM
        )
        cocotb.log.info(
            "CHK-AVS-READBACK-UNDERFLOW-INT: reading AVS_READBACK on an empty FIFO raised "
            "READBACK_UNDERFLOW_INT, which AVS_INTERRUPT_CLEAR then removed"
        )

    async def body(self) -> None:
        set_avs_sdata(0)
        await self._command_fifo()
        await self._readback_fifo()
        await self._readback_underflow()
        set_avs_sdata(1)
        cocotb.log.info(
            "CHK-AVS-INTERRUPT-CLEAR-SOURCES: %d AVSBus FIFO interrupt sources were each "
            "raised, observed in AVS_INTERRUPT, cleared through the write-only "
            "AVS_INTERRUPT_CLEAR and observed gone: %s",
            len(self.raised),
            ", ".join(self.raised),
        )
