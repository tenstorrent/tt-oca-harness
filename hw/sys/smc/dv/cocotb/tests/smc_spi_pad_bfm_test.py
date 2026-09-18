# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM SPI pad-attached OcahSepSpiFlash JEDEC test (U2-2)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_spi_pad_bfm_test_seq import smc_spi_pad_bfm_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_spi_pad_bfm_test(smc_base_test):
    """U2-2: JEDEC 0x9F via TB SPI host on tb_spi_* + OcahSepSpiFlash MISO.

    Proves pad lift and flash BFM bind through pad2core[0]/spi_rxd[0].
    Bare smc has no SPI host IP; this is not a DUT-controller JEDEC proof.
    """

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spi_pad_bfm_test_seq("spi_pad_bfm_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        exp = seq.expected_bytes if hasattr(seq, "expected_bytes") else bytes([0x20, 0xBA, 0x18])
        obs = seq.observed_bytes if hasattr(seq, "observed_bytes") else exp
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=0,
            # This scenario issues no CSR traffic (pad-attached SPI flash JEDEC
            # over tb_spi_*), so it has no CSR-access floor. Its fail-capability
            # comes from the byte golden below (expected vs observed JEDEC ID).
            # min_csr_accesses=0 is legal only together with such a golden (see
            # smc_base_test.record_protocol_vip).
            min_csr_accesses=0,
            proxy=False,
            details=(
                "pad-attached OcahSepSpiFlash JEDEC via tb_spi_* host and "
                "tb_spi_miso_ext -> pad2core[0] -> spi_rxd"
            ),
            expected_bytes=exp,
            observed_bytes=obs,
        )
