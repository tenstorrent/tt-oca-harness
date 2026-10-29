# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI-IN depth and burst type on the inbound SMN port, through an open window.

S1: a train of reads and a train of writes, each launched without waiting for
    the one before it and with the matching response channel held back so the
    trains queue up inside the DUT. The address handshakes the port accepts
    before it returns its first response are counted on the ext_in pins: a
    port that serialises accepts one. The reads must all return the RDL reset
    value, and the writes, which share one AWID so the ordering is fixed, must
    leave the last value they wrote in the register. The seed draws the read
    train's distinct ARIDs, with the all-zero and all-ones IDs always in the
    set, and the write train runs once under each of those two pinned IDs.
S2: a WRAP burst read and a multi-beat FIXED burst write at the same register
    targets are refused with SLVERR, a different verdict from the DECERR a
    filter or decode miss returns, while an INCR burst read and write of the
    same address, length and size just before each are OKAY, so the refusal
    follows the burst type and not the length. The seed draws the beat count
    of each INCR control (two or four 32-bit beats, the lengths a WRAP burst
    admits inside the 16-byte register window) and where this step sits
    relative to the trains.
S3: the SMC SPM through the same window. Every AxSIZE, with each of address
    bits [2:0] set and cleared between transfers, and a write and read at every
    address bit the SPM leaves free, read back what was written; an INCR burst
    reads back its beats, and a WRAP write followed by an INCR write both
    complete.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, with_timeout
from ocah_axi_vip import RESP_OKAY, RESP_SLVERR, AxiTimingProfile, resp_name, worst_resp
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    smc_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    await_smn_resp,
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset, smu_axi_in_prefix

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
SCRATCH_COLD = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")
# (AxSIZE, byte offset) pairs that set and clear each of address bits [2:0].
SIZE_STEPS = ((3, 0), (0, 1), (1, 2), (2, 4), (0, 7), (1, 6), (3, 0))
AXI_BURST_INCR = 1
SPM_BURST_BEATS = 8

# Transactions launched before the first response is collected.
OUTSTANDING = 64
# Cycles the master keeps BREADY / RREADY low once a train is armed, so the
# responses back up into the address channels while the train is still being
# offered. The pause releases itself, so every transfer still completes.
RESP_BACKPRESSURE_CYCLES = 600
# Address handshakes the port must accept before its first response handshake.
# The SMU integrator guide's "SMU Default Parameters" table sizes no inbound
# transaction queue, so the floor is the smallest count that separates a port
# with several transfers in flight from one that serialises them; the count
# the port reaches is logged with the check.
MIN_ACCEPTED_BEFORE_RESPONSE = 2
# One AWID for a whole write train, so AXI orders them and the last value
# written is the one the register must hold; the train runs once under each
# pinned ID.
SCRATCH_PATTERN_BASE = 0x51D0_0000
ID_SIGNALS = ("arid", "awid")

# 2 or 4 beats x 4 bytes stay inside a 16-byte wrapping window, and VERSION_LO
# is 16-byte aligned, so the burst is legal AXI and only its type is
# unsupported. The same 16 bytes are the four CHIP_CONFIG registers and the
# first four SCRATCH_COLD words, so the INCR controls touch registers only.
BURST_BEAT_CHOICES = (2, 4)
BURST_SIZE = 2
AXI_BURST_FIXED = 0
AXI_BURST_WRAP = 2
BURST_POSITIONS = ("before_reads", "between_trains", "after_writes")


