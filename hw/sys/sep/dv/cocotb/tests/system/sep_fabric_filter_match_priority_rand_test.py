# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter match, priority, source ID, default deny and granule on both SEP filters.

The inbound filter (System Interface master on ``m_axi``) and the outbound
filter (CPU-LSU master on ``s_axi``, through the route demux) decide every
probe of this leaf. The expected verdict of each probe comes from the filter
reference model ``env.sep_filter_model``, written from
``hw/ip/axi_filter/doc/index.adoc`` ("Instances", "Match, Then Permit",
"Address Range Granule", "Blocked Transactions"),
``hw/ip/axi_filter/regs/gen/adoc/filter_ctrl.adoc`` and
``hw/sys/smc/doc/assets/smc-traffic-filters.svg`` (``src_id`` against
AxUSER[3:0]). The model reads only the programmed entry fields and the probe
attributes.

Address sources:

* the outbound route: ``hw/sys/sep/doc/fabric.adoc`` ("Fabric Topology"). The
  SMU aperture passes to the outbound filter with the initiator AxUSER. The AP
  and STEE output remaps replace the address with ``offset[55:19]`` joined
  with the region address bits [18:0]
  (``hw/ip/output_remap/regs/gen/adoc/output_remap.adoc``, ``region_attrs``)
  and set the source ID to OTHERS (0);
* the units: ``hw/sys/sep/regs/gen/adoc/memory_map.adoc``.

Legs:

* leg 3, default deny: the reset state, all 48 entries armed but disabled,
  the wide-range control and the enabled control entry per instance;
* leg 1, match and priority: (entry state, attribute) cells on a seeded entry
  stack, and the corner cells fall-through (a), permission block (b), burst
  fall-through (c, inbound), disabled lowest entry (d), read and write that
  choose different entries (e) and no match (g);
* leg 2, source ID: exact, mismatch, wildcard, fall-through and upper AxUSER
  bits inbound; OTHERS against the AP and STEE remaps and the exact and
  mismatch cells on the SMU aperture outbound;
* leg 4, granule: seven (granule, shape, instance) cells probed at the widened
  edges.

Checkers: CHK-FILTER-CELL, CHK-FILTER-SRC, CTL-FILTER-RAND (stimulus
completeness, no DUT claim), CHK-RESET-DENY, CHK-RESET-DENY-ARMED,
CHK-RESET-DENY-CONTROL, CHK-GRANULE. CTL-FILTER-ACTIVE is the bring-up
precondition. The inbound cells that open tests grade run as controls and log
CTL-FILTER-CELL / CTL-RESET-DENY lines.

Not graded here: ``group_id`` (random value, logged), the ``locked`` bit, the
filter register storage, the SEP debug bypass, the response of the
extension-window and ``0x4000_0100`` reset-state probes (logged), and the
START_ADDR / END_ADDR read-back after a write (logged).

Run mode: no_cpu, real PROD fuse sense with SEC_DIS 0 and fixed SIP_DIS and
SYS_DIS whose DBG_1 bit 0 is clear, so the inbound filter is active.
RANDCFG (legs 1, 2, 4) and RAND-REP (leg 3); every draw comes from
``SepSeededRng`` and the run seed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_tap import start_taps, stop_taps
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_filter_model import TERM_SRC, FilterEntry, FilterModel, FilterVerdict
from env.sep_lcc_golden import LC_PROD, LCC_FEAT_CTRL, feat_ctrl_expected
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_csr_bank_seq import AP_BASE, INFILT_BASE, STEE_BASE
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_outbound_remap_seq import (
    AP_REGION_BASE,
    IDX_START,
    REMAP_ATTRS,
    REMAP_OFFSET_MASK,
    REMAP_VALID,
    STEE_REGION_BASE,
)

TEST = "sep_fabric_filter_match_priority_rand_test"

RESP_OKAY = 0
RESP_DECERR = 3
_RESP = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", -1: "NONE"}
AXI_BURST_INCR = 1
M32 = 0xFFFF_FFFF
M64 = (1 << 64) - 1

# Pinned image: PROD, SEC_DIS 0, DBG_1 bit 0 clear in both disable vectors.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0E
_SYS_DIS = 0x00FF_00FF_00FF_00FE
_MAX_SENSE_CYCLES = 20_000

# Units (hw/sys/sep/regs/gen/adoc/memory_map.adoc).
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SCRATCH_BASE = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")
SCRATCH_BYTES = sym("SEP_SCRATCH_COLD_REG_MAP_SIZE")
# Entry ranges of a scratch cell are placed from the scratch-cold base to the
# end of the scratch-warm block: the filter compares addresses only, and the
# block above holds the ranges that do not cover the probe. No probe targets
# scratch-warm.
SCRATCH_PLACE_LO = SCRATCH_BASE
SCRATCH_PLACE_HI = (
    sym("SEP_SCRATCH_WARM_REG_MAP_BASE_ADDR") + sym("SEP_SCRATCH_WARM_REG_MAP_SIZE") - 1
)
MBOX_WORD = sym("AXIL_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR")
CRYPTO_WORD = sym("AES_REG_MAP_BASE_ADDR")
CPU_CTRL_WORD = SEP_CPU_CTRL.addr("SEP_GLOBAL_BASE_ADDR")
FILTER_PAGE_WORD = INFILT_BASE
# Inbound register classes of the deny probes; their unit sits behind no
# PR-XEXT or PR-CSR tap, so their allow control reads PR-INFLT.
REG_CLASSES = ("mbox", "crypto", "fpage", "cpuctrl")
EXT_BASE = sym("SEP_EXTERNAL_REG_MAP_BASE_ADDR")
EXT_END = EXT_BASE + sym("SEP_EXTERNAL_REG_MAP_SIZE") - 1
SHIM_BASE = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_BASE_ADDR")
SHIM_SIZE = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_SIZE")
XBAR_LIMIT_WORD = 0x4000_0100
SMU_BASE = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
SMU_END = SMU_BASE + SEP_CPU_CTRL.reset("SMU_REGION_SIZE") - 1
# The bench responder decodes stores to the first SMU page as console output.
SMU_SAFE_LO = 0x8000_2000

# Output remap region 0 (hw/ip/output_remap/regs/gen/adoc/output_remap.adoc).
REGION_BITS = 19
AP_OFFSET = 0x20_0000_0000
STEE_OFFSET = 0x28_0000_0000
if IDX_START != REGION_BITS:
    raise RuntimeError(f"output remap region span is 2^{IDX_START}; the contract states 2^19")
REMAP_FIELDS = REMAP_OFFSET_MASK | REMAP_VALID

ARMED_END = (1 << 48) - 1
G4K = 0x1000
G8 = 0x8


def remap_target(offset: int, local: int, region_base: int) -> int:
    """Outbound address of an AP or STEE region-0 access (output_remap.adoc)."""
    intra = (local - region_base) & ((1 << REGION_BITS) - 1)
    return ((offset >> REGION_BITS) << REGION_BITS) | intra


@dataclass
class Probe:
    """One transaction of the leaf: master, target class, attributes."""

    inst: str  # "in" (SI, inbound filter) or "out" (LSU, outbound filter)
    cls: str  # sram, scratch, mbox, crypto, fpage, cpuctrl, smu, ap, stee
    addr: int  # master address
    faddr: int  # address at the filter
    write: bool
    prot1: int = 0
    user: int = 0  # master AxUSER
    fuser: int = 0  # AxUSER[3:0] at the filter
    axlen: int = 0
    nbytes: int = 8

    @property
    def dir(self) -> str:
        return "W" if self.write else "R"


