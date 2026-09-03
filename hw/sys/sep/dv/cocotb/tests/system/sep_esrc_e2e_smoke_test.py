# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP ESRC -> DRBG -> CSRNG -> EDN -> KM entropy alive smoke (PyUVM).

Proves the real entropy datapath produces genbits that the Key Manager actually
CONSUMES, with NO force on the DRBG/EDN -- only the permitted ESRC raw-noise force
(+esrc_noise_force) that makes the ring oscillators alive under Verilator. Bring-up
follows reference suite order via the reusable sep_esrc_bringup_seq API: select internal DRBG,
configure ESRC (generators off), enable CSRNG, stage EDN commands, start the
generators, wait for a seed, then enable EDN last.

The KM only pulls from the EDN->KM stream when its own PicoRV32 requests entropy
(km_drbg_sampler asserts TREADY on a CPU DATA read or an enabled prefetch -- never
autonomously). After the TRNG reset and reinitialization sequence completes, this
test releases the KM CPU and runs a tiny KM ROM image (km_rom_entropy.parhex,
loaded via +km_rom_hex in crypto.toml) that disables the sampler read-timeout and
issues a single blocking DRBG DATA read -- making the KM genuinely consume one
genbits word (a real tvalid && tready handshake) and store it to KM SRAM word0.

This is a positive-evidence alive smoke (no vacuous pass): the force is proven to
have taken (lane-0 DUT noise_i tracks the driven bit), a seed is accumulated, the
CSRNG CTR_DRBG produces genbits, the KM consumes a word (post-mux tvalid && tready
handshake) AND lands it in KM SRAM, and CSRNG/EDN err_code + recov_alert are zero.
On top of the alive checks, the CHK1..CHK5 golden-vs-probe scoreboard
(sep_drbg_scoreboard + sep_entropy_golden) runs bit-exact and STRICT: decorrelator
SR -> BIW+SHA whitener -> 384b seed -> CTR_DRBG genbits -> EDN/KM beats, each stage
the golden input to the next, every stage compared against its DUT probe. CHK5_pool
scores mux endpoint [2] (AXIS2 == pool native EDN beats). The 0x1095 FIFO drain is
not this smoke.
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

        # Shared entropy bring-up: starts the STRICT CHK1..CHK5 scoreboard (report()
        # fails on any stage mismatch; CHK2 actual data = AXI frontdoor FIFO_RDATA),
        # drives the ESRC noise, and runs the reference suite config order through EDN-enable.
        # CHK5_pool golden: the entropy FIFO already pulls mux endpoint [2] from
        # reset, so this smoke also proves AXIS2==pool native routing. This smoke
        # does not drain the 0x1095_0000 FIFO aperture.
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
