# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 FIFO integrity: a real parity fault and a real pointer fault.

`hw/ip/uart/uart_16550/doc/architecture.adoc` (Error Handling): "FIFO and
holding-register data have parity protection, and the FIFO pointers are
redundancy-checked. An internal parity or pointer failure drives `err_o` and
can raise the separately enabled FIFO-error interrupt." Its interrupt table
gives the source ID 7, "Investigate `err_o`; `IER.EFEI` masks this source. An
IIR read does not repair or acknowledge an underlying parity failure."
`uart_log_engine_wrap.adoc` (Interrupts) names the wrapper output `uart_err_o`
"a data-parity or pointer integrity error in the UART FIFOs or holding
registers", and `hw/sys/smc/doc/port_table.adoc` (`smc_ras_o`) carries the
four as `uart_intg_err`, a level that ignores the interrupt enables.

Every other leaf reaches ID 7 through `ITR.TFEI`. Here the fault is real:

* **Parity.** With the transmitter disabled (divisor 0) one character is
  queued in the TX FIFO, so its entry stays at the head. The stored parity bit
  of that entry is flipped by a deposit into the published
  `prim_fifo_sync_parity` storage (`tb/smc_public_scope.vlt`); the entry's
  data bits are untouched. `tb_uart_err_raw[0]` (`uart_err_o` of UART0) and
  `tb_ras_uart_intg_err` must rise, and so must `tb_uart_irq_combined[0]`
  (peripheral interrupt 18) while `IER.EFEI` is still clear, since the SMC ORs
  `uart_err_o` into that line (`hw/ip/uart/uart_16550/doc/index.adoc`,
  Integration). IIR must show no ID 7 and `tb_uart_irq_raw[0]` must stay 0
  with `IER.EFEI` clear; with it set IIR must read `0xCE` (pending, ID 7,
  FIFOs enabled) and `tb_uart_irq_raw[0]` must rise; a second and a third IIR
  read must still show ID 7 with `err_o` high; enabling the transmitter pops
  the entry and `err_o` must fall.
* **Pointer.** With the FIFO empty, one bit of the secondary copy of the read
  pointer (`prim_count` keeps two copies whose sum is constant) is flipped off
  its reset value.
  `err_o` must rise although the FIFO is empty, ID 7 must report under
  `IER.EFEI`, the error must hold, and `FCR.XMIT_FIFO_RESET` (which clears
  both copies) must drop it.

Token `CHK-UART-FIFO-INTG-REAL`, one line per clause, emitted after each
compare holds.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import UART_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fifo_fault_inject import SMC_PERIPH, flip_bit, hier, hold_level, read_int, wait_level

_REPO = Path(__file__).resolve().parents[6]
_UART_H = _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main.h"
_UART_WO_H = (
    _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main_wo.h"
)
_UART_CTRL_H = (
    _REPO
    / "hw"
    / "ip"
    / "uart"
    / "uart_log_engine_wrap"
    / "regs"
    / "gen"
    / "c"
    / "uart_log_engine_ctrl.h"
)

_UART0 = 0
_WRAP = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_"
UART_CTRL = smc_indexed_addr(f"{_WRAP}UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", _UART0)
UART_RBR = smc_indexed_addr(f"{_WRAP}UART_RBR_BASE_ADDR", _UART0)
UART_IER = smc_indexed_addr(f"{_WRAP}UART_IER_BASE_ADDR", _UART0)
UART_IIR = smc_indexed_addr(f"{_WRAP}UART_IIR_BASE_ADDR", _UART0)
UART_LCR = smc_indexed_addr(f"{_WRAP}UART_LCR_BASE_ADDR", _UART0)
UART_LSR = smc_indexed_addr(f"{_WRAP}UART_LSR_BASE_ADDR", _UART0)
UART_ITR = smc_indexed_addr(f"{_WRAP}UART_ITR_BASE_ADDR", _UART0)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
FCR_RCVR_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm")
FCR_XMIT_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__XMIT_FIFO_RESET_bm")
IER_EFEI = _field_mask(_UART_H, "UART_16550_MAIN__IER__EFEI_bm")
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
IIR_FIFOS_ENABLED = _field_mask(_UART_H, "UART_16550_MAIN__IIR__FIFOS_ENABLED_bm")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
LSR_THRE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__THRE_bm")

