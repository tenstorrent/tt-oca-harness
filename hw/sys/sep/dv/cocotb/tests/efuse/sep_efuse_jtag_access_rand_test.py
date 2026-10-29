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
other token-block accesses, and per denied access its address and pattern. The
required interface-control write of every leaf is a denied ``EFUSE_PROGRAM_CTRL``
program of p, so the p read at the end grades a refused burn in every leaf.
``dv_sim_prestage.py`` stages the image from ``env/sep_efuse_plan.py`` and the leaf
builds the same plan. JTAG and frontdoor accesses never overlap, except one
frontdoor read and one JTAG read of the shadow word of p, started on the same clock
at the end of the leaf. CHK-JTAG-CONCURRENT grades the JTAG response not OKAY and the
frontdoor read OKAY with the staged word; ``CTRL-JTAG-CONCURRENT-OVERLAP`` requires
both AR handshakes before either read completes; ``OBS-EF-ARB-CONCURRENT`` logs the JTAG data,
the clock each read completes on and the command count at the post-guard tap.

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
                    bit p reads 0 at the direct read at the end. PROD and RMA_SIP
                    grade the same way. No program command reaches
                    ``efuse_shim_command_req_o`` after a denied write. Controls: the
                    frontdoor program of c sets bit c at the same direct read and shows
                    one program command at the tap (else ``CHK-HOOK FAIL``); the read
                    address error flag reads 1 before the denied status write (else
                    ``CHK-HOOK FAIL``); at the end of the leaf the pattern of each
                    denied shadow write, ``EFUSE_READ_CTRL`` write and status write,
                    written through the frontdoor, changes the readback
                    (``CTRL-JTAG-DENY-WRITE``): for the status write the flag is set
                    again by an out-of-range read, reads 1, and the frontdoor clear
                    makes it read 0.
  CHK-JTAG-TOKEN    with every DBG_1 and DBG_2 bit of ``FEAT_CTRL`` at 0 (register and
                    probe), a JTAG write of ``TOKEN_T1`` into the SIP array and a go
                    give the SIP match 0x15 at a frontdoor read.
  CHK-JTAG-CONCURRENT  the concurrent pair at the end of the leaf: JTAG response not
                    OKAY, frontdoor response OKAY with the staged word.

The plan draws the result of the go (Match or Mismatch, equal weight) and builds the
array content that gives it, so the go golden varies over seeds. The other value
shows in the same leaf: after a Mismatch go, the CHK-JTAG-TOKEN Match; after a SIP
Match go, the ``TOKEN_OTHER`` Mismatch that step 13 polls before ``TOKEN_T1`` (a
missing 0x2a fails CHK-JTAG-TOKEN); after a chiplet Match go, the end-of-leaf
``TOKEN_OTHER`` Mismatch, graded as ``CTRL-JTAG-MATCH-END``. Step 13 polls the
``TOKEN_OTHER`` Mismatch unless the SIP go of the leaf gave a Mismatch, so a leaf
whose go is on the chiplet channel runs it too: the 0x15 of CHK-JTAG-TOKEN always
follows a known 0x2a on the SIP channel.

