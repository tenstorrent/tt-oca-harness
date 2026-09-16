# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO wrap-0 register vs LSIO mux."""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_gpio_p0_mux_test_seq import smc_gpio_p0_mux_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_p0_mux_test(smc_base_test):
    """GPIO0 interface_enable vs a live lsio_select competitor."""

    required_evidence = (
        "CHK-GPIO-P0-MUX-LSIO",
        "CHK-GPIO-P0-MUX-PATTERN",
        "CHK-GPIO-P0-MUX-PRIO",
        "CHK-GPIO-P0-MUX-REG",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_p0_mux_test_seq("gpio_p0_mux_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)

        # Three-way relation over the MEASURED `core2pad_en_o` samples the
        # sequence retained, checked here as one statement rather than three
        # booleans: the wrap-0 enable must be off at entry, on under the register
        # path, still on when lsio_select competes with it, and on again under
        # lsio_select alone -- the last being the leg a select bit tied to 0
        # would fail. The individual samples are asserted in the sequence; what
        # this adds is that all four came from the same run and hold together.
        bit = 1 << 0
        pattern = tuple((v & bit) != 0 for v in (seq.en_base, seq.en_reg, seq.en_both, seq.en_lsio))
        assert pattern == (False, True, True, True), (
            f"gpio p0 mux enable pattern base/reg/both/lsio = {pattern}, "
            f"expected (False, True, True, True) "
            f"(raw 0x{seq.en_base:x} 0x{seq.en_reg:x} 0x{seq.en_both:x} "
            f"0x{seq.en_lsio:x})"
        )
        assert (seq.val_lsio, seq.val_lsio_flipped) == (0, 1), (
            f"wrap0 core2pad did not follow the LSIO source: observed "
            f"{seq.val_lsio} then {seq.val_lsio_flipped}, expected 0 then 1"
        )
        cocotb.log.info(
            "CHK-GPIO-P0-MUX-PATTERN: core2pad_en[0] base=%d reg=%d both=%d "
            "lsio=%d; core2pad[0] tracked the LSIO source %d -> %d",
            *(int(p) for p in pattern),
            seq.val_lsio,
            seq.val_lsio_flipped,
        )
