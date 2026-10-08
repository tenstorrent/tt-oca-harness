# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Local-master alias remap: region boundary classes, AxCACHE override, valid gate.

RANDCFG. The seed draws one alias region ``k``, a start page ``S``, a page
count (2 to 5) and so the non-inclusive end ``E``, an offset ``O`` (bits
55:12, bit 32 set, no carry out of bit 55), a ``cacheable`` value ``c`` and an
incoming AxCACHE ``a`` (AXI4 encodings 0x0, 0x2, 0x3, 0xF, ``a`` != ``c``). The
region lies in the SMU window above 0x8000_1000, so a miss reaches the outbound
filter at its own address, and a hit, which the offset moves to an address at
or above 0x1_0000_0000, reaches it at the translated address.

Model (``hw/ip/axi_alias_remap/regs/gen/adoc/alias_remap.adoc``,
``region_start``, ``region_end``, ``region_attrs``; ``hw/sys/sep/doc/fabric.adoc``,
"Address Remapping"):

* hit when the region is valid and ``S <= src < E`` (``end_addr`` non-inclusive);
* a hit adds the offset to address bits [55:12]:
  ``((src >> 12) + (O >> 12)) << 12 | src[11:0]``, and replaces all four AxCACHE
  bits with ``cacheable``;
* a miss keeps the address and AxCACHE.

Address anchor: the outbound filter (``hw/ip/axi_filter/doc/index.adoc``,
"Address Range Granule", "Blocked Transactions"). One outbound entry over the
8-byte granule of one address admits a request at that address (the outbound
responder answers OKAY) and refuses every other address with DECERR. Each
class probe runs twice: with the entry over the translated granule and with
the entry over the source granule. A hit is admitted only by the first and a
miss only by the second.

AxCACHE anchor: PR-ALIAS, the input and output requests of the alias remap
(observation tap). The output AxCACHE equals ``c`` on a hit and equals the
input AxCACHE of the same request on a miss. X or Z fails (VCS).

Checkers:
  CHK-ALIAS-CLASS  per class, direction and run (valid 1 and valid 0): the
                   admitted address of the pair of probes is the model address.
  CHK-ALIAS-CACHE  per probe: the AxCACHE at the alias remap output.
  CTL-ALIAS-RAND   stimulus completeness: at least one hit, one miss and one
                   AxCACHE override ran (no DUT claim).
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_common import RESP_DECERR, RESP_OKAY, granule8
from env.sep_fabric_common import resp_name as _rname
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LCC_FEAT_CTRL
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import LOCAL_MASTER_ALIAS_REMAP_CTRL_0, SEP_CPU_CTRL, sep_reg
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_START,
    ALIAS_STRIDE,
    OUTFILT_ENTRIES,
)
from seq_lib.sep_fabric_filter_bank_seq import ADDR_MASK as _FILTER_ADDR_MASK
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank

# The 56-bit filter address field (START_ADDR / END_ADDR).
ADDR_MASK: int = _FILTER_ADDR_MASK
TEST = "sep_fabric_alias_remap_attr_rand_test"

_META = LOCAL_MASTER_ALIAS_REMAP_CTRL_0
# One region per LOCAL_MASTER_ALIAS_REMAP_CTRL instance of the generated map.
N_REGIONS = sum(
    1
    for k in range(64)
    if hasattr(sep_reg, f"LOCAL_MASTER_ALIAS_REMAP_CTRL_{k}__REG_MAP_BASE_ADDR")
)
PAGE = 0x1000
START_FIELD = _META.field_mask("REGION_REGION_START", "start_addr")
END_FIELD = _META.field_mask("REGION_REGION_END", "end_addr")
OFFSET_FIELD = _META.field_mask("REGION_REGION_ATTRS", "offset")
CACHE_FIELD = _META.field_mask("REGION_REGION_ATTRS", "cacheable")
CACHE_LSB = _META.field_lsb("REGION_REGION_ATTRS", "cacheable")
VALID_FIELD = _META.field_mask("REGION_REGION_ATTRS", "valid")
ATTRS_FIELDS = OFFSET_FIELD | CACHE_FIELD | VALID_FIELD

