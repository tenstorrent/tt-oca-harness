# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Addresses, field masks and UART loopback setup shared by the log-engine leaves.

Every constant here comes from a generated RDL header -- `uart_16550_main.h`,
`uart_16550_main_wo.h` and its address header, `uart_16550_dl_addr.h`,
`log_engine.h`, `uart_log_engine_ctrl.h` -- or from the indexed `smc_addr.h`
macros of the wrapper, never from a literal.

`arm_uart` puts one wrapper's UART where a log-engine transfer can use it: the
pad mux enabled, the divisor latches at the fastest rate the RDL allows, eight
data bits, the FIFOs on, interrupts masked and `MCR.LOOP` set so the bytes the
engine writes into the transmit holding register come back through that same
UART's receiver and no pad carries them.
"""

from __future__ import annotations

from .smc_addr_map import (
    log_engine_u32,
    smc_indexed_addr,
    uart_16550_dl_offset,
    uart_16550_main_u32,
    uart_16550_wo_offset,
    uart_16550_wo_u32,
    uart_log_engine_ctrl_u32,
)

WRAP = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_"
WRAP_PY = "SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_{index}__"
WRAP_STRIDE_SYMBOL = f"{WRAP}STRIDE"
WRAP_NUM = f"{WRAP}NUM"
LOG_CTRL_PATH = "smc_uart_wrap/uart_log_engine_wrap/log_engine/LOG_CTRL"
LOG_CTRL_PY = WRAP_PY + "LOG_ENGINE_LOG_CTRL_{element}__REG_ADDR"

UART_EN = uart_log_engine_ctrl_u32("UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
LCR_DLAB = uart_16550_main_u32("UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = uart_16550_main_u32("UART_16550_MAIN__LCR__WLS_bm")
MCR_LOOP = uart_16550_main_u32("UART_16550_MAIN__MCR__LOOP_bm")
LSR_DR = uart_16550_main_u32("UART_16550_MAIN__LSR__DR_bm")
LSR_TEMT = uart_16550_main_u32("UART_16550_MAIN__LSR__TEMT_bm")
RBR_DATA = uart_16550_main_u32("UART_16550_MAIN__RBR__DATA_bm")
# LSR bits the receiver raises on a damaged character. All four are `rclr`, so
# each LSR read is the only chance to see the ones that read set.
LSR_LINE_ERRORS = (
    uart_16550_main_u32("UART_16550_MAIN__LSR__OE_bm")
    | uart_16550_main_u32("UART_16550_MAIN__LSR__PE_bm")
    | uart_16550_main_u32("UART_16550_MAIN__LSR__FE_bm")
    | uart_16550_main_u32("UART_16550_MAIN__LSR__BI_bm")
)
IER_ERBFI = uart_16550_main_u32("UART_16550_MAIN__IER__ERBFI_bm")
IIR_PENDING = uart_16550_main_u32("UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_ID = uart_16550_main_u32("UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_ID_SHIFT = uart_16550_main_u32("UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
IIR_FIFOS_ENABLED = uart_16550_main_u32("UART_16550_MAIN__IIR__FIFOS_ENABLED_bm")
IIR_FIFOS_SHIFT = uart_16550_main_u32("UART_16550_MAIN__IIR__FIFOS_ENABLED_bp")
LSR_THRE = uart_16550_main_u32("UART_16550_MAIN__LSR__THRE_bm")
MCR_DTR = uart_16550_main_u32("UART_16550_MAIN__MCR__DTR_bm")
MCR_RTS = uart_16550_main_u32("UART_16550_MAIN__MCR__RTS_bm")
MCR_OUT1 = uart_16550_main_u32("UART_16550_MAIN__MCR__OUT1_bm")
MCR_OUT2 = uart_16550_main_u32("UART_16550_MAIN__MCR__OUT2_bm")
MSR_DCTS = uart_16550_main_u32("UART_16550_MAIN__MSR__DCTS_bm")
MSR_DDSR = uart_16550_main_u32("UART_16550_MAIN__MSR__DDSR_bm")
MSR_TERI = uart_16550_main_u32("UART_16550_MAIN__MSR__TERI_bm")
MSR_DDCD = uart_16550_main_u32("UART_16550_MAIN__MSR__DDCD_bm")
MSR_CTS = uart_16550_main_u32("UART_16550_MAIN__MSR__CTS_bm")
MSR_DSR = uart_16550_main_u32("UART_16550_MAIN__MSR__DSR_bm")
MSR_RI = uart_16550_main_u32("UART_16550_MAIN__MSR__RI_bm")
MSR_DCD = uart_16550_main_u32("UART_16550_MAIN__MSR__DCD_bm")
# uart_16550_main.rdl: DCTS, DDSR and DDCD set when their level "has changed
# since the last time this register was read", while TERI sets only when RI
# "has changed from a `1` to a `0`" -- a trailing edge, not any change.
MSR_ANY_EDGE_DELTAS = MSR_DCTS | MSR_DDSR | MSR_DDCD
MSR_DELTAS = MSR_ANY_EDGE_DELTAS | MSR_TERI
MSR_LEVELS = MSR_CTS | MSR_DSR | MSR_RI | MSR_DCD
FCR_FIFO_ENABLE = uart_16550_wo_u32("UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
FCR_RCVR_FIFO_RESET = uart_16550_wo_u32("UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm")
FCR_XMIT_FIFO_RESET = uart_16550_wo_u32("UART_16550_MAIN_WO__FCR__XMIT_FIFO_RESET_bm")
THR_OFFSET = uart_16550_wo_offset("UART_16550_MAIN_WO_THR_BASE_ADDR")
FCR_OFFSET = uart_16550_wo_offset("UART_16550_MAIN_WO_FCR_BASE_ADDR")
DLL_OFFSET = uart_16550_dl_offset("UART_16550_DL_DLL_BASE_ADDR")
DLM_OFFSET = uart_16550_dl_offset("UART_16550_DL_DLM_BASE_ADDR")

CTRL_EN = log_engine_u32("LOG_ENGINE__CTRL__EN_bm")
LOG_LEN = log_engine_u32("LOG_ENGINE__LOG_CTRL__LOG_LEN_bm")
INTR_STATUS_MASK = log_engine_u32("LOG_ENGINE__INTR_STATUS__LOG_FETCH_ERR_bm") | log_engine_u32(
    "LOG_ENGINE__INTR_STATUS__LOG_WRITE_ERR_bm"
)

# uart_16550_main.rdl, LCR.WLS: "0x3 - 8 bits per character". The log engine
# hands the UART whole bytes, so the character has to be eight bits wide.
WLS_8_BITS = 3
# uart_16550_dl.rdl, DLL: "baud_rate = system_clock_frequency / (16 * (divisor
# + 1))", and "When the divisor is set to 0, the transmitter and receiver logic
# are disabled". 1 is the smallest divisor that keeps them running, so it is
# the fastest the loopback can carry the log.
DIVISOR = 1

# log_engine.rdl gives LOG_CTRL 16 elements and architecture.adoc divides the
# region equally among them, so a region size fixes the slot size.
NUM_LOG_ENTRIES = 16

# SEP_IN accesses `arm_uart` and `restore_uart` issue.
ARM_UART_ACCESSES = 10
RESTORE_UART_ACCESSES = 8


def uart_reg(wrap: int, register: str) -> int:
    """Absolute address of one UART register of wrapper ``wrap``."""
    return smc_indexed_addr(f"{WRAP}UART_{register}_BASE_ADDR", wrap)


def uart_base(wrap: int) -> int:
    """Base of the UART register window of wrapper ``wrap``."""
    return smc_indexed_addr(f"{WRAP}UART_BASE_ADDR", wrap)


def engine_reg(wrap: int, register: str) -> int:
    """Absolute address of one log-engine register of wrapper ``wrap``."""
    return smc_indexed_addr(f"{WRAP}LOG_ENGINE_{register}_BASE_ADDR", wrap)


def wrap_ctrl_reg(wrap: int) -> int:
    """The wrapper's own pad-mux enable register."""
    return smc_indexed_addr(f"{WRAP}UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", wrap)


