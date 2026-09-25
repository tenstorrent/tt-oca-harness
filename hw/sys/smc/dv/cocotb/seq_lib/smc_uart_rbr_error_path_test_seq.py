# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A UART character that arrives broken while the receive FIFO is off.

`uart_core.sv` carries the received character on one of two paths, chosen by
`FCR.FIFO_ENABLE`: through the receive FIFO, or through the receiver buffer
register on its own. Each path has its own copy of the error flags that travel
with a character. The FIFO path has met broken characters -- that is what
`smc_uart_error_conditions_test` drives -- and `smc_uart_core_mode_select_test`
sends clean characters down the register path, but nothing had ever sent a
broken one down it.

Two kinds are sent, which are the two the pair of UARTs can disagree into
existence:

* **Parity.** The transmitter is set to odd parity and the receiver to even,
  so every character arrives with the wrong parity bit.
* **Framing.** The transmitter sends eight bits and the receiver expects five,
  so the receiver samples its stop bit where a data bit still is. The
  character is chosen to put a zero there and a one earlier in the frame, so
  it is a framing error and not the all-zero frame that would be a break.

A clean character runs first on the same path, so the flags are the difference
the disagreement makes.

The third leg is the receive trigger level, which `uart_core.sv` builds from
`ECR.RCVR_TRIGGER_MS2B` and `FCR.RCVR_TRIGGER` together and compares against
the depth the FIFO was built with. Every leaf so far programs a level the
design supports; this one programs a level above the depth, where the
watermark can never be reached. With the FIFOs on and a character waiting,
`LSR.DR` has to report it while the received-data-ready interrupt stays away.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import UART_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

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

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")

FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
FCR_RCVR_TRIGGER_BP = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_TRIGGER_bp")
ECR_TRIGGER_MS2B_BP = _field_mask(_UART_H, "UART_16550_MAIN__ECR__RCVR_TRIGGER_MS2B_bp")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
IER_ELSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ELSI_bm")
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_PEN = _field_mask(_UART_H, "UART_16550_MAIN__LCR__PEN_bm")
LCR_EPS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__EPS_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_PE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__PE_bm")
LSR_FE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__FE_bm")
LSR_BI = _field_mask(_UART_H, "UART_16550_MAIN__LSR__BI_bm")
LSR_OE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__OE_bm")
#: The LSR error flags that clear on read (`uart_16550_main.rdl`).
LSR_READ_CLEARED = LSR_OE | LSR_PE | LSR_FE | LSR_BI

#: LCR.WLS encodings, from the field description in `uart_16550_main.rdl`.
WLS_5 = 0x0
WLS_8 = 0x3

#: The transmitter, reached through the UART3-to-UART0 cross, and the receiver.
TX_UART = 3
RX_UART = 0

CLEAN_BYTE = 0x55
#: Eight bits sent, five expected: the receiver samples its stop bit at the
#: sixth transmitted bit. This byte, sent least significant bit first, puts a
#: one in the first five, zeros in the sixth and seventh, and a one in the
#: eighth. The sixth is where the stop bit is sampled, so the frame is broken
#: but not all zeros. The eighth is what makes the receiver's framing visible:
#: a receiver still framing eight bits reads the whole byte with a good stop
#: bit, while one framing five reads only the low five bits.
FRAMING_BYTE = 0x81
FRAMING_FIVE_BITS = FRAMING_BYTE & 0x1F
#: A trigger level above the receive FIFO depth: 0x5 selects 64 entries, which
#: no FIFO in this configuration has.
UNSUPPORTED_RXILVL = 0x5

_INTR_RDR = 0x2
POLL_LIMIT = 512
POLL_NS = 100


def _uart_reg(name: str, idx: int) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_{name}_BASE_ADDR", idx
    )


