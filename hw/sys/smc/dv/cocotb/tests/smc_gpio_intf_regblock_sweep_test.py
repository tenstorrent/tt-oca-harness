# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_012 ANCHOR: smc_gpio_intf_regblock_sweep_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: c065f43a6879651743934132e450ef015bf65d7ce0042c64a4b56be05b32063e
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 198 `smc_gpio_intf_regblock_sweep_test` ENV: cocotb
"""GPIO_INTF DATA_CTRL_ENABLE and ACCESS_FILTER cycle on all 65 instances.

Drives both registers to all-ones and all-zeros through half-register writes,
reads each one back against its generated RDL contract, and restores the RDL
reset. The armed ACCESS_FILTER state carries an AxPROT allow leg, an AxPROT
deny leg and a refused AWPROT=7 write on every instance.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_intf_regblock_sweep_test_seq import smc_gpio_intf_regblock_sweep_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 65 GPIO_INTF instances, 26 SEP_IN AXI accesses each:
#   DATA_CTRL_ENABLE cycle: reset read, 2x(half write + readback) for the ones
#     pattern, the same for the zeros pattern, 2 restore writes, restore read 12
#   ACCESS_FILTER cycle: reset read, and a write plus a readback for each of
#     the arprot-ones, armed, arprot-zeros, awprot-ones and restore steps,
#     plus the refused read of the armed state, and the refused AWPROT=7
#     write of the armed state with its readback                             14
GPIO_INTF_REGBLOCK_SWEEP_MIN_CSR_ACCESSES = 65 * 26


@pyuvm.test()
class smc_gpio_intf_regblock_sweep_test(smc_base_test):
    """Cycle GPIO_INTF DATA_CTRL_ENABLE and ACCESS_FILTER on every instance."""

    required_evidence = (
        "CHK-GPIO-INTF-ACCESS-FILTER-DENY",
        "CHK-GPIO-INTF-ACCESS-FILTER-SWEEP",
        "CHK-GPIO-INTF-ACCESS-FILTER-WRITE-DENY",
        "CHK-GPIO-INTF-DATA-CTRL-ENABLE-SWEEP",
        "CHK-NONVAC",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_intf_regblock_sweep_test_seq("smc_gpio_intf_regblock_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            min_csr_accesses=GPIO_INTF_REGBLOCK_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_swept} GPIO_INTF register instances cycled against the "
                f"generated RDL map, {seq.denials} AxPROT read refusals, "
                f"{seq.write_denials} AWPROT write refusals"
            ),
        )
