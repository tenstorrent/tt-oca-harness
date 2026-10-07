# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART log-engine CTRL.EN cleared mid-transfer, multi-entry trigger, and replica 1.

Firmware test: `fw/tests/uart_log_engine_disable_during_xfer` is loaded into
scratch by the firmware loader. On wrap 0 with UART0 in MCR.LOOP it triggers a
32-byte entry (as deep as the UART TX FIFO, so the writer is still moving
bytes) and clears CTRL.EN one register access later, then counts the bytes the
loopback returns: at least one and fewer than 32, all from the slot, none once
the UART is idle,
with INTR_STATUS held at 0 while both error interrupts are enabled. A 16-byte
re-trigger must deliver exactly 16 bytes. It then fires four entries at once and
waits for all four LOG_CTRL words to hwclr, aborts another 32-byte transfer from
the WAIT state with the same byte-count halt check and recovery, and finally
runs a 16-byte entry on replica 1 (wrap 1). Every count, completion and status
check is the firmware's.

Bench observation: after the PASS word the 256-byte SPM source holds the
multi-entry fill 0xC0 + (i & 0x3F) that the later scenarios reuse, and both
engines read back programmed at that buffer -- REGION_SIZE 0x100,
LOG_WRITE_ADDR at their own UART's THR -- with CTRL.EN and MCR.LOOP cleared on
both wraps by the cleanup.

Tokens: CHK-FW-LOG-ENGINE-DISABLE-BOOT, CHK-FW-LOG-ENGINE-CSR-STATE,
CHK-FW-LOG-ENGINE-SPM-PATTERN.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=uart_log_engine_disable_during_xfer.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must not use +skip_fuse_sense: a run with the fuse sense skipped is not
evidence for the fuse-derived boot path.
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

LOG_REGION_SIZE = 0x100
# Scenario B fills the whole 256-byte region; nothing after it rewrites the buffer.
SPM_PATTERN = bytes(0xC0 + (i & 0x3F) for i in range(LOG_REGION_SIZE))


@pyuvm.test()
class smc_fw_uart_log_engine_disable_during_xfer_test(smc_base_test):
    """Firmware disables the engine mid-transfer; the bench reads both engines' state."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-LOG-ENGINE-CSR-STATE",
        "CHK-FW-LOG-ENGINE-DISABLE-BOOT",
        "CHK-FW-LOG-ENGINE-SPM-PATTERN",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        seq = smc_fw_log_engine_test_seq(
            "fw_uart_log_engine_disable_during_xfer_seq",
            tag="LOG-ENGINE-DISABLE",
            # PASS landed 497 us after release in the reference run (~990 polls at a
            # 5 ns clk_smc_i); 10_000 is ~10x that.
            poll_iterations=10_000,
            spm_pattern=SPM_PATTERN,
            engines=(
                LogEngineFinalState(0, LOG_BUFFER_BASE, LOG_REGION_SIZE, uart_reg(0, "RBR")),
                LogEngineFinalState(1, LOG_BUFFER_BASE, LOG_REGION_SIZE, uart_reg(1, "RBR")),
            ),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.csr_state_ok and seq.spm_pattern_ok, (
            f"bench observation incomplete: csr={seq.csr_state_ok} spm={seq.spm_pattern_ok}"
        )
