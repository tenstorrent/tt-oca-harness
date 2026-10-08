# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The inbound fabric filters the global address first, then rebases the aperture to 0.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology" and "Address
Remapping"; ``hw/sys/sep/doc/assets/sep-input-fabric.svg``;
``hw/sys/sep/doc/memory_map.adoc``, "Units Unreachable from the Inbound Port"):

* The inbound filter compares the chiplet-global address before the remap.
* The global-to-local remap rebases the ``SEP_REGION_SIZE``-byte window at
  ``SEP_GLOBAL_BASE_ADDR`` to local address 0 and passes every other address
  unchanged.
* The peripheral crossbar forwards a local address below ``0x4000_0000`` to
  the local crossbar and answers DECERR at or above it.
* The inbound port has no path to the Boot ROM, Reset Control, AP region and
  STEE region, so a request to them answers DECERR even through an entry that
  admits it.

The System Interface (SI, ``m_axi``) is the only initiator through the inbound
filter. The CPU load/store splice (LSU, ``s_axi``) stages markers, programs the
aperture and the filter entries, and reads every programmed register back
before the first dependent SI request. Expected local addresses come from
``env.sep_rebase_model``; filter verdicts rest on the programmed entries only.

Evidence anchors: the SI responses and read data, the LSU read-back, PR-XEXT
(``xbar_ext_in_*``, the ``ext`` initiator of the local crossbar), PR-CSR
(``sys_csr_axil_*``, the system-CSR AXI-Lite port) and PR-INFLT (``pr_inflt_*``,
the request out of the inbound filter, global address). A refusal at the
crossbar limit shows the request leaving the filter on PR-INFLT, so the DECERR
is the crossbar's, not the filter's. The responses of the
in-window edge reads and of the read at ``0x3FFF_FFF8`` are logged only: the
specification states no response for those local addresses.

Run mode: ``no_cpu`` on ``lsu_stub_all_live`` with real PROD fuse sense of a
pinned image, so the inbound filter is active on every request. RAND-REP: the
seed draws the SRAM read and write offsets and the scratch word; the
configurations, the cells and their order are the same on every seed.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SepEfuseImage
from env.sep_fabric_common import RESP_DECERR, RESP_OKAY
from env.sep_fabric_common import RESP_NAME as _RESP
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare, lane32
from env.sep_filter_model import FilterEntry
from env.sep_lcc_golden import LC_PROD, LCC_FEAT_CTRL, feat_ctrl_expected
from env.sep_rebase_model import rebase
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank

TEST_NAME = "sep_fabric_inbound_rebase_test"


# Pinned bring-up image: PROD, and SIP_DIS / SYS_DIS with DBG_1 bit 0 clear in
# both. The image seed is a constant, so every run senses the same image.
_IMAGE_SEED = 0x2025_0225
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0E
_SYS_DIS = 0x00FF_00FF_00FF_00FE
_MAX_SENSE_CYCLES = 20_000

# SI attributes. AxPROT 0b010: data, non-secure, unprivileged. Every entry
# programs allow_ns equal to prot[1], and every probe carries AxUSER 0.
SI_PROT = 0b010
SI_NS = (SI_PROT >> 1) & 1

# Aperture configurations (base, size). Each size is a power of two and a
# 4 KiB multiple. The specification states no legal values for either register.
BASE = 0x40_0000_0000
SIZE_A = 0x2000_0000
SIZE_B = 0x1000_0000
SIZE_C = 0x8000_0000
RESTORE_BASE = SEP_CPU_CTRL.reset("SEP_GLOBAL_BASE_ADDR")
RESTORE_SIZE = SEP_CPU_CTRL.reset("SEP_REGION_SIZE")

