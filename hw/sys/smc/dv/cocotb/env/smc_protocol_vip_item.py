# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC protocol VIP sequence item.

This item records an OSS-runnable protocol intent for tests that still use
direct-AXI CSR stimulus until public BFMs are available.
"""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcProtocolVipKind(Enum):
    I2C = "i2c"
    I3C = "i3c"
    JTAG = "jtag"
    OUTPUT_FABRIC = "output_fabric"
    MAILBOX = "mailbox"
    EFUSE = "efuse"
    CLOCK = "clock"
    GPIO_IRQ = "gpio_irq"
    UART_LOG = "uart_log"
    SIDEBAND = "sideband"
    ZEROER_DMA = "zeroer_dma"
    DIAGNOSTIC = "diagnostic"
    CPU = "cpu"
    CSR = "csr"
    AXI = "axi"


class SmcProtocolVipItem(uvm_sequence_item):
    """A completed high-level protocol VIP scenario."""

    def __init__(self, name: str = "SmcProtocolVipItem") -> None:
        super().__init__(name)
        self.kind: SmcProtocolVipKind = SmcProtocolVipKind.I2C
        self.scenario: str = "unspecified"
        self.proxy: bool = True
        self.csr_accesses: int = 0
        self.timeouts: int = 0
        # Completion marker only — not a checker. Sequences abort on any real
        # protocol mismatch before recording, so a recorded item already implies
        # sequence-level checks passed. The scoreboard validates evidence
        # consistency (scenario/details/counts/golden), not this field.
        self.passed: bool = True
        self.details: str = ""
        # U6-3 optional byte-level golden (None = no golden gate).
        self.expected_bytes: bytes | None = None
        self.observed_bytes: bytes | None = None

    def __str__(self) -> str:
        mode = "proxy" if self.proxy else "protocol"
        golden = ""
        if self.expected_bytes is not None:
            golden = (
                f" golden={self.expected_bytes.hex()}"
                f" obs={(self.observed_bytes or b'').hex()}"
            )
        return (
            f"{self.kind.value}:{self.scenario} mode={mode} "
            f"csr_accesses={self.csr_accesses} timeouts={self.timeouts} "
            f"passed={self.passed}{golden} details={self.details}"
        )
