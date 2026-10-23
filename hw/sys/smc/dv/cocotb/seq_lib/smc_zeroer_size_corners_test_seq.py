# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer jobs at the edges of what SIZE and DEST_ADDR describe.

The RDL gives `SIZE` as "Size in bytes of zeros to write" and `DEST_ADDR` as
the "Byte address to write zeros to", and `hw/sys/smc/doc/zeroer.adoc` lists
unaligned start addresses and burst fragmentation at page boundaries among
what the zeroer handles. Two jobs here sit at those edges:

* **A job of zero bytes.** `CTRL_STATUS` is written, which is the trigger,
  with `SIZE` at 0. Zero bytes are to be written, so nothing may reach the
  output fabric: the poisoned word at `DEST_ADDR` has to keep its poison, and
  an eight-byte job started afterwards has to be the only write transaction
  the responder books across both triggers.
* **A job that starts four bytes before a page boundary and ends mid-word.**
  Sixteen bytes from `page - 4`: the upper half of the word below the
  boundary, the whole word at it, and the lower half of the word above. AXI
  forbids a burst across a 4 KB boundary, so the job takes at least two
  write transactions, and the bytes on either side of it have to keep their
  poison.

Both jobs are aimed at the output-fabric responder window.

After them the start address is walked over the zeroer's 56-bit data address
(`zeroer.adoc`, AXI4 master characteristics), with the SYS_OUT responder's
memory written and read through its backdoor and its AW, W and B channels
sampled passively:

* **DEST_ADDR as storage.** All ones, 0 and the 64 walking-one words, each
  read back over the RW width `zeroer_ctrl.adoc` gives the field.
* **Window guard.** `GLOBAL_BASE` is first moved from its reset value, which
  is `1 << 30`, to 0x6000_0000 and restored at the end.
  `LOCAL_BASE`, `GLOBAL_BASE` and `REGION_SIZE` are then read and
  no single-bit destination may lie in the local or global SMC window or the
  8 MiB M-mode and Xvisor windows `fabric.adoc` places 0x0100_0000 and
  0x0180_0000 above either base, since the input demux sends those addresses
  back into the SMC instead of to SYS_OUT.
* **Bit walk.** One eight-byte job at each `1 << k`, k = 3..55: its first AW
  carries that address, its eight bytes are zeroed and the words either side
  keep their poison. The k = 20 job is 64 KiB, and its `STATUS` samples are
  held against the responder's count of write responses.
* **Unaligned starts** at 1, 2 and 4 bytes: exactly the eight bytes from the
  start are strobed and zeroed.
* **SIZE 0.** `CTRL_STATUS` ignores the start while `SIZE` is 0, so no AW is
  issued and `STATUS` reads 0; the eight-byte job after it books one AW.
* **Above range.** A start at bit 56 has to return `STATUS` to 0; its AW
  address, BRESP and the `DEST_ADDR` readback are logged and not compared,
  since the response above the mapped range is not documented.

`SIZE` and `DEST_ADDR` are cleared at the end so a later write to
`CTRL_STATUS` cannot start a job over anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_MODEL_BASE,
    OUTPUT_FABRIC_MODEL_REGION,
    OUTPUT_FABRIC_MODEL_SIZE,
    check_output_responder_delta,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)
from .smc_zeroer_dma_timeout_test_seq import (
    STATUS_BM,
    ZEROER_CTRL_STATUS,
    ZEROER_DEST_ADDR,
    ZEROER_SIZE,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR,
    SMC_BASE_CONFIG_LOCAL_BASE_REG_ADDR,
    SMC_BASE_CONFIG_REGION_SIZE_REG_ADDR,
)

_WORD_BYTES = 8
_PAGE_BYTES = 0x1000

#: The zero-size job's destination, and the eight-byte job that follows it.
_EMPTY_DEST = OUTPUT_FABRIC_ADDR + 0x2000
_EMPTY_POISON = 0xA0A1_A2A3_A4A5_A6A7
_FOLLOW_DEST = OUTPUT_FABRIC_ADDR + 0x2100
_FOLLOW_POISON = 0xB0B1_B2B3_B4B5_B6B7

#: The page-crossing job: sixteen bytes from four bytes below a page boundary.
_PAGE = OUTPUT_FABRIC_ADDR + 0x4000
_CROSS_DEST = _PAGE - 4
_CROSS_BYTES = 16
_CROSS_MIN_BURSTS = 2
#: (name, word address, poison, mask of the bytes the job covers)
_CROSS_WORDS = (
    ("BELOW", _PAGE - _WORD_BYTES, 0xC0C1_C2C3_C4C5_C6C7, 0xFFFF_FFFF_0000_0000),
    ("AT", _PAGE, 0xD0D1_D2D3_D4D5_D6D7, 0xFFFF_FFFF_FFFF_FFFF),
    ("ABOVE", _PAGE + _WORD_BYTES, 0xE0E1_E2E3_E4E5_E6E7, 0x0000_0000_FFFF_FFFF),
)

