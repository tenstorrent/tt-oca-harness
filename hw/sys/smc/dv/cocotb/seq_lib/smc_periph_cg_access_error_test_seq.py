# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every clock-gated peripheral answers SLVERR with 0xBADCAB1E while its gate is closed.

``CLOCK_GATE_CONTROL`` stops the AVSBus, I2C, UART, telemetry and I3C clocks
with one enable each. In front of each of those peripherals an access gate on
the SMC clock steers the crossbar leg into an error slave while the enable is
set, so software reads an error instead of waiting on a register block whose
clock has stopped. For each peripheral the same three-step experiment runs on
its own enable, with the other four enables cleared:

1. gate CLEARED -- a probe register answers OKAY and its word is recorded
   ([NEGATIVE-NEEDS-POSITIVE-CONTROL]);
2. gate SET -- a read of the probe completes SLVERR with ``0xBADCAB1E`` and a
   write of the complemented word completes SLVERR; a no-response raises in
   the driver, so a wedged access fails the run ([TIMEOUT-MUST-FAIL]);
3. gate CLEARED -- the probe answers OKAY with the recorded word, so the
   refused write took no effect and the peripheral is reachable again.

The probe of each peripheral is a register of its generated map that answers
at reset on this bench; where the register is writable the recovery read also
shows the refused write landed nowhere.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import (
    AVS_CG_EN,
    CLOCK_GATE_CONTROL,
    I2C_CG_EN,
    I3C_CG_EN,
    TELEMETRY_CG_EN,
    UART_CG_EN,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i3c_to_fabric_test_seq import HCI_VERSION_OFFSET

AXI_RESP_SLVERR = 2
# The word the access gates' error slaves return while a peripheral clock is gated.
GATED_RDATA = SmcCsrSeq.ERR_SLAVE_SIGNATURE

# (peripheral, CLOCK_GATE_CONTROL enable, probe register, probe address)
PERIPHERALS: tuple[tuple[str, int, str, int], ...] = (
    (
        "AVSBUS",
        AVS_CG_EN,
        "AVS_CFG_0",
        smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR"),
    ),
    (
        "I2C",
        I2C_CG_EN,
        "I2C_CTRL_0",
        smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", 0),
    ),
    (
        "UART",
        UART_CG_EN,
        "UART0_LOG_ENGINE_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
        ),
    ),
    (
        "TELEMETRY",
        TELEMETRY_CG_EN,
        "TELEMETRY0_CTRL",
        smc_indexed_addr(
            "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_CTRL_BASE_ADDR", 0
        ),
    ),
    (
        "I3C",
        I3C_CG_EN,
        "I3C0_HCI_VERSION",
        smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", 0) + HCI_VERSION_OFFSET,
    ),
)
ALL_PERIPH_CG_EN = AVS_CG_EN | I2C_CG_EN | UART_CG_EN | TELEMETRY_CG_EN | I3C_CG_EN

# Per peripheral: ungated probe read (1), gate write + readback (2), gated read
# and refused write (2), ungate write + readback (2), recovery read (1).
ACCESSES_PER_PERIPHERAL = 8
# Plus the CLOCK_GATE_CONTROL save (1), the write + readback that clears all
# five enables (2) and the restore write + readback (2).
EXPECTED_ACCESSES = 5 + ACCESSES_PER_PERIPHERAL * len(PERIPHERALS)
# Value-checked reads: the clear-all readback, two readbacks and the recovery
# read per peripheral, and the restore readback.
EXPECTED_VALUE_CHECKS = 2 + 3 * len(PERIPHERALS)


