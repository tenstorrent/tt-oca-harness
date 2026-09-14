# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS system timer preset sweep, driven from the CPU, with the timer left running.

Firmware test: `fw/tests/octs_p0_primary_test` is loaded into scratch by the
firmware loader. It probes OCTS CTRL writability against a value that differs
from the reset default in every field, programs CTRL and TIMER_GPIO_ENABLE,
writes and reads back PRESET including a 64-bit value only a live HI half can
return, starts the timer and requires COUNT to grow across three reads. The
cocotb OCTS leaves drive these registers from SEP_IN; this one drives them
from the hart that owns them in the product.

Bench observation: the image parks with the timer running, so after the PASS
word the sequence reads STATUS.RUNNING and TIMER_GPIO_ENABLE, reads
TIMER_COUNT_LO twice and requires it to have advanced, and counts rising edges
on pad 56 (tb_octs_cnt_credit_from_dut), which a PRIMARY-mode timer pulses --
the observation smc_octs_dual_sync_test uses for PRIMARY outbound.

Tokens: CHK-FW-OCTS-PRIMARY-BOOT, CHK-FW-OCTS-COUNT-ADVANCES, CHK-FW-OCTS-CREDIT-PAD.

Requires the staged image and a held boot:
  +smc_scratch_ram_hex=octs_p0_primary_test.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
Must NOT use +skip_fuse_sense -- see dv_policy 1.6.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_fw_octs_p0_primary_test_seq import smc_fw_octs_p0_primary_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_fw_octs_p0_primary_test(smc_base_test):
    """Firmware sweeps OCTS presets; the bench sees the timer count and pulse."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-OCTS-COUNT-ADVANCES",
        "CHK-FW-OCTS-CREDIT-PAD",
        "CHK-FW-OCTS-PRIMARY-BOOT",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        seq = smc_fw_octs_p0_primary_test_seq("fw_octs_p0_primary_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.timer_ok, (
            f"timer observation incomplete: count_advance={seq.count_advance} "
            f"credit_edges={seq.credit_edges}"
        )
