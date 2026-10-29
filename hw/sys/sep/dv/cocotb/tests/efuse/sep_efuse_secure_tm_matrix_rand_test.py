# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure test mode: programs blocked, secret fields masked at the shadow output, JTAG writes blocked.

RAND-REP. Run mode no_cpu (``lsu_stub_all_live``), real fuse sense. The seed draws
the state of the t=0 image (TEST_DEV, PROD, PROD_END, RMA_SIP, RMA_CHIPLET, equal
weights) and a filter-legal pair;
``dv_sim_prestage.py`` stages the image from ``env/sep_efuse_plan.py`` and the leaf
builds the same plan. The plan also draws the order of the four protection targets
(an unset ``LOCKS`` bit, an unset assigned ``LOCKS_SPARE`` bit, a ``SIP_DIS`` bit, a
``SYS_DIS`` bit) with four absent bits each (frontdoor and JTAG at strap 1 and at
strap 0), and a zero bit of each of the five program classes (a 256-bit field, a
32-bit field, a disable bit, a ``LOCKS`` bit, a spare word). No lock bit locks a
slot of a target, a program field or a secret field.

Every leaf runs a strap-1 epoch (``secure_tm_req_i`` = 1 from before reset release)
and then a strap-0 epoch (the strap changes only while the cold reset is asserted).
``W_prog`` is ``W_PROG_MULT`` times the sense time the leaf measures at its first
sense; both epochs use it for every program.

Contract (``hw/sys/sep/doc/test_mode.adoc``, sections Entry and Exit, Protection
While Active; ``hw/sys/sep/doc/otp_fuse_controller.adoc``, sections Shadow Register
and JTAG Access Control, Shadow Register Updates and Test-Mode Protection;
``hw/sys/sep/doc/security_disable.adoc``, Token Activation):

  CHK-BIND          the SHA-256 of 32 zero bytes equals the bench SEC_DIS digest.
  CHK-STM-CTL       controls: ``secure_tm_o`` is 0 from reset release until sense
                    done and equals the strap after it; at strap 1 each frontdoor
                    target write leaves the shadow unchanged and ``FEAT_CTRL`` equals
                    the profile row and the strap-0 baseline; at strap 0 each
                    frontdoor write lands; the SEC_DIS match gives
                    ``security_disable_o`` = 1 and an all-ones ``FEAT_CTRL``.
  CHK-STM-PROG      no strap-1 program changes its bank bit (direct read in the strap-0
                    epoch before any program of that epoch) and no ``PROGRAM`` or
                    ``PROGRAM_READ_BACK`` command reaches ``efuse_shim_command_req_o``
                    at strap 1.
  CHK-STM-PROG-CTL  each strap-0 program lands inside ``W_prog`` (direct read) and
                    shows a program command with its address at the tap.
  CHK-STM-SECRET    at strap 1 the four secret fields read 0 at
                    ``efuse_shadow_probe_o`` while the frontdoor read (OKAY) and the OTP
                    word keep the staged value. Control: the strap-0 probe shows the staged
                    words.
  CHK-STM-JTAG      TEST_DEV, PROD_END and RMA_CHIPLET: a strap-1 JTAG write of a new
                    bit leaves each target unchanged.
  CHK-STM-JTAG-CTL  TEST_DEV, PROD_END and RMA_CHIPLET: the strap-0 JTAG write of a
                    new bit to each target lands (``after == before | bit``); JTAG
                    reaches the shadow registers outside PROD and RMA_SIP, and the
                    four targets are set-only in every state. PROD and RMA_SIP restrict
                    JTAG to the token block and log
                    ``OBS-BLOCKED CHK-STM-JTAG reason=lifecycle_gate``.
  INFO-STM-STATE     logs the drawn state and ``jtag_leg`` (1 when CHK-STM-JTAG runs)
                    of the seed. A control line, not a check.
  CTRL-STM-WRITE-ISSUED  each target write returns a response from the DUT; a
                    missing response is a recorded failure.
  CTRL-STM-PROG-ISSUED  after each program go of both straps, the software-owned
                    fields of ``EFUSE_PROGRAM_CTRL`` (``efuse_addr``, ``efuse_data``,
                    ``efuse_program_read_back``, ``program_enable``) read back equal to
                    the go, so a strap-1 go that did not land fails.