class smc_periph_cg_access_error_test_seq(SmcCsrSeq):
    """Gate each peripheral clock in turn and hold its window to SLVERR/0xBADCAB1E."""

    def __init__(self, name: str = "smc_periph_cg_access_error_test_seq") -> None:
        super().__init__(name)
        # Probe word per peripheral from the ungated positive control.
        self.ungated_words: dict[str, int] = {}
        # Peripherals whose gated read and write both completed SLVERR.
        self.gated_refused: list[str] = []
        # Peripherals whose recovery read returned the positive control's word.
        self.recovered: list[str] = []
        self.value_checks = 0

    async def _one_peripheral(self, periph: str, cg_en: int, reg: str, addr: int, base: int):
        word = await self.csr_read(f"{periph}_{reg}_UNGATED", addr)
        self.ungated_words[periph] = word

        gated = base | cg_en
        await self.csr_write(f"CLOCK_GATE_CONTROL_{periph}_ON", CLOCK_GATE_CONTROL, gated)
        await self.csr_read(f"CLOCK_GATE_CONTROL_{periph}_ON", CLOCK_GATE_CONTROL, expected=gated)
        # Exact code and exact word on the read; exact code on the write. The
        # complement of the recorded word is written so a write that leaked
        # through the gate into a writable field is caught by the recovery read.
        await self.csr_read_err_signature(f"{periph}_{reg}_GATED", addr, resp=AXI_RESP_SLVERR)
        await self.csr_write_expect_error(
            f"{periph}_{reg}_GATED", addr, (~word) & 0xFFFF_FFFF, resp=AXI_RESP_SLVERR
        )
        self.gated_refused.append(periph)

        await self.csr_write(f"CLOCK_GATE_CONTROL_{periph}_OFF", CLOCK_GATE_CONTROL, base)
        await self.csr_read(f"CLOCK_GATE_CONTROL_{periph}_OFF", CLOCK_GATE_CONTROL, expected=base)
        await self.csr_read(f"{periph}_{reg}_RECOVERED", addr, expected=word)
        self.recovered.append(periph)

        cocotb.log.info(
            "CHK-PERIPH-CG-ACCESS-ERROR-%s: %s @ 0x%08x answered OKAY (0x%08x) ungated, "
            "SLVERR with 0x%08X on read and SLVERR on write with CLOCK_GATE_CONTROL=0x%x, "
            "and OKAY with the same word again once the enable was cleared",
            periph,
            reg,
            addr,
            word,
            GATED_RDATA,
            gated,
        )

    async def body(self) -> None:
        original = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        base = original & ~ALL_PERIPH_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_ALL_OFF", CLOCK_GATE_CONTROL, base)
        await self.csr_read("CLOCK_GATE_CONTROL_ALL_OFF", CLOCK_GATE_CONTROL, expected=base)

        for periph, cg_en, reg, addr in PERIPHERALS:
            await self._one_peripheral(periph, cg_en, reg, addr, base)

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=original)

        # ---- Reconciliation against the scoreboard, not against self-counts ----
        self.assert_all_reachable(EXPECTED_ACCESSES, "PERIPH_CG_ACCESS_ERROR")
        sb = self.env.scoreboard
        self.value_checks = sb.sys_axi_value_checks_seen
        assert self.value_checks >= EXPECTED_VALUE_CHECKS, (
            f"expected {EXPECTED_VALUE_CHECKS} value-checked SEP_IN AXI reads "
            f"(CLOCK_GATE_CONTROL readbacks and the recovery reads), scoreboard saw "
            f"{self.value_checks}"
        )
        cocotb.log.info(
            "CHK-PERIPH-CG-ACCESS-ERROR-SWEEP: %d peripheral(s) [%s] each answered OKAY "
            "ungated, SLVERR with 0x%08X on read and SLVERR on write gated, and the recorded "
            "word again ungated; CLOCK_GATE_CONTROL restored to 0x%x; scoreboard "
            "value_checks=%d (>= %d)",
            len(PERIPHERALS),
            ",".join(p for p, _cg, _r, _a in PERIPHERALS),
            GATED_RDATA,
            original,
            self.value_checks,
            EXPECTED_VALUE_CHECKS,
        )
