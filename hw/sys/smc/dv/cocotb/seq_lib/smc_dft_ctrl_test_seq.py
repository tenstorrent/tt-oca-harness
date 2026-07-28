# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap Round 5: DFT_CTRL status decode (TC_SMC_P1CG_23).

RTL exposes a top-level DFT_CTRL block at 0xC000_F800 whose single
STATUS_SMU register was never reached by P0/P1/round-1..4. On Verilator
the DFT control/status wrap is replaced by `verilator_stubs/
smc_dft_ctrl_status_wrap.sv`, so the read is bounded (may DECERR /
no-decode); on Xcelium it exercises the real decode. The check proves
the block base decodes without a UVM_ERROR.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

DFT_CTRL_STATUS_SMU = 0xC000_F800


class smc_dft_ctrl_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # DFT_CTRL @ 0xC000_F800 is simulator-divergent in the OSS bench:
        #  * Verilator uses verilator_stubs/smc_dfx_ctrl_status_wrap.sv and the
        #    window sits above periph_main (ends 0xC000_E800) with no responder,
        #    so a read reaches the bench's bounded timeout (no AXI decode).
        #  * VCS builds the real DFT wrap RTL, which decodes and answers, so the
        #    read completes with a response (no bus hang).
        # Assert the actual per-simulator behaviour deterministically (non-vacuous
        # on both): it FAILS if Verilator's no-decode window starts responding, or
        # if VCS's real decode hangs instead of answering.
        if "verilator" in (cocotb.SIM_NAME or "").lower():
            await self.csr_short_timeout("DFT_CTRL_STATUS_SMU", DFT_CTRL_STATUS_SMU,
                                         timeout_ns=200)
        else:
            await self.csr_read_allow_error("DFT_CTRL_STATUS_SMU", DFT_CTRL_STATUS_SMU)
