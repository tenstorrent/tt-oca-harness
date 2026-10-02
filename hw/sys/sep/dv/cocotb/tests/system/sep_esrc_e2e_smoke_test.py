# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ESRC -> DRBG -> CSRNG -> EDN -> KM entropy alive smoke (PyUVM).

Proves the real entropy datapath produces genbits that the Key Manager consumes, with
no force on the DRBG/EDN; only the ESRC raw-noise force (+esrc_noise_force) that makes
the ring oscillators run under Verilator. Bring-up order, via sep_esrc_bringup_seq:
select internal DRBG, configure ESRC with generators off, enable CSRNG, stage EDN
commands, start the generators, wait for a seed, enable EDN.

The KM pulls entropy only on a PicoRV32 DRBG DATA read or an enabled prefetch, so
after TRNG reinitialization the test releases the KM CPU running km_rom_entropy.parhex
(+km_rom_hex in crypto.toml), which disables the sampler read-timeout, does one
blocking DRBG DATA read and stores the word to KM SRAM word0.

Checks: the force takes (lane-0 noise_i tracks the driven bit), genbits are produced,
the KM handshakes and stores one word, CSRNG/EDN err_code and recov_alert stay zero,
and the strict CHK1..CHK5 scoreboard (sep_drbg_scoreboard + sep_entropy_golden)
matches every stage bit-exact, including CHK5_pool on mux endpoint [2]. The EPOOL
aperture (0x1095_0000) is not drained.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq


@pyuvm.test()
class sep_esrc_e2e_smoke_test(sep_base_test):
    """Bring up the real entropy stack and prove genbits reach + are consumed by the KM."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # Starts the strict CHK1..CHK5 scoreboard (CHK2 data from AXI FIFO_RDATA),
        # drives the ESRC noise and configures through EDN-enable. The entropy FIFO
        # pulls mux endpoint [2] from reset, so CHK5_pool also proves AXIS2 routing.
        await self.bring_up_entropy(strict=True, score_sinks={"pool": "golden"})

        # Release the KM only after the initial TRNG reset/reinitialization. Its
        # blocking DRBG DATA read then consumes one word from the live stream.
        await self.start_seq(sep_km_release_seq("km_release"))

        # Concurrent FIFO_RDATA drain so the FIFO never overflows during the long
        # genbits/KM phase (forked after the last bring-up write so it owns the AXI
        # sequencer during the signal-probe waits).
        self.start_fifo_drain()

        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.logger.info("CSRNG genbits produced")

        assert await self.wait_km_entropy_handshake(), (
            "KM never consumed an entropy word (km_entropy tvalid && tready)"
        )
        self.logger.info("KM consumed a genbits word (post-mux handshake)")

        assert await self.wait_km_consumed_word(), (
            "KM consumed a word but never stored it to SRAM (CPU wedged?)"
        )
        self.logger.info("KM landed the consumed entropy word in SRAM word0")

        await self.check_entropy_alerts_zero()
        self.logger.info("ESRC->DRBG->CSRNG->EDN->KM alive; KM consumed entropy; alerts clean")

        await self.stop_fifo_drain()
        assert self.drbg_sb.report()
