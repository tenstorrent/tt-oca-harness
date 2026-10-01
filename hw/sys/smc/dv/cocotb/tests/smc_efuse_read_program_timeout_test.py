# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse PROGRAM/READ timeout CSR vs recovery burn.

Reportable DUT-path claim: the ``EFUSE_PROGRAM_REQ_TIMEOUT`` /
``EFUSE_READ_REQ_TIMEOUT`` CSRs abort an outstanding request when
``timeout_enable=1, cycles=0`` and let it complete at the RDL-default cycle
count -- real ``efuse_interface_controller`` RTL.

Model-backed, NOT silicon-path coverage: the ``OTP=...`` burn observations come
from ``tb_efuse_programmed_word0``, a tap on the ``efuse_bank_model.sv``
simulation stand-in (``hw/ip/efuse/doc/architecture.adoc:163-170``). See the
sequence docstring for the full split.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_read_program_timeout_test_seq import (
    smc_efuse_read_program_timeout_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_read_program_timeout_test(smc_base_test):
    """timeout_enable|0 aborts; default timeout recovers OTP bit0."""

    required_evidence = (
        "CHK-EFUSE-READ-STATUS-SET-ON-NO-ENABLE",
        "CHK-EFUSE-TMO-BASIC",
        "CHK-EFUSE-TMO-PROG",
        "CHK-EFUSE-TMO-PROG-REC",
        "CHK-EFUSE-TMO-PROG-SET",
        "CHK-EFUSE-TMO-RD",
        "CHK-EFUSE-TMO-RD-REC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_read_program_timeout_test_seq("efuse_tmo_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted CHK token names, not on relayed booleans: the four
        # `*_ok` flags are literal `True` assignments on lines unreachable
        # unless the real compares already passed, so asserting on them
        # carries no fail capability of its own ([NO-DUMMY-DEAD-CODE]).
        required = (
            "CHK-EFUSE-TMO-PROG",
            "CHK-EFUSE-TMO-PROG-SET",
            "CHK-EFUSE-TMO-PROG-REC",
            "CHK-EFUSE-TMO-RD",
            "CHK-EFUSE-TMO-RD-REC",
            "CHK-EFUSE-READ-STATUS-SET-ON-NO-ENABLE",
            "CHK-EFUSE-TMO-BASIC",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
