# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 FIFO integrity: a real parity fault and a real pointer fault.

`hw/ip/i2c/doc/index.adoc` (Interfaces): "`i2c_fifo_intg_err_o` is the OR of
an instance's four FIFO integrity errors: a pointer mismatch in a hardened
FIFO counter, or a parity mismatch on the entry at the head of a FIFO. It is
independent of `INTR_ENABLE`. The pointer error holds until the FIFO is
cleared or reset; the parity error clears once that entry is read. The SMC
ORs the instances into `smc_ras_o.i2c_intg_err`." `i2c.rdl` declares
`INTR_STATE.CONTROLLER_TX_FIFO_ERROR` "asserted while the Controller TX FIFO
reports an integrity error: a parity mismatch on the entry at its head, or a
pointer mismatch in its hardened counter. The parity error clears once that
entry is read; the pointer error holds until `FIFO_CTRL.FMTRST` or a reset.
Write `1` to clear; the field stays set while the error persists."

Every other leaf reaches the `*_FIFO_ERROR` bits through `INTR_TEST`. Here
the fault is real, on the controller TX (FMT) FIFO of I2C0:

* **Parity.** With the controller disabled one format entry is queued, so it
  stays at the head. The stored parity bit of that entry is flipped by a
  deposit into the published `prim_fifo_sync_parity` storage
  (`tb/smc_public_scope.vlt`); the entry's data bits are untouched, and only
  that slot is read, since the entry array has no reset and the other slots
  are X on a four-state simulator. `tb_i2c_intg_err[0]`,
  `tb_ras_i2c_intg_err` and `INTR_STATE.CONTROLLER_TX_FIFO_ERROR` must rise
  with `INTR_ENABLE` all zero and `tb_i2c_irq[0]` low; enabling the source
  must raise the line; a W1C with the faulted entry still at the head must
  leave the status bit set, since the field stays set while the error
  persists; enabling the controller pops
  the entry (the byte goes out with START and STOP and `NAKOK`, so the
  unanswered address ends the transfer) and the error must fall with it.
* **Pointer.** With the FIFO empty, one bit of the secondary copy of the
  write pointer (`prim_count` keeps two copies whose sum is constant) is
  flipped off its reset value. The error must rise with the FIFO empty, hold,
  and fall on `FIFO_CTRL.FMTRST`, which reloads both copies. The status bit
  must be set under the pointer fault with the FIFO empty, and a W1C while
  the fault persists must leave it set: the field reports the pointer
  mismatch and holds until the FIFO reset.

Tokens `CHK-I2C-FIFO-INTG-REAL` (the output, the RAS bit, the interrupt line
and the clearing) and `CHK-I2C-FIFO-INTG-STATUS` (the status bit after a W1C
under the parity fault, and under the pointer fault before and after a W1C),
one line per clause, emitted after each compare holds.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import I2C_CG_EN, _field_mask, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fifo_fault_inject import (
    SMC_PERIPH,
    flip_bit,
    hier,
    hold_level,
    read_field,
    read_int,
    wait_level,
)
from .smc_i2c_field_masks import (
    _I2C_H,
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_FMTRST,
    I2C_FIFO_CTRL_RXRST,
    I2C_HOST_FIFO_STATUS_FMTLVL,
    I2C_STATUS_HOSTIDLE,
)
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CONTROLLER_EVENTS,
    I2C0_CTRL,
    I2C0_FDATA,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_OVRD_OFF,
    I2C_WRAP_ENABLE_CONTROLLER,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

_I2C0 = 0
I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", _I2C0)
I2C0_INTR_ENABLE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR", _I2C0)
I2C0_HOST_FIFO_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", _I2C0
)

INTR_CONTROLLER_TX_FIFO_ERROR = _field_mask(_I2C_H, "I2C__INTR_STATE__CONTROLLER_TX_FIFO_ERROR_bm")
INTR_ENABLE_CONTROLLER_TX_FIFO_ERROR = _field_mask(
    _I2C_H, "I2C__INTR_ENABLE__CONTROLLER_TX_FIFO_ERROR_bm"
)
INTR_CMD_COMPLETE = _field_mask(_I2C_H, "I2C__INTR_STATE__CMD_COMPLETE_bm")
FDATA_NAKOK = _field_mask(_I2C_H, "I2C__FDATA__NAKOK_bm")
FMTLVL_BP = _field_mask(_I2C_H, "I2C__HOST_FIFO_STATUS__FMTLVL_bp")
INTR_ALL = 0xFFFF_FFFF

