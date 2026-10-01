# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every inbound-filter entry with full-width 56-bit windows, on live traffic.

RANDCFG. With the inbound filter active (real PROD fuse sense, sep_debug=0),
the CPU-LSU master stages a value in a pure-RW CSR (SEP_SW_DEBUG, address X)
and programs one inbound entry at a time; the external SMN master, the only
path through the inbound filter, then reads X. Only the entry under test is
enabled, and the filter blocks by default, so the response shows whether X is
inside the programmed 56-bit window:
  * inside  -> OKAY and the staged value (the read reached the CSR);
  * outside -> DECERR and not the staged value.

Value plan per entry: START takes S_B then ~S_B (both above X), END takes E
then ~E (both at or above X), and both return to reset at the end. So every
START_ADDR and END_ADDR bit of every entry takes a 0->1 and a 1->0 step, and
the upper bits [55:32] decide the response of a read whose own upper bits are
zero.

Checkers:
  CHK-WALK-READBACK  every START/END (56 bits) and FILTER_CONFIG write to the
                     entry under test, bit-leg windows included, reads back
                     as the readback model says. The setup disable of every
                     entry before the walk is not graded.
  CHK-WALK-ALLOW     windows [S, E] and [S, ~E] with S <= X <= E, ~E answer
                     OKAY with the staged value.
  CHK-WALK-EXACT     the one granule that holds X answers OKAY with the
                     staged value; the next granule answers DECERR.
  CHK-WALK-ABOVE     windows starting at S_B and ~S_B, both above X, answer
                     DECERR without the staged value.
  CHK-WALK-BELOW     a window ending below X answers DECERR without the
                     staged value.
  CHK-WALK-BIT       for every address bit k above the granule and for each
                     bound, a window where that bound's bit k alone decides
                     the response for one staged probe word (X or one of the
                     cold scratch words, chosen per bit): a compare that
                     ignores bit k of either bound flips the answer. For
                     k >= 32 the deciding bound is the one-hot 1<<k. Every
                     such window is read back (CHK-WALK-READBACK).
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected, lc_state_name
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_csr_bank_seq import INFILT_BASE
from seq_lib.sep_fabric_entry_walk_seq import (
    ADDR_MASK,
    GRANULE_BYTES,
    SepFilterEntryWalker,
    bit_legs,
    exact_window,
    granule,
)
from seq_lib.sep_inbound_filter_rule_seq import (
    INFILT_N_ENTRIES,
    RESP_DECERR,
    RESP_OKAY,
    TARGET_ADDR,
    SepInboundFilter,
    ext_read_seq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq
from seq_lib.sep_scratch_reset_seq import SCRATCH_COLD_0, SCRATCH_N, SCRATCH_STRIDE

_MAX_SENSE_CYCLES = 20_000
# Distinct non-zero disable vectors so the decoded FEAT_CTRL is non-vacuous.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
X = TARGET_ADDR
# Bit-leg probes: X and the cold scratch words, which the external master reaches
# through the inbound filter and which differ from X and each other in bits [5:3].
PROBE_ADDRS = [X] + [SCRATCH_COLD_0 + j * SCRATCH_STRIDE for j in range(SCRATCH_N)]
BIT_LEGS = list(bit_legs(PROBE_ADDRS))
if granule(X) == 0 or X > (ADDR_MASK >> 1):
    raise RuntimeError(f"target 0x{X:x} leaves no room below or above it")


class _EntryPlan:
    """Seed-derived windows for one entry (single source of truth)."""

    def __init__(self, rng: SepSeededRng, entry: int) -> None:
        self.entry = entry
        g = GRANULE_BYTES
        self.allow_start = rng.randrange(0, X + 1)
        # E and ~E must both hold X: E in [X, ADDR_MASK - X].
        self.allow_end = rng.randrange(X, ADDR_MASK - X + 1)
        # S_B and ~S_B must both sit above X's granule.
        lo = (granule(X) + 1) * g
        self.above_start = rng.randrange(lo, ADDR_MASK - lo + 1)
        self.below_end = rng.randrange(0, granule(X) * g)
        self.below_start = rng.randrange(0, self.below_end + 1)
        self.rng = rng


@pyuvm.test()
class sep_fabric_inbound_filter_window_walk_test(sep_base_test):
    """All inbound entries, START/END at full width, graded by external reads."""

    async def _bring_up_prod_filter_active(self) -> None:
        """Real-sense a PROD image -> sep_debug=0 (inbound filter active)."""
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        assert ctl.sep_debug == 0, (
            f"sep_debug must be 0 (filter active) in PROD, got {ctl.sep_debug} "
            f"(FEAT_CTRL=0x{ctl.feat_ctrl:016x})"
        )
        self.logger.info("inbound filter ACTIVE: %s sep_debug=0", lc_state_name(image.lc_raw()))

    async def _ext_read(self, addr: int) -> tuple[int, int]:
        seq = ext_read_seq(addr)
        await self.start_ext_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _expect_allow(self, chk: str, e: int, addr: int, win, staged: int) -> None:
        resp, data = await self._ext_read(addr)
        assert resp == RESP_OKAY and data == staged, (
            f"{chk} FAIL: entry {e} ext read 0x{addr:08x} with window "
            f"0x{win[0]:014x}..0x{win[1]:014x} resp={resp} data=0x{data:08x}, "
            f"want OKAY and 0x{staged:08x}"
        )

    async def _expect_deny(self, chk: str, e: int, addr: int, win, staged: int) -> None:
        resp, data = await self._ext_read(addr)
        assert resp == RESP_DECERR, (
            f"{chk} FAIL: entry {e} ext read 0x{addr:08x} with window "
            f"0x{win[0]:014x}..0x{win[1]:014x} resp={resp}, want DECERR"
        )
        assert data != staged, (
            f"{chk} FAIL: entry {e} denied read 0x{addr:08x} returned the staged "
            f"value 0x{data:08x}; the blocked access reached the CSR"
        )

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        staged = rng.getrandbits(32) | 0x1  # non-zero, so a zero read cannot match
        plans = [_EntryPlan(rng, e) for e in range(INFILT_N_ENTRIES)]
        self.logger.info("inbound walk: %d entries, X=0x%08x staged=0x%08x", len(plans), X, staged)
        await self._bring_up_prod_filter_active()
        drv = SepInboundFilter(self)
        await drv.disable_all()
        probe_vals = [staged] + [rng.getrandbits(32) | 0x1 for _ in PROBE_ADDRS[1:]]
        for addr, val in zip(PROBE_ADDRS, probe_vals):
            await drv.stage_target(addr, val)
            got = await drv.read_cpu(addr)
            assert got == val, f"staged probe 0x{addr:08x}=0x{got:08x} != 0x{val:08x}"
        filt = SepFilterEntryWalker(
            self, bank_base=INFILT_BASE, bank="INFILT", n_entries=INFILT_N_ENTRIES
        )
        counts = dict.fromkeys(("ALLOW", "EXACT", "ABOVE", "BELOW", "BIT"), 0)

        for p in plans:
            e = p.entry
            await filt.program_window(e, p.allow_start, p.allow_end)
            win = await filt.check_window(e, "allow")
            await filt.set_enabled(e, True)
            await self._expect_allow("CHK-WALK-ALLOW", e, X, win, staged)

            await filt.program_window(e, p.allow_start, ~p.allow_end & ADDR_MASK)
            win = await filt.check_window(e, "allow-inv-end")
            await self._expect_allow("CHK-WALK-ALLOW", e, X, win, staged)

            for tag, s in (("above", p.above_start), ("above-inv", ~p.above_start & ADDR_MASK)):
                assert granule(s) > granule(X)
                await filt.program_window(e, s, p.rng.randrange(s, ADDR_MASK + 1))
                win = await filt.check_window(e, tag)
                await self._expect_deny("CHK-WALK-ABOVE", e, X, win, staged)
                counts["ABOVE"] += 1

            await filt.program_window(e, p.below_start, p.below_end)
            win = await filt.check_window(e, "below")
            await self._expect_deny("CHK-WALK-BELOW", e, X, win, staged)

            await filt.program_window(e, *exact_window(X))
            win = await filt.check_window(e, "exact")
            await self._expect_allow("CHK-WALK-EXACT", e, X, win, staged)
            await self._expect_deny("CHK-WALK-EXACT", e, X + GRANULE_BYTES, win, staged)

            for k, field, bwin, bit_allow, i in BIT_LEGS:
                await filt.program_window(e, *bwin)
                bwin = await filt.check_window(e, f"bit{k}-{field}")
                chk = f"CHK-WALK-BIT k={k} {field}"
                if bit_allow:
                    await self._expect_allow(chk, e, PROBE_ADDRS[i], bwin, probe_vals[i])
                else:
                    await self._expect_deny(chk, e, PROBE_ADDRS[i], bwin, probe_vals[i])
                counts["BIT"] += 1

            await filt.restore(e)
            counts["ALLOW"] += 2
            counts["EXACT"] += 2
            counts["BELOW"] += 1
            self.logger.info(
                "entry %d: allow=0x%014x..0x%014x/~end above=0x%014x/~ below=..0x%014x",
                e,
                p.allow_start,
                p.allow_end,
                p.above_start,
                p.below_end,
            )

        n = len(plans)
        self.logger.info(
            "CHK-WALK-READBACK PASS: %d filter readbacks over %d entries match the 56-bit model",
            filt.readbacks,
            n,
        )
        self.logger.info(
            "CHK-WALK-ALLOW PASS: %d windows holding X answered OKAY with 0x%08x",
            counts["ALLOW"],
            staged,
        )
        self.logger.info(
            "CHK-WALK-EXACT PASS: %d exact-granule reads (OKAY at X, DECERR at the next granule)",
            counts["EXACT"],
        )
        self.logger.info(
            "CHK-WALK-ABOVE PASS: %d windows starting above X answered DECERR", counts["ABOVE"]
        )
        self.logger.info(
            "CHK-WALK-BELOW PASS: %d windows ending below X answered DECERR", counts["BELOW"]
        )
        self.logger.info(
            "CHK-WALK-BIT PASS: %d single-bit windows (every bit above the granule, START "
            "and END, on every entry) decided the response",
            counts["BIT"],
        )
