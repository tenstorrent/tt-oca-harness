# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer SRAM initialisation, partial ranges, egress use, unmapped and denied targets, DMA.

Sources doc/programmer/src/smc-programming.adoc, hw/sys/smc/doc/{zeroer,fabric}.adoc.

The 128 KiB SRAM aperture is filled with a non-zero pattern over SEP_IN and cleared with the
programmer's sequence, then read back whole. Partial ranges, an egress region with INT_EN, an
unmapped local destination, a destination covered by an outbound-filter write block entry and
two DMA copies follow. Values the documents leave open are measured and printed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import (
    _REPO,
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
    DMA_CTRL_STATUS_0,
    LOCAL_BASE_RESET,
    generated_unit_at,
    generated_window,
    reg_field_encode,
)
from .smc_output_fabric_vip_utils import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    OUTPUT_FABRIC_ADDR,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    ZEROER_CTRL_CTRL_STATUS_REG_ADDR,
    ZEROER_CTRL_DEST_ADDR_REG_ADDR,
    ZEROER_CTRL_SIZE_REG_ADDR,
)

ZEROER_DEST_ADDR = ZEROER_CTRL_DEST_ADDR_REG_ADDR
ZEROER_SIZE = ZEROER_CTRL_SIZE_REG_ADDR
ZEROER_CTRL_STATUS = ZEROER_CTRL_CTRL_STATUS_REG_ADDR
_ZEROER_CTRL_H = _REPO / "hw" / "ip" / "zeroer" / "regs" / "gen" / "c" / "zeroer_ctrl.h"
ZEROER_CTRL_STATUS_START = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", int_en=1)
STATUS_BM = reg_field_encode(_ZEROER_CTRL_H, "ZEROER_CTRL", "CTRL_STATUS", status=1)

_SRAM_FIRST, _SRAM_LAST = generated_window("spm_memory")
_SRAM_BASE = LOCAL_BASE_RESET + _SRAM_FIRST
_SRAM_BYTES = 0x2_0000
_UNMAPPED_LOCAL = 0xC080_0000
assert _SRAM_BYTES <= _SRAM_LAST - _SRAM_FIRST + 1
assert generated_unit_at(_UNMAPPED_LOCAL - LOCAL_BASE_RESET) is None
_WORD = 8
_CHUNK = 2048
_GUARD = 8

_EGRESS_DEST = OUTPUT_FABRIC_ADDR + 0x2000
_EGRESS_BYTES = 0x800
_DENIED_DEST = OUTPUT_FABRIC_ADDR + 0x4000
_DENIED_BYTES = 0x400
_DENIED_END = _DENIED_DEST + 0xFFF
_DMA_SRC = OUTPUT_FABRIC_ADDR + 0x3000
_DMA_BYTES = 64
_DMA_DST = _SRAM_BASE + 0x8000

# (name, DEST_ADDR, SIZE): an unaligned start, one beat and one 256-beat burst.
_PARTIAL_LEGS = (
    ("UNALIGNED", _SRAM_BASE + 0x1003, 0x25),
    ("ONE_BEAT", _SRAM_BASE + 0x2000, 8),
    ("ONE_BURST", _SRAM_BASE + 0x4000, 0x800),
)

_FILTER_CTRL_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_FILTER_DATA_BUS_WIDTH_8B = 3
# Reads pass, writes (single beat or burst) are blocked.
WRITE_BLOCK_CONFIG = reg_field_encode(
    _FILTER_CTRL_H,
    "FILTER_CTRL",
    "FILTER_CONFIG",
    read_allowed=1,
    entry_enabled=1,
    data_bus_width=_FILTER_DATA_BUS_WIDTH_8B,
    allow_burst=1,
)

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
_CHK_ORDER = (
    ("CHK-ZEROER-SRAM-FULL", "S2"),
    ("CHK-ZEROER-SRAM-PARTIAL", "S3"),
    ("CHK-ZEROER-EGRESS-REGION", "S4"),
    ("CHK-ZEROER-UNMAPPED-OR-DENIED", "S5"),
    ("CHK-ACCEL-LOCAL-TARGETS", "S6"),
)

# Liveness ceilings, not checked quantities: expiry FAILS.
_FIRST_AW_CYCLES = 4000
_STATUS_POLLS = 40000
_DMA_DONE_POLLS = 200
_DMA_BOUND_CYCLES = 40000
_QUIET_CYCLES = 200
_DMA_QUIET_RUN = 64


