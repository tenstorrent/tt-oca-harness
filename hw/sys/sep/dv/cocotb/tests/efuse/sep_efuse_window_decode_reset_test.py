# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Interface-control and token window reset values, read-write behaviour, and window decode.

After a real fuse sense the interface-control window (``0x1093_0400``, 28 bytes) and
the token window (``0x1093_0500``) hold the described registers with their reset
values and read-write behaviour. No access past the interface-control extent and no
access in the reserved span at ``0x1093_0600`` changes ``EFUSE_INTERFACE_CTRL_STATUS``,
``EFUSE_PROGRAM_CTRL`` or ``EFUSE_READ_CTRL``, or aliases a software-writable shadow
word.

Sources: ``hw/sys/sep/regs/gen/adoc/memory_map.adoc`` (rows eFuse Interface Control,
eFuse Token Registers, Reserved); ``hw/ip/efuse/regs/gen/adoc/efuse_interface_ctrl.adoc``
(reset and access columns); ``hw/ip/efuse/regs/gen/adoc/efuse_mmr.adoc`` (token arrays,
``TOKEN_MATCH_FAULT``); ``hw/sys/sep/regs/gen/adoc/blocks/sep_lifecycle_ctrl.adoc``
(``FEAT_CTRL``, access R); ``hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc``
(registers with access RW); ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (section Fuse
Fields, row ``SYS_DIS``: set-only OR-merge; section Fuse Sensing and Boot Sequencing,
the sense-completion indicator).

Image: fixed TEST_DEV image of ``env/sep_efuse_plan.py`` (one fixed filter-legal
disable-vector pair, each 256-bit field its own fixed vector, no lock bit), written
before the first reset. Draws: ``plan(test, seed)`` (timeout counts, control-register
patterns, token word orders, past-extent offsets, reserved-span addresses, control
word w).

Checkers:
  CHK-CSR-RESET   the five interface-control registers read their reset values after
                  sense done and answer OKAY. Zero-reset rows count on a four-state
                  simulator only; on Verilator they log ``OBS-CSR-RESET LOG``.
  CHK-CSR-RW      ``EFUSE_PROGRAM_CTRL`` and ``EFUSE_READ_CTRL`` read back the drawn
                  pattern; a write of 0x71 to the status register leaves 0x1.
  CHK-TOKEN-RW    each token array reads back the eight words written in drawn order.
  CHK-FEAT-RO     ``FEAT_CTRL`` keeps its value after a write of its complement.
  CHK-WIN-DECODE  past-extent and reserved accesses change no graded register and no
                  software-writable shadow word; the control write of a ``SYS_DIS``
                  word reads back all ones; the 256-word sweep matches the model.

Log-only: the response and read data past the extent and in the reserved span
(``OBS-WIN-RESP LOG``), the two read-data registers (``OBS-CSR-DATA LOG``), the timeout
write and readback (``OBS-CSR-RW LOG``), ``TOKEN_MATCH_FAULT`` and the match registers
(``OBS-TOKEN-FAULT LOG``). The FCOV graded window is closed around these controls.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import SHADOW_BASE
from env.sep_efuse_plan import (
    CHANNELS,
    MATCH_ADDR,
    PROGRAM_CTRL_ADDR,
    READ_CTRL_ADDR,
    STATUS_ADDR,
    T_WINDOW_DECODE,
    TOKEN_ARRAY_ADDR,
    TOKEN_MATCH_FAULT_ADDR,
    TOKEN_OTHER,
    TOKEN_T1,
    TOKEN_T2,
    plan,
    shadow_addr,
    token_words,
)
from env.sep_efuse_test_lib import SepEfuseFd, log_line
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from sep_base_test import sep_base_test
from sep_reg_meta import EFUSE_INTERFACE_CTRL, SEP_LIFECYCLE_CTRL

TEST = T_WINDOW_DECODE

_IC = EFUSE_INTERFACE_CTRL
_STATUS = "EFUSE_INTERFACE_CTRL_STATUS"
_PG = "EFUSE_PROGRAM_CTRL"
_RD = "EFUSE_READ_CTRL"
_RD_TMO = "EFUSE_READ_REQ_TIMEOUT"
_PG_TMO = "EFUSE_PROGRAM_REQ_TIMEOUT"
_RESET_REGS = (_STATUS, _PG, _RD, _RD_TMO, _PG_TMO)
_DATA_REGS = ("EFUSE_PROGRAM_INTERFACE_READ_DATA", "EFUSE_READ_INTERFACE_READ_DATA")

