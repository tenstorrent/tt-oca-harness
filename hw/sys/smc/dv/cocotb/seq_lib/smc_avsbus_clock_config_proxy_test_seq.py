# SPDX-License-Identifier: Apache-2.0
"""AVSBus clock/config proxy test."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = 0xC001_0018  # base_config offset 0x18 (was 0x30 before HANG_DET_* added)
AVS_CG_EN = 1 << 10
AVSBUS_TIMEOUT_READS = [
    ("AVS_CFG_0", 0xC000_8050),
    ("AVS_CFG_1", 0xC000_8054),
    ("AVS_CONFIG", 0xC000_8058),
]


class smc_avsbus_clock_config_proxy_test_seq(SmcCsrSeq):
    """Toggle AVS clock gate and probe config decode with allowed errors."""

    def __init__(self, name: str = "smc_avsbus_clock_config_proxy_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        original = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        enabled = original | AVS_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_AVS_EN", CLOCK_GATE_CONTROL, enabled)
        await self.csr_read("CLOCK_GATE_CONTROL_AVS_EN", CLOCK_GATE_CONTROL, expected=enabled)
        for name, addr in AVSBUS_TIMEOUT_READS:
            await self.csr_short_timeout(name, addr)
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, expected=original)
        assert self.accesses == 8 and self.timeouts == 3, "AVSBus clock/config proxy mismatch"
