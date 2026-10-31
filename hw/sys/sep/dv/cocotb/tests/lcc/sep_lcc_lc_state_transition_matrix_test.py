# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A frontdoor LC_STATE shadow write that the W1S and token rules hold changes nothing.

No testlist entry carries this module's name. Seven entries in
``testlists/efuse_lcc.toml`` run it, each selecting a start state with
``+lc_start=N``: sep_lcc_lc_state_w1s_prod_test (1),
sep_lcc_lc_state_w1s_prod_demote_test, sep_lcc_lc_state_w1s_rma_sip_test,
sep_lcc_lc_state_w1s_rma_chiplet_test, sep_lcc_lc_state_w1s_prod_end_test,
sep_lcc_lc_state_w1s_prod_end_rma_test (the two PROD_END exits, pinned with
``+lc_prod_end_exit``) and sep_lcc_lc_state_w1s_transient_test. Run one of those
names, not this one.

The lifecycle stitch walk covers the OTP-program path: burn a fuse bit, re-sense,
check the decode. This test covers the other writer of LC_STATE -- the frontdoor
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
INVALID". Demotion is not a term: the chapter calls it volatile debug state,
distinct from RMA "whose state transitions are hardware-ordered", so a demoted
part must transition exactly like a non-demoted one.

Two TT texts disagree on a bus write that the chapter golden moves:
``otp_fuse_controller.adoc`` (Fuse Fields) gives LC_STATE as SW writable
set-only, and ``sep_efuse_map.rdl`` (register ``LC_STATE``) gives ``lc_state`` as
sw = r, which makes every bus write a no-change. A write that the gates hold has
the same value under both texts and is graded. A write that the chapter moves is
an advance cell: its LC_STATE result is logged (``OBS-LC-WR-ADVANCE``), and only
FEAT_CTRL against the decode of the state the DUT returned is graded
(``CHK-LC-FEAT-DECODE``). Later cells start from the returned state.

One sensed starting state per leaf. ``efuse_bank_model`` deposits the OTP image
in a time-0 ``initial`` and a fuse survives reset, so a test cannot re-sense its
way to a different starting state -- only a superset is reachable, by programming
bits for real. Each starting state is therefore its own leaf, staged at t=0 by
``dv_sim_prestage.py`` and selected by ``+lc_start`` (with ``+lc_demote`` /
``+lc_transient_rma`` for the two variant leaves). Real fuse sense throughout;
no backdoor deposit anywhere on the lifecycle path.

Both halves of every hold and readback cell are value-checked: the LC_STATE
shadow word (the differential ``{~raw, raw}``) and the LCC FEAT_CTRL decode of
that same state.
FEAT_CTRL is what proves the write reached the lifecycle controller rather than
only the shadow storage -- and for a state outside the named set it must read 0
("all features disabled by fail-closed default"), which no in-spec state
produces under these disable vectors.

