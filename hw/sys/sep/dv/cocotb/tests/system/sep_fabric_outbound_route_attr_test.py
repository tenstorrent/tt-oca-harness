# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound route of the SMU aperture and the AP and STEE regions, with attributes.

RANDCFG. Real PROD fuse sense of a pinned image (PROD, SEC_DIS 0, fixed
``SIP_DIS`` and ``SYS_DIS`` whose DBG_1 bit 0 is clear), so the inbound filter
is active, then one DEMOTE_1 write for the no-bypass leg. The seed draws the AP
region ``i``, the STEE region ``j``, their offsets (bits 55:19, not the region
identity), the AxPROT values, the direction order and the LSU AxUSER[3:0] ``u``
(1 to 15). The SMU aperture stays at its reset pair (``0x8000_0000``, size
``0x4000_0000``); the test never writes it.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology", "Transaction
Routing", "Filtering and Protection"; ``hw/sys/sep/doc/assets/sep-output-fabric.svg``;
``hw/ip/output_remap/regs/gen/adoc/output_remap.adoc``; ``hw/ip/axi_filter/doc/index.adoc``,
"Match, Then Permit", "Blocked Transactions"; ``hw/sys/smc/doc/assets/smc-traffic-filters.svg``):

* the SMU aperture and the AP and STEE regions leave on ``smn_outbound_axi_req_o``
  through the outbound filter; a local scratch or system-CSR request does not;
* the AP and STEE remaps rewrite the address to ``{O[55:19], a[18:0]}`` and set
  the source ID in AxUSER to OTHERS (zero); other traffic keeps the AxUSER of
  its initiator; AxPROT passes unchanged;
* the outbound filter checks the address after remapping, matches ``src_id``
  against AxUSER[3:0] and has no bypass.

Verdict anchor: the LSU response. An admitted request reaches the always-ready
outbound responder (``tb/sep_outbound_mbx.sv``), which answers OKAY; the
outbound filter answers DECERR to a refused request. Every outbound entry comes
as a pair over one range (``allow_ns`` 0 and 1, read and write allowed,
``src_id`` 0), so either AxPROT[1] matches one entry of the pair. PR-OUT
(observation tap) records what leaves the port.

Checkers:
  CHK-OUT-ROUTE     SMU read and write, AP and STEE write: OKAY with the pair
                    over the class enabled, DECERR with it disabled; AP and
                    STEE DECERR with a pair over the untranslated word only.
                    No PR-OUT capture for the disabled SMU pair.
  CHK-OUT-USER      AP and STEE requests with AxUSER[3:0] ``u`` skip entry 0
                    (``src_id`` ``u``, permissions clear) and entry 1
                    (``src_id`` 0) admits them; control: entry 0 with
                    ``src_id`` 0 refuses them.
  CHK-OUT-NOBYPASS  with the inbound filter bypassed after DEMOTE_1, the SMU
                    read answers DECERR with its pair disabled and OKAY with it
                    enabled.
  CHK-OUT-NOEXTRA   no PR-OUT capture for LSU reads of the cold scratch word
                    and SEP_SW_DEBUG behind a pair that covers them; control:
                    an SMU read captures.
  CHK-OUT-CAPTURE   each PR-OUT capture carries the predicted address, the
                    issued AxPROT, AxUSER 0 for AP and STEE and the issued
                    AxUSER for SMU, and the issued W data and strobe. X or Z
                    fails (VCS).
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import OUTBOUND_MBX_MAGIC, RESP_DECERR, RESP_OKAY, granule8
from env.sep_fabric_common import resp_name as _rname
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LC_PROD, LCC_FEAT_CTRL, lc_state_name
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AP_OUTPUT_REMAP_CTRL_0, SEP_CPU_CTRL, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import AP_BASE, REMAP_ATTRS, REMAP_STRIDE, STEE_BASE
from seq_lib.sep_fabric_filter_bank_seq import ADDR_MASK as _FILTER_ADDR_MASK
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccDemoteSeq
from seq_lib.sep_outbound_remap_seq import (
    AP_REGION_BASE,
    IDX_START,
    N_REGIONS,
    STEE_REGION_BASE,
)

# The 56-bit filter address field (START_ADDR / END_ADDR).
ADDR_MASK: int = _FILTER_ADDR_MASK
TEST = "sep_fabric_outbound_route_attr_test"

