# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each address-map row answers the cells that the generated memory map states.

Run mode: no_cpu (``lsu_stub_all_live``), real PROD fuse sense, the Key Manager
held in reset with no image. Randomization: every seed walks every cell of the
inventory; the seed draws the offset inside each cell, the row order, the SI
AxID (non-zero) and the burst start and AxLEN.

The expected cells come from ``hw/sys/sep/regs/gen/adoc/memory_map.adoc`` (Hole
in Extent and Past Extent columns, through ``env.sep_decode_resp``), the
``ocah_*`` annotations of ``hw/sys/sep/regs/sep.rdl`` and the register
allocation of the generated IP-XACT (``seq_lib.sep_row_response_seq``). The
table states each cell for a 32-bit access at the inbound AXI port, so every
graded single beat uses AxSIZE 2 in both halves of the 64-bit data bus; an
AxSIZE 3 access is logged and not graded. The reset-control rows state what the
SEP CPU sees, so the reset-control cells are graded from the LSU.

Every SI access goes through inbound entry 0, which covers 0x1000_0000 to
0x1FFF_FFFF with read, write and burst allowed. The decoded registers answer
OKAY through that entry, so a DECERR in this leaf comes from the decode and not
from the filter.

CHK-ROW: response code and addressed data lane of every cell (Reserved, Past
Extent, Hole in Extent, live word), with X or Z in an error payload failing on
VCS. A hole write leaves its neighbour register unchanged; the in-extent write
of the same data to the neighbour changes it (control).

CTL-ROW-RAND: stimulus completeness. Every inventory cell was walked.

CHK-ROW-NOALIAS: a reset-control gap or tail write and an HMAC or KMAC hole
write leave the live reference register (``SW_RESET_N``, HMAC ``CFG``, a KMAC
``PREFIX`` word) unchanged; an in-extent write to the same register changes it.

CHK-ROW-CACHE: an OTBN register access answers OKAY with AxCACHE[1] = 0 and 1 on
both channels (``hw/sys/sep/doc/otbn.adoc``, OCAH Modifications).

CHK-ROW-KM: every Key Manager mailbox offset past its seven registers, and the
reserved span after it, answers DECERR with 0xBADCAB1E, and no baseline register
moves. The baseline control write of ``SEP_IRQ_ENABLE`` reads back.

CHK-ROW-BURST / CHK-ROW-BURST-CONTROL: an SI burst to the crypto region answers
DECERR on B, or on every one of its AxLEN + 1 R beats (no early burst
termination, IHI 0022 A3.4.1), and lands no beat (``hw/sys/sep/doc/crypto.adoc``,
Single-Beat Access Only); a single beat at the same address answers its 32-bit
cell.

