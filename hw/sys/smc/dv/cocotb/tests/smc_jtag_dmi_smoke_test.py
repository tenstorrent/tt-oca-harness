# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU JTAG DMI dmstatus smoke."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_jtag_dmi_smoke_test_seq import smc_jtag_dmi_smoke_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_jtag_dmi_smoke_test(smc_base_test):
    """DTMCS + DMI read dmstatus.version==2 after dmactive."""

    required_evidence = ("CHK-JTAG-DMI-SMOKE",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_jtag_dmi_smoke_test_seq("jtag_dmi_smoke_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dmi_ok, "U7-3 DMI smoke failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.JTAG,
            type(self).__name__,
            csr_accesses=0,
            # This scenario issues no CSR traffic at all (JTAG DMI only), so it
            # has no CSR-access floor. Its fail-capability comes from the byte
            # golden below: expected_bytes = DMI abstract-debug version 2 vs the
            # observed dmstatus[3:0]. min_csr_accesses=0 is legal only together
            # with such a golden (see smc_base_test.record_protocol_vip).
            min_csr_accesses=0,
            proxy=False,
            details=(
                f"CPU JTAG DMI: IDCODE=0x{seq.idcode:08X} "
                f"DTMCS=0x{seq.dtmcs:08X} dmstatus=0x{seq.dmstatus:08X} "
                f"(version={seq.dmstatus & 0xF})"
            ),
            expected_bytes=bytes([2]),
            observed_bytes=bytes([seq.dmstatus & 0xF]),
        )