_MAX_SENSE_CYCLES = 20_000
# Pinned image: DBG_1 bit 0 (SEP_DBG) is clear in both, so PROD keeps the
# inbound filter active and DEMOTE_1 opens it.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0C
_SYS_DIS = 0x00FF_00FF_00FF_00FC

SMU_BASE = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
SMU_SIZE = SEP_CPU_CTRL.reset("SMU_REGION_SIZE")
SMU_LAST = SMU_BASE + SMU_SIZE - 1
SMU_MID = SMU_BASE + SMU_SIZE // 2
SMU_WORDS = (("first", SMU_BASE), ("middle", SMU_MID), ("last", SMU_LAST - 7))
LOCAL_LO = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")
# The pair covers cold scratch up to the last byte of the SEP_CPU_CTRL pages.
_CPU_CTRL_END = sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR") + sym("SEP_CPU_CTRL_REG_MAP_SIZE")
LOCAL_HI = ((_CPU_CTRL_END + 0xFFF) & ~0xFFF) - 1
IN_REGION = 0x100  # word address a inside a remap region (below 0x8_0000)
COLD_SCRATCH = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")
SW_DEBUG = SEP_CPU_CTRL.addr("SEP_SW_DEBUG")
SW_DEBUG_FIELD = SEP_CPU_CTRL.field_mask("SEP_SW_DEBUG", "sep_sw_debug")
SMU_BASE_REG = SEP_CPU_CTRL.addr("SMU_GLOBAL_BASE_ADDR")
SMU_SIZE_REG = SEP_CPU_CTRL.addr("SMU_REGION_SIZE")
REMAP_OFFSET_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "offset")
REMAP_VALID_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "valid")
REGION_MASK = (1 << IDX_START) - 1
# sep_outbound_mbx latches its completion state on these 32-bit write words.
_MBX_MAGIC = OUTBOUND_MBX_MAGIC

# Outbound entry pairs: entries 0 and 1 are the source-ID stack.
PAIR_SMU = (2, 3)
PAIR_AP = (4, 5)
PAIR_STEE = (6, 7)
PAIR_LOCAL = (8, 9)
PAIR_UNTRANSLATED = (10, 11)


class _Cls:
    """One remapped class (AP or STEE)."""

    def __init__(self, name: str, region_base: int, csr_base: int, region: int, offset: int):
        self.name = name
        self.csr_base = csr_base
        self.region = region
        self.offset = offset
        self.local = region_base + (region << IDX_START) + IN_REGION
        self.translated = ((offset >> IDX_START) << IDX_START) | (self.local & REGION_MASK)


class _Cfg:
    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.u = rng.randrange(1, 16)
        self.ap = self._draw_class(rng, "ap", AP_REGION_BASE, AP_BASE)
        self.stee = self._draw_class(rng, "stee", STEE_REGION_BASE, STEE_BASE)
        self.dir_first_write = bool(rng.getrandbits(1))
        self._rng = rng

    @staticmethod
    def _bad_target(t: int) -> bool:
        return (SMU_BASE <= t <= SMU_LAST) or (LOCAL_LO <= t <= LOCAL_HI)

    def _draw_class(self, rng: SepSeededRng, name: str, region_base: int, csr_base: int) -> _Cls:
        region = rng.randrange(N_REGIONS)
        identity = (region_base + (region << IDX_START)) >> IDX_START
        while True:
            hi = rng.getrandbits(56 - IDX_START)
            if hi == identity:
                continue
            c = _Cls(name, region_base, csr_base, region, hi << IDX_START)
            if self._bad_target(c.translated) or self._bad_target(c.local):
                continue
            # The two remapped words never share one granule, so a pair over
            # one never covers the other.
            if name == "stee" and (c.translated >> 3) == (self.ap.translated >> 3):
                continue
            return c

    def prot(self, prot1: int) -> int:
        """AxPROT with bit 1 forced and bits 0 and 2 seeded."""
        return (self._rng.getrandbits(3) & 0b101) | (prot1 << 1)

    def wdata(self) -> int:
        while True:
            d = self._rng.getrandbits(64)
            if (d & 0xFFFF_FFFF) not in _MBX_MAGIC and (d >> 32) not in _MBX_MAGIC:
                return d

    def dirs(self) -> tuple[bool, bool]:
        return (True, False) if self.dir_first_write else (False, True)

    def summary(self) -> str:
        return (
            f"seed={self.seed} u={self.u} ap_region={self.ap.region} "
            f"O_ap=0x{self.ap.offset:014x} ap_local=0x{self.ap.local:x} "
            f"ap_pred=0x{self.ap.translated:014x} stee_region={self.stee.region} "
            f"O_stee=0x{self.stee.offset:014x} stee_local=0x{self.stee.local:x} "
            f"stee_pred=0x{self.stee.translated:014x}"
        )


