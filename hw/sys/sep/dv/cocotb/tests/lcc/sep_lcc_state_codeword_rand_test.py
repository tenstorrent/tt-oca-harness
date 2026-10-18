# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Lifecycle integrity error: FEAT_CTRL fails closed, SEC_DIS wins, the JTAG filter refuses.

RAND-REP. Run mode no_cpu (``lsu_stub_all_live``), real fuse sense. The seed draws
the nibble n of the t=0 image (``{~n, n}`` in ``LC_STATE``) from the seven
open-profile nibbles (0000 weight 2, 0001, 0010, 0011, 0110, 0111, 1000 weight 1)
and a filter-legal disable-vector pair; ``dv_sim_prestage.py`` stages the image
from ``env/sep_efuse_plan.py`` and the leaf builds the same plan. A leaf that draws
0000 (TEST_DEV) also draws leg C: the JTAG shadow word, the control bit and the
drawn bit of ``SIP_DIS`` (two bits the staged ``SIP_DIS`` lacks), the counts c1
and c2, and the word order of the token write.

Contract (``hw/sys/sep/doc/lifecycle_controller.adoc``, sections Overrides and
Final Gates (SEC_DIS), Per-LC-state Feature Control Profile, Debug and Test Port
Path Gating, row SEP OTP JTAG2AXIL path; ``hw/sys/sep/doc/security_disable.adoc``,
sections Token Activation, Implementation Requirements):

  CHK-BIND          the SHA-256 of 32 zero bytes equals the SEC_DIS digest that the
                    bench binds, read through the simulator handle of
                    ``SecDisTbDigest`` (``tb/tb_top.sv``).
  CHK-SIGINT        with ``lc_sigint_inject_i`` raised (both rails of the byte at
                    the lifecycle decoder input at 0), ``lc_sigint_err_o`` = 1 and
                    ``FEAT_CTRL`` = 0 at the register and at ``lcc_feat_ctrl_probe_o``.
                    Control: the epoch before the inject reads the non-zero profile
                    row with ``lc_sigint_err_o`` = 0. Nibble 0111 is logged
                    ``role=control``.
  CHK-SIGINT-SECDIS with the inject still raised, a ``TOKEN_ZERO`` SEC_DIS match
                    gives an all-ones ``FEAT_CTRL`` with ``lc_sigint_err_o`` = 1, and
                    a ``TOKEN_OTHER`` mismatch returns it to 0. Control:
                    ``security_disable_o`` rises on the match (else ``CHK-HOOK FAIL``).
  CHK-JTAG-SIGINT   leg C (n = 0000): while ``jtag_filter_lc_sigint_err_probe_o`` = 1
                    under ``jtag_filter_lc_sigint_inject_i``, a JTAG read of a shadow
                    word and of ``EFUSE_PROGRAM_CTRL``, a JTAG write to ``SIP_DIS`` and
                    a JTAG write to ``EFUSE_READ_REQ_TIMEOUT`` answer a response that is
                    not OKAY and change nothing at the frontdoor; the token word
                    writes, the token word read, the go and the match read answer
                    OKAY. Control: the epoch without the inject answers OKAY to the two
                    reads and to a JTAG write of the control bit and of c1, and the
                    frontdoor shows both writes landed. A probe that stays 0 under the
                    inject fails the leaf with ``CHK-HOOK FAIL``. A leaf with another
                    nibble logs ``CHK-JTAG-SIGINT N/A``.

Nothing is graded after an inject input falls: the specification states no release
of ``lc_sigint_err_o``. ``lc_sigint_err_o`` under the filter-side inject is logged
(``OBS-LC-SIGINT-FILTER``) and not graded.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_efuse_plan import (
    CH_SIP,
    CODE_MATCH,
    CODE_MISMATCH,
    GO_MASK,
    MATCH_ADDR,
    MATCH_STATUS_MASK,
    PROGRAM_CTRL_ADDR,
    SHADOW_BASE,
    TOKEN_ARRAY_ADDR,
    TOKEN_EOP_ADDR,
    TOKEN_OTHER,
    TOKEN_ZERO,
    feat_ctrl_profile,
    plan,
    shadow_addr,
    token_words,
)
from env.sep_efuse_test_lib import (
    SepEfuseFd,
    bit,
    chk_bind,
    hook_fail,
    sec_dis_go,
    wait_bit,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, SEP_LIFECYCLE_CTRL

TEST = "sep_lcc_state_codeword_rand_test"

FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
READ_TIMEOUT = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_REQ_TIMEOUT")
READ_TIMEOUT_FIELDS = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_READ_REQ_TIMEOUT", "read_req_timeout_cycles"
) | EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_REQ_TIMEOUT", "read_req_timout_enable")
ALL_ONES = (1 << 64) - 1
NIBBLE_CONTROL = 0b0111
OKAY = 0
# Bounds (clocks or reads). A timeout fails the check the wait feeds.
SIGINT_BOUND = 200
SDIS_BOUND = 200
MATCH_READS = 400
SENSE_BOUND = 20_000