Each strap-0 target cell is graded right after its readback. A strap-1 cell FAILs
right after its readback when the word changed; it PASSes only after the strap-0
twin of the same target and source lands in the same word, so the line carries
its positive probe on the word that the strap-1 write addressed (the plan draws
each strap-1 bit and its strap-0 twin in one word). The first failed check or a
missing control closes the graded window for the rest of the leaf. A cell of
``x_shadow_wr_block`` is credited through ``set_stm_shadow_wr_pass`` only after its
check passed. Every other sample of the leaf (``x_prog_block``,
``x_secret_probe``, ``x_secret_read_kept`` and ``sep_efuse_jtag_policy_cg``
``cp_state``) is held with the tag of its graded step (``set_ef_hold_tag``) and
samples only when the leaf writes that tag to the pass label
(``set_ef_hold_pass``) after every check of the step passed: the strap-1
programs after CHK-STM-PROG, the strap-0 programs after CHK-STM-PROG-CTL, the
secret reads after CHK-STM-SECRET and its strap-0 control, the JTAG writes of
both straps after every CHK-STM-JTAG and CHK-STM-JTAG-CTL line.

The status value of each program (``OBS-STM-PROG-STATUS``) and the response code of
a blocked write are logged and not graded. Log-only: ``OBS-STM-RMA-DIGEST-PROBE`` (the two RMA token digest
fields at ``efuse_shadow_probe_o`` at strap 1 and strap 0, against the staged words;
the specification does not state whether secure test mode masks them) and
``OBS-DIGEST-PROG-STATE`` (a strap-0 program of a 0 bit of a drawn digest field: the
OTP bit, the program commands at the tap and ``efuse_req_error``; the specification
does not state in which states it lands). No step writes ``LC_STATE`` and no SEC_DIS go runs at strap 1.
In RMA_CHIPLET the profile row is all ones with or without SEC_DIS, so there the
SEC_DIS control rests on ``security_disable_o`` and the match codes alone.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepEfuseBank, SepShimCmdMonitor
from env.sep_efuse_plan import (
    CODE_MATCH,
    CODE_MISMATCH,
    DIGEST_FIELDS,
    PROGRAM_CTRL_ADDR,
    SECRET_FIELDS,
    STATUS_ADDR,
    STM_PROGRAM_CLASSES,
    STM_TARGETS,
    TOKEN_OTHER,
    TOKEN_ZERO,
    bit_address,
    feat_ctrl_profile,
    field_n_words,
    field_word,
    lc_state_class,
    plan,
    program_ctrl_word,
    shadow_addr,
    zero_bits,
)
from env.sep_efuse_test_lib import (
    SenseClock,
    SepEfuseFd,
    StrapHold,
    bit,
    chk_bind,
    direct_word,
    hold_strap,
    hook_fail,
    rst_pulse,
    sec_dis_go,
    shadow_word,
    wait_bit,
)
from env.sep_fabric_common import RESP_OKAY
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_ef_hold_pass,
    set_ef_hold_tag,
    set_stm_shadow_wr_pass,
)
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, SEP_LIFECYCLE_CTRL

TEST = "sep_efuse_secure_tm_matrix_rand_test"

FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
M32 = 0xFFFF_FFFF
ALL_ONES = (1 << 64) - 1
# W_prog = W_PROG_MULT x the measured sense time (test parameter).
W_PROG_MULT = 2
# Bounds (clocks or reads). A timeout fails the check the wait feeds.
STM_BOUND = 200
SDIS_BOUND = 200
MATCH_READS = 400
SENSE_BOUND = 20_000
# x_shadow_wr_block cell code: target * 4 + source * 2 + strap. The target index
# follows STM_TARGETS (LOCKS, LOCKS_SPARE, SIP_DIS, SYS_DIS), the order of the
# sampler address decode in cov/sv/sep_fcov.sv.
_TARGET_IDX = {t: i for i, t in enumerate(STM_TARGETS)}
_SRC_IDX = {"fd": 0, "jtag": 1}
# Hold tags of the graded steps (set_ef_hold_tag): the strap-1 programs, the
# strap-0 programs, the strap-1 secret reads, the JTAG target writes.
_TAG_PROG1, _TAG_PROG0, _TAG_SECRET, _TAG_JTAG = 1, 2, 3, 4
_PASS_HOLD = 2  # clocks a step tag stays on the pass label
_REQ_ERR = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error")
# Software-owned (sw=rw, hw=r) fields of EFUSE_PROGRAM_CTRL: they read back as written.
_PG_RW = (
    EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_addr")
    | EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_data")
    | EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "efuse_program_read_back")
    | EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_enable")
)
_REQ_ERR_CLEAR = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_INTERFACE_CTRL_STATUS", "efuse_req_error_clear"
)


