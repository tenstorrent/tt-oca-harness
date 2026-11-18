# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded mailbox FIFO model: STATUS, threshold flags, ERROR_FLAGS and flushes on drawn pairs.

Specs: hw/ip/axi_lite_mailbox_unit/regs/axil_mailbox.rdl (STATUS, ERROR_FLAGS, WIRQT, RIRQT,
IRQS, CTRL), hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc (Paired FIFOs, Interrupts),
hw/ip/axi_lite_mailbox_unit/doc/interface.adoc (Mailbox access results),
hw/ip/axi_lite_mailbox_unit/doc/memmap.adoc (CTRL flush bits) and hw/sys/smc/doc/periphs.adoc
(SMC Peripheral Parameter Overrides, `MailboxDepth` 2).

Within pair N the outbound aperture A writes FIFO A->B and reads FIFO B->A; the inbound aperture
B writes FIFO B->A and reads FIFO A->B. For an aperture X the model gives `STATUS.empty` = level
of X's read FIFO is 0, `STATUS.full` = level of X's write FIFO equals the depth,
`write_level_above_thresh` = level of X's write FIFO > stored `X.WIRQT` and
`read_level_above_thresh` = level of X's read FIFO > stored `X.RIRQT`, the stored threshold being
min(written, `MailboxDepth` - 1).

The seed draws 4 passes on distinct pairs. Passes 0 and 1 are pinned: pass 0 writes A->B with a
`WIRQT` of 2 or 3 (stored 1) and an `RIRQT` of 0, pass 1 writes B->A with a `WIRQT` of 0 and an
`RIRQT` of 2 or 3 (stored 1), each with a fill of 2 to 8 words, so every seed crosses both stored
thresholds of both flags in both directions and reads a clamped value back. Passes 2 and 3 draw
the direction, the fill (0 to 8), both thresholds (0 to 3) and the extras. Every pass runs the
write to a full mailbox, the read from an empty one, both injections before one `ERROR_FLAGS`
read, a write flush and a read flush each after a re-fill of 1 or 2 words.
"""

from __future__ import annotations

import random
import re

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_addr_symbols
from .smc_csr_seq_utils import SmcCsrSeq

_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h",
    "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm",
)
EMPTY = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__EMPTY_bm")
FULL = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__FULL_bm")
WRITE_ABOVE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm")
READ_ABOVE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__READ_LEVEL_ABOVE_THRESH_bm")
STATUS_FIELDS = EMPTY | FULL | WRITE_ABOVE | READ_ABOVE
READ_ERROR = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__ERROR__READ_ERROR_bm")
WRITE_ERROR = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__ERROR__WRITE_ERROR_bm")
ERROR_FIELDS = READ_ERROR | WRITE_ERROR
WFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__WFLUSH_bm")
RFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__RFLUSH_bm")
FLUSH_BITS = WFLUSH | RFLUSH
EIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")
WIRQT_RESET = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__WIRQT__WIRQT_reset")
RIRQT_RESET = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__RIRQT__RIRQT_reset")

# periphs.adoc, SMC Peripheral Parameter Overrides: the Mailbox depth override is 2.
MAILBOX_DEPTH = 2
# interface.adoc, Mailbox access results: a full write and an empty read answer SLVERR.
AXI_SLVERR = 2
FUSE_SENSE_RISES = 200_000
N_PASSES = 4
FILL_MAX = 8
THRESH_MAX = 3
# axil_mailbox.rdl ERROR: a 32-bit read of the upper half returns 0 and clears every flag.
UPPER_HALF_OFFSET, UPPER_HALF_BYTES = 4, 4
_PAIR_SYMBOL = re.compile(r"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_(\d+)_STATUS_BASE_ADDR")
PAIRS = tuple(
    sorted(
        int(_PAIR_SYMBOL.fullmatch(sym).group(1)) for sym in smc_addr_symbols(_PAIR_SYMBOL.pattern)
    )
)
SIDE = {"A": "OUTBOUND", "B": "INBOUND"}
PEER = {"A": "B", "B": "A"}
OKAY, ERROR = "okay", "error"

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
CHK_STEPS = (
    ("CHK-MBFM-RESET", "S1"),
    ("CHK-MBFM-LEVEL", "S2"),
    ("CHK-MBFM-ERRFLAG", "S4"),
    ("CHK-MBFM-CLEAR", "S4"),
    ("CHK-MBFM-FLUSH", "S5"),
)


def stored_threshold(value: int) -> int:
    """axil_mailbox.rdl WIRQT, RIRQT: a value at or above the depth is stored as depth - 1."""
    return value if value < MAILBOX_DEPTH else MAILBOX_DEPTH - 1


def draw_passes(rng: random.Random, pairs: tuple[int, ...] = PAIRS) -> list[dict]:
    """The 4 passes of one seed; passes 0 and 1 are the pinned cells."""
    chosen = rng.sample(pairs, N_PASSES)
    passes = []
    for idx, pair in enumerate(chosen):
        if idx == 0:
            writer, wirqt, rirqt = "A", rng.choice((2, 3)), 0
            fill = rng.randint(MAILBOX_DEPTH, FILL_MAX)
        elif idx == 1:
            writer, wirqt, rirqt = "B", 0, rng.choice((2, 3))
            fill = rng.randint(MAILBOX_DEPTH, FILL_MAX)
        else:
            writer = rng.choice("AB")
            wirqt, rirqt = rng.randint(0, THRESH_MAX), rng.randint(0, THRESH_MAX)
            fill = rng.randint(0, FILL_MAX)
        passes.append(
            {
                "pair": pair,
                "writer": writer,
                "reader": PEER[writer],
                "fill": fill,
                "wirqt": wirqt,
                "rirqt": rirqt,
                "extra_full": rng.random() < 0.5,
                "extra_empty": rng.random() < 0.5,
                "extra_flush": rng.choice((None, "writer_rflush", "reader_wflush")),
                "wflush_fill": rng.randint(1, MAILBOX_DEPTH),
                "rflush_fill": rng.randint(1, MAILBOX_DEPTH),
                "rev_fill": rng.randint(1, MAILBOX_DEPTH),
                "words": [rng.getrandbits(64) for _ in range(16)],
            }
        )
    check_draw(passes)
    return passes


def check_draw(passes: list[dict]) -> None:
    """The pinned cells and the filters of the draw."""
    assert len({p["pair"] for p in passes}) == N_PASSES, "passes do not take distinct pairs"
    p0, p1 = passes[0], passes[1]
    assert p0["writer"] == "A" and p1["writer"] == "B", "pinned directions missing"
    assert stored_threshold(p0["wirqt"]) == 1 and p0["wirqt"] >= MAILBOX_DEPTH
    assert stored_threshold(p1["rirqt"]) == 1 and p1["rirqt"] >= MAILBOX_DEPTH
    assert p0["rirqt"] == 0 and p1["wirqt"] == 0, "pinned stored-0 thresholds missing"
    assert min(p0["fill"], p1["fill"]) >= MAILBOX_DEPTH, "pinned fill does not reach the depth"
    for p in passes:
        assert 0 <= p["fill"] <= FILL_MAX
        assert 0 <= p["wirqt"] <= THRESH_MAX and 0 <= p["rirqt"] <= THRESH_MAX
        for key in ("wflush_fill", "rflush_fill", "rev_fill"):
            assert 1 <= p[key] <= MAILBOX_DEPTH, f"{key} {p[key]} leaves the flush at level 0"


class _Model:
    """Levels of the two FIFOs of one pair and the four stored thresholds."""

    def __init__(self) -> None:
        self.fifo: dict[str, list[int]] = {"A": [], "B": []}
        self.wirqt = {"A": WIRQT_RESET, "B": WIRQT_RESET}
        self.rirqt = {"A": RIRQT_RESET, "B": RIRQT_RESET}

    def level(self, writer: str) -> int:
        return len(self.fifo[writer])

    def status(self, side: str) -> int:
        wl, rl = self.level(side), self.level(PEER[side])
        word = EMPTY if rl == 0 else 0
        word |= FULL if wl == MAILBOX_DEPTH else 0
        word |= WRITE_ABOVE if wl > self.wirqt[side] else 0
        word |= READ_ABOVE if rl > self.rirqt[side] else 0
        return word


class smc_mailbox_fifo_model_rand_test_seq(SmcCsrSeq):
    """Drawn pairs, directions, fills and thresholds against a per-pair FIFO model."""

    def __init__(self, name: str = "smc_mailbox_fifo_model_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.passes: list[dict] = []
        self.models: dict[int, _Model] = {}
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.status_reads = 0
        self.flag_seen: dict[tuple[int, str], set[int]] = {}
        self.n_full_writes = 0
        self.n_empty_reads = 0
        self.n_flushes = 0
        self.cg = 0
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    @staticmethod
    def _cell(p: dict) -> str:
        return (
            f"pair {p['pair']} {p['writer']}->{p['reader']} fill {p['fill']} "
            f"WIRQT {p['wirqt']} RIRQT {p['rirqt']}"
        )

    def _drawn(self) -> str:
        return "drawn=" + "; ".join(self._cell(p) for p in self.passes)

    @staticmethod
    def _addr(pair: int, side: str, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_MAILBOX_{SIDE[side]}_MAILBOX_{pair}_{reg}_BASE_ADDR")

    def _item(self, name, op, pair, side, reg, data=0, mode=OKAY) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op, item.addr, item.length = op, self._addr(pair, side, reg), 8
        item.wdata = data
        item.expect_error = item.allow_error = mode == ERROR
        item.expected_resp = AXI_SLVERR if mode == ERROR else None
        return item

    @staticmethod
    def _resp(item: SmcSysAxiItem, mode: str) -> None:
        want = AXI_SLVERR if mode == ERROR else 0
        assert item.resp_code == want, f"{item.name}: response {item.resp_code}, want {want}"
        if item.op is SmcSysAxiOp.READ:
            assert isinstance(item.rdata, int), f"{item.name}: unresolved read data"

    async def _do(self, name, op, pair, side, reg, data=0, mode=OKAY) -> SmcSysAxiItem:
        item = self._item(name, op, pair, side, reg, data, mode)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._resp(item, mode)
        return item

    async def _rd(self, name, pair, side, reg) -> int:
        return int((await self._do(name, SmcSysAxiOp.READ, pair, side, reg)).rdata)

    async def _wr(self, name, pair, side, reg, data) -> None:
        await self._do(name, SmcSysAxiOp.WRITE, pair, side, reg, data)

    async def _status(self, tag: str, p: dict) -> None:
        """STATUS of both apertures against the model."""
        pair, model = p["pair"], self.models[p["pair"]]
        for side in "AB":
            got = await self._rd(f"{tag}_STATUS_{pair}{side}", pair, side, "STATUS")
            want = model.status(side)
            self.status_reads += 1
            assert got & STATUS_FIELDS == want, (
                f"{tag}: STATUS of pair {pair} {side} 0x{got:x}, model 0x{want:x} (levels "
                f"A->B {model.level('A')} B->A {model.level('B')}, WIRQT {model.wirqt}, "
                f"RIRQT {model.rirqt}); {self._cell(p)}"
            )
            if side == p["writer"]:
                self.flag_seen.setdefault((pair, "write"), set()).add(got & WRITE_ABOVE)
            else:
                self.flag_seen.setdefault((pair, "read"), set()).add(got & READ_ABOVE)

    async def _push(self, tag: str, p: dict, side: str, word: int) -> None:
        await self._wr(tag, p["pair"], side, "WRITE_DATA", word)
        self.models[p["pair"]].fifo[side].append(word)
        assert self.models[p["pair"]].level(side) <= MAILBOX_DEPTH
        await self._status(tag, p)

    async def _pop(self, tag: str, p: dict, side: str) -> None:
        model = self.models[p["pair"]]
        writer = PEER[side]
        assert model.fifo[writer], f"{tag}: model pop from an empty FIFO"
        want = model.fifo[writer].pop(0)
        got = await self._rd(tag, p["pair"], side, "READ_DATA")
        assert got == want, f"{tag}: READ_DATA 0x{got:016x}, want 0x{want:016x}; {self._cell(p)}"
        await self._status(tag, p)

    async def _full_write(self, tag: str, p: dict) -> None:
        pair, writer = p["pair"], p["writer"]
        assert self.models[pair].level(writer) == MAILBOX_DEPTH, f"{tag}: model not full"
        await self._do(tag, SmcSysAxiOp.WRITE, pair, writer, "WRITE_DATA", p["words"][15], ERROR)
        self.n_full_writes += 1
        await self._status(tag, p)

    async def _empty_read(self, tag: str, p: dict, side: str) -> None:
        assert self.models[p["pair"]].level(PEER[side]) == 0, f"{tag}: model not empty"
        await self._do(tag, SmcSysAxiOp.READ, p["pair"], side, "READ_DATA", mode=ERROR)
        self.n_empty_reads += 1
        await self._status(tag, p)

    async def _flags(self, tag: str, pair: int, side: str) -> tuple[int, int]:
        """First and repeat ERROR_FLAGS reads."""
        first = await self._rd(f"{tag}_EF1", pair, side, "ERROR_FLAGS") & ERROR_FIELDS
        again = await self._rd(f"{tag}_EF2", pair, side, "ERROR_FLAGS") & ERROR_FIELDS
        return first, again

    async def _upper_half_clear(self, tag: str, p: dict, side: str) -> str:
        """IRQS.eirq acknowledged, an empty read, then ERROR_FLAGS read at +4 with 4 bytes and again
        with 8 bytes.

        IRQS.eirq is the sentinel of the injection: an empty read sets the read-error flag and
        IRQS[2] (interface.adoc:50-51), reading IRQS does not clear it (architecture.adoc:61-62)
        and reading ERROR_FLAGS does not acknowledge it (architecture.adoc:68-69).
        """
        pair = p["pair"]
        await self._wr(f"{tag}_IRQS_ACK", pair, side, "IRQS", EIRQ)
        pre = await self._rd(f"{tag}_IRQS_PRE", pair, side, "IRQS") & EIRQ
        assert pre == 0, (
            f"{tag}: IRQS.eirq of {side} reads 1 after a write of 1 to it, want 0 "
            f"(axil_mailbox.rdl IRQS: write 1 acknowledges and clears); {self._cell(p)}"
        )
        await self._do(f"{tag}_INJECT", SmcSysAxiOp.READ, pair, side, "READ_DATA", mode=ERROR)
        self.n_empty_reads += 1
        injected = await self._rd(f"{tag}_IRQS_INJ", pair, side, "IRQS") & EIRQ
        assert injected == EIRQ, (
            f"{tag}: IRQS.eirq of {side} reads 0 after an empty read, want 1 "
            f"(interface.adoc: an empty read sets the read-error flag and IRQS[2]); {self._cell(p)}"
        )
        item = SmcSysAxiItem(f"rd_{tag}_EF_UPPER")
        item.op, item.length = SmcSysAxiOp.READ, UPPER_HALF_BYTES
        item.addr = self._addr(pair, side, "ERROR_FLAGS") + UPPER_HALF_OFFSET
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self._resp(item, OKAY)
        upper = int(item.rdata) & ((1 << (8 * UPPER_HALF_BYTES)) - 1)
        after = await self._rd(f"{tag}_EF_AFTER", pair, side, "ERROR_FLAGS") & ERROR_FIELDS
        assert (upper, after) == (0, 0), (
            f"{tag}: after an empty read on {side}, the 4-byte ERROR_FLAGS read at +4 returned "
            f"0x{upper:x} and the 8-byte read after it 0b{after:02b}, want 0 and 0 "
            f"(axil_mailbox.rdl ERROR: a read of any size or alignment clears every flag); "
            f"{self._cell(p)}"
        )
        kept = await self._rd(f"{tag}_IRQS_POST", pair, side, "IRQS") & EIRQ
        assert kept == EIRQ, (
            f"{tag}: IRQS.eirq of {side} reads 0 after the ERROR_FLAGS reads, want 1 "
            f"(architecture.adoc: reading ERROR_FLAGS does not acknowledge IRQS[2]); "
            f"{self._cell(p)}"
        )
        return (
            f"{side} IRQS.eirq {int(bool(pre))}->{int(bool(injected))}->{int(bool(kept))}, "
            f"upper-half 0x{upper:x}/0b{after:02b}"
        )

    async def _flush(self, tag: str, p: dict, side: str, bit: int) -> str:
        pair, model = p["pair"], self.models[p["pair"]]
        fifo = side if bit == WFLUSH else PEER[side]
        before = model.level(fifo)
        assert before > 0, f"{tag}: flush at level 0 does not discriminate"
        await self._wr(f"{tag}_CTRL", pair, side, "CTRL", bit)
        ctrl = await self._rd(f"{tag}_CTRL_RB", pair, side, "CTRL")
        assert ctrl & FLUSH_BITS == 0, (
            f"{tag}: CTRL of pair {pair} {side} reads 0x{ctrl:x} after the flush write, want 0 "
            f"in the flush bits (memmap.adoc: pulses, not stored); {self._cell(p)}"
        )
        model.fifo[fifo].clear()
        self.n_flushes += 1
        await self._status(tag, p)
        name = "wflush" if bit == WFLUSH else "rflush"
        return f"{side}.{name} of FIFO {fifo}->{PEER[fifo]} at level {before}"

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        await self.wait_fuse_sense_done(max_cycles=FUSE_SENSE_RISES)
        self.passes = draw_passes(self.rng)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %d passes on %d pairs (depth %d): %s",
            self.seed,
            len(self.passes),
            len(PAIRS),
            MAILBOX_DEPTH,
            "; ".join(
                f"{self._cell(p)} extra_full {int(p['extra_full'])} extra_empty "
                f"{int(p['extra_empty'])} extra_flush {p['extra_flush']} refills "
                f"{p['wflush_fill']}/{p['rflush_fill']}/{p['rev_fill']}"
                for p in self.passes
            ),
        )
        self.cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, self.cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=self.cg | MAILBOX_CG_EN
        )
        logged = []
        for p in self.passes:
            self.models[p["pair"]] = _Model()
            for side in "AB":
                st = await self._rd(f"RESET_STATUS_{p['pair']}{side}", p["pair"], side, "STATUS")
                logged.append(
                    f"pair {p['pair']} {side} empty {st & EMPTY} full {int(bool(st & FULL))}"
                )
        self._mark("S1")
        self._chk(
            "S1",
            "CHK-MBFM-RESET",
            f"logged control, not graded: {'; '.join(logged)} beside the control values empty 1 "
            f"and full 0 (graded by smc_mailbox_register_map_reset_test, "
            f"CHK-RESET-ALL-64-APERTURES); {self._drawn()}",
        )

    async def _s2(self) -> None:
        clamps, crossed, quiet = [], [], []
        for idx, p in enumerate(self.passes):
            pair, w, r, model = p["pair"], p["writer"], p["reader"], self.models[p["pair"]]
            await self._wr(f"P{idx}_WIRQT", pair, w, "WIRQT", p["wirqt"])
            await self._wr(f"P{idx}_RIRQT", pair, r, "RIRQT", p["rirqt"])
            got_w = await self._rd(f"P{idx}_WIRQT_RB", pair, w, "WIRQT")
            got_r = await self._rd(f"P{idx}_RIRQT_RB", pair, r, "RIRQT")
            want_w, want_r = stored_threshold(p["wirqt"]), stored_threshold(p["rirqt"])
            assert (got_w, got_r) == (want_w, want_r), (
                f"pass {idx}: WIRQT/RIRQT read back {got_w}/{got_r} after writes "
                f"{p['wirqt']}/{p['rirqt']}, want {want_w}/{want_r} (axil_mailbox.rdl: a value "
                f"at or above MailboxDepth {MAILBOX_DEPTH} is stored as depth - 1)"
            )
            model.wirqt[w], model.rirqt[r] = want_w, want_r
            clamps.append(f"P{idx} {p['wirqt']}->{got_w}/{p['rirqt']}->{got_r}")
            await self._status(f"P{idx}_S2_START", p)
            n = min(p["fill"], MAILBOX_DEPTH)
            for k in range(n):
                await self._push(f"P{idx}_S2_W{k}", p, w, p["words"][k])
            for k in range(n):
                await self._pop(f"P{idx}_S2_P{k}", p, r)
            for side in "AB":
                first, again = await self._flags(f"P{idx}_S2_{side}", pair, side)
                assert (first, again) == (0, 0), (
                    f"pass {idx}: ERROR_FLAGS of {side} 0b{first:02b}/0b{again:02b} after "
                    f"accesses that found room or data, want 0; {self._cell(p)}"
                )
            quiet.append(f"P{idx} A,B 0")
            wf = self.flag_seen.get((pair, "write"), set())
            rf = self.flag_seen.get((pair, "read"), set())
            crossed.append(
                f"P{idx} write flag {'crossed' if len(wf) == 2 else 'constant'}, read flag "
                f"{'crossed' if len(rf) == 2 else 'constant'}"
            )
        for idx in (0, 1):
            pair = self.passes[idx]["pair"]
            for kind in ("write", "read"):
                assert len(self.flag_seen[(pair, kind)]) == 2, (
                    f"pinned pass {idx}: the {kind} threshold flag never changed over the fill"
                )
        self._mark("S2")
        self._chk(
            "S2",
            "CHK-MBFM-LEVEL",
            f"threshold readbacks (written->read) {', '.join(clamps)} equal min(T, "
            f"{MAILBOX_DEPTH - 1}); {self.status_reads} STATUS reads of both apertures after "
            f"every write and pop equal the model in empty, full and both threshold flags; "
            f"discriminating cells: {', '.join(crossed)}; ERROR_FLAGS after the fills "
            f"{', '.join(quiet)}; {self._drawn()}",
        )

    async def _s3(self) -> None:
        self.s3_log = []
        for idx, p in enumerate(self.passes):
            pair, w = p["pair"], p["writer"]
            for k in range(MAILBOX_DEPTH):
                await self._push(f"P{idx}_S3_W{k}", p, w, p["words"][2 + k])
            extra = max(p["fill"] - MAILBOX_DEPTH, 1) + (1 if p["extra_full"] else 0)
            for k in range(extra):
                await self._full_write(f"P{idx}_S3_FULL{k}", p)
            first, again = await self._flags(f"P{idx}_S3_{w}", pair, w)
            assert (first, again) == (WRITE_ERROR, 0), (
                f"pass {idx}: ERROR_FLAGS of {w} 0b{first:02b} then 0b{again:02b} after {extra} "
                f"writes to a full mailbox, want 0b{WRITE_ERROR:02b} then 0; {self._cell(p)}"
            )
            self.s3_log.append(f"P{idx} {extra} full writes -> 0b{first:02b}/0b{again:02b}")
        self._mark("S3")

    async def _s4(self) -> None:
        both_log, read_log, upper_log = [], [], ""
        for idx, p in enumerate(self.passes):
            pair, w, r = p["pair"], p["writer"], p["reader"]
            word = p["words"][14]
            wr = self._item(
                f"P{idx}_S4_BOTH_FULL", SmcSysAxiOp.WRITE, pair, w, "WRITE_DATA", word, ERROR
            )
            rd = self._item(
                f"P{idx}_S4_BOTH_EMPTY", SmcSysAxiOp.READ, pair, w, "READ_DATA", 0, ERROR
            )
            assert self.models[pair].level(w) == MAILBOX_DEPTH and self.models[pair].level(r) == 0
            group = SmcSysAxiGroupItem(f"P{idx}_S4_BOTH", [wr, rd])
            await self.start_item(group)
            await self.finish_item(group)
            self.accesses += 2
            self._resp(wr, ERROR)
            self._resp(rd, ERROR)
            self.n_full_writes += 1
            self.n_empty_reads += 1
            await self._status(f"P{idx}_S4_BOTH", p)
            first, again = await self._flags(f"P{idx}_S4_BOTH_{w}", pair, w)
            assert (first, again) == (ERROR_FIELDS, 0), (
                f"pass {idx}: ERROR_FLAGS of {w} 0b{first:02b} then 0b{again:02b} after a full "
                f"write and an empty read, want 0b{ERROR_FIELDS:02b} then 0; {self._cell(p)}"
            )
            both_log.append(f"P{idx} {w} 0b{first:02b}/0b{again:02b}")
            for k in range(MAILBOX_DEPTH):
                await self._pop(f"P{idx}_S4_P{k}", p, r)
            n_empty = 2 if p["extra_empty"] else 1
            for k in range(n_empty):
                await self._empty_read(f"P{idx}_S4_EMPTY{k}", p, r)
            first, again = await self._flags(f"P{idx}_S4_{r}", pair, r)
            assert (first, again) == (READ_ERROR, 0), (
                f"pass {idx}: ERROR_FLAGS of {r} 0b{first:02b} then 0b{again:02b} after "
                f"{n_empty} empty reads, want 0b{READ_ERROR:02b} then 0; {self._cell(p)}"
            )
            read_log.append(f"P{idx} {n_empty} empty reads on {r} -> 0b{first:02b}/0b{again:02b}")
            if idx == 0:
                upper_log = await self._upper_half_clear(f"P{idx}_S4_UPPER", p, r)
        self._mark("S4")
        self._chk(
            "S4",
            "CHK-MBFM-ERRFLAG",
            f"writes to a full mailbox set write_error alone ({', '.join(self.s3_log)}); reads "
            f"from an empty one set read_error alone ({', '.join(read_log)}); a full write and "
            f"an empty read issued as one group set both ({', '.join(both_log)}); every pass "
            f"read ERROR_FLAGS 0 on both apertures after its fill and drain (S2); "
            f"{self.n_full_writes} full writes and {self.n_empty_reads} empty reads answered "
            f"SLVERR (interface.adoc); {self._drawn()}",
        )
        self._chk(
            "S4",
            "CHK-MBFM-CLEAR",
            f"every first ERROR_FLAGS read after an injection returned the flags set and the "
            f"repeat read 0: {3 * len(self.passes)} injection reads over {len(self.passes)} "
            f"passes; on pass 0, IRQS.eirq read 0 after its acknowledge and 1 after one more "
            f"empty read, the 4-byte read at ERROR_FLAGS + 4 then returned 0, the 8-byte read "
            f"after it 0 and IRQS.eirq still 1 ({upper_log}); {self._drawn()}",
        )

    async def _s5(self) -> None:
        log = []
        for idx, p in enumerate(self.passes):
            w, r = p["writer"], p["reader"]
            for k in range(p["wflush_fill"]):
                await self._push(f"P{idx}_S5_WF{k}", p, w, p["words"][4 + k])
            log.append(await self._flush(f"P{idx}_S5_WFLUSH", p, w, WFLUSH))
            for k in range(p["rflush_fill"]):
                await self._push(f"P{idx}_S5_RF{k}", p, w, p["words"][6 + k])
            log.append(await self._flush(f"P{idx}_S5_RFLUSH", p, r, RFLUSH))
            if p["extra_flush"] is not None:
                for k in range(p["rev_fill"]):
                    await self._push(f"P{idx}_S5_XF{k}", p, r, p["words"][8 + k])
                if p["extra_flush"] == "writer_rflush":
                    log.append(await self._flush(f"P{idx}_S5_XFLUSH", p, w, RFLUSH))
                else:
                    log.append(await self._flush(f"P{idx}_S5_XFLUSH", p, r, WFLUSH))
            for k in range(2):
                await self._push(f"P{idx}_S5_POST{k}", p, w, p["words"][10 + k])
            for k in range(2):
                await self._pop(f"P{idx}_S5_POSTP{k}", p, r)
        self._mark("S5")
        self._chk(
            "S5",
            "CHK-MBFM-FLUSH",
            f"{self.n_flushes} flushes ({'; '.join(log)}): CTRL read 0 in the flush bits after "
            f"each and STATUS of both apertures equalled the model with the flushed FIFO at "
            f"level 0; after the flushes each pass pushed and popped 2 words in order; "
            f"{self._drawn()}",
        )

    async def _s6(self) -> None:
        for idx, p in enumerate(self.passes):
            pair, w, r = p["pair"], p["writer"], p["reader"]
            await self._wr(f"P{idx}_WIRQT_RESTORE", pair, w, "WIRQT", WIRQT_RESET)
            await self._wr(f"P{idx}_RIRQT_RESTORE", pair, r, "RIRQT", RIRQT_RESET)
            for side in "AB":
                first, again = await self._flags(f"P{idx}_S6_{side}", pair, side)
                assert (first, again) == (0, 0), f"pass {idx}: ERROR_FLAGS of {side} not 0"
        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, self.cg)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORED", CLOCK_GATE_CONTROL, expected=self.cg)
        self._mark("S6")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 2 bounded waits: fuse sense wait on tb_fuse_sense_done "
            "<= %d clk_smc_i rises (tb_fuse_reset_n %s, tb_rst_warm_smc_clk_n %s at the end); "
            "SEP_IN accesses x%d each bounded by the driver at %d ns (cfg.axi_timeout_ns); "
            "expiry raises AssertionError; the sequence has no other wait",
            FUSE_SENSE_RISES,
            self._level("tb_fuse_reset_n"),
            self._level("tb_rst_warm_smc_clk_n"),
            self.accesses,
            self.cfg.axi_timeout_ns,
        )
        self._nonvac()

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(sig.value)

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        assert self.n_full_writes >= 2 * N_PASSES, f"full writes {self.n_full_writes}"
        assert self.n_empty_reads >= 2 * N_PASSES, f"empty reads {self.n_empty_reads}"
        assert self.n_flushes >= 2 * N_PASSES, f"flushes {self.n_flushes}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; %d writes to a full "
            "mailbox, %d reads from an empty one, %d flushes, %d STATUS reads; %s",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(c for c, _ in self.chk_lines),
            self.n_full_writes,
            self.n_empty_reads,
            self.n_flushes,
            self.status_reads,
            self._drawn(),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        self.done = True
