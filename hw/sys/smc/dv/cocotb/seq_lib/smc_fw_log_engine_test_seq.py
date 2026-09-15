# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART log-engine data path under firmware; the bench reads what the engine used.

The four images built on this sequence -- single_entry (golden path),
boundary_backpressure (effective-length boundaries and TX backpressure),
disable_during_xfer (CTRL.EN cleared mid-transfer, multi-entry, replica 1),
fetch_err (AXI fetch DECERR -> INTR_STATUS.LOG_FETCH_ERR) -- each pre-load a
pattern into SPM, point LOG_REGION_ADDR at it, point LOG_WRITE_ADDR at the
UART's THR, put the UART in MCR.LOOP so the bytes come back through its own
receiver, and compare what they read from RBR against the pattern. MCR.LOOP
keeps the bytes inside the UART: tx_o stays marking and no pad carries them.
The byte-for-byte compare is therefore the firmware's, and this sequence does
not claim it.

What the bench observes on its own, after the PASS word:

* the SPM region the engine fetched from still holds the pattern the image
  says it transferred (read over SEP_IN AXI, 64 bits at a time);
* the engine's LOG_REGION_ADDR / LOG_REGION_SIZE / LOG_WRITE_ADDR read back as
  the image's final scenario programmed them, and CTRL.EN and UART MCR read
  back cleared as the image's cleanup left them;
* when the image enables the UART received-data interrupt (single_entry),
  the UART interrupt line rose while the run was live: a looped-back byte did
  land in the RX FIFO. tb_uart_irq_any is the OR over the UART wraps'
  interrupt outputs, and UART0 is the only one the image programs;
* when the image fetches from an unmapped address (fetch_err), a SEP_IN read of
  that address returns an AXI error: the fabric really answers it with DECERR,
  which is the cause the firmware's LOG_FETCH_ERR check rests on.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb

from .smc_addr_map import SPM_MEMORY_BASE, smc_indexed_addr
from .smc_fw_image_boot_seq import smc_fw_image_boot_seq

_LE = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_"
_UART = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_"

# LOG_BUFFER_BASE in every image: SPM + 0x40000.
LOG_BUFFER_BASE = SPM_MEMORY_BASE + 0x40000
# MCR bit 4, LOOP (uart_16550_main.rdl); the value every image writes as 0x10.
UART_MCR_LOOP = 0x10
UART_IRQ_SIGNAL = "tb_uart_irq_any"


def le_reg(wrap: int, name: str) -> int:
    return smc_indexed_addr(f"{_LE}{name}_BASE_ADDR", wrap)


def uart_reg(wrap: int, name: str) -> int:
    return smc_indexed_addr(f"{_UART}{name}_BASE_ADDR", wrap)


@dataclass(frozen=True)
class LogEngineFinalState:
    """What one wrap's engine and UART should read back after the image's cleanup."""

    wrap: int
    region_addr: int
    region_size: int
    write_addr: int
    #: The image's cleanup wrote MCR = 0 on this wrap.
    mcr_cleared: bool = True


