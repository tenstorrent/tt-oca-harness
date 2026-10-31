# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FEAT_CTRL per raw state code, strap, demotion and SEC_DIS; disable-vector owners; DFT ports.

RAND-REP. Run mode no_cpu (``lsu_stub_all_live``), real fuse sense. The seed draws
one leaf plan (``env/sep_efuse_plan.py``, the same function ``dv_sim_prestage.py``
stages the t=0 image from): the follow-on leg (B 3, C 2, RMA bypass 1, earlier
owner 1, walk 2, E 2), the raw code r of the leg, the strap s of the leg A read,
the disable-vector pair (or the exception of the leg) and the leg dimensions.

Leg A runs in every leaf: the strap-s read, the SEC_DIS demotion step, then a cold
reset at strap 0. Then only the follow-on leg runs. Every ``FEAT_CTRL`` read
is a 64-bit frontdoor read with a sample of ``lcc_feat_ctrl_probe_o``. The golden is
``feat_ctrl_profile`` (``hw/sys/sep/doc/lifecycle_controller.adoc``, Per-LC-state
Feature Control Profile, row by row) on the model shadow values (the staged pair
OR-merged with the writes of the leaf).

  CHK-FEAT-CELL     legs A and C: ``FEAT_CTRL`` (register and probe) equals the
                    profile row of the (raw, demotion, SEC_DIS, strap) cell; the
                    ``LC_STATE`` shadow word holds ``{~r, r}``; ``sep_ras_o.lc_sigint_err`` = 0;
                    ``DEMOTE_1`` and ``DEMOTE_2`` read the RW1S golden in every state (``dem=``
                    is the readback); each output pair is complementary, differs from the
                    undemoted reference pair of the first leg A read when its register is
                    demoted and equals it otherwise. Leg C also grades a cell right after
                    its first cold reset (``after=reset``): both registers read 0.
                    Hook control at the leg A read: the strap port and the latched
                    ``secure_tm_o`` equal s (``CHK-HOOK FAIL`` otherwise).
                    In leg C the SEC_DIS cell is all ones with ``security_disable_o``
                    high and the cell after the mismatch is the demotion row with it
                    low. The RMA_CHIPLET SEC_DIS cell is logged ``ctl=1``. Each
                    leg C demotion cell also requires the write response OKAY and
                    both DEMOTE registers equal to the RW1S golden. Leg A also
                    grades the cell after the SEC_DIS demotion step
                    (``after=sdis_demote_mismatch``): the DEMOTE_1 row of the state.
  CHK-LC-STATE-PORT every CHK-FEAT-CELL cell: the ``lc_state_o`` port (tap
                    ``lc_state_probe_o``) equals the ``LC_STATE`` shadow byte and
                    ``{~r, r}`` (``doc/integrator/src/smu-sep.adoc``, ``lc_state_o``;
                    ``otp_fuse_controller.adoc``, LC_STATE encoding).
  CHK-SDIS-DEMOTE-SET leg A, every leaf: after a TOKEN_ZERO match raises
                    ``security_disable_o``, a write of ``demote`` (with a marker bit) to
                    ``DEMOTE_1`` reads back ``demote`` 1 and ``lock`` 0, and
                    ``FEAT_CTRL`` (register and probe) is all ones with
                    ``security_disable_o`` still high. ``demote`` sets while ``lock``
                    is 0 with no SEC_DIS term (``lifecycle_controller.adoc``,
                    Programming and Locking). A TOKEN_OTHER mismatch then clears
                    SEC_DIS and the next CHK-FEAT-CELL is the DEMOTE_1 row.
  CHK-DEMOTE-MARK   every ``DEMOTE_1``/``DEMOTE_2`` write that leaves the register
                    unchanged by the RW1S golden (a blocked ``demote``, a repeated
                    ``lock``, a ``zero`` write, ...) and the leg A SEC_DIS write carry
                    one ``rsvd`` bit k in [63:32] that no write since the cold reset
                    set (k drawn with ``SepSeededRng``); the 64-bit readback right
                    after the write has bit k set. ``rsvd`` is write-one-to-set with no write enable
                    (``sep_lifecycle_ctrl.rdl`` DEMOTE_1/2), so bit k proves that the
                    write reached the register.
  CHK-GATE-BOUND    every read with SEC_DIS 0: no bit outside the OR of the SEC_DIS 0
                    rows of the state (model shadows). A read whose mask is all ones
                    logs ``INFO-GATE-BOUND LOG ... graded=0``.
  CHK-DEMOTE-STEP   leg B: after each operation both demotion registers equal the
                    RW1S golden (``demote`` sets only while ``lock`` is 0; the
                    ``rsvd`` bits [63:2] are write-one-to-set with no lock and hold
                    every bit written since the cold reset,
                    ``sep_lifecycle_ctrl.rdl`` DEMOTE_1/2 ``rsvd``) and ``FEAT_CTRL``
                    equals the row of the cumulative demotion (``rsvd`` is "Not
                    used"). The random sequence draws ``rsvd.<k>`` writes of one
                    bit k in [63:2]. The model holds the marker bits of
                    CHK-DEMOTE-MARK. The write response is not graded.
                    A write of both bits while ``lock`` is 0 has no stated demote
                    golden: its demote bit is logged (``OBS-DEMOTE-LOCK-ONE-WRITE``,
                    every both-bits write) and the model takes the readback; the lock
                    bit and ``FEAT_CTRL`` stay graded.
  CHK-DEMOTE-ENC    leg B: each output pair is complementary, the pair of a demoted
                    register differs from the undemoted reference pair and an
                    undemoted register keeps it, and each lock probe equals the lock
                    bit of the register.
  CHK-DEMOTE-RESET  leg B: after each cold reset both registers read 0, and
                    ``FEAT_CTRL`` and both pairs equal the undemoted reference.
  CHK-DEMOTE-OTP    leg B: the ``LC_STATE`` shadow word equals the staged byte
                    ``{~r, r}`` (and keeps its leg B start value) after
                    every operation and every sense, no bank bit changes
                    (``otp_bank_probe_o``) and no program command reaches
                    ``efuse_shim_command_req_o`` from the first check cycle to the end
                    of the forced block. Control: a frontdoor program of a 0 bit of
                    the first ``SPARE8`` word shows one program command with its
                    address, a bank diff of that bit only, and the bit in the shadow
                    after the next sense.
  CHK-RMA-BYPASS    leg D: in RMA_SIP and RMA_CHIPLET both disable shadows read the
                    staged values and ``FEAT_CTRL`` equals the row.
  CHK-DIS-EARLIER   leg D: after a write of 0 to ``SIP_DIS`` and of ~S to ``SYS_DIS``,
                    ``SIP_DIS`` reads S and ``FEAT_CTRL`` AND S is 0; both writes
                    are answered OKAY (set-only, unlocked: a legal write); ``DEMOTE_1``
                    and ``DEMOTE_2`` read the RW1S golden after the PROD demotion writes
                    (``dem_regs=``).
  CHK-DIS-STEP      leg D: after each walk write the owner shadow equals the OR-merge
                    golden and ``FEAT_CTRL`` the row; after the cold reset both shadows
                    read the staged 0 and ``FEAT_CTRL`` the undemoted row.
  CHK-DTP-FEAT      leg E: ``FEAT_CTRL`` bit k is the inverse of ``SIP_DIS`` bit k for
                    SEP_DBG 0, CHIPLET_DBG 1, SEP_FUSE_DBG 2, SMC_FUSE_DBG 3, SIP_DBG 24.
  CHK-DTP-PORT      leg E: ``sep_fuse_dft_disable_o`` takes the value of the all-open
                    control cell exactly on the cells where SIP_DBG, CHIPLET_DBG,
                    SEP_DBG and SEP_FUSE_DBG are open, and the value of the all-closed
                    control cell elsewhere; ``smc_fuse_dft_disable_o`` the same with
                    SIP_DBG, CHIPLET_DBG and SMC_FUSE_DBG. No level is named. Control:
                    the two control cells differ on each port.
  CHK-BIND          leg C: the SHA-256 of 32 zero bytes equals the bench SEC_DIS digest.

Logged, not graded: ``OBS-LCC-WR-RESP`` gives the response of every DEMOTE write with
``applied=0`` for a write the RW1S golden leaves without effect (no document states the
response of a write the block does not apply); ``OBS-DEMOTE-PAIR-LEVEL`` gives, once
per register and leaf, the undemoted and the demoted ``lcc_demote_state_<n>_probe_o``
level (no document states which level means demoted).

``secure_tm_req_i`` is s in leg A and 0 in every follow-on leg. The leg E walk sets
the five named bits in the drawn order; the plan draws a permutation of the bits
0, 1, 2, 3 and 24 (SIP_DBG).
"""

from __future__ import annotations

import copy

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepEfuseBank, SepShimCmdMonitor, diff_is_exactly, diff_log
from env.sep_efuse_image import LC_FIELD_MASK, LC_WORD_IDX, lc_encode
from env.sep_efuse_plan import (
    CODE_MATCH,
    CODE_MISMATCH,
    DFT_GATE_BITS,
    DIS_GROUPS,
    LEG_B,
    LEG_C,
    LEG_D_EARLIER,
    LEG_D_RMA,
    LEG_D_WALK,
    LEG_E,
    PROGRAM_CTRL_ADDR,
    ST_PROD,
    ST_RMA_CHIPLET,
    ST_TEST_DEV,
    TOKEN_OTHER,
    TOKEN_ZERO,
    feat_ctrl_profile,
    field_word,
    lc_state_class,
    plan,
    program_ctrl_word,
    shadow_addr,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    StrapHold,
    bit,
    chk_bind,
    hook_fail,
    log_line,
    rst_pulse,
    sec_dis_go,
    shadow_word,
    wait_bit,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, SEP_LIFECYCLE_CTRL

TEST = "sep_lcc_feat_ctrl_state_matrix_rand_test"

FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
DEMOTE_ADDR = {1: SEP_LIFECYCLE_CTRL.addr("DEMOTE_1"), 2: SEP_LIFECYCLE_CTRL.addr("DEMOTE_2")}
DEMOTE_BIT = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "demote")
LOCK_BIT = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "lock")
DEMOTE_OP = {"demote": DEMOTE_BIT, "lock": LOCK_BIT, "zero": 0, "both": DEMOTE_BIT | LOCK_BIT}
OP_NAME = {"demote": "set_demote", "lock": "set_lock", "zero": "zero", "both": "set_both"}
RSVD_MASK = SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "rsvd")
RSVD_BITS = tuple(b for b in range(64) if (RSVD_MASK >> b) & 1)
# Marker bits sit in the upper 32-bit lane: the FCOV write class of a DEMOTE write
# (sep_lc_demote_lock_cg) reads the low lane, which then carries the op value alone.
MARK_BITS = tuple(b for b in RSVD_BITS if b >= 32)
# Salt of the marker-bit stream; the leaf plan draws nothing from it.
_MARK_SALT = 0x4D41_524B_4445_4D4F


def _op_value(op: str) -> int:
    """Write data of a leg-B op; ``rsvd.<k>`` sets bit k of the ``rsvd`` field."""
    if op.startswith("rsvd."):
        return 1 << int(op.split(".")[1])
    return DEMOTE_OP[op]


DIS_ADDR = {"SIP_DIS": shadow_addr("SIP_DIS"), "SYS_DIS": shadow_addr("SYS_DIS")}
PROGRAM_DONE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
M32 = 0xFFFF_FFFF
M64 = (1 << 64) - 1
ALL_ONES = M64
# Leg E disable bits, positions from the RDL LC_DISABLE fields (lifecycle_controller.adoc,
# Disable Vector Format and Debug and Test Port Path Gating).
SEP_DBG, CHIPLET_DBG, SEP_FUSE_DBG, SMC_FUSE_DBG, SIP_DBG = DFT_GATE_BITS
LEG_E_ORDER = (SEP_DBG, CHIPLET_DBG, SEP_FUSE_DBG, SMC_FUSE_DBG, SIP_DBG)
SEP_CASE_BITS = (SIP_DBG, CHIPLET_DBG, SEP_DBG, SEP_FUSE_DBG)
SMC_CASE_BITS = (SIP_DBG, CHIPLET_DBG, SMC_FUSE_DBG)
# Bounds (clocks or reads). A timeout fails the check the wait feeds.
SDIS_BOUND = 200
MATCH_READS = 400
PROGRAM_READS = 400
SENSE_BOUND = 20_000


def gate_mask(raw: int, sip: int, sys_: int) -> int:
    """OR of the SEC_DIS = 0 profile rows of the state for the given shadows."""
    out = 0
    for d1 in (0, 1):
        for d2 in (0, 1):
            out |= feat_ctrl_profile(raw, sip, sys_, demote_1=d1, demote_2=d2).value
    return out


def gate_bound_graded(p) -> bool:
    """True when some SEC_DIS 0 read of the leaf plan has a mask that is not all ones."""
    raw, leg = p.lc_raw, p.leg["leg"]
    masks = [gate_mask(raw, p.sip_dis, p.sys_dis)]
    if leg == LEG_D_WALK:
        sh = {"SIP_DIS": 0, "SYS_DIS": 0}
        for st in p.leg["walk"]:
            sh[st["owner"]] |= 1 << st["bit"]
            masks.append(gate_mask(raw, sh["SIP_DIS"], sh["SYS_DIS"]))
    elif leg == LEG_D_EARLIER:
        masks.append(gate_mask(raw, p.sip_dis, ~p.sip_dis & M64))
    return any(m != ALL_ONES for m in masks)


@pyuvm.test()
class sep_lcc_feat_ctrl_state_matrix_rand_test(StrapHold, sep_base_test):
    """FEAT_CTRL, demotion, disable-vector owners and DFT fuse ports follow the profile."""

    required_evidence = (
        "CHK-FEAT-CELL",
        "CHK-LC-STATE-PORT",
        "CHK-SDIS-DEMOTE-SET",
        "CHK-DEMOTE-MARK",
    )

    # -- samples and model ---------------------------------------------------

    def _pair(self, reg: int) -> int:
        return self.rd_known(getattr(cocotb.top, f"lcc_demote_state_{reg}_probe_o")) & 0x3

    def _pair_level(self, reg: int, pair: int) -> None:
        """Log the demoted and undemoted output pair level of ``reg`` once per leaf."""
        if reg in self.pair_level_logged or self.ref_pairs is None:
            return
        self.pair_level_logged.add(reg)
        self.chk.obs(
            "DEMOTE-PAIR-LEVEL",
            reg=reg,
            state=self.state,
            undemoted=f"0b{self.ref_pairs[reg]:02b}",
            demoted=f"0b{pair:02b}",
        )

    def _golden(self):
        return feat_ctrl_profile(
            self.raw,
            self.sip_m,
            self.sys_m,
            demote_1=self.dem[1][0],
            demote_2=self.dem[2][0],
            sec_dis=self.sdis,
        )

    def _dem_value(self, reg: int) -> int:
        d, lk = self.dem[reg]
        return (DEMOTE_BIT if d else 0) | (LOCK_BIT if lk else 0) | self.rsvd[reg]

    def _vec(self) -> int:
        return self.dem[1][0] << 3 | self.dem[1][1] << 2 | self.dem[2][0] << 1 | self.dem[2][1]

    def _apply_op(self, reg: int, op: str) -> None:
        """RW1S golden (sep_lifecycle_ctrl.adoc DEMOTE_1/2; lifecycle_controller.adoc,
        Programming and Locking): demote sets only while lock is 0, lock always sets,
        a zero write changes nothing. A write of both bits sets lock; its demote bit is
        stated only when lock is already 1 (no change). With lock 0 the demote bit is
        open: ``_cycle`` takes it from the readback."""
        self.open_demote = None
        if op.startswith("rsvd."):
            self.rsvd[reg] |= _op_value(op) & RSVD_MASK
        elif op == "demote" and not self.dem[reg][1]:
            self.dem[reg][0] = 1
        elif op == "lock":
            self.dem[reg][1] = 1
        elif op == "both":
            if not self.dem[reg][1]:
                self.open_demote = reg
            self.dem[reg][1] = 1

    async def _feat(self) -> tuple[int, int]:
        reg = await self.fd.rd64(FEAT_CTRL)
        probe = self.rd_known(cocotb.top.lcc_feat_ctrl_probe_o)
        self._gate_bound(reg)
        return reg, probe

    def _gate_bound(self, feat: int) -> None:
        if self.sdis:
            return
        mask = gate_mask(self.raw, self.sip_m, self.sys_m)
        if mask == ALL_ONES:
            log_line(
                self.logger,
                "INFO-GATE-BOUND",
                self.seed,
                state=self.state,
                mask="all_ones",
                graded=0,
            )
            return
        extra = feat & ~mask & M64
        self.chk.ok(
            "GATE-BOUND",
            extra == 0,
            state=self.state,
            mask=f"0x{mask:016x}",
            feat=f"0x{feat:016x}",
            extra_bits=f"0x{extra:x}",
        )

    async def _cold_reset(self, *, strap: int | None = None) -> None:
        """Cold reset with clocks running; the strap changes only while rst_ni is low."""
        await rst_pulse(self, strap=strap)
        await self.wait_fuse_sense(max_cycles=SENSE_BOUND)
        self.cfg.reset_done.set()
        self.sip_m, self.sys_m = self.p.sip_dis, self.p.sys_dis
        self.dem = {1: [0, 0], 2: [0, 0]}
        self.open_demote: int | None = None
        self.rsvd = {1: 0, 2: 0}
        self.sdis = 0

    async def _feat_cell(
        self,
        leg: str,
        reg: int,
        probe: int,
        *,
        sdis_port,
        ctl: int = 0,
        step_ok: bool = True,
        **extra,
    ) -> None:
        row = self._golden()
        lcw = shadow_word(self, LC_WORD_IDX)
        sigint = bit(self, "lcc_sigint_err_probe_o")
        sdis_ok = sdis_port == "na" or sdis_port == self.sdis
        got = {r: await self.fd.rd64(DEMOTE_ADDR[r]) for r in (1, 2)}
        exp = {r: self._dem_value(r) for r in (1, 2)}
        pairs = {r: self._pair(r) for r in (1, 2)}
        port = self.rd_known(cocotb.top.lc_state_probe_o) & LC_FIELD_MASK
        if self.ref_pairs is None and exp[1] == exp[2] == 0:
            self.ref_pairs = dict(pairs)
        for r in (1, 2):
            if exp[r] & DEMOTE_BIT:
                self._pair_level(r, pairs[r])
        self.chk.ok(
            "LC-STATE-PORT",
            port == lcw & LC_FIELD_MASK == lc_encode(self.raw),
            leg=leg,
            raw=f"0x{self.raw:x}",
            lc_state_o=f"0x{port:02x}",
            lc_shadow=f"0x{lcw & LC_FIELD_MASK:02x}",
            exp=f"0x{lc_encode(self.raw):02x}",
            secdis=self.sdis,
            after=extra.get("after", "na"),
        )
        pairs_ok = self.ref_pairs is not None and all(
            pairs[r] in (0b01, 0b10)
            and (pairs[r] != self.ref_pairs[r]) == bool(exp[r] & DEMOTE_BIT)
            for r in (1, 2)
        )
        self.chk.ok(
            "FEAT-CELL",
            reg == row.value
            and probe == row.value
            and lcw & LC_FIELD_MASK == lc_encode(self.raw)
            and sigint == 0
            and sdis_ok
            and got == exp
            and pairs_ok
            and step_ok,
            leg=leg,
            raw=f"0x{self.raw:x}",
            state=self.state,
            dem=f"{got[1] & DEMOTE_BIT}{got[2] & DEMOTE_BIT}",
            dem_regs=f"0x{got[1]:x}/0x{got[2]:x}",
            dem_exp=f"0x{exp[1]:x}/0x{exp[2]:x}",
            pairs=f"0b{pairs[1]:02b}/0b{pairs[2]:02b}",
            pairs_ref=(
                f"0b{self.ref_pairs[1]:02b}/0b{self.ref_pairs[2]:02b}" if self.ref_pairs else "na"
            ),
            secdis=self.sdis,
            stm=self._strap,
            sip=f"0x{self.sip_m:016x}",
            sys=f"0x{self.sys_m:016x}",
            exp=f"0x{row.value:016x}",
            got=f"0x{reg:016x}",
            probe=f"0x{probe:016x}",
            lc_shadow=f"0x{lcw & LC_FIELD_MASK:02x}",
            rsvd=f"0x{lcw & ~LC_FIELD_MASK & M32:x}",
            sigint=sigint,
            row=row.row,
            sdis_port=sdis_port,
            ctl=ctl,
            src=row.source,
            **extra,
        )

    # -- leg A ---------------------------------------------------------------

    def _strap_hook(self) -> int:
        """Hook control of the strap drive: the DUT port ``secure_tm_req_i`` (bench net
        ``test_en_strap_i``) and the latched ``secure_tm_o`` both equal s; a miss ends the
        leaf (``CHK-HOOK FAIL``)."""
        port = bit(self, "test_en_strap_i")
        latched = bit(self, "secure_tm_o")
        if port != self._strap or latched != self._strap:
            hook_fail(
                self.chk,
                reason="strap",
                stm=self._strap,
                strap_port=port,
                secure_tm_o=latched,
            )
        self.chk.ctrl("HOOK", True, reason="strap", stm=self._strap, strap_port=port)
        return port

    async def _leg_a(self) -> None:
        reg, probe = await self._feat()
        self._strap_hook()
        await self._feat_cell("a", reg, probe, sdis_port=bit(self, "lcc_security_disable_probe_o"))
        await self._leg_a_sdis_demote()
        close_graded_window(self.logger)
        await self._cold_reset(strap=0)
        open_graded_window(TEST, self.logger)

    async def _leg_a_sdis_demote(self) -> None:
        """DEMOTE_1 write while SEC_DIS is 1, then the cell after the mismatch.

        ``demote`` sets while ``lock`` is 0 with no SEC_DIS term
        (``lifecycle_controller.adoc``, Programming and Locking), and SEC_DIS forces
        ``FEAT_CTRL`` all ones (Overrides and Final Gates). After the TOKEN_OTHER
        mismatch the cell is the DEMOTE_1 row of the state.
        """
        code, reads = await sec_dis_go(self.fd, TOKEN_ZERO, CODE_MATCH, max_reads=MATCH_READS)
        rose = await wait_bit(self, "lcc_security_disable_probe_o", 1, SDIS_BOUND)
        if code != CODE_MATCH or rose is None:
            hook_fail(
                self.chk,
                reason="security_disable_o did not rise on the leg A TOKEN_ZERO match",
                code=f"0x{(code or 0):02x}",
                reads=reads,
            )
        self.sdis = 1
        sdis_wr = bit(self, "lcc_security_disable_probe_o")
        got = await self._write_demote(1, "demote", mark=True)
        reg, probe = await self._feat()
        sdis_rd = bit(self, "lcc_security_disable_probe_o")
        row = self._golden()
        self.chk.ok(
            "SDIS-DEMOTE-SET",
            sdis_wr == 1
            and sdis_rd == 1
            and got is not None
            and got & (DEMOTE_BIT | LOCK_BIT) == DEMOTE_BIT
            and reg == row.value == ALL_ONES
            and probe == row.value,
            state=self.state,
            stm=self._strap,
            sdis_port=f"{sdis_wr}/{sdis_rd}",
            demote1_rd=f"0x{(got or 0):016x}",
            demote=int(bool((got or 0) & DEMOTE_BIT)),
            lock=int(bool((got or 0) & LOCK_BIT)),
            feat=f"0x{reg:016x}",
            probe=f"0x{probe:016x}",
            exp=f"0x{row.value:016x}",
            row=row.row,
        )
        code, reads = await sec_dis_go(self.fd, TOKEN_OTHER, CODE_MISMATCH, max_reads=MATCH_READS)
        fell = await wait_bit(self, "lcc_security_disable_probe_o", 0, SDIS_BOUND)
        self.sdis = 0
        reg, probe = await self._feat()
        await self._feat_cell(
            "a",
            reg,
            probe,
            sdis_port=bit(self, "lcc_security_disable_probe_o"),
            step_ok=code == CODE_MISMATCH and fell is not None,
            after="sdis_demote_mismatch",
            code_mismatch=f"0x{(code or 0):02x}",
            mismatch_reads=reads,
        )

    # -- leg B ---------------------------------------------------------------

    async def _cycle(self, step: str, reg: int | None, op: str | None) -> None:
        r1 = await self.fd.rd64(DEMOTE_ADDR[1])
        r2 = await self.fd.rd64(DEMOTE_ADDR[2])
        feat, probe = await self._feat()
        pairs = {1: self._pair(1), 2: self._pair(2)}
        locks = {
            1: bit(self, "lcc_demote_lock_1_probe_o"),
            2: bit(self, "lcc_demote_lock_2_probe_o"),
        }
        lcw = shadow_word(self, LC_WORD_IDX)
        diff = self.bank.diff_since(self.snap)
        progs = self.shim.programs_since(self.otp_mark)
        got = {1: r1, 2: r2}
        ungraded = {1: 0, 2: 0}
        if op == "both":
            self.chk.obs(
                "DEMOTE-LOCK-ONE-WRITE",
                reg=reg,
                pre_lock=int(self.open_demote is None),
                demote_rd=int(bool(got[reg] & DEMOTE_BIT)),
                lock_rd=int(bool(got[reg] & LOCK_BIT)),
                feat=f"0x{feat:016x}",
                probe=f"0x{probe:016x}",
            )
        if self.open_demote is not None:
            # The demote bit of a both-bits write with lock 0 has no stated golden: the
            # model takes the readback, and the lock bit and FEAT_CTRL stay graded.
            self.dem[self.open_demote][0] = int(bool(got[self.open_demote] & DEMOTE_BIT))
            ungraded[self.open_demote] = DEMOTE_BIT
            self.open_demote = None
        row = self._golden()
        exp = {1: self._dem_value(1), 2: self._dem_value(2)}
        self.chk.ok(
            "DEMOTE-STEP",
            all((got[r] ^ exp[r]) & ~ungraded[r] == 0 for r in (1, 2))
            and feat == row.value
            and probe == row.value,
            step=step,
            reg=reg if reg is not None else "na",
            op=OP_NAME.get(op, op) if op else "none",
            reg_exp=f"0x{exp[reg or 1]:x}",
            reg_got=f"0x{got[reg or 1]:x}",
            other_exp=f"0x{exp[3 - (reg or 1)]:x}",
            other_got=f"0x{got[3 - (reg or 1)]:x}",
            feat_exp=f"0x{row.value:016x}",
            feat_got=f"0x{feat:016x}",
            feat_probe=f"0x{probe:016x}",
            row=row.row,
        )
        for r in (1, 2):
            demoted = bool(got[r] & DEMOTE_BIT)
            if demoted:
                self._pair_level(r, pairs[r])
            comp = pairs[r] in (0b01, 0b10)
            distinct = pairs[r] != self.ref_pairs[r]
            self.chk.ok(
                "DEMOTE-ENC",
                comp
                and (distinct if demoted else not distinct)
                and locks[r] == int(bool(got[r] & LOCK_BIT)),
                step=step,
                reg=r,
                undemoted=f"0b{self.ref_pairs[r]:02b}",
                demoted=f"0b{pairs[r]:02b}" if demoted else "na",
                pair=f"0b{pairs[r]:02b}",
                complementary=comp,
                distinct=distinct,
                lock_probe=locks[r],
                lock_reg=int(bool(got[r] & LOCK_BIT)),
            )
        self._otp_note(step, lcw, diff, progs)

    def _otp_note(self, step: str, lcw: int, diff, progs) -> None:
        bad = (lcw & LC_FIELD_MASK) != self.staged_lc or lcw != self.ref_lcw or diff or progs
        self.otp_cycles += 1
        if bad:
            self.otp_bad.append(f"{step}:lc=0x{lcw:x},diff={diff_log(diff)},progs={len(progs)}")

    async def _write_demote(self, reg: int, op: str, *, mark: bool = False) -> int | None:
        """DEMOTE write; a write that leaves the register unchanged carries a marker.

        The marker is one ``rsvd`` bit k that no write since the cold reset set; ``rsvd``
        is write-one-to-set with no lock, so the readback of bit k proves that the
        write reached the register (``CHK-DEMOTE-MARK``). ``mark`` adds the marker to a
        write that changes the register too. Returns that readback, or None for a write
        with no marker. The response is logged, not graded (``OBS-LCC-WR-RESP``).
        """
        before = self._dem_value(reg)
        self._apply_op(reg, op)
        applied = self._dem_value(reg) != before
        value = _op_value(op)
        k = None
        if mark or not applied:
            free = [b for b in MARK_BITS if not (self.rsvd[reg] >> b) & 1]
            if not free:
                hook_fail(self.chk, reason="no free rsvd marker bit", reg=reg, op=op)
            k = self.mark_rng.choice(free)
            value = value | (1 << k)
            self.rsvd[reg] |= 1 << k
        self._wr_resp = await self.fd.wr_graded_by_readback(DEMOTE_ADDR[reg], value, length=8)
        self.chk.obs(
            "LCC-WR-RESP",
            reg=f"DEMOTE_{reg}",
            op=OP_NAME.get(op, op),
            applied=applied,
            secdis=self.sdis,
            wdata=f"0x{value:016x}",
            resp=self._wr_resp,
        )
        if k is None:
            return None
        got = await self.fd.rd64(DEMOTE_ADDR[reg])
        self.chk.ok(
            "DEMOTE-MARK",
            (got >> k) & 1 == 1,
            reg=reg,
            op=OP_NAME.get(op, op),
            applied=applied,
            mark_bit=k,
            got=(got >> k) & 1,
            readback=f"0x{got:016x}",
        )
        return got

    async def _reset_check(self, stage: str) -> None:
        vec = self._vec()
        await self._cold_reset()
        r1 = await self.fd.rd64(DEMOTE_ADDR[1])
        r2 = await self.fd.rd64(DEMOTE_ADDR[2])
        feat, probe = await self._feat()
        pairs = (self._pair(1), self._pair(2))
        lcw = shadow_word(self, LC_WORD_IDX)
        self.otp_after_sense.append(lcw)
        self._otp_note(
            f"reset_{stage}",
            lcw,
            self.bank.diff_since(self.snap),
            self.shim.programs_since(self.otp_mark),
        )
        self.chk.ok(
            "DEMOTE-RESET",
            vec != 0
            and r1 == 0
            and r2 == 0
            and feat == self.ref_feat
            and probe == self.ref_feat
            and pairs == (self.ref_pairs[1], self.ref_pairs[2]),
            stage=stage,
            vec_before=f"0x{vec:x}",
            regs=f"0x{r1 | r2:x}",
            feat=f"0x{feat:016x}",
            feat_ref=f"0x{self.ref_feat:016x}",
            pairs_ref=int(pairs == (self.ref_pairs[1], self.ref_pairs[2])),
        )

    async def _leg_b(self) -> None:
        leg = self.p.leg
        self.bank = SepEfuseBank()
        self.snap = self.bank.snapshot()
        self.shim = SepShimCmdMonitor().start()
        await ClockCycles(cocotb.top.clk_i, 2)
        self.otp_mark = self.shim.mark()
        self.otp_bad: list[str] = []
        self.otp_cycles = 0
        self.otp_after_sense: list[int] = []
        self.ref_pairs = {1: self._pair(1), 2: self._pair(2)}
        self.ref_lcw = shadow_word(self, LC_WORD_IDX)
        self.staged_lc = lc_encode(self.raw) & LC_FIELD_MASK
        self.ref_feat = self._golden().value
        if self.state in (ST_TEST_DEV, ST_PROD):
            base = feat_ctrl_profile(self.raw, self.sip_m, self.sys_m).value
            d1 = feat_ctrl_profile(self.raw, self.sip_m, self.sys_m, demote_1=1).value
            d2 = feat_ctrl_profile(self.raw, self.sip_m, self.sys_m, demote_2=1).value
            self.chk.ctrl(
                "DEMOTE-STEP-CONTRAST",
                base != d1 and base != d2,
                state=self.state,
                undemoted=f"0x{base:016x}",
                demote_1=f"0x{d1:016x}",
                demote_2=f"0x{d2:016x}",
            )
        self.logger.info(
            "INFO-LEG-B ref pairs=0b%s/0b%s lc_shadow=0x%x feat=0x%016x",
            format(self.ref_pairs[1], "02b"),
            format(self.ref_pairs[2], "02b"),
            self.ref_lcw,
            self.ref_feat,
        )

        # Cell walk: 00, 10, 11, reset; 01, reset.
        await self._cycle("cell00", None, None)
        await self._write_demote(1, "demote")
        await self._cycle("cell10", 1, "demote")
        await self._write_demote(2, "demote")
        await self._cycle("cell11", 2, "demote")
        self.logger.info("INFO-LEG-B vector before reset=0x%x (cells)", self._vec())
        await self._reset_check("cell")
        await self._write_demote(2, "demote")
        await self._cycle("cell01", 2, "demote")
        self.logger.info("INFO-LEG-B vector before reset=0x%x (cell 01)", self._vec())
        await self._reset_check("cell")

        # Reset vector v: (demote 1, lock 1, demote 2, lock 2) as bits 3..0.
        v = leg["reset_vector"]
        for reg, (dbit, lbit) in ((1, (3, 2)), (2, (1, 0))):
            if (v >> dbit) & 1:
                await self._write_demote(reg, "demote")
                await self._cycle(f"vec_d{reg}", reg, "demote")
            if (v >> lbit) & 1:
                await self._write_demote(reg, "lock")
                await self._cycle(f"vec_l{reg}", reg, "lock")
        self.logger.info("INFO-LEG-B vector before reset=0x%x (v=0x%x)", self._vec(), v)
        await self._reset_check("vec")

        # Random sequence.
        for k, (op, reg) in enumerate(leg["ops"]):
            await self._write_demote(reg, op)
            await self._cycle(f"rand{k}", reg, op)
        self.logger.info("INFO-LEG-B vector before reset=0x%x (random)", self._vec())
        await self._reset_check("rand")

        # Forced block: lock then demote on A, demote then lock on B.
        a = leg["reg_a"]
        b = 3 - a
        for k, (reg, op) in enumerate(
            (
                (a, "lock"),
                (a, "demote"),
                (a, "zero"),
                (a, "lock"),
                (b, "demote"),
                (b, "zero"),
                (b, "lock"),
                (b, "demote"),
                (b, "zero"),
            )
        ):
            await self._write_demote(reg, op)
            await self._cycle(f"forced{k}", reg, op)
        self.logger.info("INFO-LEG-B vector before reset=0x%x (forced)", self._vec())
        await self._reset_check("forced")

        # Control program: one 0 bit of the first SPARE8 word.
        close_graded_window(self.logger)
        ctl = leg["ctl_bit"]
        w = field_word("SPARE8")
        staged = self.p.image.words[w]
        mark = self.shim.mark()
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(ctl["addr"], go=0))
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(ctl["addr"], go=1))
        done = None
        for n in range(1, PROGRAM_READS + 1):
            if await self.fd.rd(PROGRAM_CTRL_ADDR) & PROGRAM_DONE:
                done = n
                break
        progs = self.shim.programs_since(mark)
        await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
        img = copy.deepcopy(self.p.image)
        img.words[w] |= 1 << ctl["bit"]
        self.write_efuse_image(img)
        await self._cold_reset()
        spare8 = shadow_word(self, w)
        lcw = shadow_word(self, LC_WORD_IDX)
        self.otp_after_sense.append(lcw)
        diff = self.bank.diff_since(self.snap)
        await self.shim.stop()
        ctl_cmd = int(len(progs) == 1 and progs[0].address == ctl["addr"])
        self.chk.ok(
            "DEMOTE-OTP",
            not self.otp_bad
            and self.otp_cycles > 0
            and (self.ref_lcw & LC_FIELD_MASK) == self.staged_lc
            and all(
                (x & LC_FIELD_MASK) == self.staged_lc and x == self.ref_lcw
                for x in self.otp_after_sense
            )
            and done is not None
            and spare8 == staged | (1 << ctl["bit"])
            and ctl_cmd == 1
            and diff_is_exactly(diff, ctl["addr"]),
            lc_shadow=f"0x{self.ref_lcw:x}",
            ref=f"0x{self.staged_lc:x}",
            lc_shadow_after_sense=f"0x{lcw:x}",
            cycles=self.otp_cycles,
            violations=len(self.otp_bad),
            first_violation=self.otp_bad[0] if self.otp_bad else "none",
            ctl_bit=ctl["bit"],
            ctl_spare8_staged=f"0x{staged:08x}",
            ctl_spare8=f"0x{spare8:08x}",
            ctl_cmd=ctl_cmd,
            ctl_cmds=len(progs),
            ctl_done_reads=done if done is not None else "timeout",
            ctl_diff=diff_log(diff),
        )

    # -- leg C ---------------------------------------------------------------

    async def _sdis_cell(self) -> None:
        ctl = int(self.state == ST_RMA_CHIPLET)
        code, reads = await sec_dis_go(self.fd, TOKEN_ZERO, CODE_MATCH, max_reads=MATCH_READS)
        rose = await wait_bit(self, "lcc_security_disable_probe_o", 1, SDIS_BOUND)
        if not self.sdis_seen and (code != CODE_MATCH or rose is None):
            hook_fail(
                self.chk,
                reason="security_disable_o did not rise on the first TOKEN_ZERO match",
                code=f"0x{(code or 0):02x}",
                reads=reads,
            )
        self.sdis_seen = True
        self.sdis = 1
        reg, probe = await self._feat()
        await self._feat_cell(
            "c",
            reg,
            probe,
            sdis_port=bit(self, "lcc_security_disable_probe_o"),
            ctl=ctl,
            step_ok=code == CODE_MATCH and rose is not None,
            after="match",
            code_match=f"0x{(code or 0):02x}",
            match_reads=reads,
        )
        code, reads = await sec_dis_go(self.fd, TOKEN_OTHER, CODE_MISMATCH, max_reads=MATCH_READS)
        fell = await wait_bit(self, "lcc_security_disable_probe_o", 0, SDIS_BOUND)
        self.sdis = 0
        reg, probe = await self._feat()
        await self._feat_cell(
            "c",
            reg,
            probe,
            sdis_port=bit(self, "lcc_security_disable_probe_o"),
            step_ok=code == CODE_MISMATCH and fell is not None,
            after="mismatch",
            code_mismatch=f"0x{(code or 0):02x}",
            mismatch_reads=reads,
        )

    async def _demote_cell(self, reg_n: int) -> None:
        """Leg C demote write, then a FEAT_CTRL cell that also grades the write.

        The write is answered OKAY and DEMOTE_1/2 read back the RW1S golden, so a lost
        write fails also in a state whose profile row does not depend on demotion.
        """
        await self._write_demote(reg_n, "demote")
        got = {r: await self.fd.rd64(DEMOTE_ADDR[r]) for r in (1, 2)}
        exp = {r: self._dem_value(r) for r in (1, 2)}
        reg, probe = await self._feat()
        await self._feat_cell(
            "c",
            reg,
            probe,
            sdis_port="na",
            step_ok=self._wr_resp == 0 and got == exp,
            wr_resp=self._wr_resp,
            demote1_exp=f"0x{exp[1]:x}",
            demote1_rd=f"0x{got[1]:x}",
            demote2_exp=f"0x{exp[2]:x}",
            demote2_rd=f"0x{got[2]:x}",
        )

    async def _leg_c(self) -> None:
        await chk_bind(self.chk)
        self.sdis_seen = False
        reg, probe = await self._feat()
        await self._feat_cell("c", reg, probe, sdis_port="na")
        await self._sdis_cell()
        await self._demote_cell(1)
        await self._sdis_cell()
        await self._demote_cell(2)
        await self._sdis_cell()
        await self._cold_reset()
        reg, probe = await self._feat()
        await self._feat_cell("c", reg, probe, sdis_port="na", after="reset")
        await self._demote_cell(2)
        await self._sdis_cell()
        close_graded_window(self.logger)
        await self._cold_reset()

    # -- leg D ---------------------------------------------------------------

    async def _rd_dis(self) -> tuple[int, int]:
        return await self.fd.rd64(DIS_ADDR["SIP_DIS"]), await self.fd.rd64(DIS_ADDR["SYS_DIS"])

    async def _leg_d_rma(self) -> None:
        sip, sys_ = await self._rd_dis()
        reg, probe = await self._feat()
        row = self._golden()
        groups_ok = all(
            (self.p.sip_dis | self.p.sys_dis) & m and self.p.sys_dis & ~self.p.sip_dis & m
            for _g, m in DIS_GROUPS
        )
        self.chk.ctrl(
            "RMA-BYPASS-PAIR",
            groups_ok,
            sip=f"0x{self.p.sip_dis:016x}",
            sys=f"0x{self.p.sys_dis:016x}",
        )
        self.chk.ok(
            "RMA-BYPASS",
            sip == self.p.sip_dis
            and sys_ == self.p.sys_dis
            and reg == row.value
            and probe == row.value,
            state=self.state,
            shadow_sip=f"0x{sip:016x}",
            shadow_sys=f"0x{sys_:016x}",
            staged_equal=int(sip == self.p.sip_dis and sys_ == self.p.sys_dis),
            feat=f"0x{reg:016x}",
            feat_exp=f"0x{row.value:016x}",
            probe=f"0x{probe:016x}",
            row=row.row,
        )

    async def _leg_d_earlier(self) -> None:
        s = self.p.sip_dis
        if self.state == ST_PROD:
            await self._write_demote(1, "demote")
            await self._write_demote(2, "demote")
        dem = {r: await self.fd.rd64(DEMOTE_ADDR[r]) for r in (1, 2)}
        dem_exp = {r: self._dem_value(r) for r in (1, 2)}
        reg0, _ = await self._feat()
        self.logger.info("INFO-LEG-D earlier owner start FEAT_CTRL=0x%016x", reg0)
        not_s = ~s & M64
        resp_sys = await self.fd.wr_graded_by_readback(DIS_ADDR["SYS_DIS"], not_s, length=8)
        self.sys_m |= not_s
        resp_sip = await self.fd.wr_graded_by_readback(DIS_ADDR["SIP_DIS"], 0, length=8)
        sip, sys_ = await self._rd_dis()
        reg, probe = await self._feat()
        row = self._golden()
        self.chk.ok(
            "DIS-EARLIER",
            s != 0
            and sip == s
            and sys_ == self.sys_m
            and dem == dem_exp
            and reg & s == 0
            and reg == row.value
            and probe == row.value
            and resp_sys == 0
            and resp_sip == 0,
            state=self.state,
            S=f"0x{s:016x}",
            sip_got=f"0x{sip:016x}",
            sys=f"0x{sys_:016x}",
            sys_exp=f"0x{self.sys_m:016x}",
            feat=f"0x{reg:016x}",
            feat_exp=f"0x{row.value:016x}",
            feat_and_S=f"0x{reg & s:x}",
            dem_regs=f"0x{dem[1]:x}/0x{dem[2]:x}",
            dem_exp=f"0x{dem_exp[1]:x}/0x{dem_exp[2]:x}",
            resp_sys_wr=resp_sys,
            resp_sip_wr=resp_sip,
        )

    async def _write_dis(self, owner: str, value: int, width: int) -> None:
        addr = DIS_ADDR[owner]
        if width == 64:
            await self.fd.wr64(addr, value)
        else:
            await self.fd.wr(addr, value & M32)
            await self.fd.wr(addr + 4, value >> 32)

    async def _leg_d_walk(self) -> None:
        if self.state == ST_PROD:
            await self._write_demote(1, "demote")
            await self._write_demote(2, "demote")
        reg, probe = await self._feat()
        row = self._golden()
        self.chk.ctrl(
            "DIS-START",
            reg == row.value and probe == row.value,
            state=self.state,
            feat=f"0x{reg:016x}",
            feat_exp=f"0x{row.value:016x}",
        )
        for k, st in enumerate(self.p.leg["walk"]):
            b, owner, width = st["bit"], st["owner"], st["width"]
            await self._write_dis(owner, 1 << b, width)
            if owner == "SIP_DIS":
                self.sip_m |= 1 << b
            else:
                self.sys_m |= 1 << b
            got = await self.fd.rd64(DIS_ADDR[owner])
            reg, probe = await self._feat()
            exp_sh = self.sip_m if owner == "SIP_DIS" else self.sys_m
            row = self._golden()
            self.chk.ok(
                "DIS-STEP",
                got == exp_sh and reg == row.value and probe == row.value,
                state=self.state,
                step=k,
                bit=b,
                owner="SIP" if owner == "SIP_DIS" else "SYS",
                width=width,
                wr=f"0x{1 << b:016x}",
                shadow_exp=f"0x{exp_sh:016x}",
                shadow_got=f"0x{got:016x}",
                feat_exp=f"0x{row.value:016x}",
                feat_got=f"0x{reg:016x}",
                feat_probe=f"0x{probe:016x}",
                row=row.row,
            )
        await self._cold_reset()
        sip, sys_ = await self._rd_dis()
        reg, probe = await self._feat()
        row = self._golden()
        self.chk.ok(
            "DIS-STEP",
            sip == 0 and sys_ == 0 and reg == row.value and probe == row.value,
            state=self.state,
            step="reset",
            sip=f"0x{sip:x}",
            sys=f"0x{sys_:x}",
            feat_exp=f"0x{row.value:016x}",
            feat_got=f"0x{reg:016x}",
        )

    # -- leg E ---------------------------------------------------------------

    async def _leg_e_cell(self) -> dict:
        sip = await self.fd.rd64(DIS_ADDR["SIP_DIS"])
        reg, _probe = await self._feat()
        return {
            "sip_exp": self.sip_m,
            "sip": sip,
            "feat": reg,
            "sep": bit(self, "sep_fuse_dft_disable_o"),
            "smc": bit(self, "smc_fuse_dft_disable_o"),
        }

    async def _leg_e(self) -> None:
        cells = [await self._leg_e_cell()]
        for st in self.p.leg["leg_e"]:
            b = st["bit"]
            await self._write_dis("SIP_DIS", 1 << b, st["width"])
            self.sip_m |= 1 << b
            cells.append(await self._leg_e_cell())
        ctl_open, ctl_closed = cells[0], cells[-1]
        ctl_ok = self.chk.ctrl(
            "DTP-PORT-CLASSES",
            ctl_open["sep"] != ctl_closed["sep"] and ctl_open["smc"] != ctl_closed["smc"],
            ctl_open=f"{ctl_open['sep']},{ctl_open['smc']}",
            ctl_closed=f"{ctl_closed['sep']},{ctl_closed['smc']}",
        )
        self.chk.obs(
            "DTP-PORT-LEVEL",
            sep_open=ctl_open["sep"],
            sep_closed=ctl_closed["sep"],
            smc_open=ctl_open["smc"],
            smc_closed=ctl_closed["smc"],
        )
        for c in cells:
            bits = "".join(str((c["sip"] >> b) & 1) for b in LEG_E_ORDER)
            fbits = "".join(str((c["feat"] >> b) & 1) for b in LEG_E_ORDER)
            inv = all(((c["feat"] >> b) & 1) == 1 - ((c["sip"] >> b) & 1) for b in LEG_E_ORDER)
            self.chk.ok(
                "DTP-FEAT",
                inv and c["sip"] == c["sip_exp"],
                bits=f"0b{bits}",
                feat_bits=f"0b{fbits}",
                feat=f"0x{c['feat']:016x}",
                sip=f"0x{c['sip']:016x}",
                sip_exp=f"0x{c['sip_exp']:016x}",
            )
            sep_open = all(not (c["sip"] >> b) & 1 for b in SEP_CASE_BITS)
            smc_open = all(not (c["sip"] >> b) & 1 for b in SMC_CASE_BITS)
            sep_want = ctl_open["sep"] if sep_open else ctl_closed["sep"]
            smc_want = ctl_open["smc"] if smc_open else ctl_closed["smc"]
            self.chk.ok(
                "DTP-PORT",
                ctl_ok and c["sep"] == sep_want and c["smc"] == smc_want,
                bits=f"0b{bits}",
                sep_port=c["sep"],
                sep_class="open_case" if sep_open else "other",
                smc_port=c["smc"],
                smc_class="open_case" if smc_open else "other",
            )

    # -- scenario ------------------------------------------------------------

    async def run_scenario(self) -> None:
        self.seed = seed = self.random_seed()
        p = plan(TEST, seed)
        self.p = p
        self.raw = p.lc_raw
        self.state = lc_state_class(self.raw)
        leg = p.leg["leg"]
        self._strap = p.leg["strap"]
        for line in p.log_lines(leg=leg, raw=f"0x{self.raw:x}", stm=self._strap):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        extra = {
            LEG_B: ("CHK-DEMOTE-STEP", "CHK-DEMOTE-ENC", "CHK-DEMOTE-OTP", "CHK-DEMOTE-RESET"),
            LEG_C: ("CHK-BIND",),
            LEG_D_RMA: ("CHK-RMA-BYPASS",),
            LEG_D_EARLIER: ("CHK-DIS-EARLIER",),
            LEG_D_WALK: ("CHK-DIS-STEP",),
            LEG_E: ("CHK-DTP-FEAT", "CHK-DTP-PORT"),
        }[leg]
        gate = ("CHK-GATE-BOUND",) if gate_bound_graded(p) else ()
        self.required_evidence = (*self.required_evidence, *gate, *extra)
        self.logger.info(
            "INFO-EVIDENCE-PLAN seed=%d required=%s", seed, ",".join(self.required_evidence)
        )
        self.fd = SepEfuseFd(self)
        self.sip_m, self.sys_m = p.sip_dis, p.sys_dis
        self.dem = {1: [0, 0], 2: [0, 0]}
        self.open_demote: int | None = None
        self.rsvd = {1: 0, 2: 0}
        self.sdis = 0
        self.ref_pairs = None
        self.pair_level_logged: set[int] = set()
        self.mark_rng = SepSeededRng(seed ^ _MARK_SALT)

        self.write_efuse_image(p.image)
        open_graded_window(TEST, self.logger)
        await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        await self._leg_a()
        if leg == LEG_B:
            await self._leg_b()
        elif leg == LEG_C:
            await self._leg_c()
        elif leg == LEG_D_RMA:
            await self._leg_d_rma()
        elif leg == LEG_D_EARLIER:
            await self._leg_d_earlier()
        elif leg == LEG_D_WALK:
            await self._leg_d_walk()
        else:
            await self._leg_e()
        close_graded_window(self.logger)
        self.chk.finish(f" leg={leg} raw=0x{self.raw:x}")