def _fill_pattern(seed: int, nbytes: int) -> bytes:
    """Non-zero bytes whose value depends on the offset and the seed."""
    return bytes(((i * seed) % 251) + 1 for i in range(nbytes))


class _Wire:
    """Passive clk_smc_i sampler of the zeroer and DMA master ports and their interrupts."""

    _NAMES = (
        "tb_zeroer_awvalid",
        "tb_zeroer_awready",
        "tb_zeroer_awaddr",
        "tb_zeroer_bvalid",
        "tb_zeroer_intp",
        "tb_dma_busy",
        "tb_dma_mst_awvalid",
        "tb_dma_mst_awready",
        "tb_dma_mst_awaddr",
        "tb_dma_mst_bvalid",
        "tb_dma_trans_complete",
    )

    def __init__(self) -> None:
        self.zaw: list[int] = []
        self.zb_cycles = 0
        self.intp_rises = 0
        self.intp_last = 0
        self.busy_seen = False
        self.busy_low_run = 0
        self.daw: list[int] = []
        self.db_cycles = 0
        self.complete_cycles = 0
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        sigs = [getattr(dut, name) for name in self._NAMES]
        prev_intp = 0
        while True:
            await RisingEdge(dut.clk_smc_i)
            for sig in sigs:
                assert sig.value.is_resolvable, f"{sig._name} is X/Z: {sig.value}"
            zv, zr, za, zb, intp, busy, dv, dr, da, db, comp = (int(s.value) for s in sigs)
            if zv and zr:
                self.zaw.append(za)
            self.zb_cycles += zb
            if intp and not prev_intp:
                self.intp_rises += 1
            prev_intp = intp
            self.intp_last = intp
            if dv and dr:
                self.daw.append(da)
            self.db_cycles += db
            self.complete_cycles += comp
            if busy:
                self.busy_seen = True
                self.busy_low_run = 0
            else:
                self.busy_low_run += 1


