# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_CPU_CTRL read-only, locked and inert registers, and the scratch bank write shapes.

RAND-REP, no_cpu on ``lsu_stub_all_live`` with ``+skip_fuse_sense``. Every
access goes through the CPU-LSU master on ``s_axi`` with full strobes on the
64-bit lane or on one 32-bit half. The seed draws the values, the lanes, the
write order, the scratch event sequence, the index permutations and the write
shapes. The event kinds and both shapes of each bank run in every leaf.

Contract (``hw/sys/sep/regs/gen/adoc/blocks/sep_cpu_ctrl.adoc``,
``hw/sys/sep/regs/gen/adoc/blocks/sep_scratch.adoc``,
``hw/sys/sep/doc/cpu.adoc`` Dual Scratch Register Banks):

* ``SEP_VERSION_ID.version_id`` (R) reads its reset value 0xDEADBEEF after
  every write.
* After ``SEP_NMI_VEC_LOCK.lock`` (RW1S) is 1, a ``SEP_NMI_VEC`` write does not
  change ``nmi_vec`` (bits 31:1), and a write of 0 or all-ones to the lock
  leaves it at 1.
* ``SEP_FUSE_SENSE_STATUS`` and ``SMC_FUSE_SENSE_STATUS`` (R) ignore a write
  of the complement of bit 0. Every access, the ``TIMEOUT_CLEAR`` and
  ``TIMEOUT_MODE`` writes included, gets a response.
* Each scratch register stores the low word of every write, for every write
  order and shape. Bits 63:32 have no field.

Expected values come from the register description (the generated register
metadata) and from a write model, never from a DUT read. Reserved bits with
no stated read value are logged as ``OBS-CC-RSVD`` and not graded.

Checkers:
  CHK-CC-RO       ``SEP_VERSION_ID[31:0]`` after each of the 8 writes.
  CHK-NMI-LOCK    ``SEP_NMI_VEC[31:1]`` after each of the 8 locked writes, and
                  ``lock`` after each of the 4 lock writes.
  CHK-CC-INERT    bit 0 of both sense status registers after the complement
                  write; every write response, the timeout registers included.
  CHK-SCR-SHAPE   the low word of each written scratch register (64-bit
                  readback, and ``scratch_cold_probe_o`` for the cold bank).
Controls (not counted): CTL-NMI-DEFAULT, CTL-NMI-STORE, CTL-SCR-SEQ,
CTL-SCR-NEIGHBOUR. Observations: OBS-CC-RSVD, OBS-TIMEOUT.

The graded window (owner code of this test) is open around the graded
writes and their readbacks only. The first reads, the writes before the lock,
the neighbour reads and the reset events run with the window closed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, RegBlock
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_scratch_reset_seq import SCRATCH_COLD_ADDRS, SCRATCH_N, SCRATCH_WARM_ADDRS

TEST = "sep_cpu_ctrl_reg_shape_test"
M64 = 0xFFFF_FFFF_FFFF_FFFF
M32 = 0xFFFF_FFFF

