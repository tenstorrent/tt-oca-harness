# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO_CTRL window routing sweep.

Sweeps every bootrom ``EXTERNAL_MANDATORY_GPIO_CTRL_N`` CONTROL address. The
OSS tree carries no GPIO pad block behind that window (``memmap.adoc`` lists it
as technology-specific), so every address must answer with an AXI error
response and the error-slave word ``csr_read_err_signature`` expects.
"""

from __future__ import annotations

import cocotb

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
            await self.csr_read_err_signature(f"GPIO_CTRL_{idx}", addr)
        self.assert_all_reachable(len(idxs), "GPIO_CTRL_FULL_SWEEP")
        cocotb.log.info(
            "CHK-GPIO-CTRL-WINDOW-ERROR-SWEEP: %d GPIO_CTRL window reads "
            "(GPIO_CTRL_%d @ 0x%08x .. GPIO_CTRL_%d @ 0x%08x) each answered with an AXI "
            "error response and the error-slave word 0x%08X; %d SEP_IN accesses checked by "
            "the scoreboard",
            len(idxs),
            idxs[0],
            addrs[0],
            idxs[-1],
            addrs[-1],
            self.ERR_SLAVE_SIGNATURE,
            self.accesses,
        )
