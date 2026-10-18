# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG access policy of the eFuse windows in PROD and RMA_SIP.

RANDCFG. Run mode no_cpu (``lsu_stub_all_live``), real fuse sense. The seed draws
the state (PROD or RMA_SIP) and the image: ``SIP_DIS`` with every DBG_1 and DBG_2
bit set and drawn Function bits, a drawn ``SYS_DIS``, the RMA digests of
``TOKEN_T1`` and ``TOKEN_T2`` and ``TRANSIENT_RMA_EN`` = 0. It also draws the
control bit c and the probe bit p (two 0 spare bits), the access count N (15 to
20) and the access list: every (class, operation) cell at least once, the go
channel with the word order and the vector of each word write, the positions of the
other token-block accesses, and per denied access its address and pattern.
``dv_sim_prestage.py`` stages the image from ``env/sep_efuse_plan.py`` and the leaf
builds the same plan. JTAG and frontdoor accesses never overlap.

Contract (``hw/sys/sep/doc/otp_fuse_controller.adoc``, section Shadow Register and
JTAG Access Control; ``hw/sys/sep/doc/lifecycle_controller.adoc``, row SEP OTP
JTAG2AXIL path; ``hw/sys/sep/doc/token_processing.adoc``, sections Token Matching
Mechanism and Token Submission):

  CHK-JTAG          each JTAG access answers as its class requires. The token block
                    (three token arrays, ``TOKEN_EOP``, three match registers)
                    answers OKAY; in RMA_SIP a token word read returns the word last
                    written; a match read of a channel with a go returns the SHA-256
                    golden of its last go (Match 0x15, Mismatch 0x2a). A shadow word or
                    interface-control access answers a response that is not OKAY and
                    the target reads the same at the frontdoor before and after; the
                    bit p reads 0 at the direct read at the end. The PROD token word
                    read and write, the PROD read of ``SEC_DISABLE_TOKEN_MATCH`` and
                    the PROD read of a shadow word or ``EFUSE_PROGRAM_CTRL`` log their
                    response (``resp_graded=0``). No program command reaches
                    ``efuse_shim_command_req_o`` after a denied write. Controls: the
                    frontdoor program of c sets bit c at the same direct read and shows
                    one program command at the tap (else ``CHK-HOOK FAIL``); the read
                    address error flag reads 1 before the denied status write (else
                    ``CHK-HOOK FAIL``).
  CHK-JTAG-TOKEN    with every DBG_1 and DBG_2 bit of ``FEAT_CTRL`` at 0 (register and
                    probe), a JTAG write of ``TOKEN_T1`` into the SIP array and a go
                    give the SIP match 0x15 at a frontdoor read.

The plan draws the result of the go (Match or Mismatch, equal weight) and builds the
array content that gives it, so the go golden varies over seeds. The other value
shows in the same leaf: after a Mismatch go, the CHK-JTAG-TOKEN Match; after a SIP
Match go, the ``TOKEN_OTHER`` Mismatch that step 13 polls before ``TOKEN_T1`` (a
missing 0x2a fails CHK-JTAG-TOKEN); after a chiplet Match go, the end-of-leaf
``TOKEN_OTHER`` Mismatch, graded as ``CTRL-JTAG-MATCH-END``.

A match read of a channel with no go since power-on logs ``OBS-JTAG-MATCH-NOGO``.
The response code of a denied access and the data of a denied read are not graded.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_plan import (
    CH_CHIPLET,
    CH_SEC_DIS,
    CH_SIP,
    CODE_IDLE,
    CODE_MATCH,
    CODE_MISMATCH,
    DBG1_MASK,
    DBG2_MASK,
    GO_MASK,
    MATCH_ADDR,
    MATCH_STATUS_MASK,
    PROGRAM_CTRL_ADDR,
    READ_CTRL_ADDR,
    STATUS_ADDR,
    TOKEN_ARRAY_ADDR,
    TOKEN_EOP_ADDR,
    TOKEN_OTHER,
    TOKEN_T1,
    field_word,
    lc_state_class,
    match_code,
    plan,
    program_ctrl_word,
    read_ctrl_word,
    token_words,
    words_token,
)
from env.sep_efuse_test_lib import SenseClock, SepEfuseFd, bit, direct_word, hook_fail
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, SEP_LIFECYCLE_CTRL, register_fields

TEST = "sep_efuse_jtag_access_rand_test"

FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
DBG_MASK = DBG1_MASK | DBG2_MASK
M32 = 0xFFFF_FFFF
OKAY = 0
READ_ADDR_ERROR = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_INTERFACE_CTRL_STATUS", "efuse_read_addr_error"
)
PROGRAM_DONE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
# The first bit address past the 256 words of 32 bits.
OUT_OF_RANGE_BIT = 8192
# W = W_MULT x the measured sense time (test parameter).
W_MULT = 2
MATCH_READS = 400
SENSE_BOUND = 20_000


