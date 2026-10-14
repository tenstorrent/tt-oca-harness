# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA and zeroer request attributes sampled at the SYS_OUT boundary.

Sources: smc dma.adoc, zeroer.adoc, fabric.adoc (alias remapping, source ID by traffic path).

The SYS_OUT request is read from the packed ``output_axi_req`` of tb_top. Its field offsets
follow the AXI_TYPEDEF_REQ_T member order and are cross-checked on every sample against the
exported ``tb_output_axi_{ar,aw}addr`` probes.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import DMA_CONFIG_ENABLED_ND, smc_addr
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq
from .smc_zeroer_dma_timeout_test_seq import (
    STATUS_BM,
    ZEROER_CTRL_STATUS,
    ZEROER_CTRL_STATUS_START,
    ZEROER_DEST_ADDR,
    ZEROER_SIZE,
)

_JOB_BYTES = 256
_DMA_SRC = 0x0200_1000
_DMA_DST = 0x0200_2000
_ZEROER_BASE = 0x0200_3000
_POISON = 0xA5A5_5A5A_C3C3_3C3C

# Packed AXI4 request layout, LSB first: r_ready, ar_valid, ar, b_ready, w_valid, w,
# aw_valid, aw (axi/typedef.svh).
_ID_W, _ADDR_W, _USER_W, _DATA_W = 8, 56, 12, 64
_AR_BELOW_ADDR = 8 + 3 + 2 + 1 + 4 + 3 + 4 + 4 + _USER_W
_AR_W = _ID_W + _ADDR_W + _AR_BELOW_ADDR
_W_W = _DATA_W + _DATA_W // 8 + 1 + _USER_W
_AW_BELOW_ADDR = _AR_BELOW_ADDR + 6
_AW_W = _ID_W + _ADDR_W + _AW_BELOW_ADDR
_AR_OFF = 2
_B_READY_OFF = _AR_OFF + _AR_W
_W_OFF = _B_READY_OFF + 2
_AW_VALID_OFF = _W_OFF + _W_W
_AW_OFF = _AW_VALID_OFF + 1
_REQ_W = _AW_OFF + _AW_W
# (offset within the channel, width) for the members the checks cover.
_AR_FIELDS = {"user": (0, 12), "prot": (20, 3), "cache": (23, 4), "burst": (28, 2)}
_AW_FIELDS = {"user": (0, 12), "prot": (26, 3), "cache": (29, 4), "burst": (34, 2)}
_AR_ADDR_OFF = _AR_BELOW_ADDR
_AW_ADDR_OFF = _AW_BELOW_ADDR

_BURST_INCR = 1
_DMA_DONE_POLLS = 2000
_STATUS_ASSERT_CYCLES = 4000
_STATUS_CLEAR_CYCLES = 40000
_STEP_IDS = ("S1", "S2", "S3", "S4")
_CHK_ORDER = (
    ("CHK-ACCEL-EGRESS-INCR", "S2"),
    ("CHK-ACCEL-EGRESS-CACHE", "S3"),
    ("CHK-ACCEL-EGRESS-PROT-USER", "S4"),
)


def _dma(reg: str) -> int:
    return smc_addr(f"SMC_TOP_DMA_CTRL_{reg}_BASE_ADDR")


def _bits(word: int, off: int, width: int) -> int:
    return (word >> off) & ((1 << width) - 1)


