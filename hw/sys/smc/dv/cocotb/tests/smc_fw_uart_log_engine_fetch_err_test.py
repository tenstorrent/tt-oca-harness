# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART log-engine fetch from an unmapped address raises INTR_STATUS.LOG_FETCH_ERR.

Firmware test: `fw/tests/uart_log_engine_fetch_err` is loaded into scratch by
the firmware loader. It derives an unmapped SMC-local address from the
generated map (the first 4 KB boundary past the WDT cluster, checked at
compile time to lie before the reset unit), and on wrap 0 runs: the INTR_TEST
self-test for both bits, INTR_STATUS capture while INTR_ENABLE masks irq_o, a
fetch from the unmapped region that must latch LOG_FETCH_ERR and clear on W1C
once the engine is stopped, a good fetch proving the engine recovers, a
sustained DECERR over a 4 KB region whose LOG_CTRL must not hwclr, the same
fault with WRITE_ERR unmasked, and the fault on replica 1. Sixteen CHK tokens
are counted inside the image and PASS is refused if any is missing.

Bench observation: a SEP_IN AXI read of that unmapped address returns an error
response, so the fabric really answers the image's fetch region with DECERR;
after the PASS word the SPM region used for the retiring good fetches still
holds 0xD0..0xDF, and both engines read back pointed at the unmapped region
with CTRL.EN cleared (wrap 0's MCR.LOOP cleared by the cleanup; wrap 1's UART
was never configured by the image and is not checked).

Tokens: CHK-FW-LOG-ENGINE-FETCH-ERR-BOOT, CHK-FW-LOG-ENGINE-CSR-STATE,
CHK-FW-LOG-ENGINE-SPM-PATTERN, CHK-FW-LOG-ENGINE-FETCH-DECERR.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=uart_log_engine_fetch_err.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_addr_map import smc_addr
from seq_lib.smc_fw_log_engine_test_seq import (
    LogEngineFinalState,
    smc_fw_log_engine_test_seq,
    uart_reg,
)
from smc_base_test import smc_base_test

GOOD_REGION_SIZE = 0x100
GOOD_XFER_LEN = 16
# UNMAPPED_ADDR in the image: the first 4 KB-aligned address past the WDT cluster.
_WDT_END = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR") + smc_addr(
    "SMC_TOP_SMC_CLUSTER_CORE3_WDT_SIZE"
)
UNMAPPED_ADDR = (_WDT_END + 0xFFF) & ~0xFFF
assert UNMAPPED_ADDR + 0x1000 <= smc_addr("SMC_TOP_SMC_RESET_UNIT_BASE_ADDR"), (
    "the image's unmapped fetch window no longer fits before the reset unit"
)


@pyuvm.test()
class smc_fw_uart_log_engine_fetch_err_test(smc_base_test):
    """Firmware latches LOG_FETCH_ERR; the bench confirms the address really DECERRs."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-LOG-ENGINE-CSR-STATE",
        "CHK-FW-LOG-ENGINE-FETCH-DECERR",
        "CHK-FW-LOG-ENGINE-FETCH-ERR-BOOT",
        "CHK-FW-LOG-ENGINE-SPM-PATTERN",
    )
    min_evidence = 4

    async def run_scenario(self) -> None:
        seq = smc_fw_log_engine_test_seq(
            "fw_uart_log_engine_fetch_err_seq",
            tag="LOG-ENGINE-FETCH-ERR",
            # PASS landed 1.80 ms after release in the reference run (~3600 polls at a
            # 5 ns clk_smc_i); 40_000 is ~11x that.
            poll_iterations=40_000,
            spm_pattern=bytes(0xD0 + i for i in range(GOOD_XFER_LEN)),
            engines=(
                LogEngineFinalState(0, UNMAPPED_ADDR, GOOD_REGION_SIZE, uart_reg(0, "RBR")),
                LogEngineFinalState(
                    1, UNMAPPED_ADDR, GOOD_REGION_SIZE, uart_reg(1, "RBR"), mcr_cleared=False
                ),
            ),
            decerr_probe=UNMAPPED_ADDR,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.csr_state_ok and seq.spm_pattern_ok and seq.decerr_ok, (
            f"bench observation incomplete: csr={seq.csr_state_ok} spm={seq.spm_pattern_ok} "
            f"decerr={seq.decerr_ok}"
        )
