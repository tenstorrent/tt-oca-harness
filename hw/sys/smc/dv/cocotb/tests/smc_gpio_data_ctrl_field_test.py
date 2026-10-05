# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One GPIO DATA_CTRL, one field at a time, on a pad nothing else uses.

Drives each of the seven software-writable DATA_CTRL fields of GPIO instance
60 on its own -- set, read back, put straight back to its reset, read back --
with nothing held between fields. The integrator pad table reserves index 60
and the testbench never drives it; the pad's output enable is sampled after
every write and must stay at zero.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_data_ctrl_field_test_seq import smc_gpio_data_ctrl_field_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   the idle read against the RDL reset                                       1
#   7 fields x (set, read back, restore, read back)                          28
GPIO_DATA_CTRL_FIELD_MIN_CSR_ACCESSES = 1 + 7 * 4


@pyuvm.test()
class smc_gpio_data_ctrl_field_test(smc_base_test):
    """Drive each DATA_CTRL field of one idle GPIO instance on its own."""

    required_evidence = ("CHK-GPIO-DATA-CTRL-FIELDS",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_data_ctrl_field_test_seq("smc_gpio_data_ctrl_field_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            min_csr_accesses=GPIO_DATA_CTRL_FIELD_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{seq.fields_driven} DATA_CTRL fields driven one at a time",
        )