# Reset values from the reset column of efuse_interface_ctrl.adoc. efuse_sense_done
# has no reset value: its description and the sense-completion indicator of
# otp_fuse_controller.adoc give 1 after sense done.
_SENSE_DONE = _IC.field_mask(_STATUS, "efuse_sense_done")
_RESET_EXP = {
    _STATUS: _SENSE_DONE | (_IC.reset_raw(_STATUS) & _IC.mask32(_STATUS) & ~_SENSE_DONE),
    _PG: _IC.reset32(_PG),
    _RD: _IC.reset32(_RD),
    _RD_TMO: _IC.reset32(_RD_TMO),
    _PG_TMO: _IC.reset32(_PG_TMO),
}
# Independent anchor: the values the contract states for the RDL reset column.
if _RESET_EXP != {_STATUS: 0x1, _PG: 0x0, _RD: 0x0, _RD_TMO: 0x0080_0000, _PG_TMO: 0x0080_0000}:
    raise RuntimeError(f"interface-control reset values {_RESET_EXP} differ from the contract")

_STATUS_RO_WRITE = 0x0000_0071  # bits 0, 4, 5, 6 at 1; the three clear bits at 0
_FEAT_CTRL = SEP_LIFECYCLE_CTRL.addr("FEAT_CTRL")
_FEAT_MASK = SEP_LIFECYCLE_CTRL.mask("FEAT_CTRL")
_SHADOW_LAST = SHADOW_BASE + 0x3FC
_PAST_EXTENT_PINNED = STATUS_ADDR + 0x1C
_RSVD_PINNED = (SHADOW_BASE + 0x600, SHADOW_BASE + 0xC1C, SHADOW_BASE + 0xFFFC)
_ARRAY_TOKEN = {"sip": TOKEN_T1, "chiplet": TOKEN_T2, "sec_dis": TOKEN_OTHER}
_ARRAY_TAG = {"sip": "sip", "chiplet": "chp", "sec_dis": "sdis"}
_RESP = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", -1: "NONE"}
_RESP_DECERR = 3
_WORD = 0xFFFF_FFFF