class _Remap(SepAxiRegDriver):
    """Program one AP or STEE output-remap region; RDL-field read-back."""

    _DRIVER_TAG = "OUTREMAP"

    async def program(self, c: _Cls, valid: bool) -> None:
        attrs = c.csr_base + c.region * REMAP_STRIDE + REMAP_ATTRS
        word = (c.offset & REMAP_OFFSET_FIELD) | (REMAP_VALID_FIELD if valid else 0)
        await self._wr(attrs, word & 0xFFFF_FFFF)
        await self._wr(attrs + 4, word >> 32)
        got = await self._rd(attrs) | (await self._rd(attrs + 4) << 32)
        fc = field_compare(got, word, REMAP_OFFSET_FIELD | REMAP_VALID_FIELD)
        line = f"{c.name} region={c.region} region_attrs {fc.fields()}"
        assert fc.ok, f"REMAP-READBACK FAIL: {line}"
        self.log.info("REMAP-READBACK LOG: %s", line)


@pyuvm.test()
class sep_fabric_outbound_route_attr_test(sep_base_test):
    """SMU, AP and STEE outbound route, AxPROT and AxUSER, source-ID forcing, no bypass."""

    required_evidence = (
        "CHK-OUT-ROUTE",
        "CHK-OUT-USER",
        "CHK-OUT-NOBYPASS",
        "CHK-OUT-NOEXTRA",
        "CHK-OUT-CAPTURE",
    )

    # ------------------------------------------------------------------ access

    async def _lsu(
        self,
        addr: int,
        *,
        write: bool,
        expect_okay: bool,
        prot: int,
        user: int,
        wdata: int = 0,
    ) -> SepAxiAccessSeq:
        if not expect_okay:
            self.env.axi_monitor.arm_expected_decerr(1)
        seq = SepAxiAccessSeq(
            "out_probe",
            op=SepAxiOp.WRITE if write else SepAxiOp.READ,
            addr=addr,
            wdata=wdata,
            length=8,
            size=3,
            expect_error=not expect_okay,
            prot=prot,
            user=user,
        )
        await self.start_seq(seq)
        if not expect_okay and seq.resp_code != RESP_DECERR:
            self.env.axi_monitor.release_expected_decerr(1)
        return seq

    async def _cell(
        self,
        cls: str,
        addr: int,
        pred: int,
        *,
        write: bool,
        prot: int,
        expect_okay: bool,
        graded: bool,
        chk: str = "CHK-OUT-ROUTE",
    ) -> tuple[int, list]:
        """One LSU access; returns (resp, PR-OUT beats of the access).

        A response other than the expected one fails ``chk`` at once.
        """
        user = self.tcfg.u
        wdata = self.tcfg.wdata() if write else 0
        mark = self.out.mark()
        if graded:
            open_graded_window(TEST, self.logger)
        seq = await self._lsu(
            addr, write=write, expect_okay=expect_okay, prot=prot, user=user, wdata=wdata
        )
        if graded:
            close_graded_window(self.logger)
        beats = self.out.since(mark)
        want = RESP_OKAY if expect_okay else RESP_DECERR
        assert seq.resp_code == want, (
            f"{chk} FAIL: class={cls} dir={'W' if write else 'R'} addr=0x{addr:x} "
            f"prot=0x{prot:x} user={user} resp={_rname(seq.resp_code)} expect={_rname(want)} "
            f"out_seen={len(beats)}"
        )
        if seq.resp_code == RESP_OKAY:
            # An admitted outbound access must show on PR-OUT; _capture fails
            # CHK-OUT-CAPTURE when its address beat is missing.
            self.n_expect += 1
            self._capture(
                cls, addr, pred, write=write, prot=prot, user=user, wdata=wdata, beats=beats
            )
        return seq.resp_code, beats

    def _capture(self, cls, addr, pred, *, write, prot, user, wdata, beats) -> None:
        """CHK-OUT-CAPTURE of one admitted access."""
        ch = "aw" if write else "ar"
        addr_beats = [b for b in beats if b.ch == ch]
        w_beats = [b for b in beats if b.ch == "w"]
        other = [b for b in beats if b.ch not in (ch, "w")]
        want_user = 0 if cls in ("ap", "stee") else user
        d = "W" if write else "R"
        assert len(addr_beats) == 1 and not other and (len(w_beats) == (1 if write else 0)), (
            f"CHK-OUT-CAPTURE FAIL: class={cls} dir={d} issued=0x{addr:x} beats="
            + " ".join(b.fmt() for b in beats)
        )
        b = addr_beats[0]
        unknown = b.has_unknown() or any(x.has_unknown() for x in w_beats)
        seen_w = w_beats[0] if write else None
        line = (
            f"class={cls} dir={d} issued=0x{addr:x} seen={_hx(b.addr)} prot={_hx(b.prot)} "
            f"user_issued={user} user_seen={_hx(b.user)} "
            f"wdata={_hx(seen_w.data) if write else 'na'} wstrb={_hx(seen_w.strb) if write else 'na'}"
        )
        ok = (
            not unknown
            and b.addr == pred
            and b.prot == prot
            and b.user == want_user
            and (not write or (seen_w.data == wdata and seen_w.strb == 0xFF))
        )
        assert ok, (
            f"CHK-OUT-CAPTURE FAIL: {line} predicted=0x{pred:x} prot_issued={prot} "
            f"user_expect={want_user} wdata_issued=0x{wdata:x}" + (" X/Z" if unknown else "")
        )
        self.logger.info("CHK-OUT-CAPTURE PASS: %s", line)
        self.n_capture += 1

    # ---------------------------------------------------------------- filters

    def _pair(self, lo: int, hi: int, ns: int) -> FilterEntry:
        return FilterEntry(
            start=lo,
            end=hi,
            enabled=True,
            read_allowed=True,
            write_allowed=True,
            allow_ns=bool(ns),
            allow_burst=False,
            src_id=0,
        )

    async def _program_pair(self, pair: tuple[int, int], lo: int, hi: int) -> None:
        for idx, ns in zip(pair, (0, 1)):
            await self.filt.program(idx, self._pair(lo, hi, ns))

    async def _pair_enable(self, pair: tuple[int, int], on: bool) -> None:
        for idx in pair:
            await self.filt.set_enabled(idx, on)

    # ---------------------------------------------------------------- legs

    async def _bring_up(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        assert sec_dis == 0, f"bring-up: SEC_DIS={sec_dis}; the pinned image needs SEC_DIS 0"
        feat = await self._rd64(LCC_FEAT_CTRL)
        self.logger.info(
            "FEAT_CTRL LOG: lc=%s sec_dis=%d feat_ctrl=0x%016x sep_debug=%d",
            lc_state_name(image.lc_raw()),
            sec_dis,
            feat,
            feat & 1,
        )
        base = await self._rd64(SMU_BASE_REG)
        size = await self._rd64(SMU_SIZE_REG)
        self.logger.info(
            "SMU aperture LOG: SMU_GLOBAL_BASE_ADDR=0x%x SMU_REGION_SIZE=0x%x", base, size
        )

    async def _rd64(self, addr: int) -> int:
        """A 64-bit register as two 32-bit reads (lo, then hi)."""
        v = 0
        for half in (0, 1):
            seq = SepAxiAccessSeq("rd32", op=SepAxiOp.READ, addr=addr + 4 * half, length=4, size=2)
            await self.start_seq(seq)
            assert seq.resp_ok, (
                f"read 0x{addr + 4 * half:x} not OKAY (resp={_rname(seq.resp_code)})"
            )
            v |= (seq.rdata & 0xFFFF_FFFF) << (32 * half)
        return v

    async def _smu_leg(self) -> None:
        """Steps 5 and 6."""
        await self._program_pair(PAIR_SMU, SMU_BASE, SMU_LAST)
        first_on = {}
        for word, addr in SMU_WORDS:
            for write in self.tcfg.dirs():
                for p1 in (0, 1):
                    prot = self.tcfg.prot(p1)
                    r, beats = await self._cell(
                        "smu", addr, addr, write=write, prot=prot, expect_okay=True, graded=True
                    )
                    assert r == RESP_OKAY, (
                        f"CHK-OUT-ROUTE FAIL: class=smu word={word} dir={'W' if write else 'R'} "
                        f"prot=0x{prot:x} entry_on_resp={_rname(r)}"
                    )
                    if word == "first":
                        first_on.setdefault(write, len([b for b in beats if b.ch in ("aw", "ar")]))
        await self._pair_enable(PAIR_SMU, False)
        for write in self.tcfg.dirs():
            prot = self.tcfg.prot(1)
            r, beats = await self._cell(
                "smu", SMU_BASE, SMU_BASE, write=write, prot=prot, expect_okay=False, graded=True
            )
            d = "W" if write else "R"
            line = (
                f"class=smu dir={d} entry_on_resp=OKAY entry_off_resp={_rname(r)} "
                f"untranslated_only_resp=na control_reads=0 entry_off_out_seen={len(beats)} "
                f"entry_on_out_seen={first_on[write]}"
            )
            assert r == RESP_DECERR and not beats and first_on[write] == 1, (
                f"CHK-OUT-ROUTE FAIL: {line}"
            )
            self.logger.info("CHK-OUT-ROUTE PASS: %s", line)
        await self._pair_enable(PAIR_SMU, True)

    async def _remap_leg(self, c: _Cls, pair: tuple[int, int]) -> None:
        """Steps 7 to 9 for one remapped class."""
        lo, hi = granule8(c.translated)
        await self._program_pair(pair, lo, hi)
        on = {}
        for write in self.tcfg.dirs():
            for p1 in (0, 1):
                prot = self.tcfg.prot(p1)
                r, _ = await self._cell(
                    c.name,
                    c.local,
                    c.translated,
                    write=write,
                    prot=prot,
                    expect_okay=True,
                    graded=True,
                )
                on.setdefault(write, []).append(r)
        await self._pair_enable(pair, False)
        off = {}
        for write in self.tcfg.dirs():
            for p1 in (0, 1):
                r, beats = await self._cell(
                    c.name,
                    c.local,
                    c.translated,
                    write=write,
                    prot=self.tcfg.prot(p1),
                    expect_okay=False,
                    graded=True,
                )
                assert not beats, (
                    f"CHK-OUT-ROUTE FAIL: class={c.name} pair disabled, PR-OUT captured"
                )
                off.setdefault(write, []).append(r)
        ulo, uhi = granule8(c.local)
        await self._program_pair(PAIR_UNTRANSLATED, ulo, uhi)
        unt = {}
        for write in self.tcfg.dirs():
            for p1 in (0, 1):
                r, beats = await self._cell(
                    c.name,
                    c.local,
                    c.translated,
                    write=write,
                    prot=self.tcfg.prot(p1),
                    expect_okay=False,
                    graded=True,
                )
                assert not beats, (
                    f"CHK-OUT-ROUTE FAIL: class={c.name} untranslated-only, PR-OUT captured"
                )
                unt.setdefault(write, []).append(r)
        await self._pair_enable(PAIR_UNTRANSLATED, False)
        # The read cells are controls; the write cells are graded.
        ctl_ok = all(x == RESP_OKAY for x in on[False]) and all(
            x == RESP_DECERR for x in off[False] + unt[False]
        )
        line = (
            f"class={c.name} dir=W entry_on_resp={_join(on[True])} entry_off_resp={_join(off[True])} "
            f"untranslated_only_resp={_join(unt[True])} control_reads={len(on[False]) + len(off[False]) + len(unt[False])} "
            f"entry_off_out_seen=na entry_on_out_seen=na"
        )
        graded_ok = (
            all(x == RESP_OKAY for x in on[True])
            and all(x == RESP_DECERR for x in off[True])
            and all(x == RESP_DECERR for x in unt[True])
        )
        assert graded_ok and ctl_ok, (
            f"CHK-OUT-ROUTE FAIL: {line} control_on={_join(on[False])} control_off={_join(off[False])} "
            f"control_untranslated={_join(unt[False])}"
        )
        self.logger.info("CHK-OUT-ROUTE PASS: %s", line)

    async def _stack_leg(self, c: _Cls) -> None:
        """Steps 11 to 13 for one remapped class."""
        lo, hi = granule8(c.translated)
        p1 = self._stack_prot1[c.name]
        prot = self.tcfg.prot(p1)
        u = self.tcfg.u
        e0 = FilterEntry(
            start=lo,
            end=hi,
            enabled=True,
            read_allowed=False,
            write_allowed=False,
            allow_ns=bool(p1),
            allow_burst=False,
            src_id=u,
        )
        e1 = FilterEntry(
            start=lo,
            end=hi,
            enabled=True,
            read_allowed=True,
            write_allowed=True,
            allow_ns=bool(p1),
            allow_burst=False,
            src_id=0,
        )
        await self.filt.program(0, e0)
        await self.filt.program(1, e1)
        res = {}
        for write in self.tcfg.dirs():
            v = self.filt.model.verdict(c.translated, write=write, prot1=p1, user=0)
            assert v.allowed and v.fallthrough, (
                f"model: stack does not fall through for OTHERS ({v.summary()})"
            )
            r, _ = await self._cell(
                c.name,
                c.local,
                c.translated,
                write=write,
                prot=prot,
                expect_okay=True,
                graded=True,
                chk="CHK-OUT-USER",
            )
            res[write] = r
        # Control: entry 0 with src_id 0 matches and refuses.
        e0c = FilterEntry(**{**vars(e0), "src_id": 0})
        await self.filt.program(0, e0c)
        ctl = {}
        for write in self.tcfg.dirs():
            r, _ = await self._cell(
                c.name,
                c.local,
                c.translated,
                write=write,
                prot=prot,
                expect_okay=False,
                graded=False,
                chk="CHK-OUT-USER",
            )
            ctl[write] = r
        await self.filt.set_enabled(0, False)
        await self.filt.set_enabled(1, False)
        for write in self.tcfg.dirs():
            line = (
                f"class={c.name} dir={'W' if write else 'R'} user_issued={u} resp={_rname(res[write])} "
                f"control_resp={_rname(ctl[write])}"
            )
            assert res[write] == RESP_OKAY and ctl[write] == RESP_DECERR, (
                f"CHK-OUT-USER FAIL: {line}"
            )
            self.logger.info("CHK-OUT-USER PASS: %s", line)

    async def _local_leg(self) -> None:
        """Step 14."""
        await self._program_pair(PAIR_LOCAL, LOCAL_LO, LOCAL_HI)
        rng = self.tcfg._rng
        m_scratch = rng.getrandbits(32) | 1
        m_dbg = (rng.getrandbits(32) | 1) & SW_DEBUG_FIELD
        for addr, m in ((COLD_SCRATCH, m_scratch), (SW_DEBUG, m_dbg)):
            seq = SepAxiAccessSeq("stage", op=SepAxiOp.WRITE, addr=addr, wdata=m, length=4, size=2)
            await self.start_seq(seq)
            assert seq.resp_ok, f"stage write 0x{addr:x} not OKAY"
        local_seen = 0
        n_local = 0
        for name, addr in (("cold_scratch", COLD_SCRATCH), ("sep_sw_debug", SW_DEBUG)):
            mark = self.out.mark()
            open_graded_window(TEST, self.logger)
            seq = SepAxiAccessSeq("local_rd", op=SepAxiOp.READ, addr=addr, length=8, size=3)
            await self.start_seq(seq)
            close_graded_window(self.logger)
            seen = self.out.count(mark)
            local_seen += seen
            n_local += 1
            self.logger.info(
                "local read LOG: %s addr=0x%x resp=%s data[31:0]=0x%08x data[63:32]=0x%08x out_seen=%d",
                name,
                addr,
                _rname(seq.resp_code),
                seq.rdata & 0xFFFF_FFFF,
                (seq.rdata >> 32) & 0xFFFF_FFFF,
                seen,
            )
        # Capture control: the SMU pair is enabled.
        _, beats = await self._cell(
            "smu",
            SMU_MID,
            SMU_MID,
            write=False,
            prot=self.tcfg.prot(1),
            expect_okay=True,
            graded=False,
            chk="CHK-OUT-NOEXTRA",
        )
        control = len([b for b in beats if b.ch == "ar"])
        line = f"local_reads={n_local} out_seen={local_seen} control_out={control}"
        assert local_seen == 0 and control == 1, f"CHK-OUT-NOEXTRA FAIL: {line}"
        self.logger.info("CHK-OUT-NOEXTRA PASS: %s", line)
        reset = SEP_CPU_CTRL.reset("SEP_SW_DEBUG") & 0xFFFF_FFFF
        seq = SepAxiAccessSeq(
            "restore", op=SepAxiOp.WRITE, addr=SW_DEBUG, wdata=reset, length=4, size=2
        )
        await self.start_seq(seq)
        await self._pair_enable(PAIR_LOCAL, False)

    async def _ext_read(self, addr: int, tag: str) -> int:
        seq = SepAxiAccessSeq(f"si_{tag}", op=SepAxiOp.READ, addr=addr, length=4, size=2)
        await self.start_ext_seq(seq)
        self.logger.info(
            "SI read LOG: %s addr=0x%x resp=%s data=0x%08x",
            tag,
            addr,
            _rname(seq.resp_code),
            seq.rdata & 0xFFFF_FFFF,
        )
        return seq.resp_code

    async def _nobypass_leg(self) -> None:
        """Steps 15 to 19."""
        feat0 = await self._rd64(LCC_FEAT_CTRL)
        self.logger.info("FEAT_CTRL LOG: before DEMOTE_1 feat_ctrl=0x%016x", feat0)
        await self._ext_read(LCC_FEAT_CTRL, "feat_ctrl_before_demote")
        demote = SepLccDemoteSeq(1)
        await self.start_seq(demote)
        self.logger.info("DEMOTE_1 LOG: demote=%s lock=%s", demote.demote, demote.lock)
        feat1 = await self._rd64(LCC_FEAT_CTRL)
        self.logger.info("FEAT_CTRL LOG: after DEMOTE_1 feat_ctrl=0x%016x", feat1)
        pre = await self._ext_read(LCC_FEAT_CTRL, "feat_ctrl_after_demote")
        if pre != RESP_OKAY:
            self.logger.error("CHK-OUT-NOBYPASS FAIL: bypass_not_established")
            raise AssertionError("CHK-OUT-NOBYPASS FAIL: bypass_not_established")
        await self._pair_enable(PAIR_SMU, False)
        r_off, b_off = await self._cell(
            "smu",
            SMU_MID,
            SMU_MID,
            write=False,
            prot=self.tcfg.prot(1),
            expect_okay=False,
            graded=True,
            chk="CHK-OUT-NOBYPASS",
        )
        await self._pair_enable(PAIR_SMU, True)
        r_on, _ = await self._cell(
            "smu",
            SMU_MID,
            SMU_MID,
            write=False,
            prot=self.tcfg.prot(1),
            expect_okay=True,
            graded=True,
            chk="CHK-OUT-NOBYPASS",
        )
        line = (
            f"bypass_pre={_rname(pre)} feat_after=0x{feat1:016x} disabled_resp={_rname(r_off)} "
            f"enabled_resp={_rname(r_on)}"
        )
        assert r_off == RESP_DECERR and not b_off and r_on == RESP_OKAY, (
            f"CHK-OUT-NOBYPASS FAIL: {line}"
        )
        self.logger.info("CHK-OUT-NOBYPASS PASS: %s", line)

    # ---------------------------------------------------------------- scenario

    async def run_scenario(self) -> None:
        self.tcfg = cfg = _Cfg(self.random_seed())
        self.logger.info("outbound route attr: %s", cfg.summary())
        self.n_capture = 0
        self.n_expect = 0
        self._stack_prot1 = {"ap": cfg._rng.getrandbits(1), "stee": cfg._rng.getrandbits(1)}

        await self._bring_up()
        self.out = SepFabricTap("PR-OUT").start()
        self.filt = SepFilterBank(self, "out")
        remap = _Remap(self)
        await remap.program(cfg.ap, True)
        await remap.program(cfg.stee, True)

        await self._smu_leg()
        await self._remap_leg(cfg.ap, PAIR_AP)
        await self._remap_leg(cfg.stee, PAIR_STEE)
        await self._stack_leg(cfg.ap)
        await self._stack_leg(cfg.stee)
        await self._local_leg()
        await self._nobypass_leg()
        close_graded_window(self.logger)
        await self.out.stop()
        line = f"captures={self.n_capture} admitted={self.n_expect}"
        assert self.n_expect > 0 and self.n_capture == self.n_expect, (
            f"CHK-OUT-CAPTURE FAIL: {line}"
        )
        self.logger.info("OUT-CAPTURE-SUMMARY LOG: %s", line)


def _hx(v) -> str:
    return "X" if v is None else f"0x{v:x}"


def _join(rs: list[int]) -> str:
    return ",".join(_rname(r) for r in rs)