class _EgressSampler:
    """Keeps every SYS_OUT AR and AW handshake whose address lies in a named buffer."""

    def __init__(self, dut, windows: dict[str, tuple[int, int]]) -> None:
        self.dut = dut
        self.windows = windows
        self.stop = False
        self.kept: dict[str, list[dict[str, int]]] = {name: [] for name in windows}

    def _classify(self, addr: int, channel: str) -> str | None:
        for name, (lo, hi) in self.windows.items():
            if name.endswith(channel) and lo <= addr < hi:
                return name
        return None

    def _sample(self, word: int, channel: str, valid_off: int, ch_off: int) -> None:
        dut = self.dut
        valid = _bits(word, valid_off, 1)
        ready = getattr(dut, f"tb_output_axi_{channel}ready").value
        assert ready.is_resolvable, f"tb_output_axi_{channel}ready is X/Z"
        if not (valid and int(ready)):
            return
        fields = _AR_FIELDS if channel == "ar" else _AW_FIELDS
        addr_off = _AR_ADDR_OFF if channel == "ar" else _AW_ADDR_OFF
        addr = _bits(word, ch_off + addr_off, _ADDR_W)
        probe = getattr(dut, f"tb_output_axi_{channel}addr").value
        assert probe.is_resolvable and int(probe) == addr, (
            f"{channel} address slice 0x{addr:x} differs from tb_output_axi_{channel}addr "
            f"{probe}; the packed request layout is wrong"
        )
        kind = self._classify(addr, channel)
        if kind is None:
            return
        self.kept[kind].append(
            {name: _bits(word, ch_off + off, width) for name, (off, width) in fields.items()}
            | {"addr": addr}
        )

    async def run(self) -> None:
        req = self.dut.output_axi_req
        while not self.stop:
            await RisingEdge(self.dut.clk_smc_i)
            await ReadOnly()
            value = req.value
            assert value.is_resolvable, f"output_axi_req is X/Z at {get_sim_time('ps')} ps"
            word = int(value)
            self._sample(word, "ar", 1, _AR_OFF)
            self._sample(word, "aw", _AW_VALID_OFF, _AW_OFF)