Checkers, by leaf (``+lc_start`` value). Every leaf starts with CHK-START-SENSED
(the sensed LC_STATE equals the staged start state), except the demoted and
transient leaves, and ends with ``INFO-LEAF`` (the walk, the seed and the
required checks; it grades nothing). Each walk names its required checks
(``_REQUIRED``), and a leaf that misses one fails.

  1 (PROD)
    * CHK-W1S-NO-CLEAR   a write of 0 clears nothing.
    * CHK-GATE-SIP       bit 1 without an RMA_SIP token match does not set.
    * CHK-GATE-CHIP-ORD  bit 2 with a CHIPLET match but no RMA_SIP does not set
                         -- the ordering gate, with the token gate already open.
    * CHK-GATE-SIP-FAULT a collapsed SIP comparator reports the error code, and
                         bit 1 then does not set (the gate fails closed).
    * advance SIP-ADVANCE: bit 1 with a match (chapter: PROD -> RMA_SIP).
  1 + demote
    * CHK-DEMOTE-OPEN      DEMOTE_1+DEMOTE_2 in PROD is observable in FEAT_CTRL.
    * advance DEMOTE-ADVANCE: the same bit-1 write, demoted.
  2 (RMA_SIP_0)
    * advance RMA-BIT0: bit 0 inside RMA_SIP (chapter: 0x2 -> 0x3).
    * CHK-GATE-CHIP-TOK  bit 2 without a CHIPLET match does not set.
    * advance CHIP-ADVANCE: bit 2 with a match (chapter: RMA_CHIPLET).
    * advance INVALID-REACH: bit 3 (chapter: outside the named set).
  6 (RMA_CHIP_0)
    * advance RMA-BIT0: bit 0 inside RMA_CHIPLET (chapter: 0x6 -> 0x7).
  8 (PROD_END)
    * advance PROD-END-EXIT: the seed selects one of the two exits (one sensed
                           start per leaf): a write of the ungated bit 0
                           (chapter: 0x9), or an RMA_SIP token match and a write
                           of bit 1 (chapter: INVALID 0xA).
    * CTRL-LC-INVALID-START the exit returned an INVALID state; a miss fails the
                           leaf, since the next cell needs that start.
    * CHK-INVALID-TERM     from that INVALID state, a write of the remaining
                           lifecycle bits with both tokens matched changes
                           nothing.
  8 + transient RMA
    * CTRL-TRANSIENT-EN-ARMED the TRANSIENT_RMA_EN shadow bit 0 reads 1 after
                             sense (``efuse_shadow_probe_o``), so both cells run armed.
    * CHK-TRANSIENT-NO-TOKEN with TRANSIENT_RMA_EN armed and no token presented,
                             the state holds at PROD_END.
    * CHK-TRANSIENT-INVALID  the transient path applies the same W1S and token
                             rules with no bus request, INVALID result included.

  Every advance cell logs ``OBS-LC-WR-ADVANCE`` (prior state, write, chapter
  golden, returned state) and grades ``CHK-LC-FEAT-DECODE``: FEAT_CTRL equals
  the feature-control decode of the returned state (0 for an INVALID state).

Every hold and readback cell grades LC_STATE[7:0] against ``{~raw, raw}`` of the
golden state.
Every cell grades ``CHK-LC-STATE-PORT``: the ``lc_state_o`` port (tap
``lc_state_probe_o``) equals LC_STATE[7:0] at ``efuse_shadow_probe_o`` and
``{~raw, raw}`` of the cell's state (the golden state of a hold or readback cell,
the returned state of an advance cell). ``doc/integrator/src/smu-sep.adoc:202``
gives ``lc_state_o`` as the differentially encoded LC_STATE shadow, and
``hw/sys/sep/doc/otp_fuse_controller.adoc:217-218`` gives that encoding as
``{~raw[3:0], raw[3:0]}`` in bits [7:0].
Every write cell also carries, in LC_STATE[31:8], one bit that no earlier write
or the sensed word set; ``CTRL-LC-WR-LANDED`` requires that bit in the readback,
so a dropped write fails the leaf whether the bytes overwrite or OR-merge. The
seeded patterns leave LC_STATE[31:24] clear (``_MARK_POOL``), so every write cell
of every walk has such a bit on every seed.
Every leaf with a bus-write cell also writes a second seed-derived [31:8]
pattern that differs from the first in both directions (a CHK-W1S-NO-CLEAR
cell). ``CTRL-TOKEN-MATCH`` (each token match), ``CTRL-GATE-SIP-FAULT`` (the
collapsed comparator code) and ``CTRL-TOKEN-SIP-HELD`` (the SIP match before
CHK-INVALID-TERM) record the preconditions of the hold cells.

Log-only, every cell: ``OBS-LC-UPPER`` (LC_STATE[31:8] written, prior and read:
the RDL gives ``lc_state`` and ``rsvd`` as sw = r and ``rsvd`` as "Unused", and
the fuse-field table gives LC_STATE as SW writable set-only; the texts disagree);
every hold cell whose write a token gate or the terminal rule refuses (the
CHK-GATE-* cells and CHK-INVALID-TERM): ``OBS-LC-WR-REFUSED-RESP`` (the write
response; no text states the response of a refused write, so the scoreboard
does not grade it); every write cell: ``OBS-LC-WR-NIBBLE`` (bits
[7:4] of the write data and of the readback word: the specification does not
state how a write of the complement nibble acts).

