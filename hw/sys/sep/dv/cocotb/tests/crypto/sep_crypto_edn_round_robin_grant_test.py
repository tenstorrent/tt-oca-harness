# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Crypto-EDN round-robin grant: two adapter clients held requesting at once.

``sep_crypto_edn_multisink_arbitration_test`` proves AES and KMAC complete and
that their beat time-spans overlap. It cannot create a same-cycle dual
``edn_req``: AES/KMAC masking reseeds are short pulses separated by AXI
configuration. This test holds AES (crypto_edn[0]) and OTBN URND
(crypto_edn[3]) with ``edn_req`` high *before* EDN is enabled, then brings up
the real entropy chain so ``prim_arbiter_ppc`` inside ``drbg_axis_edn_adapter``
has to grant both.

The grant monitor starts only after the ESRC seed is ready so the dual-req
window is not sampled during ``wait_seed_ready``. CHK1..CHK4 stay bit-exact
on that bring-up. Two crypto sinks are live (AES + OTBN URND), so CHK5 is
dual-sink ROUTING: each post-adapter beat equals the AXIS1 word the adapter
granted that cycle.

Probes: ``tb_top.crypto_edn_req_o`` / ``crypto_edn_ack_o`` (signed-off
observation ports).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge, ClockCycles
import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import SepAes, AES_TRIGGER, AES_TRIGGER_PRNG_RESEED
from seq_lib.sep_esrc_bringup_seq import (
    SepEntropyCfg,
    SepEsrcConfigSeq,
    SepEsrcEnableGeneratorsSeq,
    SepEsrcEnableEdnSeq,
)
from env.sep_drbg_scoreboard import SepDrbgScoreboard

_AES_BIT = 0
_URND_BIT = 3
_BOTH = (1 << _AES_BIT) | (1 << _URND_BIT)
_DUAL_REQ_CYCLES = 50_000
_GRANT_WAIT_CYCLES = 200_000


def _req() -> int:
    try:
        return int(cocotb.top.crypto_edn_req_o.value)
    except ValueError:
        return 0


def _ack() -> int:
    try:
        return int(cocotb.top.crypto_edn_ack_o.value)
    except ValueError:
        return 0


@pyuvm.test()
class sep_crypto_edn_round_robin_grant_test(sep_base_test):
    """Hold AES + OTBN URND edn_req together, then prove the arbiter grants both."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_no_cpu()

        # OTBN is released at cold reset (SW_RESET_N reset 0x7E). Without EDN it
        # parks in UrndRefresh with crypto_edn_req[3] held.
        for _ in range(_DUAL_REQ_CYCLES):
            if _req() & (1 << _URND_BIT):
                break
            await RisingEdge(dut.clk_i)
        else:
            raise AssertionError(
                f"OTBN URND edn_req never asserted (crypto_edn_req_o=0x{_req():x})"
            )

        aes = SepAes(self)
        await aes._wr(AES_TRIGGER, AES_TRIGGER_PRNG_RESEED)

        dual_seen = None
        for _ in range(_DUAL_REQ_CYCLES):
            req = _req()
            if (req & _BOTH) == _BOTH:
                dual_seen = req
                break
            await RisingEdge(dut.clk_i)
        assert dual_seen is not None, (
            "CHK-DUAL-REQ FAIL: AES and OTBN URND edn_req were never high in the "
            f"same cycle (last crypto_edn_req_o=0x{_req():x})"
        )
        self.logger.info(
            "CHK-DUAL-REQ PASS: crypto_edn_req bits 0x%x (AES bit %d + URND bit %d)",
            dual_seen, _AES_BIT, _URND_BIT,
        )

        # Same entropy bring-up as the other no_cpu consumers, split so the
        # grant monitor is not running during wait_seed_ready.
        cfg = SepEntropyCfg()
        self.entropy_cfg = cfg
        self.drbg_sb = SepDrbgScoreboard(
            dut, self.logger, strict=True,
            golden_kwargs=cfg.golden_kwargs(), chk2_backdoor=cfg.chk2_backdoor,
            score_km=False,
            score_sinks={"aes": "golden", "otbn_urnd": "golden"},
        )
        self.drbg_sb.start()
        await self.assert_noise_force_active()
        await self.start_seq(SepEsrcConfigSeq("esrc_config", cfg=cfg))
        await self.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
        if not await self.wait_seed_ready():
            await self.report_entropy_stall()
            raise AssertionError("ESRC never produced a seed (drbg_seed_valid_o)")
        self.start_fifo_drain()
        self.drbg_sb.enable_chk5()

        grants: list[int] = []
        dual_grants: list[int] = []

        async def _monitor() -> None:
            prev_ack = 0
            while True:
                await RisingEdge(dut.clk_i)
                req = _req()
                ack = _ack()
                for bit in (_AES_BIT, _URND_BIT):
                    mask = 1 << bit
                    rising = (ack & mask) and not (prev_ack & mask)
                    if rising and (req & mask):
                        grants.append(bit)
                        if (req & _BOTH) == _BOTH:
                            dual_grants.append(bit)
                prev_ack = ack

        # Both clients are still held (EDN has not been enabled). Start the
        # grant sampler, then enable EDN so the adapter has to pick.
        cocotb.start_soon(_monitor())
        await self.start_seq(SepEsrcEnableEdnSeq("esrc_enable_edn"))

        for _ in range(_GRANT_WAIT_CYCLES):
            if (
                _AES_BIT in grants
                and _URND_BIT in grants
                and any(a != b for a, b in zip(grants, grants[1:]))
            ):
                break
            await ClockCycles(dut.clk_i, 20)
        else:
            raise AssertionError(
                "crypto-EDN grants did not alternate "
                f"(grants={grants[:16]} dual_grants={dual_grants[:16]})"
            )

        assert _AES_BIT in grants and _URND_BIT in grants, (
            "CHK-NO-STARVE FAIL: a requesting client got no edn_ack "
            f"(grants={grants})"
        )
        self.logger.info(
            "CHK-NO-STARVE PASS: both clients acked (AES grants=%d URND grants=%d)",
            grants.count(_AES_BIT), grants.count(_URND_BIT),
        )

        # AES masking reseeds pulse edn_req per beat, so a same-cycle dual-req
        # sample at ack often sees only AES. Consecutive post-adapter grants
        # still alternate 0,3,0,3 -- that is the round-robin decision.
        assert any(a != b for a, b in zip(grants, grants[1:])), (
            "CHK-GRANT-ALT FAIL: consecutive grants did not go to different "
            f"clients (grants={grants} dual_grants={dual_grants})"
        )
        self.logger.info(
            "CHK-GRANT-ALT PASS: consecutive grants alternate (grants=%s dual_grants=%s)",
            grants[:12], dual_grants[:12],
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        ra = self.drbg_sb.results["CHK5_aes"]
        ru = self.drbg_sb.results["CHK5_otbn_urnd"]
        assert ra.mismatches == 0 and ru.mismatches == 0
        self.logger.info(
            "CHK-ROUTING PASS: CHK5_aes match=%d and CHK5_otbn_urnd match=%d "
            "equal the AXIS1 grant-order stream (mismatch=0)",
            ra.matches, ru.matches)
        self.logger.info(
            "CHK1..CHK4 bit-exact + CHK5_aes/CHK5_otbn_urnd ROUTING PASS")