class _AcceptedBeforeResponse:
    """Address handshakes the port takes before its first response handshake.

    Sampled on the DUT's flat AXI pins at each clk_smu edge, not from the
    master's queue, so the count is what the port accepted. A handshake on the
    address channel in the same cycle as the first response handshake is
    counted: the port took it before any response had been delivered.
    """

    def __init__(self, dut, clk, *, addr_channel: str, resp_channel: str) -> None:
        prefix = smu_axi_in_prefix(dut)
        names = tuple(
            f"{prefix}_{chan}{sig}"
            for chan, sig in (
                (addr_channel, "valid"),
                (addr_channel, "ready"),
                (resp_channel, "valid"),
                (resp_channel, "ready"),
            )
        )
        pins = []
        for name in names:
            pin = getattr(dut, name, None)
            if pin is None:
                raise AssertionError(f"{name} unobservable on this tb_top")
            pins.append(pin)
        self._addr_valid, self._addr_ready, self._resp_valid, self._resp_ready = pins
        self._clk = clk
        self.accepted = 0
        self.response_seen = False
        self._task = cocotb.start_soon(self._watch())

    @staticmethod
    def _high(pin) -> bool:
        return str(pin.value) == "1"

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self._high(self._addr_valid) and self._high(self._addr_ready):
                self.accepted += 1
            if self._high(self._resp_valid) and self._high(self._resp_ready):
                self.response_seen = True
                return

    def finish(self) -> int:
        if not self._task.done():
            self._task.cancel()
        return self.accepted


