# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound route of the SMU aperture and the AP and STEE regions, with attributes.

RANDCFG. Real PROD fuse sense of a pinned image (PROD, SEC_DIS 0, fixed
``SIP_DIS`` and ``SYS_DIS`` whose DBG_1 bit 0 is clear), so the inbound filter
is active, then one DEMOTE_1 write for the no-bypass leg. The seed draws the AP
region ``i``, the STEE region ``j``, their offsets (bits 54:19, not the region
identity), the AxPROT values, the direction order, the offset of the
``>= 4 GiB`` alias (bits 54:32) and two LSU AxUSER values (12 bits, ``[11:4]``
non-zero, ``[3:0]`` non-zero and distinct), which the LSU alternates. Offset
bit 55 is fixed: 1 for AP, 0 for STEE; a second pass of each class flips it in
the same region. Alias region 0 maps one SMU page to the same page with address
bit 55 set, then to a page at or above 4 GiB with bit 55 clear. A third STEE
pass clears the region valid bit. The SMU aperture stays at its reset pair
(``0x8000_0000``, size ``0x4000_0000``); the test never writes it.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology", "Transaction
Routing" and its ``sep-outbound-attributes-table``, "Filtering and Protection";
``hw/sys/sep/doc/assets/sep-output-fabric.svg``;
``hw/ip/output_remap/regs/gen/adoc/output_remap.adoc``;
``hw/ip/axi_alias_remap/regs/gen/adoc/alias_remap.adoc``; ``hw/ip/axi_filter/doc/index.adoc``,
"Match, Then Permit", "Blocked Transactions"; ``hw/sys/smc/doc/assets/smc-traffic-filters.svg``):

* the SMU aperture, an address at or above 4 GiB and the AP and STEE regions
  leave on ``smn_outbound_axi_req_o`` through the outbound filter; a local
  scratch or system-CSR request does not;
* the AP and STEE remaps rewrite the address to ``{O[55:19], a[18:0]}`` and set
  the source ID in AxUSER[3:0] to OTHERS (zero); a STEE region with its valid
  bit clear passes the address unchanged (``output_remap.adoc``, ``valid``) and
  still leaves through the STEE remapper with OTHERS; the SMU path sets SEP's
  ID, which no specification gives as a number;
* AxPROT[1] (NS) leaves as 1 on the AP path and as the inverse of bit 55 of the
  outgoing address on the SMU and STEE paths; AxPROT bits 0 and 2 and address
  bit 55 pass unchanged;
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
  CHK-OUT-LOCAL-DATA each of those local reads answers OKAY and returns the
                    seeded value staged in the register field.
  CHK-OUT-CAPTURE   each PR-OUT capture carries the predicted address, the
                    issued AxPROT with bit 1 replaced by the NS of its path,
                    the issued W data and strobe, and AxUSER[3:0] 0 on the AP
                    and STEE paths. On the SMU path (aperture and >= 4 GiB)
                    AxUSER[3:0] is not OTHERS (0) and is the same on every
                    capture of the leaf, over two distinct issued values: SEP's
                    ID replaces the initiator's. X or Z on any captured field,
                    W user included, fails (VCS).
                    Logged, not graded (no stated value): the SMU-path number
                    (OBS-OUT-SRC-ID), AxUSER[11:4] of every capture and the W
                    user of SMU-path writes (OBS-OUT-WUSER).
  CHK-OUT-HIBIT     each path has passing captures in both directions at
                    issued AxPROT[1] 0 and 1 for each address bit 55 value:
                    AP with bit 55 set and clear (NS 1 for both), the SMU
                    aperture with bit 55 clear (NS 1), >= 4 GiB and STEE with
                    bit 55 clear (NS 1) and set (NS 0), and the STEE region
                    with its valid bit clear at the pass-through address (bit
                    55 clear, NS 1).
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import (
    FILTER_ADDR_MASK,
    OUTBOUND_MBX_MAGIC,
    RESP_DECERR,
    RESP_OKAY,
    SRC_ID_MASK,
    SepSrcIdGrade,
    draw_src_users,
    granule8,
    outbound_ns,
    outbound_user,
)
from env.sep_fabric_common import resp_name as _rname
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LC_PROD, LCC_FEAT_CTRL, lc_state_name
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import (
    AP_OUTPUT_REMAP_CTRL_0,
    LOCAL_MASTER_ALIAS_REMAP_CTRL_0,
    SEP_CPU_CTRL,
    RegBlock,
    sym,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_START,
    AP_BASE,
    REMAP_ATTRS,
    REMAP_STRIDE,
    STEE_BASE,
)
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccDemoteSeq
from seq_lib.sep_outbound_remap_seq import (
    AP_REGION_BASE,
    IDX_START,
    N_REGIONS,
    STEE_REGION_BASE,
)

