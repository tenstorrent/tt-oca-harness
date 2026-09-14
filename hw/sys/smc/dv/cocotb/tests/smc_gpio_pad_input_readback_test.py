# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pad input transitions are captured in the GPIO registers on several wraps.

Closes SMC-GPIO-PAD.S1 (port_table.adoc: pad2core_i, core2pad_en_o): six
bonded wraps are driven low and high from the bench pad path and
DATA_CTRL.pad2core must follow each level within a bounded number of reads;
each wrap's TX enable must raise and release only its own core2pad_en_o bit.
The RX direction enable (no pad2core_en_o vector probe) and
lsio_interface_select_o (unconnected in tb_top) are not claimed.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_gpio_pad_input_readback_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_gpio_pad_input_readback_test_seq import (
    EXPECTED_MIN_ACCESSES,
    WRAPS,
    smc_gpio_pad_input_readback_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_pad_input_readback_test(smc_base_test):
    """pad2core capture and core2pad_en direction on several GPIO wraps."""

    # The per-wrap token carries the wrap number, so the required set is built
    # from WRAPS: every wrap in it logs its own CHK-GPIO-PAD-INPUT-WRAP<n> line.
    required_evidence = tuple(
        sorted(
            (
                "CHK-GPIO-PAD-INPUT-FLOOR",
                "CHK-GPIO-PAD-INPUT-READBACK",
                *(f"CHK-GPIO-PAD-INPUT-WRAP{wrap}" for wrap in WRAPS),
            )
        )
    )
    min_evidence = len(required_evidence)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_pad_input_readback_test_seq("gpio_pad_input_readback_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.wraps_done) == len(WRAPS) and len(seq.oe_cycles) == len(WRAPS), (
            f"only {len(seq.wraps_done)} of {len(WRAPS)} wraps completed both legs"
        )
        cocotb.log.info(
            "CHK-GPIO-PAD-INPUT-FLOOR: %d wraps, %d SEP_IN accesses (floor %d), oe cycles %s",
            len(seq.wraps_done),
            seq.accesses,
            EXPECTED_MIN_ACCESSES,
            seq.oe_cycles,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.GPIO_IRQ,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_MIN_ACCESSES,
            proxy=False,
            details=(
                f"pad2core capture both ways and TX enable on wraps {list(WRAPS)}: "
                f"{seq.accesses} SEP_IN accesses"
            ),
        )