@dataclass
class Result:
    resp: int
    data: int | None
    target_seen: int
    out_seen: int
    readback: int | None
    verdict: FilterVerdict
    perm: int


@pyuvm.test()
class sep_fabric_filter_match_priority_rand_test(sep_base_test):
    """Both filters: lowest match wins, failed terms fall through, unmatched traffic is refused."""

    required_evidence = (
        "CHK-FILTER-CELL",
        "CHK-FILTER-SRC",
        "CHK-RESET-DENY",
        "CHK-RESET-DENY-ARMED",
        "CHK-RESET-DENY-CONTROL",
        "CHK-GRANULE",
    )

    # ------------------------------------------------------------------
    # Graded window
    # ------------------------------------------------------------------
    def _gate(self, graded: bool) -> None:
        if graded:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    # ------------------------------------------------------------------
    # Bus access
    # ------------------------------------------------------------------
    async def _lsu(
        self, op, addr, *, wdata=0, length=4, size=2, prot=None, user=0, expect_error=False
    ):
        seq = SepAxiAccessSeq(
            "fmp_lsu",
            op=op,
            addr=addr,
            wdata=wdata,
            length=length,
            size=size,
            prot=prot,
            user=user,
            expect_error=expect_error,
            allow_unverified_write_resp=(op is SepAxiOp.WRITE and expect_error),
        )
        await self.start_seq(seq)
        return seq

    async def _lrd(self, addr: int, length: int = 4) -> int:
        seq = await self._lsu(SepAxiOp.READ, addr, length=length, size=2 if length == 4 else 3)
        assert seq.resp_ok, f"LSU read 0x{addr:08x} resp={_RESP.get(seq.resp_code)}"
        return seq.rdata

    async def _lwr(self, addr: int, data: int, length: int = 4) -> None:
        seq = await self._lsu(
            SepAxiOp.WRITE, addr, wdata=data, length=length, size=2 if length == 4 else 3
        )
        assert seq.resp_ok, f"LSU write 0x{addr:08x} resp={_RESP.get(seq.resp_code)}"

    async def _si(self, p: Probe, wdata: int = 0, *, allow_timeout: bool = False):
        size = 2 if p.nbytes == 4 else 3
        length = p.nbytes * (p.axlen + 1)
        seq = SepAxiAccessSeq(
            "fmp_si",
            op=SepAxiOp.WRITE if p.write else SepAxiOp.READ,
            addr=p.addr,
            wdata=wdata,
            length=length,
            size=size,
            burst=AXI_BURST_INCR if p.axlen else None,
            prot=p.prot1 << 1,
            user=p.user,
            allow_unverified_write_resp=p.write,
            allow_timeout=allow_timeout and not p.write,
        )
        await self.start_ext_seq(seq)
        assert not seq.timed_out or allow_timeout, f"SI {p.dir} 0x{p.addr:08x} timed out"
        return seq

    # ------------------------------------------------------------------
    # Memory model of the staged words (4-byte granularity)
    # ------------------------------------------------------------------
    def _mget(self, addr: int, nbytes: int) -> int:
        if nbytes == 4:
            return self.mem[addr]
        v = 0
        for i in range(nbytes // 4):
            v |= self.mem[addr + 4 * i] << (32 * i)
        return v

    def _mset(self, addr: int, nbytes: int, value: int) -> None:
        for i in range(nbytes // 4):
            self.mem[addr + 4 * i] = (value >> (32 * i)) & M32

    def _fresh(self, nbytes: int, avoid: int) -> int:
        """A seeded value that differs, in every 32-bit lane, from ``avoid`` and the markers."""
        while True:
            v = self.rng.getrandbits(8 * nbytes)
            lanes = [(v >> (32 * i)) & M32 for i in range(nbytes // 4)]
            old = [(avoid >> (32 * i)) & M32 for i in range(nbytes // 4)]
            if all(a != b and a not in self.markers and a != 0 for a, b in zip(lanes, old)):
                return v

    async def _stage(self, addr: int, nbytes: int) -> None:
        """Stage a non-zero marker at ``addr`` and read it back."""
        while True:
            v = self.rng.getrandbits(8 * nbytes)
            lanes = [(v >> (32 * i)) & M32 for i in range(nbytes // 4)]
            if all(x != 0 and x not in self.markers for x in lanes):
                break
        for i, lane in enumerate(lanes):
            await self._lwr(addr + 4 * i, lane)
            self.markers.add(lane)
        for i, lane in enumerate(lanes):
            got = await self._lrd(addr + 4 * i)
            assert got == lane, f"staged 0x{addr + 4 * i:08x} read 0x{got:08x} != 0x{lane:08x}"
            self.mem[addr + 4 * i] = lane

    # ------------------------------------------------------------------
    # Probe execution
    # ------------------------------------------------------------------
    def _bank(self, inst: str) -> SepFilterBank:
        return self.inb if inst == "in" else self.outb

    def _verdict(self, p: Probe) -> FilterVerdict:
        return self._bank(p.inst).model.verdict(
            p.faddr, write=p.write, prot1=p.prot1, user=p.fuser, axlen=p.axlen
        )

    def _target_mark(self) -> tuple[int, int, int]:
        return (self.taps["PR-XEXT"].mark(), self.taps["PR-CSR"].mark(), self.taps["PR-OUT"].mark())

    def _seen(self, mark, p: Probe) -> tuple[int, int]:
        ch = "aw" if p.write else "ar"
        xe = self.taps["PR-XEXT"].count(mark[0], ch)
        cs = self.taps["PR-CSR"].count(mark[1], ch)
        out = self.taps["PR-OUT"].count(mark[2], ch)
        return xe + cs, out

    async def _run(self, p: Probe) -> Result:
        """Run one probe and grade it against the model. Returns the evidence."""
        v = self._verdict(p)
        perm = int(
            v.winner is not None and self._bank(p.inst).model.entries[v.winner].permits(p.write)
        )
        mark = self._target_mark()
        data = None
        readback = None
        if p.inst == "in":
            nb = p.nbytes * (p.axlen + 1)
            mem_ok = p.cls in ("sram", "scratch")
            old = self._mget(p.addr, nb) if mem_ok else 0
            wdata = self._fresh(nb, old) if p.write else 0
            seq = await self._si(p, wdata)
            resp = seq.resp_code
            target_seen, out_seen = self._seen(mark, p)
            if not p.write:
                data = seq.rdata
            if mem_ok:
                if p.write and v.allowed:
                    self._mset(p.addr, nb, wdata)
                    data = wdata
                if p.write:
                    readback = 0
                    for i in range(nb // 4):
                        readback |= (await self._lrd(p.addr + 4 * i)) << (32 * i)
            tag = f"inst=in cls={p.cls} dir={p.dir} addr=0x{p.addr:08x} prot1={p.prot1} user=0x{p.user:x} len={p.axlen}"
            assert resp == (RESP_OKAY if v.allowed else RESP_DECERR), (
                f"{self._chk} FAIL: probe {tag}: resp={_RESP.get(resp)} model={v.summary()}"
            )
            if v.allowed:
                assert target_seen >= 1, (
                    f"{self._chk} FAIL: probe {tag}: admitted but no PR-XEXT/PR-CSR handshake"
                )
                if mem_ok and not p.write:
                    want = self._mget(p.addr, nb)
                    mask = M32 if p.cls == "scratch" else (1 << (8 * nb)) - 1
                    assert (data & mask) == (want & mask), (
                        f"{self._chk} FAIL: probe {tag}: rdata 0x{data:x} != staged 0x{want:x} (mask 0x{mask:x})"
                    )
            else:
                assert target_seen == 0, (
                    f"{self._chk} FAIL: probe {tag}: refused but {target_seen} PR-XEXT/PR-CSR handshake(s)"
                )
            if readback is not None:
                want = self._mget(p.addr, nb)
                assert readback == want, (
                    f"{self._chk} FAIL: probe {tag}: LSU read-back 0x{readback:x} != model 0x{want:x} "
                    f"(allowed={v.allowed})"
                )
        else:
            deny = not v.allowed
            mon = self.env.axi_monitor
            if deny:
                mon.arm_expected_decerr(1)
            seq = await self._lsu(
                SepAxiOp.WRITE if p.write else SepAxiOp.READ,
                p.addr,
                wdata=self.rng.getrandbits(32) if p.write else 0,
                prot=p.prot1 << 1,
                user=p.user,
                expect_error=deny,
            )
            resp = seq.resp_code
            if deny and resp != RESP_DECERR:
                mon.release_expected_decerr(1)
            target_seen, out_seen = self._seen(mark, p)
            data = None if p.write else seq.rdata
            tag = f"inst=out cls={p.cls} dir={p.dir} addr=0x{p.addr:08x} faddr=0x{p.faddr:x} prot1={p.prot1} user=0x{p.user:x}"
            assert resp == (RESP_OKAY if v.allowed else RESP_DECERR), (
                f"{self._chk} FAIL: probe {tag}: resp={_RESP.get(resp)} model={v.summary()}"
            )
            if v.allowed:
                assert out_seen >= 1, (
                    f"{self._chk} FAIL: probe {tag}: admitted but no PR-OUT handshake"
                )
                addrs = self.taps["PR-OUT"].addrs(mark[2], "aw" if p.write else "ar")
                self.logger.info(
                    "probe %s PR-OUT addr=%s",
                    tag,
                    [hex(a) if a is not None else "X" for a in addrs],
                )
            else:
                assert out_seen == 0, (
                    f"{self._chk} FAIL: probe {tag}: refused but {out_seen} PR-OUT handshake(s)"
                )
        return Result(resp, data, target_seen, out_seen, readback, v, perm)

    # ------------------------------------------------------------------
    # Entry programming
    # ------------------------------------------------------------------
    async def _load(self, inst: str, entries: dict[int, FilterEntry]) -> None:
        """Program the entries of one cell; every other entry used earlier goes to reset."""
        bank = self._bank(inst)
        used = self.used[inst]
        for idx in sorted(used - set(entries)):
            await bank.restore_reset(idx)
        for idx, e in sorted(entries.items()):
            await bank.program(idx, e)
        self.used[inst] = set(entries)

    async def _clear(self, inst: str) -> None:
        await self._load(inst, {})

    # ------------------------------------------------------------------
    # Bring-up
    # ------------------------------------------------------------------
    async def _bring_up(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        golden = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        lo = await self._lrd(LCC_FEAT_CTRL)
        hi = await self._lrd(LCC_FEAT_CTRL + 4)
        feat = lo | (hi << 32)
        sep_dbg = feat & 1
        if feat != golden or sep_dbg != 0:
            self.logger.error(
                "CTL-FILTER-ACTIVE FAIL: feat_ctrl=0x%016x golden=0x%016x", feat, golden
            )
            raise AssertionError(
                f"CTL-FILTER-ACTIVE FAIL: feat_ctrl=0x{feat:016x} golden=0x{golden:016x}"
            )
        self.logger.info(
            "CTL-FILTER-ACTIVE LOG: feat_ctrl=0x%016x golden=0x%016x sep_dbg=%d",
            feat,
            golden,
            sep_dbg,
        )

    async def _remap(self, csr_base: int, offset: int, valid: bool) -> None:
        attrs = csr_base + REMAP_ATTRS
        word = (offset & REMAP_OFFSET_MASK) | (REMAP_VALID if valid else 0)
        await self._lwr(attrs, word & M32)
        await self._lwr(attrs + 4, word >> 32)
        got = await self._lrd(attrs) | (await self._lrd(attrs + 4) << 32)
        rsvd = got & ~REMAP_FIELDS & M64
        line = (
            f"remap 0x{csr_base:08x} region 0 attrs=0x{got & REMAP_FIELDS:016x} "
            f"want=0x{word:016x} field_mask=0x{REMAP_FIELDS:016x} rsvd=0x{rsvd:x}"
        )
        assert (got & REMAP_FIELDS) == word, f"REMAP-READBACK FAIL: {line}"
        self.logger.info("REMAP-READBACK LOG: %s", line)

    # ------------------------------------------------------------------
    # Probe builders
    # ------------------------------------------------------------------
    def _p_in(
        self,
        cls: str,
        write: bool,
        prot1: int,
        *,
        user: int = 0,
        axlen: int = 0,
        addr: int | None = None,
    ) -> Probe:
        a = (
            addr
            if addr is not None
            else {
                "sram": self.s0,
                "scratch": self.c0,
                "mbox": MBOX_WORD,
                "crypto": CRYPTO_WORD,
                "fpage": FILTER_PAGE_WORD,
                "cpuctrl": CPU_CTRL_WORD,
                "ext": self.ext_word,
                "xlim": XBAR_LIMIT_WORD,
            }[cls]
        )
        nbytes = 4 if cls in ("scratch", "mbox", "crypto", "fpage", "cpuctrl") else 8
        return Probe("in", cls, a, a, write, prot1, user, user & 0xF, axlen, nbytes)

    def _p_out(
        self, cls: str, write: bool, prot1: int, *, user: int = 0, addr: int | None = None
    ) -> Probe:
        if cls == "smu":
            a = addr if addr is not None else self.smu_word
            return Probe("out", cls, a, a, write, prot1, user, user & 0xF, 0, 4)
        base, off = (AP_REGION_BASE, AP_OFFSET) if cls == "ap" else (STEE_REGION_BASE, STEE_OFFSET)
        a = addr if addr is not None else base + self.ap_intra
        return Probe("out", cls, a, remap_target(off, a, base), write, prot1, user, 0, 0, 4)

    # ------------------------------------------------------------------
    # Windows for the entry stacks
    # ------------------------------------------------------------------
    def _region(self, p: Probe) -> tuple[int, int]:
        """The address span a cell may place entries in (filter-side addresses)."""
        if p.cls == "sram":
            return SRAM_BASE, SRAM_BASE + SRAM_SIZE - 1
        if p.cls == "scratch":
            return SCRATCH_PLACE_LO, SCRATCH_PLACE_HI
        if p.cls == "smu":
            return SMU_SAFE_LO, SMU_END
        base = p.faddr & ~((1 << REGION_BITS) - 1)
        return base, base + (1 << REGION_BITS) - 1

    def _cover(self, p: Probe, burst: bool) -> tuple[int, int]:
        """A seeded range whose widened span holds every byte of the probe."""
        lo_r, hi_r = self._region(p)
        g = G4K if burst else G8
        first = p.faddr & ~(g - 1)
        last = (p.faddr + p.nbytes * (p.axlen + 1) - 1) | (g - 1)
        lo = max(lo_r, first - g * self.rng.randrange(0, 4))
        hi = min(hi_r, last + g * self.rng.randrange(0, 4))
        return lo + self.rng.randrange(0, g), hi - self.rng.randrange(0, g)

    def _apart(self, p: Probe) -> tuple[int, int]:
        """A seeded 8-byte-granule range near the probe that does not hold it."""
        lo_r, hi_r = self._region(p)
        first = p.faddr & ~7
        last = (p.faddr + p.nbytes * (p.axlen + 1) - 1) | 7
        span = 8 * self.rng.randrange(1, 32)
        gap = 8 * self.rng.randrange(0, 8)
        below = (max(lo_r, first - gap - span), first - gap - 1)
        above = (last + 1 + gap, min(hi_r, last + gap + span))
        sides = [r for r in (below, above) if r[0] <= r[1] and r[0] >= lo_r and r[1] <= hi_r]
        assert sides, f"no room for an apart range around 0x{p.faddr:x}"
        return self.rng.choice(sides)

    def _entry(
        self, p: Probe, rng_span, *, enabled=True, rd=True, wr=True, ns=None, burst=False, src=0
    ) -> FilterEntry:
        return FilterEntry(
            start=rng_span[0],
            end=rng_span[1],
            enabled=enabled,
            read_allowed=rd,
            write_allowed=wr,
            allow_ns=bool(p.prot1 if ns is None else ns),
            allow_burst=burst,
            src_id=src,
            group_id=self.rng.randrange(16),
        )

    def _noise(self, p: Probe, idxs: list[int], below_ok: bool) -> dict[int, FilterEntry]:
        """Entries that never match the probe: apart ranges, or a covering range
        with a failing term (``below_ok`` allows covering noise)."""
        out = {}
        for i in idxs:
            kind = self.rng.randrange(3) if below_ok else 0
            if kind == 0:
                out[i] = self._entry(
                    p,
                    self._apart(p),
                    ns=self.rng.getrandbits(1),
                    rd=bool(self.rng.getrandbits(1)),
                    wr=bool(self.rng.getrandbits(1)),
                )
            elif kind == 1:
                out[i] = self._entry(p, self._cover(p, False), enabled=False)
            else:
                out[i] = self._entry(p, self._cover(p, False), ns=1 - p.prot1)
        return out

    def _verdict_of(self, inst: str, entries: dict[int, FilterEntry], p: Probe) -> FilterVerdict:
        m = FilterModel(len(self._bank(inst).model.entries), inst)
        for i, e in entries.items():
            m.set(i, e)
        return m.verdict(p.faddr, write=p.write, prot1=p.prot1, user=p.fuser, axlen=p.axlen)

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------
    def _cell_line(self, p: Probe, r: Result, control_seen: int) -> str:
        v = r.verdict
        winner = "none" if v.winner is None else str(v.winner)
        perm = r.perm
        data = r.data if r.data is not None else 0
        return (
            f"inst={p.inst} dir={p.dir} prot1={p.prot1} len={p.axlen} winner={winner} perm={perm} "
            f"expect={v.resp} got={_RESP.get(r.resp)} data=0x{data:x} "
            f"target_seen={r.target_seen if p.inst == 'in' else r.out_seen} control_seen={control_seen}"
        )

    def _count(self, inst: str, v: FilterVerdict) -> None:
        s = self.stats[inst]
        s["cells"] += 1
        if v.allowed:
            s["allow"] += 1
        else:
            s["block"] += 1
        if v.allowed and v.fallthrough:
            s["fallthrough"] += 1
        if v.reason == "perm_block":
            s["perm_block"] += 1
        if v.reason == "no_match":
            s["no_match"] += 1

    # ------------------------------------------------------------------
    # Leg 3: default deny
    # ------------------------------------------------------------------
    def _deny_probes_in(self) -> list[Probe]:
        ps = []
        for prot1 in (0, 1):
            for cls in ("sram", "scratch", "mbox", "crypto"):
                for w in (False, True):
                    ps.append(self._p_in(cls, w, prot1))
            ps.append(self._p_in("fpage", False, prot1))
            ps.append(self._p_in("cpuctrl", False, prot1))
        return ps

    def _deny_probes_out(self) -> list[Probe]:
        return [self._p_out(c, False, prot1) for prot1 in (0, 1) for c in ("smu", "ap")]

    async def _deny_round(self, label: str, graded_in: bool) -> dict:
        """Steps 4 to 7: every probe answers DECERR and reaches no target."""
        st = {
            "in_probes": 0,
            "in_p0": 0,
            "in_p1": 0,
            "in_decerr": 0,
            "in_seen": 0,
            "out_probes": 0,
            "out_p0": 0,
            "out_p1": 0,
            "out_decerr": 0,
            "out_seen": 0,
            "rb_same": 0,
            "ext_seen": 0,
        }
        self._gate(graded_in)
        self._chk = "CHK-RESET-DENY-ARMED" if graded_in else "CTL-RESET-DENY"
        for p in self._deny_probes_in():
            r = await self._run(p)
            assert not r.verdict.allowed, f"{label}: model admits {p}"
            st["in_probes"] += 1
            st["in_p0" if p.prot1 == 0 else "in_p1"] += 1
            st["in_decerr"] += int(r.resp == RESP_DECERR)
            st["in_seen"] += r.target_seen
            if r.readback is not None:
                st["rb_same"] += 1
        # Step 5: the staged words keep their staged value.
        for a, nb in ((self.s0, 8), (self.s0 + 8, 8), (self.c0, 4)):
            for i in range(nb // 4):
                got = await self._lrd(a + 4 * i)
                assert got == self.mem[a + 4 * i] == self.staged[a + 4 * i], (
                    f"{self._chk} FAIL: {label}: staged word 0x{a + 4 * i:08x} read 0x{got:08x}, staged "
                    f"0x{self.staged[a + 4 * i]:08x}"
                )
                st["rb_same"] += 1
        # Step 6: outbound, graded.
        self._gate(True)
        self._chk = "CHK-RESET-DENY-ARMED" if graded_in else "CHK-RESET-DENY"
        for p in self._deny_probes_out():
            r = await self._run(p)
            assert not r.verdict.allowed, f"{label}: model admits {p}"
            st["out_probes"] += 1
            st["out_p0" if p.prot1 == 0 else "out_p1"] += 1
            st["out_decerr"] += int(r.resp == RESP_DECERR)
            st["out_seen"] += r.out_seen
        # Step 7: responses logged; PR-EXT silence of the extension-window read graded.
        self._gate(False)
        for prot1 in (0, 1):
            for cls in ("ext", "xlim"):
                p = self._p_in(cls, False, prot1)
                m = self.taps["PR-EXT"].mark()
                seq = await self._si(p, allow_timeout=True)
                ext = self.taps["PR-EXT"].count(m, "ar")
                self.logger.info(
                    "%s LOG: si_read cls=%s addr=0x%08x prot1=%d resp=%s timed_out=%s pr_ext=%d",
                    label,
                    cls,
                    p.addr,
                    prot1,
                    _RESP.get(seq.resp_code),
                    seq.timed_out,
                    ext,
                )
                if cls == "ext":
                    st["ext_seen"] += ext
        return st

    async def _leg3(self) -> None:
        # Steps 4 to 7, reset state.
        st0 = await self._deny_round("RESET", graded_in=False)
        assert st0["in_seen"] == 0 and st0["in_decerr"] == st0["in_probes"], (
            f"CTL-RESET-DENY FAIL: {st0}"
        )
        self.logger.info(
            "CTL-RESET-DENY LOG inst=in probes=%d prot1_0=%d prot1_1=%d decerr=%d target_seen=%d "
            "readback_same=%d",
            st0["in_probes"],
            st0["in_p0"],
            st0["in_p1"],
            st0["in_decerr"],
            st0["in_seen"],
            st0["rb_same"],
        )
        # Step 8: arm all 48 entries.
        self._gate(False)
        armed_ns = {"in": [0, 0], "out": [0, 0]}
        for inst in ("in", "out"):
            bank = self._bank(inst)
            ns_set = set(self.rng.sample(list(range(bank.n)), bank.n // 2))
            for i in range(bank.n):
                ns = 1 if i in ns_set else 0
                await bank.program(
                    i,
                    FilterEntry(
                        start=0,
                        end=ARMED_END,
                        enabled=False,
                        read_allowed=True,
                        write_allowed=True,
                        allow_ns=bool(ns),
                        allow_burst=True,
                        src_id=0,
                        group_id=self.rng.randrange(16),
                    ),
                )
                armed_ns[inst][ns] += 1
            self.used[inst] = set(range(bank.n))
        # Step 9: repeat steps 4 to 7 with the armed entries.
        st1 = await self._deny_round("ARMED", graded_in=True)
        # Step 10: wide-range control.
        self._chk = "CHK-RESET-DENY-ARMED"
        self._gate(False)
        wide_seen = 0
        wide_ok = 0
        ext_ctrl_seen = 0
        for prot1 in (0, 1):
            for inst in ("in", "out"):
                bank = self._bank(inst)
                k = self.rng.choice(
                    [i for i in range(bank.n) if int(bank.model.entries[i].allow_ns) == prot1]
                )
                await bank.set_enabled(k, True)
                if inst == "in":
                    for cls in ("sram", "scratch"):
                        r = await self._run(self._p_in(cls, False, prot1))
                        assert r.resp == RESP_OKAY and r.target_seen >= 1, (
                            f"CHK-RESET-DENY-ARMED FAIL: wide control in {cls} p{prot1}"
                        )
                        wide_ok += 1
                        wide_seen += r.target_seen
                    # The register classes that the armed run also counts: each
                    # read passes the filter (PR-INFLT) and its unit answers OKAY,
                    # so their armed DECERR does not come from decode.
                    for cls in REG_CLASSES:
                        p = self._p_in(cls, False, prot1)
                        m = self.taps["PR-INFLT"].mark()
                        seq = await self._si(p)
                        inflt = self.taps["PR-INFLT"].count(m, "ar")
                        assert seq.resp_code == RESP_OKAY and inflt >= 1, (
                            f"CHK-RESET-DENY-ARMED FAIL: wide control in {cls} p{prot1} "
                            f"addr=0x{p.addr:08x} resp={_RESP.get(seq.resp_code)} pr_inflt_ar={inflt}; "
                            "expected OKAY after the filter admits the read"
                        )
                        wide_ok += 1
                        wide_seen += inflt
                    p = self._p_in("ext", False, prot1)
                    m = self.taps["PR-EXT"].mark()
                    seq = await self._si(p, allow_timeout=True)
                    addrs = self.taps["PR-EXT"].addrs(m, "ar")
                    self.logger.info(
                        "WIDE-CTRL LOG: ext read addr=0x%08x prot1=%d resp=%s pr_ext=%s",
                        p.addr,
                        prot1,
                        _RESP.get(seq.resp_code),
                        [hex(a) for a in addrs if a is not None],
                    )
                    hits = sum(1 for a in addrs if a == (p.addr & M32))
                    assert hits == 1, (
                        f"CHK-RESET-DENY FAIL: PR-EXT control shows {hits} request(s) at 0x{p.addr:08x}"
                    )
                    ext_ctrl_seen += hits
                else:
                    for cls in ("smu", "ap"):
                        r = await self._run(self._p_out(cls, False, prot1))
                        assert r.resp == RESP_OKAY and r.out_seen >= 1, (
                            f"CHK-RESET-DENY-ARMED FAIL: wide control out {cls} p{prot1}"
                        )
                        wide_ok += 1
                await bank.set_enabled(k, False)
        # CHK-RESET-DENY (outbound reset state, PR-EXT silence).
        assert st0["out_decerr"] == st0["out_probes"] and st0["out_seen"] == 0, (
            f"CHK-RESET-DENY FAIL: {st0}"
        )
        assert st0["ext_seen"] == 0 and ext_ctrl_seen >= 1, (
            f"CHK-RESET-DENY FAIL: ext_seen={st0['ext_seen']} ext_ctrl_seen={ext_ctrl_seen}"
        )
        self.logger.info(
            "CHK-RESET-DENY PASS: inst=out probes=%d prot1_0=%d prot1_1=%d decerr=%d target_seen=%d "
            "readback_same=%d ext_seen=%d ext_ctrl_seen=%d",
            st0["out_probes"],
            st0["out_p0"],
            st0["out_p1"],
            st0["out_decerr"],
            st0["out_seen"],
            st0["rb_same"],
            st0["ext_seen"],
            ext_ctrl_seen,
        )
        # CHK-RESET-DENY-ARMED.
        probes = st1["in_probes"] + st1["out_probes"]
        decerr = st1["in_decerr"] + st1["out_decerr"]
        assert decerr == probes and st1["in_seen"] == 0 and st1["out_seen"] == 0, (
            f"CHK-RESET-DENY-ARMED FAIL: {st1}"
        )
        assert st1["ext_seen"] == 0, f"CHK-RESET-DENY-ARMED FAIL: PR-EXT saw {st1['ext_seen']}"
        assert min(armed_ns["in"] + armed_ns["out"]) > 0
        self.logger.info(
            "CHK-RESET-DENY-ARMED PASS: entries=48 enabled=0 range_end=2^48-1 armed_ns0=%d armed_ns1=%d "
            "probes=%d prot1_0=%d prot1_1=%d decerr=%d target_seen=%d wide_ctrl_okay=%d "
            "wide_ctrl_seen=%d wide_ctrl_in=sram,scratch,mbox,crypto,fpage,cpuctrl",
            armed_ns["in"][0] + armed_ns["out"][0],
            armed_ns["in"][1] + armed_ns["out"][1],
            probes,
            st1["in_p0"] + st1["out_p0"],
            st1["in_p1"] + st1["out_p1"],
            decerr,
            st1["in_seen"] + st1["out_seen"],
            wide_ok,
            wide_seen,
        )
        # Steps 11 and 12: the seeded control entry per instance.
        self._chk = "CHK-RESET-DENY-CONTROL"
        for inst in ("in", "out"):
            bank = self._bank(inst)
            prot1 = self.rng.getrandbits(1)
            if inst == "in":
                cls = self.rng.choice(["sram", "scratch"])
                p = self._p_in(cls, False, prot1)
            else:
                cls = self.rng.choice(["smu", "ap"])
                p = self._p_out(cls, False, prot1)
            k = self.rng.randrange(bank.n)
            await bank.program(k, self._entry(p, self._cover(p, False)))
            r = await self._run(p)
            seen = r.target_seen if inst == "in" else r.out_seen
            assert r.resp == RESP_OKAY and seen >= 1, (
                f"CHK-RESET-DENY-CONTROL FAIL: entry {k} {inst} {cls} resp={_RESP.get(r.resp)} seen={seen}"
            )
            self.logger.info(
                "CHK-RESET-DENY-CONTROL PASS: enabled_entry=%d inst=%s probe=%s prot1=%d resp=OKAY seen=%d",
                k,
                inst,
                cls,
                prot1,
                seen,
            )
            await bank.set_enabled(k, False)
        # Step 13: every entry back to reset.
        for inst in ("in", "out"):
            self.used[inst] = set(range(self._bank(inst).n))
            await self._clear(inst)

    # ------------------------------------------------------------------
    # Leg 1: match and priority
    # ------------------------------------------------------------------
    def _class_draw(self, n: int, classes: list[str]) -> list[str]:
        out = list(classes) + [self.rng.choice(classes) for _ in range(n - len(classes))]
        self.rng.shuffle(out)
        return out

    def _attr_cell(self, inst: str, state: str, attr: str, cls: str, write: bool):
        """Entries of the allow and deny configurations of one (state, attribute) sub-cell."""
        n_entries = self._bank(inst).n
        for _ in range(200):
            prot1 = self.rng.getrandbits(1)
            axlen = 1 if attr == "burst" else 0
            p = (
                self._p_in(cls, write, prot1, axlen=axlen)
                if inst == "in"
                else self._p_out(cls, write, prot1)
            )
            n = self.rng.randrange(3, 7)
            idxs = self.rng.sample(list(range(n_entries)), n)
            c = self.rng.choice(idxs)
            noise = self._noise(p, [i for i in idxs if i != c], below_ok=True)
            burst = attr == "burst"
            # An 8-byte cover holds the probe at either granule, so the burst
            # cell differs from its allow cell in allow_burst only.
            ce = self._entry(p, self._cover(p, False), burst=burst)
            allow = {**noise, c: ce}
            if state == "dis":
                deny_c = replace(ce, enabled=False)
            elif attr == "range":
                deny_c = replace(ce, **dict(zip(("start", "end"), self._apart(p))))
            elif attr == "prot1":
                deny_c = replace(ce, allow_ns=not ce.allow_ns)
            elif attr == "burst":
                deny_c = replace(ce, allow_burst=False)
            elif attr == "rd":
                deny_c = replace(ce, read_allowed=False)
            else:
                deny_c = replace(ce, write_allowed=False)
            deny = {**noise, c: deny_c}
            if (
                any(
                    e.covers(FILTER_PAGE_WORD) or e.covers(CPU_CTRL_WORD)
                    for e in list(allow.values()) + [deny_c]
                )
                and inst == "in"
            ):
                continue
            va = self._verdict_of(inst, allow, p)
            vd = self._verdict_of(inst, deny, p)
            if not (va.allowed and va.winner == c):
                continue
            if vd.winner not in (None, c):
                continue
            perm_attr = (attr == "rd" and not write) or (attr == "wr" and write)
            if (attr in ("rd", "wr") and state == "en") and not perm_attr:
                if not vd.allowed:
                    continue
            elif vd.allowed:
                continue
            return p, allow, deny, c
        raise AssertionError(f"no stack draw for {inst} {state} {attr} {cls}")

    async def _leg1(self) -> None:
        attrs = {
            "in": ["range", "prot1", "burst", "rd", "wr"],
            "out": ["range", "prot1", "rd", "wr"],
        }
        classes = {"in": ["sram", "scratch"], "out": ["smu", "ap"]}
        for inst in ("in", "out"):
            cells = [(s, a) for a in attrs[inst] for s in ("en", "dis")]
            plain = [c for c in cells if c[1] != "burst"]
            cls_of = dict(zip(plain, self._class_draw(len(plain), classes[inst])))
            for c in cells:
                if c[1] == "burst":
                    cls_of[c] = "sram"
            for state, attr in cells:
                cls = cls_of[(state, attr)]
                graded = inst == "out" or (state == "en" and attr == "prot1")
                self._chk = "CHK-FILTER-CELL" if graded else "CTL-FILTER-CELL"
                for write in (False, True):
                    p, allow, deny, c = self._attr_cell(inst, state, attr, cls, write)
                    self._gate(graded)
                    await self._load(inst, deny)
                    rd = await self._run(p)
                    await self._load(inst, allow)
                    ra = await self._run(p)
                    self._gate(False)
                    self._count(inst, rd.verdict)
                    self._count(inst, ra.verdict)
                    ctl = ra.target_seen if inst == "in" else ra.out_seen
                    for r in (rd, ra):
                        line = f"cell={state}/{attr} cls={cls} " + self._cell_line(p, r, ctl)
                        if graded:
                            self.logger.info("CHK-FILTER-CELL PASS: %s", line)
                        else:
                            self.logger.info("CTL-FILTER-CELL LOG: %s", line)
            await self._corners(inst)

    async def _pair(self, inst: str, p: Probe, first: dict, second: dict, label: str) -> None:
        """Run the probe under two entry sets (cell, then its paired control) and log both."""
        self._gate(True)
        await self._load(inst, first)
        r1 = await self._run(p)
        await self._load(inst, second)
        r2 = await self._run(p)
        self._gate(False)
        assert r1.verdict.allowed != r2.verdict.allowed, f"{label}: pair does not differ in verdict"
        self._count(inst, r1.verdict)
        self._count(inst, r2.verdict)
        ctl = r2.target_seen if inst == "in" else r2.out_seen
        self.logger.info("CHK-FILTER-CELL PASS: corner=%s %s", label, self._cell_line(p, r1, ctl))
        ctl = r1.target_seen if inst == "in" else r1.out_seen
        self.logger.info(
            "CHK-FILTER-CELL PASS: corner=%s/pair %s", label, self._cell_line(p, r2, ctl)
        )

    def _lh(self, inst: str, n_noise: int) -> tuple[int, int, list[int]]:
        n = self._bank(inst).n
        idxs = self.rng.sample(list(range(n)), 2 + n_noise)
        lo, hi = sorted(idxs[:2])
        return lo, hi, idxs[2:]

    async def _corners(self, inst: str) -> None:
        self._chk = "CHK-FILTER-CELL"
        cls = "sram" if inst == "in" else self.rng.choice(["smu", "ap"])
        for write in (False, True):
            mk = (
                (lambda w, pr, axlen=0: self._p_in(cls, w, pr, axlen=axlen))
                if inst == "in"
                else (lambda w, pr, axlen=0: self._p_out(cls, w, pr))
            )
            # a: the lowest entry fails on prot[1], a higher entry admits.
            p = mk(write, self.rng.getrandbits(1))
            lo, hi, nz = self._lh(inst, self.rng.randrange(1, 5))
            noise = self._noise(p, nz, below_ok=False)
            low = self._entry(p, self._cover(p, False), ns=1 - p.prot1)
            high = self._entry(p, self._cover(p, False))
            await self._pair(
                inst,
                p,
                {**noise, lo: low, hi: high},
                {**noise, lo: low, hi: replace(high, enabled=False)},
                "a_fallthrough_ns",
            )
            # b: the lowest match has the permission bit clear; the higher entry never counts.
            p = mk(write, self.rng.getrandbits(1))
            lo, hi, nz = self._lh(inst, self.rng.randrange(1, 5))
            noise = self._noise(p, nz, below_ok=False)
            low = self._entry(p, self._cover(p, False), rd=write, wr=not write)
            high = self._entry(p, self._cover(p, False))
            await self._pair(
                inst,
                p,
                {**noise, lo: low, hi: high},
                {**noise, lo: replace(low, read_allowed=True, write_allowed=True), hi: high},
                "b_perm_block",
            )
            # c: the lowest entry refuses a burst, a higher entry with allow_burst 1 admits it.
            if inst == "in":
                p = mk(write, self.rng.getrandbits(1), axlen=1)
                lo, hi, nz = self._lh(inst, self.rng.randrange(1, 5))
                noise = self._noise(p, nz, below_ok=False)
                low = self._entry(p, (p.faddr, p.faddr + 15), burst=False)
                high = self._entry(p, self._cover(p, True), burst=True)
                self._gate(True)
                await self._load(inst, {**noise, lo: low, hi: high})
                r1 = await self._run(p)
                p1 = replace(p, axlen=0)
                r2 = await self._run(p1)
                self._gate(False)
                assert r1.verdict.allowed and r1.verdict.winner == hi and r1.verdict.fallthrough
                assert r2.verdict.allowed and r2.verdict.winner == lo
                self._count(inst, r1.verdict)
                self._count(inst, r2.verdict)
                self.logger.info(
                    "CHK-FILTER-CELL PASS: corner=c_fallthrough_burst %s",
                    self._cell_line(p, r1, r2.target_seen),
                )
                self.logger.info(
                    "CHK-FILTER-CELL PASS: corner=c_fallthrough_burst/pair %s",
                    self._cell_line(p1, r2, r1.target_seen),
                )
            # d: the lowest covering entry is disabled, a higher entry admits.
            p = mk(write, self.rng.getrandbits(1))
            lo, hi, nz = self._lh(inst, self.rng.randrange(1, 5))
            noise = self._noise(p, nz, below_ok=False)
            low = self._entry(p, self._cover(p, False), enabled=False)
            high = self._entry(p, self._cover(p, False))
            await self._pair(
                inst,
                p,
                {**noise, lo: low, hi: high},
                {**noise, lo: low, hi: replace(high, enabled=False)},
                "d_disabled_lowest",
            )
            # g: no enabled entry covers the probe.
            p = mk(write, self.rng.getrandbits(1))
            lo, hi, nz = self._lh(inst, self.rng.randrange(1, 5))
            noise = self._noise(p, [lo, hi] + nz, below_ok=False)
            await self._pair(
                inst, p, noise, {**noise, hi: self._entry(p, self._cover(p, False))}, "g_no_match"
            )
        # e: one address, the read and the write carry different prot[1] and pick different entries.
        pr = self.rng.getrandbits(1)
        pw = 1 - pr
        rd_p = self._p_in(cls, False, pr) if inst == "in" else self._p_out(cls, False, pr)
        wr_p = replace(rd_p, write=True, prot1=pw)
        lo, hi, nz = self._lh(inst, self.rng.randrange(1, 5))
        noise = self._noise(rd_p, nz, below_ok=False)
        read_wins = bool(self.rng.getrandbits(1))
        low = self._entry(rd_p, self._cover(rd_p, False), ns=pr, rd=read_wins, wr=True)
        high = self._entry(rd_p, self._cover(rd_p, False), ns=pw, rd=True, wr=not read_wins)
        self._gate(True)
        await self._load(inst, {**noise, lo: low, hi: high})
        r1 = await self._run(rd_p)
        r2 = await self._run(wr_p)
        self._gate(False)
        assert r1.verdict.winner == lo and r2.verdict.winner == hi
        assert r1.verdict.allowed != r2.verdict.allowed
        self._count(inst, r1.verdict)
        self._count(inst, r2.verdict)
        self.stats[inst]["ar_aw_diverge"] += 1
        seen = [r.target_seen if inst == "in" else r.out_seen for r in (r1, r2)]
        self.logger.info(
            "CHK-FILTER-CELL PASS: corner=e_ar_aw_diverge %s", self._cell_line(rd_p, r1, seen[1])
        )
        self.logger.info(
            "CHK-FILTER-CELL PASS: corner=e_ar_aw_diverge %s", self._cell_line(wr_p, r2, seen[0])
        )

    # ------------------------------------------------------------------
    # Leg 2: source ID
    # ------------------------------------------------------------------
    async def _src_pair(self, inst, p_cell, p_ctl, entries, ctl_entries, cls_name, src_cfg) -> None:
        self._gate(True)
        await self._load(inst, entries)
        r1 = await self._run(p_cell)
        if ctl_entries is not entries:
            await self._load(inst, ctl_entries)
        r2 = await self._run(p_ctl)
        self._gate(False)
        assert r1.verdict.allowed != r2.verdict.allowed or cls_name in (
            "wildcard",
            "fallthrough",
            "upper_bits",
        )
        self._count(inst, r1.verdict)
        self._count(inst, r2.verdict)
        key = {"exact": "src_exact", "mismatch": "src_mismatch", "wildcard": "src_wildcard"}.get(
            cls_name
        )
        if key:
            self.stats[inst][key] += 1
        self.logger.info(
            "CHK-FILTER-SRC PASS: inst=%s dir=%s class=%s src_cfg=%d user=0x%x expect=%s got=%s control_resp=%s",
            inst,
            p_cell.dir,
            cls_name,
            src_cfg,
            p_cell.user,
            r1.verdict.resp,
            _RESP.get(r1.resp),
            _RESP.get(r2.resp),
        )

    async def _leg2(self) -> None:
        self._chk = "CHK-FILTER-SRC"
        n_in = self.inb.n
        values = [1, 2, 4, 8, 15]
        values.append(self.rng.choice([v for v in range(1, 16) if v not in values]))
        self.rng.shuffle(values)
        first_mismatch_zero = True
        for s in values:
            for write in (False, True):
                prot1 = self.rng.getrandbits(1)
                idx = self.rng.randrange(n_in)
                p_ok = self._p_in("sram", write, prot1, user=s)
                ent = {idx: self._entry(p_ok, self._cover(p_ok, False), src=s)}
                if first_mismatch_zero:
                    mu = 0
                    first_mismatch_zero = False
                else:
                    mu = self.rng.choice([u for u in range(16) if u != s])
                p_bad = replace(p_ok, user=mu, fuser=mu)
                await self._src_pair("in", p_ok, p_bad, ent, ent, "exact", s)
                await self._src_pair("in", p_bad, p_ok, ent, ent, "mismatch", s)
                # Upper AxUSER bit set, AxUSER[3:0] = s: the probe matches.
                up = (1 << self.rng.randrange(4, 12)) | s
                p_up = replace(p_ok, user=up, fuser=up & 0xF)
                await self._src_pair("in", p_up, p_bad, ent, ent, "upper_bits", s)
        # Wildcard: src_id 0 against AxUSER[3:0] 0, 15 and two drawn values.
        users = [0, 15] + self.rng.sample(list(range(1, 15)), 2)
        self.rng.shuffle(users)
        for u in users:
            for write in (False, True):
                p = self._p_in("sram", write, self.rng.getrandbits(1), user=u)
                ent = {self.rng.randrange(n_in): self._entry(p, self._cover(p, False), src=0)}
                await self._src_pair("in", p, p, ent, ent, "wildcard", 0)
        # Fall-through on a source-ID mismatch: the lowest entry mismatches, a higher admits.
        for write in (False, True):
            u = self.rng.randrange(16)
            p = self._p_in("sram", write, self.rng.getrandbits(1), user=u)
            lo, hi, _ = self._lh("in", 0)
            x = self.rng.choice([v for v in range(1, 16) if v != u])
            hsrc = self.rng.choice([0, u]) if u else 0
            low = self._entry(p, self._cover(p, False), src=x)
            high = self._entry(p, self._cover(p, False), src=hsrc)
            ent = {lo: low, hi: high}
            ctl = {lo: low, hi: replace(high, enabled=False)}
            v = self._verdict_of("in", ent, p)
            assert v.allowed and v.fallthrough and v.lowest_cover_fails == [TERM_SRC]
            await self._src_pair("in", p, p, ent, ctl, "fallthrough", x)
            self.stats["in"]["src_mismatch"] += 1
        # Outbound: OTHERS against the AP and STEE remaps.
        n_out = self.outb.n
        for cls in ("ap", "stee"):
            for write in (False, True):
                prot1 = self.rng.getrandbits(1)
                s = self.rng.randrange(1, 16)
                p = self._p_out(cls, write, prot1, user=s)
                idx = self.rng.randrange(n_out)
                bad = {idx: self._entry(p, self._cover(p, False), src=s)}
                idx2 = self.rng.randrange(n_out)
                good = {idx2: self._entry(p, self._cover(p, False), src=0)}
                await self._src_pair("out", p, p, bad, good, "mismatch", s)
                await self._src_pair("out", p, p, good, bad, "wildcard", 0)
        # Outbound exact and mismatch on the SMU aperture with the LSU AxUSER.
        for write in (False, True):
            u = self.rng.randrange(1, 16)
            v = self.rng.choice([x for x in range(1, 16) if x != u])
            p = self._p_out("smu", write, self.rng.getrandbits(1), user=u)
            idx = self.rng.randrange(n_out)
            ok = {idx: self._entry(p, self._cover(p, False), src=u)}
            bad = {idx: replace(ok[idx], src_id=v)}
            await self._src_pair("out", p, p, ok, bad, "exact", u)
            await self._src_pair("out", p, p, bad, ok, "mismatch", v)
        await self._clear("in")
        await self._clear("out")

    # ------------------------------------------------------------------
    # Leg 4: granule
    # ------------------------------------------------------------------
    async def _granule_cell(self, inst: str, gran: int, shape: str) -> None:
        self._chk = "CHK-GRANULE"
        burst = gran == G4K
        if inst == "in":
            n_g = SRAM_SIZE // gran
            g = self.rng.randrange(1, n_g - 3)
            base = SRAM_BASE + g * gran
        else:
            lo_g = (SMU_SAFE_LO // gran) + 1
            hi_g = (SMU_END // gran) - 3
            g = self.rng.randrange(lo_g, hi_g)
            base = g * gran
        if shape == "one":
            a = self.rng.randrange(1, gran // 4 - 1) * 4
            b = self.rng.randrange(a // 4 + 1, gran // 4) * 4
            start, end = base + a, base + b
        elif shape == "equal":
            a = self.rng.randrange(1, gran // 4) * 4
            start = end = base + a
        else:
            start = base + self.rng.randrange(0, gran // 4) * 4
            end = base + gran + self.rng.randrange(0, gran // 4) * 4
        prot1 = self.rng.getrandbits(1)
        mk = (
            (lambda a, w: self._p_in("sram", w, prot1, addr=a))
            if inst == "in"
            else (lambda a, w: self._p_out("smu", w, prot1, addr=a))
        )
        e = FilterEntry(
            start=start,
            end=end,
            enabled=True,
            read_allowed=True,
            write_allowed=True,
            allow_ns=bool(prot1),
            allow_burst=burst,
            src_id=0,
            group_id=self.rng.randrange(16),
        )
        wb, wt = e.widened
        points = [wb - 4, wb, wb + 4, wt - 3, wt + 1]
        self._gate(False)
        if inst == "in":
            for a in points:
                await self._stage(a, 4)
        await self._load(inst, {self.rng.randrange(self._bank(inst).n): e})
        idx = next(iter(self.used[inst]))
        _cfg, rb_s, rb_e = await self._bank(inst).read_entry(idx)
        allow = block = ctl = 0
        self._gate(True)
        for a in points:
            for w in (False, True):
                p = replace(mk(a, w), nbytes=4)
                r = await self._run(p)
                if r.verdict.allowed:
                    allow += 1
                    ctl += r.target_seen if inst == "in" else r.out_seen
                else:
                    block += 1
                self._count(inst, r.verdict)
        self._gate(False)
        if inst == "in":
            for a in points:
                got = await self._lrd(a)
                assert got == self.mem[a], (
                    f"CHK-GRANULE FAIL: word 0x{a:08x} read 0x{got:08x} != 0x{self.mem[a]:08x}"
                )
        assert allow == 6 and block == 4, f"CHK-GRANULE FAIL: allow={allow} block={block}"
        self.logger.info(
            "CHK-GRANULE PASS: inst=%s gran=%d shape=%s start=0x%x end=0x%x rb_start=0x%x rb_end=0x%x "
            "admitted=[0x%x,0x%x] probes=%d allow=%d block=%d refused_seen=0 control_seen=%d",
            inst,
            gran,
            shape,
            start,
            end,
            rb_s,
            rb_e,
            wb,
            wt,
            allow + block,
            allow,
            block,
            ctl,
        )

    async def _leg4(self) -> None:
        cells = [
            ("out", G4K, "one"),
            ("out", G4K, "equal"),
            ("out", G4K, "straddle"),
            ("in", G4K, "equal"),
            ("in", G4K, "straddle"),
            ("in", G8, "straddle"),
            ("out", G8, "straddle"),
        ]
        for inst, gran, shape in cells:
            await self._granule_cell(inst, gran, shape)
        await self._clear("in")
        await self._clear("out")

    # ------------------------------------------------------------------
    async def run_scenario(self) -> None:
        self.rng = SepSeededRng(self.random_seed())
        self.mem: dict[int, int] = {}
        self.markers: set[int] = set()
        self.used = {"in": set(), "out": set()}
        keys = (
            "cells",
            "allow",
            "block",
            "fallthrough",
            "perm_block",
            "no_match",
            "ar_aw_diverge",
            "src_exact",
            "src_mismatch",
            "src_wildcard",
        )
        self.stats = {i: {k: 0 for k in keys} for i in ("in", "out")}
        self._chk = "CTL-FILTER-ACTIVE"
        close_graded_window(self.logger)

        await self._bring_up()
        self.inb = SepFilterBank(self, "in")
        self.outb = SepFilterBank(self, "out")
        self.taps = start_taps("PR-XEXT", "PR-CSR", "PR-OUT", "PR-EXT", "PR-SRAM", "PR-INFLT")

        # Step 2: stage the SRAM pair and the cold scratch word.
        self.s0 = SRAM_BASE + 0x1000 + 16 * self.rng.randrange(0, (SRAM_SIZE - 0x2000) // 16)
        self.c0 = SCRATCH_BASE + 8 * self.rng.randrange(0, SCRATCH_BYTES // 8)
        shim_end = SHIM_BASE + SHIM_SIZE - 1
        self.ext_word = 8 * self.rng.randrange((shim_end + 0x1000) // 8, (EXT_END - 7) // 8)
        assert EXT_BASE <= self.ext_word <= EXT_END - 7
        self.smu_word = 4 * self.rng.randrange(SMU_SAFE_LO // 4 + 0x400, (SMU_END - 0x1000) // 4)
        self.ap_intra = 8 * self.rng.randrange(0, (1 << REGION_BITS) // 8)
        await self._stage(self.s0, 16)
        await self._stage(self.c0, 4)
        self.staged = dict(self.mem)
        self.logger.info(
            "FMP-CFG LOG: seed=%d s0=0x%08x c0=0x%08x ext=0x%08x smu=0x%08x ap_intra=0x%x",
            self.random_seed(),
            self.s0,
            self.c0,
            self.ext_word,
            self.smu_word,
            self.ap_intra,
        )

        # Step 3: AP and STEE output remap region 0.
        await self._remap(AP_BASE, AP_OFFSET, True)
        await self._remap(STEE_BASE, STEE_OFFSET, True)

        await self._leg3()
        await self._leg1()
        await self._leg2()
        await self._leg4()

        for inst in ("in", "out"):
            s = self.stats[inst]
            line = " ".join(f"{k}={v}" for k, v in s.items())
            zero = [k for k in s if s[k] == 0]
            assert not zero, (
                f"CTL-FILTER-RAND FAIL: seed={self.random_seed()} inst={inst} zero={zero} {line}"
            )
            self.logger.info(
                "CTL-FILTER-RAND LOG: seed=%d inst=%s %s", self.random_seed(), inst, line
            )

        close_graded_window(self.logger)
        await self._remap(AP_BASE, 0, False)
        await self._remap(STEE_BASE, 0, False)
        await stop_taps(self.taps)