# The 56-bit filter address field (START_ADDR / END_ADDR).
ADDR_MASK: int = FILTER_ADDR_MASK
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
SCRATCH_FIELD = RegBlock("SEP_SCRATCH_COLD").field_mask("SCRATCH_0_", "data") & 0xFFFF_FFFF
SMU_BASE_REG = SEP_CPU_CTRL.addr("SMU_GLOBAL_BASE_ADDR")
SMU_SIZE_REG = SEP_CPU_CTRL.addr("SMU_REGION_SIZE")
REMAP_OFFSET_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "offset")
REMAP_VALID_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "valid")
REGION_MASK = (1 << IDX_START) - 1
# sep_outbound_mbx latches its completion state on these 32-bit write words.
_MBX_MAGIC = OUTBOUND_MBX_MAGIC
BIT55 = 1 << 55
# Alias region 0 maps this SMU page, clear of the three SMU_WORDS, onto the
# same page with address bit 55 set.
_ALIAS = LOCAL_MASTER_ALIAS_REMAP_CTRL_0
ALIAS_PAGE = SMU_MID + 0x1000
ALIAS_VALID_FIELD = _ALIAS.field_mask("REGION_REGION_ATTRS", "valid")
ALIAS_FIELDS = {
    ALIAS_START: _ALIAS.field_mask("REGION_REGION_START", "start_addr"),
    ALIAS_END: _ALIAS.field_mask("REGION_REGION_END", "end_addr"),
    ALIAS_ATTRS: _ALIAS.field_mask("REGION_REGION_ATTRS", "offset") | ALIAS_VALID_FIELD,
}
SMU_HI_LOCAL = ALIAS_PAGE + IN_REGION

