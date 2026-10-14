# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC protocol VIP sequence item.

This item records an OSS-runnable protocol intent for tests whose stimulus is
direct-AXI CSR traffic rather than a pad-level BFM.
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
        # None = "not measured on this path". Printing 0 for an unmeasured
        # counter manufactures a clean-looking statistic, so unmeasured is
        # rendered as `n/a` and the scoreboard skips the counter relations.
        self.timeouts: int | None = 0
        self.details: str = ""
        # True when this record was stamped automatically by
        # smc_base_test.run_phase rather than by a scenario that measured its
        # own protocol activity. An auto record is a coverage/activity stamp
        # only: the scoreboard books it in a separate `protocol_vip_auto` bin,
        # never counts it as a protocol check, and never lets it satisfy the
        # scoreboard's minimum-activity gate ([NO-ALWAYS-PASS-CHECKER]).
        self.auto_evidence: bool = False
        # Minimum CSR accesses the scenario's stimulus must have produced. This
        # converts `csr_accesses` from a printed statistic into a fail-capable
        # activity floor ([NO-ZERO-ACTIVITY-PASS]) and is MANDATORY (>0) on a
        # scenario-recorded item: with the floor at 0 every assert on the record
        # reduces to a constant while the item is still logged and counted as a
        # protocol VIP *check* ([NO-ALWAYS-PASS-CHECKER]). The default stays 0
        # because that is the only legal value for an `auto_evidence` stamp;
        # `smc_base_test.record_protocol_vip` refuses a floor-less recorded item
        # at the call site and `SmcScoreboard._check_protocol_vip` refuses to
        # book one as a check.
        self.min_csr_accesses: int = 0
        # Non-CSR fabric traffic (JTAG-AXI accesses, output-fabric beats) with
        # its own floor and a label naming what it is. Kept separate so such
        # accesses are never folded into `csr_accesses`, which would make the
        # record state a count of CSR traffic that did not happen.
        #
        # `fabric_accesses` is always MEASURED: smc_base_test.record_protocol_vip
        # fills it from SmcScoreboard.axi_accesses_by_bus (the driver-stamped
        # per-port tally of completed accesses), never from a value the call site
        # supplies -- a floor constant passed as the observation would make
        # `fabric_accesses >= min_fabric_accesses` a `C >= C` tautology
        # ([NO-ALWAYS-PASS-CHECKER]). `fabric_access_source` is printed so the
        # retained evidence names where the number came from.
        self.fabric_accesses: int = 0
        self.min_fabric_accesses: int = 0
        self.fabric_access_label: str = ""
        self.fabric_access_source: str = ""
        # Optional byte-level golden (None = no golden gate).
        self.expected_bytes: bytes | None = None
        self.observed_bytes: bytes | None = None

    def __str__(self) -> str:
        mode = "proxy" if self.proxy else "protocol"
        golden = ""
        if self.expected_bytes is not None:
            golden = f" golden={self.expected_bytes.hex()} obs={(self.observed_bytes or b'').hex()}"
        timeouts = "n/a" if self.timeouts is None else self.timeouts
        role = "AUTO-COVERAGE-STAMP" if self.auto_evidence else "scenario-recorded"
        fabric = ""
        if self.fabric_accesses or self.min_fabric_accesses:
            label = self.fabric_access_label or "non-CSR fabric"
            source = f" [{self.fabric_access_source}]" if self.fabric_access_source else ""
            fabric = f" {label}={self.fabric_accesses} (min={self.min_fabric_accesses}){source}"
        return (
            f"{self.kind.value}:{self.scenario} mode={mode} role={role} "
            f"csr_accesses={self.csr_accesses} (min={self.min_csr_accesses})"
            f"{fabric} timeouts={timeouts}{golden} details={self.details}"
        )
