# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART log-engine golden path: SRAM entry fetched and written to the UART, looped back.

Firmware test: `fw/tests/uart_log_engine_single_entry` is loaded into scratch
by the firmware loader. It writes a 16-byte pattern into SPM, points wrap 0's
engine at it (LOG_REGION_ADDR/SIZE) and at UART0's THR (LOG_WRITE_ADDR), puts
UART0 in MCR.LOOP with the received-data interrupt enabled, triggers
LOG_CTRL[0] = 16 and reads the 16 bytes back from RBR in order, then requires
LOG_CTRL[0] to have hwclr'd and INTR_STATUS to be 0. MCR.LOOP keeps the bytes
inside the UART, so the byte compare is the firmware's.

Bench observation: the UART interrupt line (tb_uart_irq_any, the OR over the
UART wraps; only UART0 is programmed by the image) rose while the image ran, so
a looped-back byte did land in the RX FIFO; after the PASS word
the SPM source region still holds 0xA0..0xAF, and the engine reads back
programmed at that region with CTRL.EN and MCR.LOOP cleared by the cleanup.

Tokens: CHK-FW-LOG-ENGINE-SINGLE-BOOT, CHK-FW-LOG-ENGINE-CSR-STATE,
CHK-FW-LOG-ENGINE-SPM-PATTERN, CHK-FW-LOG-ENGINE-UART-IRQ.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=uart_log_engine_single_entry.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_log_engine_test_seq import (
    LOG_BUFFER_BASE,
    LogEngineFinalState,
    smc_fw_log_engine_test_seq,
    uart_reg,
)
from smc_base_test import smc_base_test

XFER_LEN = 16
LOG_REGION_SIZE = 0x100


@pyuvm.test()
class smc_fw_uart_log_engine_single_entry_test(smc_base_test):
    """Firmware runs one 16-byte log entry; the bench sees the IRQ, source and engine state."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-LOG-ENGINE-CSR-STATE",
        "CHK-FW-LOG-ENGINE-SINGLE-BOOT",
        "CHK-FW-LOG-ENGINE-SPM-PATTERN",
        "CHK-FW-LOG-ENGINE-UART-IRQ",
    )
    min_evidence = 4

    async def run_scenario(self) -> None:
        seq = smc_fw_log_engine_test_seq(
            "fw_uart_log_engine_single_entry_seq",
            tag="LOG-ENGINE-SINGLE",
            # PASS landed 100 us after release in the reference run (~200 polls at a
            # 5 ns clk_smc_i); 2000 is ~10x that.
            poll_iterations=2_000,
            spm_pattern=bytes(0xA0 + i for i in range(XFER_LEN)),
            engines=(LogEngineFinalState(0, LOG_BUFFER_BASE, LOG_REGION_SIZE, uart_reg(0, "RBR")),),
            expect_uart_irq=True,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.csr_state_ok and seq.spm_pattern_ok and seq.uart_irq_ok, (
            f"bench observation incomplete: csr={seq.csr_state_ok} spm={seq.spm_pattern_ok} "
            f"irq={seq.uart_irq_ok}"
        )