# `uart_16550_main.rdl` IIR.INTERRUPT_ID: 0x7 is the FIFO Error Interrupt.
ID_FIFO_ERROR = 0x7
# The whole IIR word for a pending FIFO-error with the FIFOs enabled: pending
# is active-low, the id sits at [3:1], FIFOS_ENABLED reads 2'b11.
IIR_FIFO_ERROR_PENDING = (ID_FIFO_ERROR << IIR_INTERRUPT_ID_BP) | IIR_FIFOS_ENABLED

# The TX FIFO of UART0 and the secondary copy of its read pointer.
_UART0_CORE = (
    f"{SMC_PERIPH}.u_uart_wrap.gen_uart_log_engine_wraps[0]"
    ".u_uart_log_engine_wrap.u_uart_16550.u_uart_core"
)
TX_FIFO_STORAGE = f"{_UART0_CORE}.u_uart_txfifo.gen_normal_fifo.storage"
TX_FIFO_RPTR_COPY = (
    f"{_UART0_CORE}.u_uart_txfifo.gen_normal_fifo.u_fifo_cnt"
    ".gen_secure_ptrs.u_rptr.gen_cnts[1].u_cnt_flop.q_o"
)
# One entry is the THR character plus the odd-parity bit stored above it.
ENTRY_WIDTH = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__THR__DATA_bw")
ENTRY_BITS = ENTRY_WIDTH + 1
CHARACTER = 0xA5

# Bounds and holds in clk_periph cycles. err_o is combinational from the
# storage; the RAS bit crosses the peripheral clock flop and a two-flop
# synchroniser on the SMC clock.
_ERR_BOUND = 64
_HOLD = 32
# The transmitter at divisor 1 takes the entry within a few hundred cycles.
_POP_BOUND = 4096


def _odd_parity(data: int, width: int) -> int:
    return 1 ^ (bin(data & ((1 << width) - 1)).count("1") & 1)


def _iir_pending(iir: int) -> bool:
    return (iir & IIR_INTERRUPT_PENDING) == 0