async def arm_uart(seq, wrap: int) -> None:
    """Put one wrapper's UART in loopback at the fastest divisor."""
    base = uart_base(wrap)
    await seq.csr_write(f"WRAP{wrap}_PADMUX", wrap_ctrl_reg(wrap), UART_EN)
    await seq.csr_write(f"WRAP{wrap}_LCR_DLAB", uart_reg(wrap, "LCR"), LCR_DLAB)
    await seq.csr_write(f"WRAP{wrap}_DLL", base + DLL_OFFSET, DIVISOR)
    await seq.csr_write(f"WRAP{wrap}_DLM", base + DLM_OFFSET, 0)
    await seq.csr_write(f"WRAP{wrap}_LCR_8N1", uart_reg(wrap, "LCR"), WLS_8_BITS & LCR_WLS)
    await seq.csr_write(f"WRAP{wrap}_MCR_LOOP", uart_reg(wrap, "MCR"), MCR_LOOP)
    await seq.csr_write(f"WRAP{wrap}_FCR", base + FCR_OFFSET, FCR_FIFO_ENABLE)
    await seq.csr_write(f"WRAP{wrap}_IER", uart_reg(wrap, "IER"), 0)
    await seq.csr_read(f"WRAP{wrap}_MCR_RB", uart_reg(wrap, "MCR"), expected=MCR_LOOP)
    idle = await seq.csr_read(f"WRAP{wrap}_LSR_IDLE", uart_reg(wrap, "LSR"))
    assert idle & LSR_DR == 0, (
        f"wrapper {wrap}: LSR reports received data before the engine sent any, so the "
        f"receiver is not the quiet start the byte compare assumes"
    )


async def restore_uart(seq, wrap: int) -> None:
    """Put one wrapper's UART back to its reset configuration."""
    base = uart_base(wrap)
    await seq.csr_write(f"WRAP{wrap}_MCR_CLR", uart_reg(wrap, "MCR"), 0)
    await seq.csr_write(f"WRAP{wrap}_LCR_CLR", uart_reg(wrap, "LCR"), LCR_DLAB)
    await seq.csr_write(f"WRAP{wrap}_DLL_CLR", base + DLL_OFFSET, 0)
    await seq.csr_write(f"WRAP{wrap}_DLM_CLR", base + DLM_OFFSET, 0)
    await seq.csr_write(f"WRAP{wrap}_LCR_RESET", uart_reg(wrap, "LCR"), 0)
    await seq.csr_write(f"WRAP{wrap}_FCR_CLR", base + FCR_OFFSET, 0)
    await seq.csr_write(f"WRAP{wrap}_PADMUX_CLR", wrap_ctrl_reg(wrap), 0)
    await seq.csr_read(f"WRAP{wrap}_MCR_CLR_RB", uart_reg(wrap, "MCR"), expected=0)