#: An address no device on the bench bus answers; NAKOK lets the controller
#: finish the transfer with its STOP regardless.
ABSENT_ADDR = 0x51
FMT_ENTRY = (ABSENT_ADDR << 1) | I2C_FDATA_START | I2C_FDATA_STOP | FDATA_NAKOK

# The controller TX (FMT) FIFO of I2C0 and the secondary copy of its write
# pointer.
_I2C0_CORE = f"{SMC_PERIPH}.u_i2c_wrap.gen_i2cs[0].u_i2c.u_i2c_core"
FMT_FIFO_STORAGE = f"{_I2C0_CORE}.u_controller_tx_fifo.gen_normal_fifo.storage"
FMT_FIFO_WPTR_COPY = (
    f"{_I2C0_CORE}.u_controller_tx_fifo.gen_normal_fifo.u_fifo_cnt"
    ".gen_secure_ptrs.u_wptr.gen_cnts[1].u_cnt_flop.q_o"
)
# One entry is the FDATA fields up to NAKOK plus the odd-parity bit stored
# above them.
ENTRY_WIDTH = _field_mask(_I2C_H, "I2C__FDATA__NAKOK_bp") + 1
ENTRY_BITS = ENTRY_WIDTH + 1

# Bounds and holds in clk_periph cycles. The error is combinational from the
# storage or registered in the counter; the RAS bit crosses the peripheral
# clock flop and a two-flop synchroniser on the SMC clock.
_ERR_BOUND = 64
_HOLD = 64
# The controller pops the entry after its byte and the ACK slot at the
# programmed timing; the STOP and HOSTIDLE follow within the same order.
_POP_BOUND = 20_000
_IDLE_POLLS = 400
_POLL_CYCLES = 50


def _odd_parity(data: int, width: int) -> int:
    return 1 ^ (bin(data & ((1 << width) - 1)).count("1") & 1)