# Local addresses, from the generated register map.
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LAST_WORD = SRAM_SIZE - 8
SCRATCH_COLD = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")
SCRATCH_BANK = sym("SEP_SCRATCH_COLD_REG_MAP_SIZE")
BOOT_ROM = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
RESET_CTRL_SW_RESET_N = sym("SEP_RESET_CTRL_SW_RESET_N_REG_ADDR")
AP_REGION = sym("AP_REGION_MEM_BASE_ADDR")
STEE_REGION = sym("STEE_REGION_MEM_BASE_ADDR")
STEE_LAST = STEE_REGION + sym("STEE_REGION_MEM_SIZE") - 1
XBAR_LIMIT = 0x4000_0000
ABOVE_LIMIT = XBAR_LIMIT + 0x100
_DCCM = sym("SEP_DCCM_MEM_BASE_ADDR")
CPU_RESOURCES = (
    ("iccm", sym("SEP_ICCM_MEM_BASE_ADDR")),
    ("dccm", _DCCM),
    # The Reserved row that follows the DCCM.
    ("reserved_c006", _DCCM + sym("SEP_DCCM_MEM_SIZE")),
    ("pic", sym("PIC_REG_MAP_BASE_ADDR")),
    # The Reserved row of the CPU Resources map after the PIC page; the
    # register map gives it no symbol.
    ("reserved_c0088", 0xC008_8000),
)
UNITS = (
    ("boot_rom", BOOT_ROM),
    ("reset_ctrl", RESET_CTRL_SW_RESET_N),
    ("ap_region", AP_REGION),
    ("stee_region", STEE_REGION),
)

ADDR_56 = (1 << 56) - 1
ADDR_64 = (1 << 64) - 1
GLOBAL_BASE_MASK = SEP_CPU_CTRL.mask("SEP_GLOBAL_BASE_ADDR")
REGION_SIZE_MASK = SEP_CPU_CTRL.mask("SEP_REGION_SIZE")


@dataclass(frozen=True)
class _Draw:
    o: int
    o2: int
    s: int
    m1: int
    m2: int
    m3: int
    w: int
    ap_word: int
    stee_word: int
    cpu_res_word: int

    @classmethod
    def from_seed(cls, seed: int) -> "_Draw":
        rng = SepSeededRng(seed)
        o = rng.randrange(0, SRAM_LAST_WORD + 8, 8)
        o2 = o
        while o2 == o:
            o2 = rng.randrange(0, SRAM_LAST_WORD + 8, 8)
        s = rng.randrange(0, SCRATCH_BANK, 8)
        # M1, M3 and W are 64-bit; M2 is the 32-bit scratch datum. The four are
        # pairwise different, and none is zero.
        vals: list[int] = []
        while len(vals) < 4:
            v = rng.getrandbits(64) if len(vals) != 1 else rng.getrandbits(32)
            low = [x & 0xFFFF_FFFF for x in vals]
            if v and v not in vals and (v & 0xFFFF_FFFF) not in low:
                vals.append(v)
        nz = []
        while len(nz) < 3:
            v = rng.getrandbits(32)
            if v:
                nz.append(v)
        return cls(o, o2, s, vals[0], vals[1], vals[2], vals[3], nz[0], nz[1], nz[2])

    def summary(self) -> str:
        return (
            f"o=0x{self.o:x} o2=0x{self.o2:x} s=0x{self.s:x} M1=0x{self.m1:x} "
            f"M2=0x{self.m2:x} M3=0x{self.m3:x} W=0x{self.w:x}"
        )


def _entry(start: int, end: int) -> FilterEntry:
    """Enabled, read and write allowed, allow_burst 0, src_id 0, allow_ns = SI prot[1]."""
    return FilterEntry(
        start=start,
        end=end,
        enabled=True,
        read_allowed=True,
        write_allowed=True,
        allow_ns=bool(SI_NS),
        allow_burst=False,
        src_id=0,
    )


