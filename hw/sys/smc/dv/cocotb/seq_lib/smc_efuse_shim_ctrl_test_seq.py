# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap: EFUSE_INTERFACE_CTRL + EFUSE_SHIM_CTRL (TC_SMC_P1CG_05).

Existing eFuse tests touch chip_config + permission boundary but the
Samsung eFuse shim interface control registers (0xC000_C000 /
0xC000_C100) are otherwise unreached.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

EFUSE_INTERFACE_CTRL = 0xC000_C000  # real internal SMC register (responds OKAY here)
EFUSE_SHIM_CTRL      = 0xC000_C100  # Samsung vendor shim (absent in DUT-only OSS bench)


class smc_efuse_shim_ctrl_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # EFUSE_INTERFACE_CTRL is a real internal SMC register: it MUST return an
        # OKAY response. Gate the test on it via csr_read (scoreboard asserts
        # item.resp_ok), so a broken decode / SLVERR / bus hang here fails the test.
        await self.csr_read("EFUSE_INTERFACE_CTRL", EFUSE_INTERFACE_CTRL)
        # EFUSE_SHIM_CTRL is the Samsung vendor shim, which has no AXI responder
        # in the DUT-only OSS bench (bounded read times out by design). Probe it
        # for decode coverage on the full chip, but it does NOT gate the OSS pass.
        await self.csr_read_bounded("EFUSE_SHIM_CTRL", EFUSE_SHIM_CTRL)
        if self.timeouts:
            cocotb.log.info(
                "EFUSE_SHIM_CTRL (Samsung vendor shim) not present in DUT-only "
                "OSS bench (%d/1 shim window bounded-timed-out); decode deferred "
                "to full-chip. INTERFACE_CTRL OKAY gate above is the real check.",
                self.timeouts,
            )
