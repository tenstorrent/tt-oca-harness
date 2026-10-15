# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO_INTF DATA_CTRL written and the pad driven both ways on all 65 instances.

Writes every software-writable DATA_CTRL field on every instance, reads each
word back against its predicted value, and drives the pad from the bench
through all four interrupt types, with the interrupt bit of that instance
alone and `DATA_CTRL.pad2core` as the observables.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_intf_data_ctrl_write_sweep_test_seq import (
    smc_gpio_intf_data_ctrl_write_sweep_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 65 GPIO_INTF instances, 18 SEP_IN AXI accesses each: the reset read, a write
# and readback for lsio_select, the active-high write with a readback at each
# pad level, a write and readback for each of active-low, rising edge, falling
# edge, the masked level and the unmasked level, and the restore write and
# readback.
GPIO_INTF_DATA_CTRL_WRITE_SWEEP_MIN_CSR_ACCESSES = 65 * 18


@pyuvm.test()
class smc_gpio_intf_data_ctrl_write_sweep_test(smc_base_test):
    """Write every DATA_CTRL field and toggle the pad on every GPIO_INTF instance."""

    required_evidence = (
        "CHK-GPIO-INTF-DATA-CTRL-WRITE-SWEEP",
        "CHK-GPIO-INTF-IRQ-TYPE-SWEEP",
        "CHK-GPIO-INTF-PAD-RECEIVER-SWEEP",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_intf_data_ctrl_write_sweep_test_seq(
            "smc_gpio_intf_data_ctrl_write_sweep_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            min_csr_accesses=GPIO_INTF_DATA_CTRL_WRITE_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_swept} GPIO_INTF DATA_CTRL instances written through every "
                f"field and driven through every interrupt type from the pad"
            ),
        )