class smc_uart_rbr_error_path_test_seq(SmcCsrSeq):
    """A broken character must carry its flags through the register path too."""

    def __init__(self, name: str = "smc_uart_rbr_error_path_test_seq") -> None:
        super().__init__(name)
        self.seen: list[tuple[str, int]] = []
        self.received: dict[str, int] = {}

    def _regs(self, idx: int) -> dict[str, int]:
        return {
            "ctrl": smc_indexed_addr(
                "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
                idx,
            ),
            **{k: _uart_reg(k.upper(), idx) for k in ("rbr", "ier", "iir", "lcr", "mcr", "lsr")},
            "ecr": _uart_reg("ECR", idx),
        }

    async def _program(
        self, idx: int, tag: str, *, wls: int, pen: bool, eps: bool, fifo: int
    ) -> dict[str, int]:
        r = self._regs(idx)
        await self.csr_write(f"{tag}_EN", r["ctrl"], UART_EN)
        await self.csr_write(f"{tag}_MCR", r["mcr"], MCR_RTS)
        await self.csr_write(f"{tag}_LCR_DLAB", r["lcr"], wls | LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", r["rbr"], 1)
        await self.csr_write(f"{tag}_DLH", r["ier"], 0)
        lcr = wls | (LCR_PEN if pen else 0) | (LCR_EPS if eps else 0)
        await self.csr_write(f"{tag}_LCR", r["lcr"], lcr)
        await self.csr_read(f"{tag}_LCR_RB", r["lcr"], expected=lcr)
        await self.csr_write(f"{tag}_IER", r["ier"], IER_ERBFI | IER_ELSI)
        await self.csr_write(f"{tag}_FCR", r["iir"], fifo)
        # Reads clear what an earlier leg left behind.
        await self.csr_read(f"{tag}_LSR_CLR", r["lsr"])
        await self.csr_read(f"{tag}_IIR_CLR", r["iir"])
        await self.csr_read(f"{tag}_RBR_CLR", r["rbr"])
        return r

    async def _await_lsr(self, r: dict[str, int], tag: str, want: int) -> int:
        """Poll LSR until ``want`` is set, then read it once more.

        The character's error flags are levels while it sits in the receiver
        buffer register, and `ERROR_IN_RCVR_FIFO` follows them directly, but
        `PE`, `FE` and `BI` are sticky copies that are set a cycle later and
        cleared by any read of LSR. The read that first sees `DR` can fall in
        that cycle and return the character with its flag not yet set. The
        character stays in the register until it is read out, so the flag is
        set again after that read, and a second read before popping it sees
        it. Every error flag returned by any read of the poll is kept.
        """
        lsr = 0
        seen = 0
        for _ in range(POLL_LIMIT):
            lsr = await self.csr_read(f"{tag}_LSR", r["lsr"])
            seen |= lsr & LSR_READ_CLEARED
            if lsr & want == want:
                await Timer(POLL_NS, unit="ns")
                again = await self.csr_read(f"{tag}_LSR_AGAIN", r["lsr"])
                return again | seen
            await Timer(POLL_NS, unit="ns")
        return lsr | seen

    async def _leg(self, tag: str, tx_wls: int, rx_wls: int, tx_eps: bool, byte: int) -> int:
        """Send one character with the two ends configured as given."""
        pen = tx_wls == rx_wls
        tx = await self._program(TX_UART, f"{tag}_TX", wls=tx_wls, pen=pen, eps=tx_eps, fifo=0)
        rx = await self._program(RX_UART, f"{tag}_RX", wls=rx_wls, pen=pen, eps=True, fifo=0)
        await self.csr_write(f"{tag}_SEND", tx["rbr"], byte)
        lsr = await self._await_lsr(rx, tag, LSR_DR)
        assert lsr & LSR_DR, (
            f"{tag}: no character reached the receiver with the FIFOs disabled (LSR=0x{lsr:08x})"
        )
        char = (await self.csr_read(f"{tag}_POP", rx["rbr"])) & 0xFF
        self.received[tag] = char
        return lsr

    async def body(self) -> None:
        assert "smc_uart_cross_3to0" in cocotb.plusargs, (
            "smc_uart_rbr_error_path_test needs +smc_uart_cross_3to0; without it UART3's "
            "transmit pin does not reach UART0's receive pin"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)

        clean = await self._leg("CLEAN", WLS_8, WLS_8, True, CLEAN_BYTE)
        assert clean & (LSR_PE | LSR_FE | LSR_BI) == 0, (
            f"a character both ends agreed on arrived with an error flag (LSR=0x{clean:08x}); "
            f"the two legs below are the difference the disagreement makes"
        )
        cocotb.log.info(
            "CHK-UART-RBR-CLEAN: with the FIFOs disabled a character both ends agreed on "
            "reached the receiver buffer register with no error flag (LSR=0x%08x)",
            clean,
        )

        parity = await self._leg("PARITY", WLS_8, WLS_8, False, CLEAN_BYTE)
        assert parity & LSR_PE, (
            f"a character sent with odd parity to a receiver set to even did not set LSR.PE "
            f"on the register path (LSR=0x{parity:08x})"
        )
        self.seen.append(("parity", parity))

        framing = await self._leg("FRAMING", WLS_8, WLS_5, True, FRAMING_BYTE)
        assert framing & LSR_FE, (
            f"a character whose stop bit the receiver sampled on a data bit did not set LSR.FE "
            f"on the register path (LSR=0x{framing:08x})"
        )
        assert self.received["FRAMING"] == FRAMING_FIVE_BITS, (
            f"the framing character was read back as 0x{self.received['FRAMING']:02x}, not the "
            f"0x{FRAMING_FIVE_BITS:02x} of its low five bits; the receiver framed it with a "
            f"word length other than the five it was programmed with"
        )
        assert framing & LSR_BI == 0, (
            f"the framing character also read as a break (LSR=0x{framing:08x}); it carries a "
            f"one, so the frame is not the all-zero one a break is"
        )
        self.seen.append(("framing", framing))
        cocotb.log.info(
            "CHK-UART-RBR-ERRORS: with the FIFOs disabled, a parity disagreement and a word "
            "length disagreement each reached the receiver buffer register with their own flag "
            "and no other: %s",
            ", ".join(f"{name} LSR=0x{lsr:08x}" for name, lsr in self.seen),
        )

        # ---- A trigger level the FIFO is not deep enough for ----------------
        rx = self._regs(RX_UART)
        await self.csr_write(
            "RXILVL_ECR", rx["ecr"], (UNSUPPORTED_RXILVL >> 2) << ECR_TRIGGER_MS2B_BP
        )
        tx = await self._program(TX_UART, "RXILVL_TX", wls=WLS_8, pen=False, eps=True, fifo=0)
        rx = await self._program(
            RX_UART,
            "RXILVL_RX",
            wls=WLS_8,
            pen=False,
            eps=True,
            fifo=FCR_FIFO_ENABLE | ((UNSUPPORTED_RXILVL & 0x3) << FCR_RCVR_TRIGGER_BP),
        )
        await self.csr_write("RXILVL_SEND", tx["rbr"], CLEAN_BYTE)
        lsr = await self._await_lsr(rx, "RXILVL", LSR_DR)
        assert lsr & LSR_DR, (
            f"no character reached the receiver with a trigger level above the FIFO depth "
            f"(LSR=0x{lsr:08x})"
        )
        iir = await self.csr_read("RXILVL_IIR", rx["iir"])
        pending = (iir & IIR_INTERRUPT_PENDING) == 0
        ident = (iir & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP
        assert not (pending and ident == _INTR_RDR), (
            f"the received-data-ready interrupt is pending (IIR=0x{iir:08x}) with the trigger "
            f"level set above the FIFO depth; the watermark it counts against can never be "
            f"reached"
        )
        await self.csr_read("RXILVL_POP", rx["rbr"])
        await self.csr_write("RXILVL_ECR_RESTORE", rx["ecr"], 0)
        cocotb.log.info(
            "CHK-UART-RXILVL-UNSUPPORTED: with the receive trigger level programmed to 0x%x, "
            "which selects more entries than the FIFO holds, a character still reached the "
            "receiver (LSR=0x%08x) and the received-data-ready interrupt stayed away "
            "(IIR=0x%08x)",
            UNSUPPORTED_RXILVL,
            lsr,
            iir,
        )