@pyuvm.test()
class sep_lcc_state_codeword_rand_test(sep_base_test):
    """Integrity error forces FEAT_CTRL to 0, SEC_DIS overrides it, the JTAG filter refuses."""

    required_evidence = ("CHK-BIND", "CHK-SIGINT", "CHK-SIGINT-SECDIS")

    # -- samples -------------------------------------------------------------

    async def _feat(self) -> tuple[int, int]:
        """64-bit frontdoor read of FEAT_CTRL and the probe right after it."""
        reg = await self.fd.rd64(FEAT_CTRL)
        return reg, self.rd_known(cocotb.top.lcc_feat_ctrl_probe_o)

    async def _cold_reset(self) -> None:
        await RisingEdge(cocotb.top.clk_i)
        await self.resense(max_cycles=SENSE_BOUND)

    # -- checks --------------------------------------------------------------

    async def _legs_a_b(self, n: int, sip: int, sys_: int) -> None:
        dut = cocotb.top
        role = "control" if n == NIBBLE_CONTROL else "new"
        ctl_row = feat_ctrl_profile(n, sip, sys_)
        self.logger.info("GOLDEN ctl n=0x%x %s value=0x%016x", n, ctl_row.log(), ctl_row.value)
        ctl_feat, ctl_probe = await self._feat()
        ctl_sigint = bit(self, "lcc_sigint_err_probe_o")

        # Leg A, injection epoch. The 0111 cell of leg A is a control and is not
        # credited, so its window opens at leg B.
        if role == "new":
            open_graded_window(TEST, self.logger)
        self._set_pin(dut, "lc_sigint_inject_i", 1)
        waited = await wait_bit(self, "lcc_sigint_err_probe_o", 1, SIGINT_BOUND)
        await RisingEdge(dut.clk_i)
        feat, probe = await self._feat()
        sigint = bit(self, "lcc_sigint_err_probe_o")
        fail_row = feat_ctrl_profile(n, sip, sys_, sigint_err=1)
        self.chk.ok(
            "SIGINT",
            waited is not None
            and sigint == 1
            and feat == fail_row.value
            and probe == fail_row.value
            and ctl_row.value != 0
            and ctl_feat == ctl_row.value
            and ctl_probe == ctl_row.value
            and ctl_sigint == 0,
            n=f"0x{n:x}",
            role=role,
            exp_feat=f"0x{fail_row.value:x}",
            got_feat=f"0x{feat:x}",
            got_probe=f"0x{probe:x}",
            sigint=sigint,
            sigint_wait_clks=waited if waited is not None else "timeout",
            ctl_feat=f"0x{ctl_feat:016x}",
            ctl_probe=f"0x{ctl_probe:016x}",
            ctl_exp=f"0x{ctl_row.value:016x}",
            ctl_sigint=ctl_sigint,
            row=ctl_row.row,
            src=f"{fail_row.source}",
        )

        # Leg B: SEC_DIS over the integrity error, then a mismatch.
        open_graded_window(TEST, self.logger)
        code_m, reads_m = await sec_dis_go(self.fd, TOKEN_ZERO, CODE_MATCH, max_reads=MATCH_READS)
        rose = await wait_bit(self, "lcc_security_disable_probe_o", 1, SDIS_BOUND)
        if code_m != CODE_MATCH or rose is None:
            hook_fail(
                self.chk,
                n=f"0x{n:x}",
                reason="security_disable_o did not rise on the TOKEN_ZERO match",
                code=f"0x{(code_m or 0):02x}",
                reads=reads_m,
            )
        on_feat, _on_probe = await self._feat()
        on_sigint = bit(self, "lcc_sigint_err_probe_o")
        on_sdis = bit(self, "lcc_security_disable_probe_o")
        on_row = feat_ctrl_profile(n, sip, sys_, sec_dis=1, sigint_err=1)
        code_mm, reads_mm = await sec_dis_go(
            self.fd, TOKEN_OTHER, CODE_MISMATCH, max_reads=MATCH_READS
        )
        off_feat, _off_probe = await self._feat()
        off_sigint = bit(self, "lcc_sigint_err_probe_o")
        off_row = feat_ctrl_profile(n, sip, sys_, sec_dis=0, sigint_err=1)
        self.chk.ok(
            "SIGINT-SECDIS",
            on_row.value == ALL_ONES
            and on_feat == on_row.value
            and on_sigint == 1
            and on_sdis == 1
            and code_mm == CODE_MISMATCH
            and off_feat == off_row.value
            and off_sigint == 1,
            n=f"0x{n:x}",
            got_feat=f"0x{on_feat:016x}",
            sigint=on_sigint,
            sdis=on_sdis,
            after_mismatch=f"0x{off_feat:x}",
            after_mismatch_sigint=off_sigint,
            code_match=f"0x{code_m:02x}",
            code_mismatch=f"0x{(code_mm or 0):02x}",
            mismatch_reads=reads_mm,
            src=on_row.source,
        )
        close_graded_window(self.logger)
        self._set_pin(dut, "lc_sigint_inject_i", 0)
        await self._cold_reset()

    # -- leg C ---------------------------------------------------------------

    async def _jtag(self, *, write: bool, addr: int, wdata: int = 0) -> tuple[int, int]:
        return await self.jtag_axil_op(write=write, addr=addr, wdata=wdata)

    async def _leg_c(self, leg: dict, sip_staged: int) -> None:
        dut = cocotb.top
        word = leg["jtag_shadow_word"]
        shadow = SHADOW_BASE + 4 * word
        ctl_bit, drawn_bit = leg["ctl_bit"], leg["drawn_bit"]
        c1, c2 = leg["c1"], leg["c2"]
        sip_addr = shadow_addr("SIP_DIS")

        # Control epoch, no inject.
        probe0 = bit(self, "jtag_filter_lc_sigint_err_probe_o")
        r_sh, _ = await self._jtag(write=False, addr=shadow)
        r_pg, _ = await self._jtag(write=False, addr=PROGRAM_CTRL_ADDR)
        r_wr, _ = await self._jtag(
            write=True, addr=shadow_addr("SIP_DIS", ctl_bit // 32), wdata=1 << (ctl_bit % 32)
        )
        sip_ctl = await self.fd.rd64(sip_addr)
        r_cw, _ = await self._jtag(write=True, addr=READ_TIMEOUT, wdata=c1)
        cw = await self.fd.rd(READ_TIMEOUT)
        ctl_bit_set = (sip_ctl >> ctl_bit) & 1 == 1 and (sip_ctl >> drawn_bit) & 1 == 0
        ctl_cw_landed = cw & READ_TIMEOUT_FIELDS == c1
        ctl_ok = self.chk.ctrl(
            "JTAG-SIGINT-CONTROL",
            probe0 == 0
            and (r_sh, r_pg, r_wr, r_cw) == (OKAY, OKAY, OKAY, OKAY)
            and ctl_bit_set
            and ctl_cw_landed
            and sip_ctl == sip_staged | (1 << ctl_bit),
            filter_err=probe0,
            shadow_word=word,
            resp_shadow=r_sh,
            resp_program_ctrl=r_pg,
            resp_sip_wr=r_wr,
            resp_cw=r_cw,
            sip_dis=f"0x{sip_ctl:016x}",
            ctl_bit=ctl_bit,
            drawn_bit=drawn_bit,
            cw=f"0x{cw:08x}",
            c1=f"0x{c1:07x}",
        )
        ctl = {
            "ctl_resp": "OKAY" if (r_sh, r_pg) == (OKAY, OKAY) else "ERR",
            "ctl_wr_resp": "OKAY" if r_wr == OKAY else "ERR",
            "ctl_bit_set": ctl_bit_set,
            "ctl_cw_resp": "OKAY" if r_cw == OKAY else "ERR",
            "ctl_cw_landed": ctl_cw_landed,
        }

        # Injection epoch.
        open_graded_window(TEST, self.logger)
        self._set_pin(dut, "jtag_filter_lc_sigint_inject_i", 1)
        waited = await wait_bit(self, "jtag_filter_lc_sigint_err_probe_o", 1, SIGINT_BOUND)
        if waited is None:
            close_graded_window(self.logger)
            hook_fail(
                self.chk,
                reason="jtag_filter_lc_sigint_err_probe_o stayed 0 under the inject",
                bound=SIGINT_BOUND,
            )
        self.chk.obs("LC-SIGINT-FILTER", lc_sigint_err=bit(self, "lcc_sigint_err_probe_o"))
        sip_before = await self.fd.rd64(sip_addr)

        def line(tgt: str, op: str, exp: str, resp: int, ok: bool, sip_now: int, **extra) -> None:
            err = bit(self, "jtag_filter_lc_sigint_err_probe_o")
            good = resp == OKAY if exp == "allow" else resp != OKAY
            self.chk.ok(
                "JTAG-SIGINT",
                ctl_ok and err == 1 and good and ok,
                filter_err=err,
                tgt=tgt,
                op=op,
                exp=exp,
                resp=resp,
                sip_dis_before=f"0x{sip_ctl:016x}",
                sip_dis_after=f"0x{sip_now:016x}",
                **extra,
                **ctl,
            )

        resp, _ = await self._jtag(write=False, addr=shadow)
        line("shadow", "rd", "deny", resp, True, sip_before, addr=f"0x{shadow:08x}")
        resp, _ = await self._jtag(write=False, addr=PROGRAM_CTRL_ADDR)
        line("ifctl", "rd", "deny", resp, True, sip_before, addr=f"0x{PROGRAM_CTRL_ADDR:08x}")

        resp, _ = await self._jtag(
            write=True, addr=shadow_addr("SIP_DIS", drawn_bit // 32), wdata=1 << (drawn_bit % 32)
        )
        sip_after = await self.fd.rd64(sip_addr)
        line(
            "shadow",
            "wr",
            "deny",
            resp,
            sip_after == sip_ctl and sip_before == sip_ctl and (sip_after >> drawn_bit) & 1 == 0,
            sip_after,
            addr=f"0x{sip_addr:08x}",
            drawn_bit=drawn_bit,
        )

        resp, _ = await self._jtag(write=True, addr=READ_TIMEOUT, wdata=c2)
        cw_after = await self.fd.rd(READ_TIMEOUT)
        line(
            "ifctl",
            "wr",
            "deny",
            resp,
            cw_after & READ_TIMEOUT_FIELDS == c1,
            sip_after,
            addr=f"0x{READ_TIMEOUT:08x}",
            reg=f"0x{cw_after & READ_TIMEOUT_FIELDS:08x}",
            exp_reg=f"0x{c1:08x}",
        )

        words = token_words(TOKEN_OTHER)
        order = leg["token_order"]
        for k in order:
            addr = TOKEN_ARRAY_ADDR[CH_SIP][k]
            resp, _ = await self._jtag(write=True, addr=addr, wdata=words[k])
            line("token_word", "wr", "allow", resp, True, sip_after, addr=f"0x{addr:08x}", index=k)
        first = TOKEN_ARRAY_ADDR[CH_SIP][order[0]]
        resp, data = await self._jtag(write=False, addr=first)
        line(
            "token_word",
            "rd",
            "allow",
            resp,
            True,
            sip_after,
            addr=f"0x{first:08x}",
            data=f"0x{data:08x}",
        )
        resp, _ = await self._jtag(write=True, addr=TOKEN_EOP_ADDR, wdata=GO_MASK[CH_SIP])
        line("eop", "wr", "allow", resp, True, sip_after, addr=f"0x{TOKEN_EOP_ADDR:08x}")
        await ClockCycles(dut.clk_i, 4)
        resp, data = await self._jtag(write=False, addr=MATCH_ADDR[CH_SIP])
        line(
            "match",
            "rd",
            "allow",
            resp,
            True,
            sip_after,
            addr=f"0x{MATCH_ADDR[CH_SIP]:08x}",
            data=f"0x{data & MATCH_STATUS_MASK:02x}",
        )

        close_graded_window(self.logger)
        self._set_pin(dut, "jtag_filter_lc_sigint_inject_i", 0)
        await self._cold_reset()

    # -- scenario ------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        p = plan(TEST, seed)
        n = p.lc_raw
        for line in p.log_lines(n=f"0b{n:04b}"):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        leg_c = bool(p.leg["leg_c"])
        if leg_c:
            self.required_evidence = (*self.required_evidence, "CHK-JTAG-SIGINT")
        self.logger.info(
            "EVIDENCE-PLAN seed=%d required=%s", seed, ",".join(self.required_evidence)
        )
        close_graded_window(self.logger)
        self.fd = SepEfuseFd(self)

        chk_bind(self.chk)
        self.write_efuse_image(p.image)
        await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        await self._legs_a_b(n, p.sip_dis, p.sys_dis)

        if leg_c:
            await self._leg_c(p.leg, p.sip_dis)
        else:
            self.logger.info("CHK-JTAG-SIGINT N/A seed=%d n=0x%x", seed, n)
        self.chk.finish(f" n=0x{n:x}")