class smc_zeroer_sram_init_test_seq(output_fabric_pass_all_cfg_seq):
    """SRAM clear, partial ranges, egress region, unmapped and denied targets, DMA copies."""

    def __init__(self, name: str = "smc_zeroer_sram_init_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._printed: list[tuple[str, str]] = []
        self._responder = None

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id} printed while the last completed step is "
            f"{self._stamps[-1][0] if self._stamps else None}, expected {step}"
        )
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self._printed.append((chk_id, step))

    async def _sep_write(self, addr: int, data: bytes) -> None:
        assert addr % _WORD == 0 and len(data) % _WORD == 0, "SEP_IN burst must be word aligned"
        done = 0
        while done < len(data):
            n = min(len(data) - done, _CHUNK - ((addr + done) % _CHUNK))
            item = SmcSysAxiItem(f"sram_wr_0x{addr + done:x}")
            item.op = SmcSysAxiOp.WRITE
            item.addr = addr + done
            item.length = _WORD
            item.beats = n // _WORD
            item.wdata = int.from_bytes(data[done : done + n], "little")
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
            done += n

    async def _sep_read(self, addr: int, nbytes: int) -> bytes:
        assert addr % _WORD == 0 and nbytes % _WORD == 0, "SEP_IN burst must be word aligned"
        out = bytearray()
        while len(out) < nbytes:
            cur = addr + len(out)
            n = min(nbytes - len(out), _CHUNK - (cur % _CHUNK))
            item = SmcSysAxiItem(f"sram_rd_0x{cur:x}")
            item.op = SmcSysAxiOp.READ
            item.addr = cur
            item.length = _WORD
            item.beats = n // _WORD
            await self.start_item(item)
            await self.finish_item(item)
            self.accesses += 1
            out += item.rdata.to_bytes(n, "little")
        return bytes(out)

    def _egress_poison(self, label: str, addr: int, nbytes: int, byte: int) -> None:
        data = bytes([byte]) * nbytes
        self._responder.write(addr, data)
        got = self._responder.read(addr, nbytes)
        assert got == data, f"{label}: egress 0x{addr:08x} did not take its poison"

    def _egress_nonzero(self, addr: int, nbytes: int) -> int:
        return sum(1 for b in self._responder.read(addr, nbytes) if b)

    async def _status(self) -> int:
        word = await self.csr_read("ZEROER_CTRL_STATUS_POLL", ZEROER_CTRL_STATUS, length=8)
        return word

    async def _zeroer_job(self, label: str, dest: int, size: int, int_en: bool) -> dict:
        """Program DEST_ADDR and SIZE, start, poll STATUS to 0 and observe the ports."""
        wire = _Wire()
        wire.start()
        try:
            await self.csr_write(f"{label}_DEST_ADDR", ZEROER_DEST_ADDR, dest, length=8)
            await self.csr_write(f"{label}_SIZE", ZEROER_SIZE, size, length=8)
            await self.csr_read(f"{label}_DEST_RB", ZEROER_DEST_ADDR, expected=dest, length=8)
            await self.csr_read(f"{label}_SIZE_RB", ZEROER_SIZE, expected=size, length=8)
            await self.csr_write(
                f"{label}_START",
                ZEROER_CTRL_STATUS,
                ZEROER_CTRL_STATUS_START if int_en else 0,
                length=8,
            )
            for _ in range(_FIRST_AW_CYCLES):
                if wire.zaw:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, 1)
            else:
                raise AssertionError(
                    f"{label}: no zeroer AW handshake within {_FIRST_AW_CYCLES} clk_smc_i cycles "
                    f"of the start write (DEST 0x{dest:x}, SIZE 0x{size:x})"
                )
            polls = 0
            word = STATUS_BM
            for _ in range(_STATUS_POLLS):
                word = await self._status()
                polls += 1
                if not word & STATUS_BM:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, 1)
            else:
                raise AssertionError(
                    f"{label}: STATUS still 1 after {_STATUS_POLLS} polls; AW handshakes "
                    f"{len(wire.zaw)}, B cycles {wire.zb_cycles}, interrupt rises "
                    f"{wire.intp_rises}, last CTRL_STATUS 0x{word:x}"
                )
            second = await self._status()
            if int_en:
                await ClockCycles(cocotb.top.clk_smc_i, _QUIET_CYCLES)
        finally:
            wire.stop()
        return {
            "label": label,
            "polls": polls,
            "status": 1 if word & STATUS_BM else 0,
            "status2": 1 if second & STATUS_BM else 0,
            "other_bits": second & ~STATUS_BM,
            "aw": list(wire.zaw),
            "b_cycles": wire.zb_cycles,
            "intp": wire.intp_rises,
            "intp_last": wire.intp_last,
        }

    @staticmethod
    def _check_done(obs: dict) -> None:
        assert obs["status"] == 0 and obs["status2"] == 0, (
            f"{obs['label']}: STATUS reads {obs['status']} then {obs['status2']} after the clear"
        )

    async def _setup(self) -> None:
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self.csr_write("ZEROER_SIZE_IDLE", ZEROER_SIZE, 0, length=8)
        idle = await self._status()
        assert not idle & STATUS_BM, f"STATUS reads 1 with the zeroer idle (0x{idle:x})"
        pattern = _fill_pattern(7, _SRAM_BYTES)
        await self._sep_write(_SRAM_BASE, pattern)
        for off in (0, 0x1_0000, _SRAM_BYTES - _CHUNK):
            got = await self._sep_read(_SRAM_BASE + off, _CHUNK)
            assert got == pattern[off : off + _CHUNK], (
                f"SRAM sample at +0x{off:x} reads back differently from the pattern written; "
                f"a later zero compare would prove nothing"
            )
        self._egress_poison("EGRESS", _EGRESS_DEST - _GUARD, _EGRESS_BYTES + 2 * _GUARD, 0xA5)
        self._egress_poison("DENIED", _DENIED_DEST - _GUARD, _DENIED_BYTES + 2 * _GUARD, 0x5A)

    async def _step_full(self) -> None:
        obs = await self._zeroer_job("FULL", _SRAM_BASE, _SRAM_BYTES, False)
        self._check_done(obs)
        data = await self._sep_read(_SRAM_BASE, _SRAM_BYTES)
        nonzero_words = sum(1 for i in range(0, _SRAM_BYTES, _WORD) if any(data[i : i + _WORD]))
        assert nonzero_words == 0, f"{nonzero_words} SRAM word(s) non-zero after the clear"
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-ZEROER-SRAM-FULL",
            "DEST 0x%08x SIZE 0x%x, CTRL_STATUS written 0: STATUS 0 after %d polls (then %d), "
            "SEP_IN read-back of %d bytes: %d non-zero words of %d",
            _SRAM_BASE,
            _SRAM_BYTES,
            obs["polls"],
            obs["status2"],
            _SRAM_BYTES,
            nonzero_words,
            _SRAM_BYTES // _WORD,
        )

    async def _step_partial(self) -> None:
        pattern = _fill_pattern(3, _SRAM_BYTES)
        await self._sep_write(_SRAM_BASE, pattern)
        parts = []
        for name, dest, size in _PARTIAL_LEGS:
            obs = await self._zeroer_job(f"PARTIAL_{name}", dest, size, False)
            self._check_done(obs)
            lo = (dest & ~(_WORD - 1)) - _GUARD
            hi = ((dest + size + _WORD - 1) & ~(_WORD - 1)) + _GUARD
            got = await self._sep_read(lo, hi - lo)
            want = bytearray(pattern[lo - _SRAM_BASE : hi - _SRAM_BASE])
            want[dest - lo : dest - lo + size] = bytes(size)
            assert got == bytes(want), self._diff(name, lo, got, bytes(want), dest, size)
            parts.append(
                f"{name}[0x{dest:08x}+0x{size:x}]: {size} bytes zero, "
                f"{hi - lo - size} bytes either side keep the pattern, STATUS polls {obs['polls']}"
            )
        self._stamp("S3")
        self._chk("S3", "CHK-ZEROER-SRAM-PARTIAL", "%s", "; ".join(parts))

    @staticmethod
    def _diff(name: str, lo: int, got: bytes, want: bytes, dest: int, size: int) -> str:
        bad = [i for i, (a, b) in enumerate(zip(got, want, strict=True)) if a != b]
        first = bad[0]
        return (
            f"{name}: {len(bad)} byte(s) differ in the window from 0x{lo:08x}; first at "
            f"0x{lo + first:08x} reads 0x{got[first]:02x}, expected 0x{want[first]:02x}; range "
            f"0x{dest:08x}..0x{dest + size - 1:08x}"
        )

    def _check_egress_unchanged(self, label: str, dest: int, nbytes: int, byte: int) -> None:
        got = self._responder.read(dest - _GUARD, nbytes + 2 * _GUARD)
        want = bytes([byte]) * (nbytes + 2 * _GUARD)
        bad = [i for i, (a, b) in enumerate(zip(got, want, strict=True)) if a != b]
        assert not bad, (
            f"{label}: {len(bad)} byte(s) of the egress window at 0x{dest - _GUARD:08x} changed, "
            f"first at +0x{bad[0]:x} reads 0x{got[bad[0]]:02x}, last at +0x{bad[-1]:x}; "
            f"window length 0x{len(got):x}"
        )

    async def _step_egress(self) -> None:
        obs = await self._zeroer_job("EGRESS", _EGRESS_DEST, _EGRESS_BYTES, True)
        self._check_done(obs)
        nonzero = self._egress_nonzero(_EGRESS_DEST, _EGRESS_BYTES)
        below = self._responder.read(_EGRESS_DEST - _GUARD, _GUARD)
        above = self._responder.read(_EGRESS_DEST + _EGRESS_BYTES, _GUARD)
        assert nonzero == 0, f"{nonzero} byte(s) of the egress region still non-zero"
        assert below == above == bytes([0xA5]) * _GUARD, (
            f"guard words changed: below {below.hex()} above {above.hex()}"
        )
        assert obs["intp"] == 1, (
            f"{obs['intp']} tb_zeroer_intp pulse(s) after the INT_EN start write, expected 1"
        )
        assert obs["intp_last"] == 0, "tb_zeroer_intp still high after the quiet window"
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-ZEROER-EGRESS-REGION",
            "DEST 0x%08x SIZE 0x%x INT_EN start: STATUS 0 after %d polls, %d non-zero bytes, "
            "guard words 0x%s / 0x%s unchanged, %d tb_zeroer_intp pulse(s) with %d quiet cycles "
            "and the line low at the end, %d AW handshakes",
            _EGRESS_DEST,
            _EGRESS_BYTES,
            obs["polls"],
            nonzero,
            below.hex(),
            above.hex(),
            obs["intp"],
            _QUIET_CYCLES,
            len(obs["aw"]),
        )

    async def _step_unmapped_denied(self) -> None:
        unm = await self._zeroer_job("UNMAPPED", _UNMAPPED_LOCAL, 0x100, True)
        self._check_done(unm)
        await self.csr_write("OUTBOUND0_START_DENY", OUTBOUND0_START, _DENIED_DEST, length=8)
        await self.csr_write("OUTBOUND0_END_DENY", OUTBOUND0_END, _DENIED_END, length=8)
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_DENY", OUTBOUND0_FILTER_CONFIG, WRITE_BLOCK_CONFIG, length=8
        )
        writes_before, _ = output_responder_counts()
        den = await self._zeroer_job("DENIED", _DENIED_DEST, _DENIED_BYTES, True)
        writes_after, _ = output_responder_counts()
        self._check_done(den)
        self._check_egress_unchanged("DENIED", _DENIED_DEST, _DENIED_BYTES, 0x5A)
        await self.program_outbound_pass_all()
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-ZEROER-UNMAPPED-OR-DENIED",
            "unmapped DEST 0x%08x: STATUS 0 after %d polls, CTRL_STATUS bits outside STATUS 0x%x, "
            "%d interrupt pulse(s), %d AW handshakes, %d B cycles; denied DEST 0x%08x SIZE 0x%x "
            "under a write-block entry: STATUS 0 after %d polls, CTRL_STATUS bits outside STATUS "
            "0x%x, %d interrupt pulse(s), %d AW handshakes, %d B cycles, egress region and guards "
            "unchanged, SYS_OUT write count delta %d; the response codes are not on a tb probe",
            _UNMAPPED_LOCAL,
            unm["polls"],
            unm["other_bits"],
            unm["intp"],
            len(unm["aw"]),
            unm["b_cycles"],
            _DENIED_DEST,
            _DENIED_BYTES,
            den["polls"],
            den["other_bits"],
            den["intp"],
            len(den["aw"]),
            den["b_cycles"],
            writes_after - writes_before,
        )

    async def _program_dma(self, tag: str, src: int, dst: int, length: int) -> None:
        await self.csr_write(f"DMA_CONFIG{tag}", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        for name, reg, val in (
            ("DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, dst & 0xFFFF_FFFF),
            ("DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, dst >> 32),
            ("SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, src & 0xFFFF_FFFF),
            ("SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, src >> 32),
            ("LENGTH_LO", DMA_CTRL_LENGTH_LO, length),
            ("LENGTH_HI", DMA_CTRL_LENGTH_HI, 0),
            ("DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, 0),
            ("DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0),
            ("SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, 0),
            ("SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0),
            ("NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, 1),
            ("NUM_REPETITIONS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"DMA_{name}{tag}", reg, val)

    async def _dma_launch(
        self, tag: str, src: int, dst: int, length: int
    ) -> tuple[_Wire, int, int]:
        """Program a descriptor; the NEXT_ID read launches it. The sampler stays running."""
        await self._program_dma(tag, src, dst, length)
        baseline = await self.csr_read(f"DMA_DONE_0_BASELINE{tag}", DMA_CTRL_DONE_0)
        wire = _Wire()
        wire.start()
        start_id = await self.csr_read(f"DMA_NEXT_ID_0_START{tag}", DMA_CTRL_NEXT_ID_0)
        return wire, baseline, start_id

    async def _dma_quiesce(self, label: str, wire: _Wire) -> int:
        """Bounded wait for the DMA to start and then stay idle for a run of cycles."""
        for waited in range(_DMA_BOUND_CYCLES):
            started = wire.busy_seen or bool(wire.daw)
            if started and wire.busy_low_run >= _DMA_QUIET_RUN:
                return waited
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: tb_dma_busy not quiescent within {_DMA_BOUND_CYCLES} clk_smc_i cycles: "
            f"busy_seen {wire.busy_seen}, idle run {wire.busy_low_run}, AW handshakes "
            f"{[hex(a) for a in wire.daw]}, B cycles {wire.db_cycles}"
        )

    async def _step_dma(self) -> None:
        src_data = bytes((0x11 + 5 * i) & 0xFF for i in range(_DMA_BYTES))
        self._responder.write(_DMA_SRC, src_data)
        assert self._responder.read(_DMA_SRC, _DMA_BYTES) == src_data, "DMA source not preloaded"
        await self._sep_write(_DMA_DST, bytes([0xEE]) * _DMA_BYTES)
        pre = await self._sep_read(_DMA_DST, _DMA_BYTES)
        assert pre == bytes([0xEE]) * _DMA_BYTES, "DMA destination poison did not stick"

        wire, baseline, start_id = await self._dma_launch("_SRAM", _DMA_SRC, _DMA_DST, _DMA_BYTES)
        try:
            done = baseline
            for _ in range(_DMA_DONE_POLLS):
                done = await self.csr_read("DMA_DONE_0_POLL", DMA_CTRL_DONE_0)
                if done > baseline:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, 20)
            else:
                raise AssertionError(
                    f"DMA copy to SRAM did not retire: DONE {done}, baseline {baseline}"
                )
            ok_wait = await self._dma_quiesce("DMA_SRAM", wire)
        finally:
            wire.stop()
        got = await self._sep_read(_DMA_DST, _DMA_BYTES)
        assert got == src_data, f"SRAM holds {got.hex()}, source {src_data.hex()}"
        ok_aw = [hex(a) for a in wire.daw]
        ok_b = wire.db_cycles

        unm_base = await self.csr_read("DMA_DONE_0_BASELINE_PRE_UNMAPPED", DMA_CTRL_DONE_0)
        wire, baseline, unm_id = await self._dma_launch(
            "_UNMAPPED", _DMA_SRC, _UNMAPPED_LOCAL, _DMA_BYTES
        )
        try:
            unm_wait = await self._dma_quiesce("DMA_UNMAPPED", wire)
        finally:
            wire.stop()
        unm_done = await self.csr_read("DMA_DONE_0_AFTER_UNMAPPED", DMA_CTRL_DONE_0)
        unm_status = await self.csr_read("DMA_STATUS_0_AFTER_UNMAPPED", DMA_CTRL_STATUS_0)
        self._stamp("S6")
        self._chk(
            "S6",
            "CHK-ACCEL-LOCAL-TARGETS",
            "DMA 0x%08x -> SRAM 0x%08x, %d bytes: id %d retired (DONE %d), SRAM equals the "
            "source, AW %s, %d B cycles, idle %d cycles after %d; DMA -> unmapped 0x%08x: id %d, "
            "DONE %d (before %d, %d), STATUS_0 0x%x, AW %s, %d B cycles, tb_dma_busy idle for %d "
            "cycles after %d cycles, %d completion cycles; the response codes are not on a tb "
            "probe",
            _DMA_SRC,
            _DMA_DST,
            _DMA_BYTES,
            start_id,
            done,
            ok_aw,
            ok_b,
            _DMA_QUIET_RUN,
            ok_wait,
            _UNMAPPED_LOCAL,
            unm_id,
            unm_done,
            unm_base,
            baseline,
            unm_status,
            [hex(a) for a in wire.daw],
            wire.db_cycles,
            _DMA_QUIET_RUN,
            unm_wait,
            wire.complete_cycles,
        )

    async def body(self) -> None:
        dut = cocotb.top
        for name in _Wire._NAMES:
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        self._responder = self.cfg.sys_out_mem
        assert self._responder is not None, "SYS_OUT responder not bound"
        mon = self.env.output_axi_monitor
        mon.allow_slverr = True
        mon.allow_decerr = True

        await self._setup()
        self._stamp("S1")
        await self._step_full()
        await self._step_partial()
        await self._step_egress()
        await self._step_unmapped_denied()
        await self._step_dma()

        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
        self._nonvac()

    def _nonvac(self) -> None:
        steps = [s for s, _t in self._stamps]
        assert steps == list(_STEPS), f"step stamps {steps} not in the expected order"
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"step stamps {times} are not strictly increasing"
        )
        assert self._printed == list(_CHK_ORDER), (
            f"checker lines {self._printed} not in step order {list(_CHK_ORDER)}"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6 with checker lines printed in step "
            "order after their own compares; checker lines %s; stamps %s ps",
            ",".join(c for c, _s in self._printed),
            ",".join(str(t) for t in times),
        )
