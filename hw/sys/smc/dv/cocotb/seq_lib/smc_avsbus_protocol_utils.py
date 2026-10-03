# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus protocol-frame observables for the SMC bench.

The AVSBus target is a pin-level device on GPIO pads 49/50/51: the DUT drives
``avs_clock_o`` and ``avs_mdata_o`` out and reads ``avs_sdata_i`` back in. The
bench owns the sdata line through ``tb_avs_sdata_ext`` and observes the other
two through ``tb_avs_clk_from_dut`` / ``tb_avs_mdata_from_dut``, so a protocol
transaction is driven entirely from the SMC boundary: AVS_CMD over the SEP_IN
AXI path, the reply level on the sdata pad.

Two DUT-produced observables are recorded here.

``AvsFsmMonitor``
    ``cur_state_debug_o``, lifted to ``tb_avsbus_cur_state_debug``. The
    one-hot bit order is transcribed from the block specification,
    ``hw/ip/avsbus_controller/doc/architecture.adoc`` "Protocol State
    Machine", which tabulates bits 0..16 against the state names. A state
    counts as visited only when the same code holds over two consecutive
    ``clk_periph_i`` samples: the bus crosses into the register domain
    through a three-stage synchronizer, whose per-bit skew can present a
    transient code for a single sample. The AVS clock is a divided
    ``clk_ref_i``, so the shortest real state lasts several ``clk_periph_i``
    cycles.

``AvsMdataMonitor``
    The serial master subframe on the sdata-adjacent pad. Frame shape is
    transcribed from ``hw/ip/avsbus_controller/doc/interface.adoc`` "AVSBus
    Frame Format": 32 bits, most significant first, a fixed ``2'b01``
    preamble in [31:30], the AVS_CMD fields in the same bit positions they
    occupy in the register, and a hardware CRC-3 in [2:0]. The line idles
    high, so a frame is the 32 bits starting at the first low bit; the CRC
    is left out of every compare because no published source in this tree
    gives the AVSBus CRC-3 polynomial.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import FallingEdge, RisingEdge

from .smc_addr_map import _REPO, _field_mask, smc_addr

_AVSBUS_H = _REPO / "hw" / "ip" / "avsbus_controller" / "regs" / "gen" / "c" / "avsbus_controller.h"


def avs_field(symbol: str) -> int:
    """Field mask / position / reset value from generated ``avsbus_controller.h``."""
    return _field_mask(_AVSBUS_H, symbol)


# --- Authoritative AVSBus window (PeakRDL smc_addr.h) ---
AVS_CMD = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CMD_BASE_ADDR")
AVS_READBACK = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_READBACK_BASE_ADDR")
AVS_NORMAL_STATUS = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_NORMAL_STATUS_BASE_ADDR")
AVS_FIFOS_STATUS = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_FIFOS_STATUS_BASE_ADDR")
AVS_INTERRUPT = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_BASE_ADDR")
AVS_INTERRUPT_MASK = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_MASK_BASE_ADDR")
AVS_INTERRUPT_CLEAR = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_INTERRUPT_CLEAR_BASE_ADDR")
AVS_CFG_0 = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")
AVS_CFG_1 = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_1_BASE_ADDR")

# --- Generated-header field symbols used on the proof path ---
CMD_DATA_BM = avs_field("AVSBUS_CONTROLLER__AVS_CMD__CMD_DATA_bm")
CMD_DATA_BP = avs_field("AVSBUS_CONTROLLER__AVS_CMD__CMD_DATA_bp")
RAIL_SEL_BM = avs_field("AVSBUS_CONTROLLER__AVS_CMD__RAIL_SEL_bm")
RAIL_SEL_BP = avs_field("AVSBUS_CONTROLLER__AVS_CMD__RAIL_SEL_bp")
CMD_CODE_BM = avs_field("AVSBUS_CONTROLLER__AVS_CMD__CMD_CODE_bm")
CMD_CODE_BP = avs_field("AVSBUS_CONTROLLER__AVS_CMD__CMD_CODE_bp")
CMD_GRP_BM = avs_field("AVSBUS_CONTROLLER__AVS_CMD__CMD_GRP_bm")
CMD_GRP_BP = avs_field("AVSBUS_CONTROLLER__AVS_CMD__CMD_GRP_bp")
R_OR_W_BM = avs_field("AVSBUS_CONTROLLER__AVS_CMD__R_OR_W_bm")
R_OR_W_BP = avs_field("AVSBUS_CONTROLLER__AVS_CMD__R_OR_W_bp")