# The SMU window at its reset aperture (sep_cpu_ctrl.adoc, SMU_GLOBAL_BASE_ADDR
# and SMU_REGION_SIZE). The test never writes the aperture registers.
SMU_LO = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
SMU_HI = SMU_LO + SEP_CPU_CTRL.reset("SMU_REGION_SIZE") - 1
# The bench outbound responder decodes stores to the first SMU page, so the
# regions start one page above the window base.
REGION_FLOOR = SMU_LO + 0x1000

CACHE_VALUES = (0x0, 0x2, 0x3, 0xF)
CLASSES = ("below", "start", "mid", "end_m1", "end", "above")
# AxPROT of every probe: data, non-secure, unprivileged. The outbound entry
# takes allow_ns = AxPROT[1].
PROBE_PROT = 0b010


def translate(src: int, offset: int) -> int:
    """``((src >> 12) + (O >> 12)) << 12 | src[11:0]`` (alias_remap.adoc, offset)."""
    return ((((src >> 12) + (offset >> 12)) << 12) | (src & (PAGE - 1))) & ADDR_MASK


class _Cfg:
    """Seed-drawn configuration of the leaf (single source of truth)."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.region = rng.randrange(N_REGIONS)
        self.pages = rng.randrange(2, 6)
        # Page S-1 at or above 0x8000_1000 and the page above E inside the SMU window.
        lo = (REGION_FLOOR + PAGE) // PAGE
        hi = (SMU_HI + 1) // PAGE - self.pages - 2
        self.start = rng.randrange(lo, hi + 1) * PAGE
        self.end = self.start + self.pages * PAGE
        # Offset: bits [55:12], bit 32 set, and the page sum of every probed
        # source keeps bit 32 set and stays below 2^56. [31:12] is drawn small
        # enough that no source page carries out of bit 31.
        top_src_page = (self.end + PAGE) >> 12
        lo_max = (1 << 20) - 1 - top_src_page
        o_lo = rng.randrange(0, lo_max + 1)
        o_hi = rng.randrange(0, (1 << 23) - 1)  # bits [55:33]; not all ones
        self.offset = (o_hi << 33) | (1 << 32) | (o_lo << 12)
        assert self.offset & OFFSET_FIELD == self.offset
        pair = rng.choice([(c, a) for c in CACHE_VALUES for a in CACHE_VALUES if c != a])
        self.cacheable, self.axcache = pair
        self.entry = rng.randrange(OUTFILT_ENTRIES)
        self.dir_first_write = bool(rng.getrandbits(1))
        self.wbytes = [rng.getrandbits(8) for _ in range(64)]
        self._wi = 0
        for cls in CLASSES:
            src = self.src(cls)
            t = translate(src, self.offset)
            if t < (1 << 32) or t > ADDR_MASK:
                raise RuntimeError(f"class {cls}: translated 0x{t:x} is not in [2^32, 2^56)")
            if src < REGION_FLOOR or src > SMU_HI:
                raise RuntimeError(f"class {cls}: source 0x{src:x} leaves the SMU window")

    def src(self, cls: str) -> int:
        return {
            "below": self.start - 1,
            "start": self.start,
            "mid": self.start + PAGE,
            "end_m1": self.end - 1,
            "end": self.end,
            "above": self.end + PAGE,
        }[cls]

    def hit(self, cls: str, valid: bool) -> bool:
        return valid and self.start <= self.src(cls) < self.end

    def wbyte(self) -> int:
        b = self.wbytes[self._wi % len(self.wbytes)]
        self._wi += 1
        return b

    def dirs(self) -> tuple[bool, bool]:
        return (True, False) if self.dir_first_write else (False, True)

    def summary(self) -> str:
        return (
            f"seed={self.seed} region={self.region} S=0x{self.start:x} E=0x{self.end:x} "
            f"pages={self.pages} O=0x{self.offset:014x} c=0x{self.cacheable:x} "
            f"a=0x{self.axcache:x} entry={self.entry}"
        )


class _AliasRegion(SepAxiRegDriver):
    """Program and read back one alias region on its RDL field bits."""

    _DRIVER_TAG = "ALIASREG"
    _AXI_SIZE = 2

    async def _wr64(self, addr: int, v: int) -> None:
        await self._wr(addr, v & 0xFFFF_FFFF)
        await self._wr(addr + 4, (v >> 32) & 0xFFFF_FFFF)

    async def _rd64(self, addr: int) -> int:
        return await self._rd(addr) | (await self._rd(addr + 4) << 32)

    async def program(self, k: int, start: int, end: int, attrs: int, tag: str) -> None:
        base = ALIAS_BASE + k * ALIAS_STRIDE
        await self._wr64(base + ALIAS_START, start)
        await self._wr64(base + ALIAS_END, end)
        await self._wr64(base + ALIAS_ATTRS, attrs)
        for name, off, want, mask in (
            ("region_start", ALIAS_START, start, START_FIELD),
            ("region_end", ALIAS_END, end, END_FIELD),
            ("region_attrs", ALIAS_ATTRS, attrs, ATTRS_FIELDS),
        ):
            fc = field_compare(await self._rd64(base + off), want, mask)
            line = f"region={k} {tag} {name} {fc.fields()}"
            assert fc.ok, f"ALIAS-READBACK FAIL: {line}"
            self.log.info("ALIAS-READBACK LOG: %s", line)


def attrs_word(offset: int, cacheable: int, valid: bool) -> int:
    return (
        (offset & OFFSET_FIELD)
        | ((cacheable << CACHE_LSB) & CACHE_FIELD)
        | (VALID_FIELD if valid else 0)
    )


@pyuvm.test()
class sep_fabric_alias_remap_attr_rand_test(sep_base_test):
    """Alias remap boundary classes, AxCACHE override and valid gate."""

    required_evidence = ("CHK-ALIAS-CLASS", "CHK-ALIAS-CACHE")

    async def _probe(
        self, addr: int, *, write: bool, cache: int, expect_okay: bool
    ) -> tuple[int, object, object]:
        """One 1-byte LSU probe (AxSIZE 0, AxLEN 0). Returns (resp, in beat, out beat)."""
        mi, mo = self.tap_in.mark(), self.tap_out.mark()
        if not expect_okay:
            self.env.axi_monitor.arm_expected_decerr(1)
        seq = SepAxiAccessSeq(
            "alias_probe",
            op=SepAxiOp.WRITE if write else SepAxiOp.READ,
            addr=addr,
            wdata=self.tcfg.wbyte() if write else 0,
            length=1,
            size=0,
            expect_error=not expect_okay,
            prot=PROBE_PROT,
            attrs={"cache": cache},
        )
        await self.start_seq(seq)
        if not expect_okay and seq.resp_code != RESP_DECERR:
            self.env.axi_monitor.release_expected_decerr(1)
        ch = "aw" if write else "ar"
        ins = [b for b in self.tap_in.since(mi, ch) if b.addr == addr]
        outs = self.tap_out.since(mo, ch)
        assert len(ins) == 1, (
            f"PR-ALIAS input shows {len(ins)} {ch} request(s) at 0x{addr:x}, expected 1"
        )
        assert len(outs) >= 1, f"PR-ALIAS output shows no {ch} request for 0x{addr:x}"
        # The output beat of this request is the first output beat at or after
        # the input handshake (the remap holds one request at a time per channel).
        out = next((b for b in outs if b.t_ps >= ins[0].t_ps), outs[-1])
        return seq.resp_code, ins[0], out

    async def _class_pair(self, cls: str, *, write: bool, valid: bool, cache: int) -> None:
        """Steps 5 to 7 of one class and direction."""
        cfg = self.tcfg
        src = cfg.src(cls)
        pred = translate(src, cfg.offset)
        hit = cfg.hit(cls, valid)
        d = "W" if write else "R"
        filt = self.filt
        e = cfg.entry

        # Entry over the translated granule.
        await filt.program(e, self._entry(pred))
        open_graded_window(TEST, self.logger)
        r_t, in_t, out_t = await self._probe(src, write=write, cache=cache, expect_okay=hit)
        close_graded_window(self.logger)
        # Entry over the source granule.
        await filt.program(e, self._entry(src))
        open_graded_window(TEST, self.logger)
        r_s, in_s, out_s = await self._probe(src, write=write, cache=cache, expect_okay=not hit)
        close_graded_window(self.logger)

        want_t = RESP_OKAY if hit else RESP_DECERR
        want_s = RESP_DECERR if hit else RESP_OKAY
        line = (
            f"region={cfg.region} valid={int(valid)} class={cls} dir={d} src=0x{src:x} "
            f"predicted=0x{pred:x} hit={int(hit)} hit_addr_resp={_rname(r_t)} "
            f"src_addr_resp={_rname(r_s)}"
        )
        assert r_t == want_t and r_s == want_s, f"CHK-ALIAS-CLASS FAIL: {line}"
        self.logger.info("CHK-ALIAS-CLASS PASS: %s", line)
        self.n_hit += int(hit)
        self.n_miss += int(not hit)
        for beat_in, beat_out in ((in_t, out_t), (in_s, out_s)):
            self._check_cache(beat_in, beat_out, hit=hit, write=write, issued=cache)

    def _entry(self, addr: int) -> FilterEntry:
        lo, hi = granule8(addr)
        return FilterEntry(
            start=lo,
            end=hi,
            enabled=True,
            read_allowed=True,
            write_allowed=True,
            allow_ns=bool(PROBE_PROT & 0b010),
            allow_burst=False,
            src_id=0,
        )

    def _check_cache(self, beat_in, beat_out, *, hit: bool, write: bool, issued: int) -> None:
        cfg = self.tcfg
        ci, co = beat_in.cache, beat_out.cache
        line = (
            f"region={cfg.region} dir={'W' if write else 'R'} cache_issued=0x{issued:x} "
            f"cache_remap_in={_hx(ci)} cache_remap_out={_hx(co)} "
            f"expect={'0x%x' % cfg.cacheable if hit else _hx(ci)} hit={int(hit)}"
        )
        assert ci is not None and co is not None, f"CHK-ALIAS-CACHE FAIL: X/Z AxCACHE: {line}"
        want = cfg.cacheable if hit else ci
        assert co == want, f"CHK-ALIAS-CACHE FAIL: {line}"
        if hit and (ci ^ cfg.cacheable) != 0xF:
            line += " bin=none(input does not differ from cacheable on all four bits)"
        self.logger.info("CHK-ALIAS-CACHE PASS: %s", line)
        if hit:
            self.n_override += 1

    async def run_scenario(self) -> None:
        self.tcfg = cfg = _Cfg(self.random_seed())
        self.logger.info("alias remap attr: %s", cfg.summary())
        self.n_hit = self.n_miss = self.n_override = 0

        # Step 1.
        await self.bring_up_no_cpu()
        feat = 0
        for half in (0, 1):
            rd = SepAxiAccessSeq(
                "feat_ctrl_rd", op=SepAxiOp.READ, addr=LCC_FEAT_CTRL + 4 * half, length=4, size=2
            )
            await self.start_seq(rd)
            feat |= (rd.rdata & 0xFFFF_FFFF) << (32 * half)
        self.logger.info("FEAT_CTRL LOG: value=0x%016x", feat)

        self.tap_in = SepFabricTap("PR-ALIAS-IN").start()
        self.tap_out = SepFabricTap("PR-ALIAS-OUT").start()
        self.filt = SepFilterBank(self, "out")
        alias = _AliasRegion(self)
        k = cfg.region

        # Steps 2 to 8: valid region, the six classes, read and write.
        await alias.program(
            k, cfg.start, cfg.end, attrs_word(cfg.offset, cfg.cacheable, True), "valid"
        )
        for cls in CLASSES:
            for write in cfg.dirs():
                await self._class_pair(cls, write=write, valid=True, cache=cfg.axcache)

        # Step 9: AxCACHE corners on the middle-page hit probe.
        mid = cfg.src("mid")
        for c, a in ((0xF, 0x0), (0x0, 0xF)):
            await alias.program(
                k, cfg.start, cfg.end, attrs_word(cfg.offset, c, True), f"corner_c{c:x}"
            )
            await self.filt.program(cfg.entry, self._entry(translate(mid, cfg.offset)))
            saved = cfg.cacheable
            cfg.cacheable = c
            for write in cfg.dirs():
                open_graded_window(TEST, self.logger)
                resp, bi, bo = await self._probe(mid, write=write, cache=a, expect_okay=True)
                close_graded_window(self.logger)
                assert resp == RESP_OKAY, (
                    f"CHK-ALIAS-CLASS FAIL: corner c=0x{c:x} a=0x{a:x} mid hit resp={_rname(resp)}"
                )
                self._check_cache(bi, bo, hit=True, write=write, issued=a)
            cfg.cacheable = saved

        # Step 10: byte E miss probe keeps AxCACHE.
        await alias.program(
            k, cfg.start, cfg.end, attrs_word(cfg.offset, cfg.cacheable, True), "miss_cache"
        )
        end_b = cfg.src("end")
        await self.filt.program(cfg.entry, self._entry(end_b))
        for write in cfg.dirs():
            open_graded_window(TEST, self.logger)
            resp, bi, bo = await self._probe(
                end_b, write=write, cache=cfg.axcache, expect_okay=True
            )
            close_graded_window(self.logger)
            assert resp == RESP_OKAY, f"CHK-ALIAS-CLASS FAIL: byte E miss resp={_rname(resp)}"
            self._check_cache(bi, bo, hit=False, write=write, issued=cfg.axcache)

        # Step 11: valid-clear run, the six classes, read and write.
        await alias.program(
            k, cfg.start, cfg.end, attrs_word(cfg.offset, cfg.cacheable, False), "valid_clear"
        )
        for cls in CLASSES:
            for write in cfg.dirs():
                await self._class_pair(cls, write=write, valid=False, cache=cfg.axcache)

        # Step 12: valid-clear with cacheable 0xF, middle page, AxCACHE 0x0.
        await alias.program(
            k, cfg.start, cfg.end, attrs_word(cfg.offset, 0xF, False), "valid_clear_cF"
        )
        await self.filt.program(cfg.entry, self._entry(mid))
        for write in cfg.dirs():
            open_graded_window(TEST, self.logger)
            resp, bi, bo = await self._probe(mid, write=write, cache=0x0, expect_okay=True)
            close_graded_window(self.logger)
            assert resp == RESP_OKAY, (
                f"CHK-ALIAS-CLASS FAIL: valid-clear cacheable 0xF mid miss resp={_rname(resp)}"
            )
            self._check_cache(bi, bo, hit=False, write=write, issued=0x0)

        # Step 13: restore.
        await alias.program(k, 0, 0, 0, "restore")
        await self.filt.restore_reset(cfg.entry)
        await self.tap_in.stop()
        await self.tap_out.stop()

        line = (
            f"seed={cfg.seed} hits={self.n_hit} misses={self.n_miss} "
            f"cache_override={self.n_override}"
        )
        assert self.n_hit >= 1 and self.n_miss >= 1 and self.n_override >= 1, (
            f"CTL-ALIAS-RAND FAIL: {line}"
        )
        self.logger.info("CTL-ALIAS-RAND LOG: %s", line)


def _hx(v) -> str:
    return "X" if v is None else f"0x{v:x}"