class smc_accel_egress_attrs_test_seq(output_fabric_pass_all_cfg_seq):
    """Run a DMA copy and a zeroer job and check the attributes of their SYS_OUT requests."""

    def __init__(self, name: str = "smc_accel_egress_attrs_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []

    def _step(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk: str, step: str, text: str, *args) -> None:
        cocotb.log.info("%s: " + text, chk, *args)
        self.chk_steps.append((chk, step))

    async def _poll_status(self, want: int, cycles: int, what: str) -> None:
        for _ in range(cycles):
            word = await self.csr_read("ZEROER_CTRL_STATUS_POLL", ZEROER_CTRL_STATUS, length=8)
            if (1 if word & STATUS_BM else 0) == want:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(f"CTRL_STATUS.STATUS never {what} within {cycles} clk_smc_i polls")

    async def _run_dma(self, responder) -> None:
        await self.csr_write("DMA_CONFIG", _dma("CONFIG"), DMA_CONFIG_ENABLED_ND)
        for reg, value in (
            ("SRC_ADDRESS", _DMA_SRC),
            ("DST_ADDRESS", _DMA_DST),
            ("LENGTH", _JOB_BYTES),
            ("SRC_STRIDE", 0),
            ("DST_STRIDE", 0),
            ("NUM_REPETITIONS", 1),
        ):
            await self.csr_write(f"DMA_{reg}_LO", _dma(f"{reg}_LO"), value & 0xFFFF_FFFF)
            await self.csr_write(f"DMA_{reg}_HI", _dma(f"{reg}_HI"), value >> 32)
        baseline = await self.csr_read("DMA_DONE_0_BASELINE", _dma("DONE_0"))
        start_id = await self.csr_read("DMA_NEXT_ID_0_START", _dma("NEXT_ID_0"))
        for _ in range(_DMA_DONE_POLLS):
            done = await self.csr_read("DMA_DONE_0_POLL", _dma("DONE_0"))
            if done > baseline:
                break
            await ClockCycles(cocotb.top.clk_smc_i, 16)
        else:
            raise AssertionError(
                f"DMA_DONE_0 stayed 0x{baseline:x} for {_DMA_DONE_POLLS} polls; the "
                f"{_JOB_BYTES}-byte copy launched as id {start_id} did not complete"
            )
        assert done == start_id, f"DMA completed id {done}, launched id {start_id}"
        for off in range(0, _JOB_BYTES, 8):
            got = responder.read_int(_DMA_DST + off, 8)
            assert got == _POISON + off, (
                f"DMA destination +0x{off:x} reads 0x{got:016x}, expected 0x{_POISON + off:016x}"
            )

    async def _run_zeroer(self, responder) -> None:
        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, _ZEROER_BASE, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, _JOB_BYTES, length=8)
        await self.csr_write(
            "ZEROER_CTRL_STATUS_START", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )
        await self._poll_status(1, _STATUS_ASSERT_CYCLES, "left its idle level")
        await self._poll_status(0, _STATUS_CLEAR_CYCLES, "returned to its idle level")
        for off in range(0, _JOB_BYTES, 8):
            got = responder.read_int(_ZEROER_BASE + off, 8)
            assert got == 0, f"zeroer region +0x{off:x} reads 0x{got:016x} after the job"
        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)

    @staticmethod
    def _require_samples(kept: dict[str, list[dict[str, int]]], names: tuple[str, ...]) -> None:
        for name in names:
            assert kept[name], f"no {name} request was sampled in its buffer"

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "output_axi_req"), "tb_top does not expose output_axi_req"
        width = len(dut.output_axi_req)
        assert width == _REQ_W, f"output_axi_req is {width} bits wide, layout needs {_REQ_W}"
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"

        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        for off in range(0, _JOB_BYTES, 8):
            responder.write_int(_DMA_SRC + off, _POISON + off, 8)
            responder.write_int(_DMA_DST + off, 0, 8)
            responder.write_int(_ZEROER_BASE + off, _POISON ^ off, 8)
        windows = {
            "dma_ar": (_DMA_SRC, _DMA_SRC + _JOB_BYTES),
            "dma_aw": (_DMA_DST, _DMA_DST + _JOB_BYTES),
            "zeroer_aw": (_ZEROER_BASE, _ZEROER_BASE + _JOB_BYTES),
        }
        sampler = _EgressSampler(dut, windows)
        watcher = cocotb.start_soon(sampler.run())
        self._step("S1")

        try:
            await self._run_dma(responder)
            await self._run_zeroer(responder)
        finally:
            sampler.stop = True
        await RisingEdge(dut.clk_smc_i)
        await watcher
        kept = sampler.kept
        self._require_samples(kept, tuple(windows))
        for name, reqs in kept.items():
            for req in reqs:
                assert req["burst"] == _BURST_INCR, (
                    f"{name} request to 0x{req['addr']:x} has burst type {req['burst']}, "
                    f"expected INCR ({_BURST_INCR})"
                )
        self._step("S2")
        self._chk(
            "CHK-ACCEL-EGRESS-INCR",
            "S2",
            "every kept request has burst type INCR (1): DMA AR %d, DMA AW %d, zeroer AW %d",
            len(kept["dma_ar"]),
            len(kept["dma_aw"]),
            len(kept["zeroer_aw"]),
        )

        await ClockCycles(dut.clk_smc_i, 1)
        encodings = {}
        for name in ("dma_ar", "dma_aw"):
            for req in kept[name]:
                assert req["cache"] & 0x2, (
                    f"{name} request to 0x{req['addr']:x} has cache 0x{req['cache']:x} with "
                    f"bit 1 (modifiable) clear"
                )
            encodings[name] = sorted({req["cache"] for req in kept[name]})
        self._step("S3")
        self._chk(
            "CHK-ACCEL-EGRESS-CACHE",
            "S3",
            "bit 1 set on all %d DMA AR and %d DMA AW; ARCACHE values %s, AWCACHE values %s "
            "(alias remap at reset; encoding pending owner value, alias remap values not driven)",
            len(kept["dma_ar"]),
            len(kept["dma_aw"]),
            [f"0x{v:x}" for v in encodings["dma_ar"]],
            [f"0x{v:x}" for v in encodings["dma_aw"]],
        )

        await ClockCycles(dut.clk_smc_i, 1)
        summary = []
        for name in windows:
            for member in ("prot", "user"):
                values = {req[member] for req in kept[name]}
                assert len(values) == 1, (
                    f"{name} {member} is not constant over the run: "
                    f"{sorted(f'0x{v:x}' for v in values)}"
                )
                summary.append(f"{name}.{member}=0x{values.pop():x}")
        self._step("S4")
        self._chk(
            "CHK-ACCEL-EGRESS-PROT-USER",
            "S4",
            "each member is constant over the run (values pending owner value): %s",
            " ".join(summary),
        )
        self._fence()

    def _fence(self) -> None:
        ids = [s for s, _ in self.steps]
        assert ids == list(_STEP_IDS), f"step order {ids}, expected {list(_STEP_IDS)}"
        stamps = [t for _, t in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing: {stamps}"
        assert self.chk_steps == list(_CHK_ORDER), (
            f"checker lines {self.chk_steps}, expected {list(_CHK_ORDER)}"
        )
        stamp_of = dict(self.steps)
        assert all(stamp_of[step] >= 0 for _, step in self.chk_steps)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            "S1<S2<S3<S4 step stamps strictly increasing, each checker line after its compare",
            [c for c, _ in self.chk_steps],
            stamps,
        )
