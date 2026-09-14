# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO_CTRL window routing sweep (TC_SMC_P1CG_07).

Sweeps every bootrom ``EXTERNAL_MANDATORY_GPIO_CTRL_N`` CONTROL address. The
OSS tree carries no GPIO pad block behind that window (``memmap.adoc`` lists it
as technology-specific), so every address must answer with an AXI error
response and the all-zero word ``csr_read_decerr_zero`` expects.
"""

from __future__ import annotations

from .smc_addr_map import external_gpio_ctrl_addr, external_gpio_ctrl_indices
from .smc_csr_seq_utils import SmcCsrSeq


class smc_gpio_ctrl_full_sweep_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        idxs = external_gpio_ctrl_indices()
        addrs = [external_gpio_ctrl_addr(idx) for idx in idxs]
        # GPIO_CTRL lies inside the RDL-declared adopter extension window, so
        # the passive SEP_IN monitor treats a DECERR there as a protocol error
        # unless the sequence declares it is provoking one on purpose.
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        assert monitor is not None, "no axi_monitor on this sequence's env"
        monitor.expected_decerr_addrs.update(addrs)
        for idx, addr in zip(idxs, addrs):
            await self.csr_read_decerr_zero(f"GPIO_CTRL_{idx}", addr)
        assert self.accesses == len(idxs), f"GPIO_CTRL full sweep count mismatch: {self.accesses}"