CMD_FIFO_OCCUPIED_BM = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_OCCUPIED_SLOTS_bm")
CMD_FIFO_OCCUPIED_BP = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_OCCUPIED_SLOTS_bp")
CMD_FIFO_VACANT_BM = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_VACANT_SLOTS_bm")
CMD_FIFO_VACANT_BP = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_VACANT_SLOTS_bp")
CMD_FIFO_DEPTH = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__CMD_FIFO_VACANT_SLOTS_reset")
RB_FIFO_OCCUPIED_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_OCCUPIED_SLOTS_bm"
)
RB_FIFO_OCCUPIED_BP = avs_field(
    "AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_OCCUPIED_SLOTS_bp"
)
RB_FIFO_VACANT_BM = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_VACANT_SLOTS_bm")
RB_FIFO_VACANT_BP = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_VACANT_SLOTS_bp")
RB_FIFO_DEPTH = avs_field("AVSBUS_CONTROLLER__AVS_FIFOS_STATUS__READBACK_FIFO_VACANT_SLOTS_reset")

TOTAL_RETRIES_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__TOTAL_RETRIES_bm")
TOTAL_RETRIES_BP = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__TOTAL_RETRIES_bp")
MASTER_IS_RETRYING_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__AVS_MASTER_IS_RETRYING_bm")
CMD_FIFO_EMPTY_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__CMD_FIFO_EMPTY_bm")
READBACK_HAS_DATA_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__READBACK_HAS_DATA_bm")
AVS_BUS_IS_IDLE_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__AVS_BUS_IS_IDLE_bm")

SLAVE_UNRESPONSIVE_BM = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__SLAVE_UNRESPONSIVE_INT_bm")
MAX_RETRIES_ATTEMPTED_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT__MAX_RETRIES_ATTEMPTED_INT_bm"
)
CLEAR_SLAVE_UNRESPONSIVE_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_SLAVE_UNRESPONSIVE_INT_bm"
)
CLEAR_MAX_RETRIES_ATTEMPTED_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_MAX_RETRIES_ATTEMPTED_INT_bm"
)
CLEAR_READBACK_HAS_DATA_BM = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_READBACK_HAS_DATA_INT_bm"
)

MAX_RETRIES_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__MAX_RETRIES_bm")
MAX_RETRIES_BP = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__MAX_RETRIES_bp")
RESYNC_INTERVAL_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_0__RESYNC_INTERVAL_bm")
STOP_AVS_CLOCK_ON_IDLE_BM = avs_field("AVSBUS_CONTROLLER__AVS_CFG_1__STOP_AVS_CLOCK_ON_IDLE_bm")

# --- FSM one-hot codes, transcribed from architecture.adoc ------------------
AVS_STATE_BIT = {
    "AVS_RESET": 0,
    "AVS_SLAVE_RESYNC": 1,
    "AVS_LAUNCH_FRAME_POST_RESYNC": 2,
    "AVS_IDLE": 3,
    "AVS_SHIFT_1ST_SUBFRAME": 4,
    "AVS_END_1ST_SUBFRAME": 5,
    "AVS_SHIFT_MID_SUBFRAME": 6,
    "AVS_END_MID_SUBFRAME": 7,
    "AVS_SHIFT_LAST_SUBFRAME": 8,
    "AVS_END_LAST_SUBFRAME": 9,
    "AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME": 10,
    "AVS_RETRY_END_XMIT_AND_RECV_SUBFRAME": 11,
    "AVS_RETRY_SHIFT_XMIT_SUBFRAME": 12,
    "AVS_RETRY_END_XMIT_SUBFRAME": 13,
    "AVS_RETRY_SHIFT_RECV_SUBFRAME": 14,
    "AVS_RETRY_END_RECV_SUBFRAME": 15,
    "AVS_PROCESS_PREVIOUS_SDATA": 16,
}
AVS_STATE = {name: 1 << bit for name, bit in AVS_STATE_BIT.items()}
AVS_CODE_NAME = {code: name for name, code in AVS_STATE.items()}