RANDCFG: the tokens and the LC_STATE[23:8] patterns come from the run seed
(``SepLcTransitionCfg``, masked with ``_MARK_POOL``). The two PROD_END leaves pin the exit with
``+lc_prod_end_exit=bit0|rma_sip``; without it the seed selects one
(``_prod_end_exit``).
Every other cell within a leaf is fixed.
"""

from __future__ import annotations

from functools import partial

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_efuse_image import LC_WORD_IDX, SepEfuseImage, lc_encode
from env.sep_efuse_test_lib import shadow_word
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
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_CMP_INJECT_COLLAPSE,
    TOKEN_CMP_INJECT_OFF,
    TOKEN_CMP_SEL_SIP,
    TOKEN_ERROR,
    TOKEN_MATCH,
    TOKEN_RMA_CHIPLET,
    TOKEN_RMA_SIP,
    SepRmaTokenMatchSeq,
    SepRmaTokenStatusSeq,
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

# The two exits from PROD_END. One sensed start per leaf, and each exit leaves
# PROD_END, so a leaf walks one of them; the seed selects which.
_PROD_END_EXITS = ("bit0", "rma_sip")
# Salt for the exit-choice stream, so it is independent of the SepLcTransitionCfg
# stream drawn from the same seed.
_PROD_END_EXIT_SALT = 0x5052_4F44_454E_4400
# LC_STATE bits kept out of the seeded [31:8] patterns, so CTRL-LC-WR-LANDED has
# an unused bit for each write cell. Eight bits cover the longest walk (six writes).
_MARK_POOL = 0xFF00_0000
# Checks each walk emits; a leaf that misses one fails its evidence gate.
_REQUIRED = {
    "prod-gates": (
        "CHK-START-SENSED",
        "CHK-W1S-NO-CLEAR",
        "CHK-GATE-SIP",
        "CHK-GATE-CHIP-ORD",
        "CHK-GATE-SIP-FAULT",
        "CHK-LC-FEAT-DECODE",
    ),
    "prod-demoted": ("CHK-DEMOTE-OPEN", "CHK-W1S-NO-CLEAR", "CHK-LC-FEAT-DECODE"),
    "rma-sip + invalid-reach": (
        "CHK-START-SENSED",
        "CHK-LC-FEAT-DECODE",
        "CHK-W1S-NO-CLEAR",
        "CHK-GATE-CHIP-TOK",
    ),
    "rma-chiplet": ("CHK-START-SENSED", "CHK-LC-FEAT-DECODE", "CHK-W1S-NO-CLEAR"),
    "prod-end": (
        "CHK-START-SENSED",
        "CHK-LC-FEAT-DECODE",
        "CHK-W1S-NO-CLEAR",
        "CHK-INVALID-TERM",
    ),
    "transient-rma": ("CHK-TRANSIENT-NO-TOKEN", "CHK-TRANSIENT-INVALID", "CHK-W1S-NO-CLEAR"),
}
# Every walk grades the lc_state_o port in every cell.
_REQUIRED = {walk: (*ids, "CHK-LC-STATE-PORT") for walk, ids in _REQUIRED.items()}


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

    def _prod_end_exit(self) -> str:
        """PROD_END exit for this seed, or the ``+lc_prod_end_exit`` override."""
        raw = cocotb.plusargs.get("lc_prod_end_exit")
        if raw not in (None, "", True):
            choice = str(raw)
            assert choice in _PROD_END_EXITS, (
                f"+lc_prod_end_exit={choice} is not one of {_PROD_END_EXITS}"
            )
            return choice
        rng = SepSeededRng(self.cfg_lc.seed ^ _PROD_END_EXIT_SALT)
        return _PROD_END_EXITS[rng.randrange(len(_PROD_END_EXITS))]

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
        # Every [31:8] bit written or sensed so far. A bit outside this set is
        # absent from the readback whether the bytes overwrite or OR-merge.
        self._nuisance = self.cfg_lc.nuisance & ~_MARK_POOL
        self._nuisance2 = self.cfg_lc.nuisance2 & ~_MARK_POOL
        self._upper_seen = self._upper | self._nuisance | self._nuisance2
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
            "INFO-LC-START leaf start %s sensed from OTP (transient_rma=%d)",
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
        code = "none" if seq.match_code is None else f"0x{seq.match_code:02x}"
        # Same text as SepChkLog.ctrl(): a miss logs CTRL-MISSING and fails the
        # leaf, because the gate cells after it would pass for the wrong reason.
        if seq.matched is not True:
            line = f"CTRL-MISSING TOKEN-MATCH: kind={name} code={code}"
            self.logger.error(line)
            raise AssertionError(line)
        if kind == TOKEN_RMA_SIP:
            self._sip_match = True
        else:
            self._chiplet_match = True
        self.logger.info("CTRL-TOKEN-MATCH seen: kind=%s code=%s", name, code)

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
        """Run one cell; the expected next state comes from the chapter golden.

        A ``CHK-`` cell is a hold or a readback: both TT texts give its value. A
        cell with no ``CHK-`` prefix is a bus write that the chapter golden moves;
        the RDL gives ``lc_state`` as sw = r, so that state is logged
        (``OBS-LC-WR-ADVANCE``) and only the FEAT_CTRL decode of the state the DUT
        returned is graded (``CHK-LC-FEAT-DECODE``).
        """
        prev = self._cur
        # One [31:8] bit no earlier write or sense set: its readback shows that
        # this write reached the shadow (CTRL-LC-WR-LANDED).
        free = LC_STATE_UPPER_MASK & ~self._upper_seen
        mark = free & -free
        pattern = (self._nuisance if upper is None else upper) | mark
        full_wdata = (wdata & LC_STATE_BYTE_MASK) | pattern
        if do_write:
            assert mark, f"CTRL-MISSING LC-WR-LANDED {tag}: no unused LC_STATE[31:8] bit left"
            self._upper_seen |= pattern
            expected = lc_state_next(
                prev,
                wdata,
                sip_match=self._sip_match,
                chiplet_match=self._chiplet_match,
            )
        else:
            # Readback-only cell: the move was caused by something other than a
            # bus write, so the caller supplies the golden.
            assert expect is not None, "a readback-only cell needs an expected state"
            expected = expect

        advance = do_write and expected != prev
        assert advance != tag.startswith("CHK-"), (
            f"CTRL-MISSING LC-CELL-KIND {tag}: golden {lc_state_name(expected)} from "
            f"{lc_state_name(prev)}; a CHK- cell must hold and an advance cell must move"
        )
        # A hold cell whose write sets a lifecycle bit that is still 0 is a write
        # that a token gate or the terminal rule refuses. No text states the
        # response of a refused write, so it is logged (OBS-LC-WR-REFUSED-RESP).
        refused = do_write and not advance and bool(wdata & 0xF & ~prev)
        seq = SepLcShadowWriteSeq(
            full_wdata,
            None if advance else expected,
            None,
            sip_dis=SIP_DIS,
            sys_dis=SYS_DIS,
            demote_1=self._demote_1,
            demote_2=self._demote_2,
            do_write=do_write,
            refused=refused,
            name=f"lc_w1s_{tag}",
        )
        await self.start_seq(seq)
        if refused:
            self.logger.info(
                "OBS-LC-WR-REFUSED-RESP tag=%s prev=%s wdata=0x%08x resp=%s",
                tag,
                lc_state_name(prev),
                full_wdata,
                seq.write_resp,
            )
        observed = seq.observed_lc_raw
        assert observed is not None, "sequence did not publish an observed LC code"
        assert seq.observed_feat is not None, "sequence did not publish a FEAT_CTRL value"
        dut = cocotb.top
        shadow = self.rd(dut.efuse_shadow_probe_o, allow_unknown=True) >> (32 * LC_WORD_IDX)
        if do_write and seq.observed_word is not None:
            self.logger.info(
                "OBS-LC-WR-NIBBLE tag=%s wdata_hi=0x%x observed_hi=0x%x",
                tag,
                (full_wdata >> 4) & 0xF,
                (seq.observed_word >> 4) & 0xF,
            )
        # lc_state_o is the differentially encoded LC_STATE shadow, {~raw, raw}.
        # It is graded against the shadow probe and against the encoding of the
        # cell's state, so a probe fault cannot mask a port fault.
        port = self.rd(dut.lc_state_probe_o, 0xFF) & 0xFF
        port_raw = observed if advance else expected
        assert port == shadow & LC_STATE_BYTE_MASK == lc_encode(port_raw), (
            f"CHK-LC-STATE-PORT FAIL: tag={tag} lc_state_o=0x{port:02x} "
            f"shadow=0x{shadow & 0xFFFF_FFFF:08x} expect=0x{lc_encode(port_raw):02x}"
        )
        self.logger.info(
            "CHK-LC-STATE-PORT PASS: tag=%s lc_state_o=0x%02x shadow=0x%08x expect=0x%02x",
            tag,
            port,
            shadow & 0xFFFF_FFFF,
            lc_encode(port_raw),
        )

        assert seq.observed_word is not None
        word = seq.observed_word
        if not advance:
            # The transition rules again, in observed-code form, against the code
            # the DUT returned. It overlaps the per-cell value check and fails on a
            # step that is wrong in a way the expectation shares.
            assert is_valid_lc_transition(prev, observed), (
                f"{tag}: DUT stepped {lc_state_name(prev)} -> {lc_state_name(observed)}, "
                "which the lifecycle does not permit"
            )
            assert word & LC_STATE_BYTE_MASK == lc_encode(expected), (
                f"{tag}: LC_STATE[7:0] 0x{word & LC_STATE_BYTE_MASK:02x} != "
                f"0x{lc_encode(expected):02x}"
            )
        got_upper = word & LC_STATE_UPPER_MASK
        if do_write:
            assert got_upper & mark, (
                f"CTRL-MISSING LC-WR-LANDED {tag}: unused bit 0x{mark:08x} written, "
                f"LC_STATE[31:8] reads 0x{got_upper:08x}"
            )
            self.logger.info(
                "CTRL-LC-WR-LANDED LOG tag=%s mark=0x%08x upper=0x%08x",
                tag,
                mark,
                got_upper,
            )
        # LC_STATE[31:8]: the RDL gives ``lc_state`` and ``rsvd`` as sw = r and
        # ``rsvd`` as "Unused" (sep_efuse_map.rdl, LC_STATE), while the fuse-field
        # table gives LC_STATE as SW writable set-only (otp_fuse_controller.adoc,
        # Fuse Fields). The texts disagree, so the readback after a write is logged.
        self.logger.info(
            "OBS-LC-UPPER LOG tag=%s wrote=0x%08x prior=0x%08x read=0x%08x "
            "overwrite=%d or_merge=%d",
            tag,
            pattern if do_write else 0,
            self._upper,
            got_upper,
            int(do_write and got_upper == pattern),
            int(do_write and got_upper == (pattern | self._upper)),
        )
        self._upper = got_upper
        want_feat = feat_ctrl_expected(
            observed if advance else expected,
            SIP_DIS,
            SYS_DIS,
            demote_1=self._demote_1,
            demote_2=self._demote_2,
            sec_dis=0,
        )
        self._cur = int(observed)
        if advance:
            # The chapter golden moves the state; the RDL gives lc_state as sw = r.
            self.logger.info(
                "OBS-LC-WR-ADVANCE cell=%s prev=%s wdata=0x%x sip_match=%d "
                "chiplet_match=%d chapter=0x%x got=0x%x word=0x%08x",
                tag,
                lc_state_name(prev),
                wdata,
                int(self._sip_match),
                int(self._chiplet_match),
                expected,
                observed,
                word,
            )
            # The cells after an advance start from the state it reaches, so a
            # state other than the chapter golden is a missing setup for them.
            landed = (
                f"cell={tag} prev={lc_state_name(prev)} expect={lc_state_name(expected)} "
                f"got={lc_state_name(observed)}"
            )
            assert observed == expected, f"CTRL-MISSING LC-ADVANCE-STATE {landed}"
            self.logger.info("CTRL-LC-ADVANCE-STATE seen: %s", landed)
            assert seq.observed_feat == want_feat, (
                f"CHK-LC-FEAT-DECODE FAIL: cell={tag} state={lc_state_name(observed)} "
                f"FEAT_CTRL 0x{seq.observed_feat:016x} != decode 0x{want_feat:016x}"
            )
            self.logger.info(
                "CHK-LC-FEAT-DECODE PASS: cell=%s state=%s FEAT_CTRL=0x%016x",
                tag,
                lc_state_name(observed),
                want_feat,
            )
            return int(observed)
        assert observed == expected, (
            f"{tag}: DUT LC 0x{observed:x} ({lc_state_name(observed)}) != "
            f"golden 0x{expected:x} ({lc_state_name(expected)})"
        )
        assert seq.observed_feat == want_feat, (
            f"{tag}: FEAT_CTRL 0x{seq.observed_feat:016x} != golden 0x{want_feat:016x}"
        )
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
        """A second [31:8] pattern over the first; the readback is OBS-LC-UPPER.

        The two patterns differ in both directions, so the logged readback tells
        an overwrite from an OR-merge. The nibble cell is a write of 0
        (CHK-W1S-NO-CLEAR).
        """
        await self._cell(0x0, "CHK-W1S-NO-CLEAR", upper=self._nuisance2)

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
        self.logger.info("CTRL-GATE-SIP-FAULT LOG code=0x%02x", code)
        await self._cell(0x2, "CHK-GATE-SIP-FAULT")
        await self._set_token_inject(TOKEN_CMP_INJECT_OFF, TOKEN_CMP_SEL_SIP)

        await self._match(TOKEN_RMA_SIP)
        await self._cell(0x2, "SIP-ADVANCE")

    async def _walk_prod_demoted(self) -> None:
        await self._demote()
        # Non-vacuity for the advance below: this readback's FEAT_CTRL golden
        # carries demote_1/2=1, so it passes only if the demotion took effect.
        await self._cell(0x0, "CHK-DEMOTE-OPEN")
        await self._prove_upper_write()
        await self._match(TOKEN_RMA_SIP)
        await self._cell(0x2, "DEMOTE-ADVANCE")

    async def _walk_rma_sip(self) -> None:
        # Read the preloaded state first (see _walk_prod).
        await self._cell(0x0, "CHK-START-SENSED", do_write=False, expect=LC_RMA_SIP_0)
        await self._cell(0x1, "RMA-BIT0")
        await self._prove_upper_write()
        # No CHIPLET token presented yet: the token gate alone.
        await self._cell(0x4, "CHK-GATE-CHIP-TOK")
        await self._match(TOKEN_RMA_CHIPLET)
        await self._cell(0x4, "CHIP-ADVANCE")
        # Leave the named set: bit 3 from the state the DUT returned.
        await self._cell(0x8, "INVALID-REACH")

    async def _walk_rma_chiplet(self) -> None:
        # Read the preloaded state first (see _walk_prod).
        await self._cell(0x0, "CHK-START-SENSED", do_write=False, expect=LC_RMA_CHIP_0)
        await self._cell(0x1, "RMA-BIT0")
        await self._prove_upper_write()

    async def _walk_prod_end(self, exit_path: str) -> None:
        # Read the preloaded state first (see _walk_prod).
        await self._cell(0x0, "CHK-START-SENSED", do_write=False, expect=LC_PROD_END)
        if exit_path == "rma_sip":
            # The RMA path, which the chapter forbids from PROD_END. The SIP
            # token gate is open, so the exact compare fails on a DUT that moves
            # PROD_END into a named RMA state, and on one that holds bit 1 and
            # stays in PROD_END. The golden result is outside the named set.
            exit_wdata = 0x2
            await self._match(TOKEN_RMA_SIP)
        else:
            exit_wdata = 0x1
        want = lc_state_next(
            LC_PROD_END,
            exit_wdata,
            sip_match=self._sip_match,
            chiplet_match=self._chiplet_match,
        )
        assert is_invalid_lc(want), (
            f"test bug: the golden for the {exit_path} exit from PROD_END is "
            f"{lc_state_name(want)}, not INVALID"
        )
        got = await self._cell(exit_wdata, "PROD-END-EXIT")
        await self._prove_upper_write()
        # CHK-INVALID-TERM holds the state from INVALID; it needs the exit to have
        # left the named set.
        assert is_invalid_lc(got), (
            f"CTRL-MISSING LC-INVALID-START: the {exit_path} exit from PROD_END "
            f"returned {lc_state_name(got)}, so CHK-INVALID-TERM has no INVALID start"
        )
        self.logger.info(
            "CTRL-LC-INVALID-START seen: seed=%d exit=%s state=0x%x",
            self.cfg_lc.seed,
            exit_path,
            got,
        )
        # The lifecycle bits the exit left clear: bits 1 and 2 after the bit-0
        # exit, bits 0 and 2 after the bit-1 exit. Bit 0 is ungated, and with
        # both tokens matched bits 1 and 2 are open too, so a DUT that treated
        # INVALID as ordinary W1S would set them. The chapter's end-of-life rule
        # holds them.
        remaining = 0x7 & ~got
        await self._match(TOKEN_RMA_SIP)
        await self._match(TOKEN_RMA_CHIPLET)
        # Live control for the bit-1 half of the claim: the SIP match must still
        # hold after the CHIPLET presentation, or a DUT that treats INVALID as
        # ordinary W1S would also hold the state here and pass.
        sip = SepRmaTokenStatusSeq(TOKEN_RMA_SIP)
        await self.start_seq(sip)
        assert sip.match_code == TOKEN_MATCH, (
            "CHK-INVALID-TERM: RMA_SIP_TOKEN_MATCH reads "
            f"0x{sip.match_code:02x} after the RMA_CHIPLET match, expected the match "
            f"code 0x{TOKEN_MATCH:02x}; the hold below would not be under test"
        )
        self.logger.info("CTRL-TOKEN-SIP-HELD LOG code=0x%02x", sip.match_code)
        held = await self._cell(remaining, "CHK-INVALID-TERM")
        assert held == got, (
            f"CHK-INVALID-TERM: from INVALID 0x{got:x} a write of the remaining "
            f"lifecycle bits 0x{remaining:x} with both tokens matched must hold, "
            f"got 0x{held:x}"
        )

    async def _walk_transient(self) -> None:
        """Transient RMA: the same gates, with no bus request at all."""
        expected = lc_state_next(LC_PROD_END, 0x2, sip_match=True, chiplet_match=False)
        assert is_invalid_lc(expected), "test bug: PROD_END + bit1 should be INVALID"

        en = shadow_word(self, SepEfuseImage.field("TRANSIENT_RMA_EN").word) & 1
        assert en == 1, (
            f"CTRL-MISSING TRANSIENT-EN-ARMED: TRANSIENT_RMA_EN shadow bit 0 reads {en} "
            "after sense, staged 1"
        )
        self.logger.info(
            "CTRL-TRANSIENT-EN-ARMED seen: seed=%d staged=1 shadow=%d", self.cfg_lc.seed, en
        )

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
        start = self._lc_start()
        demote = self._flag("lc_demote")
        transient = self._flag("lc_transient_rma")
        prod_end_exit = self._prod_end_exit() if start == LC_PROD_END and not transient else None
        self.logger.info(
            "INFO-LC-LEAF start=%s demote=%d transient_rma=%d RANDCFG: %s%s",
            lc_state_name(start),
            int(demote),
            int(transient),
            self.cfg_lc.summary(),
            f" prod_end_exit={prod_end_exit}" if prod_end_exit else "",
        )

        if transient:
            assert start == LC_PROD_END, (
                "+lc_transient_rma is defined only from PROD_END here, where the "
                "transient result is outside the named set"
            )
            walked, walk = "transient-rma", self._walk_transient
        elif start == LC_PROD and demote:
            walked, walk = "prod-demoted", self._walk_prod_demoted
        elif start == LC_PROD:
            walked, walk = "prod-gates", self._walk_prod
        elif start == LC_RMA_SIP_0:
            walked, walk = "rma-sip + invalid-reach", self._walk_rma_sip
        elif start == LC_RMA_CHIP_0:
            walked, walk = "rma-chiplet", self._walk_rma_chiplet
        else:
            walked, walk = "prod-end", partial(self._walk_prod_end, prod_end_exit)
        self.required_evidence = _REQUIRED[walked]

        await self._sense(start, transient_rma=transient)
        await walk()

        self.logger.info(
            "INFO-LEAF walked=%s exit=%s start=%s seed=%d required=%s",
            walked,
            prod_end_exit or "na",
            lc_state_name(start),
            self.cfg_lc.seed,
            ",".join(self.required_evidence),
        )