VERSION_ID = SEP_CPU_CTRL.addr("SEP_VERSION_ID")
VERSION_FIELD = SEP_CPU_CTRL.field_mask("SEP_VERSION_ID", "version_id")
VERSION_RESET = SEP_CPU_CTRL.reset("SEP_VERSION_ID") & VERSION_FIELD
NMI_VEC = SEP_CPU_CTRL.addr("SEP_NMI_VEC")
NMI_FIELD = SEP_CPU_CTRL.field_mask("SEP_NMI_VEC", "nmi_vec")
NMI_RSVD0 = SEP_CPU_CTRL.field_mask("SEP_NMI_VEC", "rsvd")
NMI_RESET = SEP_CPU_CTRL.reset("SEP_NMI_VEC")
NMI_LOCK = SEP_CPU_CTRL.addr("SEP_NMI_VEC_LOCK")
LOCK_FIELD = SEP_CPU_CTRL.field_mask("SEP_NMI_VEC_LOCK", "lock")
TIMEOUT_CLEAR = SEP_CPU_CTRL.addr("TIMEOUT_CLEAR")
TIMEOUT_MODE = SEP_CPU_CTRL.addr("TIMEOUT_MODE")
TIMEOUT_INTERRUPT = SEP_CPU_CTRL.addr("TIMEOUT_INTERRUPT")
SENSE_REGS = {
    "SEP_FUSE_SENSE_STATUS": (
        SEP_CPU_CTRL.addr("SEP_FUSE_SENSE_STATUS"),
        SEP_CPU_CTRL.field_mask("SEP_FUSE_SENSE_STATUS", "sep_fuse_sense_done"),
    ),
    "SMC_FUSE_SENSE_STATUS": (
        SEP_CPU_CTRL.addr("SMC_FUSE_SENSE_STATUS"),
        SEP_CPU_CTRL.field_mask("SMC_FUSE_SENSE_STATUS", "smc_fuse_sense_done"),
    ),
}
SCR_META = RegBlock("SEP_SCRATCH_COLD")
SCR_FIELD = SCR_META.field_mask("SCRATCH_0_", "data")
SCR_RESET = SCR_META.reset("SCRATCH_0_") & SCR_FIELD
BANKS = {"cold": SCRATCH_COLD_ADDRS, "warm": SCRATCH_WARM_ADDRS}

N_WRITES = 8  # writes per register class (fixed by the entry)
LANES = ("64", "lo", "hi")
# The lanes that reach bit 0 of a register (a high-half write carries no field bit).
LOW_LANES = ("64", "lo")
# Bounded waits (environment choices, logged).
RESET_BOUND = 2_000  # clk_i cycles for a reset tap to read 1 after a pulse
PULSE_CYCLES = 16  # low width of a wdt_rst_ni or rst_ni pulse
STATUS_GAP = 64  # idle gap between the two baseline status reads


def _lane_value(value: int, lane: str) -> int:
    """The 64-bit image a lane write puts on the register (other bits untouched)."""
    if lane == "64":
        return value & M64
    if lane == "lo":
        return value & M32
    return value & (M32 << 32)


