# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer jobs: aligned beat structure, restart, 56-bit destination and a random mix.

Contract SMC_POWER_DMA_ZEROER_022, anchor smc_zeroer_job_breadth_test.
Scenarios ZEROER-JOB.S1, .S4, .S6 and .S7.
Sources hw/sys/smc/doc/zeroer.adoc, hw/ip/zeroer/regs/zeroer_ctrl.rdl.

Every region is pre-filled with a non-zero pattern and flanked by an 8-byte guard on each
side. An aligned 64-byte job is observed beat by beat on the zeroer master port; later jobs
are judged on the responder memory: the bytes in [DEST, DEST+SIZE) read zero and the guards
keep their pattern. The destination with bits [55:32] set is read back from the egress AW
address and the memory at that address. Its DEST_ADDR and SIZE read-back values are printed,
not asserted.
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import _REPO, reg_field_encode
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    output_fabric_pass_all_cfg_seq,
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

_BEAT_BYTES = 8
_GUARD = 8
_SLOT = 0x2000
_ALIGNED_DEST = OUTPUT_FABRIC_ADDR + 0x4000
_ALIGNED_BYTES = 64
_SECOND_DEST = OUTPUT_FABRIC_ADDR + 0x6000 + 0x40
_SECOND_BYTES = 0x58
_HIGH_DEST = 0x00A5_5A12_0000_1000
_HIGH_BYTES = 0x40
_RANDOM_BASE = OUTPUT_FABRIC_ADDR + 0x10000
_RANDOM_JOBS = 20
_BUCKETS = {"small": (1, 64), "mid": (65, 0x7FF), "multi": (0x801, 0x1800)}

# Bounds are liveness ceilings, not checked quantities: expiry FAILS.
_FIRST_AW_CYCLES = 4000
_STATUS_CLEAR_CYCLES = 40000


class _Wire:
    """Passive clk_smc_i sampler of the zeroer master port AW and W handshakes."""

    def __init__(self) -> None:
        self.aw: list[tuple[int, int]] = []
        self.w: list[tuple[int, int, int]] = []
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_smc_i)
            ctl = (
                dut.tb_zeroer_awvalid,
                dut.tb_zeroer_awready,
                dut.tb_zeroer_wvalid,
                dut.tb_zeroer_wready,
            )
            for sig in ctl:
                assert sig.value.is_resolvable, f"{sig._name} is X/Z: {sig.value}"
            awv, awr, wv, wr = (int(sig.value) for sig in ctl)
            if awv and awr:
                addr, length = dut.tb_zeroer_awaddr.value, dut.tb_zeroer_awlen.value
                assert addr.is_resolvable and length.is_resolvable, (
                    f"AW payload is X/Z at a handshake: addr={addr} len={length}"
                )
                self.aw.append((int(addr), int(length)))
            if wv and wr:
                data = dut.tb_zeroer_wdata.value
                strb = dut.tb_zeroer_wstrb.value
                last = dut.tb_zeroer_wlast.value
                assert data.is_resolvable and strb.is_resolvable and last.is_resolvable, (
                    f"W payload is X/Z at a handshake: data={data} strb={strb} last={last}"
                )
                self.w.append((int(data), int(strb), int(last)))