Not graded: the Forwarded and adopter-defined rows; the response of a burst to
a register region outside the crypto region (the specification states none);
any AxSIZE 3 access.
"""

from __future__ import annotations

from collections import Counter

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import RESP_DECERR, RESP_OKAY
from env.sep_fabric_common import RESP_NAME as _RN
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import KMAC, OTBN
from seq_lib import sep_row_response_seq as rr
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq, capture_addr_handshake, take_handshake
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

_TEST = "sep_fabric_row_response_matrix_test"
_MAX_SENSE_CYCLES = 20_000
# A pinned PROD image whose SIP_DIS and SYS_DIS keep the inbound filter active.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
# AxPROT of every SI request: data, non-secure, unprivileged. Entry 0 sets
# allow_ns to AxPROT[1].
SI_PROT = 0b010
OKAY, DECERR = RESP_OKAY, RESP_DECERR
AXI_INCR = 1
_HMAC_POLL = 200

# Hole neighbours: a stable register of the same unit with no read side effect.
HOLE_NEIGHBOUR_NAME = {
    "otbn": "INTR_ENABLE",
    "esrc": "MIN_ENTROPY_H",
    "abr": "INTR_BLOCK_RF_NOTIF_INTR_EN_R",
}


def _reg_named(key: str, name: str) -> rr.Reg:
    return next(r for r in rr.row_regs(key) if r.name == name)


@pyuvm.test()
class sep_fabric_row_response_matrix_test(sep_base_test):
    """Every graded address-map row cell, the OTBN AxCACHE cells and the crypto burst rule."""

    required_evidence = (
        "CHK-ROW",
        "CHK-ROW-NOALIAS",
        "CHK-ROW-CACHE",
        "CHK-ROW-KM",
        "CHK-ROW-BURST",
        "CHK-ROW-BURST-CONTROL",
    )

    # ------------------------------------------------------------------ access
    async def _lsu(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        size: int = 2,
        wdata: int = 0,
        cache: int | None = None,
        expect: str = "ok",
    ) -> tuple[int, int]:
        """One LSU access. ``expect``: ``ok`` (OKAY required), ``err`` (graded
        error; the caller checks the code), ``any`` (logged only)."""
        length = 1 << size
        mon = self.env.axi_monitor
        kw = {}
        if expect == "err":
            kw["expect_error"] = True
            kw["allow_unverified_write_resp"] = op is SepAxiOp.WRITE
        elif expect == "any":
            if op is SepAxiOp.READ:
                kw["allow_ungraded_read_resp"] = True
            else:
                kw["allow_unverified_write_resp"] = True
        if expect != "ok":
            mon.arm_expected_decerr(1)
            if op is SepAxiOp.READ:
                mon.open_error_rdata_window()
        seq = SepAxiAccessSeq(
            f"row_lsu_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata & ((1 << (8 * length)) - 1),
            length=length,
            size=size,
            attrs=None if cache is None else {"cache": cache},
            **kw,
        )
        try:
            await self.start_seq(seq)
        finally:
            if expect != "ok" and op is SepAxiOp.READ:
                mon.close_error_rdata_window()
        if expect != "ok" and seq.resp_code != DECERR:
            mon.release_expected_decerr(1)
        if expect == "ok" and not seq.resp_ok:
            raise AssertionError(f"LSU {op.value} 0x{addr:08x} answered {_RN.get(seq.resp_code)}")
        return seq.resp_code, seq.rdata

    async def _si(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        size: int = 2,
        wdata: int = 0,
        length: int | None = None,
        burst: int | None = None,
    ) -> SepAxiAccessSeq:
        """One SI access through inbound entry 0 with a drawn non-zero AxID."""
        length = (1 << size) if length is None else length
        mon = self.env.ext_axi_monitor
        if op is SepAxiOp.READ:
            mon.open_error_rdata_window()
        seq = SepAxiAccessSeq(
            f"row_si_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata & ((1 << (8 * length)) - 1),
            length=length,
            size=size,
            burst=burst,
            prot=SI_PROT,
            axi_id=self.rng.randrange(1, 64),
            allow_unverified_write_resp=op is SepAxiOp.WRITE,
        )
        try:
            await self.start_ext_seq(seq)
        finally:
            if op is SepAxiOp.READ:
                mon.close_error_rdata_window()
        assert not seq.timed_out, f"SI {op.value} 0x{addr:08x} timed out"
        return seq

    # ------------------------------------------------------------- bookkeeping
    def _walk(self, row: str, kind: str, d: str, init: str) -> None:
        self.walked.add((row, kind, d, init))

    def _fail(self, chk: str, line: str) -> None:
        self.logger.error("%s FAIL: %s", chk, line)
        self.fails.append(f"{chk}: {line}")

    def _row_line(self, ok: bool, line: str) -> None:
        if ok:
            self.logger.info("CHK-ROW PASS: %s", line)
        else:
            self._fail("CHK-ROW", line)

    def _grade_cell(
        self, row: str, kind: str, init: str, op: SepAxiOp, addr: int, resp: int, rdata: int, wdata
    ) -> None:
        exp = rr.expected_cell(addr, "r" if op is SepAxiOp.READ else "w")
        d = "R" if op is SepAxiOp.READ else "W"
        got = rdata & 0xFFFF_FFFF
        ok = resp == exp.resp and (exp.rdata is None or got == exp.rdata)
        self._row_line(
            ok,
            f"row={row} kind={kind} init={init} dir={d} size=2 addr=0x{addr:08x} "
            f"wdata={'na' if wdata is None else f'0x{wdata:08x}'} resp={_RN.get(resp)} "
            f"rdata=0x{got:08x} expect={_RN[exp.resp]}/"
            f"{'na' if exp.rdata is None else f'0x{exp.rdata:08x}'}",
        )
        self._walk(row, kind, d, init)

    def _log_size3(self, row: str, kind: str, resp: int, rdata: int, d: str) -> None:
        self.logger.info(
            "ROW-SIZE3 LOG: row=%s kind=%s dir=%s size=3 resp=%s rdata=0x%016x graded=0",
            row,
            kind,
            d,
            _RN.get(resp),
            rdata,
        )

    def _expect_reg(self, addr: int) -> int:
        return self.regval.get(addr, rr.word_reset(addr))

    async def _lsu_write_reg(self, addr: int, wdata: int, tag: str) -> tuple[int, int, int]:
        """In-extent LSU write and read-back; returns (read, expected, mask)."""
        await self._lsu(SepAxiOp.WRITE, addr, wdata=wdata)
        exp, mask = rr.write_readback(addr, self._expect_reg(addr), wdata)
        _r, got = await self._lsu(SepAxiOp.READ, addr)
        self.regval[addr] = exp
        if (got & mask) != (exp & mask):
            raise AssertionError(
                f"{tag}: 0x{addr:08x} read 0x{got & mask:08x} after a write of 0x{wdata:08x}, "
                f"expected 0x{exp & mask:08x} (field_mask=0x{mask:08x})"
            )
        return got, exp, mask

    # --------------------------------------------------------------- bring-up
    async def _bring_up(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        # The image carries no SEC_DIS token, so the golden takes SEC_DIS 0 from
        # the image, not from the DUT.
        feat = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        self.logger.info(
            "ROW-BRINGUP LOG: feat_ctrl=0x%016x golden=0x%016x sep_debug=%d",
            ctl.feat_ctrl,
            feat,
            ctl.sep_debug,
        )

    async def _program_entry(self) -> None:
        bank = SepFilterBank(self, "in")
        await bank.program(
            0,
            FilterEntry(
                start=0x1000_0000,
                end=0x1FFF_FFFF,
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=bool((SI_PROT >> 1) & 1),
                allow_burst=True,
            ),
        )

    # ---------------------------------------------------------------- inventory
    def _inventory(self) -> set[tuple[str, str, str, str]]:
        inv: set[tuple[str, str, str, str]] = set()
        for d in ("R", "W"):
            inv.add(("reset_ctrl", "past", d, "LSU"))
            inv.add((f"rsvd_{rr.past_bounds('reset_ctrl')[2]:08x}", "reserved", d, "LSU"))
            for base in rr.RESERVED_BASES:
                rr.reserved_row(base)
                inv.add((f"rsvd_{base:08x}", "reserved", d, "SI"))
            for k in rr.HOLE_ROWS:
                inv.add((k, "hole", d, "SI"))
            for k in rr.PAST_ROWS:
                inv.add((k, "past", d, "SI"))
            inv.add(("km_mbox", "past", d, "SI"))
            for k in rr.BURST_ROWS:
                for kind in ("reg", "hole"):
                    inv.add((k, f"burst_{kind}", d, "SI"))
        inv.add(("reset_ctrl", "live", "R", "LSU"))
        for k in rr.LIVE_SI_ROWS:
            inv.add((k, "live", "R", "SI"))
        return inv

    # -------------------------------------------------------------------- legs
    async def _reset_ctrl_leg(self) -> None:
        """Steps 4 to 6: reset-control cells, no-alias draws and the control."""
        resp, ref = await self._lsu(SepAxiOp.READ, rr.SW_RESET_N)
        got = ref & rr.SW_RESET_N_FIELDS
        self._row_line(
            resp == OKAY and got == rr.SW_RESET_N_REF,
            f"row=reset_ctrl kind=live init=LSU dir=R size=2 addr=0x{rr.SW_RESET_N:08x} "
            f"wdata=na resp={_RN.get(resp, resp)} rdata=0x{ref & 0xFFFF_FFFF:08x} expect=OKAY/0x{rr.SW_RESET_N_REF:02x} "
            f"field_mask=0x{rr.SW_RESET_N_FIELDS:02x} lsu_before=na lsu_after=na "
            f"rsvd=0x{ref & ~rr.SW_RESET_N_FIELDS & 0xFFFF_FFFF:08x}",
        )
        self._walk("reset_ctrl", "live", "R", "LSU")
        first, last, nxt = rr.past_bounds("reset_ctrl")
        rr.reserved_row(nxt)
        drawn = (first + 8) + 8 * self.rng.randrange(0, ((last - 8) - (first + 8)) // 8 + 1)
        pairs = (first, drawn, last, nxt)
        self.logger.info("ROW-RAND LOG: reset_ctrl drawn pair 0x%08x", drawn)
        for op in (SepAxiOp.READ, SepAxiOp.WRITE):
            d = "R" if op is SepAxiOp.READ else "W"
            for word in pairs:
                row = "reset_ctrl" if word < nxt else f"rsvd_{nxt:08x}"
                kind = "past" if word < nxt else "reserved"
                for a in (word, word + 4):
                    wd = ((self.rng.getrandbits(25) << 7) | 0x01) if op is SepAxiOp.WRITE else None
                    resp, rdata = await self._lsu(op, a, wdata=wd or 0, expect="err")
                    self._grade_cell(row, kind, "LSU", op, a, resp, rdata, wd)
                resp, rdata = await self._lsu(
                    op, word, size=3, wdata=self.rng.getrandbits(64), expect="any"
                )
                self._log_size3(row, kind, resp, rdata, d)
        # Step 5: no-alias draws in the gap at AxSIZE 0, 1, 2 and 3.
        for size in (0, 1, 2, 3):
            for _ in range(2):
                n = 1 << size
                # AxSIZE 0 and 1 draw 4-byte-aligned addresses, so the data
                # lies on the byte lanes of SW_RESET_N[6:0].
                step = max(n, 4)
                lo = (first + step - 1) & ~(step - 1)
                a = lo + step * self.rng.randrange(0, (nxt - lo) // step)
                wd = (self.rng.getrandbits(8 * n - 7) << 7) | 0x01
                expect = "err" if size == 2 else "any"
                resp, rdata = await self._lsu(SepAxiOp.WRITE, a, size=size, wdata=wd, expect=expect)
                if size == 2:
                    self._grade_cell("reset_ctrl", "past", "LSU", SepAxiOp.WRITE, a, resp, 0, wd)
                else:
                    self.logger.info(
                        "ROW-NOALIAS-DRAW LOG: addr=0x%08x size=%d resp=%s graded=0",
                        a,
                        size,
                        _RN.get(resp),
                    )
                _r, after = await self._lsu(SepAxiOp.READ, rr.SW_RESET_N)
                self._noalias(
                    "reset_ctrl",
                    a - rr.SW_RESET_N,
                    rr.SW_RESET_N,
                    rr.SW_RESET_N_REF,
                    after & rr.SW_RESET_N_FIELDS,
                    wd,
                )
        # Step 6: the reset-control control. In-extent writes change the read.
        for value in (0x76, rr.SW_RESET_N_REF):
            await self._lsu(SepAxiOp.WRITE, rr.SW_RESET_N, wdata=value)
            _r, back = await self._lsu(SepAxiOp.READ, rr.SW_RESET_N)
            if back & rr.SW_RESET_N_FIELDS != value:
                raise AssertionError(
                    f"CHK-ROW-NOALIAS FAIL: control write of SW_RESET_N=0x{value:02x} read back "
                    f"0x{back & rr.SW_RESET_N_FIELDS:02x}; the reference cannot show an alias"
                )
            self.logger.info(
                "CTL-ROW-NOALIAS LOG: unit=reset_ctrl wrote=0x%02x read=0x%02x",
                value,
                back & rr.SW_RESET_N_FIELDS,
            )
        self.noalias_ctl.add("reset_ctrl")

    def _noalias(self, unit: str, off: int, live: int, before: int, after: int, wd: int) -> None:
        line = (
            f"unit={unit} off=0x{off & 0xFFFF_FFFF:x} live=0x{live:08x} before=0x{before:x} "
            f"after=0x{after:x} wdata=0x{wd:x}"
        )
        if after == before:
            self.logger.info("CHK-ROW-NOALIAS PASS: %s", line)
        else:
            self._fail("CHK-ROW-NOALIAS", line)
        self.noalias_draws[unit] += 1

    async def _wait_hmac(self) -> None:
        """Step 7: HMAC CFG answers OKAY again after the HMAC domain reset."""
        for i in range(_HMAC_POLL):
            resp, _d = await self._lsu(SepAxiOp.READ, rr.HMAC_CFG, expect="any")
            if resp == OKAY:
                self.logger.info("ROW-HMAC-READY LOG: CFG OKAY after %d read(s)", i + 1)
                return
            await ClockCycles(cocotb.top.clk_i, 20)
        raise AssertionError(f"HMAC CFG did not answer OKAY in {_HMAC_POLL} reads")

    async def _program_refs(self) -> None:
        """Step 8: the HMAC CFG and KMAC PREFIX references."""
        _r, cur = await self._lsu(SepAxiOp.READ, rr.HMAC_CFG)
        self.regval[rr.HMAC_CFG] = cur & 0xFFFF_FFFF
        hval = rr.hmac_cfg_reference(self.rng)
        await self._lsu_write_reg(rr.HMAC_CFG, hval, "HMAC CFG reference")
        k = self.rng.randrange(0, 10)
        self.kmac_ref = KMAC.addr(f"PREFIX_{k}_")
        kval = self.rng.randrange(1, 1 << 32)
        await self._lsu_write_reg(self.kmac_ref, kval, "KMAC PREFIX reference")
        self.logger.info(
            "ROW-REF LOG: hmac_cfg=0x%08x kmac_prefix[%d]@0x%08x=0x%08x",
            self.regval[rr.HMAC_CFG],
            k,
            self.kmac_ref,
            self.regval[self.kmac_ref],
        )

    async def _otbn_cache_leg(self) -> None:
        """Step 9: OTBN register access with AxCACHE 0x0, 0x2, 0x3 and 0xF."""
        ie = OTBN.addr("INTR_ENABLE")
        done = OTBN.field_mask("INTR_ENABLE", "done")
        st = OTBN.addr("STATUS")
        for c in (0x0, 0x2, 0x3, 0xF):
            rresp, v = await self._lsu(SepAxiOp.READ, ie, cache=c)
            w = (~v) & done
            bresp, _ = await self._lsu(SepAxiOp.WRITE, ie, wdata=w, cache=c)
            _r, back = await self._lsu(SepAxiOp.READ, ie, cache=c)
            await self._lsu(SepAxiOp.READ, st, cache=c)
            self.regval[ie] = w
            line = (
                f"init=LSU arcache=0x{c:x} awcache=0x{c:x} rresp={_RN[rresp]} "
                f"bresp={_RN[bresp]} readback=0x{back & done:x}"
            )
            if (back & done) == w:
                self.logger.info("CHK-ROW-CACHE PASS: %s", line)
            else:
                self._fail("CHK-ROW-CACHE", line + f" written=0x{w:x}")

    async def _reserved_leg(self) -> None:
        """Step 10: the 8 Reserved rows from SI."""
        bases = list(rr.RESERVED_BASES)
        self.rng.shuffle(bases)
        for base in bases:
            row = rr.map_row(base)
            mid = base + 8 + 8 * self.rng.randrange(0, (row.end - 15 - base - 8) // 8 + 1)
            words = (base, row.end - 7, mid)
            self.logger.info("ROW-RAND LOG: rsvd_%08x words %s", base, [hex(w) for w in words])
            for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                d = "R" if op is SepAxiOp.READ else "W"
                for word in words:
                    for a in (word, word + 4):
                        wd = self.rng.getrandbits(32) if op is SepAxiOp.WRITE else None
                        s = await self._si(op, a, wdata=wd or 0)
                        self._grade_cell(
                            f"rsvd_{base:08x}", "reserved", "SI", op, a, s.resp_code, s.rdata, wd
                        )
                    s = await self._si(op, word, size=3, wdata=self.rng.getrandbits(64))
                    self._log_size3(f"rsvd_{base:08x}", "reserved", s.resp_code, s.rdata, d)

    async def _hole_leg(self) -> None:
        """Steps 11 and 12: hole cells from SI, with the neighbour compare and control."""
        units = list(rr.HOLE_ROWS)
        self.rng.shuffle(units)
        for unit in units:
            word = self.rng.choice(rr.hole_words(unit))
            if unit == "hmac":
                nb = rr.HMAC_CFG
            elif unit == "kmac":
                nb = self.kmac_ref
            else:
                nb = _reg_named(unit, HOLE_NEIGHBOUR_NAME[unit]).addr
            _r, before = await self._lsu(SepAxiOp.READ, nb)
            reg = rr.reg_by_word()[nb]
            mask = reg.word_mask(nb)
            exp_nb = self._expect_reg(nb)
            if (before & mask) != (exp_nb & mask):
                raise AssertionError(
                    f"CHK-ROW FAIL: {unit} neighbour 0x{nb:08x} read 0x{before & mask:x} before "
                    f"the hole access, model 0x{exp_nb & mask:x}"
                )
            comp = (~before) & 0xFFFF_FFFF
            self.logger.info("ROW-RAND LOG: %s hole word 0x%08x neighbour 0x%08x", unit, word, nb)
            for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                d = "R" if op is SepAxiOp.READ else "W"
                for a in (word, word + 4):
                    s = await self._si(op, a, wdata=comp)
                    self._grade_cell(
                        unit,
                        "hole",
                        "SI",
                        op,
                        a,
                        s.resp_code,
                        s.rdata,
                        comp if op is SepAxiOp.WRITE else None,
                    )
                    if op is SepAxiOp.WRITE:
                        _r, after = await self._lsu(SepAxiOp.READ, nb)
                        same = (after & mask) == (before & mask)
                        line = (
                            f"row={unit} kind=hole_neighbour init=LSU addr=0x{nb:08x} "
                            f"hole=0x{a:08x} before=0x{before & mask:x} after=0x{after & mask:x} "
                            f"wdata=0x{comp:08x} field_mask=0x{mask:x}"
                        )
                        self._row_line(same, line)
                        if unit in ("hmac", "kmac"):
                            self._noalias(unit, a - nb, nb, before & mask, after & mask, comp)
                s = await self._si(op, word, size=3, wdata=(comp << 32) | comp)
                self._log_size3(unit, "hole", s.resp_code, s.rdata, d)
            # Step 12: the hole-write control on the same neighbour (window closed).
            close_graded_window(self.logger)
            got, exp, _m = await self._lsu_write_reg(nb, comp, f"{unit} hole-write control")
            if (got & mask) == (before & mask):
                raise AssertionError(
                    f"CHK-ROW FAIL: {unit} control write of 0x{comp:08x} to 0x{nb:08x} did not "
                    f"change its read (0x{got & mask:x}); a landed hole write would not show"
                )
            self.logger.info(
                "CTL-ROW-HOLE LOG: unit=%s neighbour=0x%08x wrote=0x%08x read=0x%x before=0x%x",
                unit,
                nb,
                comp,
                got & mask,
                before & mask,
            )
            if unit in ("hmac", "kmac"):
                self.noalias_ctl.add(unit)
            if unit == "abr":
                # ABR has no stable register with a non-zero reset, so its live
                # word is graded at the value this control leaves in it.
                open_graded_window(_TEST, self.logger)
                await self._live_word("abr", _reg_named("abr", HOLE_NEIGHBOUR_NAME["abr"]))
                close_graded_window(self.logger)
            await self._lsu_write_reg(nb, before, f"{unit} neighbour restore")
            open_graded_window(_TEST, self.logger)

    async def _past_leg(self) -> None:
        """Step 13: past-extent cells from SI."""
        rows = list(rr.PAST_ROWS)
        self.rng.shuffle(rows)
        for key in rows:
            row = rr.map_row(key)
            e = row.base + row.extent
            lo = (e + 8 + 7) & ~7
            drawn = lo + 8 * self.rng.randrange(0, (row.end - 7 - lo) // 8 + 1)
            self.logger.info("ROW-RAND LOG: %s past E=0x%08x drawn 0x%08x", key, e, drawn)
            for op in (SepAxiOp.READ, SepAxiOp.WRITE):
                d = "R" if op is SepAxiOp.READ else "W"
                for a in (e, e + 4, drawn, drawn + 4):
                    wd = self.rng.getrandbits(32) if op is SepAxiOp.WRITE else None
                    s = await self._si(op, a, wdata=wd or 0)
                    self._grade_cell(key, "past", "SI", op, a, s.resp_code, s.rdata, wd)
                for w8 in ((e + 7) & ~7, drawn):
                    s = await self._si(op, w8, size=3, wdata=self.rng.getrandbits(64))
                    self._log_size3(key, "past", s.resp_code, s.rdata, d)

    async def _live_word(self, key: str, reg: rr.Reg) -> None:
        a = reg.addr
        mask = reg.word_mask(a)
        exp = self._expect_reg(a)
        _r, lsu_b = await self._lsu(SepAxiOp.READ, a)
        s = await self._si(SepAxiOp.READ, a)
        _r, lsu_a = await self._lsu(SepAxiOp.READ, a)
        got = s.rdata & 0xFFFF_FFFF
        pre_ok = (lsu_b & mask) == (exp & mask) and (lsu_a & mask) == (exp & mask)
        nonzero_ok = key not in rr.NONZERO_LIVE or (exp & mask) != 0
        ok = s.resp_code == OKAY and (got & mask) == (exp & mask) and pre_ok and nonzero_ok
        self._row_line(
            ok,
            f"row={key} kind=live init=SI dir=R size=2 addr=0x{a:08x} wdata=na "
            f"resp={_RN.get(s.resp_code)} rdata=0x{got & mask:08x} expect=OKAY/0x{exp & mask:08x} "
            f"field_mask=0x{mask:08x} lsu_before=0x{lsu_b & mask:08x} "
            f"lsu_after=0x{lsu_a & mask:08x} rsvd=0x{got & ~mask & 0xFFFF_FFFF:08x} reg={reg.name}",
        )
        self._walk(key, "live", "R", "SI")

    async def _live_leg(self) -> None:
        """Step 14: the live word of each row except reset control and ABR."""
        rows = [k for k in rr.LIVE_SI_ROWS if k != "abr"]
        self.rng.shuffle(rows)
        for key in rows:
            await self._live_word(key, rr.live_word(key))

    async def _km_leg(self) -> None:
        """Step 15: Key Manager mailbox window from SI with KM held in reset."""
        base = rr.ROW_BASE["km_mbox"]
        names = ("SEP_STATUS", "SEP_IRQ_STATUS", "SEP_CTRL", "SEP_IRQ_ENABLE")
        baseline = {}
        for a in rr.KM_BASELINE:
            s = await self._si(SepAxiOp.READ, a)
            assert s.resp_code == OKAY, f"KM baseline 0x{a:08x} answered {_RN.get(s.resp_code)}"
            baseline[a] = s.rdata & rr.reg_by_word()[a].word_mask(a)
        s = await self._si(SepAxiOp.READ, rr.KM_SEPARATOR)
        assert s.resp_code == OKAY, f"KM separator answered {_RN.get(s.resp_code)}"
        self.logger.info(
            "ROW-KM LOG: baseline %s separator=0x%08x",
            " ".join(f"{n}=0x{baseline[a]:x}" for n, a in zip(names, rr.KM_BASELINE)),
            s.rdata & 0xFFFF_FFFF,
        )
        first, last, nxt = rr.past_bounds("km_mbox")
        rsvd_last = rr.reserved_row(nxt).end + 1 - 8
        lo1 = ((first + 7) & ~7) - base
        d1 = lo1 + 8 * self.rng.randrange(0, ((last - 8 - base) - lo1) // 8 + 1)
        d2 = nxt + 8 * self.rng.randrange(0, (rsvd_last - nxt) // 8 + 1)
        pairs = (first, last, base + d1, d2)
        self.logger.info("ROW-RAND LOG: km pairs %s", [hex(p) for p in pairs])
        lines = []
        for op in (SepAxiOp.READ, SepAxiOp.WRITE):
            d = "R" if op is SepAxiOp.READ else "W"
            for p in pairs:
                for a in (p, p + 4):
                    wd = self.rng.getrandbits(32) if op is SepAxiOp.WRITE else None
                    s = await self._si(op, a, wdata=wd or 0)
                    exp = rr.expected_cell(a, "r" if op is SepAxiOp.READ else "w")
                    got = s.rdata & 0xFFFF_FFFF
                    same = True
                    for b in rr.KM_BASELINE:
                        sb = await self._si(SepAxiOp.READ, b)
                        v = sb.rdata & rr.reg_by_word()[b].word_mask(b)
                        same = same and sb.resp_code == OKAY and v == baseline[b]
                    ok = (
                        s.resp_code == DECERR
                        and exp.resp == DECERR
                        and (exp.rdata is None or got == exp.rdata)
                        and same
                    )
                    row = "km_mbox" if a < nxt else f"rsvd_{nxt:08x}"
                    kind = "past" if a < nxt else "reserved"
                    self._walk(row, kind, d, "SI")
                    line = (
                        f"off=0x{a - base:x} dir={d} resp={_RN.get(s.resp_code)} "
                        f"rdata=0x{got if op is SepAxiOp.READ else 0:08x} "
                        f"baseline_same={int(same)}"
                    )
                    if ok:
                        lines.append(line)
                    else:
                        self._fail("CHK-ROW-KM", line)
        close_graded_window(self.logger)
        for v in (rr.KM_IRQ_ENABLE_CTL, 0):
            s = await self._si(SepAxiOp.WRITE, rr.KM_IRQ_ENABLE, wdata=v)
            r = await self._si(SepAxiOp.READ, rr.KM_IRQ_ENABLE)
            if s.resp_code != OKAY or r.resp_code != OKAY or (r.rdata & 0xFFFF_FFFF) != v:
                raise AssertionError(
                    f"CHK-ROW-KM FAIL: baseline control SEP_IRQ_ENABLE write 0x{v:x} answered "
                    f"{_RN.get(s.resp_code)}, read back 0x{r.rdata & 0xFFFF_FFFF:x} "
                    f"({_RN.get(r.resp_code)})"
                )
        self.regval[rr.KM_IRQ_ENABLE] = 0
        for line in lines:
            self.logger.info("CHK-ROW-KM PASS: %s baseline_ctl=0x%x", line, rr.KM_IRQ_ENABLE_CTL)

    async def _snapshot(self, key: str) -> dict[int, tuple[int, int]]:
        snap = {}
        for reg in rr.snapshot_regs(key):
            for a in reg.words:
                _r, v = await self._lsu(SepAxiOp.READ, a)
                snap[a] = (v & 0xFFFF_FFFF, reg.word_mask(a))
        return snap

    async def _burst_leg(self) -> None:
        """Steps 16 to 19: SI INCR bursts to the crypto windows, with single-beat control."""
        mon = self.env.ext_axi_monitor
        for key in rr.BURST_ROWS:
            row = rr.map_row(key)
            for kind in ("reg", "hole"):
                for op in (SepAxiOp.WRITE, SepAxiOp.READ):
                    d = "R" if op is SepAxiOp.READ else "W"
                    # A start with room for two beats before its 4 KB page ends.
                    starts = (
                        [r.addr for r in rr.burst_start_regs(key)]
                        if kind == "reg"
                        else list(rr.hole_words(key))
                    )
                    start = self.rng.choice([a for a in starts if (a & 0xFFF) <= 0xFF0])
                    page_end = (start & ~0xFFF) + 0x1000
                    max_len = min(255, (page_end - start) // 8 - 1)
                    axlen = self.rng.randrange(1, max_len + 1)
                    nbeats = axlen + 1
                    assert rr.in_crypto_region(start) and row.base <= start <= row.end
                    close_graded_window(self.logger)
                    snap = await self._snapshot(key)
                    wdata = 0
                    for i in range(2 * nbeats):
                        a = start + 4 * i
                        w = (~snap[a][0]) & 0xFFFF_FFFF if a in snap else self.rng.getrandbits(32)
                        wdata |= w << (32 * i)
                    open_graded_window(_TEST, self.logger)
                    ch = "ar" if op is SepAxiOp.READ else "aw"
                    hs = cocotb.start_soon(capture_addr_handshake(ch, prefix="m_axi"))
                    if op is SepAxiOp.READ:
                        mon.start_beat_capture()
                    s = await self._si(
                        op, start, size=3, wdata=wdata, length=8 * nbeats, burst=AXI_INCR
                    )
                    beats = mon.take_beat_capture() if op is SepAxiOp.READ else []
                    ax = take_handshake(hs)
                    close_graded_window(self.logger)
                    changed = []
                    if op is SepAxiOp.WRITE:
                        after = await self._snapshot(key)
                        changed = [
                            f"0x{a:08x}:0x{v & m:x}->0x{after[a][0] & m:x}"
                            for a, (v, m) in snap.items()
                            if (after[a][0] & m) != (v & m)
                        ]
                        resp_ok = s.resp_code == DECERR and len(s.resp_list) == 1
                        n_dec = 1 if resp_ok else 0
                    else:
                        resp_ok = len(beats) == nbeats and all(b == DECERR for b in beats)
                        n_dec = sum(1 for b in beats if b == DECERR)
                    one_burst = ax is not None and ax["len"] == axlen and ax["addr"] == start
                    line = (
                        f"init=SI addr=0x{start:08x} kind={kind} len={axlen} dir={d} "
                        f"resp={_RN.get(s.resp_code)} beats_decerr={n_dec} "
                        f"wdata={'0x%x' % (wdata & 0xFFFF_FFFF_FFFF_FFFF) if op is SepAxiOp.WRITE else 'na'} "
                        f"regs_compared={len(snap) if op is SepAxiOp.WRITE else 0} "
                        f"changed={len(changed)} window={key} ax={ax}"
                    )
                    if resp_ok and not changed and one_burst:
                        self.logger.info("CHK-ROW-BURST PASS: %s", line)
                    else:
                        self._fail("CHK-ROW-BURST", f"{line} beats={beats} changed={changed[:4]}")
                    self._walk(key, f"burst_{kind}", d, "SI")
                    await self._burst_control(key, kind, start, snap)
                    open_graded_window(_TEST, self.logger)

    async def _burst_control(self, key, kind, start, snap) -> None:
        """Step 19: the single beat at the burst start through the same entry."""
        if kind == "reg":
            cur, m = snap[start]
            comp = (~cur) & 0xFFFF_FFFF
            exp, mask = rr.write_readback(start, cur, comp)
            w = await self._si(SepAxiOp.WRITE, start, wdata=comp)
            r = await self._si(SepAxiOp.READ, start)
            ok = (
                w.resp_code == OKAY
                and r.resp_code == OKAY
                and (r.rdata & mask) == (exp & mask)
                and (exp & mask) != (cur & mask)
            )
            rst = await self._si(SepAxiOp.WRITE, start, wdata=cur)
            back = await self._si(SepAxiOp.READ, start)
            assert rst.resp_code == OKAY and (back.rdata & m) == (cur & m), (
                f"burst control restore of 0x{start:08x} read 0x{back.rdata & m:x}, "
                f"snapshot 0x{cur & m:x}"
            )
            line = (
                f"init=SI addr=0x{start:08x} size=2 kind=reg single_resp={_RN.get(r.resp_code)} "
                f"single_rdata=0x{r.rdata & 0xFFFF_FFFF:08x} wrote=0x{comp:08x} "
                f"expect=0x{exp & mask:x} field_mask=0x{mask:x} window={key}"
            )
        else:
            r = await self._si(SepAxiOp.READ, start)
            w = await self._si(SepAxiOp.WRITE, start, wdata=self.rng.getrandbits(32))
            er = rr.expected_cell(start, "r")
            ew = rr.expected_cell(start, "w")
            ok = (
                r.resp_code == er.resp
                and (r.rdata & 0xFFFF_FFFF) == er.rdata
                and w.resp_code == ew.resp
                and er.resp != DECERR
            )
            line = (
                f"init=SI addr=0x{start:08x} size=2 kind=hole single_resp={_RN.get(r.resp_code)} "
                f"single_rdata=0x{r.rdata & 0xFFFF_FFFF:08x} write_resp={_RN.get(w.resp_code)} "
                f"expect={_RN[er.resp]}/0x{er.rdata:08x} window={key}"
            )
        if ok:
            self.logger.info("CHK-ROW-BURST-CONTROL PASS: %s", line)
        else:
            self._fail("CHK-ROW-BURST-CONTROL", line)

    # ---------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        self.rng = SepSeededRng(self.random_seed())
        self.walked: set[tuple[str, str, str, str]] = set()
        self.fails: list[str] = []
        self.regval: dict[int, int] = {}
        self.noalias_draws: Counter = Counter()
        self.noalias_ctl: set[str] = set()
        inventory = self._inventory()
        self.logger.info(
            "ROW-INVENTORY LOG: seed=%d cells=%d live=%s",
            self.random_seed(),
            len(inventory),
            " ".join(
                f"{k}=0x{rr.live_word(k).addr:08x}({rr.live_word(k).name})"
                for k in rr.ROW_BASE
                if rr.live_word(k) is not None
            ),
        )
        assert rr.live_word("abr") is None, (
            "ABR has a non-zero-reset stable register; the leaf has no ABR live cell"
        )

        await self._bring_up()
        await self._program_entry()

        open_graded_window(_TEST, self.logger)
        await self._reset_ctrl_leg()
        close_graded_window(self.logger)
        await self._wait_hmac()
        await self._program_refs()
        open_graded_window(_TEST, self.logger)
        await self._otbn_cache_leg()
        await self._reserved_leg()
        await self._hole_leg()
        await self._past_leg()
        await self._live_leg()
        await self._km_leg()
        open_graded_window(_TEST, self.logger)
        await self._burst_leg()
        close_graded_window(self.logger)

        # The no-alias control must have changed each reference.
        missing_ctl = {"reset_ctrl", "hmac", "kmac"} - self.noalias_ctl
        assert not missing_ctl, f"CHK-ROW-NOALIAS FAIL: no control for {sorted(missing_ctl)}"

        # Step 20: stimulus completeness.
        kinds = Counter(k for _r, k, _d, _i in self.walked)
        line = (
            f"seed={self.random_seed()} walked={len(self.walked & inventory)} "
            f"inventory={len(inventory)} rows={len({r for r, *_ in self.walked})} "
            f"reserved={kinds['reserved']} past={kinds['past']} hole={kinds['hole']} "
            f"live={kinds['live']} si={sum(1 for *_x, i in self.walked if i == 'SI')} "
            f"burst={kinds['burst_reg'] + kinds['burst_hole']}"
        )
        missing = sorted(inventory - self.walked)
        extra = sorted(self.walked - inventory)
        if missing or extra:
            self._fail("CTL-ROW-RAND", f"{line} missing={missing} extra={extra}")
        else:
            self.logger.info("CTL-ROW-RAND LOG: %s", line)

        if self.fails:
            raise AssertionError(f"{len(self.fails)} check failure(s); first: {self.fails[0]}")
