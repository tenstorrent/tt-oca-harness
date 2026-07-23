# SPDX-License-Identifier: Apache-2.0
"""P1 coverage-gap round 3: full GPIO_INTF sweep.

RTL exposes 68 GPIO_INTF entries (0xC000_4000 stride 0x10). Existing
P0/P1 tests only touch entries 0-2. This test sweeps all 68 with a
read each to prove every GPIO interface's decode is alive.
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

_GPIO_INTF_BASE = 0xC000_4000
_GPIO_INTF_STRIDE = 0x10
_GPIO_INTF_COUNT = 68

# Per-interface DATA_CTRL reset content, identical on Verilator and VCS. The
# all-zero interfaces match the gpio_intf.rdl reset (every field, incl.
# lsio_enable[25], resets 0x0) -> G3 spec-anchored. The bit25=1 subset is a
# REGRESSION-LOCK: bit25 is `lsio_enable` (sw=r/hw=w), whose RDL reset is 0x0;
# those interfaces read 1 because their `lsio_enable` HW input is tied high
# (physically routed to the LSIO block). That locks the per-instance HW tie,
# not a spec reset constant. [audit: F1 common-mode, see smcoss_audit.md]
_GPIO_INTF_DEFAULT_BIT25 = 0x0200_0000
_GPIO_INTF_BIT25_INDICES = frozenset(
    {27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 49, 50, 51, 53, 60, 65, 66, 67}
)


class smc_gpio_intf_full_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        for idx in range(_GPIO_INTF_COUNT):
            addr = _GPIO_INTF_BASE + idx * _GPIO_INTF_STRIDE
            expected = (
                _GPIO_INTF_DEFAULT_BIT25 if idx in _GPIO_INTF_BIT25_INDICES else 0x0
            )
            await self.csr_read(f"GPIO_INTF_{idx}", addr, expected=expected)
        assert self.accesses == _GPIO_INTF_COUNT, "GPIO_INTF full sweep count mismatch"
