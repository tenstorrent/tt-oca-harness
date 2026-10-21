# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_010 ANCHOR: smc_efuse_read_program_timeout_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: d66adfdc2dbbb7005e02ef8ce713e0ee87f8ed3229bdaede8dd8e17bf012c4da
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 98 `smc_efuse_read_program_timeout_test` ENV: cocotb
"""eFuse PROGRAM/READ timeout CSR vs recovery burn, address range and slot 8/31 locks.

Reportable DUT-path claim: the ``EFUSE_PROGRAM_REQ_TIMEOUT`` /
``EFUSE_READ_REQ_TIMEOUT`` CSRs abort an outstanding request when
``timeout_enable=1, cycles=0`` and let it complete at the RDL-default cycle
count -- real ``efuse_interface_controller`` RTL.

Model-backed, NOT silicon-path coverage: the ``OTP=...`` burn observations come
from ``tb_efuse_programmed_word0``, a tap on the ``efuse_bank_model.sv``
simulation stand-in (``hw/ip/efuse/doc/architecture.adoc:163-170``). See the
sequence docstring for the full split.

After the timeout legs the sequence requests program and read at out-of-range
bit addresses and clears each address error with its W1P strobe, programs and
reads the last in-range bit, reads back a word whose bits 31:29 were burned,
and sets the LOCKS write and read locks of slots 8 and 31.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_read_program_timeout_test_seq import (
    smc_efuse_read_program_timeout_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_read_program_timeout_test(smc_base_test):
    """timeout_enable|0 aborts; default timeout recovers OTP bit0; range and lock legs."""

    required_evidence = (
        "CHK-EFUSE-GUARD-HI-READ",
        "CHK-EFUSE-GUARD-HI-WRITE",
        "CHK-EFUSE-LAST-IN-RANGE",
        "CHK-EFUSE-OOR-PROG",
        "CHK-EFUSE-OOR-READ",
        "CHK-EFUSE-RDATA-UPPER-ONES",
        "CHK-EFUSE-READ-STATUS-SET-ON-NO-ENABLE",
        "CHK-EFUSE-TMO-BASIC",
        "CHK-EFUSE-TMO-PROG",
        "CHK-EFUSE-TMO-PROG-REC",
        "CHK-EFUSE-TMO-PROG-SET",
        "CHK-EFUSE-TMO-RD",
        "CHK-EFUSE-TMO-RD-REC",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 15

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_read_program_timeout_test_seq("efuse_tmo_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Each token is emitted only after its leg's compares passed, so the
        # emitted CHK tokens are the record of which legs ran.
        required = (
            "CHK-EFUSE-TMO-PROG",
            "CHK-EFUSE-TMO-PROG-SET",
            "CHK-EFUSE-TMO-PROG-REC",
            "CHK-EFUSE-TMO-RD",
            "CHK-EFUSE-TMO-RD-REC",
            "CHK-EFUSE-READ-STATUS-SET-ON-NO-ENABLE",
            "CHK-EFUSE-TMO-BASIC",
            "CHK-EFUSE-OOR-PROG",
            "CHK-EFUSE-OOR-READ",
            "CHK-EFUSE-LAST-IN-RANGE",
            "CHK-EFUSE-RDATA-UPPER-ONES",
            "CHK-EFUSE-GUARD-HI-WRITE",
            "CHK-EFUSE-GUARD-HI-READ",
            "CHK-TIMEOUT-PATHS",
            "CHK-NONVAC",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
