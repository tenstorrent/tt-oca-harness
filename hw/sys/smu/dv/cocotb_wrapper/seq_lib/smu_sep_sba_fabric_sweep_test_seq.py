# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP system-bus sweep of the fabric paths that leave the SEP.

S0..S3 are ``smu_dtp_sep_dm_dmi_test``: TEST_DEV leaves SEP debug open and the
debug module comes out of reset. Every later step drives the debug module's
system bus (RISC-V Debug Specification 0.13, "System Bus Access"), which takes
8-, 16-, 32- and 64-bit accesses at any address aligned to the access size and
reports a bus error in ``sbcs.sberror``.

S4: the SMU aperture. A SEP address in ``[SMU_GLOBAL_BASE_ADDR,
    SMU_GLOBAL_BASE_ADDR + SMU_REGION_SIZE)`` (``sep_cpu_ctrl`` reset values)
    goes to the outbound filter and then to the SMN (``hw/sys/sep/doc/
    fabric.adoc``), whose crossbar sends it to ``ext_out``. With outbound
    filter entry 1 open over the whole 56-bit space, every access size at
    every aligned offset of one doubleword, and a write and read at every
    address bit the aperture leaves free, are held by the bench responder and
    read back.
S5: the alias remap. A local-master alias region adds its offset to address
    bits [55:12] of a request inside ``[region_start, region_end)``
    (``alias_remap`` register description), and a remapped address at or above
    4 GiB leaves on the outbound path. One page at a SEP address the local
    crossbar sends to the peripheral fabric is remapped by each power of two
    from 2^32 to 2^55 in turn; each write and read reaches the responder at
    the remapped address. With ``cacheable`` set the write and the read leave
    with the top two AxCACHE bits high. An offset that wraps the page field
    moves the page into the SEP view of the SMC SPM, where a write through the
    remap reads back both through it and directly. The AP and STEE output
    remaps put region 0 of their windows at a programmed 512 KiB target, and a
    write and read there reach the responder at the target.
S6: responder errors. A one-shot SLVERR and DECERR from the responder on an
    outbound read and write each come back as a system-bus error, and the
    next access at that address completes.
S7: the SMC aperture. A SEP address in the SMC window goes straight to the
    SMC's resources (``hw/sys/sep/doc/fabric.adoc``: "Neighboring SMC
    resources are accessed through the SMC global aperture"). Every access
    size at every aligned offset of one SPM doubleword and a write and read at
    every SPM address bit read back through the SEP view of the SMC window.
S8: the external aperture. No adopter peripheral is attached to the SEP
    extension port, whose response the SMU port table ties to DECERR when
    unused (``hw/sys/smu/doc/port_table.adoc``, ``sep_external_resp_i``); the
    eFuse SHIM control word at its base is the one target in
    ``0x2000_0000``-``0x3FFF_FFFF`` that answers
    (``hw/sys/sep/dv/models/regs/sep_external.rdl``). No external TRNG is
    connected, and the integrator guide terminates ``ext_trng_axil`` in a
    DECERR slave then (``doc/integrator/src/smu.adoc``, "External TRNG").
    Every access size, offset and free address bit of the external aperture,
    an access back below the walk's base, and every address bit and byte
    offset of the TRNG window, returns ``sberror`` 2, "a bad address was
    accessed", for both reads and writes.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    DMI_OP_WRITE,
    pack_dmi,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    _FILTER_CTRL_H,
    _REPO_ROOT,
    _SEP_ADDR_H,
    _SEP_CPU_CTRL_H,
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    _indexed_addr,
    smu_dtp_sep_dm_sba_test_seq,
)

_ALIAS_REMAP_C = _REPO_ROOT / "hw" / "ip" / "axi_alias_remap" / "regs" / "gen" / "c"
_ALIAS_REMAP_H = _ALIAS_REMAP_C / "alias_remap.h"
_ALIAS_REMAP_ADDR_H = _ALIAS_REMAP_C / "alias_remap_addr.h"
_SMC_ADDR_H = _REPO_ROOT / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "smc_addr.h"