@pyuvm.test()
class sep_efuse_window_decode_reset_test(sep_base_test):
    """Interface-control and token window registers after sense, and the window decode."""

    required_evidence = (
        "CHK-CSR-RESET",
        "CHK-CSR-RW",
        "CHK-TOKEN-RW",
        "CHK-FEAT-RO",
        "CHK-WIN-DECODE",
    )

    async def _rd(self, addr: int, *, ungraded: bool = False) -> tuple[int, bool, int]:
        """One 32-bit frontdoor read: (rdata, OKAY, response code).

        ``ungraded`` lets a non-OKAY response through the scoreboard; the leaf logs it.
        """
        seq = await self.fd.access(SepAxiOp.READ, addr, ungraded_read=ungraded)
        return seq.rdata & _WORD, bool(seq.resp_ok), int(seq.resp_code)

    async def _wr(self, addr: int, data: int, *, ungraded: bool = False) -> tuple[bool, int]:
        """One 32-bit frontdoor write: (OKAY, response code)."""
        seq = await self.fd.access(SepAxiOp.WRITE, addr, data, unverified_write=ungraded)
        return bool(seq.resp_ok), int(seq.resp_code)

    def _log(self, tag: str, **fields: object) -> None:
        log_line(self.logger, tag, self.seed, **fields)

    async def _graded_regs(self) -> dict[str, int]:
        """STATUS, EFUSE_PROGRAM_CTRL and EFUSE_READ_CTRL, field bits only."""
        out = {}
        for name, addr in ((_STATUS, STATUS_ADDR), (_PG, PROGRAM_CTRL_ADDR), (_RD, READ_CTRL_ADDR)):
            v, _ok, _c = await self._rd(addr)
            out[name] = v & _IC.mask32(name)
        return out

    async def _unmapped(self, access):
        """Run one access whose response code is logged and not graded.

        The AXI monitor fails a DECERR beat it was not told to expect. The
        response here is not graded, so the access takes one credit and hands it
        back when the answer is not DECERR (a credit left standing would hide a
        later unexpected DECERR).
        """
        mon = self.env.axi_monitor
        mon.arm_expected_decerr(1)
        result = await access()
        if result[-1] != _RESP_DECERR:
            mon.release_expected_decerr(1)
        return result

    async def _decode_access(self, win: str, addr: int) -> None:
        """Procedure step 14 for one address: read, then write the complement."""
        off = addr & 0x3FF
        word_addr = SHADOW_BASE + off
        graded = off in self.rw_offsets
        exp_word = self.model[off // 4]
        exp_regs = {name: v & _IC.mask32(name) for name, v in self.reg_model.items()}
        wdata = ~exp_word & _WORD

        regs0 = await self._graded_regs()
        word0, _ok, _c = await self._rd(word_addr)
        for op in ("rd", "wr"):
            if op == "rd":
                rdata, _ok, code = await self._unmapped(lambda: self._rd(addr, ungraded=True))
                self._log(
                    "OBS-WIN-RESP",
                    win=win,
                    addr=f"0x{addr:08x}",
                    op="rd",
                    resp=_RESP.get(code, code),
                    rdata=f"0x{rdata:08x}",
                )
            else:
                _ok, code = await self._unmapped(lambda: self._wr(addr, wdata, ungraded=True))
                self._log(
                    "OBS-WIN-RESP",
                    win=win,
                    addr=f"0x{addr:08x}",
                    op="wr",
                    resp=_RESP.get(code, code),
                    rdata="na",
                )
            regs = await self._graded_regs()
            word, _ok, _c = await self._rd(word_addr)
            regs_ok = regs == exp_regs and (op == "wr" or regs0 == exp_regs)
            word_ok = word == exp_word and (op == "wr" or word0 == exp_word)
            self.chk.ok(
                "WIN-DECODE",
                regs_ok and (word_ok or not graded),
                win=win,
                addr=f"0x{addr:08x}",
                op=op,
                wdata=f"0x{wdata:08x}" if op == "wr" else "na",
                alias_graded=int(graded),
                alias_addr=f"0x{word_addr:08x}",
                alias_exp=f"0x{exp_word:08x}",
                alias_got=f"0x{word:08x}",
                regs_equal=int(regs_ok),
                regs_got=",".join(f"0x{regs[n]:08x}" for n in (_STATUS, _PG, _RD)),
                regs_exp=",".join(f"0x{exp_regs[n]:08x}" for n in (_STATUS, _PG, _RD)),
            )

    async def _control_reads(self, tag: str) -> None:
        """Procedure step 13: the last shadow word and STATUS answer OKAY with the model."""
        for addr, exp, mask in (
            (_SHADOW_LAST, self.model[0xFF], _WORD),
            (STATUS_ADDR, _RESET_EXP[_STATUS], _IC.mask32(_STATUS)),
        ):
            got, ok, code = await self._rd(addr, ungraded=True)
            cmp = field_compare(got, exp, mask)
            self.chk.ok(
                "WIN-DECODE",
                ok and cmp.ok,
                win="ctl",
                when=tag,
                addr=f"0x{addr:08x}",
                op="rd",
                resp=_RESP.get(code, code),
                got=f"0x{got & mask:08x}",
                exp=f"0x{exp:08x}",
                rsvd=f"0x{cmp.rsvd:x}",
            )

    async def run_scenario(self) -> None:
        dut = cocotb.top
        self.seed = seed = self.random_seed()
        p = plan(TEST, seed)
        for line in p.log_lines():
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        four_state = "verilator" not in str(cocotb.SIM_NAME).lower()
        close_graded_window(self.logger)

        # Step 2-3: fixed image before the first reset; strap 0 (idle default); sense.
        self.write_efuse_image(p.image)
        self.model = list(p.image.words)
        self.rw_offsets = set(p.leg["rw_shadow_offsets"])
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        if not self.rd_known(dut.sep_fuse_sense_done_o):
            raise AssertionError("sep_fuse_sense_done_o is low after bring-up")

        # Step 4: reset reads, before any write of the leaf.
        open_graded_window(TEST, self.logger)
        for name in _RESET_REGS:
            addr = _IC.addr(name)
            got, ok, code = await self._rd(addr, ungraded=True)
            mask = _IC.mask32(name)
            cmp = field_compare(got, _RESET_EXP[name], mask)
            if _RESET_EXP[name] == 0 and not four_state:
                self._log(
                    "OBS-CSR-RESET",
                    reg=name,
                    exp=f"0x{_RESET_EXP[name]:08x}",
                    got=f"0x{got & mask:08x}",
                    resp=_RESP.get(code, code),
                    reason="zero_reset_row_two_state",
                )
                continue
            self.chk.ok(
                "CSR-RESET",
                ok and cmp.ok,
                reg=name,
                exp=f"0x{_RESET_EXP[name]:08x}",
                got=f"0x{got & mask:08x}",
                resp=_RESP.get(code, code),
                rsvd=f"0x{cmp.rsvd:x}",
            )
        close_graded_window(self.logger)
        fault_before, _ok, _c = await self._rd(TOKEN_MATCH_FAULT_ADDR)

        # Step 5: the two read-data registers answer OKAY; data logged.
        open_graded_window(TEST, self.logger)
        for name in _DATA_REGS:
            got, ok, code = await self._rd(_IC.addr(name), ungraded=True)
            if not ok:
                self.chk.ok("CSR-RESET", False, reg=name, resp=_RESP.get(code, code))
            self._log("OBS-CSR-DATA", reg=name, resp=_RESP.get(code, code), rdata=f"0x{got:08x}")
        close_graded_window(self.logger)

        # Step 6: match registers, logged (retained digest, no reset value; no go).
        match_vals = []
        for ch in CHANNELS:
            v, _ok, _c = await self._rd(MATCH_ADDR[ch])
            match_vals.append(v)

        # Step 7: timeout counts with enable 0 (logged control).
        for name, key in (
            (_RD_TMO, "read_req_timeout_cycles"),
            (_PG_TMO, "program_req_timeout_cycles"),
        ):
            wr = int(p.draws[key])
            await self._wr(_IC.addr(name), wr)
            got, _ok, _c = await self._rd(_IC.addr(name))
            self._log("OBS-CSR-RW", reg=name, wr=f"0x{wr:08x}", got=f"0x{got:08x}")

        # Step 8: control-register patterns (go and enable bits 0).
        open_graded_window(TEST, self.logger)
        pg_pat = int(p.draws["program_ctrl_pattern"])
        rd_pat = int(p.draws["read_ctrl_pattern"])
        self.reg_model = {_STATUS: _RESET_EXP[_STATUS], _PG: pg_pat, _RD: rd_pat}
        for name, addr, pat in ((_PG, PROGRAM_CTRL_ADDR, pg_pat), (_RD, READ_CTRL_ADDR, rd_pat)):
            ok_w, code = await self._wr(addr, pat, ungraded=True)
            got, _ok, _c = await self._rd(addr)
            cmp = field_compare(got, pat, _IC.mask32(name))
            self.chk.ok(
                "CSR-RW",
                ok_w and cmp.ok and pat != _RESET_EXP[name],
                reg=name,
                wr=f"0x{pat:08x}",
                got=f"0x{got & _IC.mask32(name):08x}",
                resp=_RESP.get(code, code),
                rsvd=f"0x{cmp.rsvd:x}",
            )

        # Step 9: write of 1 to read-only status bits; response code not graded.
        await self._wr(STATUS_ADDR, _STATUS_RO_WRITE, ungraded=True)
        got, _ok, _c = await self._rd(STATUS_ADDR)
        cmp = field_compare(got, _RESET_EXP[_STATUS], _IC.mask32(_STATUS))
        self.chk.ok(
            "CSR-RW",
            cmp.ok,
            reg="STATUS",
            wr=f"0x{_STATUS_RO_WRITE:08x}",
            got=f"0x{got & _IC.mask32(_STATUS):08x}",
            exp=f"0x{_RESET_EXP[_STATUS]:08x}",
            rsvd=f"0x{cmp.rsvd:x}",
        )

        # Step 10: 24 token words in the drawn order; no go; read back.
        for ch in CHANNELS:
            words = token_words(_ARRAY_TOKEN[ch])
            order = list(p.draws[f"word_order.{ch}"])
            resp_ok = True
            for k in order:
                ok_w, _code = await self._wr(TOKEN_ARRAY_ADDR[ch][k], words[k], ungraded=True)
                resp_ok = resp_ok and ok_w
            got_words = []
            for k in range(8):
                v, _ok, _c = await self._rd(TOKEN_ARRAY_ADDR[ch][k])
                got_words.append(v)
            equal = sum(int(g == w) for g, w in zip(got_words, words))
            self.chk.ok(
                "TOKEN-RW",
                resp_ok and equal == 8,
                arr=_ARRAY_TAG[ch],
                words=8,
                equal=int(equal == 8),
                n_equal=equal,
                order=order,
                resp_ok=int(resp_ok),
            )
        close_graded_window(self.logger)
        fault_after, _ok, _c = await self._rd(TOKEN_MATCH_FAULT_ADDR)
        self._log(
            "OBS-TOKEN-FAULT",
            fault_before=f"0x{fault_before:x}",
            fault_after=f"0x{fault_after:x}",
            match_logged=",".join(f"0x{v:x}" for v in match_vals),
        )

        # Steps 11-12: FEAT_CTRL is read only.
        open_graded_window(TEST, self.logger)
        lo, _ok, _c = await self._rd(_FEAT_CTRL)
        hi, _ok, _c = await self._rd(_FEAT_CTRL + 4)
        before = (hi << 32 | lo) & _FEAT_MASK
        wr64 = ~before & _FEAT_MASK
        await self._wr(_FEAT_CTRL, wr64 & _WORD, ungraded=True)
        await self._wr(_FEAT_CTRL + 4, wr64 >> 32, ungraded=True)
        lo, _ok, _c = await self._rd(_FEAT_CTRL)
        hi, _ok, _c = await self._rd(_FEAT_CTRL + 4)
        after = (hi << 32 | lo) & _FEAT_MASK
        self.chk.ok(
            "FEAT-RO",
            before == after,
            before=f"0x{before:016x}",
            wr=f"0x{wr64:016x}",
            after=f"0x{after:016x}",
        )

        # Step 13: control reads before the first unmapped access.
        await self._control_reads("before")

        # Step 14: past-extent leg (pinned 0x1093_041C, then the seven drawn offsets).
        for addr in (_PAST_EXTENT_PINNED, *p.leg["past_extent_addrs"]):
            await self._decode_access("ctrl", addr)

        # Step 15: reserved leg (three pinned, then the six drawn addresses).
        for addr in (*_RSVD_PINNED, *p.leg["rsvd_addrs"]):
            await self._decode_access("rsvd", addr)

        # Step 16: control reads after the last unmapped access.
        await self._control_reads("after")

        # Step 17: legal set-only write of the complement of SYS_DIS word w.
        ctl_addr = int(p.leg["ctl_word_addr"])
        w = int(p.draws["sys_dis_ctl_word"])
        if ctl_addr != shadow_addr("SYS_DIS", w):
            raise AssertionError("plan control-word address disagrees with the SYS_DIS map")
        staged = self.model[(ctl_addr - SHADOW_BASE) // 4]
        wr = ~staged & _WORD
        ok_w, code = await self._wr(ctl_addr, wr, ungraded=True)
        got, _ok, _c = await self._rd(ctl_addr)
        self.chk.ok(
            "WIN-DECODE",
            ok_w and got == _WORD and staged != _WORD,
            win="ctlwr",
            word=w,
            addr=f"0x{ctl_addr:08x}",
            staged=f"0x{staged:08x}",
            wr=f"0x{wr:08x}",
            got=f"0x{got:08x}",
            resp=_RESP.get(code, code),
        )
        self.model[(ctl_addr - SHADOW_BASE) // 4] = _WORD

        # Step 18: the 256 shadow words equal the model.
        mism = []
        for i in range(256):
            v, _ok, _c = await self._rd(SHADOW_BASE + 4 * i)
            if v != self.model[i]:
                mism.append(f"{i}:0x{v:08x}/0x{self.model[i]:08x}")
        self.chk.ok(
            "WIN-DECODE",
            not mism,
            win="sweep",
            words=256,
            mismatches=len(mism),
            first=",".join(mism[:4]) or "none",
        )
        close_graded_window(self.logger)
        self.chk.finish()
