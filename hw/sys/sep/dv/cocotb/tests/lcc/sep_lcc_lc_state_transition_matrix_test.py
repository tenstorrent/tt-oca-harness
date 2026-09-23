# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""LC_STATE next state on the shadow write-1-to-set path (OSS).

No testlist entry carries this module's name. Six entries in
``testlists/efuse_lcc.toml`` run it, each selecting a start state with
``+lc_start=N``: sep_lcc_lc_state_w1s_prod_test (1),
sep_lcc_lc_state_w1s_prod_demote_test, sep_lcc_lc_state_w1s_rma_sip_test,
sep_lcc_lc_state_w1s_rma_chiplet_test, sep_lcc_lc_state_w1s_prod_end_test and
sep_lcc_lc_state_w1s_transient_test. Run one of those names, not this one.

The lifecycle stitch walk covers the OTP-program path: burn a fuse bit, re-sense,
check the decode. This test covers the OTHER writer of LC_STATE -- the frontdoor
shadow write, whose setup phase computes the next lifecycle state in
``hw/ip/efuse/rtl/efuse_shadow_regs.sv``. Nothing else in this tree drives that
path, so nothing else can fail on a wrong next state.

The contract, from ``hw/sys/sep/doc/lifecycle_controller.adoc``, is three rules
and no destination table:

  * write-1-to-set: a lifecycle bit only goes 0 -> 1, never 1 -> 0;
  * bit 0 is a DON'T CARE inside RMA_SIP (``4'b001X``) and RMA_CHIPLET
    (``4'b011X``), and bit 3 is ungated, so setting either is not a transition
    the lifecycle constrains;
  * the RMA ordering is hardware-enforced: bit 1 needs an RMA_SIP token match,
    and bit 2 needs an RMA_CHIPLET token match AND RMA_SIP already established.

What the chapter says about destinations follows from those three: INVALID is
end-of-life and terminal, and from PROD_END every reachable set lands outside
the named encodings -- the chapter's "the only permitted transition is to
INVALID". Demotion is NOT a term: the chapter calls it volatile debug state,
distinct from RMA "whose state transitions are hardware-ordered", so a demoted
part must transition exactly like a non-demoted one.

ONE SENSED STARTING STATE PER LEAF. ``efuse_bank_model`` deposits the OTP image
in a time-0 ``initial`` and a fuse survives reset, so a test cannot re-sense its
way to a different starting state -- only a superset is reachable, by programming
bits for real. Each starting state is therefore its own leaf, staged at t=0 by
``dv_sim_prestage.py`` and selected by ``+lc_start`` (with ``+lc_demote`` /
``+lc_transient_rma`` for the two variant leaves). Real fuse sense throughout;
no backdoor deposit anywhere on the lifecycle path.

Both halves of every cell are value-checked: the LC_STATE shadow word (the
differential ``{~raw, raw}``) and the LCC FEAT_CTRL decode of that same state.
FEAT_CTRL is what proves the write reached the lifecycle controller rather than
only the shadow storage -- and for a state outside the named set it must read 0
("all features disabled by fail-closed default"), which no in-spec state
produces under these disable vectors.

Checkers, by leaf (``+lc_start`` value):

  1 (PROD)
    * CHK-W1S-NO-CLEAR   a write of 0 clears nothing.
    * CHK-GATE-SIP       bit 1 without an RMA_SIP token match does not set.
    * CHK-GATE-CHIP-ORD  bit 2 with a CHIPLET match but no RMA_SIP does not set
                         -- the ordering gate, with the token gate already open.
    * CHK-SIP-ADVANCE    bit 1 with a match advances PROD -> RMA_SIP.
  1 + demote
    * CHK-DEMOTE-OPEN      DEMOTE_1+DEMOTE_2 in PROD is observable in FEAT_CTRL,
                           so the cell below cannot pass vacuously.
    * CHK-DEMOTE-NO-BLOCK  the same PROD -> RMA_SIP advance succeeds demoted.
  2 (RMA_SIP_0)
    * CHK-RMA-BIT0       bit 0 sets inside RMA_SIP (0x2 -> 0x3).
    * CHK-GATE-CHIP-TOK  bit 2 from RMA_SIP without a CHIPLET match does not set.
    * CHK-CHIP-ADVANCE   bit 2 with a match reaches RMA_CHIPLET.
    * CHK-INVALID-REACH  a write whose result is outside the named set lands
                         there, and FEAT_CTRL fails closed to 0.
    * CHK-INVALID-TERM   from there, a write of every bit with BOTH tokens
                         matched changes nothing.
  6 (RMA_CHIP_0)
    * CHK-RMA-BIT0       bit 0 sets inside RMA_CHIPLET (0x6 -> 0x7).
  8 (PROD_END)
    * CHK-PROD-END-INVALID  PROD_END's reachable destination is INVALID.
  8 + transient RMA
    * CHK-TRANSIENT-INVALID  the transient path applies the same W1S and token
                             rules with no bus request, INVALID result included.

Every leaf with a bus-write cell also runs CHK-UPPER-WRITE: two seed-derived
[31:8] patterns with a unique bit each. LC_STATE[31:8] is sep_efuse_map.rdl's
``rsvd`` field and takes a plain shadow write, so the second pattern replaces
the first; a stale OR of the two fails. The set-only rule covers the lifecycle
nibble alone (CHK-W1S-NO-CLEAR), not these bytes.

RANDCFG: the tokens and the byte [31:8] pattern come from the run seed
(``SepLcTransitionCfg``); the cells within a leaf are fixed, so no contract is
seed-selected.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_efuse_image import LC_WORD_IDX, lc_encode
from env.sep_lc_transition import SIP_DIS, SYS_DIS, SepLcTransitionCfg
from env.sep_lcc_golden import (
    LC_PROD,
    LC_PROD_END,
    LC_RMA_CHIP_0,
    LC_RMA_SIP_0,
    feat_ctrl_expected,
    is_invalid_lc,
    is_valid_lc_transition,
    lc_state_name,
    lc_state_next,
)
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_CMP_INJECT_COLLAPSE,
    TOKEN_CMP_INJECT_OFF,
    TOKEN_CMP_SEL_SIP,
    TOKEN_ERROR,
    TOKEN_RMA_CHIPLET,
    TOKEN_RMA_SIP,
    SepRmaTokenMatchSeq,
)
from seq_lib.sep_lc_shadow_write_seq import (
    LC_STATE_BYTE_MASK,
    LC_STATE_UPPER_MASK,
    SepLcShadowWriteSeq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import DEMOTE_BIT, SepLccDemoteSeq

_MAX_SENSE_CYCLES = 20_000

# Starting states this test knows how to walk. A leaf that asks for anything
# else is a testlist/registry mistake, not a DUT failure, so it fails loudly.
_SUPPORTED_STARTS = (LC_PROD, LC_RMA_SIP_0, LC_RMA_CHIP_0, LC_PROD_END)


@pyuvm.test()
class sep_lcc_lc_state_transition_matrix_test(sep_base_test):
    """Shadow-write LC_STATE next state: W1S, token gates, INVALID terminal."""

    # -- leaf selection ------------------------------------------------------
    def _lc_start(self) -> int:
        raw = cocotb.plusargs.get("lc_start")
        start = LC_PROD if raw in (None, "", True) else int(str(raw), 0)
        assert start in _SUPPORTED_STARTS, (
            f"+lc_start=0x{start:x} is not a starting state this test walks "
            f"(supported: {[hex(s) for s in _SUPPORTED_STARTS]})"
        )
        return start

    @staticmethod
    def _flag(name: str) -> bool:
        return name in cocotb.plusargs

    # -- setup ---------------------------------------------------------------
    async def _sense(self, lc_raw: int, *, transient_rma: bool) -> None:
        """Bring up on the t=0 image for this leaf's starting state."""
        fixed = dict(self.cfg_lc.image_fixed())
        if transient_rma:
            fixed["TRANSIENT_RMA_EN"] = 1
        image = self.select_efuse_image(lc_raw=lc_raw, fixed=fixed)
        assert image.lc_raw() == lc_raw, (
            f"test bug: image LC 0x{image.lc_raw():x} != requested 0x{lc_raw:x}"
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        self._sip_match = False
        self._chiplet_match = False
        self._demote_1 = 0
        self._demote_2 = 0
        self._cur = lc_raw
        # Bytes [31:8] of the sensed LC word, before any shadow write.
        self._upper = image.shadow_word(LC_WORD_IDX) & LC_STATE_UPPER_MASK
        sec_dis = int(getattr(cocotb.top, "lcc_security_disable_probe_o").value) & 0x1
        assert sec_dis == 0, (
            "SEC_DIS is asserted, which forces FEAT_CTRL to all-ones and would "
            "make every decode check in this walk vacuous"
        )
        # The sensed nibble, read off the DUT, must be the state the leaf asked
        # for -- otherwise every cell below measures the wrong starting state.
        probe = int(getattr(cocotb.top, "efuse_shadow_probe_o").value)
        sensed = (probe >> (32 * LC_WORD_IDX)) & 0xF
        assert sensed == lc_raw, (
            f"leaf asked to start at {lc_state_name(lc_raw)} but the DUT sensed "
            f"{lc_state_name(sensed)}; the t=0 image staged by dv_sim_prestage.py "
            "does not match this leaf's +lc_start"
        )
        self.logger.info(
            "[lc-w1s] leaf start %s sensed from OTP (transient_rma=%d)",
            lc_state_name(lc_raw),
            int(transient_rma),
        )

    async def _match(self, kind: int) -> None:
        token = (
            self.cfg_lc.tokens.sip_token
            if kind == TOKEN_RMA_SIP
            else self.cfg_lc.tokens.chiplet_token
        )
        seq = SepRmaTokenMatchSeq(kind, token)
        await self.start_seq(seq)
        name = "RMA_SIP" if kind == TOKEN_RMA_SIP else "RMA_CHIPLET"
        assert seq.matched is True, (
            f"{name} token did not match (code=0x{seq.match_code:02x}); the gate "
            "cells would then pass for the wrong reason"
        )
        if kind == TOKEN_RMA_SIP:
            self._sip_match = True
        else:
            self._chiplet_match = True
        self.logger.info("[lc-w1s] %s token matched", name)

    async def _match_under_fault(self, kind: int) -> int:
        """Present a good token with the comparator faulted; expect the error code.

        The comparator ORs 6'b111111 onto every status bit on a redundancy
        fault, and the lifecycle gate compares for equality with the match code.
        So the token itself is valid and would otherwise open the gate: the only
        reason the advance must not land is the fault. Returns the status code.
        """
        token = (
            self.cfg_lc.tokens.sip_token
            if kind == TOKEN_RMA_SIP
            else self.cfg_lc.tokens.chiplet_token
        )
        seq = SepRmaTokenMatchSeq(kind, token)
        await self.start_seq(seq)
        assert seq.match_code is not None, "token match status never sampled"
        return int(seq.match_code)

    async def _set_token_inject(self, mode: int, sel: int = TOKEN_CMP_SEL_SIP) -> None:
        cocotb.top.token_cmp_fault_sel_i.value = sel
        cocotb.top.token_cmp_fault_inject_i.value = mode
        await ClockCycles(cocotb.top.clk_i, 2)

    async def _demote(self) -> None:
        for group in (1, 2):
            seq = SepLccDemoteSeq(group, DEMOTE_BIT)
            await self.start_seq(seq)
            assert seq.demote == 1, f"DEMOTE_{group} did not read back asserted"
        self._demote_1 = 1
        self._demote_2 = 1

    # -- one cell ------------------------------------------------------------
    async def _cell(
        self,
        wdata: int,
        tag: str,
        *,
        do_write: bool = True,
        expect: int | None = None,
        upper: int | None = None,
    ) -> int:
        """Run one cell; the expected next state comes from the chapter golden."""
        prev = self._cur
        pattern = self.cfg_lc.nuisance if upper is None else upper
        full_wdata = (wdata & LC_STATE_BYTE_MASK) | pattern
        if do_write:
            expected = lc_state_next(
                prev,
                wdata,
                sip_match=self._sip_match,
                chiplet_match=self._chiplet_match,
            )
            expected_upper = pattern
        else:
            # Readback-only cell: the move was caused by something other than a
            # bus write, so the caller supplies the golden.
            assert expect is not None, "a readback-only cell needs an expected state"
            expected = expect
            expected_upper = self._upper

        seq = SepLcShadowWriteSeq(
            full_wdata,
            expected,
            expected_upper,
            sip_dis=SIP_DIS,
            sys_dis=SYS_DIS,
            demote_1=self._demote_1,
            demote_2=self._demote_2,
            do_write=do_write,
            name=f"lc_w1s_{tag}",
        )
        await self.start_seq(seq)
        observed = seq.observed_lc_raw
        assert observed is not None, "sequence did not publish an observed LC code"
        assert seq.observed_feat is not None, "sequence did not publish a FEAT_CTRL value"
        self._last_feat = seq.observed_feat

        # The transition rules again, in observed-code form, against the code the
        # DUT returned. It overlaps the per-cell value check and fails on a step
        # that is wrong in a way the expectation shares.
        assert is_valid_lc_transition(prev, observed), (
            f"{tag}: DUT stepped {lc_state_name(prev)} -> {lc_state_name(observed)}, "
            "which the lifecycle does not permit"
        )
        if do_write:
            assert seq.observed_word is not None
            assert (seq.observed_word & LC_STATE_UPPER_MASK) == expected_upper, (
                f"CHK-UPPER-WRITE FAIL: {tag} LC_STATE[31:8] = "
                f"0x{seq.observed_word & LC_STATE_UPPER_MASK:08x} want 0x{expected_upper:08x}"
            )
            assert seq.observed_word == (expected_upper | lc_encode(expected)), (
                f"{tag}: LC_STATE word 0x{seq.observed_word:08x} != "
                f"0x{(expected_upper | lc_encode(expected)):08x}"
            )
            if tag == "CHK-UPPER-WRITE":
                self.logger.info(
                    "CHK-UPPER-WRITE PASS: LC_STATE[31:8]=0x%08x is the second "
                    "pattern alone; the prior 0x%08x did not persist",
                    expected_upper,
                    self._upper,
                )
            self._upper = expected_upper
        want_feat = feat_ctrl_expected(
            expected,
            SIP_DIS,
            SYS_DIS,
            demote_1=self._demote_1,
            demote_2=self._demote_2,
            sec_dis=0,
        )
        assert observed == expected, (
            f"{tag}: DUT LC 0x{observed:x} ({lc_state_name(observed)}) != "
            f"golden 0x{expected:x} ({lc_state_name(expected)})"
        )
        assert seq.observed_feat == want_feat, (
            f"{tag}: FEAT_CTRL 0x{seq.observed_feat:016x} != golden 0x{want_feat:016x}"
        )
        self._cur = int(observed)
        action = f"write 0x{wdata:x}" if do_write else "no write"
        self.logger.info(
            "%s PASS: %s + %s (sip_match=%d chiplet_match=%d demote=%d%d) -> %s",
            tag,
            lc_state_name(prev),
            action,
            int(self._sip_match),
            int(self._chiplet_match),
            self._demote_1,
            self._demote_2,
            lc_state_name(observed),
        )
        return int(observed)

    async def _prove_upper_write(self) -> None:
        """Second [31:8] write replaces the first: rsvd takes a plain shadow write."""
        second = self.cfg_lc.nuisance2
        # Non-vacuity: the two patterns must differ in both directions, so a
        # DUT that OR-merged instead of replacing would fail this cell rather
        # than land on the same value either way.
        assert second & ~self._upper & LC_STATE_UPPER_MASK, (
            "CHK-UPPER-WRITE FAIL: second pattern adds no new bits "
            f"(prior=0x{self._upper:08x} second=0x{second:08x})"
        )
        assert self._upper & ~second & LC_STATE_UPPER_MASK, (
            "CHK-UPPER-WRITE FAIL: second pattern covers every prior bit, so an "
            f"OR would read the same (prior=0x{self._upper:08x} second=0x{second:08x})"
        )
        await self._cell(0x0, "CHK-UPPER-WRITE", upper=second)

    # -- per-leaf walks ------------------------------------------------------
    async def _walk_prod(self) -> None:
        # Read the preloaded state before touching it. Two things depend on
        # this: nothing else asserts the image actually starts where the walk
        # claims, and the coverage sampler only records an LC state on a real
        # LC_STATE read -- every cell below writes first, so without this the
        # start state is never observed.
        await self._cell(0x0, "CHK-START-SENSED", do_write=False, expect=LC_PROD)
        await self._cell(0x0, "CHK-W1S-NO-CLEAR")
        await self._prove_upper_write()
        await self._cell(0x2, "CHK-GATE-SIP")
        # CHIPLET matched but RMA_SIP not established: the ordering gate holds
        # here with the token gate already open.
        await self._match(TOKEN_RMA_CHIPLET)
        await self._cell(0x4, "CHK-GATE-CHIP-ORD")
        # A faulted comparator must fail CLOSED at the lifecycle gate, not just
        # report an error code. self._sip_match stays False, so the golden holds
        # the state and the cell fails if the DUT advances. This is the cell that
        # separates a gate written as "== match code" from one written as "not a
        # mismatch": the fault code 0x3F would pass the latter.
        await self._set_token_inject(TOKEN_CMP_INJECT_COLLAPSE, TOKEN_CMP_SEL_SIP)
        code = await self._match_under_fault(TOKEN_RMA_SIP)
        assert code == TOKEN_ERROR, (
            "CHK-GATE-SIP-FAULT: a collapsed SIP comparator must report the error "
            f"code 0x{TOKEN_ERROR:02x}, got 0x{code:02x}; the fail-closed cell "
            "below would otherwise pass for the wrong reason"
        )
        await self._cell(0x2, "CHK-GATE-SIP-FAULT")
        await self._set_token_inject(TOKEN_CMP_INJECT_OFF, TOKEN_CMP_SEL_SIP)

        await self._match(TOKEN_RMA_SIP)
        got = await self._cell(0x2, "CHK-SIP-ADVANCE")
        assert got == 0x3, f"CHK-SIP-ADVANCE: PROD + bit1 must reach 0x3, got 0x{got:x}"

    async def _walk_prod_demoted(self) -> None:
        await self._demote()
        # Non-vacuity for the advance below: this readback's FEAT_CTRL golden
        # carries demote_1/2=1, so it passes only if the demotion took effect.
        await self._cell(0x0, "CHK-DEMOTE-OPEN")
        await self._prove_upper_write()
        await self._match(TOKEN_RMA_SIP)
        got = await self._cell(0x2, "CHK-DEMOTE-NO-BLOCK")
        assert got == 0x3, (
            "CHK-DEMOTE-NO-BLOCK: a demoted PROD part must still advance to "
            f"RMA_SIP on a token match, got 0x{got:x}"
        )

    async def _walk_rma_sip(self) -> None:
        # Read the preloaded state before touching it. Two things depend on
        # this: nothing else asserts the image actually starts where the walk
        # claims, and the coverage sampler only records an LC state on a real
        # LC_STATE read -- every cell below writes first, so without this the
        # start state is never observed.
        await self._cell(0x0, "CHK-START-SENSED", do_write=False, expect=LC_RMA_SIP_0)
        got = await self._cell(0x1, "CHK-RMA-BIT0")
        await self._prove_upper_write()
        assert got == 0x3, f"RMA_SIP is 4'b001X: 0x2 + bit0 must be 0x3, got 0x{got:x}"
        # No CHIPLET token presented yet: the token gate alone.
        await self._cell(0x4, "CHK-GATE-CHIP-TOK")
        await self._match(TOKEN_RMA_CHIPLET)
        got = await self._cell(0x4, "CHK-CHIP-ADVANCE")
        assert got == 0x7, f"RMA_SIP + bit2 with a match must reach 0x7, got 0x{got:x}"

        # Reached RMA_CHIPLET legitimately; now leave the named set.
        got = await self._cell(0x8, "CHK-INVALID-REACH")
        assert is_invalid_lc(got), (
            "CHK-INVALID-REACH: 0x7 + bit3 must land outside the named encodings, "
            f"got {lc_state_name(got)}"
        )
        assert got == 0xF, f"expected 0xF (0x7 | 0x8), got 0x{got:x}"
        # Under these disable vectors no in-spec state decodes to 0, so this is a
        # real discriminator rather than a coincidence.
        assert self._last_feat == 0, (
            "CHK-INVALID-REACH: FEAT_CTRL must fail closed to 0 outside the named "
            f"set, got 0x{self._last_feat:016x}"
        )
        await self._match(TOKEN_RMA_SIP)
        got = await self._cell(0xF, "CHK-INVALID-TERM")
        assert got == 0xF, (
            "CHK-INVALID-TERM: INVALID is end-of-life; a write of every bit with "
            f"both tokens matched must change nothing, got 0x{got:x}"
        )

    async def _walk_rma_chiplet(self) -> None:
        # Read the preloaded state before touching it. Two things depend on
        # this: nothing else asserts the image actually starts where the walk
        # claims, and the coverage sampler only records an LC state on a real
        # LC_STATE read -- every cell below writes first, so without this the
        # start state is never observed.
        await self._cell(0x0, "CHK-START-SENSED", do_write=False, expect=LC_RMA_CHIP_0)
        got = await self._cell(0x1, "CHK-RMA-BIT0")
        await self._prove_upper_write()
        assert got == 0x7, f"RMA_CHIPLET is 4'b011X: 0x6 + bit0 must be 0x7, got 0x{got:x}"

    async def _walk_prod_end(self) -> None:
        # Read the preloaded state before touching it. Two things depend on
        # this: nothing else asserts the image actually starts where the walk
        # claims, and the coverage sampler only records an LC state on a real
        # LC_STATE read -- every cell below writes first, so without this the
        # start state is never observed.
        await self._cell(0x0, "CHK-START-SENSED", do_write=False, expect=LC_PROD_END)
        got = await self._cell(0x1, "CHK-PROD-END-INVALID")
        await self._prove_upper_write()
        assert is_invalid_lc(got) and got == 0x9, (
            "CHK-PROD-END-INVALID: PROD_END's reachable destination is INVALID "
            f"(0x9), got {lc_state_name(got)}"
        )
        # Bits 1 and 2 are still clear. Both tokens matched, so a DUT that
        # treated INVALID as ordinary W1S would set them. The chapter's
        # end-of-life rule holds them.
        await self._match(TOKEN_RMA_SIP)
        await self._match(TOKEN_RMA_CHIPLET)
        held = await self._cell(0x6, "CHK-INVALID-TERM")
        assert held == 0x9, (
            "CHK-INVALID-TERM: from INVALID 0x9 a write of the remaining "
            f"lifecycle bits with both tokens matched must hold, got 0x{held:x}"
        )

    async def _walk_transient(self) -> None:
        """Transient RMA: the same gates, with no bus request at all."""
        expected = lc_state_next(LC_PROD_END, 0x2, sip_match=True, chiplet_match=False)
        assert is_invalid_lc(expected), "test bug: PROD_END + bit1 should be INVALID"

        # TRANSIENT_RMA_EN is armed but no token has been presented. The state
        # must hold: the transient path applies the token gates, it does not
        # bypass them. Without this cell the walk below could pass on a DUT that
        # moves as soon as the enable bit is sensed.
        await self._cell(0x0, "CHK-TRANSIENT-NO-TOKEN", do_write=False, expect=LC_PROD_END)

        await self._match(TOKEN_RMA_SIP)
        got = await self._cell(0x0, "CHK-TRANSIENT-INVALID", do_write=False, expect=expected)
        assert got == expected, (
            "CHK-TRANSIENT-INVALID: the transient path must apply the same W1S and "
            f"token rules as the bus path; expected 0x{expected:x}, got 0x{got:x}"
        )
        # The transient cells never write the shadow. A later bus write of 0
        # keeps INVALID and lets the two-pattern upper-byte write run on this
        # leaf too.
        await self._cell(0x0, "CHK-W1S-NO-CLEAR")
        await self._prove_upper_write()

    # -- entry ---------------------------------------------------------------
    async def run_scenario(self) -> None:
        self.cfg_lc = SepLcTransitionCfg(self.random_seed())
        self._last_feat = 0
        start = self._lc_start()
        demote = self._flag("lc_demote")
        transient = self._flag("lc_transient_rma")
        self.logger.info(
            "lc W1S leaf: start=%s demote=%d transient_rma=%d RANDCFG: %s",
            lc_state_name(start),
            int(demote),
            int(transient),
            self.cfg_lc.summary(),
        )

        await self._sense(start, transient_rma=transient)

        if transient:
            assert start == LC_PROD_END, (
                "+lc_transient_rma is defined only from PROD_END here, where the "
                "transient result is outside the named set"
            )
            await self._walk_transient()
            walked = "transient-rma"
        elif start == LC_PROD:
            if demote:
                await self._walk_prod_demoted()
                walked = "prod-demoted"
            else:
                await self._walk_prod()
                walked = "prod-gates"
        elif start == LC_RMA_SIP_0:
            await self._walk_rma_sip()
            walked = "rma-sip + invalid-terminal"
        elif start == LC_RMA_CHIP_0:
            await self._walk_rma_chiplet()
            walked = "rma-chiplet"
        else:
            await self._walk_prod_end()
            walked = "prod-end"

        self.logger.info(
            "CHK-LEAF PASS: walked %s from a sensed %s (tokens and LC_STATE[31:8] "
            "pattern from seed %d)",
            walked,
            lc_state_name(start),
            self.cfg_lc.seed,
        )
