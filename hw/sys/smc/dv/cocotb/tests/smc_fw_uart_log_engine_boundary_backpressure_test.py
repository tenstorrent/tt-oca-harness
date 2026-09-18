# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART log-engine effective-length boundaries and log-write under TX backpressure.

Firmware test: `fw/tests/uart_log_engine_boundary_backpressure` is loaded into
scratch by the firmware loader. On wrap 0 with UART0 in MCR.LOOP it runs: A, an
8-byte request inside a 16-byte slot (one fetch beat); B, a 64-byte request
into a 64-byte slot that overfills the 32-entry UART TX FIFO so the write FSM
runs against uart_tx_ready low; C, a completion check against a defined UART
offset (the write-error path is unreachable, as the image documents); D, a
24-byte request clamped to its 16-byte slot; E, a 15-byte slot rounded down to
one 8-byte beat. A, D and E read back exactly the requested or clamped byte
count from RBR and require no extra byte. Those compares are the firmware's.

Bench observation: after the PASS word the SPM source holds E's 0xE0..0xEF in
its first 16 bytes and B's 0x50..0x7F behind them (B was the only scenario to
write past byte 16), and the engine reads back programmed as E left it --
REGION_SIZE 0xF0 at the buffer, LOG_WRITE_ADDR at UART0's THR -- with CTRL.EN
and MCR.LOOP cleared by the cleanup.

Tokens: CHK-FW-LOG-ENGINE-BOUNDARY-BOOT, CHK-FW-LOG-ENGINE-CSR-STATE,
CHK-FW-LOG-ENGINE-SPM-PATTERN.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=uart_log_engine_boundary_backpressure.ecc.hex   (bare basename; staged by c_compile)
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

# Scenario E: 240 / 16 = 15 bytes per slot.
SCENARIO_E_REGION_SIZE = 0xF0
# Bytes 0..15 are scenario E's 0xE0.., bytes 16..63 are what remains of
# scenario B's 0x40 + i fill (A, C, D and E rewrite only the first 8 or 16).
SPM_PATTERN = bytes(0xE0 + i for i in range(16)) + bytes(0x40 + i for i in range(16, 64))


@pyuvm.test()
class smc_fw_uart_log_engine_boundary_backpressure_test(smc_base_test):
    """Firmware runs the boundary scenarios; the bench reads the source and engine state."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-LOG-ENGINE-BOUNDARY-BOOT",
        "CHK-FW-LOG-ENGINE-CSR-STATE",
        "CHK-FW-LOG-ENGINE-SPM-PATTERN",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        seq = smc_fw_log_engine_test_seq(
            "fw_uart_log_engine_boundary_backpressure_seq",
            tag="LOG-ENGINE-BOUNDARY",
            # PASS landed 334 us after release in the reference run (~670 polls at a
            # 5 ns clk_smc_i); 7000 is ~10x that.
            poll_iterations=7_000,
            spm_pattern=SPM_PATTERN,
            engines=(
                LogEngineFinalState(0, LOG_BUFFER_BASE, SCENARIO_E_REGION_SIZE, uart_reg(0, "RBR")),
            ),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.csr_state_ok and seq.spm_pattern_ok, (
            f"bench observation incomplete: csr={seq.csr_state_ok} spm={seq.spm_pattern_ok}"
        )
