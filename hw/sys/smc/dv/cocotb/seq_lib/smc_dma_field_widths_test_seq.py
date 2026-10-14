# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA effective field widths: discarded upper register bits and the 56-bit address width.

Specs hw/sys/smc/doc/dma.adoc, vendor idma overlay dma_ctrl.rdl.

Sources and destinations sit in the SYS_OUT responder memory and are preloaded and read back
through its backdoor. The egress addresses come from the SYS_OUT address handshakes sampled
at clk_smc_i rises; only handshakes inside a copy's own address window are attributed to it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_dma_sanity_test_seq import (
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    PASS_ALL_CONFIG,
)

ADDR_MASK = (1 << 56) - 1
TOP_BYTE_HI = 0xFF00_0000
WINDOW = 0x0200_0000
GUARD = 16
POISON = 0xA5
POLL_LIMIT = 1000
POLL_CYCLES = 20
REGION_MARGIN = 0x1000
ROW_BYTES = 16
ROW_STRIDE = 0x40

_EGRESS = (
    "tb_output_axi_arvalid",
    "tb_output_axi_arready",
    "tb_output_axi_araddr",
    "tb_output_axi_awvalid",
    "tb_output_axi_awready",
    "tb_output_axi_awaddr",
    "tb_output_axi_bvalid",
    "tb_output_axi_bready",
    "tb_output_axi_bresp",
    "tb_output_axi_rvalid",
    "tb_output_axi_rready",
    "tb_output_axi_rresp",
)


def _pattern(addr: int) -> int:
    return 1 + (((addr * 13) ^ (addr >> 7) ^ 0x3C) % 0x90)


class _Desc:
    """One copy: the effective (56-bit) values and the raw values written to the registers."""

    def __init__(self, name: str, src: int, dst: int, length: int, reps: int = 1) -> None:
        self.name = name
        self.src = src
        self.dst = dst
        self.length = length
        self.reps = reps
        self.src_stride = ROW_STRIDE if reps > 1 else 0
        self.dst_stride = ROW_STRIDE if reps > 1 else 0
        self.src_hi_extra = 0
        self.dst_hi_extra = 0
        self.length_hi = 0
        self.src_stride_hi = 0
        self.dst_stride_hi = 0
        self.reps_hi = 0
        self.id = -1
        self.start_index = 0

    @property
    def extent(self) -> int:
        rows = self.reps + 1 if self.reps > 1 else 1
        return (rows - 1) * self.dst_stride + self.length

    def region(self, base: int, stride: int) -> tuple[int, int]:
        rows = self.reps + 1 if self.reps > 1 else 1
        return base - REGION_MARGIN, base + (rows - 1) * stride + self.length + REGION_MARGIN

    def row_addrs(self, base: int, stride: int) -> list[int]:
        return [base + n * stride for n in range(self.reps)]


