# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound mailbox 0 CSR precheck (TC_SMC_P1CG_01).

Reads the inbound-mailbox 0 STATUS/ERROR/IRQ CSR surface after enabling the
mailbox clock-gate.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = 1 << 1

MAILBOX0_INBOUND_STATUS = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + 0x10
MAILBOX0_INBOUND_ERROR_FLAGS = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + 0x18
MAILBOX0_INBOUND_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR") + 0x38


_INBOUND_EXPECTED = (
    ("MBOX0_INBOUND_STATUS", MAILBOX0_INBOUND_STATUS, 0x1),
    ("MBOX0_INBOUND_ERROR_FLAGS", MAILBOX0_INBOUND_ERROR_FLAGS, 0x0),
    ("MBOX0_INBOUND_IRQEN", MAILBOX0_INBOUND_IRQEN, 0x0),
)


class smc_mailbox_inbound_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        # Inbound mailbox 0 surface — strict reads asserting reset content,
        # identical on Verilator and VCS. STATUS, ERROR_FLAGS and IRQEN are RDL
        # reset constants (axil_mailbox.rdl) -> spec-anchored.
        for name, addr, expected in _INBOUND_EXPECTED:
            await self.csr_read(name, addr, expected=expected)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        self.assert_all_reachable(6, "MAILBOX_INBOUND")
        value_checks = sb.sys_axi_value_checks_seen - value_checks_before
        assert value_checks == len(_INBOUND_EXPECTED), (
            f"MAILBOX_INBOUND: the scoreboard booked {value_checks} exact-value compares "
            f"for {len(_INBOUND_EXPECTED)} reads that each carry an expected word"
        )
        cocotb.log.info(
            "CHK-MAILBOX-INBOUND-RESET-SURFACE: inbound mailbox 0 %s each matched its "
            "expected word in a scoreboard value compare with the mailbox clock gate "
            "enabled (CLOCK_GATE_CONTROL 0x%08x -> 0x%08x, restored after); %d SEP_IN "
            "accesses checked, %d value compares booked",
            ", ".join(f"{name}=0x{exp:x}" for name, _addr, exp in _INBOUND_EXPECTED),
            cg,
            cg | MAILBOX_CG_EN,
            self.accesses,
            value_checks,
        )