class smc_fw_log_engine_test_seq(smc_fw_image_boot_seq):
    """Boot a log-engine image, then read back the engine state and its SRAM source."""

    def __init__(
        self,
        name: str,
        *,
        tag: str,
        poll_iterations: int,
        spm_pattern: bytes,
        engines: tuple[LogEngineFinalState, ...],
        expect_uart_irq: bool = False,
        decerr_probe: int | None = None,
    ) -> None:
        super().__init__(name)
        assert len(spm_pattern) % 8 == 0, "pattern is read as 64-bit words"
        self.tag = tag
        self.poll_iterations = poll_iterations
        self.spm_pattern = spm_pattern
        self.engines = engines
        self.expect_uart_irq = expect_uart_irq
        self.decerr_probe = decerr_probe
        self.uart_irq_edges = 0
        self.csr_state_ok = False
        self.spm_pattern_ok = False
        self.uart_irq_ok = False
        self.decerr_ok = False

    async def before_boot(self) -> None:
        if self.expect_uart_irq:
            self.count_edges_from_now(UART_IRQ_SIGNAL)

    async def _check_engine(self, final: LogEngineFinalState) -> None:
        w = final.wrap
        ctrl = await self.csr_read(f"LE{w}_CTRL", le_reg(w, "CTRL"))
        region_addr = await self.csr_read(f"LE{w}_REGION_ADDR", le_reg(w, "LOG_REGION_ADDR"))
        region_size = await self.csr_read(f"LE{w}_REGION_SIZE", le_reg(w, "LOG_REGION_SIZE"))
        write_addr = await self.csr_read(f"LE{w}_WRITE_ADDR", le_reg(w, "LOG_WRITE_ADDR"))
        mcr = await self.csr_read(f"UART{w}_MCR", uart_reg(w, "MCR"))
        got = (ctrl & 1, region_addr, region_size, write_addr)
        want = (0, final.region_addr, final.region_size, final.write_addr)
        assert got == want, (
            f"wrap {w} engine state (CTRL.EN, REGION_ADDR, REGION_SIZE, WRITE_ADDR) = "
            f"{tuple(hex(v) for v in got)}, expected {tuple(hex(v) for v in want)}"
        )
        if final.mcr_cleared:
            assert mcr & UART_MCR_LOOP == 0, (
                f"wrap {w} UART MCR=0x{mcr:08x} still has LOOP set after the image's cleanup"
            )
        cocotb.log.info(
            "CHK-FW-LOG-ENGINE-CSR-STATE: wrap %d CTRL=0x%x REGION_ADDR=0x%08x "
            "REGION_SIZE=0x%x WRITE_ADDR=0x%08x UART MCR=0x%02x (read over SEP_IN after PASS)",
            w,
            ctrl,
            region_addr,
            region_size,
            write_addr,
            mcr,
        )

    async def after_pass(self) -> None:
        for final in self.engines:
            await self._check_engine(final)
        self.csr_state_ok = True

        got = bytearray()
        for off in range(0, len(self.spm_pattern), 8):
            word = await self.csr_read(f"SPM_LOG_{off:03x}", LOG_BUFFER_BASE + off, length=8)
            got += word.to_bytes(8, "little")
        assert bytes(got) == self.spm_pattern, (
            f"SPM at 0x{LOG_BUFFER_BASE:08x} holds {got.hex()} but the image's fetch source "
            f"should be {self.spm_pattern.hex()}"
        )
        self.spm_pattern_ok = True
        cocotb.log.info(
            "CHK-FW-LOG-ENGINE-SPM-PATTERN: %d bytes at 0x%08x match the image's fetch source "
            "(first 0x%02x last 0x%02x)",
            len(got),
            LOG_BUFFER_BASE,
            got[0],
            got[-1],
        )

        if self.expect_uart_irq:
            self.uart_irq_edges = self.edges_counted(UART_IRQ_SIGNAL)
            assert self.uart_irq_edges >= 1, (
                f"{UART_IRQ_SIGNAL} never rose: no looped-back byte reached the UART RX FIFO "
                f"with the received-data interrupt enabled"
            )
            self.uart_irq_ok = True
            cocotb.log.info(
                "CHK-FW-LOG-ENGINE-UART-IRQ: %s rose %d time(s) while the image ran",
                UART_IRQ_SIGNAL,
                self.uart_irq_edges,
            )

        if self.decerr_probe is not None:
            # The SEP_IN monitor treats DECERR as a protocol failure unless the
            # address is declared; this read exists to observe exactly that
            # response, the same declaration the deadspace-decode leaf makes.
            self.env.axi_monitor.expected_decerr_addrs.add(self.decerr_probe)
            await self.csr_read_expect_error("LOG_FETCH_TARGET", self.decerr_probe)
            self.decerr_ok = True
            cocotb.log.info(
                "CHK-FW-LOG-ENGINE-FETCH-DECERR: SEP_IN read of 0x%08x, the image's fetch "
                "region, returned an AXI error response",
                self.decerr_probe,
            )