def _iir_id(iir: int) -> int:
    return (iir & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


class smc_uart_fifo_integrity_fault_test_seq(SmcCsrSeq):
    """Real UART0 TX FIFO parity and pointer faults against err_o, IIR and the RAS bit."""

    def __init__(self, name: str = "smc_uart_fifo_integrity_fault_test_seq") -> None:
        super().__init__(name)
        # Measured values the test module gates on.
        self.iir_masked: int | None = None
        self.iir_enabled: int | None = None
        self.iir_reread: tuple[int, ...] = ()
        self.err_after_pop: int | None = None
        self.err_pointer_fault: int | None = None
        self.err_after_fifo_reset: int | None = None

    @staticmethod
    def _err() -> int:
        return read_int(cocotb.top.tb_uart_err_raw)

    @staticmethod
    def _err0() -> int:
        return read_int(cocotb.top.tb_uart_err_raw) & 1

    @staticmethod
    def _ras() -> int:
        return read_int(cocotb.top.tb_ras_uart_intg_err)

    @staticmethod
    def _irq0() -> int:
        return read_int(cocotb.top.tb_uart_irq_raw) & 1

    @staticmethod
    def _irq_combined0() -> int:
        return read_int(cocotb.top.tb_uart_irq_combined) & 1

    async def _set_divisor(self, label: str, divisor: int) -> None:
        await self.csr_write(f"{label}_LCR_DLAB", UART_LCR, LCR_WLS | LCR_DLAB)
        # DLL / DLH are the write-only aliases of the RBR / IER addresses.
        await self.csr_write(f"{label}_DLL_via_UART_RBR", UART_RBR, divisor & 0xFF)
        await self.csr_write(f"{label}_DLH_via_UART_IER", UART_IER, (divisor >> 8) & 0xFF)
        await self.csr_write(f"{label}_LCR_8N1", UART_LCR, LCR_WLS)

    async def _fifo_reset(self, label: str) -> None:
        # FCR is the write-only alias of the IIR address.
        await self.csr_write(
            f"{label}_FCR_via_UART_IIR",
            UART_IIR,
            FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET | FCR_XMIT_FIFO_RESET,
        )

    async def _require_no_id7(self, label: str, reads: int = 4) -> int:
        """IIR must report no FIFO-error id over ``reads`` reads; returns the last IIR."""
        iir = 0
        for n in range(reads):
            iir = await self.csr_read(f"{label}_IIR{n}", UART_IIR)
            assert not (_iir_pending(iir) and _iir_id(iir) == ID_FIFO_ERROR), (
                f"{label}: IIR=0x{iir:02x} reports id 0x{ID_FIFO_ERROR:x} while IER.EFEI is clear"
            )
        return iir

    async def _require_id7(self, label: str) -> int:
        iir = await self.csr_read(f"{label}_IIR", UART_IIR)
        assert iir == IIR_FIFO_ERROR_PENDING, (
            f"{label}: IIR=0x{iir:02x}, expected 0x{IIR_FIFO_ERROR_PENDING:02x} "
            f"(pending, id 0x{ID_FIFO_ERROR:x}, FIFOs enabled)"
        )
        return iir

    async def _quiet_baseline(self, label: str) -> None:
        await self.csr_write(f"{label}_IER0", UART_IER, 0)
        await self.csr_write(f"{label}_ITR0", UART_ITR, 0)
        for n in range(8):
            iir = await self.csr_read(f"{label}_IIR_DRAIN{n}", UART_IIR)
            if not _iir_pending(iir):
                break
        assert not _iir_pending(iir), f"{label}: IIR=0x{iir:02x} still pending before the fault"
        await hold_level(self._err, 0, _HOLD, f"{label}: tb_uart_err_raw before the fault")
        await hold_level(self._ras, 0, _HOLD, f"{label}: tb_ras_uart_intg_err before the fault")

    async def _parity_leg(self) -> None:
        label = "PARITY"
        await self._set_divisor(label, 0)
        await self._fifo_reset(label)
        await self._quiet_baseline(label)

        # One character queued while the transmitter is off: the head entry is
        # never popped, so the fault sits on a live entry.
        await self.csr_write(f"{label}_THR_via_UART_RBR", UART_RBR, CHARACTER)
        lsr = await self.csr_read(f"{label}_LSR_QUEUED", UART_LSR)
        assert (lsr & LSR_THRE) == 0, (
            f"{label}: LSR=0x{lsr:02x} THRE set, the character did not stay in the TX FIFO"
        )

        storage = hier(TX_FIFO_STORAGE)
        entry = read_int(storage) & ((1 << ENTRY_BITS) - 1)
        expected_entry = (_odd_parity(CHARACTER, ENTRY_WIDTH) << ENTRY_WIDTH) | CHARACTER
        assert entry == expected_entry, (
            f"{label}: TX FIFO slot 0 holds 0x{entry:03x}, expected 0x{expected_entry:03x} "
            f"(character 0x{CHARACTER:02x} with its stored odd-parity bit)"
        )
        # A queued, intact entry raises nothing: the rise below is the flip's.
        await hold_level(self._err, 0, _HOLD, f"{label}: tb_uart_err_raw with the entry queued")
        await flip_bit(storage, ENTRY_WIDTH, f"{label}: parity bit of TX FIFO slot 0")

        await wait_level(self._err0, 1, _ERR_BOUND, f"{label}: tb_uart_err_raw[0]")
        err = self._err()
        assert err == 1, f"{label}: tb_uart_err_raw=0x{err:x}, only UART0 carries the fault"
        await wait_level(self._ras, 1, _ERR_BOUND, f"{label}: tb_ras_uart_intg_err")
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: parity: one stored parity bit of the queued TX entry "
            "flipped at %s bit %d; tb_uart_err_raw=0x%x (UART0 err_o high, the other three "
            "low) and tb_ras_uart_intg_err=1 within %d cycles",
            TX_FIFO_STORAGE,
            ENTRY_WIDTH,
            err,
            _ERR_BOUND,
        )

        self.iir_masked = await self._require_no_id7(f"{label}_MASKED")
        assert self._irq0() == 0, f"{label}: tb_uart_irq_raw[0]=1 with IER.EFEI clear"
        # The SMC ORs uart_err_o into the peripheral interrupt, so the line is
        # up with the mask clear while the UART's own request is not.
        await wait_level(
            self._irq_combined0, 1, _ERR_BOUND, f"{label}: tb_uart_irq_combined[0] from err_o"
        )
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: mask: with IER.EFEI=0 and err_o high, four IIR reads "
            "reported no id 0x%x (last IIR=0x%02x) and tb_uart_irq_raw[0]=0, while "
            "tb_uart_irq_combined[0]=1: err_o reaches peripheral interrupt 18 through the SMC "
            "OR regardless of the mask",
            ID_FIFO_ERROR,
            self.iir_masked,
        )

        await self.csr_write(f"{label}_IER_EFEI", UART_IER, IER_EFEI)
        self.iir_enabled = await self._require_id7(f"{label}_ENABLED")
        await wait_level(self._irq0, 1, _ERR_BOUND, f"{label}: tb_uart_irq_raw[0]")
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: report: with IER.EFEI=1 IIR=0x%02x (pending, id 0x%x, "
            "FIFOs enabled) and tb_uart_irq_raw[0]=1 (the UART's own request)",
            self.iir_enabled,
            ID_FIFO_ERROR,
        )

        rereads = []
        for n in range(2):
            rereads.append(await self._require_id7(f"{label}_REREAD{n}"))
            assert self._err0() == 1, f"{label}: err_o fell after IIR read {n + 1}"
        self.iir_reread = tuple(rereads)
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: persistence: two further IIR reads returned %s with "
            "tb_uart_err_raw[0]=1 after each; an IIR read neither repairs nor acknowledges "
            "the parity failure",
            ", ".join(f"0x{v:02x}" for v in self.iir_reread),
        )

        await self.csr_write(f"{label}_IER_OFF", UART_IER, 0)
        iir_remasked = await self._require_no_id7(f"{label}_REMASKED", reads=2)
        assert self._err0() == 1, f"{label}: err_o fell when IER.EFEI was cleared"
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: remask: clearing IER.EFEI removed id 0x%x from IIR "
            "(last IIR=0x%02x) while tb_uart_err_raw[0]=1: the mask hides the report, not "
            "the fault",
            ID_FIFO_ERROR,
            iir_remasked,
        )

        # Divisor 1 enables the transmitter, which pops the head entry.
        await self._set_divisor(f"{label}_POP", 1)
        await wait_level(self._err0, 0, _POP_BOUND, f"{label}: tb_uart_err_raw[0] after the pop")
        self.err_after_pop = self._err0()
        await wait_level(self._ras, 0, _ERR_BOUND, f"{label}: tb_ras_uart_intg_err after the pop")
        lsr = 0
        for n in range(64):
            lsr = await self.csr_read(f"{label}_LSR_POPPED{n}", UART_LSR)
            if lsr & LSR_THRE:
                break
        assert lsr & LSR_THRE, f"{label}: LSR=0x{lsr:02x} THRE clear after the entry popped"
        slot0 = read_int(storage) & ((1 << ENTRY_BITS) - 1)
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: pop: enabling the transmitter popped the faulted entry; "
            "tb_uart_err_raw[0]=0 and tb_ras_uart_intg_err=0 with LSR.THRE=1; slot 0 still "
            "reads 0x%03x (the storage keeps the flipped bit, the empty FIFO stops reporting it)",
            slot0,
        )

    async def _pointer_leg(self) -> None:
        label = "POINTER"
        # The reset reloads both pointer copies (the primary to zero, the
        # secondary to all ones, their sum constant), so the flip below lands
        # off the reset value and the restore compare after the second reset
        # can fail.
        await self._fifo_reset(f"{label}_PRE")
        await self._quiet_baseline(label)
        lsr = await self.csr_read(f"{label}_LSR_EMPTY", UART_LSR)
        assert lsr & LSR_THRE, f"{label}: LSR=0x{lsr:02x} the TX FIFO is not empty"

        rptr_copy = hier(TX_FIFO_RPTR_COPY)
        all_ones = (1 << len(rptr_copy)) - 1
        before, after = await flip_bit(rptr_copy, 0, f"{label}: secondary read-pointer copy")
        assert before == all_ones and after != all_ones, (
            f"{label}: secondary pointer copy 0x{before:x} -> 0x{after:x}, expected the flip to "
            f"leave its reset value 0x{all_ones:x}"
        )

        await wait_level(self._err0, 1, _ERR_BOUND, f"{label}: tb_uart_err_raw[0]")
        self.err_pointer_fault = self._err0()
        await wait_level(self._ras, 1, _ERR_BOUND, f"{label}: tb_ras_uart_intg_err")
        await self.csr_write(f"{label}_IER_EFEI", UART_IER, IER_EFEI)
        iir = await self._require_id7(f"{label}_ENABLED")
        await hold_level(self._err0, 1, _HOLD, f"{label}: tb_uart_err_raw[0] holding")
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: pointer: one bit of the secondary read-pointer copy "
            "flipped at %s (0x%x -> 0x%x) with the FIFO empty; tb_uart_err_raw[0]=1, "
            "tb_ras_uart_intg_err=1, IIR=0x%02x under IER.EFEI, and err_o held for %d clk_periph "
            "cycles",
            TX_FIFO_RPTR_COPY,
            before,
            after,
            iir,
            _HOLD,
        )

        await self._fifo_reset(label)
        await wait_level(self._err0, 0, _ERR_BOUND, f"{label}: tb_uart_err_raw[0] after FCR reset")
        self.err_after_fifo_reset = self._err0()
        await wait_level(self._ras, 0, _ERR_BOUND, f"{label}: tb_ras_uart_intg_err after FCR reset")
        restored = read_int(rptr_copy)
        assert restored == all_ones, (
            f"{label}: secondary pointer copy reads 0x{restored:x} after FCR.XMIT_FIFO_RESET, "
            f"expected its reset value 0x{all_ones:x}"
        )
        await self._require_no_id7(f"{label}_CLEARED", reads=2)
        await self.csr_write(f"{label}_IER_OFF", UART_IER, 0)
        cocotb.log.info(
            "CHK-UART-FIFO-INTG-REAL: pointer clear: FCR.XMIT_FIFO_RESET restored the pointer "
            "copy to 0x%x, tb_uart_err_raw[0]=0, tb_ras_uart_intg_err=0 and IIR reports no id "
            "0x%x",
            restored,
            ID_FIFO_ERROR,
        )

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART_EN", UART_CTRL, UART_EN)
        await ClockCycles(cocotb.top.clk_smc_i, 8)

        await self._parity_leg()
        await self._pointer_leg()
        await self._set_divisor("RESTORE", 0)