class smc_i2c_fifo_integrity_fault_test_seq(SmcCsrSeq):
    """Real I2C0 FMT FIFO parity and pointer faults against the status bit, the output and RAS."""

    def __init__(self, name: str = "smc_i2c_fifo_integrity_fault_test_seq") -> None:
        super().__init__(name)
        # Measured values the test module gates on.
        self.ras_with_enable_clear: int | None = None
        self.irq_with_enable_clear: int | None = None
        self.irq_with_enable_set: int | None = None
        self.ras_after_pop: int | None = None
        self.ras_pointer_fault: int | None = None
        self.ras_after_fmtrst: int | None = None
        self.status_w1c_parity_live: int | None = None
        self.status_pointer_fault: int | None = None
        self.status_w1c_pointer_live: int | None = None

    @staticmethod
    def _intg() -> int:
        return read_int(cocotb.top.tb_i2c_intg_err)

    @staticmethod
    def _intg0() -> int:
        return read_int(cocotb.top.tb_i2c_intg_err) & 1

    @staticmethod
    def _ras() -> int:
        return read_int(cocotb.top.tb_ras_i2c_intg_err)

    @staticmethod
    def _irq0() -> int:
        return read_int(cocotb.top.tb_i2c_irq) & 1

    async def _status_bit(self, label: str) -> int:
        state = await self.csr_read(f"{label}_INTR_STATE", I2C0_INTR_STATE)
        return 1 if state & INTR_CONTROLLER_TX_FIFO_ERROR else 0

    async def _fmtlvl(self, label: str) -> int:
        level = await self.csr_read(f"{label}_HOST_FIFO_STATUS", I2C0_HOST_FIFO_STATUS)
        return (level & I2C_HOST_FIFO_STATUS_FMTLVL) >> FMTLVL_BP

    async def _configure(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_FIFO_INTG")
        await self.csr_write("I2C0_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write(
            "I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST | I2C_FIFO_CTRL_FMTRST
        )
        await self.csr_write("I2C0_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write("I2C0_INTR_ENABLE0", I2C0_INTR_ENABLE, 0)
        await self.csr_write("I2C0_INTR_CLR", I2C0_INTR_STATE, INTR_ALL)

    async def _quiet_baseline(self, label: str) -> None:
        bit = await self._status_bit(f"{label}_BASE")
        assert bit == 0, f"{label}: INTR_STATE.CONTROLLER_TX_FIFO_ERROR set before the fault"
        await hold_level(self._intg, 0, _HOLD, f"{label}: tb_i2c_intg_err before the fault")
        await hold_level(self._ras, 0, _HOLD, f"{label}: tb_ras_i2c_intg_err before the fault")
        await hold_level(self._irq0, 0, _HOLD, f"{label}: tb_i2c_irq[0] before the fault")

    async def _wait_hostidle(self, label: str) -> None:
        status = 0
        for n in range(_IDLE_POLLS):
            status = await self.csr_read(f"{label}_STATUS{n}", I2C0_STATUS)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, _POLL_CYCLES)
        raise AssertionError(f"{label}: STATUS.HOSTIDLE never set (STATUS=0x{status:08x})")

    async def _parity_leg(self) -> None:
        label = "PARITY"
        await self._quiet_baseline(label)

        # One format entry queued while the controller is disabled: nothing
        # pops it, so the fault sits on a live head entry.
        await self.csr_write(f"{label}_FDATA", I2C0_FDATA, FMT_ENTRY)
        level = await self._fmtlvl(f"{label}_QUEUED")
        assert level == 1, f"{label}: HOST_FIFO_STATUS.FMTLVL={level}, expected 1"

        storage = hier(FMT_FIFO_STORAGE)
        entry = read_field(storage, 0, ENTRY_BITS)
        expected_entry = (_odd_parity(FMT_ENTRY, ENTRY_WIDTH) << ENTRY_WIDTH) | FMT_ENTRY
        assert entry == expected_entry, (
            f"{label}: FMT FIFO slot 0 holds 0x{entry:04x}, expected 0x{expected_entry:04x} "
            f"(FDATA 0x{FMT_ENTRY:04x} with its stored odd-parity bit)"
        )
        # A queued, intact entry raises nothing: the rise below is the flip's.
        await hold_level(self._intg, 0, _HOLD, f"{label}: tb_i2c_intg_err with the entry queued")
        await flip_bit(
            storage, ENTRY_WIDTH, f"{label}: parity bit of FMT FIFO slot 0", field=(0, ENTRY_BITS)
        )

        await wait_level(self._intg0, 1, _ERR_BOUND, f"{label}: tb_i2c_intg_err[0]")
        intg = self._intg()
        assert intg == 1, f"{label}: tb_i2c_intg_err=0x{intg:x}, only I2C0 carries the fault"
        await wait_level(self._ras, 1, _ERR_BOUND, f"{label}: tb_ras_i2c_intg_err")
        bit = await self._status_bit(f"{label}_FAULT")
        assert bit == 1, f"{label}: INTR_STATE.CONTROLLER_TX_FIFO_ERROR clear with the fault live"
        self.ras_with_enable_clear = self._ras()
        await hold_level(self._irq0, 0, _HOLD, f"{label}: tb_i2c_irq[0] with INTR_ENABLE clear")
        self.irq_with_enable_clear = self._irq0()
        cocotb.log.info(
            "CHK-I2C-FIFO-INTG-REAL: parity: one stored parity bit of the queued FMT entry "
            "flipped at %s bit %d; tb_i2c_intg_err=0x%x (I2C0 only), tb_ras_i2c_intg_err=1 and "
            "INTR_STATE.CONTROLLER_TX_FIFO_ERROR=1 with INTR_ENABLE=0, tb_i2c_irq[0] held 0 for "
            "%d clk_periph cycles: the error output is independent of INTR_ENABLE",
            FMT_FIFO_STORAGE,
            ENTRY_WIDTH,
            intg,
            _HOLD,
        )

        await self.csr_write(
            f"{label}_INTR_ENABLE", I2C0_INTR_ENABLE, INTR_ENABLE_CONTROLLER_TX_FIFO_ERROR
        )
        await wait_level(self._irq0, 1, _ERR_BOUND, f"{label}: tb_i2c_irq[0] with the enable set")
        self.irq_with_enable_set = self._irq0()
        await self.csr_write(f"{label}_W1C_LIVE", I2C0_INTR_STATE, INTR_CONTROLLER_TX_FIFO_ERROR)
        relatched = await self._status_bit(f"{label}_W1C_LIVE")
        assert self._irq0() == 1, f"{label}: tb_i2c_irq[0] fell before INTR_ENABLE was cleared"
        await self.csr_write(f"{label}_INTR_ENABLE0", I2C0_INTR_ENABLE, 0)
        await wait_level(self._irq0, 0, _ERR_BOUND, f"{label}: tb_i2c_irq[0] after the enable")
        cocotb.log.info(
            "CHK-I2C-FIFO-INTG-REAL: enable: INTR_ENABLE.CONTROLLER_TX_FIFO_ERROR=1 raised "
            "tb_i2c_irq[0] (peripheral interrupt 23) and clearing it released the line"
        )
        # The field follows the FIFO's error while it persists, so the W1C
        # with the faulted entry still at the head leaves it set.
        assert relatched == 1, (
            f"{label}: INTR_STATE.CONTROLLER_TX_FIFO_ERROR cleared by a W1C with the faulted "
            f"entry still at the head"
        )
        self.status_w1c_parity_live = relatched
        cocotb.log.info(
            "CHK-I2C-FIFO-INTG-STATUS: parity W1C live: INTR_STATE.CONTROLLER_TX_FIFO_ERROR read "
            "1 after a W1C with the faulted entry still at the head: the field stays set while "
            "the parity error persists"
        )

        # The controller takes the head entry, sends it and pops it after the
        # ACK slot; NAKOK and STOP end the transfer on the unanswered address.
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await wait_level(self._intg0, 0, _POP_BOUND, f"{label}: tb_i2c_intg_err[0] after the pop")
        await wait_level(self._ras, 0, _ERR_BOUND, f"{label}: tb_ras_i2c_intg_err after the pop")
        self.ras_after_pop = self._ras()
        level = await self._fmtlvl(f"{label}_POPPED")
        assert level == 0, f"{label}: HOST_FIFO_STATUS.FMTLVL={level} after the pop, expected 0"
        await self.csr_write(f"{label}_W1C_POPPED", I2C0_INTR_STATE, INTR_CONTROLLER_TX_FIFO_ERROR)
        bit = await self._status_bit(f"{label}_POPPED")
        assert bit == 0, f"{label}: INTR_STATE.CONTROLLER_TX_FIFO_ERROR re-set after the pop"
        await hold_level(self._ras, 0, _HOLD, f"{label}: tb_ras_i2c_intg_err after the pop")
        cocotb.log.info(
            "CHK-I2C-FIFO-INTG-REAL: pop: CTRL.ENABLEHOST=1 made the controller read the "
            "faulted entry (FMTLVL 1 -> 0); tb_i2c_intg_err[0]=0, tb_ras_i2c_intg_err=0, and "
            "the W1C cleared INTR_STATE.CONTROLLER_TX_FIFO_ERROR and tb_ras_i2c_intg_err held 0 "
            "for %d clk_periph cycles: the parity error clears once the entry is read",
            _HOLD,
        )
        await self._wait_hostidle(f"{label}_DONE")
        await self.csr_write(f"{label}_DISABLE", I2C0_CTRL, 0)
        await self.csr_write(
            f"{label}_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, INTR_ALL)

    async def _pointer_leg(self) -> None:
        label = "POINTER"
        # The reset reloads both pointer copies (the primary to zero, the
        # secondary to all ones, their sum constant), so the flip below lands
        # off the reset value and the restore compare after the second reset
        # can fail.
        await self.csr_write(f"{label}_FMTRST_PRE", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_FMTRST)
        await self._quiet_baseline(label)
        level = await self._fmtlvl(f"{label}_EMPTY")
        assert level == 0, f"{label}: HOST_FIFO_STATUS.FMTLVL={level}, the FMT FIFO is not empty"

        wptr_copy = hier(FMT_FIFO_WPTR_COPY)
        all_ones = (1 << len(wptr_copy)) - 1
        before, after = await flip_bit(wptr_copy, 0, f"{label}: secondary write-pointer copy")
        assert before == all_ones and after != all_ones, (
            f"{label}: secondary pointer copy 0x{before:x} -> 0x{after:x}, expected the flip to "
            f"leave its reset value 0x{all_ones:x}"
        )

        await wait_level(self._intg0, 1, _ERR_BOUND, f"{label}: tb_i2c_intg_err[0]")
        await wait_level(self._ras, 1, _ERR_BOUND, f"{label}: tb_ras_i2c_intg_err")
        self.ras_pointer_fault = self._ras()
        await hold_level(self._ras, 1, _HOLD, f"{label}: tb_ras_i2c_intg_err holding")
        cocotb.log.info(
            "CHK-I2C-FIFO-INTG-REAL: pointer: one bit of the secondary write-pointer copy "
            "flipped at %s (0x%x -> 0x%x) with the FIFO empty; tb_i2c_intg_err[0]=1 and "
            "tb_ras_i2c_intg_err=1, held for %d clk_periph cycles",
            FMT_FIFO_WPTR_COPY,
            before,
            after,
            _HOLD,
        )
        # The field reports the pointer mismatch as well, and a W1C while the
        # mismatch persists leaves it set: only FIFO_CTRL.FMTRST or a reset
        # clears it.
        status_on_pointer = await self._status_bit(f"{label}_FAULT")
        assert status_on_pointer == 1, (
            f"{label}: INTR_STATE.CONTROLLER_TX_FIFO_ERROR clear with the pointer fault live"
        )
        self.status_pointer_fault = status_on_pointer
        await self.csr_write(f"{label}_W1C_LIVE", I2C0_INTR_STATE, INTR_CONTROLLER_TX_FIFO_ERROR)
        relatched = await self._status_bit(f"{label}_W1C_LIVE")
        assert relatched == 1, (
            f"{label}: INTR_STATE.CONTROLLER_TX_FIFO_ERROR cleared by a W1C with the pointer "
            f"fault still live"
        )
        self.status_w1c_pointer_live = relatched
        cocotb.log.info(
            "CHK-I2C-FIFO-INTG-STATUS: pointer: INTR_STATE.CONTROLLER_TX_FIFO_ERROR read 1 with "
            "the pointer fault live and the FIFO empty, and 1 again after a W1C: the field "
            "reports the pointer mismatch and stays set across the W1C"
        )

        await self.csr_write(f"{label}_FMTRST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_FMTRST)
        await wait_level(self._intg0, 0, _ERR_BOUND, f"{label}: tb_i2c_intg_err[0] after FMTRST")
        await wait_level(self._ras, 0, _ERR_BOUND, f"{label}: tb_ras_i2c_intg_err after FMTRST")
        self.ras_after_fmtrst = self._ras()
        restored = read_int(wptr_copy)
        assert restored == all_ones, (
            f"{label}: secondary pointer copy reads 0x{restored:x} after FIFO_CTRL.FMTRST, "
            f"expected its reset value 0x{all_ones:x}"
        )
        await self.csr_write(f"{label}_W1C", I2C0_INTR_STATE, INTR_CONTROLLER_TX_FIFO_ERROR)
        bit = await self._status_bit(f"{label}_CLEARED")
        assert bit == 0, f"{label}: INTR_STATE.CONTROLLER_TX_FIFO_ERROR re-set after FMTRST"
        await hold_level(self._ras, 0, _HOLD, f"{label}: tb_ras_i2c_intg_err after FMTRST")
        cocotb.log.info(
            "CHK-I2C-FIFO-INTG-REAL: pointer clear: FIFO_CTRL.FMTRST restored the pointer copy "
            "to 0x%x, tb_i2c_intg_err[0]=0, tb_ras_i2c_intg_err=0 and a W1C leaves the status "
            "bit clear: the pointer error holds until the FIFO is cleared",
            restored,
        )

    async def body(self) -> None:
        await self._configure()
        await self._parity_leg()
        await self._pointer_leg()
