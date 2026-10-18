# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure test mode: programs blocked, secret fields masked at the shadow output, JTAG writes blocked.

RAND-REP. Run mode no_cpu (``lsu_stub_all_live``), real fuse sense. The seed draws
the state of the t=0 image (TEST_DEV 2, PROD 1, RMA_SIP 1) and a filter-legal pair;
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
                    ``efuse_shadow_probe_o`` while the frontdoor read and the OTP word
                    keep the staged value. Control: the strap-0 probe shows the staged
                    words.
  CHK-STM-JTAG      TEST_DEV: a strap-1 JTAG write of a new bit leaves each target
                    unchanged. Control: the strap-0 JTAG write of the same target
                    lands; a target whose control does not land logs
                    ``CHK-STM-JTAG N/A``; a TEST_DEV leaf with no landed control fails
                    with ``CHK-HOOK FAIL``. PROD and RMA_SIP log
                    ``CHK-STM-JTAG N/A ... reason=lifecycle_gate``.

The status value of a blocked program and the response code of a blocked write are
logged and not graded. No step writes ``LC_STATE`` and no SEC_DIS go runs at strap 1.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_plan import (
    CODE_MATCH,
    CODE_MISMATCH,
    PROGRAM_CTRL_ADDR,
    SECRET_FIELDS,
    STM_PROGRAM_CLASSES,
    TOKEN_OTHER,
    TOKEN_ZERO,
    feat_ctrl_profile,
    field_n_words,
    field_word,
    lc_state_class,
    plan,
    program_ctrl_word,
    shadow_addr,
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
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_LIFECYCLE_CTRL

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
        self.logger.info("EPOCH strap=%d %s", strap, out)
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
        if src == "fd":
            resp = await self.fd.wr_graded_by_readback(addr, before | bit)
        else:
            resp, _ = await self.jtag_axil_op(write=True, addr=addr, wdata=before | bit)
        after = await self.fd.rd(addr)
        return {
            "target": t["field"],
            "word": t["word"],
            "bit": t["bit"],
            "addr": addr,
            "before": before,
            "after": after,
            "landed": after == before | bit,
            "unchanged": after == before,
            "resp": resp,
        }

    async def _programs(self, progs: dict, w_prog: int) -> dict[str, list]:
        """One program go per class, each followed by ``w_prog`` clocks and an enable clear."""
        cmds: dict[str, list] = {}
        for cls in STM_PROGRAM_CLASSES:
            pr = progs[cls]
            mark = self.shim.mark()
            await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(pr["addr"]))
            await ClockCycles(cocotb.top.clk_i, w_prog)
            status = await self.fd.rd(PROGRAM_CTRL_ADDR)
            await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
            cmds[cls] = self.shim.programs_since(mark)
            self.logger.info(
                "PROGRAM strap=%d class=%s field=%s word=%d bit=%d addr=0x%x status=0x%08x "
                "program_cmds=%d",
                self._strap,
                cls,
                pr["field"],
                pr["word"],
                pr["bit"],
                pr["addr"],
                status,
                len(cmds[cls]),
            )
        return cmds

    # -- scenario ------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        p = plan(TEST, seed)
        state = lc_state_class(p.lc_raw)
        for line in p.log_lines(state=state):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        jtag_leg = bool(p.leg["jtag_leg"])
        if jtag_leg:
            self.required_evidence = (*self.required_evidence, "CHK-STM-JTAG")
        self.logger.info(
            "EVIDENCE-PLAN seed=%d required=%s", seed, ",".join(self.required_evidence)
        )
        close_graded_window(self.logger)
        self.fd = SepEfuseFd(self)
        order = p.leg["target_order"]
        targets = p.leg["targets"]
        progs = p.leg["programs"]
        row = feat_ctrl_profile(p.lc_raw, p.sip_dis, p.sys_dis)
        self.logger.info("GOLDEN feat %s value=0x%016x", row.log(), row.value)

        chk_bind(self.chk)
        self.write_efuse_image(p.image)

        # Strap-1 epoch.
        e1 = await self._epoch_start(1, first=True)
        w_prog = W_PROG_MULT * e1["sense_clks"]
        self.logger.info(
            "W_PROG clocks=%d sense_clks=%d mult=%d", w_prog, e1["sense_clks"], W_PROG_MULT
        )
        self.shim = SepShimCmdMonitor().start()
        feat1 = await self._feat()
        fd1 = {t: await self._target_write(targets[t][0], "fd") for t in order}
        feat1_after = await self._feat()
        jt1 = {}
        if jtag_leg:
            jt1 = {t: await self._target_write(targets[t][1], "jtag") for t in order}
        open_graded_window(TEST, self.logger)
        prog1 = await self._programs(progs, w_prog)
        secret1: dict[str, dict] = {}
        for f in SECRET_FIELDS:
            base = field_word(f)
            probe = [shadow_word(self, base + k) for k in range(field_n_words(f))]
            reads = [
                await self.fd.rd_graded_by_data(shadow_addr(f, k)) for k in range(field_n_words(f))
            ]
            secret1[f] = {"probe": probe, "reads": reads}
        close_graded_window(self.logger)

        # Strap-0 epoch.
        e0 = await self._epoch_start(0, first=False)
        feat0 = await self._feat()
        fd0 = {t: await self._target_write(targets[t][2], "fd") for t in order}
        jt0 = {}
        if jtag_leg:
            jt0 = {t: await self._target_write(targets[t][3], "jtag") for t in order}

        for strap, e, feat, fdw in ((1, e1, feat1, fd1), (0, e0, feat0, fd0)):
            for t in order:
                r = fdw[t]
                landed_ok = r["unchanged"] if strap else r["landed"]
                feat_ok = (
                    feat == row.value and feat0 == feat1 and (not strap or feat1_after == feat1)
                )
                self.chk.ok(
                    "STM-CTL",
                    e["before_ones"] == 0
                    and e["before_n"] > 0
                    and e["after"] == strap
                    and landed_ok
                    and feat_ok,
                    strap=strap,
                    secure_tm_before_sense=int(e["before_ones"] != 0),
                    secure_tm_after_sense=e["after"],
                    sense_clks=e["sense_clks"],
                    target=t,
                    bit=f"{r['word']}:{r['bit']}",
                    before=f"0x{r['before']:08x}",
                    after=f"0x{r['after']:08x}",
                    landed=int(r["landed"]),
                    resp=r["resp"],
                    feat=f"0x{feat:016x}",
                    feat_exp=f"0x{row.value:016x}",
                )

        if jtag_leg:
            landed_any = False
            for t in order:
                c = jt0[t]
                if not c["landed"]:
                    self.logger.info(
                        "CHK-STM-JTAG N/A seed=%d target=%s ctl_landed=0 ctl_resp=%d",
                        seed,
                        t,
                        c["resp"],
                    )
                    continue
                landed_any = True
                r = jt1[t]
                self.chk.ok(
                    "STM-JTAG",
                    r["unchanged"],
                    target=t,
                    strap=1,
                    before=f"0x{r['before']:08x}",
                    after=f"0x{r['after']:08x}",
                    resp=r["resp"],
                    ctl_after=f"0x{c['after']:08x}",
                    ctl_before=f"0x{c['before']:08x}",
                )
            if not landed_any:
                hook_fail(self.chk, reason="no strap-0 JTAG target write landed", state=state)
        else:
            self.logger.info("CHK-STM-JTAG N/A seed=%d state=%s reason=lifecycle_gate", seed, state)

        # Bank read before any strap-0 program, then the strap-0 programs.
        strap1_cmds = sum(len(v) for v in prog1.values())
        for cls in STM_PROGRAM_CLASSES:
            pr = progs[cls]
            word = await direct_word(self, field_word(pr["field"]) + pr["word"])
            bit_read = (word >> pr["bit"]) & 1
            self.chk.ok(
                "STM-PROG",
                bit_read == 0 and strap1_cmds == 0,
                strap=1,
                field=pr["field"],
                cls=cls,
                bit_read=bit_read,
                word=f"0x{word:08x}",
                strap1_prog_cmds=strap1_cmds,
            )
        otp_secret = {f: await direct_word(self, field_word(f)) for f in SECRET_FIELDS}
        open_graded_window(TEST, self.logger)
        prog0 = await self._programs(progs, w_prog)
        close_graded_window(self.logger)
        for cls in STM_PROGRAM_CLASSES:
            pr = progs[cls]
            word = await direct_word(self, field_word(pr["field"]) + pr["word"])
            bit_read = (word >> pr["bit"]) & 1
            at_addr = [c for c in prog0[cls] if c.address == pr["addr"]]
            self.chk.ok(
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

        # Secret cells: the strap-0 probe is the control of the strap-1 zero.
        for f in SECRET_FIELDS:
            base = field_word(f)
            staged = [p.image.words[base + k] & M32 for k in range(field_n_words(f))]
            ctl_probe = [shadow_word(self, base + k) for k in range(field_n_words(f))]
            s1 = secret1[f]
            reg_eq = [d for _r, d in s1["reads"]] == staged
            self.chk.ok(
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