class _Cfg:
    """Seed-drawn configuration of the leaf (single source of truth)."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed

        def rand64() -> int:
            return rng.getrandbits(64)

        # SEP_VERSION_ID: 8 values, one of them all-ones, at a drawn position. At
        # least 4 writes, the all-ones write among them, use a lane that reaches the
        # version_id field (64-bit lane or low half).
        vals = [rand64() for _ in range(N_WRITES)]
        ones = rng.randrange(N_WRITES)
        vals[ones] = M64
        others = [i for i in range(N_WRITES) if i != ones]
        rng.shuffle(others)
        low = {ones, *others[:3]}
        self.ver = [
            (v, rng.choice(LOW_LANES) if i in low else rng.choice(LANES))
            for i, v in enumerate(vals)
        ]

        # SEP_NMI_VEC before the lock: bit 0 set in at least 4 writes and bits
        # 63:32 non-zero in at least 4.
        idx = list(range(N_WRITES))
        rng.shuffle(idx)
        bit0 = set(idx[:4])
        rng.shuffle(idx)
        upper = set(idx[:4])
        pre = []
        for i in range(N_WRITES):
            v = rng.getrandbits(32) & ~1
            if i in bit0:
                v |= 1
            hi = rng.randrange(1, 1 << 32) if i in upper else 0
            pre.append(((hi << 32) | v, rng.choice(LANES)))
        self.nmi_pre = pre

        # SEP_NMI_VEC after the lock: at least 4 writes on the 64-bit lane or the
        # low half; bits 63:32 non-zero in at least 4. The low word is drawn
        # against the stored vector when the leaf runs, so it always differs in
        # bits 31:1 (``nmi_post_lo``).
        rng.shuffle(idx)
        low_lane = set(idx[:4])
        rng.shuffle(idx)
        upper = set(idx[:4])
        self.nmi_post = []
        for i in range(N_WRITES):
            lane = rng.choice(LOW_LANES) if i in low_lane else rng.choice(LANES)
            hi = rng.randrange(1, 1 << 32) if i in upper else rng.getrandbits(32)
            self.nmi_post.append((hi, rng.getrandbits(32), lane))

        # Lock writes: 0 three times and all-ones once, in a drawn order. A lane
        # that reaches bit 0 is drawn, so every lock write reaches the field.
        kinds = [0, 0, 0, M64]
        rng.shuffle(kinds)
        self.lock_writes = [(k, rng.choice(LOW_LANES)) for k in kinds]

        # TIMEOUT_CLEAR / TIMEOUT_MODE: 8 values each, one all-ones.
        self.timeout = {}
        for name in ("TIMEOUT_CLEAR", "TIMEOUT_MODE"):
            vals = [rand64() for _ in range(N_WRITES)]
            vals[rng.randrange(N_WRITES)] = M64
            self.timeout[name] = [(v, rng.choice(LANES)) for v in vals]

        # Status registers: random upper bits of the complement write and a
        # lane that reaches bit 0.
        self.sense_upper = {n: rng.getrandbits(63) << 1 for n in SENSE_REGS}
        self.sense_lane = {n: rng.choice(LOW_LANES) for n in SENSE_REGS}

        # Scratch event sequence.
        self.events = self._draw_events(rng)
        self.perm: list[list[int]] = []
        self.shape: list[str] = []
        self.half_order: list[str] = []
        used: set[int] = set()
        self.values: list[list[tuple[int, int]]] = []
        shapes_seen = {"cold": set(), "warm": set()}
        bank_events = [e for e in self.events if e != "WDT_PULSE" and e != "COLD"]
        # Both shapes for each bank: the first two writes of a bank take the
        # two shapes in a drawn order; later writes draw a shape.
        first_two: dict[str, list[str]] = {}
        for b in ("cold", "warm"):
            pair = ["64", "2x32"]
            rng.shuffle(pair)
            first_two[b] = pair
        n_by_bank = {"cold": 0, "warm": 0}
        for ev in self.events:
            if ev in ("WDT_PULSE", "COLD"):
                self.perm.append([])
                self.shape.append("")
                self.half_order.append("")
                self.values.append([])
                continue
            b = ev.split(":")[1]
            k = n_by_bank[b]
            n_by_bank[b] += 1
            shape = first_two[b][k] if k < 2 else rng.choice(("64", "2x32"))
            shapes_seen[b].add(shape)
            perm = list(range(SCRATCH_N))
            rng.shuffle(perm)
            vals = []
            for _ in range(SCRATCH_N):
                while True:
                    lo = rng.randrange(1, 1 << 32)
                    if lo not in used:
                        used.add(lo)
                        break
                vals.append((lo, rng.randrange(1, 1 << 32)))
            self.perm.append(perm)
            self.shape.append(shape)
            self.half_order.append(rng.choice(("lo_first", "hi_first")))
            self.values.append(vals)
        assert all(s == {"64", "2x32"} for s in shapes_seen.values()), shapes_seen
        assert len(bank_events) >= 4

    @staticmethod
    def _draw_events(rng: SepSeededRng) -> list[str]:
        """4 to 10 events: at least one WDT_PULSE and one COLD, each after a
        write to both banks since the previous reset event, and at least two
        WRITE_BANK events for each bank."""
        while True:
            n = rng.randrange(4, 11)
            seq: list[str] = []
            for _ in range(n):
                seq.append(rng.choice(("WRITE_BANK:cold", "WRITE_BANK:warm", "WDT_PULSE", "COLD")))
            if "WDT_PULSE" not in seq or "COLD" not in seq:
                continue
            if sum(e == "WRITE_BANK:cold" for e in seq) < 2:
                continue
            if sum(e == "WRITE_BANK:warm" for e in seq) < 2:
                continue
            ok = True
            since: set[str] = set()
            for e in seq:
                if e.startswith("WRITE_BANK"):
                    since.add(e)
                elif since != {"WRITE_BANK:cold", "WRITE_BANK:warm"}:
                    ok = False
                    break
                else:
                    since = set()
            if ok:
                return seq


@pyuvm.test()
class sep_cpu_ctrl_reg_shape_test(sep_base_test):
    """SEP_CPU_CTRL read-only, locked and inert registers; scratch write shapes."""

    required_evidence = ("CHK-CC-RO", "CHK-NMI-LOCK", "CHK-CC-INERT", "CHK-SCR-SHAPE")

    # -- access primitives --------------------------------------------------

    async def _write(self, addr: int, value: int, lane: str, *, tolerant: bool) -> int:
        """One full-strobe write on ``lane``. Returns the response code.

        ``tolerant`` accepts any response code (the code of a write to a
        read-only register or a reserved field is not stated); the arrival of
        the response is the only scored outcome. A missing response fails at
        the AXI response timeout of the agent.
        """
        if lane == "64":
            a, data, n, size = addr, value & M64, 8, 3
        elif lane == "lo":
            a, data, n, size = addr, value & M32, 4, 2
        else:
            a, data, n, size = addr + 4, (value >> 32) & M32, 4, 2
        seq = SepAxiAccessSeq(
            "ccshape_wr",
            op=SepAxiOp.WRITE,
            addr=a,
            wdata=data,
            length=n,
            size=size,
            allow_unverified_write_resp=tolerant,
        )
        await self.start_seq(seq)
        if seq.timed_out:
            raise AssertionError(f"write @0x{a:08x} lane={lane} got no response")
        if not tolerant and not seq.resp_ok:
            raise AssertionError(f"write @0x{a:08x} lane={lane} resp={seq.resp_code}")
        self.responses += 1
        return seq.resp_code

    async def _read64(self, addr: int) -> int:
        seq = SepAxiAccessSeq("ccshape_rd", op=SepAxiOp.READ, addr=addr, length=8, size=3)
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"64-bit read @0x{addr:08x} resp={seq.resp_code}")
        return seq.rdata & M64

    def _rsvd(self, name: str, got: int, field_mask: int) -> None:
        self.logger.info(
            "OBS-CC-RSVD: reg=%s reserved=0x%x mask=0x%x",
            name,
            got & ~field_mask & M64,
            ~field_mask & M64,
        )

    # -- CPU control leg ----------------------------------------------------

    async def _version_id(self) -> None:
        cfg = self.tcfg
        first = await self._read64(VERSION_ID)
        fc = field_compare(first, VERSION_RESET, VERSION_FIELD)
        assert fc.ok, f"CHK-CC-RO FAIL: first read before any write {fc.fields()}"
        self.logger.info("CTL-CC-RO-FIRST: SEP_VERSION_ID %s", fc.fields())
        open_graded_window(TEST, self.logger)
        for i, (v, lane) in enumerate(cfg.ver):
            resp = await self._write(VERSION_ID, v, lane, tolerant=True)
            got = await self._read64(VERSION_ID)
            fc = field_compare(got, VERSION_RESET, VERSION_FIELD)
            line = f"write={i} lane={lane} wdata=0x{v:016x} resp={resp} {fc.fields()}"
            assert fc.ok, f"CHK-CC-RO FAIL: {line}"
            self.logger.info("CC-RO LOG: %s", line)
            self._rsvd("SEP_VERSION_ID", got, VERSION_FIELD)
        close_graded_window(self.logger)
        n_low = sum(1 for _v, lane in cfg.ver if lane in LOW_LANES)
        ones_low = any(v == M64 and lane in LOW_LANES for v, lane in cfg.ver)
        assert n_low >= 4 and ones_low, (
            f"CHK-CC-RO FAIL: {n_low} writes reach the field (all-ones on a field lane: "
            f"{ones_low}); at least 4 and the all-ones write are needed"
        )
        self.logger.info(
            "CHK-CC-RO PASS: SEP_VERSION_ID[31:0]=0x%08x after %d writes field_lane_writes=%d",
            VERSION_RESET,
            len(cfg.ver),
            n_low,
        )

    async def _nmi(self) -> None:
        cfg = self.tcfg
        # Step 3: first read (control; the reset value stays with the open owners).
        first = await self._read64(NMI_VEC)
        fc = field_compare(first, NMI_RESET, NMI_FIELD | NMI_RSVD0)
        assert fc.ok, f"CTL-NMI-DEFAULT FAIL: {fc.fields()}"
        self.logger.info("CTL-NMI-DEFAULT: first_read=0x%016x %s", first, fc.fields())
        model = NMI_RESET & NMI_FIELD

        # Step 4: writes before the lock (control CTL-NMI-STORE).
        for i, (v, lane) in enumerate(cfg.nmi_pre):
            await self._write(NMI_VEC, v, lane, tolerant=False)
            if lane != "hi":
                model = v & NMI_FIELD
            got = await self._read64(NMI_VEC)
            fc = field_compare(got, model, NMI_FIELD | NMI_RSVD0)
            line = f"write={i} lane={lane} wdata=0x{v:016x} {fc.fields()}"
            assert fc.ok, f"CTL-NMI-STORE FAIL: {line}"
            self.logger.info("NMI-STORE LOG: %s", line)
            self._rsvd("SEP_NMI_VEC", got, NMI_FIELD | NMI_RSVD0)
        self.logger.info(
            "CTL-NMI-STORE: writes=%d bit0=0 bits31:1_exact model=0x%08x",
            len(cfg.nmi_pre),
            model,
        )

        # Step 5: lock (control: the readback shows both values).
        lk0 = await self._read64(NMI_LOCK)
        fc0 = field_compare(lk0, 0, LOCK_FIELD)
        assert fc0.ok, f"CHK-NMI-LOCK FAIL: lock before the set {fc0.fields()}"
        await self._write(NMI_LOCK, 1, "64", tolerant=False)
        lk1 = await self._read64(NMI_LOCK)
        fc1 = field_compare(lk1, LOCK_FIELD, LOCK_FIELD)
        assert fc1.ok, f"CHK-NMI-LOCK FAIL: lock after the write of 1 {fc1.fields()}"
        self.logger.info("CTL-NMI-LOCK-SET: before=%d after=%d", lk0 & 1, lk1 & 1)

        # Step 6: writes after the lock.
        open_graded_window(TEST, self.logger)
        vec = model
        for i, (hi, lo_raw, lane) in enumerate(cfg.nmi_post):
            # Low word differs from the stored vector in bits 31:1.
            lo = lo_raw & M32
            if (lo & NMI_FIELD) == vec:
                lo ^= 0x2
            v = (hi << 32) | lo
            assert lane == "hi" or (v & NMI_FIELD) != vec
            resp = await self._write(NMI_VEC, v, lane, tolerant=True)
            got = await self._read64(NMI_VEC)
            fc = field_compare(got, vec, NMI_FIELD)
            line = f"write={i} lane={lane} wdata=0x{v:016x} resp={resp} {fc.fields()}"
            assert fc.ok, f"CHK-NMI-LOCK FAIL: locked vector write changed nmi_vec: {line}"
            self.logger.info("NMI-LOCK LOG: %s", line)
            self._rsvd("SEP_NMI_VEC", got, NMI_FIELD)

        # Step 7: lock write cases.
        n0 = n1 = 0
        for k, lane in cfg.lock_writes:
            resp = await self._write(NMI_LOCK, k, lane, tolerant=True)
            got = await self._read64(NMI_LOCK)
            fc = field_compare(got, LOCK_FIELD, LOCK_FIELD)
            line = f"wdata=0x{k:x} lane={lane} resp={resp} {fc.fields()}"
            assert fc.ok, f"CHK-NMI-LOCK FAIL: lock cleared by a write: {line}"
            self.logger.info("NMI-LOCK LOG: %s", line)
            self._rsvd("SEP_NMI_VEC_LOCK", got, LOCK_FIELD)
            n0 += int(k == 0)
            n1 += int(k == M64)
        close_graded_window(self.logger)
        self.logger.info(
            "CHK-NMI-LOCK PASS: locked_writes=%d vec=0x%08x unchanged lock write-0 x%d and "
            "all-ones x%d stay 1",
            len(cfg.nmi_post),
            vec,
            n0,
            n1,
        )

    async def _timeout_and_status(self) -> None:
        cfg = self.tcfg
        n_before = self.responses
        open_graded_window(TEST, self.logger)
        for name, addr in (("TIMEOUT_CLEAR", TIMEOUT_CLEAR), ("TIMEOUT_MODE", TIMEOUT_MODE)):
            for v, lane in cfg.timeout[name]:
                resp = await self._write(addr, v, lane, tolerant=True)
                self.logger.info(
                    "CC-INERT LOG: reg=%s wdata=0x%016x lane=%s resp=%d", name, v, lane, resp
                )
        close_graded_window(self.logger)
        n_timeout = self.responses - n_before
        assert n_timeout == 2 * N_WRITES, (
            f"CHK-CC-INERT FAIL: timeout writes responses={n_timeout}/{2 * N_WRITES}"
        )
        ti = await self._read64(TIMEOUT_INTERRUPT)
        self.logger.info(
            "OBS-TIMEOUT: timeout_interrupt=0x%x after TIMEOUT_CLEAR and TIMEOUT_MODE writes", ti
        )

        # Step 9: status registers.
        base: dict[str, int] = {}
        for name, (addr, field) in SENSE_REGS.items():
            r1 = await self._read64(addr)
            await ClockCycles(cocotb.top.clk_i, STATUS_GAP)
            r2 = await self._read64(addr)
            assert (r1 & field) == (r2 & field), (
                f"CHK-CC-INERT FAIL: precondition, {name} bit 0 changed between the baseline "
                f"reads (0x{r1:x} -> 0x{r2:x}); a changing input cannot show an inert write"
            )
            base[name] = r2 & field
            self.logger.info("CTL-CC-INERT-BASE: reg=%s reads=0x%x,0x%x", name, r1, r2)
        n_status = 0
        after: dict[str, int] = {}
        open_graded_window(TEST, self.logger)
        for name, (addr, field) in SENSE_REGS.items():
            v = cfg.sense_upper[name] | ((~base[name]) & field)
            lane = cfg.sense_lane[name]
            n0 = self.responses
            resp = await self._write(addr, v, lane, tolerant=True)
            n_status += self.responses - n0
            got = await self._read64(addr)
            fc = field_compare(got, base[name], field)
            line = f"reg={name} wdata=0x{v:016x} lane={lane} resp={resp} {fc.fields()}"
            assert fc.ok, f"CHK-CC-INERT FAIL: read-only bit changed by a write: {line}"
            self.logger.info("CC-INERT LOG: %s", line)
            self._rsvd(name, got, field)
            after[name] = got & field
        close_graded_window(self.logger)
        total = n_timeout + n_status
        self.logger.info(
            "CHK-CC-INERT PASS: sep_sense=%d smc_sense=%d unchanged responses=%d/%d",
            after["SEP_FUSE_SENSE_STATUS"],
            after["SMC_FUSE_SENSE_STATUS"],
            total,
            2 * N_WRITES + len(SENSE_REGS),
        )

    # -- scratch leg ----------------------------------------------------------

    def _all_regs(self) -> list[tuple[str, int, int]]:
        return [(b, i, BANKS[b][i]) for b in ("cold", "warm") for i in range(SCRATCH_N)]

    async def _read_all(self) -> dict[tuple[str, int], int]:
        return {(b, i): await self._read64(a) for b, i, a in self._all_regs()}

    async def _write_scratch(self, addr: int, lo: int, hi: int, shape: str, order: str) -> None:
        v = (hi << 32) | lo
        if shape == "64":
            await self._write(addr, v, "64", tolerant=False)
        else:
            lanes = ("lo", "hi") if order == "lo_first" else ("hi", "lo")
            for lane in lanes:
                await self._write(addr, v, lane, tolerant=False)

    def _probe_cold(self, i: int) -> int:
        return self.rd(cocotb.top.scratch_cold_probe_o, M32 << (32 * i)) >> (32 * i)

    async def _write_bank(self, step: int) -> None:
        cfg = self.tcfg
        bank = cfg.events[step].split(":")[1]
        perm, shape, order = cfg.perm[step], cfg.shape[step], cfg.half_order[step]
        for j, i in enumerate(perm):
            lo, hi = cfg.values[step][j]
            addr = BANKS[bank][i]
            open_graded_window(TEST, self.logger)
            await self._write_scratch(addr, lo, hi, shape, order)
            got = await self._read64(addr)
            close_graded_window(self.logger)
            fc = field_compare(got, lo, SCR_FIELD)
            probe = None
            if bank == "cold":
                await RisingEdge(cocotb.top.clk_i)
                await ReadOnly()
                probe = self._probe_cold(i)
                await RisingEdge(cocotb.top.clk_i)
            line = (
                f"bank={bank} index={i} order={perm} shape={shape}"
                f"{'' if shape == '64' else '(' + order + ')'} low_word=0x{got & SCR_FIELD:08x} "
                f"upper32_written=0x{hi:08x} {fc.fields()}"
                + ("" if probe is None else f" cold_probe=0x{probe:08x}")
            )
            assert fc.ok, f"CHK-SCR-SHAPE FAIL: {line}"
            assert probe is None or probe == lo, f"CHK-SCR-SHAPE FAIL: cold probe {line}"
            self.logger.info(
                "OBS-CC-RSVD: reg=SCRATCH_%s_%d reserved=0x%x mask=0x%x",
                bank.upper(),
                i,
                got & ~SCR_FIELD & M64,
                ~SCR_FIELD & M64,
            )
            # Neighbour compare (control) against the snapshot.
            same = 0
            for b2, i2, a2 in self._all_regs():
                if (b2, i2) == (bank, i):
                    continue
                r = await self._read64(a2)
                exp = self.snapshot[(b2, i2)]
                assert (r & SCR_FIELD) == exp, (
                    f"CTL-SCR-NEIGHBOUR FAIL: write bank={bank} index={i} changed "
                    f"bank={b2} index={i2}: 0x{r & SCR_FIELD:08x} != 0x{exp:08x}"
                )
                same += 1
            self.logger.info(
                "CTL-SCR-NEIGHBOUR: bank=%s index=%d neighbours_unchanged=%d/%d",
                bank,
                i,
                same,
                2 * SCRATCH_N - 1,
            )
            self.logger.info("CHK-SCR-SHAPE PASS: %s", line)
            self.scr_shape_lines += 1
            self.snapshot[(bank, i)] = lo

    async def _wait_high(self, sig, name: str) -> int:
        for n in range(1, RESET_BOUND + 1):
            await RisingEdge(cocotb.top.clk_i)
            await ReadOnly()
            if self.rd(sig, allow_unknown=True):
                await RisingEdge(cocotb.top.clk_i)
                return n
        raise AssertionError(f"{name} did not read 1 within {RESET_BOUND} clk_i cycles")

    async def _reset_event(self, step: int) -> None:
        cfg = self.tcfg
        ev = cfg.events[step]
        dut = cocotb.top
        before = dict(self.snapshot)
        if ev == "WDT_PULSE":
            await RisingEdge(dut.clk_i)
            dut.wdt_rst_ni_i.value = 0
            await ClockCycles(dut.clk_i, PULSE_CYCLES)
            dut.wdt_rst_ni_i.value = 1
            n = await self._wait_high(dut.sep_cpu_reset_n_o, "sep_cpu_reset_n_o")
            self.logger.info("WDT_PULSE: low=%d sep_cpu_reset_n_o high after %d", PULSE_CYCLES, n)
        else:
            await self.pulse_rst_ni(hold_cycles=PULSE_CYCLES, release_bound=RESET_BOUND)
        rb = await self._read_all()
        cls = {}
        for b in ("cold", "warm"):
            cleared = all((rb[(b, i)] & SCR_FIELD) == SCR_RESET for i in range(SCRATCH_N))
            retained = all((rb[(b, i)] & SCR_FIELD) == before[(b, i)] for i in range(SCRATCH_N))
            cls[b] = "cleared" if cleared else ("retained" if retained else "mixed")
        self.logger.info(
            "CTL-SCR-SEQ: step=%d event=%s warm=%s cold=%s", step, ev, cls["warm"], cls["cold"]
        )
        self.snapshot = {k: v & SCR_FIELD for k, v in rb.items()}

    async def _scratch(self) -> None:
        cfg = self.tcfg
        rb = await self._read_all()
        self.snapshot = {k: v & SCR_FIELD for k, v in rb.items()}
        self.logger.info(
            "SCR-SNAPSHOT LOG: %s",
            " ".join(f"{b}[{i}]=0x{v:08x}" for (b, i), v in self.snapshot.items()),
        )
        for step, ev in enumerate(cfg.events):
            if ev.startswith("WRITE_BANK"):
                await self._write_bank(step)
            else:
                await self._reset_event(step)

    # -- leaf -----------------------------------------------------------------

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        self.tcfg = cfg = _Cfg(seed)
        self.responses = 0
        self.scr_shape_lines = 0
        self.logger.info("DRAW ver=%s", " ".join(f"0x{v:016x}/{lane}" for v, lane in cfg.ver))
        self.logger.info(
            "DRAW nmi_pre=%s", " ".join(f"0x{v:016x}/{lane}" for v, lane in cfg.nmi_pre)
        )
        self.logger.info(
            "DRAW nmi_post=%s",
            " ".join(f"hi=0x{h:08x}/lo=0x{lo:08x}/{lane}" for h, lo, lane in cfg.nmi_post),
        )
        self.logger.info(
            "DRAW lock_writes=%s", " ".join(f"0x{k:x}/{lane}" for k, lane in cfg.lock_writes)
        )
        for name, vals in cfg.timeout.items():
            self.logger.info("DRAW %s=%s", name, " ".join(f"0x{v:016x}/{lane}" for v, lane in vals))
        self.logger.info(
            "DRAW sense_upper=%s sense_lane=%s",
            {k: hex(v) for k, v in cfg.sense_upper.items()},
            cfg.sense_lane,
        )
        self.logger.info("DRAW events=%s", ",".join(cfg.events))
        for step, ev in enumerate(cfg.events):
            if ev.startswith("WRITE_BANK"):
                self.logger.info(
                    "DRAW step=%d %s perm=%s shape=%s half_order=%s values=%s",
                    step,
                    ev,
                    cfg.perm[step],
                    cfg.shape[step],
                    cfg.half_order[step],
                    " ".join(f"0x{h:08x}_{lo:08x}" for lo, h in cfg.values[step]),
                )
        self.logger.info(
            "CC-SHAPE env: reset_bound=%d clk_i pulse=%d status_gap=%d",
            RESET_BOUND,
            PULSE_CYCLES,
            STATUS_GAP,
        )

        await self.bring_up_no_cpu()
        dut = cocotb.top
        await self._wait_high(dut.dbg_sep_reset_n_o, "dbg_sep_reset_n_o")

        await self._version_id()
        await self._nmi()
        await self._timeout_and_status()
        await self._scratch()
        close_graded_window(self.logger)

        n_scr = sum(1 for e in cfg.events if e.startswith("WRITE_BANK")) * SCRATCH_N
        assert self.scr_shape_lines == n_scr, (
            f"CHK-SCR-SHAPE FAIL: {self.scr_shape_lines} register checks, expected {n_scr}"
        )
        self.result_pass(TEST, seed, 4)