@pyuvm.test()
class sep_fabric_inbound_rebase_test(sep_base_test):
    """Inbound filter-first order, global-to-local rebase and the crossbar limit."""

    required_evidence = (
        "CHK-REBASE",
        "CHK-REBASE-FILTER-FIRST",
        "CHK-REBASE-EDGE",
        "CHK-REBASE-XBAR-LIMIT",
        "CHK-REBASE-ABOVE",
        "CHK-REBASE-UNREACH",
    )

    # ------------------------------------------------------------------ access
    async def _lsu(self, op: SepAxiOp, addr: int, *, length: int, wdata: int = 0) -> int:
        size = {1: 0, 2: 1, 4: 2, 8: 3}[length]
        seq = SepAxiAccessSeq(
            f"rebase_lsu_{op.value}", op=op, addr=addr, wdata=wdata, length=length, size=size
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(
                f"LSU {op.value} 0x{addr:08x} answered {_RESP.get(seq.resp_code)}; "
                "the LSU set-up path must answer OKAY"
            )
        return seq.rdata

    async def _lsu_rd(self, addr: int, length: int = 4) -> int:
        return await self._lsu(SepAxiOp.READ, addr, length=length)

    async def _lsu_wr(self, addr: int, data: int, length: int = 4) -> None:
        await self._lsu(SepAxiOp.WRITE, addr, length=length, wdata=data)

    async def _si(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        length: int,
        wdata: int = 0,
        ungraded: bool = False,
    ) -> SepAxiAccessSeq:
        """One SI access. ``ungraded`` reads accept any response, and a missing
        response returns with ``timed_out`` set for the caller to fail on."""
        size = {1: 0, 2: 1, 4: 2, 8: 3}[length]
        kw = {}
        if op is SepAxiOp.READ and ungraded:
            kw = {"allow_ungraded_read_resp": True, "allow_timeout": True}
        if op is SepAxiOp.WRITE:
            kw = {"allow_unverified_write_resp": True}
        seq = SepAxiAccessSeq(
            f"rebase_si_{op.value}",
            op=op,
            addr=addr & ADDR_56,
            wdata=wdata,
            length=length,
            size=size,
            prot=SI_PROT,
            user=0,
            **kw,
        )
        await self.start_ext_seq(seq)
        return seq

    # ------------------------------------------------------------- registers
    async def _write_aperture(self, *, base: int | None = None, size: int | None = None) -> None:
        """Write base and/or size, then read both back on their RDL field bits."""
        g = SEP_CPU_CTRL.addr("SEP_GLOBAL_BASE_ADDR")
        z = SEP_CPU_CTRL.addr("SEP_REGION_SIZE")
        if base is not None:
            await self._lsu_wr(g, base & 0xFFFF_FFFF)
            await self._lsu_wr(g + 4, (base >> 32) & 0xFFFF_FFFF)
            self.ap_base = base
        if size is not None:
            await self._lsu_wr(z, size & 0xFFFF_FFFF)
            self.ap_size = size
        await self._check_aperture()

    async def _read_aperture(self) -> tuple[int, int]:
        g = SEP_CPU_CTRL.addr("SEP_GLOBAL_BASE_ADDR")
        z = SEP_CPU_CTRL.addr("SEP_REGION_SIZE")
        base = await self._lsu_rd(g) | (await self._lsu_rd(g + 4) << 32)
        size = await self._lsu_rd(z) | (await self._lsu_rd(z + 4) << 32)
        return base, size

    async def _check_aperture(self) -> None:
        base, size = await self._read_aperture()
        fb = field_compare(base, self.ap_base, GLOBAL_BASE_MASK)
        fs = field_compare(size, self.ap_size, REGION_SIZE_MASK)
        line = f"base {fb.fields()} size {fs.fields()}"
        if not (fb.ok and fs.ok):
            raise AssertionError(f"APERTURE-READBACK FAIL: {line}")
        self.logger.info("APERTURE-READBACK LOG: %s", line)

    # --------------------------------------------------------------- bring-up
    async def _bring_up(self) -> None:
        image = SepEfuseImage().randomize(
            _IMAGE_SEED, lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        golden = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        lo = await self._lsu_rd(LCC_FEAT_CTRL)
        hi = await self._lsu_rd(LCC_FEAT_CTRL + 4)
        feat = (lo & 0xFFFF_FFFF) | ((hi & 0xFFFF_FFFF) << 32)
        sep_dbg = feat & 1
        if feat != golden or sec_dis != 0 or sep_dbg != 0:
            msg = (
                f"CTL-REBASE-FILTER-ACTIVE FAIL: feat_ctrl=0x{feat:016x} "
                f"golden=0x{golden:016x} sec_dis={sec_dis} sep_dbg={sep_dbg}"
            )
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info(
            "CTL-REBASE-FILTER-ACTIVE LOG: feat_ctrl=0x%016x golden=0x%016x sep_dbg=%d",
            feat,
            golden,
            sep_dbg,
        )

    # ------------------------------------------------------------------ cells
    def _local(self, global_addr: int) -> int:
        return rebase(global_addr, self.ap_base, self.ap_size).local

    def _open(self) -> None:
        open_graded_window(TEST_NAME, self.logger)

    def _close(self) -> None:
        close_graded_window(self.logger)

    async def _sram_control_read(self, cfg: str) -> tuple[int, int]:
        """The live-path control of the unit cells: SI read of M1 through entry 3."""
        g = self.ap_base + SRAM_BASE + self.d.o
        seq = await self._si(SepAxiOp.READ, g, length=8)
        if seq.resp_code != RESP_OKAY or seq.rdata != self.d.m1:
            raise AssertionError(
                f"CHK-REBASE-UNREACH FAIL: cfg={cfg} control read 0x{g:x} "
                f"resp={_RESP.get(seq.resp_code)} rdata=0x{seq.rdata:x} staged=0x{self.d.m1:x}; "
                "the entry that covers the units does not admit a live unit"
            )
        return seq.resp_code, seq.rdata

    async def _unit_cells(self, cfg: str) -> None:
        """Steps 10 to 13: units unreachable from the inbound port, through an entry."""
        g = self.ap_base
        await self.infilt.program(3, _entry(g + SRAM_BASE, g + STEE_LAST))
        out0 = _entry(AP_REGION, STEE_LAST)
        out0.allow_ns = False
        out1 = _entry(AP_REGION, STEE_LAST)
        out1.allow_ns = True
        await self.outfilt.program(0, out0)
        await self.outfilt.program(1, out1)
        rom_word = lane32(await self._lsu_rd(BOOT_ROM), BOOT_ROM)
        rst_word = lane32(await self._lsu_rd(RESET_CTRL_SW_RESET_N), RESET_CTRL_SW_RESET_N)
        self.logger.info(
            "UNIT-VALUES LOG: cfg=%s boot_rom=0x%08x sw_reset_n=0x%08x", cfg, rom_word, rst_word
        )

        ctl_resp, ctl_data = await self._sram_control_read(cfg)

        wdata = {
            "boot_rom": rom_word,
            "reset_ctrl": rst_word,
            "ap_region": self.d.ap_word,
            "stee_region": self.d.stee_word,
        }
        self._open()
        for unit, local in UNITS:
            ga = g + local
            assert rebase(ga, self.ap_base, self.ap_size).local == local
            for direction in ("R", "W"):
                mark = self.xext.mark()
                if direction == "R":
                    seq = await self._si(SepAxiOp.READ, ga, length=4)
                else:
                    shift = 32 if local & 4 else 0
                    seq = await self._si(SepAxiOp.WRITE, ga, length=4, wdata=wdata[unit] << shift)
                seen = self.xext.since(mark)
                line = (
                    f"cfg={cfg} unit={unit} dir={direction} global=0x{ga:x} "
                    f"resp={_RESP.get(seq.resp_code)} control_resp={_RESP.get(ctl_resp)} "
                    f"control_rdata=0x{ctl_data:x} xext_logged={[hex(b.addr or 0) for b in seen]}"
                )
                if seq.resp_code != RESP_DECERR:
                    raise AssertionError(f"CHK-REBASE-UNREACH FAIL: {line}")
                self.logger.info("CHK-REBASE-UNREACH PASS: %s", line)
        self._close()

        await self.infilt.set_enabled(3, False)
        await self.outfilt.set_enabled(0, False)
        await self.outfilt.set_enabled(1, False)

    async def _expect_refused(
        self,
        chk: str,
        ga: int,
        *,
        length: int,
        direction: str = "R",
        wdata: int = 0,
        csr: bool = False,
        admitted: bool = False,
        extra: str = "",
    ) -> str:
        """A request that must answer DECERR with no PR-XEXT (and PR-CSR) handshake.

        ``admitted``: the request must also leave the inbound filter exactly once
        on PR-INFLT, with the issued global address, so the refusal comes from
        past the filter."""
        mx = self.xext.mark()
        mc = self.csr.mark()
        mf = self.inflt.mark()
        op = SepAxiOp.READ if direction == "R" else SepAxiOp.WRITE
        seq = await self._si(op, ga, length=length, wdata=wdata)
        nx = self.xext.count(mx)
        nc = self.csr.count(mc)
        f_addrs = self.inflt.addrs(mf, "ar" if direction == "R" else "aw")
        line = (
            f"addr=0x{ga:x} dir={direction} resp={_RESP.get(seq.resp_code)} "
            f"xbar_ext_in={nx} csr_seen={nc} inflt={[hex(a) if a is not None else 'X' for a in f_addrs]}"
            f"{extra}"
        )
        bad_filter = admitted and f_addrs != [ga & ADDR_56]
        if seq.resp_code != RESP_DECERR or nx != 0 or (csr and nc != 0) or bad_filter:
            raise AssertionError(f"{chk} FAIL: {line}")
        return line

    # --------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        self.d = _Draw.from_seed(self.random_seed())
        self.logger.info("REBASE draw: %s", self.d.summary())
        d = self.d

        # Step 1.
        await self._bring_up()
        self.infilt = SepFilterBank(self, "in")
        self.outfilt = SepFilterBank(self, "out")
        self.xext = SepFabricTap("PR-XEXT").start()
        self.csr = SepFabricTap("PR-CSR").start()
        self.inflt = SepFabricTap("PR-INFLT").start()

        # Step 2.
        base0, size0 = await self._read_aperture()
        self.logger.info(
            "APERTURE-RESET LOG: SEP_GLOBAL_BASE_ADDR=0x%x SEP_REGION_SIZE=0x%x", base0, size0
        )

        # Step 3: stage M1, M3 in SRAM and M2 in a cold scratch word.
        sram_rd = SRAM_BASE + d.o
        sram_wr = SRAM_BASE + d.o2
        scr = SCRATCH_COLD + d.s
        await self._lsu_wr(sram_rd, d.m1, 8)
        await self._lsu_wr(sram_wr, d.m3, 8)
        await self._lsu_wr(scr, d.m2, 4)
        for a, v, n, mask in (
            (sram_rd, d.m1, 8, ADDR_64),
            (sram_wr, d.m3, 8, ADDR_64),
            (scr, d.m2, 4, 0xFFFF_FFFF),
        ):
            got = await self._lsu_rd(a, n)
            got = lane32(got, a) if n == 4 else got
            if (got & mask) != v:
                raise AssertionError(f"STAGE FAIL: 0x{a:08x} read back 0x{got:x}, staged 0x{v:x}")

        # Step 4: configuration A.
        self.ap_base, self.ap_size = base0, size0
        await self._write_aperture(base=BASE, size=SIZE_A)
        G = self.ap_base

        # Step 5. Entry 1 first: the sampler of sep_inbound_filter_allow_cg
        # scores the window of the last entry programmed, and the SRAM entry
        # carries both the read and the write allow cell.
        await self.infilt.program(1, _entry(G + SCRATCH_COLD, G + SCRATCH_COLD + SCRATCH_BANK - 1))
        await self.infilt.program(0, _entry(G + SRAM_BASE, G + SRAM_BASE + SRAM_SIZE - 1))

        # Steps 6 to 9: in-window rebase, three legs.
        self._open()
        ga = G + SRAM_BASE + d.o
        n = self._local(ga)
        mk = self.xext.mark()
        seq = await self._si(SepAxiOp.READ, ga, length=8)
        seen = self.xext.addrs(mk, "ar")
        line = (
            f"leg=sram_rd base=0x{G:x} size=0x{self.ap_size:x} global=0x{ga:x} "
            f"local_seen={'|'.join(hex(a or 0) for a in seen) or 'none'} "
            f"resp={_RESP.get(seq.resp_code)} rdata_lo=0x{seq.rdata & 0xFFFF_FFFF:x} "
            f"staged=0x{d.m1:x} wdata=na lsu_direct=na"
        )
        if seq.resp_code != RESP_OKAY or seq.rdata != d.m1 or seen != [n]:
            raise AssertionError(
                f"CHK-REBASE FAIL: {line} rdata=0x{seq.rdata:x} model_local=0x{n:x}"
            )
        self.logger.info("CHK-REBASE PASS: %s", line)

        ga = G + SCRATCH_COLD + d.s
        n = self._local(ga)
        mc = self.csr.mark()
        seq = await self._si(SepAxiOp.READ, ga, length=8)
        seen = self.csr.addrs(mc, "ar")
        r_lo = seq.rdata & 0xFFFF_FFFF
        line = (
            f"leg=scratch_rd base=0x{G:x} size=0x{self.ap_size:x} global=0x{ga:x} "
            f"local_seen={'|'.join(hex(a or 0) for a in seen) or 'none'} "
            f"resp={_RESP.get(seq.resp_code)} rdata_lo=0x{r_lo:x} staged=0x{d.m2:x} "
            f"wdata=na lsu_direct=na rsvd_hi=0x{seq.rdata >> 32:x}"
        )
        if seq.resp_code != RESP_OKAY or r_lo != d.m2 or seen != [n]:
            raise AssertionError(f"CHK-REBASE FAIL: {line} model_local=0x{n:x}")
        self.logger.info("CHK-REBASE PASS: %s", line)

        ga = G + SRAM_BASE + d.o2
        n = self._local(ga)
        mk = self.xext.mark()
        seq = await self._si(SepAxiOp.WRITE, ga, length=8, wdata=d.w)
        seen = self.xext.addrs(mk, "aw")
        self._close()
        direct = await self._lsu_rd(sram_wr, 8)
        line = (
            f"leg=sram_wr base=0x{G:x} size=0x{self.ap_size:x} global=0x{ga:x} "
            f"local_seen={'|'.join(hex(a or 0) for a in seen) or 'none'} "
            f"resp={_RESP.get(seq.resp_code)} rdata_lo=na staged=0x{d.m3:x} "
            f"wdata=0x{d.w:x} lsu_direct=0x{direct:x}"
        )
        if seq.resp_code != RESP_OKAY or seen != [n] or direct != d.w:
            raise AssertionError(f"CHK-REBASE FAIL: {line} model_local=0x{n:x}")
        self.logger.info("CHK-REBASE PASS: %s", line)

        # Steps 10 to 13: unreachable units, configuration A.
        await self._unit_cells("A")

        # Steps 14 to 17: filter-first corner.
        await self.infilt.set_enabled(0, False)
        await self.infilt.set_enabled(1, False)
        await self.infilt.program(2, _entry(SRAM_BASE, SRAM_BASE + SRAM_SIZE - 1))
        self._open()
        ga = G + SRAM_BASE + d.o
        mx = self.xext.mark()
        seq_g = await self._si(SepAxiOp.READ, ga, length=8)
        xg = self.xext.count(mx)
        pa = SRAM_BASE + d.o
        assert not rebase(pa, self.ap_base, self.ap_size).in_window
        mx = self.xext.mark()
        seq_p = await self._si(SepAxiOp.READ, pa, length=8)
        xp = self.xext.count(mx, "ar")
        self._close()
        line = (
            f"global_resp={_RESP.get(seq_g.resp_code)} plain_resp={_RESP.get(seq_p.resp_code)} "
            f"plain_rdata=0x{seq_p.rdata:x} staged=0x{d.m1:x} xext_global={xg} xext_plain={xp}"
        )
        if (
            seq_g.resp_code != RESP_DECERR
            or xg != 0
            or seq_p.resp_code != RESP_OKAY
            or seq_p.rdata != d.m1
            or xp != 1
        ):
            raise AssertionError(f"CHK-REBASE-FILTER-FIRST FAIL: {line}")
        self.logger.info("CHK-REBASE-FILTER-FIRST PASS: %s", line)
        await self.infilt.set_enabled(2, False)

        # Steps 18 to 23: configuration B, window edges.
        await self._write_aperture(size=SIZE_B)
        await self.infilt.program(0, _entry(G - 0x10, G + 0xF))
        await self.infilt.program(1, _entry(G + SIZE_B - 0x10, G + SIZE_B + 0xF))
        self._open()
        seen_by: dict[str, str] = {}
        control_seen = 0
        for name, off, length in (
            ("bottom", 0, 8),
            ("top", SIZE_B - 8, 8),
            ("last_byte", SIZE_B - 1, 1),
        ):
            ga = G + off
            n = self._local(ga)
            mx = self.xext.mark()
            seq = await self._si(SepAxiOp.READ, ga, length=length, ungraded=True)
            if seq.timed_out:
                raise AssertionError(
                    f"CHK-REBASE-EDGE FAIL: {name} read 0x{ga:x} got no response in the bounded wait"
                )
            seen = self.xext.addrs(mx, "ar")
            self.logger.info(
                "REBASE-EDGE LOG: cell=%s global=0x%x model_local=0x%x resp=%s (not graded) seen=%s",
                name,
                ga,
                n,
                _RESP.get(seq.resp_code),
                [hex(a or 0) for a in seen],
            )
            if n < XBAR_LIMIT:
                if seen != [n]:
                    raise AssertionError(
                        f"CHK-REBASE-EDGE FAIL: {name} global=0x{ga:x} expected PR-XEXT 0x{n:x}, "
                        f"saw {[hex(a or 0) for a in seen]}"
                    )
                control_seen += 1
                seen_by[name] = hex(n)
            else:
                if seq.resp_code != RESP_DECERR or seen:
                    raise AssertionError(
                        f"CHK-REBASE-EDGE FAIL: {name} global=0x{ga:x} local=0x{n:x} at or above "
                        f"the limit: resp={_RESP.get(seq.resp_code)} seen={seen}"
                    )
                seen_by[name] = "none"
        above = await self._expect_refused("CHK-REBASE-EDGE", G + SIZE_B, length=1)
        below = await self._expect_refused("CHK-REBASE-EDGE", G - 1, length=1)
        self._close()
        self.logger.info(
            "CHK-REBASE-EDGE PASS: size=0x%x bottom_seen=%s top_seen=%s last_byte_seen=%s "
            "control_seen=%d above=[%s] below=[%s]",
            SIZE_B,
            seen_by["bottom"],
            seen_by["top"],
            seen_by["last_byte"],
            control_seen,
            above,
            below,
        )

        # Steps 24 to 26: configuration C.
        await self.infilt.set_enabled(0, False)
        await self.infilt.set_enabled(1, False)
        await self._write_aperture(size=SIZE_C)
        await self.infilt.program(0, _entry(G + 0x3FFF_FFF0, G + 0x4000_00FF))
        await self._unit_cells("C")

        # Steps 27 and 28: crossbar limit.
        self._open()
        ga = G + 0x3FFF_FFF8
        n = self._local(ga)
        mx = self.xext.mark()
        seq = await self._si(SepAxiOp.READ, ga, length=8, ungraded=True)
        if seq.timed_out:
            raise AssertionError(
                f"CHK-REBASE-XBAR-LIMIT FAIL: read 0x{ga:x} got no response in the bounded wait"
            )
        below_seen = self.xext.addrs(mx, "ar")
        self.logger.info(
            "REBASE-XBAR LOG: global=0x%x model_local=0x%x resp=%s (not graded) seen=%s",
            ga,
            n,
            _RESP.get(seq.resp_code),
            [hex(a or 0) for a in below_seen],
        )
        if below_seen != [n]:
            raise AssertionError(
                f"CHK-REBASE-XBAR-LIMIT FAIL: control read 0x{ga:x} expected PR-XEXT 0x{n:x}, "
                f"saw {[hex(a or 0) for a in below_seen]}"
            )
        ga = G + XBAR_LIMIT
        assert self._local(ga) == XBAR_LIMIT
        lim = await self._expect_refused(
            "CHK-REBASE-XBAR-LIMIT", ga, length=8, csr=True, admitted=True
        )
        self._close()
        self.logger.info(
            "CHK-REBASE-XBAR-LIMIT PASS: below_seen=0x%x local=0x%x [%s]",
            below_seen[0],
            XBAR_LIMIT,
            lim,
        )
        control_seen = len(below_seen)

        # Steps 29 to 31: local addresses at or above the limit, outside the window.
        await self.infilt.set_enabled(0, False)
        above_ranges = ((ABOVE_LIMIT, ABOVE_LIMIT + 0xFF), (0xC000_0000, 0xCFFF_FFFF))
        for idx, (lo, hi) in enumerate(above_ranges):
            await self.infilt.program(idx, _entry(lo, hi))
        # Both entries hold their programmed range and admit every probed
        # address (8-byte aligned ranges, so the 8-byte granule leaves START_ADDR
        # and END_ADDR unchanged). Each refusal below must also show the request
        # leaving the filter on PR-INFLT.
        for idx, (lo, hi) in enumerate(above_ranges):
            _, rb_lo, rb_hi = await self.infilt.read_entry(idx)
            if (rb_lo, rb_hi) != (lo, hi):
                raise AssertionError(
                    f"CHK-REBASE-ABOVE FAIL: entry {idx} read back START=0x{rb_lo:x} "
                    f"END=0x{rb_hi:x}, programmed 0x{lo:x}..0x{hi:x}"
                )
        for addr in [ABOVE_LIMIT] + [a for _, a in CPU_RESOURCES]:
            for write in (False, True):
                v = self.infilt.model.verdict(addr, write=write, prot1=SI_NS, user=0)
                assert v.allowed, f"model: entry does not admit 0x{addr:x} ({v.summary()})"
        control_seen = f"{control_seen} entries_admit=1"
        self._open()
        assert not rebase(ABOVE_LIMIT, self.ap_base, self.ap_size).in_window
        line = await self._expect_refused(
            "CHK-REBASE-ABOVE",
            ABOVE_LIMIT,
            length=8,
            csr=True,
            admitted=True,
            extra=f" control_seen={control_seen}",
        )
        self.logger.info("CHK-REBASE-ABOVE PASS: %s", line)
        for name, addr in CPU_RESOURCES:
            for direction in ("R", "W"):
                line = await self._expect_refused(
                    "CHK-REBASE-ABOVE",
                    addr,
                    length=4,
                    direction=direction,
                    wdata=d.cpu_res_word,
                    csr=True,
                    admitted=True,
                    extra=f" control_seen={control_seen} unit={name}",
                )
                self.logger.info("CHK-REBASE-ABOVE PASS: %s", line)
        self._close()

        # Step 32: clean-up.
        await self.infilt.set_enabled(0, False)
        await self.infilt.set_enabled(1, False)
        await self._write_aperture(base=RESTORE_BASE, size=RESTORE_SIZE)
        base1, size1 = await self._read_aperture()
        self.logger.info(
            "APERTURE-RESTORE LOG: SEP_GLOBAL_BASE_ADDR=0x%x SEP_REGION_SIZE=0x%x", base1, size1
        )
        await self.xext.stop()
        await self.csr.stop()
        await self.inflt.stop()