class _EgressLog:
    """Records every SYS_OUT address handshake and response of the run."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.ars: list[tuple[int, int]] = []
        self.aws: list[tuple[int, int]] = []
        self.bresps: list[tuple[int, int]] = []
        self.rresps: list[tuple[int, int]] = []

    @staticmethod
    def _int(sig, name: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{name} is X/Z ({value})"
        return int(value)

    async def run(self) -> None:
        dut = self.dut
        sigs = {n[len("tb_output_axi_") :]: getattr(dut, n) for n in _EGRESS}
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            now = int(get_sim_time("ps"))
            val = {
                k: self._int(sigs[k], f"tb_output_axi_{k}")
                for k in (
                    "arvalid",
                    "arready",
                    "awvalid",
                    "awready",
                    "bvalid",
                    "bready",
                    "rvalid",
                    "rready",
                )
            }
            if val["arvalid"] and val["arready"]:
                self.ars.append((now, self._int(sigs["araddr"], "tb_output_axi_araddr")))
            if val["awvalid"] and val["awready"]:
                self.aws.append((now, self._int(sigs["awaddr"], "tb_output_axi_awaddr")))
            if val["bvalid"] and val["bready"]:
                self.bresps.append((now, self._int(sigs["bresp"], "tb_output_axi_bresp")))
            if val["rvalid"] and val["rready"]:
                self.rresps.append((now, self._int(sigs["rresp"], "tb_output_axi_rresp")))


class smc_dma_field_widths_test_seq(SmcCsrSeq):
    """Copies whose HI registers carry bits above the effective field widths."""

    def __init__(self, name: str = "smc_dma_field_widths_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.chk_ids: list[str] = []
        self.log_e: _EgressLog | None = None
        self.next_expected_id = 0

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        self.chk_ids.append(chk_id)
        cocotb.log.info("%s: %s", chk_id, text)

    @property
    def _responder(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    async def _pass_all(self) -> None:
        for name, addr, value in (
            ("IN_START", INBOUND0_START, 0),
            ("IN_END", INBOUND0_END, ADDR_MASK),
            ("IN_CFG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("OUT_START", OUTBOUND0_START, 0),
            ("OUT_END", OUTBOUND0_END, ADDR_MASK),
            ("OUT_CFG", OUTBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
        ):
            await self.csr_write(f"PASS_{name}", addr, value, length=8)

    def _seed(self, d: _Desc) -> None:
        rows = d.reps + 1 if d.reps > 1 else 1
        for n in range(rows):
            base = d.src + n * d.src_stride
            self._responder.write(base, bytes(_pattern(base + i) for i in range(d.length)))
        self._responder.write(d.dst - GUARD, bytes([POISON]) * (d.extent + 2 * GUARD))

    def _expected_dst(self, d: _Desc) -> bytearray:
        image = bytearray([POISON]) * (d.extent + 2 * GUARD)
        for n in range(d.reps):
            row = bytes(_pattern(d.src + n * d.src_stride + i) for i in range(d.length))
            off = GUARD + n * d.dst_stride
            image[off : off + d.length] = row
        return image

    def _compare(self, d: _Desc) -> int:
        got = bytes(self._responder.read(d.dst - GUARD, d.extent + 2 * GUARD))
        want = bytes(self._expected_dst(d))
        assert got == want, (
            f"{d.name}: destination image at 0x{d.dst - GUARD:x} differs from the expected "
            f"copy of {d.reps} row(s) x {d.length} bytes; first difference at byte "
            f"{next(i for i, (a, b) in enumerate(zip(got, want)) if a != b)}"
        )
        return d.reps * d.length

    async def _program(self, d: _Desc) -> None:
        for reg, value in (
            (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            (DMA_CTRL_DST_ADDRESS_LO, d.dst & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, (d.dst >> 32) | d.dst_hi_extra),
            (DMA_CTRL_SRC_ADDRESS_LO, d.src & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, (d.src >> 32) | d.src_hi_extra),
            (DMA_CTRL_LENGTH_LO, d.length),
            (DMA_CTRL_LENGTH_HI, d.length_hi),
            (DMA_CTRL_DST_STRIDE_LO, d.dst_stride),
            (DMA_CTRL_DST_STRIDE_HI, d.dst_stride_hi),
            (DMA_CTRL_SRC_STRIDE_LO, d.src_stride),
            (DMA_CTRL_SRC_STRIDE_HI, d.src_stride_hi),
            (DMA_CTRL_NUM_REPETITIONS_LO, d.reps),
            (DMA_CTRL_NUM_REPETITIONS_HI, d.reps_hi),
        ):
            await self.csr_write(f"{d.name}_0x{reg & 0xFFF:03x}", reg, value)

    async def _launch(self, d: _Desc) -> None:
        d.start_index = len(self.log_e.ars)
        d.id = await self.csr_read(f"{d.name}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        assert d.id == self.next_expected_id + 1, (
            f"{d.name}: NEXT_ID returned {d.id} after DONE {self.next_expected_id}"
        )

    async def _await_done(self, d: _Desc) -> None:
        done = -1
        for _ in range(POLL_LIMIT):
            done = await self.csr_read(f"{d.name}_DONE", DMA_CTRL_DONE_0)
            if done == d.id:
                self.next_expected_id = d.id
                return
            assert done < d.id, f"{d.name}: DONE_0 reads {done}, past its id {d.id}"
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{d.name}: DONE_0 reached {done}, not id {d.id} within {POLL_LIMIT} polls"
        )

    async def _copy(self, d: _Desc) -> dict:
        """Run one copy; return the egress addresses attributed to it."""
        self._seed(d)
        await self._program(d)
        ar0, aw0 = len(self.log_e.ars), len(self.log_e.aws)
        b0, r0 = len(self.log_e.bresps), len(self.log_e.rresps)
        await self._launch(d)
        await self._await_done(d)
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        log = self.log_e
        s_lo, s_hi = d.region(d.src, d.src_stride)
        d_lo, d_hi = d.region(d.dst, d.dst_stride)
        ars = [a for _, a in log.ars[ar0:] if s_lo <= a < s_hi]
        aws = [a for _, a in log.aws[aw0:] if d_lo <= a < d_hi]
        bad_b = [r for _, r in log.bresps[b0:] if r != 0]
        bad_r = [r for _, r in log.rresps[r0:] if r != 0]
        assert not bad_b and not bad_r, f"{d.name}: non-OKAY responses bresp={bad_b} rresp={bad_r}"
        return {"ars": ars, "aws": aws, "b": len(log.bresps) - b0, "r": len(log.rresps) - r0}

    def _check_rows(self, d: _Desc, seen: dict) -> str:
        want_ar = d.row_addrs(d.src, d.src_stride)
        want_aw = d.row_addrs(d.dst, d.dst_stride)
        ars, aws = seen["ars"], seen["aws"]
        assert ars[: len(want_ar)] == want_ar and len(ars) >= len(want_ar), (
            f"{d.name}: AR addresses {[hex(a) for a in ars]}, expected rows "
            f"{[hex(a) for a in want_ar]}"
        )
        assert aws[: len(want_aw)] == want_aw and len(aws) >= len(want_aw), (
            f"{d.name}: AW addresses {[hex(a) for a in aws]}, expected rows "
            f"{[hex(a) for a in want_aw]}"
        )
        return f"AR {','.join(f'0x{a:x}' for a in ars)} AW {','.join(f'0x{a:x}' for a in aws)}"

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        for name in _EGRESS:
            assert hasattr(dut, name), f"tb_top has no {name}"
        assert len(dut.tb_output_axi_araddr) == 56, "SYS_OUT araddr is not 56 bits wide"
        await self._pass_all()
        self.log_e = _EgressLog(dut)
        cocotb.start_soon(self.log_e.run())
        self.next_expected_id = await self.csr_read("DONE_BASE", DMA_CTRL_DONE_0)
        await ClockCycles(dut.clk_smc_i, 2)
        self._mark("S1")

    async def _s2(self) -> str:
        d = _Desc("TOPBYTE", WINDOW + 0x1000, WINDOW + 0x2000, 64)
        d.src_hi_extra = TOP_BYTE_HI
        d.dst_hi_extra = TOP_BYTE_HI
        seen = await self._copy(d)
        copied = self._compare(d)
        assert seen["ars"] and seen["aws"], f"{d.name}: no AR or AW inside the copy window"
        assert seen["ars"][0] == d.src, f"first AR 0x{seen['ars'][0]:x}, expected 0x{d.src:x}"
        assert seen["aws"][0] == d.dst, f"first AW 0x{seen['aws'][0]:x}, expected 0x{d.dst:x}"
        assert all(a <= ADDR_MASK for a in seen["ars"] + seen["aws"])
        self._mark("S2")
        return (
            f"with SRC_ADDRESS_HI=0x{(d.src >> 32) | TOP_BYTE_HI:08x} and DST_ADDRESS_HI="
            f"0x{(d.dst >> 32) | TOP_BYTE_HI:08x} the first AR is 0x{seen['ars'][0]:x} and the "
            f"first AW is 0x{seen['aws'][0]:x} (programmed with bits 63:56 cleared: "
            f"0x{d.src:x} and 0x{d.dst:x}); {copied} bytes landed at the destination equal to "
            f"the source with {seen['b']} B and {seen['r']} R responses all OKAY on a "
            f"{len(cocotb.top.tb_output_axi_araddr)}-bit address bus"
        )

    async def _s3(self) -> str:
        d = _Desc("LENTOP", WINDOW + 0x3000, WINDOW + 0x4000, 64)
        d.length_hi = TOP_BYTE_HI
        seen = await self._copy(d)
        copied = self._compare(d)
        assert copied == d.length, f"{copied} bytes copied, LENGTH_LO {d.length}"
        self._mark("S3")
        return (
            f"with LENGTH_HI=0x{d.length_hi:08x} and LENGTH_LO={d.length} {copied} bytes were "
            f"copied and the {GUARD} bytes after the span kept 0x{POISON:02x} "
            f"({len(seen['ars'])} AR, {len(seen['aws'])} AW in the window)"
        )

    async def _s4(self) -> str:
        d = _Desc("STRIDETOP", WINDOW + 0x5000, WINDOW + 0x6000, ROW_BYTES, 4)
        d.src_stride_hi = TOP_BYTE_HI
        d.dst_stride_hi = TOP_BYTE_HI
        seen = await self._copy(d)
        copied = self._compare(d)
        rows = self._check_rows(d, seen)
        self._mark("S4")
        return (
            f"with SRC_STRIDE_HI=DST_STRIDE_HI=0x{TOP_BYTE_HI:08x} and stride LO "
            f"0x{ROW_STRIDE:x} each of {d.reps} rows of {ROW_BYTES} bytes landed at base plus "
            f"n*0x{ROW_STRIDE:x} ({copied} bytes, gaps kept 0x{POISON:02x}); {rows}"
        )

    async def _s5(self) -> str:
        d = _Desc("REPSHI", WINDOW + 0x7000, WINDOW + 0x8000, ROW_BYTES, 3)
        d.reps_hi = 1
        seen = await self._copy(d)
        copied = self._compare(d)
        assert len(seen["aws"]) == d.reps, f"{len(seen['aws'])} AW bursts for {d.reps} rows"
        self._mark("S5")
        return (
            f"with NUM_REPETITIONS_HI=0x{d.reps_hi:08x} and NUM_REPETITIONS_LO={d.reps} "
            f"{copied // ROW_BYTES} rows were copied ({copied} bytes) and row {d.reps + 1} kept "
            f"0x{POISON:02x} ({len(seen['ars'])} AR, {len(seen['aws'])} AW in the window)"
        )

    async def _s6(self) -> str:
        d = _Desc("HIGHADDR", 0x00A5_5A01_0000_1000, 0x0012_C3D4_0000_2000, 64)
        seen = await self._copy(d)
        copied = self._compare(d)
        assert seen["ars"] and seen["aws"], f"{d.name}: no AR or AW at the programmed address"
        assert seen["ars"][0] == d.src, f"first AR 0x{seen['ars'][0]:x}, expected 0x{d.src:x}"
        assert seen["aws"][0] == d.dst, f"first AW 0x{seen['aws'][0]:x}, expected 0x{d.dst:x}"
        self._mark("S6")
        return (
            f"with SRC_ADDRESS_HI=0x{d.src >> 32:08x} and DST_ADDRESS_HI=0x{d.dst >> 32:08x} the "
            f"first AR is 0x{seen['ars'][0]:x} and the first AW is 0x{seen['aws'][0]:x}, equal to "
            f"the programmed 0x{d.src:x} and 0x{d.dst:x}; {copied} destination bytes equal the "
            f"source"
        )

    async def body(self) -> None:
        await self._s1()
        text = await self._s2()
        self._chk("S2", "CHK-DMA-FW-ADDR-TOP-BYTE", text)
        text = await self._s3()
        self._chk("S3", "CHK-DMA-FW-LENGTH-TOP-BYTE", text)
        text = await self._s4()
        self._chk("S4", "CHK-DMA-FW-STRIDE-TOP-BYTE", text)
        text = await self._s5()
        self._chk("S5", "CHK-DMA-FW-REPS-HI", text)
        text = await self._s6()
        self._chk("S6", "CHK-DMA-FW-ADDR-55-32", text)
        self._nonvac()

    def _nonvac(self) -> None:
        order = ["S1", "S2", "S3", "S4", "S5", "S6"]
        assert [s for s, _ in self.steps] == order, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        want = [
            ("S2", "CHK-DMA-FW-ADDR-TOP-BYTE"),
            ("S3", "CHK-DMA-FW-LENGTH-TOP-BYTE"),
            ("S4", "CHK-DMA-FW-STRIDE-TOP-BYTE"),
            ("S5", "CHK-DMA-FW-REPS-HI"),
            ("S6", "CHK-DMA-FW-ADDR-55-32"),
        ]
        assert self.chk_steps == want, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, step stamps strictly "
            "increasing, each line after its own compare; checker lines %s; stamps %s",
            ",".join(self.chk_ids),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )
