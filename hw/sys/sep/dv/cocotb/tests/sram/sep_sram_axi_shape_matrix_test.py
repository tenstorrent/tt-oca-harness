# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP SRAM burst shapes, outstanding depth, refused burst types and a cold reset in flight.

The 256 KiB scratch SRAM at 0x1000_0000 serves INCR bursts of every length and
single-beat bursts of every type (``hw/sys/sep/doc/fabric.adoc``, Top Level
AXI4). A multi-beat FIXED or WRAP burst from the inbound master is refused: the
write ends with SLVERR and leaves SRAM unchanged, and every read beat returns
SLVERR (``hw/sys/sep/doc/fabric.adoc``, lines 62-65). A cold reset that lands
with an SRAM access outstanding leaves the interface usable: the SRAM interface
is reset by ``sep_reset_n``, which follows ``rst_ni``
(``hw/sys/sep/doc/reset_controller.adoc``, SEP Reset Controller).

Run mode: RAND-REP, no_cpu on ``lsu_stub_all_live`` with ``+skip_fuse_sense``
and ``ext_boot_seq_done_i`` at 1, so ``rst_ni`` is the only open term of the
reset-in-flight leg. Masters: the CPU-LSU master on ``s_axi`` and the inbound
master on ``m_axi``. Every multi-beat burst comes from the inbound master. The
byte model holds only written bytes, and every read covers written bytes only
(Verilator is two-state).

Checkers:
  CHK-SRAM-OUTSTANDING  INCR bursts of lengths 1, 2, 7 and 16 in one 4 KiB page,
                        reads and writes interleaved with 1 to 4 outstanding:
                        every read beat returns the byte-model bytes of its
                        address with the ID of its request, every B beat
                        carries the ID of its write, and the peak count of
                        outstanding requests on ``m_axi`` equals the drawn
                        depth (``m_axi`` channel monitor).
  CHK-SRAM-REFUSE       FIXED bursts of lengths 2, 3, 8 and 16 and WRAP bursts of
                        lengths 2, 8 and 16 from the inbound master: the write
                        ends SLVERR and the words read back unchanged, and the
                        read of the same shape returns SLVERR on each of its
                        beats. Control: an INCR burst and a single-beat FIXED
                        burst with the same ID write and read back first.
  CHK-SRAM-SINGLE       a single-beat FIXED burst and a single-beat WRAP burst
                        (AxLEN = 0, error injection) on both masters answer OKAY
                        and the data lands.
  CHK-SRAM-OTF          a CPU-LSU read and write each take ``rst_ni`` at a drawn
                        offset inside the response window; after the release a
                        write reads back with OKAY and no beat with the
                        abandoned ID appears on ``s_axi``.
  CHK-SRAM-OTF-REPLAY   the PR-SRAM request tap shows no request at the
                        abandoned address between the reset and the post-reset
                        write; the post-reset write and the readback response
                        show on the tap.
Controls (not counted): CTL-SRAM-FILTER (inbound filter entry readback),
CTL-SRAM-REACH (both masters write and read back the first and last word, each
of the 15 word-address bits and 128 drawn words).

Environment choices (logged): the per-access completion bound, the bound of the
waits on ``dbg_sep_reset_n_o``, and the quiet wait for a stale beat. The
response window W of a path counts the ``clk_i`` cycles from the edge that
transfers the request (AR, or the later of AW and W) to the edge that presents
the R or B beat; the reset falls half a cycle after edge ``o`` of that window,
with o = floor(``u_o`` * W).

The single-beat WRAP burst is an AXI4 length the bench checker of each master
rejects; the testlist passes ``+sep_axi_wrap_len1_inject``, with which that
checker reads such a request as a single-beat INCR burst and checks the rest
(``docs/SEP_TB_ARCH.adoc``, inject exceptions).

``ocah_axi_vip`` places the write beats of a burst on incrementing byte lanes.
That is the AXI4 lane rule for an INCR burst and for a WRAP burst whose window is
8 bytes or more, and not for a narrow FIXED burst or a WRAP window under 8
bytes. The refused write bursts therefore draw their size from the legal set of
their shape (FIXED: 8 bytes; WRAP of 2 beats: 4 or 8 bytes); the refused read
bursts draw from all four sizes. ``PR-SRAM`` carries the byte offset of the
request from the SRAM base ``SEP_SRAM_MEM_BASE_ADDR`` (``docs/SEP_TB_ARCH.adoc``,
PR-SRAM entry); the leaf compares it at 8-byte word granularity.

The graded window (owner code of this test) is open around the outstanding
bursts, the refused bursts, the single-beat bursts and each reset in flight. The
filter setup, the reach control, the refusal controls and the W measurement run
with the window closed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, with_timeout
from env.sep_axi_chan_mon import SepAxiChanMon
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import worst_resp
from sep_base_test import sep_base_test
from sep_reg_meta import INBOUND_FILTER_CTRL_0, sym
from seq_lib.sep_fabric_csr_bank_seq import (
    F_ALLOW_BURST,
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_READ_ALLOWED,
    F_WRITE_ALLOWED,
)
from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter, SepInboundFilterCfg
from seq_lib.sep_sram_inbound_burst_seq import SepSramByteModel

TEST = "sep_sram_axi_shape_matrix_test"

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LAST = SRAM_BASE + SRAM_SIZE - 1
WORD = 8
N_WORDS = SRAM_SIZE // WORD
WORD_BITS = N_WORDS.bit_length() - 1  # 15 word-address bits
PAGE = 0x1000
SLOT = 0x200
SIZES = (1, 2, 4, 8)
SIZE_ENC = {1: 0, 2: 1, 4: 2, 8: 3}
FIXED, INCR, WRAP = 0, 1, 2
BURST_NAME = {FIXED: "FIXED", INCR: "INCR", WRAP: "WRAP"}
OKAY, SLVERR = 0, 2
RESP_NAME = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
M64 = (1 << 64) - 1

# AxPROT of every inbound access: bit 1 set (non-secure). The filter entry sets
# allow_ns = 1 to match it (hw/ip/axi_filter/doc/index.adoc, Match).
PROT_INBOUND = 0b010
FILTER_ENTRY = 0
INCR_LENS = (1, 2, 7, 16)
FIXED_LENS = (2, 3, 8, 16)
WRAP_LENS = (2, 8, 16)
N_REACH_DRAWN = 128
# s_axi carries a 3-bit ID and m_axi a 6-bit ID (tb/sep_tb_signal_list.svh).
S_IDS = range(1, 8)
M_IDS = range(1, 64)
MASTERS = ("cpu_lsu", "inbound")

# Environment choices (logged).
ACCESS_NS = 50_000  # completion bound of one access
RESET_BOUND = 2_000  # clk_i cycles for dbg_sep_reset_n_o to follow rst_ni
FOLLOW_BOUND = 2_000  # clk_i cycles for a request handshake or a response
QUIET_CYCLES = 256  # quiet wait for a stale beat after the post-reset readback
SETTLE_CYCLES = 8  # idle clocks between bursts of one phase

PROG_FIELDS = (
    F_ENTRY_ENABLED
    | F_READ_ALLOWED
    | F_WRITE_ALLOWED
    | F_ALLOW_BURST
    | F_ALLOW_NS
    | INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "src_id")
)


def _w(v: int) -> str:
    s = f"{v & M64:016x}"
    return f"0x{s[:8]}_{s[8:]}"


def beat_addrs(burst: int, start: int, beats: int, size: int) -> list[int]:
    """AXI4 beat addresses of an aligned burst (IHI 0022, A3.4.1)."""
    if burst == FIXED:
        return [start] * beats
    if burst == INCR:
        return [start + i * size for i in range(beats)]
    span = beats * size
    lo = start - start % span
    return [lo + (start - lo + i * size) % span for i in range(beats)]


def words_of(addrs: list[int], size: int) -> list[int]:
    """The 8-byte words the bytes of the beats fall in, in first-touch order."""
    out: list[int] = []
    for a in addrs:
        for b in range(a, a + size):
            w = b - b % WORD
            if w not in out:
                out.append(w)
    return out


class _Burst:
    """One drawn burst of the outstanding or refusal steps."""

    def __init__(
        self, tag: str, op: str, burst: int, addr: int, beats: int, size: int, axi_id: int
    ):
        self.tag = tag
        self.op = op
        self.burst = burst
        self.addr = addr
        self.beats = beats
        self.size = size
        self.axi_id = axi_id
        self.data = b""

    @property
    def nbytes(self) -> int:
        return self.beats * self.size

    def fmt(self) -> str:
        return (
            f"{self.tag}:{self.op}/{BURST_NAME[self.burst]}/len={self.beats}/size={self.size}"
            f"/id={self.axi_id}/@0x{self.addr:08x}"
        )


class _Cfg:
    """Seed-drawn configuration of the leaf (single source of truth)."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.rng = rng
        used: set[int] = set()

        def uniq64() -> int:
            while True:
                v = rng.getrandbits(64)
                if v not in used and v != 0:
                    used.add(v)
                    return v

        n_pages = SRAM_SIZE // PAGE

        # Reach control: first word, last word, each word-address bit, drawn words.
        fixed = [SRAM_BASE, SRAM_BASE + SRAM_SIZE - WORD]
        fixed += [SRAM_BASE + (WORD << k) for k in range(WORD_BITS)]
        self.reach: dict[str, list[tuple[int, int, int]]] = {}
        for m in MASTERS:
            pool = set(fixed)
            drawn: list[int] = []
            while len(drawn) < N_REACH_DRAWN:
                a = SRAM_BASE + rng.randrange(N_WORDS) * WORD
                if a not in pool:
                    pool.add(a)
                    drawn.append(a)
            addrs = fixed + drawn
            sizes = list(SIZES) + [rng.choice(SIZES) for _ in range(len(addrs) - len(SIZES))]
            rng.shuffle(sizes)
            self.reach[m] = [(a, s, uniq64()) for a, s in zip(addrs, sizes)]

        # Outstanding depth: one page, eight 512-byte slots; phase A writes, phase B
        # reads of A interleaved with new writes, phase C reads of the B writes.
        self.depth = rng.randrange(1, 5)
        self.page_o = SRAM_BASE + rng.randrange(n_pages) * PAGE
        ids = rng.sample(list(M_IDS), 16)
        slots = list(range(8))
        rng.shuffle(slots)

        def incr(tag: str, op: str, beats: int, slot: int, axi_id: int) -> _Burst:
            size = rng.choice(SIZES)
            n = beats * size
            off = rng.randrange(0, (SLOT - n) // size + 1) * size
            b = _Burst(tag, op, INCR, self.page_o + slot * SLOT + off, beats, size, axi_id)
            if op == "W":
                b.data = bytes(rng.getrandbits(8) for _ in range(n))
            return b

        lens_a = list(INCR_LENS)
        rng.shuffle(lens_a)
        self.phase_a = [incr(f"A{i}", "W", n, slots[i], ids[i]) for i, n in enumerate(lens_a)]
        lens_b = list(INCR_LENS)
        rng.shuffle(lens_b)
        b_writes = [incr(f"B{i}", "W", n, slots[4 + i], ids[4 + i]) for i, n in enumerate(lens_b)]
        b_reads = [
            _Burst(f"R{a.tag}", "R", INCR, a.addr, a.beats, a.size, ids[8 + i])
            for i, a in enumerate(self.phase_a)
        ]
        self.phase_b = b_reads + b_writes
        rng.shuffle(self.phase_b)
        self.phase_c = [
            _Burst(f"R{w.tag}", "R", INCR, w.addr, w.beats, w.size, ids[12 + i])
            for i, w in enumerate(b_writes)
        ]

        # Refused bursts: one 512-byte slot each in a second page. The burst sits in
        # the low 256 bytes, the INCR control burst in the high 256 bytes.
        pages = [p for p in range(n_pages) if SRAM_BASE + p * PAGE != self.page_o]
        self.page_r = SRAM_BASE + rng.choice(pages) * PAGE
        cases = [(FIXED, n) for n in FIXED_LENS] + [(WRAP, n) for n in WRAP_LENS]
        rng.shuffle(cases)
        r_ids = rng.sample(list(M_IDS), len(cases))
        self.refuse: list[dict] = []
        for i, (burst, beats) in enumerate(cases):
            slot = self.page_r + i * SLOT
            if burst == FIXED:
                wsize = 8
                start = slot + rng.randrange(0, 256 // WORD) * WORD
            else:
                legal = [s for s in SIZES if s * beats >= WORD]
                wsize = rng.choice(legal)
                span = beats * wsize
                lo = slot + rng.randrange(0, (256 - 2 * span) // span + 1) * span
                start = lo + rng.randrange(beats) * wsize
            rsize = rng.choice(SIZES) if burst == FIXED else wsize
            b = _Burst(f"X{i}", "W", burst, start, beats, wsize, r_ids[i])
            words = words_of(beat_addrs(burst, start, beats, wsize), wsize)
            self.refuse.append(
                {
                    "b": b,
                    "rsize": rsize,
                    "ctrl": slot + 256,
                    "fixed": uniq64(),
                    "bg": [uniq64() for _ in words],
                    "incr": bytes(rng.getrandbits(8) for _ in range(beats * WORD)),
                }
            )

        # Single-beat FIXED and WRAP on each master.
        s_ids = rng.sample(list(S_IDS), 2)
        m_ids = rng.sample([i for i in M_IDS if i not in ids and i not in r_ids], 2)
        self.single: list[tuple[str, int, int, int, int]] = []
        for k, burst in enumerate((FIXED, WRAP)):
            for m in MASTERS:
                a = SRAM_BASE + rng.randrange(N_WORDS) * WORD
                axi_id = s_ids[k] if m == "cpu_lsu" else m_ids[k]
                self.single.append((m, burst, a, uniq64(), axi_id))

        # Reset in flight on the CPU-LSU master.
        self.paths = ["RD", "WR"]
        rng.shuffle(self.paths)
        self.otf: dict[str, dict[str, int]] = {}
        for p in ("RD", "WR"):
            a, a2 = (SRAM_BASE + w * WORD for w in rng.sample(range(N_WORDS), 2))
            abandon, post_w, post_r = rng.sample(list(S_IDS), 3)
            self.otf[p] = {
                "u": rng.getrandbits(32),
                "addr": a,
                "data": uniq64(),
                "id": abandon,
                "post_addr": a2,
                "post_data": uniq64(),
                "post_wid": post_w,
                "post_rid": post_r,
            }
        meas = rng.sample(range(N_WORDS), 1)[0]
        self.meas_addr = SRAM_BASE + meas * WORD
        self.meas_data = uniq64()
        self.meas_ids = rng.sample(list(S_IDS), 2)

    def draw_lines(self) -> list[str]:
        out = []
        for m in MASTERS:
            rows = self.reach[m]
            out.append(
                f"reach_{m} words={len(rows)} sizes="
                + ",".join(str(s) for _, s, _ in rows)
                + " drawn="
                + ",".join(f"0x{a:08x}" for a, _, _ in rows[2 + WORD_BITS :])
            )
        out.append(f"depth={self.depth} page_o=0x{self.page_o:08x}")
        out.append("phase_a=" + " ".join(b.fmt() for b in self.phase_a))
        out.append("phase_b=" + " ".join(b.fmt() for b in self.phase_b))
        out.append("phase_c=" + " ".join(b.fmt() for b in self.phase_c))
        out.append(
            f"page_r=0x{self.page_r:08x} refuse="
            + " ".join(f"{r['b'].fmt()}/rsize={r['rsize']}" for r in self.refuse)
        )
        out.append(
            "single="
            + " ".join(f"{m}/{BURST_NAME[bt]}/@0x{a:08x}/id={i}" for m, bt, a, _, i in self.single)
        )
        out.append(
            "otf_order="
            + ",".join(self.paths)
            + " "
            + " ".join(
                f"{p}:u_o=0x{v['u']:08x}({v['u'] / 2**32:.6f})/@0x{v['addr']:08x}/id={v['id']}"
                f"/post@0x{v['post_addr']:08x}/post_ids={v['post_wid']},{v['post_rid']}"
                for p, v in self.otf.items()
            )
        )
        out.append(f"meas=@0x{self.meas_addr:08x} ids={self.meas_ids}")
        return out


@pyuvm.test()
class sep_sram_axi_shape_matrix_test(sep_base_test):
    """SRAM burst shapes, refused burst types, outstanding depth and a reset in flight."""

    required_evidence = (
        "CHK-SRAM-OUTSTANDING",
        "CHK-SRAM-REFUSE",
        "CHK-SRAM-SINGLE",
        "CHK-SRAM-OTF",
        "CHK-SRAM-OTF-REPLAY",
    )

    # ---- access primitives ---------------------------------------------------
    def _axi(self, master: str):
        agent = self.env.axi_agent if master == "cpu_lsu" else self.env.ext_axi_agent
        return agent.driver.axi

    def _mon(self, master: str) -> SepAxiChanMon:
        return self.mon_s if master == "cpu_lsu" else self.mon_m

    def _issue(
        self,
        master: str,
        op: str,
        burst: int,
        addr: int,
        *,
        beats: int,
        size: int,
        axi_id: int,
        data: bytes = b"",
    ):
        """Start one access on the VIP master; returns its completion event."""
        axi = self._axi(master)
        kw = {"burst": burst, "size": SIZE_ENC[size]}
        if master == "inbound":
            kw["prot"] = PROT_INBOUND
        if op == "W":
            assert len(data) == beats * size, "write payload does not match the burst shape"
            return axi.init_write(address=addr, data=data, awid=axi_id, **kw)
        return axi.init_read(address=addr, length=beats * size, arid=axi_id, **kw)

    async def _wait(self, ev, what: str):
        try:
            await with_timeout(ev.wait(), ACCESS_NS, "ns")
        except Exception as exc:
            raise AssertionError(f"{what}: no completion within {ACCESS_NS} ns") from exc
        if ev.data is None:
            raise AssertionError(f"{what}: the master dropped the access")
        return ev.data

    async def _single(
        self,
        master: str,
        op: str,
        addr: int,
        size: int,
        *,
        axi_id: int,
        data: bytes = b"",
        burst: int = INCR,
    ) -> tuple[int, bytes]:
        """One single-beat access to completion; returns (worst response, read bytes)."""
        ev = self._issue(master, op, burst, addr, beats=1, size=size, axi_id=axi_id, data=data)
        raw = await self._wait(ev, f"{master} {op} {BURST_NAME[burst]} @0x{addr:08x}")
        code = worst_resp(getattr(raw, "resp", None))
        rd = bytes(getattr(raw, "data", b"") or b"") if op == "R" else b""
        return code, rd

    async def _write_word(self, master: str, addr: int, value: int, size: int, axi_id: int) -> None:
        """Write one 64-bit word with single-beat accesses of ``size`` bytes."""
        raw = value.to_bytes(WORD, "little")
        for off in range(0, WORD, size):
            code, _ = await self._single(
                master, "W", addr + off, size, axi_id=axi_id, data=raw[off : off + size]
            )
            if code != OKAY:
                raise AssertionError(
                    f"{master} write @0x{addr + off:08x} size={size} answered "
                    f"{RESP_NAME.get(code, code)}, expected OKAY"
                )
        self.model.write(addr, raw)

    async def _read_word(self, master: str, addr: int, axi_id: int) -> int:
        code, rd = await self._single(master, "R", addr, WORD, axi_id=axi_id)
        if code != OKAY or len(rd) != WORD:
            raise AssertionError(
                f"{master} read @0x{addr:08x} answered {RESP_NAME.get(code, code)} "
                f"with {len(rd)} bytes, expected OKAY and 8 bytes"
            )
        return int.from_bytes(rd, "little")

    def _beats(self, mon: SepAxiChanMon, mark, ch: str, axi_id: int):
        return [b for b in mon.since(mark, ch) if b.axi_id == axi_id]

    # ---- step 2: inbound filter entry ----------------------------------------
    async def _filter(self) -> None:
        filt = SepInboundFilter(self)
        cfg = SepInboundFilterCfg(entry=FILTER_ENTRY, allow_addr=SRAM_BASE)
        await filt.program_rule(
            cfg,
            read_allowed=True,
            write_allowed=True,
            allow_burst=True,
            end_addr=SRAM_LAST,
            allow_ns=True,
        )
        want_cfg = cfg.config_word(
            read_allowed=True, write_allowed=True, allow_burst=True, allow_ns=True
        )
        checks = (
            ("FILTER_CONFIG", cfg.cfg_addr, want_cfg, PROG_FIELDS),
            (
                "START_ADDR",
                cfg.start_addr_reg,
                SRAM_BASE,
                INBOUND_FILTER_CTRL_0.mask32("START_ADDR"),
            ),
            (
                "START_ADDR_HI",
                cfg.start_addr_reg + 4,
                0,
                INBOUND_FILTER_CTRL_0.mask("START_ADDR") >> 32,
            ),
            ("END_ADDR", cfg.end_addr_reg, SRAM_LAST, INBOUND_FILTER_CTRL_0.mask32("END_ADDR")),
            ("END_ADDR_HI", cfg.end_addr_reg + 4, 0, INBOUND_FILTER_CTRL_0.mask("END_ADDR") >> 32),
        )
        parts = []
        for name, addr, want, mask in checks:
            got = await filt.read_cpu(addr)
            fc = field_compare(got, want, mask)
            parts.append(f"{name}: {fc.fields()}")
            if not fc.ok:
                msg = f"CTL-SRAM-FILTER FAIL: entry {FILTER_ENTRY} {name} readback {fc.fields()}"
                self.logger.error(msg)
                raise AssertionError(msg)
        self.logger.info(
            "CTL-SRAM-FILTER: entry=%d entry_enabled=1 read_allowed=1 write_allowed=1 "
            "allow_burst=1 src_id=0 allow_ns=1 range=0x%08x..0x%08x %s",
            FILTER_ENTRY,
            SRAM_BASE,
            SRAM_LAST,
            " | ".join(parts),
        )

    # ---- step 3: reach control -----------------------------------------------
    async def _reach(self) -> None:
        for m in MASTERS:
            rows = self.plan.reach[m]
            for addr, size, value in rows:
                await self._write_word(m, addr, value, size, 1)
            bad = []
            for addr, _size, _value in rows:
                got = await self._read_word(m, addr, 1)
                exp = self.model.word(addr)
                if got != exp:
                    bad.append(f"@0x{addr:08x} got={_w(got)} exp={_w(exp)}")
            sizes = sorted({s for _, s, _ in rows})
            line = (
                f"CTL-SRAM-REACH: words={len(rows)} first=1 last=1 bits_walked={WORD_BITS} "
                f"mismatches={len(bad)} master={m} sizes={sizes}"
            )
            if bad or sizes != list(SIZES):
                self.logger.error("%s FAIL first: %s", line, "; ".join(bad[:4]))
                raise AssertionError(f"{line} FAIL")
            self.logger.info(line)

    # ---- step 4: outstanding depth -------------------------------------------
    async def _run_phase(self, ops: list[_Burst], depth: int) -> list[str]:
        """Issue ``ops`` in order with at most ``depth`` outstanding; grade each one."""
        mon = self.mon_m
        mark = mon.mark()
        pending: list[tuple[_Burst, object]] = []
        clk = cocotb.top.clk_i
        for op in ops:
            waited = 0
            while sum(1 for _, ev in pending if not ev.is_set()) >= depth:
                await RisingEdge(clk)
                waited += 1
                if waited > FOLLOW_BOUND:
                    raise AssertionError(
                        f"CHK-SRAM-OUTSTANDING FAIL: {depth} accesses outstanding for "
                        f"{FOLLOW_BOUND} clocks before {op.fmt()}"
                    )
            ev = self._issue(
                "inbound",
                op.op,
                op.burst,
                op.addr,
                beats=op.beats,
                size=op.size,
                axi_id=op.axi_id,
                data=op.data,
            )
            pending.append((op, ev))
        bad: list[str] = []
        for op, ev in pending:
            raw = await self._wait(ev, f"CHK-SRAM-OUTSTANDING {op.fmt()}")
            if op.op == "W":
                bs = self._beats(mon, mark, "b", op.axi_id)
                if len(bs) != 1 or bs[0].resp != OKAY:
                    bad.append(
                        f"{op.fmt()} B beats with its ID: "
                        f"{[(b.clk, b.resp) for b in bs]}, expected one OKAY"
                    )
                self.model.write(op.addr, op.data)
            else:
                rs = self._beats(mon, mark, "r", op.axi_id)
                lasts = [b.last for b in rs]
                if (
                    len(rs) != op.beats
                    or any(b.resp != OKAY for b in rs)
                    or lasts != [0] * (op.beats - 1) + [1]
                ):
                    bad.append(
                        f"{op.fmt()} R beats with its ID: "
                        f"{[(b.clk, b.resp, b.last) for b in rs]}, expected {op.beats} OKAY "
                        "with RLAST on the last"
                    )
                got = bytes(getattr(raw, "data", b"") or b"")
                exp = bytes(self.model.mem[op.addr + i] for i in range(op.nbytes))
                if got != exp:
                    bad.append(f"{op.fmt()} data {got.hex()} expected {exp.hex()}")
        await ClockCycles(clk, SETTLE_CYCLES)
        issued = {op.axi_id for op in ops}
        foreign = [
            (b.ch, b.axi_id, b.clk)
            for b in mon.since(mark)
            if b.ch in ("b", "r") and b.axi_id not in issued
        ]
        if foreign:
            bad.append(f"response beats with IDs this phase did not issue: {foreign}")
        self._peak = max(self._peak, self._depth_peak(mon.since(mark)))
        return bad

    @staticmethod
    def _depth_peak(beats) -> int:
        """Peak count of accepted AR/AW without their last R or B.

        In one clock the completions count before the requests, so a request
        accepted on the clock of the previous last response does not overlap it.
        """

        def done(b) -> bool:
            return b.ch == "b" or (b.ch == "r" and b.last == 1)

        cur = peak = 0
        for b in sorted(beats, key=lambda x: (x.clk, 0 if done(x) else 1)):
            if b.ch in ("ar", "aw"):
                cur += 1
            elif done(b):
                cur -= 1
            peak = max(peak, cur)
        return peak

    async def _outstanding(self) -> None:
        c = self.plan
        self._peak = 0
        open_graded_window(TEST, self.logger)
        bad = await self._run_phase(c.phase_a, 1)
        bad += await self._run_phase(c.phase_b, c.depth)
        bad += await self._run_phase(c.phase_c, c.depth)
        close_graded_window(self.logger)
        n = len(c.phase_a) + len(c.phase_b) + len(c.phase_c)
        if self._peak != c.depth:
            bad.append(
                f"peak outstanding on m_axi {self._peak}, expected the drawn depth {c.depth}"
            )
        if bad:
            msg = f"CHK-SRAM-OUTSTANDING FAIL: depth={c.depth} bursts={n} " + "; ".join(bad[:6])
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info(
            "CHK-SRAM-OUTSTANDING PASS: depth=%d bursts=%d id_match=1 data_match=1 "
            "lengths=%s peak=%d",
            c.depth,
            n,
            list(INCR_LENS),
            self._peak,
        )
        self.n_checks += 1

    # ---- step 5: refused FIXED and WRAP bursts --------------------------------
    async def _refuse_case(self, r: dict) -> None:
        mon = self.mon_m
        b, rsize, ctrl, value, incr_data = r["b"], r["rsize"], r["ctrl"], r["fixed"], r["incr"]
        addrs = beat_addrs(b.burst, b.addr, b.beats, b.size)
        words = words_of(addrs, b.size)
        # Background: every touched word with single-beat 8-byte writes.
        for w, bg in zip(words, r["bg"]):
            await self._write_word("inbound", w, bg, WORD, b.axi_id)
        # Control: an INCR burst and a single-beat FIXED burst with the same ID.
        ev = self._issue(
            "inbound", "W", INCR, ctrl, beats=b.beats, size=WORD, axi_id=b.axi_id, data=incr_data
        )
        raw = await self._wait(ev, f"refusal control INCR write {b.fmt()}")
        ctl_ok = worst_resp(getattr(raw, "resp", None)) == OKAY
        self.model.write(ctrl, incr_data)
        fx = value.to_bytes(WORD, "little")
        code, _ = await self._single(
            "inbound", "W", words[0], WORD, axi_id=b.axi_id, data=fx, burst=FIXED
        )
        ctl_ok &= code == OKAY
        self.model.write(words[0], fx)
        ev = self._issue("inbound", "R", INCR, ctrl, beats=b.beats, size=WORD, axi_id=b.axi_id)
        raw = await self._wait(ev, f"refusal control INCR read {b.fmt()}")
        ctl_ok &= worst_resp(getattr(raw, "resp", None)) == OKAY
        ctl_ok &= bytes(getattr(raw, "data", b"") or b"") == incr_data
        code, rd = await self._single("inbound", "R", words[0], WORD, axi_id=b.axi_id, burst=FIXED)
        ctl_ok &= code == OKAY and rd == fx
        if not ctl_ok:
            msg = (
                f"CHK-SRAM-REFUSE FAIL: {b.fmt()} control: the INCR burst at 0x{ctrl:08x} or the "
                "single-beat FIXED burst with the same ID did not write and read back with OKAY"
            )
            self.logger.error(msg)
            raise AssertionError(msg)
        # Pre-read.
        pre = {w: await self._read_word("inbound", w, b.axi_id) for w in words}
        for w in words:
            if pre[w] != self.model.word(w):
                raise AssertionError(
                    f"CHK-SRAM-REFUSE FAIL: {b.fmt()} pre-read @0x{w:08x} {_w(pre[w])} differs "
                    f"from the byte model {_w(self.model.word(w))}"
                )
        pre_bytes = {}
        for w, v in pre.items():
            for i, byte in enumerate(v.to_bytes(WORD, "little")):
                pre_bytes[w + i] = byte
        data = b"".join(bytes((~pre_bytes[a + i]) & 0xFF for i in range(b.size)) for a in addrs)
        # Refused write.
        open_graded_window(TEST, self.logger)
        mark = mon.mark()
        ev = self._issue(
            "inbound", "W", b.burst, b.addr, beats=b.beats, size=b.size, axi_id=b.axi_id, data=data
        )
        raw = await self._wait(ev, f"CHK-SRAM-REFUSE {b.fmt()} write")
        await ClockCycles(cocotb.top.clk_i, 2)
        bs = self._beats(mon, mark, "b", b.axi_id)
        close_graded_window(self.logger)
        post = {w: await self._read_word("inbound", w, b.axi_id) for w in words}
        changed = [w for w in words if post[w] != pre[w]]
        # Refused read of the same shape.
        open_graded_window(TEST, self.logger)
        mark = mon.mark()
        ev = self._issue(
            "inbound", "R", b.burst, b.addr, beats=b.beats, size=rsize, axi_id=b.axi_id
        )
        await self._wait(ev, f"CHK-SRAM-REFUSE {b.fmt()} read")
        await ClockCycles(cocotb.top.clk_i, 2)
        rs = self._beats(mon, mark, "r", b.axi_id)
        close_graded_window(self.logger)
        bresp = [x.resp for x in bs]
        rresp = [x.resp for x in rs]
        ok = (
            bresp == [SLVERR]
            and not changed
            and len(rs) == b.beats
            and all(r == SLVERR for r in rresp)
            and [x.last for x in rs] == [0] * (b.beats - 1) + [1]
        )
        line = (
            f"type={BURST_NAME[b.burst]} len={b.beats} master=inbound "
            f"bresp={'/'.join(RESP_NAME.get(r, str(r)) for r in bresp) or 'none'} "
            f"unchanged={int(not changed)} rbeats={len(rs)} "
            f"{'all_SLVERR' if rresp and all(r == SLVERR for r in rresp) else 'rresp=' + str(rresp)} "
            f"wsize={b.size} rsize={rsize} id={b.axi_id} start=0x{b.addr:08x} words={len(words)}"
        )
        if not ok:
            detail = "; ".join(f"@0x{w:08x} pre={_w(pre[w])} post={_w(post[w])}" for w in changed)
            msg = f"CHK-SRAM-REFUSE FAIL: {line} {detail}"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info("CHK-SRAM-REFUSE PASS: %s", line)
        self.n_checks += 1

    # ---- steps 6 and 7: single-beat FIXED and WRAP ------------------------------
    async def _single_case(self, master: str, burst: int, addr: int, value: int, axi_id: int):
        mon = self._mon(master)
        raw = value.to_bytes(WORD, "little")
        open_graded_window(TEST, self.logger)
        mark = mon.mark()
        wcode, _ = await self._single(master, "W", addr, WORD, axi_id=axi_id, data=raw, burst=burst)
        rcode, rd = await self._single(master, "R", addr, WORD, axi_id=axi_id, burst=burst)
        await ClockCycles(cocotb.top.clk_i, 2)
        bs = [x.resp for x in self._beats(mon, mark, "b", axi_id)]
        rs = [x.resp for x in self._beats(mon, mark, "r", axi_id)]
        close_graded_window(self.logger)
        landed = int(rd == raw)
        ok = wcode == OKAY and rcode == OKAY and bs == [OKAY] and rs == [OKAY] and landed
        line = (
            f"type={BURST_NAME[burst]} master={master} "
            f"resp={'OKAY' if wcode == rcode == OKAY else f'{RESP_NAME.get(wcode)}/{RESP_NAME.get(rcode)}'} "
            f"landed={landed} axlen=0 id={axi_id} @0x{addr:08x} data={_w(value)} "
            f"bus_b={bs} bus_r={rs} control_incr_landed={int(self.reach_ok)}"
        )
        if not ok:
            msg = f"CHK-SRAM-SINGLE FAIL: {line} read={rd.hex()}"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.model.write(addr, raw)
        self.logger.info("CHK-SRAM-SINGLE PASS: %s", line)
        self.n_checks += 1

    # ---- step 8: response window W ---------------------------------------------
    async def _follow(self, op: str, axi_id: int, *, land_at: int | None) -> dict[str, int | None]:
        """Sample the s_axi pins each clock (read-only phase) after an issue.

        ``anchor`` is the sample that shows the last request handshake (taken on
        the next edge), ``resp`` the sample that shows the response handshake.
        With ``land_at`` set, returns at sample ``anchor + 1 + land_at`` if no
        response showed by then.
        """
        top = cocotb.top
        st: dict[str, int | None] = {"anchor": None, "resp": None, "aw": None, "w": None}

        def hi(name: str) -> bool:
            v = getattr(top, f"s_axi_{name}").value
            return v.is_resolvable and int(v) == 1

        def idv(name: str) -> int | None:
            v = getattr(top, f"s_axi_{name}").value
            return int(v) if v.is_resolvable else None

        for cyc in range(1, FOLLOW_BOUND + 1):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            if op == "RD":
                if (
                    st["anchor"] is None
                    and hi("arvalid")
                    and hi("arready")
                    and idv("arid") == axi_id
                ):
                    st["anchor"] = cyc
                if hi("rvalid") and hi("rready") and idv("rid") == axi_id:
                    st["resp"] = cyc
                    return st
            else:
                if st["aw"] is None and hi("awvalid") and hi("awready") and idv("awid") == axi_id:
                    st["aw"] = cyc
                if st["w"] is None and hi("wvalid") and hi("wready"):
                    st["w"] = cyc
                if st["anchor"] is None and st["aw"] is not None and st["w"] is not None:
                    st["anchor"] = max(st["aw"], st["w"])
                if hi("bvalid") and hi("bready") and idv("bid") == axi_id:
                    st["resp"] = cyc
                    return st
            if (
                land_at is not None
                and st["anchor"] is not None
                and cyc >= st["anchor"] + 1 + land_at
            ):
                return st
        raise AssertionError(
            f"{op} id={axi_id}: no {'response' if land_at is None else 'request handshake'} "
            f"within {FOLLOW_BOUND} clocks ({st})"
        )

    async def _measure(self) -> dict[str, int]:
        c = self.plan
        wid, rid = c.meas_ids
        data = c.meas_data.to_bytes(WORD, "little")
        win: dict[str, int] = {}
        ev = self._issue(
            "cpu_lsu", "W", INCR, c.meas_addr, beats=1, size=WORD, axi_id=wid, data=data
        )
        st = await self._follow("WR", wid, land_at=None)
        raw = await self._wait(ev, "W measurement write")
        wcode = worst_resp(getattr(raw, "resp", None))
        win["WR"] = st["resp"] - st["anchor"] - 1
        self.model.write(c.meas_addr, data)
        ev = self._issue("cpu_lsu", "R", INCR, c.meas_addr, beats=1, size=WORD, axi_id=rid)
        st2 = await self._follow("RD", rid, land_at=None)
        raw = await self._wait(ev, "W measurement read")
        rcode = worst_resp(getattr(raw, "resp", None))
        rd = bytes(getattr(raw, "data", b"") or b"")
        win["RD"] = st2["resp"] - st2["anchor"] - 1
        live = wcode == OKAY and rcode == OKAY and rd == data
        self.logger.info(
            "CTL-SRAM-W: WR anchor=%s resp=%s W=%d resp_code=%s | RD anchor=%s resp=%s W=%d "
            "resp_code=%s data=%s expected=%s live=%d",
            st["anchor"],
            st["resp"],
            win["WR"],
            RESP_NAME.get(wcode),
            st2["anchor"],
            st2["resp"],
            win["RD"],
            RESP_NAME.get(rcode),
            rd.hex(),
            data.hex(),
            int(live),
        )
        if not live or min(win.values()) < 1:
            raise AssertionError(
                f"CHK-SRAM-OTF FAIL: the no-reset measurement did not complete with the drawn "
                f"data or left no cycle to land a reset in (W={win}, live={int(live)})"
            )
        return win

    # ---- step 9: reset in flight -------------------------------------------------
    async def _wait_level(self, sig, level: int, bound: int, what: str) -> int:
        top = cocotb.top
        for cyc in range(1, bound + 1):
            await RisingEdge(top.clk_i)
            await ReadOnly()
            if self.rd(sig, allow_unknown=True) == level:
                return cyc
        raise AssertionError(f"{what}: {sig._name} did not read {level} within {bound} clocks")

    async def _otf(self, path: str, w: int) -> None:
        c = self.plan
        v = c.otf[path]
        top = cocotb.top
        o = (v["u"] * w) >> 32
        self.logger.info("DRAW-SCALED %s u_o=%.6f W=%d o=%d", path, v["u"] / 2**32, w, o)
        data = v["data"].to_bytes(WORD, "little")
        if path == "RD":
            # Setup (window closed): the read address holds a written value.
            await self._write_word("cpu_lsu", v["addr"], v["data"], WORD, v["post_wid"])
        open_graded_window(TEST, self.logger)
        mon = self.mon_s
        mark = mon.mark()
        tap_mark = self.sram_tap.mark()
        op = "R" if path == "RD" else "W"
        ev = self._issue(
            "cpu_lsu",
            op,
            INCR,
            v["addr"],
            beats=1,
            size=WORD,
            axi_id=v["id"],
            data=data if op == "W" else b"",
        )
        st = await self._follow(path, v["id"], land_at=o)
        await FallingEdge(top.clk_i)
        top.rst_ni.value = 0
        fall_clk = mon.clk
        fall_tap = self.sram_tap.mark()
        low = await self._wait_level(top.dbg_sep_reset_n_o, 0, RESET_BOUND, "reset assert")
        await FallingEdge(top.clk_i)
        top.rst_ni.value = 1
        rel = await self._wait_level(top.dbg_sep_reset_n_o, 1, RESET_BOUND, "reset release")
        await self.wait_fuse_sense()
        dropped = ev.is_set() and ev.data is None
        # Midflight from the channel monitor record.
        ch_req = "ar" if path == "RD" else "aw"
        req = self._beats(mon, mark, ch_req, v["id"])
        rsp_ch = "r" if path == "RD" else "b"
        rsp_before = [b for b in self._beats(mon, mark, rsp_ch, v["id"]) if b.clk <= fall_clk]
        midflight = int(
            bool(req) and req[0].clk < fall_clk and not rsp_before and st["resp"] is None
        )
        # Post-reset write and readback with other IDs.
        post = v["post_data"].to_bytes(WORD, "little")
        mark_post = mon.mark()
        wcode, _ = await self._single(
            "cpu_lsu", "W", v["post_addr"], WORD, axi_id=v["post_wid"], data=post
        )
        rcode, rd = await self._single("cpu_lsu", "R", v["post_addr"], WORD, axi_id=v["post_rid"])
        self.model.write(v["post_addr"], post)
        await ClockCycles(top.clk_i, QUIET_CYCLES)
        stale = [
            (b.ch, b.clk)
            for b in mon.since(mark)
            if b.ch in ("r", "b") and b.axi_id == v["id"] and b.clk > fall_clk
        ]
        post_b = [b.resp for b in self._beats(mon, mark_post, "b", v["post_wid"])]
        post_r = [b.resp for b in self._beats(mon, mark_post, "r", v["post_rid"])]
        close_graded_window(self.logger)
        readback = int.from_bytes(rd, "little") if len(rd) == WORD else None
        ok = (
            midflight
            and dropped
            and wcode == OKAY
            and rcode == OKAY
            and rd == post
            and post_b == [OKAY]
            and post_r == [OKAY]
            and not stale
        )
        line = (
            f"path={path} offset={o}/{w} midflight={midflight} "
            f"readback={'X' if readback is None else hex(readback)} "
            f"resp={'OKAY' if wcode == rcode == OKAY else f'{RESP_NAME.get(wcode)}/{RESP_NAME.get(rcode)}'} "
            f"stale_beats={len(stale)} req_clk={req[0].clk if req else None} fall_after_clk={fall_clk} "
            f"anchor={st['anchor']} dropped_in_master={int(dropped)} reset_low_clks={low} "
            f"release_clks={rel} quiet={QUIET_CYCLES}"
        )
        if not ok:
            msg = f"CHK-SRAM-OTF FAIL: {line} expected={post.hex()} stale={stale}"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info("CHK-SRAM-OTF PASS: %s", line)
        self.n_checks += 1
        # Replay check on the PR-SRAM request tap.
        reqs = self.sram_tap.since(fall_tap, "req")
        rsps = self.sram_tap.since(fall_tap, "rsp")
        ab_off = (v["addr"] - SRAM_BASE) & ~(WORD - 1)
        post_off = (v["post_addr"] - SRAM_BASE) & ~(WORD - 1)

        def off(beat) -> int | None:
            return None if beat.addr is None else beat.addr & ~(WORD - 1)

        ctl_w = [b for b in reqs if b.we == 1 and off(b) == post_off]
        first_w = ctl_w[0].seq if ctl_w else None
        replay = [b for b in reqs if off(b) == ab_off and (first_w is None or b.seq < first_w)]
        unknown = [b for b in reqs if b.addr is None or b.we is None]
        ctl_r = [
            b
            for b in reqs
            if b.we == 0 and off(b) == post_off and (first_w is not None and b.seq > first_w)
        ]
        rsp_seen = int(bool(ctl_r) and any(r.seq > ctl_r[0].seq for r in rsps))
        line = (
            f"path={path} offset={o}/{w} replay={len(replay)} control_write_seen={int(bool(ctl_w))} "
            f"control_rsp_seen={rsp_seen} abandoned_off=0x{ab_off:05x} post_off=0x{post_off:05x} "
            f"tap_reqs_after_fall={len(reqs)} pre_fall_reqs={len(self.sram_tap.since(tap_mark, 'req')) - len(reqs)}"
        )
        if replay or not ctl_w or not rsp_seen or unknown:
            msg = (
                f"CHK-SRAM-OTF-REPLAY FAIL: {line} replays={[b.fmt() for b in replay]} "
                f"unknown={[b.fmt() for b in unknown]}"
            )
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info("CHK-SRAM-OTF-REPLAY PASS: %s", line)
        self.n_checks += 1

    # ---- scenario ------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.logger.info("SEED seed=%d", seed)
        plan = _Cfg(seed)
        self.plan = plan
        for line in plan.draw_lines():
            self.logger.info("DRAW %s", line)
        self.logger.info(
            "ENV bounds: access=%d ns reset_follow=%d clk follow=%d clk quiet=%d clk",
            ACCESS_NS,
            RESET_BOUND,
            FOLLOW_BOUND,
            QUIET_CYCLES,
        )
        self.n_checks = 0
        self.model = SepSramByteModel()

        await self.bring_up_no_cpu()
        self.mon_s = SepAxiChanMon("s_axi").start()
        self.mon_m = SepAxiChanMon("m_axi").start()
        await ClockCycles(cocotb.top.clk_i, 2)

        await self._filter()
        self.reach_ok = False
        await self._reach()
        self.reach_ok = True
        await self._outstanding()
        for r in plan.refuse:
            await self._refuse_case(r)
        for m, burst, addr, value, axi_id in plan.single:
            await self._single_case(m, burst, addr, value, axi_id)

        self.sram_tap = SepFabricTap("PR-SRAM").start()
        windows = await self._measure()
        for path in plan.paths:
            await self._otf(path, windows[path])
        close_graded_window(self.logger)
        await self.sram_tap.stop()
        await self.mon_s.stop()
        await self.mon_m.stop()
        self.result_pass(TEST, seed, self.n_checks)