@pyuvm.test()
class sep_efuse_secure_tm_matrix_rand_test(StrapHold, sep_base_test):
    """At strap 1 programs, shadow writes and secret outputs are blocked; at strap 0 they are not."""

    required_evidence = (
        "CHK-BIND",
        "CHK-STM-CTL",
        "CHK-STM-PROG",
        "CHK-STM-PROG-CTL",
        "CHK-STM-SECRET",
    )

    # -- samples -------------------------------------------------------------

    async def _feat(self) -> int:
        return await self.fd.rd64(FEAT_CTRL)

    # -- graded window -------------------------------------------------------

    def _open(self) -> None:
        """Open the graded window unless a graded failure already closed it."""
        if self._win_ok:
            open_graded_window(TEST, self.logger)
            self._win_open = True

    def _close(self) -> None:
        close_graded_window(self.logger)
        self._win_open = False

    def _grade(self, name: str, cond: bool, **fields) -> bool:
        """Grade one check; a FAIL closes the graded window for the rest of the leaf."""
        if not cond:
            self._close()
            self._win_ok = False
        return self.chk.ok(name, cond, **fields)

    def _ctrl(self, name: str, cond: bool, **fields) -> bool:
        """Log one control; a missing control closes the graded window."""
        if not cond:
            self._close()
            self._win_ok = False
        return self.chk.ctrl(name, cond, **fields)

    def _tag(self, tag: int) -> None:
        """Hold tag of the next samples (0: no graded step, the samples drop)."""
        set_ef_hold_tag(tag, self.logger)

    async def _release(self, tag: int, ok: bool) -> None:
        """Sample the held events of ``tag`` when ``ok`` and no check has failed.

        The graded window is open for the release and keeps the state it had.
        """
        if not ok or not self._win_ok:
            return
        clk = cocotb.top.clk_i
        was_open = self._win_open
        if not was_open:
            open_graded_window(TEST, self.logger)
        set_ef_hold_pass(tag, self.logger)
        await ClockCycles(clk, _PASS_HOLD)
        set_ef_hold_pass(0, self.logger)
        await ClockCycles(clk, 1)
        if not was_open:
            close_graded_window(self.logger)

    async def _credit(self, r: dict, strap: int) -> None:
        """Credit the x_shadow_wr_block cell of ``r`` after its check passed."""
        if not self._win_ok:
            return
        clk = cocotb.top.clk_i
        cell = _TARGET_IDX[r["target"]] * 4 + _SRC_IDX[r["src"]] * 2 + strap
        set_stm_shadow_wr_pass(cell, self.logger)
        await ClockCycles(clk, 2)
        set_stm_shadow_wr_pass(None, self.logger)
        await ClockCycles(clk, 2)

    @staticmethod
    def _epoch_ok(e: dict, strap: int) -> bool:
        return e["before_ones"] == 0 and e["before_n"] > 0 and e["after"] == strap

    @staticmethod
    def _strap1_kept(r: dict) -> bool:
        """Strap-1 golden: the whole word reads back unchanged."""
        return r["unchanged"]

    # -- epochs --------------------------------------------------------------

    async def _epoch_start(self, strap: int, first: bool) -> dict:
        """Reset into an epoch with the strap; return the secure_tm_o samples."""
        sense = SenseClock(self, extra=("secure_tm_o",)).start()
        self._strap = strap
        if first:
            await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        else:
            await rst_pulse(self, strap=strap)
            await self.wait_fuse_sense(max_cycles=SENSE_BOUND)
            self.cfg.reset_done.set()
        if not sense.done:
            sense.stop()
            raise AssertionError("secure_tm_o sampler did not see the sense-done rise")
        rec = sense.samples["secure_tm_o"]
        before = rec[:-1]
        after = None
        if strap:
            waited = await wait_bit(self, "secure_tm_o", 1, STM_BOUND)
            after = bit(self, "secure_tm_o") if waited is not None else 0
        else:
            await ClockCycles(cocotb.top.clk_i, 4)
            after = bit(self, "secure_tm_o")
        out = {
            "sense_clks": len(rec),
            "before_ones": sum(before),
            "before_n": len(before),
            "at_sense": rec[-1],
            "after": after,
        }
        self.logger.info("INFO-EPOCH strap=%d %s", strap, out)
        return out

    async def _target_write(self, t: dict, src: str) -> dict:
        """Write the target word with one absent bit; read it before and after."""
        addr = shadow_addr(t["field"], t["word"])
        before = await self.fd.rd(addr)
        bit = 1 << t["bit"]
        if before & bit:
            raise AssertionError(
                f"test bug: {t['field']} word {t['word']} bit {t['bit']} is already set"
            )
        resp: int | None
        if src == "fd":
            resp = await self.fd.wr_graded_by_readback(addr, before | bit)
        else:
            resp, _ = await self.jtag_axil_op(write=True, addr=addr, wdata=before | bit)
        after = await self.fd.rd(addr)
        return {
            "src": src,
            "target": t["field"],
            "word": t["word"],
            "bit": t["bit"],
            "addr": addr,
            "before": before,
            "after": after,
            "landed": after == before | bit,
            "unchanged": after == before,
            "resp": resp,
            "graded": False,
        }

    async def _cell(self, t: dict, src: str, strap: int, e: dict) -> dict:
        """One target write and readback; a changed strap-1 word FAILs here."""
        r = await self._target_write(t, src)
        self._ctrl(
            "STM-WRITE-ISSUED",
            r["resp"] is not None,
            src=src,
            strap=strap,
            target=r["target"],
            addr=f"0x{r['addr']:08x}",
            resp=r["resp"],
        )
        if strap and not (self._strap1_kept(r) and (src == "jtag" or self._epoch_ok(e, 1))):
            r["graded"] = True
            self._grade(
                "STM-CTL" if src == "fd" else "STM-JTAG",
                False,
                strap=1,
                src=src,
                target=r["target"],
                bit=f"{r['word']}:{r['bit']}",
                before=f"0x{r['before']:08x}",
                after=f"0x{r['after']:08x}",
                landed=int(r["landed"]),
                resp=r["resp"],
                secure_tm_before_sense=int(e["before_ones"] != 0),
                secure_tm_after_sense=e["after"],
            )
        return r

    def _field_probe(self, f: str) -> list[int]:
        return [shadow_word(self, field_word(f) + k) for k in range(field_n_words(f))]

    async def _digest_program(self, state: str, w_prog: int) -> None:
        """Strap 0: a program of a 0 bit of a drawn RMA token digest field, logged only.

        ``OBS-DIGEST-PROG-STATE``: the specification does not state in which states a
        program of a token digest lands.
        """
        p = self.p
        f = p.draw.choice("digest_prog_field", DIGEST_FIELDS)
        zeros = zero_bits(p.image, f)
        if not zeros:
            self.chk.obs("DIGEST-PROG-STATE", state=state, field=f, reason="no_zero_bit")
            return
        k, b = p.draw.choice("digest_prog_bit", zeros)
        addr = bit_address(f, k, b)
        mark = self.shim.mark()
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(addr))
        await ClockCycles(cocotb.top.clk_i, w_prog)
        status = await self.fd.rd(PROGRAM_CTRL_ADDR)
        await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
        progs = self.shim.programs_since(mark)
        st = await self.fd.rd(STATUS_ADDR)
        if st & _REQ_ERR:
            await self.fd.wr(STATUS_ADDR, _REQ_ERR_CLEAR)
        # The bank tap, not a read request: the read interface may refuse a digest word.
        word = SepEfuseBank().read()[field_word(f) + k]
        self.chk.obs(
            "DIGEST-PROG-STATE",
            state=state,
            field=f,
            bit=f"{k}:{b}",
            otp_bit=(word >> b) & 1,
            shim_prog=sum(int(c.address == addr) for c in progs),
            req_err=int(bool(st & _REQ_ERR)),
            program_ctrl=f"0x{status:08x}",
        )

    async def _programs(self, progs: dict, w_prog: int) -> dict[str, list]:
        """One program go per class, each followed by ``w_prog`` clocks and an enable clear.

        ``CTRL-STM-PROG-ISSUED`` requires the software-owned fields of
        ``EFUSE_PROGRAM_CTRL`` read back after ``w_prog`` to equal the go, so a go that
        did not land fails. ``OBS-STM-PROG-STATUS`` logs the whole word: the TT texts
        disagree on the status of a program blocked in secure test mode.
        """
        cmds: dict[str, list] = {}
        for cls in STM_PROGRAM_CLASSES:
            pr = progs[cls]
            mark = self.shim.mark()
            go = program_ctrl_word(pr["addr"])
            await self.fd.wr(PROGRAM_CTRL_ADDR, go)
            await ClockCycles(cocotb.top.clk_i, w_prog)
            status = await self.fd.rd(PROGRAM_CTRL_ADDR)
            await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
            cmds[cls] = self.shim.programs_since(mark)
            self._ctrl(
                "STM-PROG-ISSUED",
                (status & _PG_RW) == (go & _PG_RW),
                strap=self._strap,
                cls=cls,
                wrote=f"0x{go & _PG_RW:08x}",
                readback=f"0x{status & _PG_RW:08x}",
            )
            self.chk.obs(
                "STM-PROG-STATUS",
                strap=self._strap,
                cls=cls,
                field=pr["field"],
                word=pr["word"],
                bit=pr["bit"],
                addr=f"0x{pr['addr']:x}",
                status=f"0x{status:08x}",
                program_cmds=len(cmds[cls]),
            )
        return cmds

    # -- scenario ------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.p = p = plan(TEST, seed)
        state = lc_state_class(p.lc_raw)
        for line in p.log_lines(state=state):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        jtag_leg = bool(p.leg["jtag_leg"])
        self.logger.info("INFO-STM-STATE seed=%d state=%s jtag_leg=%d", seed, state, int(jtag_leg))
        if jtag_leg:
            self.required_evidence = (*self.required_evidence, "CHK-STM-JTAG", "CHK-STM-JTAG-CTL")
        self.logger.info(
            "INFO-EVIDENCE-PLAN seed=%d required=%s", seed, ",".join(self.required_evidence)
        )
        close_graded_window(self.logger)
        self._win_ok = True
        self._win_open = False
        self._tag(0)
        set_ef_hold_pass(0, self.logger)
        self.fd = SepEfuseFd(self)
        order = p.leg["target_order"]
        targets = p.leg["targets"]
        progs = p.leg["programs"]
        row = feat_ctrl_profile(p.lc_raw, p.sip_dis, p.sys_dis)
        self.logger.info("INFO-GOLDEN feat %s value=0x%016x", row.log(), row.value)

        await chk_bind(self.chk)
        self.write_efuse_image(p.image)

        # Strap-1 epoch.
        e1 = await self._epoch_start(1, first=True)
        w_prog = W_PROG_MULT * e1["sense_clks"]
        self.logger.info(
            "INFO-W-PROG clocks=%d sense_clks=%d mult=%d", w_prog, e1["sense_clks"], W_PROG_MULT
        )
        self.shim = SepShimCmdMonitor().start()
        feat1 = await self._feat()
        # The graded window holds the strap-1 target writes and readbacks, the
        # strap-1 programs and the secret reads.
        self._open()
        fd1 = {}
        for t in order:
            fd1[t] = await self._cell(targets[t][0], "fd", 1, e1)
        feat1_after = await self._feat()
        jt1 = {}
        if jtag_leg:
            self._tag(_TAG_JTAG)
            for t in order:
                jt1[t] = await self._cell(targets[t][1], "jtag", 1, e1)
            self._tag(0)
        self._tag(_TAG_PROG1)
        prog1 = await self._programs(progs, w_prog)
        self._tag(_TAG_SECRET)
        secret1: dict[str, dict] = {}
        for f in SECRET_FIELDS:
            base = field_word(f)
            probe = [shadow_word(self, base + k) for k in range(field_n_words(f))]
            reads = [
                await self.fd.rd_graded_by_data(shadow_addr(f, k)) for k in range(field_n_words(f))
            ]
            secret1[f] = {"probe": probe, "reads": reads}
        self._tag(0)
        self._close()
        digest1 = {f: self._field_probe(f) for f in DIGEST_FIELDS}

        # Strap-0 epoch. The graded window holds the strap-0 target writes and
        # readbacks and the grades of both epochs' target cells.
        e0 = await self._epoch_start(0, first=False)
        feat0 = await self._feat()
        self._open()
        for t in order:
            c = await self._cell(targets[t][2], "fd", 0, e0)
            feat_ok0 = feat0 == row.value and feat0 == feat1
            if self._grade(
                "STM-CTL",
                self._epoch_ok(e0, 0) and c["landed"] and feat_ok0,
                strap=0,
                secure_tm_before_sense=int(e0["before_ones"] != 0),
                secure_tm_after_sense=e0["after"],
                sense_clks=e0["sense_clks"],
                target=t,
                bit=f"{c['word']}:{c['bit']}",
                before=f"0x{c['before']:08x}",
                after=f"0x{c['after']:08x}",
                landed=int(c["landed"]),
                resp=c["resp"],
                feat=f"0x{feat0:016x}",
                feat_exp=f"0x{row.value:016x}",
            ):
                await self._credit(c, 0)
            r = fd1[t]
            if r["graded"]:
                continue
            feat_ok1 = feat1 == row.value and feat0 == feat1 and feat1_after == feat1
            # The strap-0 frontdoor twin of the same target word is the positive probe.
            same = c["addr"] == r["addr"]
            if self._grade(
                "STM-CTL",
                self._epoch_ok(e1, 1)
                and self._strap1_kept(r)
                and feat_ok1
                and c["landed"]
                and same,
                strap=1,
                secure_tm_before_sense=int(e1["before_ones"] != 0),
                secure_tm_after_sense=e1["after"],
                sense_clks=e1["sense_clks"],
                target=t,
                bit=f"{r['word']}:{r['bit']}",
                before=f"0x{r['before']:08x}",
                after=f"0x{r['after']:08x}",
                landed=int(r["landed"]),
                resp=r["resp"],
                feat=f"0x{feat1:016x}",
                feat_after=f"0x{feat1_after:016x}",
                feat_exp=f"0x{row.value:016x}",
                ctl_before=f"0x{c['before']:08x}",
                ctl_after=f"0x{c['after']:08x}",
                ctl_landed=int(c["landed"]),
                ctl_addr=f"0x{c['addr']:08x}",
                twin_same_word=int(same),
            ):
                await self._credit(r, 1)

        if jtag_leg:
            jtag_ok = True
            for t in order:
                self._tag(_TAG_JTAG)
                c = await self._cell(targets[t][3], "jtag", 0, e0)
                self._tag(0)
                ok = self._grade(
                    "STM-JTAG-CTL",
                    c["landed"],
                    target=t,
                    strap=0,
                    state=state,
                    bit=f"{c['word']}:{c['bit']}",
                    before=f"0x{c['before']:08x}",
                    after=f"0x{c['after']:08x}",
                    landed=int(c["landed"]),
                    resp=c["resp"],
                )
                jtag_ok &= ok
                if ok:
                    await self._credit(c, 0)
                r = jt1[t]
                if r["graded"]:
                    jtag_ok = False
                    continue
                # The strap-0 JTAG twin of the same target word is the positive probe.
                same = c["addr"] == r["addr"]
                ok = self._grade(
                    "STM-JTAG",
                    self._strap1_kept(r) and c["landed"] and same,
                    target=t,
                    strap=1,
                    bit=f"{r['word']}:{r['bit']}",
                    before=f"0x{r['before']:08x}",
                    after=f"0x{r['after']:08x}",
                    resp=r["resp"],
                    ctl_after=f"0x{c['after']:08x}",
                    ctl_before=f"0x{c['before']:08x}",
                    ctl_landed=int(c["landed"]),
                    ctl_addr=f"0x{c['addr']:08x}",
                    twin_same_word=int(same),
                )
                jtag_ok &= ok
                if ok:
                    await self._credit(r, 1)
            await self._release(_TAG_JTAG, jtag_ok)
        else:
            self.chk.blocked("STM-JTAG", "lifecycle_gate")
        self._close()

        # Bank read before any strap-0 program, then the strap-0 programs.
        strap1_cmds = sum(len(v) for v in prog1.values())
        prog1_ok = True
        for cls in STM_PROGRAM_CLASSES:
            pr = progs[cls]
            word = await direct_word(self, field_word(pr["field"]) + pr["word"])
            bit_read = (word >> pr["bit"]) & 1
            prog1_ok &= self._grade(
                "STM-PROG",
                bit_read == 0 and strap1_cmds == 0,
                strap=1,
                field=pr["field"],
                cls=cls,
                bit_read=bit_read,
                word=f"0x{word:08x}",
                strap1_prog_cmds=strap1_cmds,
            )
        await self._release(_TAG_PROG1, prog1_ok)
        otp_secret = {f: await direct_word(self, field_word(f)) for f in SECRET_FIELDS}
        self._open()
        self._tag(_TAG_PROG0)
        prog0 = await self._programs(progs, w_prog)
        self._tag(0)
        self._close()
        prog0_ok = True
        for cls in STM_PROGRAM_CLASSES:
            pr = progs[cls]
            word = await direct_word(self, field_word(pr["field"]) + pr["word"])
            bit_read = (word >> pr["bit"]) & 1
            at_addr = [c for c in prog0[cls] if c.address == pr["addr"]]
            prog0_ok &= self._grade(
                "STM-PROG-CTL",
                bit_read == 1 and len(at_addr) >= 1,
                strap=0,
                field=pr["field"],
                cls=cls,
                bit_read=bit_read,
                shim_cmd=int(len(at_addr) >= 1),
                shim_cmds=len(prog0[cls]),
                word=f"0x{word:08x}",
                w_prog=w_prog,
            )
        await self._release(_TAG_PROG0, prog0_ok)

        # Secret cells: the strap-0 probe is the control of the strap-1 zero.
        secret_ok = True
        for f in SECRET_FIELDS:
            base = field_word(f)
            staged = [p.image.words[base + k] & M32 for k in range(field_n_words(f))]
            ctl_probe = [shadow_word(self, base + k) for k in range(field_n_words(f))]
            s1 = secret1[f]
            reg_eq = [d for _r, d in s1["reads"]] == staged and all(
                r == RESP_OKAY for r, _d in s1["reads"]
            )
            secret_ok &= self._grade(
                "STM-SECRET",
                all(v == 0 for v in s1["probe"])
                and all(v != 0 for v in staged)
                and ctl_probe == staged
                and reg_eq
                and otp_secret[f] == staged[0],
                strap=1,
                field=f,
                probe=f"0x{max(s1['probe']):x}",
                ctl_probe=f"0x{ctl_probe[0]:08x}",
                staged=f"0x{staged[0]:08x}",
                reg_read_eq_staged=int(reg_eq),
                reg_resps=[r for r, _d in s1["reads"]],
                otp_word0_eq_staged=int(otp_secret[f] == staged[0]),
            )
        await self._release(_TAG_SECRET, secret_ok)
        for f in DIGEST_FIELDS:
            staged = [p.image.words[field_word(f) + k] & M32 for k in range(field_n_words(f))]
            s0 = self._field_probe(f)
            self.chk.obs(
                "STM-RMA-DIGEST-PROBE",
                state=state,
                field=f,
                strap1=f"0x{digest1[f][0]:08x}",
                strap0=f"0x{s0[0]:08x}",
                staged=f"0x{staged[0]:08x}",
                strap1_eq_staged=sum(int(a == b) for a, b in zip(digest1[f], staged)),
                strap1_zero=sum(int(a == 0) for a in digest1[f]),
                strap0_eq_staged=sum(int(a == b) for a, b in zip(s0, staged)),
                words=len(staged),
            )
        await self._digest_program(state, w_prog)

        # SEC_DIS leg at strap 0: the control of the revision-enable assumption.
        code_m, reads_m = await sec_dis_go(self.fd, TOKEN_ZERO, CODE_MATCH, max_reads=MATCH_READS)
        rose = await wait_bit(self, "lcc_security_disable_probe_o", 1, SDIS_BOUND)
        if code_m != CODE_MATCH or rose is None:
            hook_fail(
                self.chk,
                reason="security_disable_o did not rise on the TOKEN_ZERO match",
                code=f"0x{(code_m or 0):02x}",
                reads=reads_m,
            )
        sd_feat = await self._feat()
        code_mm, reads_mm = await sec_dis_go(
            self.fd, TOKEN_OTHER, CODE_MISMATCH, max_reads=MATCH_READS
        )
        fell = await wait_bit(self, "lcc_security_disable_probe_o", 0, SDIS_BOUND)
        self.chk.ok(
            "STM-CTL",
            sd_feat == ALL_ONES and code_mm == CODE_MISMATCH and fell is not None,
            strap=0,
            secure_tm_before_sense=int(e0["before_ones"] != 0),
            secure_tm_after_sense=e0["after"],
            target="sec_dis",
            landed="na",
            feat=f"0x{feat0:016x}",
            secdis_feat=f"0x{sd_feat:016x}",
            code_match=f"0x{code_m:02x}",
            code_mismatch=f"0x{(code_mm or 0):02x}",
            sdis_after_mismatch=bit(self, "lcc_security_disable_probe_o"),
        )
        await self.shim.stop()
        # The monitor stop returns in the read-only phase; leave it before the drive.
        await ClockCycles(cocotb.top.clk_i, 1)
        hold_strap(self, 0)
        self.chk.finish(f" state={state}")
