# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse PROGRAM/READ timeout CSR vs recovery burn."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_read_program_timeout_test_seq import (
    smc_efuse_read_program_timeout_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_read_program_timeout_test(smc_base_test):
    """timeout_enable|0 aborts; default timeout recovers OTP bit0."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_read_program_timeout_test_seq("efuse_tmo_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.prog_tmo_ok and seq.prog_rec_ok and seq.read_tmo_ok and seq.read_rec_ok, (
            f"efuse timeout incomplete prog={seq.prog_tmo_ok} "
            f"rec={seq.prog_rec_ok} rd={seq.read_tmo_ok} rdrec={seq.read_rec_ok}"
        )