# Liveness ceilings, not checked quantities: expiry FAILS.
_STATUS_CYCLES = 40000
_BURST_WAIT_CYCLES = 40000

_MASK64 = (1 << 64) - 1
#: `base` [55:0] of GLOBAL_BASE / LOCAL_BASE and `size` [31:0] of REGION_SIZE.
_BASE_FIELD = (1 << 56) - 1
_SIZE_FIELD = (1 << 32) - 1
#: GLOBAL_BASE for the start-address legs: REGION_SIZE-aligned, and neither its
#: window nor the M-mode / Xvisor windows above it hold a power of two.
_RELOCATED_GLOBAL_BASE = 0x6000_0000
#: The M-mode and Xvisor output-remap windows above either SMC base.
_REMAP_WINDOWS = (("M-MODE", 0x0100_0000, 0x0080_0000), ("XVISOR", 0x0180_0000, 0x0080_0000))

_WALK_BITS = range(3, 56)
_BUSY_BIT = 20
_BUSY_BYTES = 0x1_0000
_UNALIGNED_BITS = range(0, 3)
_UNALIGNED_SPAN = 0x18
_UNALIGNED_POISON = 0xA5
_SIZE0_DEST = 1 << 12
_SIZE0_FOLLOW = 1 << 13
_ABOVE_DEST = 1 << 56
_JOB_POISON = 0x5C
_NEIGHBOUR_POISON = bytes.fromhex("1f2e3d4c5b6a7988")
_ABOVE_RANGE_SF = "SF-019"

#: Ordered fence of CHK-NONVAC: (term, step stamp).
_FENCE = (
    ("EXISTING-JOBS", "S1"),
    ("DEST-PATTERNS", "S2"),
    ("WINDOW-GUARD", "S3"),
    ("BIT-WALK", "S4"),
    ("UNALIGNED", "S5"),
    ("SIZE-ZERO", "S6"),
    ("ABOVE-RANGE", "S7"),
    ("RESTORED", "S8"),
)
#: Checker lines in print order, each with the step it is printed after.
_CHECKERS = (
    ("CHK-ZEROER-EMPTY-JOB", "S1"),
    ("CHK-ZEROER-PAGE-CROSS", "S1"),
    ("CHK-ZEROER-DEST-PATTERN", "S2"),
    ("CHK-ZEROER-ADDR-WALK", "S4"),
    ("CHK-ZEROER-BUSY", "S4"),
    ("CHK-ZEROER-UNALIGNED", "S5"),
    ("CHK-ZEROER-SIZE0", "S6"),
    ("CHK-ZEROER-ABOVE-RANGE", "S7"),
)


