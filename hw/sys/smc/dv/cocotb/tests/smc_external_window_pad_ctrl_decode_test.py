# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""External-window control apertures decode into the adopter port.

Closes SMC-GPIO-EXTCTRL.S3, SMC-GPIO-EXTCTRL.S4, SMC-GPIO-EXTCTRL.S5 and
SMC-EXTWIN-MAND.S2 (memmap.adoc: AXI-Lite External Window): the supplementary
region's control blocks and the first, second and last of the 65 per-pad
control blocks are read at their generated-map addresses; each access
must drive the adopter external AXI-Lite port while in flight and complete
with a decode error carrying the error-slave word 0xBADCAB1E, the terminator's
answer for an address nothing behind the window decodes.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_external_window_pad_ctrl_decode_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_external_window_pad_ctrl_decode_test_seq import (
    EXPECTED_ACCESSES,
    smc_external_window_pad_ctrl_decode_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_external_window_pad_ctrl_decode_test(smc_base_test):
    """External-window control and per-pad block decode at the adopter port."""

    required_evidence = (
        "CHK-EXTERNAL-WINDOW-PAD-CTRL-DECODE",
        "CHK-EXTWIN-PAD-CTRL",
        "CHK-EXTWIN-PAD-CTRL-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_external_window_pad_ctrl_decode_test_seq("external_window_pad_ctrl_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.hits) == EXPECTED_ACCESSES and all(h > 0 for h in seq.hits.values()), (
            f"external-port activity was recorded for {len(seq.hits)} of {EXPECTED_ACCESSES} probes"
        )
        cocotb.log.info(
            "CHK-EXTWIN-PAD-CTRL-FLOOR: %d probes, external port active cycles %s",
            len(seq.hits),
            seq.hits,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_ACCESSES,
            proxy=False,
            details=(
                f"external-window control apertures over SEP_IN AXI: {seq.accesses} accesses, "
                f"{len(seq.cells)} cells closed at the adopter external port"
            ),
        )
