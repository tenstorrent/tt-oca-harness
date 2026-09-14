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

Probes: ``tb_top.crypto_edn_req_o`` / ``crypto_edn_ack_o`` (observation
ports).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_drbg_scoreboard import SepDrbgScoreboard
from sep_base_test import sep_base_test
from seq_lib.sep_aes_seq import AES_TRIGGER, AES_TRIGGER_PRNG_RESEED, SepAes
from seq_lib.sep_esrc_bringup_seq import (
    SepEntropyCfg,
    SepEsrcConfigSeq,
    SepEsrcEnableEdnSeq,
    SepEsrcEnableGeneratorsSeq,
)

_AES_BIT = 0
_URND_BIT = 3
_BOTH = (1 << _AES_BIT) | (1 << _URND_BIT)
_DUAL_REQ_CYCLES = 50_000
# Enough consecutive grants to see the arbiter alternate, and the floor below
# which the sample says nothing. Literals, so the asserts do not move with the
# collection loop.
_GRANT_SAMPLE_TARGET = 16
_GRANT_MIN_SAMPLES = 4
_GRANT_POLLS = 200_000
_GRANT_POLL_CYCLES = 20


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

        # OTBN is released at cold reset (SW_RESET_N reset 0x3E). Without EDN it
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
            dual_seen,
            _AES_BIT,
            _URND_BIT,
        )

        # Same entropy bring-up as the other no_cpu consumers, split so the
        # grant monitor is not running during wait_seed_ready.
        cfg = SepEntropyCfg()
        self.entropy_cfg = cfg
        self.drbg_sb = SepDrbgScoreboard(
            dut,
            self.logger,
            strict=True,
            golden_kwargs=cfg.golden_kwargs(),
            chk2_backdoor=cfg.chk2_backdoor,
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

        # Collect grants for a fixed budget and let the asserts below decide.
        # Breaking out on the same condition the asserts test would make them
        # restatements of the loop guard, unable to fail at their own sites.
        for _ in range(_GRANT_POLLS):
            if len(grants) >= _GRANT_SAMPLE_TARGET:
                break
            await ClockCycles(dut.clk_i, _GRANT_POLL_CYCLES)
        assert len(grants) >= _GRANT_MIN_SAMPLES, (
            f"CHK-NO-STARVE FAIL: only {len(grants)} post-adapter grants observed in "
            f"{_GRANT_POLLS} polls of {_GRANT_POLL_CYCLES} cycles, need "
            f"{_GRANT_MIN_SAMPLES} to judge sharing "
            f"(grants={grants[:16]} dual_grants={dual_grants[:16]})"
        )

        assert _AES_BIT in grants and _URND_BIT in grants, (
            f"CHK-NO-STARVE FAIL: a requesting client got no edn_ack (grants={grants})"
        )
        self.logger.info(
            "CHK-NO-STARVE PASS: both clients acked (AES grants=%d URND grants=%d)",
            grants.count(_AES_BIT),
            grants.count(_URND_BIT),
        )

        # Round-robin while both clients are in the fight: the grant stream
        # must strictly alternate until the first same-client pair. A repeat
        # after both clients have already been served is the legal tail (one
        # client dropped req). `any(a != b)` would be a tautology once
        # CHK-NO-STARVE has both values in the list.
        pairs = list(zip(grants, grants[1:]))
        alt_pairs = 0
        for a, b in pairs:
            if a == b:
                break
            alt_pairs += 1
        min_alt = _GRANT_MIN_SAMPLES - 1
        assert alt_pairs >= min_alt, (
            "CHK-GRANT-ALT FAIL: alternating prefix too short "
            f"(alt_pairs={alt_pairs} need>={min_alt} grants={grants} "
            f"dual_grants={dual_grants})"
        )
        prefix = grants[: alt_pairs + 1]
        assert _AES_BIT in prefix and _URND_BIT in prefix, (
            "CHK-GRANT-ALT FAIL: alternating prefix did not grant both "
            f"clients (prefix={prefix} grants={grants})"
        )
        self.logger.info(
            "CHK-GRANT-ALT PASS: %d consecutive pairs alternate and both "
            "clients appear before any same-client repeat (grants=%s "
            "dual_grants=%s)",
            alt_pairs,
            grants[:16],
            dual_grants[:12],
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        # The grant sample above establishes how much traffic each client
        # actually took, so the routing floors are held to that rather than to
        # the scoreboard's default of one beat.
        self.drbg_sb.set_min_matches(CHK5_aes=_GRANT_MIN_SAMPLES, CHK5_otbn_urnd=_GRANT_MIN_SAMPLES)
        assert self.drbg_sb.report()
        ra = self.drbg_sb.results["CHK5_aes"]
        ru = self.drbg_sb.results["CHK5_otbn_urnd"]
        self.logger.info(
            "CHK-ROUTING PASS: CHK5_aes match=%d and CHK5_otbn_urnd match=%d "
            "equal the AXIS1 grant-order stream (mismatch=0)",
            ra.matches,
            ru.matches,
        )
        self.logger.info("CHK1..CHK4 bit-exact + CHK5_aes/CHK5_otbn_urnd ROUTING PASS")
