# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM SPI library-loopback test (U2-3 demoted; not DUT pad path)."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_spi_loopback_test_seq import smc_spi_loopback_test_seq


@pyuvm.test()
class smc_spi_loopback_test(smc_base_test):
    """U2-3: library-only OcahSpiFlash self-test (proxy).

    Real pad-attached JEDEC + preload is ``smc_spi_pad_bfm_test`` (U2-2/U2-4).
    This test must not claim DUT SPI-pad protocol evidence.
    """

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spi_loopback_test_seq("spi_loopback_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            csr_accesses=0,
            proxy=True,
            details=(
                "LIBRARY-ONLY: ocah_spi_vip JEDEC/preload self-test + CSR probe; "
                "DUT pad path is smc_spi_pad_bfm_test"
            ),
        )