class _SysOutWatch:
    """Passive clk_smc_i sampler of the AW, W and B handshakes on u_output_axi_if."""

    def __init__(self) -> None:
        self.aw: list[tuple[int, int, int]] = []
        self.w_strb: list[int] = []
        self.b_resp: list[int] = []
        self._task = None

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    @staticmethod
    def _sample(ifc, ch: str, payload: tuple[str, ...]) -> tuple[int, ...] | None:
        valid, ready = getattr(ifc, f"{ch}valid").value, getattr(ifc, f"{ch}ready").value
        assert valid.is_resolvable and ready.is_resolvable, (
            f"u_output_axi_if {ch}valid / {ch}ready are X/Z: {valid} {ready}"
        )
        if not (int(valid) and int(ready)):
            return None
        values = [getattr(ifc, f"{ch}{name}").value for name in payload]
        assert all(v.is_resolvable for v in values), (
            f"u_output_axi_if {ch} payload is X/Z at a handshake: {values}"
        )
        return tuple(int(v) for v in values)

    async def _run(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while True:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            aw = self._sample(ifc, "aw", ("addr", "len", "size"))
            if aw is not None:
                self.aw.append(aw)
            w = self._sample(ifc, "w", ("strb",))
            if w is not None:
                self.w_strb.append(w[0])
            b = self._sample(ifc, "b", ("resp",))
            if b is not None:
                self.b_resp.append(b[0])

    def mark(self) -> tuple[int, int, int]:
        return len(self.aw), len(self.w_strb), len(self.b_resp)

    def strobed_bytes(self, mark: tuple[int, int, int]) -> set[int]:
        """Byte addresses enabled by the W beats since `mark`, placed by their AW (INCR)."""
        aws = self.aw[mark[0] :]
        strbs = self.w_strb[mark[1] :]
        out: set[int] = set()
        beat = 0
        for addr, length, size in aws:
            lane_bytes = 1 << size
            aligned = (addr // lane_bytes) * lane_bytes
            for n in range(length + 1):
                assert beat < len(strbs), (
                    f"AW 0x{addr:x} len {length} has fewer W beats than it announces"
                )
                beat_addr = addr if n == 0 else aligned + n * lane_bytes
                word = (beat_addr // _WORD_BYTES) * _WORD_BYTES
                strb = strbs[beat]
                out.update(word + lane for lane in range(_WORD_BYTES) if (strb >> lane) & 1)
                beat += 1
        assert beat == len(strbs), f"{len(strbs) - beat} W beat(s) follow no AW"
        return out


class smc_zeroer_size_corners_test_seq(output_fabric_pass_all_cfg_seq):
    """A zero-byte job and a job crossing a page boundary from an unaligned start."""

    def __init__(self, name: str = "smc_zeroer_size_corners_test_seq") -> None:
        super().__init__(name)
        self.empty_bursts = -1
        self.cross_bursts = -1
        self.stamps: list[tuple[str, int, int]] = []
        self.chk_marks: list[tuple[str, str | None]] = []
        self.watch = _SysOutWatch()
        self.mem = None
        self.polls = 0
        self.poll_waits = 0
        self.poll_max_cycles = 0
        self.poll_last = "no poll yet"
        self.global_base_saved: int | None = None
        self.global_base_live: int | None = None

    def _ensure_model_region(self) -> None:
        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION,
                OUTPUT_FABRIC_MODEL_BASE,
                OUTPUT_FABRIC_MODEL_SIZE,
            )

    async def _fabric_write(self, addr: int, value: int) -> None:
        item = SmcSysAxiItem(f"fabric_preload_0x{addr:x}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = _WORD_BYTES
        item.wdata = value
        await _OneShot(item, f"fabric_preload_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )

    async def _fabric_read(self, addr: int) -> int:
        item = SmcSysAxiItem(f"fabric_readback_0x{addr:x}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = _WORD_BYTES
        await _OneShot(item, f"fabric_readback_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )
        return item.rdata

    async def _poison(self, label: str, addr: int, value: int) -> None:
        await self._fabric_write(addr, value)
        got = await self._fabric_read(addr)
        assert got == value, (
            f"{label}: 0x{addr:08x} reads 0x{got:016x} after a preload of 0x{value:016x}; "
            f"the word was not poisoned, so a later compare against it would prove nothing"
        )

    async def _program(self, label: str, dest: int, size: int) -> None:
        await self.csr_write(f"{label}_DEST_ADDR", ZEROER_DEST_ADDR, dest, length=8)
        await self.csr_write(f"{label}_SIZE", ZEROER_SIZE, size, length=8)
        await self.csr_read(f"{label}_DEST_ADDR_RB", ZEROER_DEST_ADDR, expected=dest, length=8)
        await self.csr_read(f"{label}_SIZE_RB", ZEROER_SIZE, expected=size, length=8)

    async def _trigger(self, label: str) -> None:
        await self.csr_write(f"{label}_TRIGGER", ZEROER_CTRL_STATUS, 0, length=8)

    async def _await_idle(self, label: str) -> None:
        """Bounded wait for `CTRL_STATUS.STATUS` at 0, which the RDL gives as idle."""
        word = STATUS_BM
        for _ in range(_STATUS_CYCLES):
            word = await self.csr_read(f"{label}_STATUS", ZEROER_CTRL_STATUS, length=8)
            if not word & STATUS_BM:
                return
            await cocotb.triggers.ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: CTRL_STATUS.STATUS never returned to 0 (last 0x{word:016x})"
        )

    async def _empty_leg(self) -> None:
        label = "EMPTY"
        await self._poison(label, _EMPTY_DEST, _EMPTY_POISON)
        await self._poison(f"{label}_FOLLOW", _FOLLOW_DEST, _FOLLOW_POISON)
        await self._program(label, _EMPTY_DEST, 0)
        start_writes, start_reads = output_responder_counts()
        await self._trigger(label)
        await self._await_idle(label)
        # The zeroer runs one job at a time, so once the eight-byte job has
        # booked its write, anything the zero-size job issued has been booked
        # before it and shows in the exact count.
        await self._program(f"{label}_FOLLOW", _FOLLOW_DEST, _WORD_BYTES)
        await self._trigger(f"{label}_FOLLOW")
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=0,
            timeout_cycles=_BURST_WAIT_CYCLES,
        )
        await self._await_idle(f"{label}_FOLLOW")
        end_writes, _ = output_responder_counts()
        self.empty_bursts = end_writes - start_writes
        kept = await self._fabric_read(_EMPTY_DEST)
        assert kept == _EMPTY_POISON, (
            f"{label}: 0x{_EMPTY_DEST:08x} reads 0x{kept:016x} after a job of SIZE 0 aimed "
            f"at it; zero bytes were to be written, so it has to keep 0x{_EMPTY_POISON:016x}"
        )
        cleared = await self._fabric_read(_FOLLOW_DEST)
        assert cleared == 0, (
            f"{label}: 0x{_FOLLOW_DEST:08x} reads 0x{cleared:016x} after the eight-byte job "
            f"that follows the empty one"
        )
        cocotb.log.info(
            "CHK-ZEROER-EMPTY-JOB: a trigger with SIZE 0 left the poisoned word at DEST_ADDR "
            "0x%08x holding 0x%016x, and across it and the eight-byte job that followed the "
            "output responder booked %d write transaction, the eight-byte job's",
            _EMPTY_DEST,
            kept,
            self.empty_bursts,
        )

    async def _cross_page_leg(self) -> None:
        label = "CROSS"
        guard_below = _PAGE - 2 * _WORD_BYTES
        guard_above = _PAGE + 2 * _WORD_BYTES
        guard_poison = 0xF0F1_F2F3_F4F5_F6F7
        for name, addr, poison, _mask in _CROSS_WORDS:
            await self._poison(f"{label}_{name}", addr, poison)
        await self._poison(f"{label}_GUARD_BELOW", guard_below, guard_poison)
        await self._poison(f"{label}_GUARD_ABOVE", guard_above, guard_poison)
        await self._program(label, _CROSS_DEST, _CROSS_BYTES)
        start_writes, start_reads = output_responder_counts()
        await self._trigger(label)
        # At least two transactions, since no AXI burst may cross the 4 KB
        # boundary the job straddles; the design may split further, which the
        # byte compares below still bound.
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=_CROSS_MIN_BURSTS,
            read_delta=0,
            exact_writes=False,
            timeout_cycles=_BURST_WAIT_CYCLES,
        )
        await self._await_idle(label)
        end_writes, _ = output_responder_counts()
        self.cross_bursts = end_writes - start_writes
        for name, addr, poison, mask in _CROSS_WORDS:
            got = await self._fabric_read(addr)
            want = poison & ~mask & 0xFFFF_FFFF_FFFF_FFFF
            assert got == want, (
                f"{label}: word {name} at 0x{addr:08x} reads 0x{got:016x}, not 0x{want:016x}; "
                f"the job covers bytes 0x{_CROSS_DEST:08x}..0x{_CROSS_DEST + _CROSS_BYTES - 1:08x}"
                f" and only those may be zeroed (poison 0x{poison:016x})"
            )
        for tag, addr in (("GUARD_BELOW", guard_below), ("GUARD_ABOVE", guard_above)):
            got = await self._fabric_read(addr)
            assert got == guard_poison, (
                f"{label}: {tag} word at 0x{addr:08x} reads 0x{got:016x}; it lies outside the "
                f"job and has to keep 0x{guard_poison:016x}"
            )
        cocotb.log.info(
            "CHK-ZEROER-PAGE-CROSS: a %d-byte job from 0x%08x, four bytes below a 4 KB "
            "boundary, zeroed exactly its bytes: the upper half of the word below the "
            "boundary, the word at it and the lower half of the word above, with both halves "
            "outside the job and the guard words either side keeping their poison, in %d "
            "write transactions",
            _CROSS_BYTES,
            _CROSS_DEST,
            self.cross_bursts,
        )

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps")), self.accesses))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        cocotb.log.info(f"{chk_id}: {text}", *args)
        self.chk_marks.append((chk_id, self.stamps[-1][0] if self.stamps else None))

    async def _poll_idle(self, label: str, samples: list | None = None) -> int:
        """Poll `CTRL_STATUS.STATUS` until 0 within `_STATUS_CYCLES` clk_smc_i; return polls."""
        period_ns = self.cfg.smc_clk_period_ns
        start_ns = get_sim_time("ns")
        deadline = start_ns + _STATUS_CYCLES * period_ns
        polls = 0
        word = None
        while get_sim_time("ns") < deadline:
            before, _ = output_responder_counts()
            word = await self.csr_read(f"{label}_STATUS", ZEROER_CTRL_STATUS, length=8)
            after, reads = output_responder_counts()
            polls += 1
            busy = 1 if word & STATUS_BM else 0
            if samples is not None:
                samples.append((busy, before, after))
            self.poll_last = (
                f"{label} poll {polls}: CTRL_STATUS 0x{word:016x}, responder writes {after} "
                f"reads {reads}, SYS_OUT AW {len(self.watch.aw)} B {len(self.watch.b_resp)}"
            )
            if not busy:
                used = int((get_sim_time("ns") - start_ns) / period_ns)
                self.poll_max_cycles = max(self.poll_max_cycles, used)
                self.polls += polls
                self.poll_waits += 1
                return polls
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: CTRL_STATUS.STATUS still 1 after {_STATUS_CYCLES} clk_smc_i "
            f"({polls} polls); last {self.poll_last}"
        )

    def _mem_write(self, addr: int, data: bytes) -> None:
        self.mem.write(addr, data)
        got = self.mem.read(addr, len(data))
        assert got == data, f"responder bytes at 0x{addr:x} did not take their poison"

    async def _job(self, label: str, dest: int, size: int, samples: list | None = None):
        await self._program(label, dest, size)
        mark = self.watch.mark()
        await self._trigger(label)
        polls = await self._poll_idle(label, samples)
        return mark, polls

    async def _relocate_global_base(self) -> None:
        self.global_base_saved = await self.csr_read(
            "GLOBAL_BASE_SAVE", SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR, length=8
        )
        await self.csr_write(
            "GLOBAL_BASE_RELOCATE",
            SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR,
            _RELOCATED_GLOBAL_BASE,
            length=8,
        )
        got = await self.csr_read(
            "GLOBAL_BASE_RELOCATE_RB", SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR, length=8
        )
        assert got & _BASE_FIELD == _RELOCATED_GLOBAL_BASE, (
            f"GLOBAL_BASE reads 0x{got:016x} after a write of 0x{_RELOCATED_GLOBAL_BASE:x}; "
            f"[55:0] is RW, and the start-address legs need the global window relocated"
        )
        cocotb.log.info(
            "GLOBAL_BASE saved 0x%016x, relocated to 0x%x (readback 0x%016x)",
            self.global_base_saved,
            _RELOCATED_GLOBAL_BASE,
            got,
        )

    async def _dest_patterns(self) -> None:
        patterns = [_MASK64, 0] + [1 << b for b in range(64)]
        for n, value in enumerate(patterns):
            await self.csr_write(f"DEST_PAT_{n}", ZEROER_DEST_ADDR, value, length=8)
            got = await self.csr_read(f"DEST_PAT_{n}_RB", ZEROER_DEST_ADDR, length=8)
            assert got == value, (
                f"DEST_ADDR reads 0x{got:016x} after a write of 0x{value:016x}; the field is "
                f"RW over [63:0]"
            )
        await self.csr_write("DEST_PAT_LEAVE", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("DEST_PAT_LEAVE_RB", ZEROER_DEST_ADDR, expected=0, length=8)
        self._stamp("S2")
        self._chk(
            "CHK-ZEROER-DEST-PATTERN",
            "%d DEST_ADDR writes (all ones, 0, walking one b = 0..63) each read back the word "
            "written over [63:0] with BRESP and RRESP OKAY; left at 0",
            len(patterns),
        )

    async def _window_guard(self) -> None:
        local = await self.csr_read("LOCAL_BASE", SMC_BASE_CONFIG_LOCAL_BASE_REG_ADDR, length=8)
        glob = await self.csr_read("GLOBAL_BASE", SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR, length=8)
        region = await self.csr_read("REGION_SIZE", SMC_BASE_CONFIG_REGION_SIZE_REG_ADDR, length=8)
        local &= _BASE_FIELD
        glob &= _BASE_FIELD
        self.global_base_live = glob
        region &= _SIZE_FIELD
        windows = []
        for tag, base in (("LOCAL", local), ("GLOBAL", glob)):
            windows.append((tag, base, region))
            windows.extend(
                (f"{tag}+{name}", base + off, span) for name, off, span in _REMAP_WINDOWS
            )
        dests = [1 << k for k in range(56)] + [_ABOVE_DEST]
        hits = [
            f"0x{d:x} in {tag} [0x{lo:x}, 0x{lo + span:x})"
            for d in dests
            for tag, lo, span in windows
            if lo <= d < lo + span
        ]
        assert not hits, (
            f"WINDOW GUARD: LOCAL_BASE 0x{local:x}, GLOBAL_BASE 0x{glob:x}, REGION_SIZE "
            f"0x{region:x}: single-bit destinations fall inside an SMC window and would not reach "
            f"SYS_OUT: {'; '.join(hits)}"
        )
        self._stamp("S3")
        cocotb.log.info(
            "WINDOW GUARD: LOCAL_BASE 0x%x, GLOBAL_BASE 0x%x, REGION_SIZE 0x%x; none of the %d "
            "destinations lies in %s",
            local,
            glob,
            region,
            len(dests),
            ", ".join(f"{t}[0x{lo:x}+0x{sp:x}]" for t, lo, sp in windows),
        )

    async def _bit_walk(self) -> None:
        walked = []
        busy_samples: list[tuple[int, int, int]] = []
        busy_obs = None
        for k in _WALK_BITS:
            dest = 1 << k
            size = _BUSY_BYTES if k == _BUSY_BIT else _WORD_BYTES
            below, above = dest - _WORD_BYTES, dest + size
            self._mem_write(below, _NEIGHBOUR_POISON)
            self._mem_write(dest, bytes([_JOB_POISON]) * size)
            self._mem_write(above, _NEIGHBOUR_POISON)
            samples = busy_samples if k == _BUSY_BIT else None
            base_writes, _ = output_responder_counts()
            mark, polls = await self._job(f"WALK_{k}", dest, size, samples)
            if samples is not None:
                word = await self.csr_read(f"WALK_{k}_STATUS_AFTER", ZEROER_CTRL_STATUS, length=8)
                after, _ = output_responder_counts()
                samples.append((1 if word & STATUS_BM else 0, after, after))
            aws = self.watch.aw[mark[0] :]
            assert aws, f"WALK_{k}: no AW at SYS_OUT for a job at 0x{dest:x}"
            assert aws[0][0] == dest, (
                f"WALK_{k}: the first AW at SYS_OUT carries 0x{aws[0][0]:x}, the job starts at "
                f"0x{dest:x}"
            )
            head = self.mem.read(dest, _WORD_BYTES)
            assert head == bytes(_WORD_BYTES), (
                f"WALK_{k}: the {_WORD_BYTES} bytes at 0x{dest:x} read {head.hex()} after the job"
            )
            if size != _WORD_BYTES:
                body = self.mem.read(dest, size)
                left = sum(1 for b in body if b)
                assert left == 0, f"WALK_{k}: {left} of the {size} job bytes are not zero"
            for tag, addr in (("BELOW", below), ("ABOVE", above)):
                got = self.mem.read(addr, _WORD_BYTES)
                assert got == _NEIGHBOUR_POISON, (
                    f"WALK_{k}: the word {tag} the job at 0x{addr:x} reads {got.hex()}, not its "
                    f"poison {_NEIGHBOUR_POISON.hex()}"
                )
            if k == _BUSY_BIT:
                busy_obs = (base_writes, len(aws), list(busy_samples))
            walked.append((k, len(aws), polls))
        self._stamp("S4")
        self._chk(
            "CHK-ZEROER-ADDR-WALK",
            "GLOBAL_BASE 0x%x: %d jobs k = %d..%d: each first SYS_OUT AW carried 1 << k, the 8 "
            "bytes at 1 << k read 0x00 with both neighbouring words poisoned, STATUS read 0 "
            "within %d clk_smc_i; (k, AWs, polls) %s",
            self.global_base_live,
            len(walked),
            _WALK_BITS[0],
            _WALK_BITS[-1],
            _STATUS_CYCLES,
            " ".join(f"{k}/{n}/{p}" for k, n, p in walked),
        )
        self._check_busy(busy_obs)

    def _check_busy(self, obs) -> None:
        base, bursts, samples = obs
        assert bursts >= 1, "the 64 KiB job issued no burst"
        in_flight = [s for s in samples if s[2] - base < bursts]
        assert in_flight, (
            f"no STATUS sample of the 64 KiB job was taken before its last write response "
            f"({bursts} bursts); samples {samples}"
        )
        wrong = [s for s in in_flight if s[0] != 1]
        assert not wrong, (
            f"STATUS read 0 while the responder had returned fewer than {bursts} write "
            f"responses: (status, responses before, after) {[(s[0], s[1] - base, s[2] - base) for s in wrong]}"
        )
        done = [s for s in samples if s[1] - base >= bursts]
        assert done, f"no STATUS sample was taken after the last of {bursts} write responses"
        assert done[0][0] == 0, (
            f"the first STATUS sample after the last of {bursts} write responses reads {done[0][0]}"
        )
        self._chk(
            "CHK-ZEROER-BUSY",
            "k = %d job of 0x%x bytes in %d bursts: %d STATUS samples taken with fewer than %d "
            "write responses returned all read 1, the first sample after the last response "
            "read 0; (status, responses) %s",
            _BUSY_BIT,
            _BUSY_BYTES,
            bursts,
            len(in_flight),
            bursts,
            " ".join(f"{s[0]}/{s[2] - base}" for s in samples),
        )

    async def _unaligned(self) -> None:
        rows = []
        for k in _UNALIGNED_BITS:
            dest = 1 << k
            self._mem_write(0, bytes([_UNALIGNED_POISON]) * _UNALIGNED_SPAN)
            mark, _polls = await self._job(f"UNALIGNED_{k}", dest, _WORD_BYTES)
            got = self.mem.read(0, _UNALIGNED_SPAN)
            want = bytes(
                0 if dest <= i < dest + _WORD_BYTES else _UNALIGNED_POISON
                for i in range(_UNALIGNED_SPAN)
            )
            assert got == want, (
                f"UNALIGNED_{k}: bytes 0x0..0x{_UNALIGNED_SPAN - 1:x} read {got.hex()}, expected "
                f"{want.hex()} (exactly [0x{dest:x}, 0x{dest + _WORD_BYTES:x}) zeroed)"
            )
            strobed = self.watch.strobed_bytes(mark)
            assert strobed == set(range(dest, dest + _WORD_BYTES)), (
                f"UNALIGNED_{k}: W strobes enable bytes {sorted(strobed)}, the job covers "
                f"[0x{dest:x}, 0x{dest + _WORD_BYTES:x})"
            )
            aws = self.watch.aw[mark[0] :]
            rows.append(f"k={k} AW {'/'.join(f'0x{a:x}(len {n}, size {z})' for a, n, z in aws)}")
        self._stamp("S5")
        self._chk(
            "CHK-ZEROER-UNALIGNED",
            "starts 1, 2, 4 with SIZE 8: exactly the 8 bytes from the start read 0x00 and were the "
            "only strobed bytes, the other 16 of 0x0..0x17 kept 0x%02X; AW address measured "
            "(SF-020): %s",
            _UNALIGNED_POISON,
            "; ".join(rows),
        )

    async def _size_zero(self) -> None:
        self._mem_write(_SIZE0_DEST, bytes([_JOB_POISON]) * _WORD_BYTES)
        self._mem_write(_SIZE0_FOLLOW, bytes([_JOB_POISON]) * _WORD_BYTES)
        await self._program("SIZE0", _SIZE0_DEST, 0)
        mark = self.watch.mark()
        await self._trigger("SIZE0")
        word = await self.csr_read("SIZE0_STATUS", ZEROER_CTRL_STATUS, length=8)
        assert not word & STATUS_BM, f"SIZE0: CTRL_STATUS reads 0x{word:016x} after the start"
        empty_aw = len(self.watch.aw) - mark[0]
        assert empty_aw == 0, f"SIZE0: {empty_aw} AW issued by a start with SIZE 0"
        await self._program("SIZE0_FOLLOW", _SIZE0_FOLLOW, _WORD_BYTES)
        await self._trigger("SIZE0_FOLLOW")
        await self._poll_idle("SIZE0_FOLLOW")
        aws = self.watch.aw[mark[0] :]
        assert [a[0] for a in aws] == [_SIZE0_FOLLOW], (
            f"SIZE0: AWs across the SIZE 0 start and the 8-byte job: "
            f"{[hex(a[0]) for a in aws]}, expected one at 0x{_SIZE0_FOLLOW:x}"
        )
        kept = self.mem.read(_SIZE0_DEST, _WORD_BYTES)
        cleared = self.mem.read(_SIZE0_FOLLOW, _WORD_BYTES)
        assert kept == bytes([_JOB_POISON]) * _WORD_BYTES, (
            f"SIZE0: 0x{_SIZE0_DEST:x} reads {kept.hex()}"
        )
        assert cleared == bytes(_WORD_BYTES), f"SIZE0: 0x{_SIZE0_FOLLOW:x} reads {cleared.hex()}"
        self._stamp("S6")
        self._chk(
            "CHK-ZEROER-SIZE0",
            "a start with SIZE 0 at 0x%x read CTRL_STATUS 0x%016x (STATUS 0) and issued no AW, "
            "its word kept its poison; the 8-byte job after it booked exactly one AW, at 0x%x, "
            "and zeroed its word",
            _SIZE0_DEST,
            word,
            _SIZE0_FOLLOW,
        )

    async def _above_range(self) -> None:
        mon = self.env.output_axi_monitor
        allow = (mon.allow_slverr, mon.allow_decerr)
        mon.allow_slverr = mon.allow_decerr = True
        try:
            await self.csr_write("ABOVE_DEST_ADDR", ZEROER_DEST_ADDR, _ABOVE_DEST, length=8)
            await self.csr_write("ABOVE_SIZE", ZEROER_SIZE, _WORD_BYTES, length=8)
            await self.csr_read("ABOVE_SIZE_RB", ZEROER_SIZE, expected=_WORD_BYTES, length=8)
            readback = await self.csr_read("ABOVE_DEST_ADDR_RB", ZEROER_DEST_ADDR, length=8)
            mark = self.watch.mark()
            await self._trigger("ABOVE")
            polls = await self._poll_idle("ABOVE")
        finally:
            mon.allow_slverr, mon.allow_decerr = allow
        aws = self.watch.aw[mark[0] :]
        bresp = self.watch.b_resp[mark[2] :]
        self._stamp("S7")
        self._chk(
            "CHK-ZEROER-ABOVE-RANGE",
            "DEST_ADDR 0x%016x (bit 56) with SIZE 8 returned STATUS to 0 in %d polls within %d "
            "clk_smc_i; measured, not compared (LINKED-ISSUE %s, SF-020): DEST_ADDR readback "
            "0x%016x, AW %s, BRESP %s",
            _ABOVE_DEST,
            polls,
            _STATUS_CYCLES,
            _ABOVE_RANGE_SF,
            readback,
            [f"0x{a:x}(len {n})" for a, n, _z in aws],
            bresp,
        )

    async def _restore(self) -> None:
        await self.csr_write("RESTORE_DEST_ADDR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_write("RESTORE_SIZE", ZEROER_SIZE, 0, length=8)
        await self.csr_read("RESTORE_DEST_ADDR_RB", ZEROER_DEST_ADDR, expected=0, length=8)
        await self.csr_read("RESTORE_SIZE_RB", ZEROER_SIZE, expected=0, length=8)
        saved = self.global_base_saved
        await self.csr_write(
            "RESTORE_GLOBAL_BASE", SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR, saved, length=8
        )
        got = await self.csr_read(
            "RESTORE_GLOBAL_BASE_RB", SMC_BASE_CONFIG_GLOBAL_BASE_REG_ADDR, length=8
        )
        assert got & _BASE_FIELD == saved & _BASE_FIELD, (
            f"GLOBAL_BASE reads 0x{got:016x} after restoring the saved 0x{saved:016x}"
        )
        self._stamp("S8")

    def _nonvac(self) -> None:
        steps = [s for s, _t, _a in self.stamps]
        assert steps == [s for _term, s in _FENCE], f"step stamps {steps} out of order"
        assert [c for c, _ in self.chk_marks] == [c for c, _ in _CHECKERS], (
            f"checker lines {self.chk_marks} out of order"
        )
        for (chk, step), (_c, after) in zip(_CHECKERS, self.chk_marks, strict=True):
            assert after == step, f"{chk} printed after step {after}, expected {step}"
        terms = []
        prev_t, prev_a = -1, 0
        for (term, _step), (_s, t, a) in zip(_FENCE, self.stamps, strict=True):
            assert t > prev_t, f"fence term {term} at {t} ps is not after {prev_t} ps"
            assert a > prev_a, f"fence term {term} issued no SEP_IN access"
            terms.append(f"{term}@{t}ps/{a - prev_a}acc")
            prev_t, prev_a = t, a
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s",
            " < ".join(terms),
            " ".join(c for c, _ in _CHECKERS),
        )

    def _timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: STATUS polls of the start-address legs bound=%d clk_smc_i (%d "
            "waits, %d polls, longest %d clk_smc_i), expiry raises AssertionError with the last "
            "CTRL_STATUS and responder counts; the existing legs' STATUS waits bound=%d polls and "
            "responder waits bound=%d clk_smc_i raise AssertionError on expiry; every SEP_IN "
            "access (%d) bound=%d ns allow_timeout False, expiry raises in the SEP_IN driver; "
            "0 expired; last[%s]",
            _STATUS_CYCLES,
            self.poll_waits,
            self.polls,
            self.poll_max_cycles,
            _STATUS_CYCLES,
            _BURST_WAIT_CYCLES,
            self.accesses,
            self.cfg.axi_timeout_ns,
            self.poll_last,
        )

    async def body(self) -> None:
        assert _PAGE + 3 * _WORD_BYTES <= OUTPUT_FABRIC_ADDR + OUTPUT_FABRIC_MODEL_SIZE
        assert _PAGE % _PAGE_BYTES == 0
        self._ensure_model_region()
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self._empty_leg()
        self.chk_marks.append(("CHK-ZEROER-EMPTY-JOB", None))
        await self._cross_page_leg()
        self.chk_marks.append(("CHK-ZEROER-PAGE-CROSS", None))
        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
        await self._relocate_global_base()
        self._stamp("S1")
        self.chk_marks = [(c, "S1") for c, _ in self.chk_marks]
        self.mem = self.cfg.sys_out_mem
        assert self.mem is not None, "SYS_OUT responder not bound"
        self.watch.start()
        try:
            await self._dest_patterns()
            await self._window_guard()
            await self._bit_walk()
            await self._unaligned()
            await self._size_zero()
            await self._above_range()
            await self._restore()
        finally:
            self.watch.stop()
        self._nonvac()
        self._timeout_paths()