def _field_bits(addr: int) -> int:
    """Mask of the RDL field bits of an interface-control register."""
    _width, fields = register_fields(addr)
    return sum(((1 << f.width) - 1) << f.lsb for f in fields)


@pyuvm.test()
class sep_efuse_jtag_access_rand_test(sep_base_test):
    """PROD and RMA_SIP JTAG reaches only the token block; denied accesses change nothing."""

    required_evidence = ("CHK-JTAG", "CHK-JTAG-TOKEN")

    # -- helpers -------------------------------------------------------------

    async def _jrd(self, addr: int) -> tuple[int, int]:
        resp, data = await self.jtag_axil_op(write=False, addr=addr)
        return resp, data & M32

    async def _jwr(self, addr: int, data: int) -> int:
        resp, _ = await self.jtag_axil_op(write=True, addr=addr, wdata=data)
        return resp

    async def _jtag_poll(self, ch: str, want: int) -> tuple[int | None, list[int], list[int]]:
        """JTAG reads of the match register of ``ch`` until ``want``; Idle keeps the poll."""
        codes: list[int] = []
        resps: list[int] = []
        for _ in range(MATCH_READS):
            resp, data = await self._jrd(MATCH_ADDR[ch])
            code = data & MATCH_STATUS_MASK
            codes.append(code)
            resps.append(resp)
            if code == want:
                return code, codes, resps
        return None, codes, resps

    async def _feat_dbg(self) -> tuple[int, int]:
        reg = await self.fd.rd64(FEAT_CTRL)
        return reg, self.rd_known(cocotb.top.lcc_feat_ctrl_probe_o)

    def _jtag_line(self, ok: bool, acc: dict, exp: str, resp: int, graded: bool, **extra) -> None:
        self.chk.ok(
            "JTAG",
            ok,
            state=self.state,
            op=acc["op"],
            tgt=acc["cls"],
            addr=f"0x{acc['addr']:08x}",
            exp=exp,
            resp=resp,
            resp_graded=int(graded),
            **extra,
        )

    # -- denied accesses -----------------------------------------------------

    async def _denied(self, acc: dict) -> None:
        addr = acc["addr"]
        mask = M32 if acc["cls"] == "shadow" else _field_bits(addr)
        before = await self.fd.rd(addr)
        if acc.get("reg") == "EFUSE_INTERFACE_CTRL_STATUS" and acc["op"] == "wr":
            if not before & READ_ADDR_ERROR:
                hook_fail(
                    self.chk,
                    reason="efuse_read_addr_error is 0 before the denied status write",
                    status=f"0x{before:08x}",
                )
        if acc["op"] == "wr":
            resp = await self._jwr(addr, acc["data"])
        else:
            resp, _data = await self._jrd(addr)
        after = await self.fd.rd(addr)
        logged = (
            self.state == "PROD"
            and acc["op"] == "rd"
            and (acc["cls"] == "shadow" or acc.get("reg") == "EFUSE_PROGRAM_CTRL")
        )
        unchanged = before & mask == after & mask
        self._jtag_line(
            unchanged and (logged or resp != OKAY),
            acc,
            "deny",
            resp,
            not logged,
            data_ok="na",
            target_unchanged=int(unchanged),
            before=f"0x{before & mask:08x}",
            after=f"0x{after & mask:08x}",
            rsvd=f"0x{after & ~mask & M32:x}",
            wdata=f"0x{acc.get('data', 0):08x}" if acc["op"] == "wr" else "na",
        )

    # -- token block ---------------------------------------------------------

    async def _token_access(self, acc: dict) -> None:
        prod = self.state == "PROD"
        if acc["cls"] == "token_word" and acc["op"] == "wr":
            resp = await self._jwr(acc["addr"], acc["data"])
            self.last_wr[(acc["channel"], acc["index"])] = acc["data"]
            self._jtag_line(
                prod or resp == OKAY,
                acc,
                "allow",
                resp,
                not prod,
                data_ok="na",
                target_unchanged="na",
                channel=acc["channel"],
                index=acc["index"],
                vector=acc["vector"],
            )
        elif acc["cls"] == "token_word":
            resp, data = await self._jrd(acc["addr"])
            last = self.last_wr[(acc["channel"], acc["index"])]
            extra = {"data": f"0x{data:08x}", "last_wr": f"0x{last:08x}"}
            if prod:
                self._jtag_line(
                    True, acc, "allow", resp, False, data_ok="na", target_unchanged="na", **extra
                )
            else:
                self._jtag_line(
                    resp == OKAY and data == last,
                    acc,
                    "allow",
                    resp,
                    True,
                    data_ok=int(data == last),
                    target_unchanged="na",
                    **extra,
                )
        elif acc["cls"] == "eop":
            ch = acc["channel"]
            content = [self.last_wr[(ch, k)] for k in range(8)]
            golden = match_code(ch, words_token(content), self.p.image)
            pre = await self.fd.rd(MATCH_ADDR[ch]) & MATCH_STATUS_MASK
            resp = await self._jwr(TOKEN_EOP_ADDR, acc["data"])
            code, codes, resps = await self._jtag_poll(ch, golden)
            others = [c for c in codes if c not in (CODE_IDLE, golden)]
            ok = (
                resp == OKAY
                and code == golden
                and golden == acc["golden"]
                and pre != golden
                and not others
                and all(r == OKAY for r in resps)
            )
            self.last_result[ch] = golden
            self._jtag_line(
                ok,
                acc,
                "allow",
                resp,
                True,
                data_ok=int(code == golden),
                target_unchanged="na",
                channel=ch,
                golden=f"0x{golden:02x}",
                go_result=f"0x{acc['golden']:02x}",
                pre_go=f"0x{pre:02x}",
                polls=len(codes),
                codes=",".join(f"{c:02x}" for c in codes[-4:]),
            )
        else:
            ch = acc["channel"]
            resp, data = await self._jrd(acc["addr"])
            code = data & MATCH_STATUS_MASK
            logged = prod and ch == CH_SEC_DIS
            if ch in self.last_result:
                want = self.last_result[ch]
                self._jtag_line(
                    (logged or resp == OKAY) and code == want,
                    acc,
                    "allow",
                    resp,
                    not logged,
                    data_ok=int(code == want),
                    target_unchanged="na",
                    channel=ch,
                    data=f"0x{code:02x}",
                    golden=f"0x{want:02x}",
                )
            else:
                self.chk.obs("JTAG-MATCH-NOGO", state=self.state, channel=ch, data=f"0x{code:02x}")
                self._jtag_line(
                    logged or resp == OKAY,
                    acc,
                    "allow",
                    resp,
                    not logged,
                    data_ok="na",
                    target_unchanged="na",
                    channel=ch,
                )

    async def _jtag_token(self, ch: str, token: int) -> list[int]:
        resps = [
            await self._jwr(TOKEN_ARRAY_ADDR[ch][k], w) for k, w in enumerate(token_words(token))
        ]
        resps.append(await self._jwr(TOKEN_EOP_ADDR, GO_MASK[ch]))
        return resps

    # -- scenario ------------------------------------------------------------

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        p = plan(TEST, seed)
        self.p = p
        self.state = lc_state_class(p.lc_raw)
        for line in p.log_lines(state=self.state):
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        self.logger.info(
            "EVIDENCE-PLAN seed=%d required=%s", seed, ",".join(self.required_evidence)
        )
        close_graded_window(self.logger)
        self.fd = SepEfuseFd(self)
        self.last_wr: dict[tuple[str, int], int] = {}
        self.last_result: dict[str, int] = {}
        c_bit, p_bit = p.leg["spare_c"], p.leg["spare_p"]

        self.write_efuse_image(p.image)
        sense = SenseClock(self).start()
        await self.bring_up_no_cpu(max_cycles=SENSE_BOUND)
        if not sense.done:
            sense.stop()
            raise AssertionError("the sense counter did not see the sense-done rise")
        sense_clks = sense.clocks
        w = W_MULT * sense_clks
        stm = bit(self, "secure_tm_o")
        self.logger.info(
            "WINDOW W=%d sense_clks=%d mult=%d secure_tm_o=%d", w, sense_clks, W_MULT, stm
        )
        self.chk.ctrl("JTAG-STM", stm == 0, secure_tm_o=stm)

        feat, probe = await self._feat_dbg()
        if feat != probe or feat & DBG_MASK:
            self.chk.ok(
                "JTAG-TOKEN",
                False,
                state=self.state,
                reason="a debug bit of FEAT_CTRL is open",
                feat=f"0x{feat:016x}",
                probe=f"0x{probe:016x}",
            )
            self.chk.finish()

        # Status flag that a denied write could clear.
        await self.fd.wr(READ_CTRL_ADDR, read_ctrl_word(OUT_OF_RANGE_BIT))
        await ClockCycles(dut.clk_i, w)
        status = await self.fd.rd(STATUS_ADDR)
        await self.fd.wr(READ_CTRL_ADDR, 0)
        if not status & READ_ADDR_ERROR:
            hook_fail(
                self.chk, reason="efuse_read_addr_error did not set", status=f"0x{status:08x}"
            )
        self.logger.info("READ-ADDR-ERROR status=0x%08x", status)

        # Control program of c.
        self.shim = SepShimCmdMonitor().start()
        await ClockCycles(dut.clk_i, 2)
        mark = self.shim.mark()
        await self.fd.wr(PROGRAM_CTRL_ADDR, program_ctrl_word(c_bit["addr"]))
        await ClockCycles(dut.clk_i, w)
        pg = await self.fd.rd(PROGRAM_CTRL_ADDR)
        await self.fd.wr(PROGRAM_CTRL_ADDR, 0)
        ctl_cmds = self.shim.programs_since(mark)
        ctl_cmd = int(len(ctl_cmds) == 1 and ctl_cmds[0].address == c_bit["addr"])
        c_word = await direct_word(self, field_word(c_bit["field"]) + c_bit["word"])
        p_word0 = await direct_word(self, field_word(p_bit["field"]) + p_bit["word"])
        ctl_bit_read = (c_word >> c_bit["bit"]) & 1
        if not ctl_cmd:
            hook_fail(
                self.chk,
                reason="the control program shows no single program command",
                cmds=len(ctl_cmds),
            )
        self.chk.ctrl(
            "JTAG-PROGRAM",
            bool(pg & PROGRAM_DONE) and ctl_bit_read == 1 and (p_word0 >> p_bit["bit"]) & 1 == 0,
            program_ctrl=f"0x{pg:08x}",
            ctl_bit_read=ctl_bit_read,
            p_bit_read=(p_word0 >> p_bit["bit"]) & 1,
        )

        # Denied accesses, then the token block, in the drawn order.
        open_graded_window(TEST, self.logger)
        deny_mark = self.shim.mark()
        for acc in p.leg["denied"]:
            await self._denied(acc)
        await ClockCycles(dut.clk_i, w)
        p_word = await direct_word(self, field_word(p_bit["field"]) + p_bit["word"])
        denied_progs = self.shim.programs_since(deny_mark)
        p_bit_read = (p_word >> p_bit["bit"]) & 1
        for acc in p.leg["token_block"]:
            await self._token_access(acc)

        # Token match with every debug bit closed.
        pre_resps: list[int] = []
        if self.last_result.get(CH_SIP) == CODE_MATCH:
            pre_resps = await self._jtag_token(CH_SIP, TOKEN_OTHER)
            code, _codes, more = await self._jtag_poll(CH_SIP, CODE_MISMATCH)
            pre_resps += more
            if code != CODE_MISMATCH:
                pre_resps.append(-1)
        t1_resps = await self._jtag_token(CH_SIP, TOKEN_T1)
        code, codes, poll_resps = await self._jtag_poll(CH_SIP, CODE_MATCH)
        fd_match = await self.fd.rd(MATCH_ADDR[CH_SIP]) & MATCH_STATUS_MASK
        feat2, probe2 = await self._feat_dbg()
        self.last_result[CH_SIP] = CODE_MATCH
        resps = pre_resps + t1_resps + poll_resps
        self.chk.ok(
            "JTAG-TOKEN",
            all(r == OKAY for r in resps)
            and code == CODE_MATCH
            and fd_match == CODE_MATCH
            and feat & DBG_MASK == 0
            and feat2 & DBG_MASK == 0
            and probe2 == feat2,
            state=self.state,
            feat=f"0x{feat2:016x}",
            feat_before=f"0x{feat:016x}",
            dbg_open=f"0x{feat2 & DBG_MASK:x}",
            sip_match=f"0x{fd_match:02x}",
            jtag_polls=len(codes),
            non_okay=sum(1 for r in resps if r != OKAY),
        )
        close_graded_window(self.logger)

        self.chk.ok(
            "JTAG",
            p_bit_read == 0 and ctl_bit_read == 1 and ctl_cmd == 1 and not denied_progs,
            state=self.state,
            tgt="otp_word_p",
            p_bit_read=p_bit_read,
            ctl_bit_read=ctl_bit_read,
            ctl_cmd=ctl_cmd,
            prog_cmds_after_denied=len(denied_progs),
        )

        # End the held matches: the next leaf starts with none.
        for ch in (CH_SIP, CH_CHIPLET):
            if self.last_result.get(ch) != CODE_MATCH:
                continue
            resps = await self._jtag_token(ch, TOKEN_OTHER)
            got = None
            reads = 0
            for reads in range(1, MATCH_READS + 1):
                got = await self.fd.rd(MATCH_ADDR[ch]) & MATCH_STATUS_MASK
                if got == CODE_MISMATCH:
                    break
            self.chk.ctrl(
                "JTAG-MATCH-END",
                got == CODE_MISMATCH and all(r == OKAY for r in resps),
                state=self.state,
                channel=ch,
                code=f"0x{(got or 0):02x}",
                reads=reads,
                non_okay=sum(1 for r in resps if r != OKAY),
            )
            self.last_result[ch] = CODE_MISMATCH
        await self.shim.stop()
        self.chk.finish(f" state={self.state}")