class smc_zeroer_job_breadth_test_seq(output_fabric_pass_all_cfg_seq):
    """Aligned beats, restart, high destination and a random mix of zeroer jobs."""

    def __init__(self, name: str = "smc_zeroer_job_breadth_test_seq") -> None:
        super().__init__(name)
        self.runs = 0
        self._stamps: list[tuple[str, int]] = []
        self._printed: list[tuple[str, str]] = []
        self._last_dest: int | None = None
        self._last_size: int | None = None

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{chk_id} printed while the last completed step is "
            f"{self._stamps[-1][0] if self._stamps else None}, expected {step}"
        )
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self._printed.append((chk_id, step))

    async def _status(self) -> int:
        word = await self.csr_read("ZEROER_CTRL_STATUS_POLL", ZEROER_CTRL_STATUS, length=8)
        return 1 if word & STATUS_BM else 0

    def _poison(self, dest: int, size: int, pattern: int) -> None:
        """Fill [dest-GUARD, dest+size+GUARD) with `pattern`."""
        span = size + 2 * _GUARD
        fill = bytes([pattern]) * span
        self._responder.write(dest - _GUARD, fill)
        assert self._responder.read(dest - _GUARD, span) == fill, (
            f"region 0x{dest:x}+{size} did not take its pattern 0x{pattern:02x}"
        )

    def _compare(self, label: str, dest: int, size: int, pattern: int) -> None:
        """Assert [dest, dest+size) reads zero and both guards keep `pattern`."""
        inside = self._responder.read(dest, size)
        left = sum(1 for b in inside if b)
        assert left == 0, f"{label}: {left} of {size} bytes at 0x{dest:x} are still non-zero"
        for side, addr in (("below", dest - _GUARD), ("above", dest + size)):
            guard = self._responder.read(addr, _GUARD)
            assert guard == bytes([pattern]) * _GUARD, (
                f"{label}: guard {side} the region at 0x{addr:x} reads {guard.hex()}, "
                f"expected pattern 0x{pattern:02x}"
            )

    def _intact(self, label: str, dest: int, size: int, pattern: int) -> None:
        got = self._responder.read(dest - _GUARD, size + 2 * _GUARD)
        assert got == bytes([pattern]) * len(got), f"{label}: region 0x{dest:x}+{size} was changed"

    async def _program(self, dest: int, size: int) -> tuple[int, int]:
        await self.csr_write("ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, dest, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, size, length=8)
        rb_dest = await self.csr_read("ZEROER_DEST_ADDR_RB", ZEROER_DEST_ADDR, length=8)
        rb_size = await self.csr_read("ZEROER_SIZE_RB", ZEROER_SIZE, length=8)
        self._last_dest, self._last_size = dest, size
        return rb_dest, rb_size

    async def _trigger(self, label: str) -> _Wire:
        """Start the job already programmed and wait for STATUS idle; return its wire record."""
        wire = _Wire()
        wire.start()
        try:
            await self.csr_write(
                f"ZEROER_CTRL_STATUS_START_{label}",
                ZEROER_CTRL_STATUS,
                ZEROER_CTRL_STATUS_START,
                length=8,
            )
            for _ in range(_FIRST_AW_CYCLES):
                if wire.aw:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, 1)
            else:
                raise AssertionError(
                    f"{label}: no zeroer AW handshake within {_FIRST_AW_CYCLES} clk_smc_i cycles "
                    f"of the start write; DEST 0x{self._last_dest:x} SIZE {self._last_size}"
                )
            for _ in range(_STATUS_CLEAR_CYCLES):
                if await self._status() == 0:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, 1)
            else:
                raise AssertionError(
                    f"{label}: STATUS still busy {_STATUS_CLEAR_CYCLES} polls after the start "
                    f"write; AW handshakes {len(wire.aw)}, W beats {len(wire.w)}"
                )
        finally:
            wire.stop()
        self.runs += 1
        return wire

    async def body(self) -> None:
        dut = cocotb.top
        for name in (
            "tb_zeroer_awvalid",
            "tb_zeroer_awready",
            "tb_zeroer_awaddr",
            "tb_zeroer_awlen",
            "tb_zeroer_wvalid",
            "tb_zeroer_wready",
            "tb_zeroer_wdata",
            "tb_zeroer_wstrb",
            "tb_zeroer_wlast",
        ):
            assert hasattr(dut, name), f"{name} missing from the smc_uvm_top port surface"
        self._responder = self.cfg.sys_out_mem
        assert self._responder is not None, "SYS_OUT responder not bound"

        # S1: setup.
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        idle = await self._status()
        assert idle == 0, f"STATUS reads {idle} with the zeroer idle before any job"
        self._stamp("S1")

        # S2: aligned 64-byte job.
        pat2 = 0xA5
        self._poison(_ALIGNED_DEST, _ALIGNED_BYTES, pat2)
        await self._program(_ALIGNED_DEST, _ALIGNED_BYTES)
        wire = await self._trigger("ALIGNED")
        assert wire.aw == [(_ALIGNED_DEST, 7)], (
            f"aligned job AW (addr, len) {[(hex(a), n) for a, n in wire.aw]}, "
            f"expected [(0x{_ALIGNED_DEST:x}, 7)]"
        )
        assert len(wire.w) == 8, f"aligned job issued {len(wire.w)} W beats, expected 8"
        for i, (data, strb, last) in enumerate(wire.w):
            assert data == 0, f"aligned job W beat {i} data 0x{data:x}, expected 0"
            assert strb == 0xFF, f"aligned job W beat {i} strobe 0x{strb:02x}, expected 0xff"
            assert last == (1 if i == 7 else 0), f"aligned job W beat {i} WLAST {last}"
        self._compare("ALIGNED", _ALIGNED_DEST, _ALIGNED_BYTES, pat2)
        self._stamp("S2")
        self._chk(
            "S2",
            "CHK-ZEROER-JOB-ALIGNED-BEATS",
            "AW 0x%x len %d, %d W beats data 0 strobe 0xff WLAST on the last beat only, "
            "%d bytes zero and both %d-byte guards keep 0x%02x",
            wire.aw[0][0],
            wire.aw[0][1],
            len(wire.w),
            _ALIGNED_BYTES,
            _GUARD,
            pat2,
        )

        # S3: second job on a new region, then a bare re-trigger.
        pat_a, pat_b = 0x5A, 0xC3
        self._poison(_ALIGNED_DEST, _ALIGNED_BYTES, pat_a)
        self._poison(_SECOND_DEST, _SECOND_BYTES, pat_b)
        await self._program(_SECOND_DEST, _SECOND_BYTES)
        wire = await self._trigger("SECOND")
        assert wire.aw and wire.aw[0][0] == _SECOND_DEST, (
            f"second job first AW 0x{wire.aw[0][0]:x}, expected 0x{_SECOND_DEST:x}"
        )
        self._compare("SECOND", _SECOND_DEST, _SECOND_BYTES, pat_b)
        self._intact("SECOND-other-region", _ALIGNED_DEST, _ALIGNED_BYTES, pat_a)
        pat_c = 0x3C
        self._poison(_SECOND_DEST, _SECOND_BYTES, pat_c)
        wire = await self._trigger("RETRIGGER")
        assert wire.aw and wire.aw[0][0] == _SECOND_DEST, (
            f"re-trigger first AW 0x{wire.aw[0][0]:x}, expected 0x{_SECOND_DEST:x}"
        )
        self._compare("RETRIGGER", _SECOND_DEST, _SECOND_BYTES, pat_c)
        self._intact("RETRIGGER-other-region", _ALIGNED_DEST, _ALIGNED_BYTES, pat_a)
        self._stamp("S3")
        self._chk(
            "S3",
            "CHK-ZEROER-JOB-RESTART",
            "second job 0x%x+%d cleared, bare re-trigger of the same settings cleared the "
            "re-poisoned region again, the previous region 0x%x+%d kept its pattern 0x%02x",
            _SECOND_DEST,
            _SECOND_BYTES,
            _ALIGNED_DEST,
            _ALIGNED_BYTES,
            pat_a,
        )

        # S4: destination with bits [55:32] set.
        pat4 = 0x96
        self._poison(_HIGH_DEST, _HIGH_BYTES, pat4)
        rb_dest, rb_size = await self._program(_HIGH_DEST, _HIGH_BYTES)
        wire = await self._trigger("HIGH")
        assert wire.aw and wire.aw[0][0] == _HIGH_DEST, (
            f"high-address job first AW 0x{wire.aw[0][0] if wire.aw else 0:x}, "
            f"expected 0x{_HIGH_DEST:x}"
        )
        self._compare("HIGH", _HIGH_DEST, _HIGH_BYTES, pat4)
        self._stamp("S4")
        self._chk(
            "S4",
            "CHK-ZEROER-JOB-HIGH-ADDR",
            "programmed 0x%x, AW addresses %s, %d bytes cleared at that address, guards intact; "
            "DEST_ADDR reads back 0x%x and SIZE 0x%x (SF-014 width not asserted)",
            _HIGH_DEST,
            ",".join(f"0x{a:x}" for a, _n in wire.aw),
            _HIGH_BYTES,
            rb_dest,
            rb_size,
        )

        # S5: seeded random mix.
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        rng = random.Random(seed)
        cocotb.log.info("random job mix seed %d", seed)
        names = list(_BUCKETS)
        buckets = [names[i % 3] for i in range(_RANDOM_JOBS)]
        aligns = ["aligned" if i % 2 == 0 else "unaligned" for i in range(_RANDOM_JOBS)]
        rng.shuffle(buckets)
        rng.shuffle(aligns)
        tally_b = dict.fromkeys(names, 0)
        tally_a = {"aligned": 0, "unaligned": 0}
        jobs = []
        for i in range(_RANDOM_JOBS):
            lo, hi = _BUCKETS[buckets[i]]
            size = rng.randint(lo, hi)
            offset = 8 * rng.randint(0, 7) if aligns[i] == "aligned" else rng.randint(0, 63)
            if aligns[i] == "unaligned" and offset % 8 == 0:
                offset += 1 + rng.randint(0, 6)
            pattern = rng.randint(1, 255)
            dest = _RANDOM_BASE + i * _SLOT + 0x40 + offset
            self._poison(dest, size, pattern)
            await self._program(dest, size)
            await self._trigger(f"RANDOM_{i}")
            self._compare(f"RANDOM_{i}", dest, size, pattern)
            tally_b[buckets[i]] += 1
            tally_a[aligns[i]] += 1
            jobs.append(f"{buckets[i]}:{size}@+{offset}")
        assert all(tally_b.values()) and all(tally_a.values()), (
            f"empty bucket: sizes {tally_b} offsets {tally_a}"
        )
        self._stamp("S5")
        self._chk(
            "S5",
            "CHK-ZEROER-JOB-RANDOM",
            "seed %d, %d jobs each cleared exactly [DEST, DEST+SIZE) with both guards intact; "
            "size buckets %s, offset buckets %s; jobs %s",
            seed,
            _RANDOM_JOBS,
            tally_b,
            tally_a,
            " ".join(jobs),
        )

        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
        self._nonvac()

    def _nonvac(self) -> None:
        steps = [s for s, _t in self._stamps]
        assert steps == ["S1", "S2", "S3", "S4", "S5"], f"step stamps {steps} not in order"
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"step stamps {times} are not strictly increasing"
        )
        ids = [c for c, _s in self._printed]
        assert ids == [
            "CHK-ZEROER-JOB-ALIGNED-BEATS",
            "CHK-ZEROER-JOB-RESTART",
            "CHK-ZEROER-JOB-HIGH-ADDR",
            "CHK-ZEROER-JOB-RANDOM",
        ], f"checker lines {ids} not in step order"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5 with checker lines printed in step order "
            "after their own compares; checker lines %s; stamps %s ps",
            ",".join(ids),
            ",".join(str(t) for t in times),
        )