# --- Master subframe, transcribed from interface.adoc "AVSBus Frame Format" -
SUBFRAME_BITS = 32
MASTER_PREAMBLE = 0b01
MASTER_PREAMBLE_BP = 30
# The CRC-3 the hardware appends; excluded from every compare.
CRC3_BITS = 3
# interface.adoc: "Command Data ... 0xFFFF for read commands".
READ_CMD_DATA = 0xFFFF
# interface.adoc "Command Type": 2 = reserved, 3 = read.
CMD_TYPE_RESERVED = 2
CMD_TYPE_READ = 3
# Master subframe bits [29:3]: the AVS_CMD fields, in the register's own bit
# positions, from the generated header. The union spans the whole payload, so
# the frame is preamble | this | CRC-3.
AVS_CMD_WIRE_MASK = R_OR_W_BM | CMD_GRP_BM | CMD_CODE_BM | RAIL_SEL_BM | CMD_DATA_BM


def build_avs_cmd(cmd_type: int, cmd_grp: int, cmd_code: int, rail_sel: int, cmd_data: int) -> int:
    """Pack an AVS_CMD word from its generated-header field positions.

    The reserved command type is refused: the frame compare checks the wire
    against the word written, so it cannot catch a reserved code.
    """
    if cmd_type == CMD_TYPE_RESERVED:
        raise ValueError(f"AVS_CMD.R_OR_W {cmd_type:#x} is reserved")
    return (
        ((cmd_type << R_OR_W_BP) & R_OR_W_BM)
        | ((cmd_grp << CMD_GRP_BP) & CMD_GRP_BM)
        | ((cmd_code << CMD_CODE_BP) & CMD_CODE_BM)
        | ((rail_sel << RAIL_SEL_BP) & RAIL_SEL_BM)
        | ((cmd_data << CMD_DATA_BP) & CMD_DATA_BM)
    )


def expected_master_subframe(cmd_word: int) -> int:
    """The 32-bit master subframe a given AVS_CMD word produces, CRC-3 zeroed."""
    return (MASTER_PREAMBLE << MASTER_PREAMBLE_BP) | (cmd_word & AVS_CMD_WIRE_MASK)


def fifo_field(word: int, mask: int, pos: int) -> int:
    """Extract one AVS_FIFOS_STATUS / AVS_NORMAL_STATUS field."""
    return (word & mask) >> pos


def set_avs_sdata(level: int) -> None:
    """Hold the AVSBus sdata pad at ``level`` for the rest of the scenario."""
    cocotb.top.tb_avs_sdata_ext.value = level


class AvsFsmMonitor:
    """Records the AVSBus FSM one-hot codes the DUT presents on its debug bus."""

    def __init__(self) -> None:
        self.codes: set[int] = set()
        self.samples = 0
        self.unresolvable = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        previous = None
        while True:
            await RisingEdge(dut.clk_periph_i)
            raw = dut.tb_avsbus_cur_state_debug.value
            if not raw.is_resolvable:
                self.unresolvable += 1
                previous = None
                continue
            code = int(raw)
            self.samples += 1
            if code == previous:
                self.codes.add(code)
            previous = code

    def names(self) -> set[str]:
        """The transcribed names of the codes seen, ignoring codes off the table."""
        return {AVS_CODE_NAME[code] for code in self.codes if code in AVS_CODE_NAME}

    def missing(self, wanted: tuple[str, ...]) -> tuple[str, ...]:
        seen = self.names()
        return tuple(name for name in wanted if name not in seen)


class AvsMdataMonitor:
    """Captures the serial master subframe the DUT drives on its AVSBus pads."""

    def __init__(self) -> None:
        self.bits: list[int] = []
        self.clock_edges = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.kill()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await FallingEdge(dut.tb_avs_clk_from_dut)
            raw = dut.tb_avs_mdata_from_dut.value
            self.clock_edges += 1
            self.bits.append(int(raw) if raw.is_resolvable else -1)

    def subframes(self) -> list[int]:
        """Every complete 32-bit frame captured, CRC-3 zeroed, in wire order.

        The line idles high and every master subframe opens with the preamble's
        low most significant bit, so a frame begins at each low bit that is not
        already inside one.
        """
        frames: list[int] = []
        index = 0
        while index + SUBFRAME_BITS <= len(self.bits):
            if self.bits[index] != 0:
                index += 1
                continue
            window = self.bits[index : index + SUBFRAME_BITS]
            if any(bit < 0 for bit in window):
                index += 1
                continue
            word = 0
            for bit in window:
                word = (word << 1) | bit
            frames.append(word & ~0x7)
            index += SUBFRAME_BITS
        return frames