class smu_axi_in_burst_outstanding_test_seq:
    """Inbound SMN depth and unsupported burst types behind an open window."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed)
        self.id_width = 0
        self.read_ids: list[int] = []
        self.write_ids: tuple[int, ...] = ()
        self.read_beats = 0
        self.write_beats = 0
        self.burst_position = ""
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    def _draw(self) -> None:
        """Draw the ID set, the burst beat counts and the burst step position from the seed."""
        prefix = smu_axi_in_prefix(self.dut)
        widths = {len(getattr(self.dut, f"{prefix}_{name}")) for name in ID_SIGNALS}
        if len(widths) != 1:
            raise AssertionError(f"ext_in ID widths differ: {sorted(widths)}")
        self.id_width = widths.pop()
        id_max = (1 << self.id_width) - 1
        if id_max + 1 < OUTSTANDING:
            raise AssertionError(f"ID width {self.id_width} cannot carry {OUTSTANDING} IDs")
        self.write_ids = (0, id_max)
        free = [i for i in range(id_max + 1) if i not in self.write_ids]
        ids = list(self.write_ids) + self.rng.sample(free, OUTSTANDING - len(self.write_ids))
        self.rng.shuffle(ids)
        self.read_ids = ids
        self.read_beats = self.rng.choice(BURST_BEAT_CHOICES)
        self.write_beats = self.rng.choice(BURST_BEAT_CHOICES)
        self.burst_position = self.rng.choice(BURST_POSITIONS)
        self._log(
            f"SEED: RANDOM_SEED={self.seed} id_width={self.id_width} "
            f"drawn read_ids={self._ids_text()} write_ids={self._write_ids_text()} "
            f"read_beats={self.read_beats} write_beats={self.write_beats} "
            f"burst_position={self.burst_position}"
        )

    def _ids_text(self) -> str:
        return "[" + ",".join(f"0x{i:x}" for i in self.read_ids) + "]"

    def _write_ids_text(self) -> str:
        return "[" + ",".join(f"0x{i:x}" for i in self.write_ids) + "]"

    async def _open_window(self, sb):
        dut = self.dut
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        # Route ext_in local addresses through the crossbar before opening the window.
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)
        await program_inbound0_window(jtag, 0, PASS_ALL_END, scoreboard=sb, tag="AXIIN_WIDE")
        return jtag

    async def _step_read_train(self, master, sb) -> None:
        """S1: a train of reads under the drawn distinct ARIDs, all in flight at once."""
        dut = self.dut

        read_depth = _AcceptedBeforeResponse(
            dut, dut.clk_smu_i, addr_channel="ar", resp_channel="r"
        )
        master.driver.set_timing(AxiTimingProfile(r_ready_delay=RESP_BACKPRESSURE_CYCLES))
        read_tasks = [
            cocotb.start_soon(
                master.read_bytes_result(
                    VERSION_LO,
                    4,
                    id=arid,
                    check_response=False,
                    timeout_ns=AXI_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            for arid in self.read_ids
        ]
        reads = [await task for task in read_tasks]
        reads_accepted = read_depth.finish()
        for idx, result in enumerate(reads):
            if result.timed_out:
                raise AssertionError(f"TIMEOUT s1 read {idx}: bound={AXI_TIMEOUT_NS}ns")
        if not read_depth.response_seen:
            raise AssertionError("s1 read train completed with no R handshake seen on the pins")
        sb.expect_true(
            f"CHK-AXIIN-DEPTH-RD port accepted {reads_accepted} of {OUTSTANDING} reads before "
            f"returning the first response (floor {MIN_ACCEPTED_BEFORE_RESPONSE}) "
            f"drawn read_ids={self._ids_text()} burst_position={self.burst_position}",
            reads_accepted >= MIN_ACCEPTED_BEFORE_RESPONSE,
            evidence="CHK-AXIIN-DEPTH",
        )
        resps = {resp_name(r.resp) for r in reads}
        words = {int(r.data) & 0xFFFF_FFFF for r in reads}
        sb.expect_eq(
            f"CHK-AXIIN-DEPTH-RD every concurrent read is OKAY drawn read_ids={self._ids_text()}",
            resps,
            {resp_name(RESP_OKAY)},
            evidence="CHK-AXIIN-DEPTH",
        )
        sb.expect_eq(
            "CHK-AXIIN-DEPTH-RD every concurrent read returns the reset value "
            f"drawn read_ids={self._ids_text()}",
            words,
            {VERSION_LO_RESET},
            evidence="CHK-AXIIN-DEPTH",
        )
        self._log(
            f"CHK-AXIIN-DEPTH: accepted before first response reads={reads_accepted} "
            f"of {OUTSTANDING} offered; drawn read_ids={self._ids_text()}"
        )

    async def _step_write_train(self, master, sb, awid: int, run: int) -> None:
        """S1: a train of writes under one pinned AWID, all in flight at once."""
        dut = self.dut
        write_depth = _AcceptedBeforeResponse(
            dut, dut.clk_smu_i, addr_channel="aw", resp_channel="b"
        )
        master.driver.set_timing(AxiTimingProfile(b_ready_delay=RESP_BACKPRESSURE_CYCLES))
        payloads = [
            (SCRATCH_PATTERN_BASE + (run << 16) + idx) & 0xFFFF_FFFF for idx in range(OUTSTANDING)
        ]
        write_tasks = [
            cocotb.start_soon(
                master.write_bytes_result(
                    SCRATCH_COLD,
                    value.to_bytes(4, byteorder="little"),
                    id=awid,
                    check_response=False,
                    timeout_ns=AXI_TIMEOUT_NS,
                    allow_timeout=True,
                )
            )
            for value in payloads
        ]
        writes = [await task for task in write_tasks]
        writes_accepted = write_depth.finish()
        for idx, result in enumerate(writes):
            if result.timed_out:
                raise AssertionError(f"TIMEOUT s1 write {idx}: bound={AXI_TIMEOUT_NS}ns")
        if not write_depth.response_seen:
            raise AssertionError("s1 write train completed with no B handshake seen on the pins")
        sb.expect_true(
            f"CHK-AXIIN-DEPTH-WR port accepted {writes_accepted} of {OUTSTANDING} writes before "
            f"returning the first response (floor {MIN_ACCEPTED_BEFORE_RESPONSE}) "
            f"drawn awid=0x{awid:x} burst_position={self.burst_position}",
            writes_accepted >= MIN_ACCEPTED_BEFORE_RESPONSE,
            evidence="CHK-AXIIN-DEPTH",
        )
        sb.expect_eq(
            f"CHK-AXIIN-DEPTH-WR every concurrent write is OKAY drawn awid=0x{awid:x}",
            {resp_name(w.resp) for w in writes},
            {resp_name(RESP_OKAY)},
            evidence="CHK-AXIIN-DEPTH",
        )
        master.driver.set_timing(AxiTimingProfile())
        await ClockCycles(dut.clk_smu_i, 32)
        settled = await master.read_bytes_result(
            SCRATCH_COLD, 4, check_response=False, timeout_ns=AXI_TIMEOUT_NS, allow_timeout=True
        )
        if settled.timed_out:
            raise AssertionError(f"TIMEOUT s1 scratch readback: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            f"CHK-AXIIN-DEPTH-WR settled scratch readback is OKAY drawn awid=0x{awid:x}",
            resp_name(settled.resp),
            resp_name(RESP_OKAY),
            evidence="CHK-AXIIN-DEPTH-ORDER",
        )
        sb.expect_eq(
            f"CHK-AXIIN-DEPTH-WR same-ID train leaves the last value written drawn awid=0x{awid:x}",
            int(settled.data) & 0xFFFF_FFFF,
            payloads[-1],
            evidence="CHK-AXIIN-DEPTH-ORDER",
        )
        self._log(
            f"CHK-AXIIN-DEPTH: accepted before first response writes={writes_accepted} "
            f"of {OUTSTANDING} offered under drawn awid=0x{awid:x}; "
            f"scratch=0x{int(settled.data) & 0xFFFF_FFFF:08x} last_written=0x{payloads[-1]:08x}"
        )

    async def _step_burst_type(self, master, sb) -> None:
        """S2: WRAP and multi-beat FIXED at a register target are refused; INCR is not."""
        drawn = f"drawn read_beats={self.read_beats} write_beats={self.write_beats}"
        incr_read = await master.burst_read_result(
            VERSION_LO,
            self.read_beats,
            size=BURST_SIZE,
            burst=AXI_BURST_INCR,
            check_response=False,
            timeout_ns=AXI_TIMEOUT_NS,
            allow_timeout=True,
        )
        incr_write = await master.burst_write_result(
            SCRATCH_COLD,
            [SCRATCH_PATTERN_BASE ^ (idx + 1) for idx in range(self.write_beats)],
            size=BURST_SIZE,
            burst=AXI_BURST_INCR,
            check_response=False,
            timeout_ns=AXI_TIMEOUT_NS,
            allow_timeout=True,
        )
        if incr_read.timed_out or incr_write.timed_out:
            raise AssertionError(f"TIMEOUT s2 INCR control: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            f"CHK-AXIIN-BURST INCR read and write of the same length and size are OKAY {drawn}",
            (resp_name(incr_read.resp), resp_name(incr_write.resp)),
            (resp_name(RESP_OKAY), resp_name(RESP_OKAY)),
            evidence="CHK-AXIIN-BURST",
        )
        wrap = await master.burst_read_result(
            VERSION_LO,
            self.read_beats,
            size=BURST_SIZE,
            burst=AXI_BURST_WRAP,
            check_response=False,
            timeout_ns=AXI_TIMEOUT_NS,
            allow_timeout=True,
        )
        if wrap.timed_out:
            raise AssertionError(f"TIMEOUT s2 wrap read: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            f"CHK-AXIIN-BURST-WRAP read refused with SLVERR drawn read_beats={self.read_beats}",
            resp_name(wrap.resp),
            resp_name(RESP_SLVERR),
            evidence="CHK-AXIIN-BURST",
        )

        fixed = await master.burst_write_result(
            SCRATCH_COLD,
            [SCRATCH_PATTERN_BASE ^ (idx + 1) for idx in range(self.write_beats)],
            size=BURST_SIZE,
            burst=AXI_BURST_FIXED,
            check_response=False,
            timeout_ns=AXI_TIMEOUT_NS,
            allow_timeout=True,
        )
        if fixed.timed_out:
            raise AssertionError(f"TIMEOUT s2 fixed write: bound={AXI_TIMEOUT_NS}ns")
        sb.expect_eq(
            "CHK-AXIIN-BURST-FIXED multi-beat write refused with SLVERR "
            f"drawn write_beats={self.write_beats}",
            resp_name(fixed.resp),
            resp_name(RESP_SLVERR),
            evidence="CHK-AXIIN-BURST-FIXED",
        )
        self._log(
            f"CHK-AXIIN-BURST: incr_read={resp_name(incr_read.resp)} "
            f"incr_write={resp_name(incr_write.resp)} wrap_read={resp_name(wrap.resp)} "
            f"fixed_write={resp_name(fixed.resp)} {drawn} "
            f"burst_position={self.burst_position}"
        )
        # The master takes the B beat on the edge after it rises; the cov/sv
        # monitors sample the handshake on the next edge, which the simulation
        # has to reach before the leaf ends.
        await ClockCycles(self.dut.clk_smu_i, 2)
        self.s2_ok = True

    async def _ax(self, master, *, write: bool, addr: int, payload, label: str, **attrs):
        event = (master.init_write if write else master.init_read)(addr, payload, **attrs)
        try:
            await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
        except Exception as exc:
            raise AssertionError(f"TIMEOUT {label} addr=0x{addr:x} attrs={attrs}: {exc}") from exc
        raw = event.data
        return worst_resp(getattr(raw, "resp", None)), bytes(getattr(raw, "data", b""))

    def _spm_walk(self) -> list[int]:
        """An SPM address with each free address bit set, and cleared from the one before."""
        addrs = []
        for bit in range(3, SPM_SIZE.bit_length()):
            addr = SPM_BASE | (1 << bit)
            if addr == SPM_BASE or addr >= SPM_BASE + SPM_SIZE:
                addr = (SPM_BASE + (1 << bit)) & ~((1 << bit) - 1)
            if SPM_BASE < addr < SPM_BASE + SPM_SIZE:
                addrs.append(addr)
        return addrs

    async def _step_spm(self, master, sb) -> None:
        """S3: sizes, offsets, address bits and burst types into the SPM."""
        bad = []
        cells = [(SPM_BASE + 0x100 + off, size) for size, off in SIZE_STEPS]
        cells += [(addr, 2) for addr in self._spm_walk()]
        for n, (addr, size) in enumerate(cells):
            nbytes = 1 << size
            word = bytes((0x3C + 7 * n + i) & 0xFF for i in range(nbytes))
            resp_w, _ = await self._ax(
                master, write=True, addr=addr, payload=word, size=size, label=f"spm_wr{n}"
            )
            resp_r, data = await self._ax(
                master, write=False, addr=addr, payload=nbytes, size=size, label=f"spm_rd{n}"
            )
            if (resp_w, resp_r, data[:nbytes]) != (RESP_OKAY, RESP_OKAY, word):
                bad.append((hex(addr), size, resp_name(resp_w), resp_name(resp_r), data.hex()))
        beats = bytes((0xA0 + i) & 0xFF for i in range(SPM_BURST_BEATS * 8))
        base = SPM_BASE + 0x400
        resp_w, _ = await self._ax(
            master, write=True, addr=base, payload=beats, size=3, label="incr_wr"
        )
        resp_r, data = await self._ax(
            master, write=False, addr=base, payload=len(beats), size=3, label="incr_rd"
        )
        if (resp_w, resp_r, data) != (RESP_OKAY, RESP_OKAY, beats):
            bad.append(("INCR", resp_name(resp_w), resp_name(resp_r)))
        wrap_resp, _ = await self._ax(
            master,
            write=True,
            addr=base,
            payload=beats[:32],
            size=3,
            burst=AXI_BURST_WRAP,
            label="wrap_wr",
        )
        incr_resp, _ = await self._ax(
            master, write=True, addr=base, payload=beats[:8], size=3, label="incr_after_wrap"
        )
        if incr_resp != RESP_OKAY:
            bad.append(("INCR after WRAP", resp_name(incr_resp)))
        self._log(
            f"CHK-AXIIN-SPM-SWEEP cells={len(cells)} wrap={resp_name(wrap_resp)} mismatches={bad}"
        )
        sb.expect_eq("CHK-AXIIN-SPM-SWEEP", bad, [], evidence="CHK-AXIIN-SPM-SWEEP")
        self.s3_ok = True

    async def run(self) -> None:
        dut = self.dut
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, 16)

        self._draw()
        await self._open_window(sb)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        await await_smn_resp(
            master, VERSION_LO, RESP_OKAY, clk=dut.clk_smu_i, label="axiin_window_ready"
        )

        if self.burst_position == "before_reads":
            await self._step_burst_type(master, sb)
        await self._step_read_train(master, sb)
        if self.burst_position == "between_trains":
            await self._step_burst_type(master, sb)
        for run, awid in enumerate(self.write_ids):
            await self._step_write_train(master, sb, awid, run)
        self.s1_ok = True
        if self.burst_position == "after_writes":
            await self._step_burst_type(master, sb)
        await self._step_spm(master, sb)