# Outbound entry pairs: entries 0 and 1 are the source-ID stack.
PAIR_SMU = (2, 3)
PAIR_AP = (4, 5)
PAIR_STEE = (6, 7)
PAIR_LOCAL = (8, 9)
PAIR_UNTRANSLATED = (10, 11)
PAIR_SMU_HI = (12, 13)
PAIR_STEE_HI = (14, 15)
PAIR_GE4G_LO = (16, 17)
PAIR_AP_LO = (18, 19)
PAIR_STEE_INV = (20, 21)
# Route class of a capture -> the outbound path whose rule it follows.
PATH = {"smu": "smu", "ge4g": "smu", "ap": "ap", "stee": "stee", "stee_inv": "stee"}
# CHK-OUT-HIBIT: the output address bit 55 values each route class reaches.
# The SMU aperture sits below 4 GiB at reset, so bit 55 set is the >= 4 GiB
# class; the STEE pass-through address is a local address (bit 55 clear).
HIBIT_CELLS = (
    ("ap", (0, 1)),
    ("smu", (0,)),
    ("ge4g", (0, 1)),
    ("stee", (0, 1)),
    ("stee_inv", (0,)),
)


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
        # The LSU alternates two AxUSER values: with two distinct issued
        # AxUSER[3:0], a constant SMU-path output is a visible replacement
        # whatever SEP's ID is (SepSrcIdGrade).
        self.users = draw_src_users(rng)
        self.ap = self._draw_class(rng, "ap", AP_REGION_BASE, AP_BASE, bit55=1)
        self.stee = self._draw_class(rng, "stee", STEE_REGION_BASE, STEE_BASE, bit55=0)
        self.stee_hi = _Cls(
            "stee", STEE_REGION_BASE, STEE_BASE, self.stee.region, self.stee.offset | BIT55
        )
        self.ap_lo = _Cls("ap", AP_REGION_BASE, AP_BASE, self.ap.region, self.ap.offset & ~BIT55)
        self.dir_first_write = bool(rng.getrandbits(1))
        # Alias offset to a page at or above 4 GiB with address bit 55 clear.
        self.ge4g_off = rng.randrange(1, 1 << 23) << 32
        self.rng = rng

    @staticmethod
    def _bad_target(t: int) -> bool:
        return (SMU_BASE <= t <= SMU_LAST) or (LOCAL_LO <= t <= LOCAL_HI)

    def _draw_class(
        self, rng: SepSeededRng, name: str, region_base: int, csr_base: int, *, bit55: int
    ) -> _Cls:
        region = rng.randrange(N_REGIONS)
        identity = (region_base + (region << IDX_START)) >> IDX_START
        while True:
            # Offset bit 55 is fixed per class; bits 54:19 are drawn.
            hi = rng.getrandbits(55 - IDX_START) | (bit55 << (55 - IDX_START))
            if hi == identity:
                continue
            c = _Cls(name, region_base, csr_base, region, hi << IDX_START)
            if self._bad_target(c.translated) or self._bad_target(c.local):
                continue
            # The second pass flips bit 55 of the offset; that target too
            # stays clear of the SMU aperture and the local window.
            if self._bad_target(c.translated ^ BIT55):
                continue
            # The two remapped words never share one granule, so a pair over
            # one never covers the other.
            if name == "stee" and (c.translated >> 3) == (self.ap.translated >> 3):
                continue
            return c

    def prot(self, prot1: int) -> int:
        """AxPROT with bit 1 forced and bits 0 and 2 seeded."""
        return (self.rng.getrandbits(3) & 0b101) | (prot1 << 1)

    def wdata(self) -> int:
        while True:
            d = self.rng.getrandbits(64)
            if (d & 0xFFFF_FFFF) not in _MBX_MAGIC and (d >> 32) not in _MBX_MAGIC:
                return d

    def dirs(self) -> tuple[bool, bool]:
        return (True, False) if self.dir_first_write else (False, True)

    def summary(self) -> str:
        return (
            f"seed={self.seed} users=0x{self.users[0]:03x},0x{self.users[1]:03x} "
            f"ge4g_off=0x{self.ge4g_off:x} ap_region={self.ap.region} "
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


class _Alias(SepAxiRegDriver):
    """Program alias region 0 over ALIAS_PAGE (``offset`` added); RDL-field read-back."""

    _DRIVER_TAG = "ALIASREG"

    async def program(self, valid: bool, offset: int = BIT55) -> None:
        words = {
            ALIAS_START: ALIAS_PAGE,
            ALIAS_END: ALIAS_PAGE + 0x1000,
            ALIAS_ATTRS: (offset | ALIAS_VALID_FIELD) if valid else 0,
        }
        for off, word in words.items():
            await self._wr(ALIAS_BASE + off, word & 0xFFFF_FFFF)
            await self._wr(ALIAS_BASE + off + 4, word >> 32)
        for off, word in words.items():
            got = await self._rd(ALIAS_BASE + off) | (await self._rd(ALIAS_BASE + off + 4) << 32)
            fc = field_compare(got, word, ALIAS_FIELDS[off])
            line = f"region=0 valid={int(valid)} off=0x{off:x} {fc.fields()}"
            assert fc.ok, f"ALIAS-READBACK FAIL: {line}"
            self.log.info("ALIAS-READBACK LOG: %s", line)


@pyuvm.test()
class sep_fabric_outbound_route_attr_test(sep_base_test):
    """SMU, AP and STEE outbound route, AxPROT and AxUSER, source-ID forcing, no bypass."""

    required_evidence = (
        "CHK-OUT-ROUTE",
        "CHK-OUT-USER",
        "CHK-OUT-NOBYPASS",
        "CHK-OUT-NOEXTRA",
        "CHK-OUT-LOCAL-DATA",
        "CHK-OUT-CAPTURE",
        "CHK-OUT-HIBIT",
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
        user: int | None = None,
    ) -> tuple[int, list]:
        """One LSU access; returns (resp, PR-OUT beats of the access).

        A response other than the expected one fails ``chk`` at once. Without
        ``user``, the access takes the next of the two drawn AxUSER values.
        """
        if user is None:
            user = self.tcfg.users[self.n_cell % 2]
            self.n_cell += 1
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
            f"prot=0x{prot:x} user=0x{user:03x} resp={_rname(seq.resp_code)} expect={_rname(want)} "
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
        path = PATH[cls]
        want_prot = (prot & 0b101) | (outbound_ns(path, pred) << 1)
        d = "W" if write else "R"
        assert len(addr_beats) == 1 and not other and (len(w_beats) == (1 if write else 0)), (
            f"CHK-OUT-CAPTURE FAIL: class={cls} dir={d} issued=0x{addr:x} beats="
            + " ".join(b.fmt() for b in beats)
        )
        b = addr_beats[0]
        # W user is part of the W beat, so X or Z on it fails here as well.
        unknown = b.has_unknown() or any(x.has_unknown() for x in w_beats)
        seen_w = w_beats[0] if write else None
        line = (
            f"class={cls} dir={d} issued=0x{addr:x} seen={_hx(b.addr)} prot={_hx(b.prot)} "
            f"user_issued=0x{user:03x} user_seen={_hx(b.user)} "
            f"wdata={_hx(seen_w.data) if write else 'na'} wstrb={_hx(seen_w.strb) if write else 'na'}"
        )
        if path == "smu":
            # SEP's ID has no stated number: per capture it is known and not
            # OTHERS; constancy and the replacement are graded over the leaf.
            why = self.src_grade.note(b.user, user)
            user_ok = why is None
            user_expect = f"SEP's ID ({why})" if why else "SEP's ID"
        else:
            user_ok = b.user is not None and (b.user & SRC_ID_MASK) == outbound_user(path)
            user_expect = f"[3:0]={outbound_user(path)}"
        ok = (
            not unknown
            and b.addr == pred
            and b.prot == want_prot
            and user_ok
            and (not write or (seen_w.data == wdata and seen_w.strb == 0xFF))
        )
        assert ok, (
            f"CHK-OUT-CAPTURE FAIL: {line} predicted=0x{pred:x} prot_issued=0x{prot:x} "
            f"prot_expect=0x{want_prot:x} user_expect={user_expect} wdata_issued=0x{wdata:x}"
            + (" X/Z" if unknown else "")
        )
        self.logger.info("CHK-OUT-CAPTURE PASS: %s prot_issued=0x%x", line, prot)
        # The specification states only the source ID, AxUSER[3:0]; the upper
        # bits and the W user are logged.
        self.logger.info(
            "OBS-OUT-USER-HI: class=%s dir=%s user_issued_11_4=0x%02x user_seen_11_4=0x%02x "
            "(value logged)",
            cls,
            d,
            user >> 4,
            b.user >> 4,
        )
        if write and path == "smu":
            self.logger.info(
                "OBS-OUT-WUSER: class=%s dir=W wuser_issued=0x%03x wuser_seen=0x%03x "
                "awuser_seen=0x%03x (value logged)",
                cls,
                user,
                seen_w.user,
                b.user,
            )
        self.n_capture += 1
        self.hibit.setdefault(cls, set()).add(((b.addr >> 55) & 1, (prot >> 1) & 1, d))

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
        """Steps 9 to 11 for one remapped class (13 for STEE)."""
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

    async def _bit55_leg(self, cls: str, local: int, pred: int, pair: tuple[int, int]) -> None:
        """Steps 7, 8, 12, 14 and 15: one route class at one outgoing address bit 55 value."""
        lo, hi = granule8(pred)
        await self._program_pair(pair, lo, hi)
        for write in self.tcfg.dirs():
            for p1 in (0, 1):
                await self._cell(
                    cls,
                    local,
                    pred,
                    write=write,
                    prot=self.tcfg.prot(p1),
                    expect_okay=True,
                    graded=True,
                    chk="CHK-OUT-HIBIT",
                )
        await self._pair_enable(pair, False)

    async def _stack_leg(self, c: _Cls) -> None:
        """Steps 16 to 18 for one remapped class."""
        lo, hi = granule8(c.translated)
        p1 = self._stack_prot1[c.name]
        prot = self.tcfg.prot(p1)
        ns = outbound_ns(c.name, c.translated)
        u = self.tcfg.users[0]
        e0 = FilterEntry(
            start=lo,
            end=hi,
            enabled=True,
            read_allowed=False,
            write_allowed=False,
            allow_ns=bool(ns),
            allow_burst=False,
            src_id=u & SRC_ID_MASK,
        )
        e1 = FilterEntry(
            start=lo,
            end=hi,
            enabled=True,
            read_allowed=True,
            write_allowed=True,
            allow_ns=bool(ns),
            allow_burst=False,
            src_id=0,
        )
        await self.filt.program(0, e0)
        await self.filt.program(1, e1)
        res = {}
        for write in self.tcfg.dirs():
            v = self.filt.model.verdict(c.translated, write=write, prot1=ns, user=0)
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
                user=u,
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
                user=u,
            )
            ctl[write] = r
        await self.filt.set_enabled(0, False)
        await self.filt.set_enabled(1, False)
        for write in self.tcfg.dirs():
            line = (
                f"class={c.name} dir={'W' if write else 'R'} user_issued=0x{u:03x} "
                f"resp={_rname(res[write])} "
                f"control_resp={_rname(ctl[write])}"
            )
            assert res[write] == RESP_OKAY and ctl[write] == RESP_DECERR, (
                f"CHK-OUT-USER FAIL: {line}"
            )
            self.logger.info("CHK-OUT-USER PASS: %s", line)

    async def _local_leg(self) -> None:
        """Step 19."""
        await self._program_pair(PAIR_LOCAL, LOCAL_LO, LOCAL_HI)
        rng = self.tcfg.rng
        m_scratch = (rng.getrandbits(32) | 1) & SCRATCH_FIELD
        m_dbg = (rng.getrandbits(32) | 1) & SW_DEBUG_FIELD
        staged = {COLD_SCRATCH: (m_scratch, SCRATCH_FIELD), SW_DEBUG: (m_dbg, SW_DEBUG_FIELD)}
        for addr, (m, _mask) in staged.items():
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
            m, mask = staged[addr]
            got = seq.rdata & mask
            rline = (
                f"{name} addr=0x{addr:x} resp={_rname(seq.resp_code)} got=0x{got:x} want=0x{m:x}"
            )
            assert seq.resp_code == RESP_OKAY and got == m, f"CHK-OUT-LOCAL-DATA FAIL: {rline}"
            self.logger.info("CHK-OUT-LOCAL-DATA PASS: %s", rline)
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
        """Steps 20 to 24."""
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
        self.n_cell = 0
        self.hibit: dict[str, set] = {}
        self.src_grade = SepSrcIdGrade("OUT")
        self._stack_prot1 = {"ap": cfg.rng.getrandbits(1), "stee": cfg.rng.getrandbits(1)}

        await self._bring_up()
        self.out = SepFabricTap("PR-OUT").start()
        self.filt = SepFilterBank(self, "out")
        remap = _Remap(self)
        await remap.program(cfg.ap, True)
        await remap.program(cfg.stee, True)

        await self._smu_leg()
        alias = _Alias(self)
        await alias.program(True)
        await self._bit55_leg("ge4g", SMU_HI_LOCAL, SMU_HI_LOCAL | BIT55, PAIR_SMU_HI)
        await alias.program(True, cfg.ge4g_off)
        await self._bit55_leg("ge4g", SMU_HI_LOCAL, SMU_HI_LOCAL + cfg.ge4g_off, PAIR_GE4G_LO)
        await alias.program(False)
        await self._remap_leg(cfg.ap, PAIR_AP)
        await remap.program(cfg.ap_lo, True)
        await self._bit55_leg("ap", cfg.ap_lo.local, cfg.ap_lo.translated, PAIR_AP_LO)
        await remap.program(cfg.ap, True)
        await self._remap_leg(cfg.stee, PAIR_STEE)
        await remap.program(cfg.stee_hi, True)
        await self._bit55_leg("stee", cfg.stee_hi.local, cfg.stee_hi.translated, PAIR_STEE_HI)
        # A STEE region with its valid bit clear passes the address unchanged.
        await remap.program(cfg.stee, False)
        await self._bit55_leg("stee_inv", cfg.stee.local, cfg.stee.local, PAIR_STEE_INV)
        await remap.program(cfg.stee, True)
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
        why = self.src_grade.finish(min_nonzero_issued=2)
        self.logger.info("%s", self.src_grade.obs_line())
        assert why is None, f"CHK-OUT-CAPTURE FAIL: path=smu src_id {why}"
        self.logger.info("CHK-OUT-CAPTURE PASS: path=smu src_id %s", self.src_grade.summary())
        self._chk_hibit()

    def _chk_hibit(self) -> None:
        """CHK-OUT-HIBIT over the captures that CHK-OUT-CAPTURE passed."""
        ok = True
        parts = []
        for cls, bits in HIBIT_CELLS:
            seen = self.hibit.get(cls, set())
            want = {(b, p1, d) for b in bits for p1 in (0, 1) for d in ("R", "W")}
            for b in bits:
                cells = ",".join(f"p{p}{d}" for bb, p, d in sorted(seen) if bb == b)
                ns = outbound_ns(PATH[cls], b << 55)
                parts.append(f"{cls}: bit55={b} ns={ns} cells={cells}")
            ok = ok and seen == want
        line = "; ".join(parts)
        assert ok, (
            f"CHK-OUT-HIBIT FAIL: {line} -- each route class needs R and W at issued AxPROT[1] "
            "0 and 1 for each bit-55 value"
        )
        self.logger.info("CHK-OUT-HIBIT PASS: %s", line)


def _hx(v) -> str:
    return "X" if v is None else f"0x{v:x}"


def _join(rs: list[int]) -> str:
    return ",".join(_rname(r) for r in rs)