A match read of a channel with no go since power-on logs ``OBS-JTAG-MATCH-NOGO``.
The response code of a denied access and the data of a denied read are not graded.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_bank_watch import SepShimCmdMonitor
from env.sep_efuse_image import SHADOW_BASE
from env.sep_efuse_plan import (
    CH_CHIPLET,
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
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

TEST = "sep_efuse_jtag_access_rand_test"

FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
DBG_MASK = DBG1_MASK | DBG2_MASK
M32 = 0xFFFF_FFFF
OKAY = 0
READ_ADDR_ERROR = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_INTERFACE_CTRL_STATUS", "efuse_read_addr_error"
)
PROGRAM_DONE = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_PROGRAM_CTRL", "program_done")
# RW fields of EFUSE_READ_CTRL that hold a written value (efuse_read_go is RW 1P).
READ_CTRL_RW = EFUSE_INTERFACE_CTRL.field_mask(
    "EFUSE_READ_CTRL", "read_enable"
) | EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_CTRL", "efuse_addr")
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

    required_evidence = ("CHK-JTAG", "CHK-JTAG-TOKEN", "CHK-JTAG-CONCURRENT")

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

    def _jtag_line(self, ok: bool, acc: dict, exp: str, resp: int, **extra) -> None:
        self.chk.ok(
            "JTAG",
            ok,
            state=self.state,
            op=acc["op"],
            tgt=acc["cls"],
            addr=f"0x{acc['addr']:08x}",
            exp=exp,
            resp=resp,
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
        unchanged = before & mask == after & mask
        self._jtag_line(
            unchanged and resp != OKAY,
            acc,
            "deny",
            resp,
            data_ok="na",
            target_unchanged=int(unchanged),
            before=f"0x{before & mask:08x}",
            after=f"0x{after & mask:08x}",
            rsvd=f"0x{after & ~mask & M32:x}",
            wdata=f"0x{acc.get('data', 0):08x}" if acc["op"] == "wr" else "na",
        )

    # -- token block ---------------------------------------------------------

    async def _token_access(self, acc: dict) -> None:
        if acc["cls"] == "token_word" and acc["op"] == "wr":
            resp = await self._jwr(acc["addr"], acc["data"])
            self.last_wr[(acc["channel"], acc["index"])] = acc["data"]
            self._jtag_line(
                resp == OKAY,
                acc,
                "allow",
                resp,
                data_ok="na",
                target_unchanged="na",
                channel=acc["channel"],
                index=acc["index"],
                vector=acc["vector"],
            )
        elif acc["cls"] == "token_word":
            resp, data = await self._jrd(acc["addr"])
            last = self.last_wr[(acc["channel"], acc["index"])]
            self._jtag_line(
                resp == OKAY and data == last,
                acc,
                "allow",
                resp,
                data_ok=int(data == last),
                target_unchanged="na",
                data=f"0x{data:08x}",
                last_wr=f"0x{last:08x}",
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
            if ch in self.last_result:
                want = self.last_result[ch]
                self._jtag_line(
                    resp == OKAY and code == want,
                    acc,
                    "allow",
                    resp,
                    data_ok=int(code == want),
                    target_unchanged="na",
                    channel=ch,
                    data=f"0x{code:02x}",
                    golden=f"0x{want:02x}",
                )
            else:
                self.chk.obs("JTAG-MATCH-NOGO", state=self.state, channel=ch, data=f"0x{code:02x}")
                self._jtag_line(
                    resp == OKAY,
                    acc,
                    "allow",
                    resp,
                    data_ok="na",
                    target_unchanged="na",
                    channel=ch,
                )

    async def _status_clear_control(self, w: int) -> None:
        """Control of "target unchanged" for the denied status write: the same clear,
        written through the frontdoor, drops ``efuse_read_addr_error``.

        The flag is set again first by the out-of-range read of step 5 and must read 1,
        so a frontdoor clear that the DUT ignores leaves it at 1 and the control fails.
        """
        accs = [
            a
            for a in self.p.leg["denied"]
            if a["op"] == "wr" and a.get("reg") == "EFUSE_INTERFACE_CTRL_STATUS"
        ]
        if not accs:
            return
        await self.fd.wr(READ_CTRL_ADDR, read_ctrl_word(OUT_OF_RANGE_BIT))
        await ClockCycles(cocotb.top.clk_i, w)
        await self.fd.wr(READ_CTRL_ADDR, 0)
        before = await self.fd.rd(STATUS_ADDR)
        await self.fd.wr(STATUS_ADDR, accs[0]["data"])
        after = await self.fd.rd(STATUS_ADDR)
        self.chk.ctrl(
            "JTAG-DENY-WRITE",
            bool(before & READ_ADDR_ERROR) and not after & READ_ADDR_ERROR,
            state=self.state,
            tgt="ifctl",
            reg="EFUSE_INTERFACE_CTRL_STATUS",
            addr=f"0x{STATUS_ADDR:08x}",
            wdata=f"0x{accs[0]['data']:08x}",
            before=f"0x{before & READ_ADDR_ERROR:08x}",
            after=f"0x{after & READ_ADDR_ERROR:08x}",
        )

    async def _deny_write_controls(self, w: int) -> None:
        """Control of "target unchanged" for the denied status, ``EFUSE_READ_CTRL`` and
        shadow writes: the same pattern written through the frontdoor changes the readback.

        Runs after every graded access of the leaf, because a shadow write is set-only and
        cannot be undone. The status clear goes first, then ``EFUSE_READ_CTRL`` (its RW
        fields read back the written ``read_enable`` and ``efuse_addr`` after a write of 0
        and then of the pattern; it is then written 0), so a lock bit that a shadow
        control sets cannot refuse their reads.
        """
        await self._status_clear_control(w)
        seen: set[tuple[int, int]] = set()
        accs = [a for a in self.p.leg["denied"] if a["op"] == "wr"]
        rd_ctl = [a for a in accs if a.get("reg") == "EFUSE_READ_CTRL"]
        shadow = [a for a in accs if a["cls"] == "shadow"]
        for acc in rd_ctl + shadow:
            key = (acc["addr"], acc["data"])
            if key in seen:
                continue
            seen.add(key)
            addr, data = acc["addr"], acc["data"]
            if acc["cls"] != "shadow":
                await self.fd.wr(addr, 0)
            before = await self.fd.rd(addr)
            await self.fd.wr(addr, data)
            if acc["cls"] == "shadow":
                after = await self.fd.rd(addr)
                seen_ok = before & data == 0 and after & data == data
                mask = data
            else:
                await ClockCycles(cocotb.top.clk_i, w)
                after = await self.fd.rd(addr)
                await self.fd.wr(addr, 0)
                mask = READ_CTRL_RW
                seen_ok = before & mask != data & mask and after & mask == data & mask
            self.chk.ctrl(
                "JTAG-DENY-WRITE",
                seen_ok,
                state=self.state,
                tgt=acc["cls"],
                reg=acc.get("field", acc.get("reg", "na")),
                addr=f"0x{addr:08x}",
                wdata=f"0x{data:08x}",
                before=f"0x{before & mask:08x}",
                after=f"0x{after & mask:08x}",
            )

    async def _concurrent_read(self, word: int, ignore_mask: int) -> None:
        """A frontdoor read and a JTAG read of one shadow word, started on the same clock.

        CHK-JTAG-CONCURRENT: the JTAG read answers a response that is not OKAY
        (``otp_fuse_controller.adoc``, Shadow Register and JTAG Access Control), and the
        frontdoor read answers OKAY with the staged word, outside ``ignore_mask`` (the
        bit c when it shares the word). ``OBS-EF-ARB-CONCURRENT`` logs the JTAG data,
        the clock each read completes on and the command count at the post-guard tap:
        the specification does not state the arbitration of the two masters or the data
        of a denied read. ``CTRL-JTAG-CONCURRENT-OVERLAP`` requires that each read had
        its AR handshake (``s_axi_ar*``, ``j_axi_ar*``) no later than the clock the
        other read completed on, so both requests were outstanding together.
        """
        dut = cocotb.top
        addr = SHADOW_BASE + 4 * word
        done: dict[str, int] = {}
        ar: dict[str, int] = {}
        clk = {"n": 0}
        ar_sigs = {
            "fd": (dut.s_axi_arvalid, dut.s_axi_arready),
            "jtag": (dut.j_axi_arvalid, dut.j_axi_arready),
        }

        async def _count() -> None:
            while True:
                await RisingEdge(dut.clk_i)
                clk["n"] += 1
                for k, (v, r) in ar_sigs.items():
                    if (
                        k not in ar
                        and self.rd(v, allow_unknown=True)
                        and self.rd(r, allow_unknown=True)
                    ):
                        ar[k] = clk["n"]

        async def _fd() -> SepAxiAccessSeq:
            seq = await self.fd.access(SepAxiOp.READ, addr, ungraded_read=True)
            done["fd"] = clk["n"]
            return seq

        async def _jtag() -> tuple[int, int]:
            res = await self._jrd(addr)
            done["jtag"] = clk["n"]
            return res

        mark = self.shim.mark()
        await RisingEdge(dut.clk_i)
        counter = cocotb.start_soon(_count())
        fd_task = cocotb.start_soon(_fd())
        jtag_task = cocotb.start_soon(_jtag())
        fd_seq = await fd_task
        jtag_resp, jtag_data = await jtag_task
        counter.cancel()
        await ClockCycles(dut.clk_i, 2)
        fd_ar, jtag_ar = ar.get("fd"), ar.get("jtag")
        self.chk.ctrl(
            "JTAG-CONCURRENT-OVERLAP",
            fd_ar is not None
            and jtag_ar is not None
            and fd_ar <= done["jtag"]
            and jtag_ar <= done["fd"],
            state=self.state,
            word=word,
            fd_ar_clk="none" if fd_ar is None else fd_ar,
            jtag_ar_clk="none" if jtag_ar is None else jtag_ar,
            fd_done_clk=done["fd"],
            jtag_done_clk=done["jtag"],
        )
        fd_rdata = fd_seq.rdata & M32
        staged = self.p.image.words[word]
        keep = ~ignore_mask & M32
        self.chk.ok(
            "JTAG-CONCURRENT",
            jtag_resp != OKAY and fd_seq.resp_code == OKAY and fd_rdata & keep == staged & keep,
            state=self.state,
            word=word,
            jtag_resp=jtag_resp,
            fd_resp=fd_seq.resp_code,
            fd_rdata=f"0x{fd_rdata:08x}",
            staged=f"0x{staged:08x}",
            ignore=f"0x{ignore_mask:08x}",
        )
        self.chk.obs(
            "EF-ARB-CONCURRENT",
            state=self.state,
            word=word,
            jtag_rdata=f"0x{jtag_data:08x}",
            fd_done_clk=done["fd"],
            jtag_done_clk=done["jtag"],
            shim_cmds=len(self.shim.commands_since(mark)),
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
            "INFO-EVIDENCE-PLAN seed=%d required=%s", seed, ",".join(self.required_evidence)
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
            "INFO-WINDOW W=%d sense_clks=%d mult=%d secure_tm_o=%d", w, sense_clks, W_MULT, stm
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
        self.logger.info("INFO-READ-ADDR-ERROR status=0x%08x", status)

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

        # Token match with every debug bit closed. The 0x15 must follow a known
        # 0x2a on the SIP channel: the SIP code has no reset value after power-on,
        # so only a graded Mismatch go of this leaf skips the TOKEN_OTHER step.
        pre_resps: list[int] = []
        if self.last_result.get(CH_SIP) != CODE_MISMATCH:
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

        p_writes = sum(
            1 for a in p.leg["denied"] if a["op"] == "wr" and a.get("reg") == "EFUSE_PROGRAM_CTRL"
        )
        self.chk.ok(
            "JTAG",
            p_writes >= 1
            and p_bit_read == 0
            and ctl_bit_read == 1
            and ctl_cmd == 1
            and not denied_progs,
            state=self.state,
            tgt="otp_word_p",
            p_writes=p_writes,
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
        await self._deny_write_controls(w)
        p_word_idx = field_word(p_bit["field"]) + p_bit["word"]
        c_word_idx = field_word(c_bit["field"]) + c_bit["word"]
        await self._concurrent_read(
            p_word_idx, (1 << c_bit["bit"]) if c_word_idx == p_word_idx else 0
        )
        await self.shim.stop()
        self.chk.finish(f" state={self.state}")