SMU_BASE = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SMU_GLOBAL_BASE_ADDR__ADDR_reset")
SMU_SIZE = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SMU_REGION_SIZE__SIZE_reset")
ADDR_MASK = (1 << c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__END_ADDR__END_ADDR_bw")) - 1

REMAP_REGION = _indexed_addr("SEP_TOP_LOCAL_MASTER_ALIAS_REMAP_CTRL_REGION_BASE_ADDR", 0)
REMAP_START = REMAP_REGION + c_header_u32(
    _ALIAS_REMAP_ADDR_H, "ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
)
REMAP_END = REMAP_REGION + c_header_u32(
    _ALIAS_REMAP_ADDR_H, "ALIAS_REMAP_REGION_REGION_END_BASE_ADDR"
)
REMAP_ATTRS = REMAP_REGION + c_header_u32(
    _ALIAS_REMAP_ADDR_H, "ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
)
REMAP_VALID = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__VALID_bm")
REMAP_CACHEABLE = c_header_u32(
    _ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__CACHEABLE_bm"
)
REMAP_OFFSET_BM = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bm")
REMAP_PAGE = 1 << c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bp")

SEP_EXTERNAL_BASE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_BASE_ADDR")
SEP_EXTERNAL_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_SIZE")
EFUSE_SHIM_BASE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR")
EFUSE_SHIM_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_SIZE")
AP_REGION_BASE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_AP_REGION_BASE_ADDR")
STEE_REGION_BASE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_STEE_REGION_BASE_ADDR")
AP_REMAP_0 = _indexed_addr("SEP_TOP_AP_OUTPUT_REMAP_CTRL_REGION_BASE_ADDR", 0)
STEE_REMAP_0 = _indexed_addr("SEP_TOP_STEE_OUTPUT_REMAP_CTRL_REGION_BASE_ADDR", 0)
_OUTPUT_REMAP_H = _REPO_ROOT / "hw/ip/output_remap/regs/gen/c/output_remap.h"
OUTPUT_REMAP_VALID = c_header_u32(
    _OUTPUT_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__VALID_bm"
)
# Output remap region targets: 512 KiB aligned (the SEP region granularity in
# the output_remap description), above 4 GiB and apart from both apertures.
AP_TARGET = 0xA0_0000_0000
STEE_TARGET = 0x50_0008_0000
TRNG_BASE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_TRNG_BASE_ADDR")
TRNG_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_TRNG_SIZE")

SMC_LOCAL_BASE = smc_base_config_u32("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
SMC_SPM_BASE = c_header_u32(_SMC_ADDR_H, "SMC_TOP_SPM_MEMORY_BASE_ADDR")
SMC_SPM_SIZE = c_header_u32(_SMC_ADDR_H, "SMC_TOP_SPM_MEMORY_SIZE")

# A doubleword inside the SMU aperture, clear of the firmware console word the
# bench snoops at the aperture base.
SMU_PROBE = SMU_BASE + 0x1000_0100
# A SEP page the local crossbar sends to the peripheral fabric that is neither
# in the SMC window nor in the SMU aperture, so only the alias remap moves it.
REMAP_LOCAL = 0x7000_0000
REMAP_BITS = range(32, 56)

SB_BUS_ERROR = 0b010
POLL_CYCLES = 4000


def _pattern(tag: int, nbytes: int) -> int:
    word = (0x0123_4567_89AB_CDEF ^ (tag * 0x9E37_79B9_7F4A_7C15)) & ((1 << 64) - 1)
    return word & ((1 << (8 * nbytes)) - 1)


class _CacheTap:
    """AxADDR and AxCACHE of every address handshake on the outbound interface."""

    def __init__(self, dut) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self.aw: list[tuple[int, int]] = []
        self.ar: list[tuple[int, int]] = []
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        val = getattr(self._if, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on u_axi_out_if.{name}: {val}")
        return int(val)

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            for ch, log in (("aw", self.aw), ("ar", self.ar)):
                if self._int(f"{ch}valid") and self._int(f"{ch}ready"):
                    log.append((self._int(f"{ch}addr"), self._int(f"{ch}cache")))

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class smu_sep_sba_fabric_sweep_test_seq(smu_dtp_sep_dm_sba_test_seq):
    """Sweep the SEP outbound, SMC, external and TRNG paths from the debug system bus."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.mem = test.cfg.axi_out_mem
        self._sbcs: int | None = None
        self.steps: dict[str, bool] = {
            "s4": False,
            "s5": False,
            "s6": False,
            "s7": False,
            "s8": False,
        }

    async def _post(self, jtag, addr: int, data: int) -> None:
        """One DMI write scan; the next scan collects its status."""
        await self._dmi_scan(jtag, pack_dmi(addr, data, op=DMI_OP_WRITE))

    async def _sb(self, jtag, addr: int, size: int, data: int | None = None) -> tuple[int, int]:
        """One system-bus access of 2**size bytes; returns (sberror, read data).

        A DMI write completes within a few debug-module clocks, well inside the
        next scan, so writes are posted and only the sbcs poll collects status.
        """
        sbcs = (size << 17) | (SBCS_SBREADONADDR if data is None else 0)
        if sbcs != self._sbcs:
            await self._post(jtag, SBCS_ADDR, sbcs)
            self._sbcs = sbcs
        if data is not None and size == 3:
            await self._post(jtag, SBDATA1_ADDR, (data >> 32) & 0xFFFF_FFFF)
        await self._post(jtag, SBADDRESS0_ADDR, addr)
        if data is not None:
            await self._post(jtag, SBDATA0_ADDR, data & 0xFFFF_FFFF)
        for _ in range(SBA_POLLS):
            status = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if not status & SBCS_SBBUSY:
                break
        else:
            raise AssertionError(f"system-bus access 0x{addr:08x}: sbbusy never cleared")
        if status & SBCS_SBBUSYERROR:
            raise AssertionError(f"system-bus access 0x{addr:08x}: sbbusyerror")
        if ((status >> 17) & 0x7) != size or bool(status & SBCS_SBREADONADDR) != (data is None):
            raise AssertionError(f"system-bus access 0x{addr:08x}: sbcs=0x{status:08x} lost")
        err = (status >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if err:
            await self._dmi(jtag, SBCS_ADDR, sbcs | SBCS_SBERROR_W1C, DMI_OP_WRITE)
            return err, 0
        if data is not None:
            return 0, 0
        value = await self._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ)
        if size == 3:
            value |= (await self._dmi(jtag, SBDATA1_ADDR, 0, DMI_OP_READ)) << 32
        return 0, value & ((1 << (8 << size)) - 1)

    async def _sb_ok(self, jtag, addr: int, size: int, data: int) -> None:
        err, _ = await self._sb(jtag, addr, size, data)
        if err:
            raise AssertionError(f"system-bus write 0x{addr:08x}: sberror={err}")

    async def _round_trips(self, jtag, cells, backdoor) -> tuple[dict, dict]:
        """Write then read each (local address, size, tag); compare against the pattern."""
        observed, want = {}, {}
        for addr, size, tag, where in cells:
            nbytes = 1 << size
            value = _pattern(tag, nbytes)
            werr, _ = await self._sb(jtag, addr, size, value)
            rerr, rdata = await self._sb(jtag, addr, size)
            held = self.mem.read_int(where, nbytes) if backdoor else rdata
            key = f"0x{addr:08x}/{nbytes}B"
            observed[key] = (werr, rerr, rdata, held)
            want[key] = (0, 0, value, value)
        return observed, want

    @staticmethod
    def _size_cells(base: int, tag0: int):
        """Every access size, with each of address bits [2:0] set and cleared between accesses."""
        steps = ((3, 0), (0, 1), (1, 2), (2, 4), (0, 7), (1, 6), (3, 0))
        return [(base + off, size, tag0 + i, base + off) for i, (size, off) in enumerate(steps)]

    async def _smu_aperture(self, jtag, sb) -> None:
        await self._sb_ok(jtag, OUTBOUND_START_ADDR, 3, 0)
        await self._sb_ok(jtag, OUTBOUND_END_ADDR, 3, ADDR_MASK)
        await self._sb_ok(jtag, OUTBOUND_FILTER_CONFIG, 2, OUTBOUND_CFG_OPEN)
        cells = self._size_cells(SMU_PROBE, 0)
        top = (SMU_SIZE - 1).bit_length()
        for bit in range(3, top):
            addr = SMU_PROBE | (1 << bit)
            if addr != SMU_PROBE:
                cells.append((addr, 2, 100 + bit, addr))
        observed, want = await self._round_trips(jtag, cells, backdoor=True)
        self._log(f"CHK-SEP-SBA-OUT-SWEEP {len(observed)} cells {observed}")
        sb.expect_eq(
            "CHK-SEP-SBA-OUT-SWEEP",
            observed,
            want,
            evidence="CHK-SEP-SBA-OUT-SWEEP",
        )
        self.steps["s4"] = True

    async def _remap(self, jtag, sb, tap: _CacheTap) -> None:
        await self._sb_ok(jtag, REMAP_START, 3, REMAP_LOCAL)
        await self._sb_ok(jtag, REMAP_END, 3, REMAP_LOCAL + REMAP_PAGE)
        observed, want = {}, {}
        for bit in REMAP_BITS:
            offset = (1 << bit) & REMAP_OFFSET_BM
            await self._sb_ok(jtag, REMAP_ATTRS, 3, REMAP_VALID | offset)
            addr = REMAP_LOCAL + 8 * (bit - REMAP_BITS.start)
            got, exp = await self._round_trips(
                jtag, [(addr, 3, 200 + bit, addr + offset)], backdoor=True
            )
            observed.update({f"2^{bit} {k}": v for k, v in got.items()})
            want.update({f"2^{bit} {k}": v for k, v in exp.items()})
        self._log(f"CHK-SEP-SBA-REMAP-HIGH {observed}")
        sb.expect_eq(
            "CHK-SEP-SBA-REMAP-HIGH",
            observed,
            want,
            evidence="CHK-SEP-SBA-REMAP-HIGH",
        )

        offset = (1 << REMAP_BITS.start) & REMAP_OFFSET_BM
        remapped = REMAP_LOCAL + offset
        caches = {}
        for label, attrs in (
            ("plain", REMAP_VALID | offset),
            ("cacheable", REMAP_VALID | REMAP_CACHEABLE | offset),
        ):
            await self._sb_ok(jtag, REMAP_ATTRS, 3, attrs)
            aw0, ar0 = len(tap.aw), len(tap.ar)
            await self._sb(jtag, REMAP_LOCAL, 3, _pattern(300, 8))
            await self._sb(jtag, REMAP_LOCAL, 3)
            for _ in range(POLL_CYCLES):
                if len(tap.aw) > aw0 and len(tap.ar) > ar0:
                    break
                await ClockCycles(self.dut.clk_smu_i, 1)
            caches[label] = (tap.aw[aw0:], tap.ar[ar0:])
        self._log(f"CHK-SEP-SBA-REMAP-CACHEABLE {caches}")
        cacheable_top = {
            label: (
                [a for a, _ in aw],
                [a for a, _ in ar],
                sorted({c >> 2 for _, c in aw + ar}) if label == "cacheable" else None,
            )
            for label, (aw, ar) in caches.items()
        }
        sb.expect_eq(
            "CHK-SEP-SBA-REMAP-CACHEABLE",
            cacheable_top,
            {
                "plain": ([remapped], [remapped], None),
                "cacheable": ([remapped], [remapped], [0b11]),
            },
            evidence="CHK-SEP-SBA-REMAP-CACHEABLE",
        )

        # An offset that wraps the 44-bit page field moves the page down into
        # the SEP view of the SMC SPM, where the SMC window rule takes it.
        self.smc_base = int(self.dut.smc_global_base_o.value)
        target = self._smc_view(SMC_SPM_BASE) + 4 * REMAP_PAGE
        wrap = (target - REMAP_LOCAL) & REMAP_OFFSET_BM
        await self._sb_ok(jtag, REMAP_ATTRS, 3, REMAP_VALID | REMAP_CACHEABLE | wrap)
        value = _pattern(310, 8)
        werr, _ = await self._sb(jtag, REMAP_LOCAL + 8, 3, value)
        rerr, via_remap = await self._sb(jtag, REMAP_LOCAL + 8, 3)
        await self._sb_ok(jtag, REMAP_ATTRS, 3, 0)
        derr, direct = await self._sb(jtag, target + 8, 3)
        self._log(
            f"CHK-SEP-SBA-REMAP-SMC target=0x{target:x} errs=({werr},{rerr},{derr}) "
            f"remap=0x{via_remap:x} direct=0x{direct:x}"
        )
        sb.expect_eq(
            "CHK-SEP-SBA-REMAP-SMC",
            (werr, rerr, derr, via_remap, direct),
            (0, 0, 0, value, value),
            evidence="CHK-SEP-SBA-REMAP-SMC",
        )

        observed, want = {}, {}
        for name, csr, region, target in (
            ("AP", AP_REMAP_0, AP_REGION_BASE, AP_TARGET),
            ("STEE", STEE_REMAP_0, STEE_REGION_BASE, STEE_TARGET),
        ):
            await self._sb_ok(jtag, csr, 3, OUTPUT_REMAP_VALID | target)
            got, exp = await self._round_trips(
                jtag, [(region + 8, 3, 320 + len(observed), target + 8)], backdoor=True
            )
            await self._sb_ok(jtag, csr, 3, 0)
            observed[name], want[name] = next(iter(got.values())), next(iter(exp.values()))
        self._log(f"CHK-SEP-SBA-OUTPUT-REMAP {observed}")
        sb.expect_eq(
            "CHK-SEP-SBA-OUTPUT-REMAP", observed, want, evidence="CHK-SEP-SBA-OUTPUT-REMAP"
        )
        self.steps["s5"] = True

    async def _responder_errors(self, jtag, sb) -> None:
        observed, want = {}, {}
        for resp, name in ((2, "SLVERR"), (3, "DECERR")):
            addr = SMU_PROBE + 0x40 + 8 * resp
            self.mem.inject_error(addr, resp, read=True, write=False)
            observed[f"{name} read"] = (await self._sb(jtag, addr, 3))[0]
            self.mem.inject_error(addr, resp, read=False, write=True)
            observed[f"{name} write"] = (await self._sb(jtag, addr, 3, _pattern(resp, 8)))[0]
            got, _ = await self._round_trips(jtag, [(addr, 3, 400 + resp, addr)], backdoor=True)
            observed[f"{name} after"] = next(iter(got.values()))[:2]
            want[f"{name} read"] = SB_BUS_ERROR
            want[f"{name} write"] = SB_BUS_ERROR
            want[f"{name} after"] = (0, 0)
        self.mem.clear_errors()
        self._log(f"CHK-SEP-SBA-OUT-ERROR {observed}")
        sb.expect_eq("CHK-SEP-SBA-OUT-ERROR", observed, want, evidence="CHK-SEP-SBA-OUT-ERROR")
        self.steps["s6"] = True

    def _smc_view(self, local: int) -> int:
        base = self.smc_base
        return base + (local - SMC_LOCAL_BASE)

    async def _smc_window(self, jtag, sb) -> None:
        self.smc_base = int(self.dut.smc_global_base_o.value)
        spm = self._smc_view(SMC_SPM_BASE)
        cells = self._size_cells(spm + 0x100, 500)
        for bit in range(3, SMC_SPM_SIZE.bit_length()):
            addr = spm | (1 << bit)
            if addr == spm or addr >= spm + SMC_SPM_SIZE:
                # The next 2**bit boundary flips the bit from its value in spm.
                addr = (spm + (1 << bit)) & ~((1 << bit) - 1)
            if spm < addr < spm + SMC_SPM_SIZE:
                cells.append((addr, 2, 600 + bit, addr))
        observed, want = await self._round_trips(jtag, cells, backdoor=False)
        self._log(f"CHK-SEP-SBA-SMC-WINDOW {observed}")
        sb.expect_eq(
            "CHK-SEP-SBA-SMC-WINDOW",
            observed,
            want,
            evidence="CHK-SEP-SBA-SMC-WINDOW",
        )
        self.steps["s7"] = True

    async def _external_decerr(self, jtag, sb) -> None:
        probe = SEP_EXTERNAL_BASE + 0x100
        cells = [(a, s) for a, s, _, _ in self._size_cells(probe, 0)]
        for bit in range(3, SEP_EXTERNAL_SIZE.bit_length() - 1):
            addr = probe | (1 << bit)
            if addr != probe and not EFUSE_SHIM_BASE <= addr < EFUSE_SHIM_BASE + EFUSE_SHIM_SIZE:
                cells.append((addr, 2))
        # Back below the probe, so every walked bit and the region nibble fall.
        cells.append((SEP_EXTERNAL_BASE + 0x10, 2))
        for bit in range(2, TRNG_SIZE.bit_length() - 1):
            cells.append((TRNG_BASE | (1 << bit), 2))
        cells += [(TRNG_BASE + off, size) for size, off in ((0, 1), (1, 2), (0, 3), (2, 0))]
        observed, want = {}, {}
        for addr, size in cells:
            key = f"0x{addr:08x}/{1 << size}B"
            werr, _ = await self._sb(jtag, addr, size, _pattern(addr, 1 << size))
            rerr, _ = await self._sb(jtag, addr, size)
            observed[key] = (werr, rerr)
            want[key] = (SB_BUS_ERROR, SB_BUS_ERROR)
        self._log(f"CHK-SEP-SBA-EXTERNAL-DECERR {observed}")
        sb.expect_eq(
            "CHK-SEP-SBA-EXTERNAL-DECERR",
            observed,
            want,
            evidence="CHK-SEP-SBA-EXTERNAL-DECERR",
        )
        self.steps["s8"] = True

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        tap = _CacheTap(self.dut)
        try:
            await self._smu_aperture(jtag, sb)
            await self._remap(jtag, sb, tap)
            await self._responder_errors(jtag, sb)
            await self._smc_window(jtag, sb)
            await self._external_decerr(jtag, sb)
        finally:
            tap.stop()
