# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded random AXI stress: attributes, shapes, deep outstanding and a stressed SYS_OUT responder.

Spec sources: fabric.adoc Interfaces, Topology, Configuration Parameters and Routing,
memmap.adoc Memory Map, scratch.rdl SCRATCH, smu-smc.adoc AXI Interface Configuration.

Each inbound port keeps to its own registers, SPM window and output window. Data is checked by
byte address against a per-port golden model; a response is attributed to its port and AxID by
the passive recorders. Where the specification leaves the response code or the order open the
measured value is printed and only completion, the data of the own address and the response
reaching its originating port are asserted. The 50 us driver guard is the only time bound.
"""

from __future__ import annotations

import os
import random
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

import cocotb
from cocotb.utils import get_sim_time
from env.smc_env_cfg import SYS_OUT_MEM_SIZE
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp
from ocah_axi_vip import AxiTimingProfile, OcahAxiSlaveSequence

from ._one_shot import _OneShot
from .smc_addr_map import _REPO, reg_reset_word, smc_addr, smc_indexed_addr
from .smc_axi_port_response_recorder import (
    SmcAxiPortResponseRecorder,
    SmcOutputHandshakeSampler,
    SmcRawRStallWatch,
)
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)

if TYPE_CHECKING:
    from env.smc_env import SmcEnv

FUSE_SENSE_BOUND = 200_000
AXI_TIMEOUT_NS = 50_000
SYS_OUT_DEPTH = 8
SLVERR, DECERR = 2, 3
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", None: "none"}

PORTS = ("SYS", "SEP", "JTAG")
PIDX = {"SYS": 0, "SEP": 1, "JTAG": 2}
PORT_NAME = {"SYS": "SYS_IN", "SEP": "SEP_IN", "JTAG": "JTAG"}
PREFIX = {"SYS": "sys_axi", "SEP": "s_axi", "JTAG": "jtag_axi"}
ID_SPACE = {"SYS": 64, "SEP": 64, "JTAG": 4}
R_RAW_VALID = {"SYS": "tb_sys_axi_r_raw_valid", "SEP": "tb_sep_axi_r_raw_valid"}

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
RESET_CFG = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
RESET_START = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
RESET_END = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")
assert (RESET_CFG, RESET_START, RESET_END) == (0x3000, 0x0, 0x7), (
    f"filter entry 0 RDL reset is 0x{RESET_CFG:x}/0x{RESET_START:x}/0x{RESET_END:x}"
)

_SCRATCH = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR"
_WARM = "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR"
REG_LO = {
    "SYS": smc_indexed_addr(_SCRATCH, 0),
    "SEP": smc_indexed_addr(_SCRATCH, 4),
    "JTAG": smc_indexed_addr(_WARM, 0),
}
SPM_APERTURE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_APERTURE_END = SPM_APERTURE + smc_addr("SMC_TOP_SPM_MEMORY_SIZE")
SPM0 = SPM_APERTURE + 0x8_0000
WINDOW = 0x1_0000
SPM = {p: SPM0 + PIDX[p] * WINDOW for p in PORTS}
OUT0 = 0x0200_0000
OUT = {p: OUT0 + PIDX[p] * WINDOW for p in PORTS}
OUT_LIMIT = OUT0 + 3 * WINDOW

STEPS = tuple(f"S{n}" for n in range(1, 13))
CHECKERS = (
    ("CHK-RAND-ID-ECHO", "S2"),
    ("CHK-RAND-ATTR-OWN-WORD", "S3"),
    ("CHK-RAND-LOCK-OBS", "S4"),
    ("CHK-RAND-OUT-SIDEBAND", "S5"),
    ("CHK-RAND-SHAPE-BY-ADDR", "S7"),
    ("CHK-RAND-LOCAL-DEEP", "S8"),
    ("CHK-RAND-OUT-DEEP", "S9"),
    ("CHK-RAND-OUT-OTHER-PORTS-OBS", "S9"),
    ("CHK-RAND-RESP-TIMING", "S10"),
    ("CHK-RAND-RESP-ERRORS-OBS", "S11"),
    ("CHK-RAND-RESP-COMBINED", "S11"),
)

FIXED, INCR, WRAP = 0, 1, 2
S7_ARENA, S7_ARENA_SIZE = 0xC000, 0x400
S7_COMPARE_READS = 2
BURST_NAME = {FIXED: "FIXED", INCR: "INCR", WRAP: "WRAP"}


class _Golden:
    """One state per byte address of a port: absent is UNKNOWN, present is the byte written."""

    def __init__(self) -> None:
        self.byte: dict[int, int] = {}

    def put(self, addr: int, data: bytes) -> None:
        for i, value in enumerate(data):
            self.byte[addr + i] = value

    def unknown(self, lo: int, hi: int) -> None:
        for addr in range(lo, hi):
            self.byte.pop(addr, None)

    def known(self, addr: int, n: int) -> bool:
        return all(addr + i in self.byte for i in range(n))

    def get(self, addr: int, n: int) -> bytes:
        return bytes(self.byte[addr + i] for i in range(n))

    def known_units(self, lo: int, hi: int, unit: int) -> list[int]:
        bases = {a - a % unit for a in self.byte if lo <= a < hi}
        return sorted(b for b in bases if lo <= b and b + unit <= hi and self.known(b, unit))

    def mismatches(self, addr: int, data: bytes) -> list[tuple[int, int, int]]:
        return [
            (addr + i, self.byte[addr + i], value)
            for i, value in enumerate(data)
            if addr + i in self.byte and self.byte[addr + i] != value
        ]


def _hex(data: bytes) -> str:
    return data[::-1].hex()


class _StressItem(SmcSysAxiItem):
    """SmcSysAxiItem carrying the port it goes to, the observe flag and the want of a read."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.port: str | None = None
        self.observe: bool = False
        self.want: bytes | None = None


class smc_axi_random_stress_test_seq(SmcCsrSeq):
    """Seeded random attributes, shapes, depths and responder faults on the three inbound ports."""

    def __init__(self, name: str = "smc_axi_random_stress_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.golden = {p: _Golden() for p in PORTS}
        self.rec: dict[str, SmcAxiPortResponseRecorder] = {}
        self.sampler = SmcOutputHandshakeSampler()
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._step = "S1"
        self._n_item = 0
        self._step_accesses: Counter = Counter()
        self._codes: dict[str, Counter] = {p: Counter() for p in PORTS}
        # Per (step, port): reads issued at KNOWN bytes and those that answered OKAY and
        # compared; per step: the bytes compared.
        self._cmp_issued: Counter = Counter()
        self._cmp_done: Counter = Counter()
        self._cmp_bytes: Counter = Counter()
        self._out_next = {p: 0x1000 for p in PORTS}
        self._shape: Counter = Counter()
        self._shape_rows: list = []
        self._watchers: list = []

    # ------------------------------------------------------------------ plumbing
    @property
    def _env(self) -> SmcEnv:
        env = self.env
        assert env is not None, "sequence env is not initialized"
        return env

    @property
    def mem(self) -> OcahAxiSlaveSequence:
        """The SYS_OUT responder the test binds through `cfg`."""
        cfg = self.cfg
        assert cfg is not None, "sequence cfg is not initialized"
        mem = cfg.sys_out_mem
        assert mem is not None, "SYS_OUT responder not bound"
        return mem

    def _rng(self, tag: int | str) -> random.Random:
        return random.Random(f"{self.seed}:{tag}")

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    def _sequencer(self, port: str):
        agent = {
            "SEP": self._env.sys_axi_agent,
            "SYS": self._env.sys_in_axi_agent,
            "JTAG": self._env.jtag_axi_agent,
        }[port]
        return agent.sequencer

    @staticmethod
    def _w(rng: random.Random, p: int, addr: int) -> int:
        return ((0xA0 + p) << 56) | (((addr >> 3) & 0xFF_FFFF) << 32) | rng.getrandbits(32)

    @staticmethod
    def _r(rng: random.Random, p: int, index: int) -> int:
        return ((0xC0 + p) << 24) | (index << 16) | rng.getrandbits(16)

    def _in_regs(self, port: str, addr: int) -> bool:
        return REG_LO[port] <= addr < REG_LO[port] + 16

    def _payload(self, rng: random.Random, port: str, addr: int, n: int) -> bytes:
        p = PIDX[port]
        reg = self._in_regs(port, addr)
        unit = 4 if reg else 8
        cache: dict[int, bytes] = {}
        out = bytearray()
        for off in range(n):
            a = addr + off
            base = a - a % unit
            if base not in cache:
                if reg:
                    index = (base - REG_LO[port]) // 4
                    assert 0 <= index < 4, f"{port} register payload at 0x{base:x} off the port"
                    cache[base] = self._r(rng, p, index).to_bytes(4, "little")
                else:
                    cache[base] = self._w(rng, p, base).to_bytes(8, "little")
            out.append(cache[base][a % unit])
        return bytes(out)

    def _mk(self, port, op, addr, *, size=8, beats=1, burst=INCR, data=None, rng=None, **attrs):
        """Build one access. `data` is bytes for a write; with `rng` a payload by address."""
        self._n_item += 1
        item = _StressItem(f"{port.lower()}_{self._step}_{self._n_item}")
        item.op = op
        item.addr = addr
        item.length = size
        item.beats = beats
        item.burst = burst
        item.observe = bool(attrs.pop("observe", False))
        item.port = port
        if op is SmcSysAxiOp.WRITE:
            if data is None:
                data = self._payload(rng, port, addr, size * beats)
            assert len(data) == size * beats
            item.wdata = int.from_bytes(data, "little")
        for key, value in attrs.items():
            setattr(item, key, value)
        return item

    @staticmethod
    def _span(addr: int, size: int, beats: int, burst: int) -> tuple[int, int]:
        """Word-aligned byte range an access of that shape can touch."""
        total = size * beats
        if burst == FIXED and size < 8:
            # The BFM advances its strobe lanes on FIXED bursts, so a narrow FIXED
            # burst touches every lane of its container word.
            lo = addr & ~7
            hi = lo + 8
        elif burst == FIXED:
            lo = addr - addr % size
            hi = lo + size
        elif burst == WRAP:
            lo = addr - addr % total
            hi = lo + total
        else:
            lo, hi = addr, addr + total
        return lo & ~3, (hi + 3) & ~3

    def _is_out(self, addr: int) -> bool:
        return OUT0 <= addr < OUT_LIMIT

    def _settle(self, port: str, item) -> None:
        """Completion, golden update and by-address compare of one finished access."""
        assert not item.timed_out and item.resp_code is not None, (
            f"{self._step} {PORT_NAME[port]} {item.op.value} @0x{item.addr:x} did not complete "
            f"within {AXI_TIMEOUT_NS} ns"
        )
        self.accesses += 1
        self._step_accesses[self._step] += 1
        if self._step in ("S6", "S7"):
            self._shape_rows.append((self._step, port, item))
        code = item.resp_code
        self._codes[port][(item.op.value, code)] += 1
        total = item.transfer_bytes
        golden = self.golden[port]
        out = self._is_out(item.addr)
        if item.op is SmcSysAxiOp.WRITE:
            data = (item.wdata & ((1 << (8 * total)) - 1)).to_bytes(total, "little")
            clean = code == 0 and not item.observe and item.burst == INCR and not item.axi_lock
            if out:
                if clean and port == "JTAG":
                    held = self.mem.read(item.addr, total)
                    assert held == data, (
                        f"{self._step} JTAG write @0x{item.addr:x} answered OKAY but the responder "
                        f"holds {_hex(held)}, want {_hex(data)}"
                    )
                return
            if clean:
                golden.put(item.addr, data)
            else:
                golden.unknown(*self._span(item.addr, item.length, item.beats, item.burst))
            return
        if item.observe:
            return
        if out:
            known = 0 if item.want is None else total
        else:
            known = sum(1 for i in range(total) if item.addr + i in golden.byte)
        if not known:
            return
        self._cmp_issued[(self._step, port)] += 1
        if code != 0:
            return
        got = item.rdata.to_bytes(total, "little")
        if out:
            assert got == item.want, (
                f"{self._step} {PORT_NAME[port]} read @0x{item.addr:x} returned {_hex(got)}, "
                f"the responder word of that address is {_hex(item.want)}"
            )
        else:
            bad = golden.mismatches(item.addr, got)
            assert not bad, (
                f"{self._step} {PORT_NAME[port]} read @0x{item.addr:x} size {item.length} beats "
                f"{item.beats}: byte @0x{bad[0][0]:x} returned 0x{bad[0][2]:02x}, golden of that "
                f"address 0x{bad[0][1]:02x} ({len(bad)} bytes differ)"
            )
        self._cmp_done[(self._step, port)] += 1
        self._cmp_bytes[self._step] += known

    def _compare_floor(self, step: str, port: str, *, every: bool = False) -> str:
        """The reads `step` issued at KNOWN bytes on `port` compared: not none, or all with `every`."""
        issued = self._cmp_issued[(step, port)]
        done = self._cmp_done[(step, port)]
        assert issued and (done == issued if every else done), (
            f"{step} {PORT_NAME[port]}: {done} of {issued} reads issued at KNOWN bytes compared"
            + (", every one must" if every else ", the compare is vacuous")
        )
        return f"{PORT_NAME[port]} {done}/{issued}"

    def _beat_check(self, port: str, item, events) -> None:
        """Beat count of a serialized access: one B beat, or AxLEN+1 R beats ending in RLAST."""
        if item.op is SmcSysAxiOp.WRITE:
            beats = [e for e in events if e.chan == "b"]
            assert len(beats) == 1, f"{self._step} {PORT_NAME[port]} write saw {len(beats)} B beats"
            return
        beats = [e for e in events if e.chan == "r"]
        assert len(beats) == item.beats, (
            f"{self._step} {PORT_NAME[port]} read @0x{item.addr:x} returned {len(beats)} beats, "
            f"AxLEN+1 is {item.beats}"
        )
        assert [e.last for e in beats] == [0] * (item.beats - 1) + [1], (
            f"{self._step} {PORT_NAME[port]} read @0x{item.addr:x} RLAST pattern "
            f"{[e.last for e in beats]}"
        )

    async def _one(self, port: str, item):
        """One access alone on its port. Returns the response events seen at the port."""
        mark = self.rec[port].mark()
        self._prime(port, item)
        await _OneShot(item, f"{item.get_name()}_os").start(self._sequencer(port))
        events = self.rec[port].since(mark)
        self._settle(port, item)
        self._beat_check(port, item, events)
        return events

    def _launch(self, port: str, items, timing=None):
        group = SmcSysAxiGroupItem(f"{self._step}_{port}_group", items, timing=timing)
        return cocotb.start_soon(
            _OneShot(group, f"{group.get_name()}_os").start(self._sequencer(port))
        )

    async def _groups(self, plan: dict, timing: dict | None = None) -> dict:
        """Run one group per port in `plan` together; settle every access; attribute responses."""
        marks = {p: self.rec[p].mark() for p in plan}
        for p, items in plan.items():
            for item in items:
                self._prime(p, item)
        tasks = {
            p: self._launch(p, items, None if timing is None else timing.get(p))
            for p, items in plan.items()
        }
        for task in tasks.values():
            await task
        notes = {}
        for p, items in plan.items():
            for item in items:
                self._settle(p, item)
            notes[p] = self._verify_group(p, items, self.rec[p].since(marks[p]))
        return notes

    def _prime(self, port: str, item) -> None:
        """Snapshot what a read of a responder address must return before the group starts."""
        if (
            item.op is SmcSysAxiOp.READ
            and self._is_out(item.addr)
            and port == "JTAG"
            and not item.observe
        ):
            item.want = self.mem.read(item.addr, item.transfer_bytes)

    def _want_word(self, port: str, item) -> int | None:
        """Lane value a single-beat read must return, from the golden or the responder."""
        if item.beats != 1 or item.burst != INCR or item.axi_lock or item.observe:
            return None
        total = item.transfer_bytes
        if self._is_out(item.addr):
            data = item.want
        else:
            golden = self.golden[port]
            data = golden.get(item.addr, total) if golden.known(item.addr, total) else None
        return None if data is None else int.from_bytes(data, "little")

    def _verify_group(self, port: str, items, events) -> str:
        """Responses recorded at `port` equal the requests of the group, per AxID."""
        writes = [i for i in items if i.op is SmcSysAxiOp.WRITE]
        reads = [i for i in items if i.op is SmcSysAxiOp.READ]
        tag = f"{self._step} {PORT_NAME[port]}"
        b_ev = [e for e in events if e.chan == "b"]
        r_ev = [e for e in events if e.chan == "r"]
        want_b = Counter(i.axi_id for i in writes)
        want_r: Counter = Counter()
        want_last = Counter(i.axi_id for i in reads)
        for i in reads:
            want_r[i.axi_id] += i.beats
        assert Counter(e.ident for e in b_ev) == want_b, (
            f"{tag}: B responses per ID {dict(Counter(e.ident for e in b_ev))}, "
            f"requests {dict(want_b)}"
        )
        assert Counter(e.ident for e in r_ev) == want_r, (
            f"{tag}: R beats per ID {dict(Counter(e.ident for e in r_ev))}, requests {dict(want_r)}"
        )
        assert Counter(e.ident for e in r_ev if e.last) == want_last, (
            f"{tag}: RLAST per ID {dict(Counter(e.ident for e in r_ev if e.last))}, "
            f"requests {dict(want_last)}"
        )
        pending: dict[int, list] = defaultdict(list)
        free: Counter = Counter()
        for i in reads:
            want = self._want_word(port, i) if i.resp_code == 0 else None
            if want is None:
                free[i.axi_id] += i.beats
            else:
                pending[i.axi_id].append((i, want))
        for e in r_ev:
            hit = None
            if e.data is None:
                assert free[e.ident] > 0, (
                    f"{tag}: {PREFIX[port]}_rdata is X/Z on an R beat of ID {e.ident} and every "
                    f"read of that ID compares its data"
                )
            else:
                for k, (i, want) in enumerate(pending[e.ident]):
                    lane = (e.data >> (8 * (i.addr % 8))) & ((1 << (8 * i.length)) - 1)
                    if lane == want:
                        hit = k
                        break
            if hit is not None:
                pending[e.ident].pop(hit)
            else:
                assert free[e.ident] > 0, (
                    f"{tag}: R beat ID {e.ident} data 0x{e.data:x} is the golden word of no read "
                    f"of that ID of this port"
                )
                free[e.ident] -= 1
        assert not any(pending.values()), (
            f"{tag}: reads of ID without a matching response word: "
            f"{[(k, [hex(i.addr) for i, _ in v]) for k, v in pending.items() if v]}"
        )
        order = ",".join(f"{e.chan}{e.ident:x}" for e in events)
        return f"{PORT_NAME[port]} n={len(items)} order[{order}]"

    # ---------------------------------------------------------------- group builders
    def _ids(self, rng: random.Random, port: str, n: int, *, distinct: bool = True) -> list[int]:
        space = ID_SPACE[port]
        if distinct and n <= space:
            return rng.sample(range(space), n)
        return [rng.randrange(space) for _ in range(n)]

    def _spm_items(
        self, rng, port, n_w, n_r, *, regs=True, base_off=0xE000, ids=None, reg_w=None, reg_r=None
    ):
        """n_w writes and n_r reads at distinct locations; reads only of KNOWN locations."""
        golden = self.golden[port]
        arena = SPM[port] + base_off
        used: set[int] = set()
        reg_pool = list(range(4))
        rng.shuffle(reg_pool)
        items = []
        n_reg_w = (reg_w if reg_w is not None else rng.randint(0, min(2, n_w))) if regs else 0
        for _ in range(n_w):
            if n_reg_w > 0:
                n_reg_w -= 1
                idx = reg_pool.pop()
                addr = REG_LO[port] + 4 * idx
                used.add(addr)
                items.append(self._mk(port, SmcSysAxiOp.WRITE, addr, size=4, rng=rng))
                continue
            while True:
                addr = arena + 8 * rng.randrange(512)
                if addr not in used:
                    break
            used.add(addr)
            items.append(self._mk(port, SmcSysAxiOp.WRITE, addr, size=8, rng=rng))
        known_spm = [
            a for a in golden.known_units(SPM[port], SPM[port] + WINDOW, 8) if a not in used
        ]
        known_reg = [
            a
            for a in golden.known_units(REG_LO[port], REG_LO[port] + 16, 4)
            if a not in used and a % 4 == 0
        ]
        n_reg_r = (
            (
                min(reg_r, len(known_reg))
                if reg_r is not None
                else rng.randint(0, min(2, n_r, len(known_reg)))
            )
            if regs
            else 0
        )
        for a in rng.sample(known_reg, n_reg_r):
            items.append(self._mk(port, SmcSysAxiOp.READ, a, size=4))
        for _ in range(n_r - n_reg_r):
            assert known_spm, f"{port} has no KNOWN SPM word to read"
            addr = rng.choice(known_spm)
            known_spm.remove(addr)
            items.append(self._mk(port, SmcSysAxiOp.READ, addr, size=8))
        rng.shuffle(items)
        if ids is not None:
            for item, ident in zip(items, ids):
                item.axi_id = ident
        return items

    def _out_items(self, rng, port, n_w, n_r, **attrs):
        """n_w writes and n_r reads at fresh words of the port output window."""
        p = PIDX[port]
        items = []
        for op, count in ((SmcSysAxiOp.WRITE, n_w), (SmcSysAxiOp.READ, n_r)):
            for _ in range(count):
                addr = OUT[port] + self._out_next[port]
                self._out_next[port] += 8
                assert addr + 8 <= OUT[port] + WINDOW, f"{port} output window exhausted"
                if op is SmcSysAxiOp.WRITE:
                    data = self._w(rng, p, addr).to_bytes(8, "little")
                    items.append(self._mk(port, op, addr, data=data, **attrs))
                else:
                    items.append(self._mk(port, op, addr, **attrs))
        rng.shuffle(items)
        return items

    # --------------------------------------------------------------------- steps
    async def _csr8(self, addr: int, data: int) -> None:
        item = self._mk("SEP", SmcSysAxiOp.WRITE, addr, data=data.to_bytes(8, "little"))
        await self._one("SEP", item)

    async def _program_filter(self, cfg: int, start: int, end: int) -> None:
        for base_cfg, base_start, base_end in (
            (INBOUND0_FILTER_CONFIG, INBOUND0_START, INBOUND0_END),
            (OUTBOUND0_FILTER_CONFIG, OUTBOUND0_START, OUTBOUND0_END),
        ):
            await self._csr8(base_cfg, cfg)
            await self._csr8(base_start, start)
            await self._csr8(base_end, end)

    async def _s1(self) -> None:
        await wait_fuse_sense_done(FUSE_SENSE_BOUND)
        dut = cocotb.top
        cocotb.log.info(
            "RAND-SEED: %d (RANDOM_SEED of the run; one random.Random per step)", self.seed
        )
        assert self.mem.max_outstanding == SYS_OUT_DEPTH, (
            f"SYS_OUT responder depth {self.mem.max_outstanding}, this leaf needs {SYS_OUT_DEPTH}"
        )
        assert SPM["JTAG"] + WINDOW <= SPM_APERTURE_END, "SPM2 end outside the SPM aperture"
        assert OUT_LIMIT <= SYS_OUT_MEM_SIZE, "OUT2 end outside the responder memory"
        for port in PORTS:
            self.rec[port] = SmcAxiPortResponseRecorder(dut, PREFIX[port])
        self._watchers = [cocotb.start_soon(r.run()) for r in self.rec.values()]
        self._watchers.append(cocotb.start_soon(self.sampler.run()))

        cfg_seq = output_fabric_pass_all_cfg_seq("random_stress_pass_all_seq")
        cfg_seq.cfg, cfg_seq.env = self.cfg, self.env
        await cfg_seq.start(self._sequencer("SEP"))
        self.accesses += cfg_seq.accesses

        rng = self._rng(1)
        for port in PORTS:
            for index in range(4):
                addr = REG_LO[port] + 4 * index
                item = self._mk(port, SmcSysAxiOp.WRITE, addr, size=4, rng=rng)
                await self._one(port, item)
        for port in PORTS:
            p = PIDX[port]
            words = b"".join(
                self._w(rng, p, OUT[port] + 8 * k).to_bytes(8, "little") for k in range(WINDOW // 8)
            )
            self.mem.write(OUT[port], words)

    async def _s2(self) -> str:
        rng = self._rng(2)
        fixed = [0x00, 0x3F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20]
        ids = {}
        for port in ("SYS", "SEP"):
            ids[port] = fixed + rng.sample([i for i in range(64) if i not in fixed], 4)
        jtag = [0, 1, 2, 3] * 2
        rng.shuffle(jtag)
        ids["JTAG"] = jtag
        for port in PORTS:
            for k, ident in enumerate(ids[port]):
                addr = SPM[port] + 8 * k
                wr = self._mk(
                    port, SmcSysAxiOp.WRITE, addr, rng=rng, axi_id=ident, capture_resp_id=True
                )
                events = await self._one(port, wr)
                assert wr.resp_code == 0 and wr.bid == ident and events[0].ident == ident, (
                    f"S2 {PORT_NAME[port]} write awid 0x{ident:x} @0x{addr:x}: "
                    f"resp {wr.resp_code} BID {wr.bid} recorded {events[0].ident}"
                )
                rd = self._mk(port, SmcSysAxiOp.READ, addr, axi_id=ident, capture_resp_id=True)
                events = await self._one(port, rd)
                assert rd.resp_code == 0 and rd.rid == ident and events[0].ident == ident, (
                    f"S2 {PORT_NAME[port]} read arid 0x{ident:x} @0x{addr:x}: "
                    f"resp {rd.resp_code} RID {rd.rid} recorded {events[0].ident}"
                )
                assert rd.rdata == wr.wdata, (
                    f"S2 {PORT_NAME[port]} @0x{addr:x} read 0x{rd.rdata:016x}, "
                    f"wrote 0x{wr.wdata:016x}"
                )
        lists = "; ".join(
            f"{PORT_NAME[p]} {len(ids[p])} IDs [{','.join(f'0x{i:x}' for i in ids[p])}]"
            for p in PORTS
        )
        return (
            f"RAND-SEED {self.seed}: {sum(len(v) for v in ids.values())} write-then-read pairs "
            f"completed within {AXI_TIMEOUT_NS} ns, every write OKAY with BID equal to its awid, "
            f"every read OKAY with RID equal to its arid and the 8-byte word W(p,a) of its own "
            f"address, BID/RID read through the VIP capture and the passive port recorder; {lists}"
        )

    async def _s3(self) -> str:
        rng = self._rng(3)
        notes = []
        for port in PORTS:
            qos = [0x0, 0xF] + [rng.randrange(16) for _ in range(14)]
            region = [0x0, 0xF] + [rng.randrange(16) for _ in range(14)]
            user = (
                [0x000, 0xFFF]
                + [1 << b for b in range(12)]
                + [rng.randrange(4096) for _ in range(2)]
            )
            odd_reg = []
            rows = []
            for k in range(16):
                if k % 2 == 0:
                    addr, size = SPM[port] + 8 * k, 8
                else:
                    addr, size = REG_LO[port] + 4 * ((k >> 1) & 3), 4
                attrs = {
                    "axi_cache": k,
                    "axi_qos": qos[k],
                    "axi_region": region[k],
                    "axi_user": user[k],
                    "axi_id": rng.randrange(ID_SPACE[port]),
                    "axi_lock": 0,
                    "allow_error": True,
                }
                wr = self._mk(port, SmcSysAxiOp.WRITE, addr, size=size, rng=rng, **attrs)
                await self._one(port, wr)
                rd = self._mk(port, SmcSysAxiOp.READ, addr, size=size, **attrs)
                await self._one(port, rd)
                if wr.resp_code == 0 and rd.resp_code == 0:
                    assert rd.rdata == wr.wdata, (
                        f"S3 {PORT_NAME[port]} k={k} @0x{addr:x} read 0x{rd.rdata:x}, "
                        f"wrote 0x{wr.wdata:x}"
                    )
                rows.append((k, wr.resp_code, rd.resp_code))
                if k % 2:
                    odd_reg.append(k)
            bad = [f"k{k}:{RESP_NAMES[w]}/{RESP_NAMES[r]}" for k, w, r in rows if (w, r) != (0, 0)]
            okay = sum(1 for _, w, r in rows if (w, r) == (0, 0))
            self._compare_floor("S3", port)
            notes.append(
                f"{PORT_NAME[port]} {okay} of 16 pairs OKAY/OKAY, non-OKAY [{' '.join(bad) or 'none'}] "
                f"(AxCACHE k, AxQOS {qos}, AxREGION {region}, AxUSER "
                f"{[hex(u) for u in user]}; {len(odd_reg)} pairs at registers)"
            )
        return (
            "48 write-then-read pairs completed within the guard with defined data, every read "
            "answered OKAY after an OKAY write returned the word of its own address and no port's "
            "pairs all dropped out of the compare; response codes "
            "per knob value are printed and not graded, and AxUSER carriage at the island is not "
            "observable: " + " | ".join(notes)
        )

    async def _s4(self) -> str:
        rng = self._rng(4)
        notes = []
        for port in PORTS:
            addr = SPM[port] + 0x100
            ident = lambda: rng.randrange(ID_SPACE[port])  # noqa: E731

            async def write(lock=0, tolerate=False):
                item = self._mk(
                    port,
                    SmcSysAxiOp.WRITE,
                    addr,
                    rng=rng,
                    axi_lock=lock,
                    axi_id=ident(),
                    allow_error=tolerate,
                    observe=bool(lock),
                )
                await self._one(port, item)
                return item

            async def read(lock=0, tolerate=False):
                item = self._mk(
                    port,
                    SmcSysAxiOp.READ,
                    addr,
                    axi_lock=lock,
                    axi_id=ident(),
                    allow_error=tolerate,
                    observe=bool(lock),
                )
                await self._one(port, item)
                return item

            await write()
            xr = await read(lock=1, tolerate=True)
            w3 = await write()
            r4 = await read()
            assert r4.resp_code == 0 and r4.rdata == w3.wdata, (
                f"S4 {PORT_NAME[port]} ordinary read after exclusive read returned "
                f"0x{r4.rdata:x}, fresh word 0x{w3.wdata:x}, resp {r4.resp_code}"
            )
            xw = await write(lock=1, tolerate=True)
            w6 = await write()
            r7 = await read()
            assert r7.resp_code == 0 and r7.rdata == w6.wdata, (
                f"S4 {PORT_NAME[port]} ordinary read after exclusive write returned "
                f"0x{r7.rdata:x}, fresh word 0x{w6.wdata:x}, resp {r7.resp_code}"
            )
            notes.append(
                f"{PORT_NAME[port]} exclusive read {RESP_NAMES[xr.resp_code]} data 0x{xr.rdata:x}, "
                f"exclusive write {RESP_NAMES[xw.resp_code]}"
            )
        return (
            "all 21 lock-leg accesses completed within the guard; on every port the ordinary "
            "write-then-read after the exclusive read and after the exclusive write answered OKAY "
            "and returned the fresh word just written; exclusive responses "
            "are printed and not graded: " + "; ".join(notes)
        )

    async def _s5(self) -> str:
        rng = self._rng(5)
        caches = [0x0, 0xF, 0x3] + [rng.randrange(16) for _ in range(5)]
        users = [0x000, 0xFFF] + [rng.randrange(4096) for _ in range(6)]
        aw_users, ar_users, rows = [], [], []
        for k in range(8):
            addr = OUT["JTAG"] + 8 * k
            attrs = {"axi_cache": caches[k], "axi_user": users[k], "axi_id": k % 4}
            mark = self.sampler.mark()
            wr = self._mk("JTAG", SmcSysAxiOp.WRITE, addr, rng=rng, **attrs)
            await self._one("JTAG", wr)
            aw = [e for e in self.sampler.since(mark, "aw") if e.addr == addr]
            assert len(aw) == 1 and aw[0].cache == caches[k], (
                f"S5 JTAG write @0x{addr:x}: {len(aw)} AW at the responder, awcache "
                f"{[hex(e.cache) for e in aw]}, driven 0x{caches[k]:x}"
            )
            mark = self.sampler.mark()
            rd = self._mk("JTAG", SmcSysAxiOp.READ, addr, **attrs)
            await self._one("JTAG", rd)
            ar = [e for e in self.sampler.since(mark, "ar") if e.addr == addr]
            assert len(ar) == 1 and ar[0].cache == caches[k], (
                f"S5 JTAG read @0x{addr:x}: {len(ar)} AR at the responder, arcache "
                f"{[hex(e.cache) for e in ar]}, driven 0x{caches[k]:x}"
            )
            assert rd.resp_code == 0 and rd.rdata == wr.wdata, (
                f"S5 JTAG read @0x{addr:x} resp {rd.resp_code} data 0x{rd.rdata:x}, "
                f"responder word 0x{wr.wdata:x}"
            )
            aw_users.append(aw[0].user)
            ar_users.append(ar[0].user)
            rows.append(f"0x{caches[k]:X}/u{users[k]:03X}")
        assert len(set(aw_users)) == 1, f"S5 awuser differs between JTAG writes: {aw_users}"
        assert len(set(ar_users)) == 1, f"S5 aruser differs between JTAG reads: {ar_users}"
        other = []
        monitor = self._env.axi_monitor
        saved_decerr = set(monitor.expected_decerr_addrs)
        try:
            for port in ("SYS", "SEP"):
                for k in range(2):
                    other.append(await self._s5_other(rng, port, k))
        finally:
            monitor.expected_decerr_addrs.clear()
            monitor.expected_decerr_addrs.update(saved_decerr)
        return (
            f"on JTAG all 8 writes and 8 reads reached the responder at their own OUT2 address "
            f"with awcache and arcache equal to the driven AxCACHE [{' '.join(rows)}], the written "
            f"word at the address, awuser 0x{aw_users[0]:X} on all 8 writes and aruser "
            f"0x{ar_users[0]:X} on all 8 reads whatever AxUSER was driven (the numeric source ID is "
            f"not graded); SYS_IN and SEP_IN are observed only, their codes printed and not "
            f"graded: " + " | ".join(other)
        )

    async def _s5_other(self, rng: random.Random, port: str, k: int) -> str:
        """One observed write and read of SYS_IN or SEP_IN at word `k` of its OUT window."""
        addr = OUT[port] + 8 * k
        cache, user = rng.randrange(16), rng.randrange(4096)
        attrs = {
            "axi_cache": cache,
            "axi_user": user,
            "axi_id": rng.randrange(64),
            "allow_error": True,
            "observe": True,
        }
        self._env.axi_monitor.expected_decerr_addrs.add(addr)
        mark = self.sampler.mark()
        wr = self._mk(port, SmcSysAxiOp.WRITE, addr, rng=rng, **attrs)
        await self._one(port, wr)
        aw = [e for e in self.sampler.since(mark, "aw") if e.addr == addr]
        mark = self.sampler.mark()
        rd = self._mk(port, SmcSysAxiOp.READ, addr, **attrs)
        await self._one(port, rd)
        ar = [e for e in self.sampler.since(mark, "ar") if e.addr == addr]
        return (
            f"{PORT_NAME[port]} k{k} cache 0x{cache:X} user 0x{user:03X}: write "
            f"{RESP_NAMES[wr.resp_code]} aw_seen={len(aw)}"
            f"{'' if not aw else f' awcache 0x{aw[0].cache:X} awuser 0x{aw[0].user:X}'}, "
            f"read {RESP_NAMES[rd.resp_code]} ar_seen={len(ar)}"
            f"{'' if not ar else f' arcache 0x{ar[0].cache:X} aruser 0x{ar[0].user:X}'}"
        )

    async def _s6_port(self, rng: random.Random, port: str) -> list[str]:
        reg = REG_LO[port]
        notes = []
        # (a) SPM word write then read at each size.
        for s in range(4):
            n = 1 << s
            addr = SPM[port] + 0x400 + n * rng.randrange(0x400 // n)
            await self._one(port, self._mk(port, SmcSysAxiOp.WRITE, addr, size=n, rng=rng))
            await self._one(port, self._mk(port, SmcSysAxiOp.READ, addr, size=n))
        # (b) registers: only AxSIZE 2 is compared.
        for s in range(4):
            n = 1 << s
            if s == 2:
                addr = reg + 4 * rng.randrange(4)
                await self._one(port, self._mk(port, SmcSysAxiOp.WRITE, addr, size=4, rng=rng))
                await self._one(port, self._mk(port, SmcSysAxiOp.READ, addr, size=4))
                continue
            if s == 3:
                first = 2 * rng.randrange(2)
                addr = reg + 4 * first
            else:
                first = rng.randrange(4)
                addr = reg + 4 * first + n * rng.randrange(4 // n)
            attrs = {"allow_error": True, "observe": True}
            wr = self._mk(port, SmcSysAxiOp.WRITE, addr, size=n, rng=rng, **attrs)
            await self._one(port, wr)
            rd = self._mk(port, SmcSysAxiOp.READ, addr, size=n, **attrs)
            await self._one(port, rd)
            await self._one(
                port, self._mk(port, SmcSysAxiOp.WRITE, reg + 4 * first, size=4, rng=rng)
            )
            notes.append(
                f"{PORT_NAME[port]} reg size {n}: write {RESP_NAMES[wr.resp_code]} read "
                f"{RESP_NAMES[rd.resp_code]} 0x{rd.rdata:x}"
            )
        # (c) INCR bursts of 8-byte beats, compared beat by beat.
        lengths = [2, 16, 256] + [rng.randint(1, 256) for _ in range(2)]
        for page, beats in enumerate(lengths):
            base = SPM[port] + 0x2000 + 0x1000 * page
            addr = base + 8 * rng.randrange((0x1000 - beats * 8) // 8 + 1)
            await self._one(
                port, self._mk(port, SmcSysAxiOp.WRITE, addr, size=8, beats=beats, rng=rng)
            )
            await self._one(port, self._mk(port, SmcSysAxiOp.READ, addr, size=8, beats=beats))
        # (d) FIXED and WRAP bursts, observe-only, then one fresh word.
        legs = [(FIXED, 4), (FIXED, 16), (WRAP, 2), (WRAP, 4), (WRAP, 8), (WRAP, 16)]
        for i, (burst, beats) in enumerate(legs):
            attrs = {"allow_error": True, "observe": True}
            if burst == FIXED:
                addr = SPM[port] + 0x8000 + 0x400 * i + 8 * rng.randrange(8)
            else:
                addr = SPM[port] + 0x8000 + 0x400 * i + 8 * rng.randrange(beats)
            wr = self._mk(
                port, SmcSysAxiOp.WRITE, addr, size=8, beats=beats, burst=burst, rng=rng, **attrs
            )
            await self._one(port, wr)
            rd = self._mk(port, SmcSysAxiOp.READ, addr, size=8, beats=beats, burst=burst, **attrs)
            await self._one(port, rd)
            notes.append(
                f"{PORT_NAME[port]} {BURST_NAME[burst]}x{beats}: write {RESP_NAMES[wr.resp_code]} "
                f"read {RESP_NAMES[rd.resp_code]}"
            )
        addr = SPM[port] + 0x80
        await self._one(port, self._mk(port, SmcSysAxiOp.WRITE, addr, size=8, rng=rng))
        await self._one(port, self._mk(port, SmcSysAxiOp.READ, addr, size=8))
        # (e) narrow INCR read bursts at the registers, each followed by a register read.
        for _ in range(4):
            s = rng.choice((0, 1))
            n = 1 << s
            beats = rng.randint(2, 4)
            first = rng.randrange((16 - beats * n) // 4 + 1)
            addr = reg + 4 * first
            rd = self._mk(
                port, SmcSysAxiOp.READ, addr, size=n, beats=beats, allow_error=True, observe=True
            )
            await self._one(port, rd)
            await self._one(port, self._mk(port, SmcSysAxiOp.READ, reg, size=4))
            notes.append(
                f"{PORT_NAME[port]} narrow x{beats} size {n}: {RESP_NAMES[rd.resp_code]} "
                f"0x{rd.rdata:x}"
            )
        return notes

    async def _s6(self) -> list[str]:
        rng = self._rng(6)
        notes = []
        for port in PORTS:
            before = self._step_accesses["S6"]
            notes += await self._s6_port(rng, port)
            done = self._step_accesses["S6"] - before
            assert done == 51, f"S6 {PORT_NAME[port]} issued {done} accesses, contract has 51"
        return notes

    def _s7_access(self, rng: random.Random, port: str, used: list[tuple[int, int]]):
        arena, size = SPM[port] + S7_ARENA, S7_ARENA_SIZE
        known = self.golden[port].known_units(arena, arena + size, 8)
        for _ in range(200):
            at_reg = rng.random() < 0.3
            is_write = rng.random() < 0.5
            lock = 1 if rng.random() < 0.125 else 0
            roll = rng.random()
            burst = INCR if roll < 0.7 else (FIXED if roll < 0.85 else WRAP)
            if at_reg or lock:
                burst = INCR
            n = 1 << rng.randrange(4)
            if burst == INCR:
                beats = 1 if lock else rng.randint(1, 16)
            elif burst == FIXED:
                beats = rng.randint(2, 16)
            else:
                beats = rng.choice((2, 4, 8, 16))
            if at_reg:
                base, span = REG_LO[port], 16
                addr = base + n * rng.randrange(span // n)
                beats = min(beats, (base + span - addr) // n)
            elif burst == INCR:
                if known and not is_write and rng.random() < 0.7:
                    addr = rng.choice(known) + n * rng.randrange(8 // n)
                else:
                    addr = arena + n * rng.randrange(size // n)
                beats = min(beats, (arena + size - addr) // n)
            elif burst == FIXED:
                addr = arena + n * rng.randrange(size // n)
            else:
                container = beats * n
                addr = (
                    arena + container * rng.randrange(size // container) + n * rng.randrange(beats)
                )
            lo, hi = self._span(addr, n, beats, burst)
            if any(lo < old_hi and old_lo < hi for old_lo, old_hi in used):
                continue
            used.append((lo, hi))
            observe = bool(lock) or burst != INCR or (at_reg and not (n == 4 and beats == 1))
            attrs = {
                "axi_id": rng.randrange(ID_SPACE[port]),
                "axi_user": rng.randrange(4096),
                "axi_cache": rng.randrange(16),
                "axi_qos": rng.randrange(16),
                "axi_region": rng.randrange(16),
                "axi_lock": lock,
                "prot": rng.randrange(8),
                "allow_error": True,
                "observe": observe,
            }
            op = SmcSysAxiOp.WRITE if is_write else SmcSysAxiOp.READ
            return self._mk(port, op, addr, size=n, beats=beats, burst=burst, rng=rng, **attrs)
        raise AssertionError(f"S7 {port}: no disjoint access found")

    def _s7_compares(self, port: str, item) -> bool:
        """A read of step 7 that will compare: not observed, AxPROT[1] clear, KNOWN span."""
        return (
            item.op is SmcSysAxiOp.READ
            and not item.observe
            and not item.prot & 2
            and self.golden[port].known(item.addr, item.transfer_bytes)
        )

    async def _s7_known_reads(self, rng: random.Random, port: str, need: int) -> list:
        """`need` full-width reads of KNOWN arena words, after one aligned write when none is."""
        arena = SPM[port] + S7_ARENA
        items = []
        units = self.golden[port].known_units(arena, arena + S7_ARENA_SIZE, 8)
        if need > 0 and not units:
            wr = self._mk(
                port, SmcSysAxiOp.WRITE, arena, rng=rng, axi_id=rng.randrange(ID_SPACE[port])
            )
            await self._one(port, wr)
            items.append(wr)
            units = [arena]
        for k in range(need):
            rd = self._mk(
                port, SmcSysAxiOp.READ, units[k % len(units)], axi_id=rng.randrange(ID_SPACE[port])
            )
            await self._one(port, rd)
            items.append(rd)
        return items

    async def _s7_port(self, port: str) -> None:
        rng = self._rng(f"7:{port}")
        compares = 0
        for _ in range(10):
            used: list[tuple[int, int]] = []
            items = [self._s7_access(rng, port, used) for _ in range(4)]
            compares += sum(1 for item in items if self._s7_compares(port, item))
            await self._groups({port: items})
            for item in items:
                self._shape[(item.length, BURST_NAME[item.burst], item.beats)] += 1
        for item in await self._s7_known_reads(rng, port, S7_COMPARE_READS - compares):
            self._shape[(item.length, BURST_NAME[item.burst], item.beats)] += 1

    async def _s7(self) -> None:
        tasks = [cocotb.start_soon(self._s7_port(p)) for p in PORTS]
        for task in tasks:
            await task

    def _log_shape_rows(self) -> None:
        """One line per observe-only access of steps 6 and 7, AxLOCK 1 marked, then the PROT view."""
        for step, port, it in self._shape_rows:
            if not it.observe:
                continue
            cocotb.log.info(
                "OBS-SHAPE: %s %s %s @0x%x AxSIZE=%d AxBURST=%s AxLEN=%d AxLOCK=%d AxPROT=%d resp=%s",
                step,
                PORT_NAME[port],
                it.op.value,
                it.addr,
                (it.length).bit_length() - 1,
                BURST_NAME[it.burst],
                it.beats - 1,
                it.axi_lock,
                it.prot,
                RESP_NAMES[it.resp_code],
            )
        rows = [(p, it) for step, p, it in self._shape_rows if step == "S7"]
        parts = []
        for p in PORTS:
            hi = [it for q, it in rows if q == p and it.prot & 2]
            lo = [it for q, it in rows if q == p and not it.prot & 2]
            parts.append(
                f"{PORT_NAME[p]} AxPROT[1]=1: {len(hi)} accesses, {sum(1 for i in hi if i.resp_code == DECERR)} DECERR "
                f"({sum(1 for i in hi if i.resp_code == DECERR and i.op is SmcSysAxiOp.READ)} reads, "
                f"{sum(1 for i in hi if i.resp_code == DECERR and i.op is SmcSysAxiOp.WRITE)} writes); "
                f"AxPROT[1]=0: {len(lo)} accesses, {sum(1 for i in lo if i.resp_code == DECERR)} DECERR"
            )
        cocotb.log.info(
            "OBS-SHAPE-PROT: step 7 DECERR by AxPROT[1], observed and not graded: %s",
            "; ".join(parts),
        )

    def _shape_text(self) -> str:
        by_size: Counter = Counter()
        by_burst: Counter = Counter()
        by_len: Counter = Counter()
        for (size, burst, beats), count in self._shape.items():
            by_size[size] += count
            by_burst[burst] += count
            by_len[beats] += count
        return (
            f"step 7 counts by size {dict(sorted(by_size.items()))}, burst {dict(by_burst)}, "
            f"AxLEN+1 {dict(sorted(by_len.items()))}"
        )

    def _profile(self, rng: random.Random) -> AxiTimingProfile:
        b_hold, r_hold = rng.randint(64, 96), rng.randint(64, 96)
        aw, w = rng.randint(0, 16), rng.randint(0, 16)
        return AxiTimingProfile(
            aw_delay=max(aw - w, 0),
            w_delay=max(w - aw, 0),
            ar_delay=rng.randint(0, 16),
            b_ready_delay=b_hold,
            r_ready_delay=r_hold,
        )

    @staticmethod
    def _give_ids(items, ids) -> None:
        for item, ident in zip(items, ids):
            item.axi_id = ident

    async def _s8(self) -> str:
        rng = self._rng(8)
        notes = []
        for depth in (4, 8, 9, 16, 24):
            plan = {}
            for port in PORTS:
                items = self._spm_items(rng, port, depth // 2, depth - depth // 2)
                distinct = port != "JTAG" or depth <= 4
                self._give_ids(items, self._ids(rng, port, depth, distinct=distinct))
                plan[port] = items
            out = await self._groups(plan)
            notes.append(f"depth {depth}: " + "; ".join(out.values()))
        plan = {}
        for port in PORTS:
            items = self._spm_items(rng, port, 4, 4)
            ids = [1, 2] * 4
            rng.shuffle(ids)
            self._give_ids(items, ids)
            plan[port] = items
        out = await self._groups(plan)
        notes.append("same-ID {1,2}: " + "; ".join(out.values()))
        plan, timing, watches, outs = {}, {}, {}, []
        for port in PORTS:
            items = self._spm_items(rng, port, 8, 8, reg_w=2, reg_r=2)
            self._give_ids(items, [rng.choice((1, 2)) for _ in range(16)])
            plan[port] = items
            timing[port] = self._profile(rng)
        # One port at a time: a response of one port held at the manager can back up the
        # shared fabric and delay another port's first response past its own hold.
        for port in PORTS:
            watch = SmcRawRStallWatch(cocotb.top, PREFIX[port], R_RAW_VALID.get(port))
            watches[port] = watch
            watcher = cocotb.start_soon(watch.run())
            outs.append(await self._groups({port: plan[port]}, {port: timing[port]}))
            watch.stop = True
            await watcher
        stalls = {}
        for port, watch in watches.items():
            stalls[port] = dict(watch.stalls)
            assert watch.stalls["b"] > 0 and watch.stalls["r"] > 0, (
                f"S8 {PORT_NAME[port]} manager hold {timing[port].summary()} never held a "
                f"response: stalls {watch.stalls} valid cycles {watch.valid_cycles} of {watch.cycles}"
            )
        notes.append(
            "manager holds reached the bus (b, r stall counts above 0): "
            + "; ".join(
                f"{PORT_NAME[p]} {timing[p].summary()} b/r stalls {stalls[p]['b']}/{stalls[p]['r']}"
                for p in PORTS
            )
            + "; DUT-side stalls are printed and not graded: "
            + "; ".join(
                f"{PORT_NAME[p]} aw={stalls[p]['aw']} w={stalls[p]['w']} ar={stalls[p]['ar']}"
                for p in PORTS
            )
        )
        return (
            "per port and per AxID the recorded B responses, R beats and R words equal the requests "
            "for depths 4, 8, 9, 16, 24 (61 accesses per port), for the AxID set {1, 2} on all three "
            "ports and under the manager stall profiles with the b and r stall counters "
            "above 0 on every port; every access completed within the guard; response order "
            "is printed and not graded, and accesses beyond the configured limits are answered "
            "rather than refused: " + " | ".join(notes)
        )

    def _outside_items(self, rng, port: str, n: int):
        items = self._out_items(rng, port, n // 2, n - n // 2, allow_error=True, observe=True)
        self._give_ids(items, self._ids(rng, port, n))
        for item in items:
            self._env.axi_monitor.expected_decerr_addrs.add(item.addr)
        return items

    def _out_window_events(self, mark: int, port: str = "JTAG"):
        lo, hi = OUT[port], OUT[port] + WINDOW
        return [e for e in self.sampler.since(mark) if lo <= e.addr < hi]

    async def _s9(self) -> tuple[str, str]:
        rng = self._rng(9)
        deep, others = [], []
        for kind in ("read", "write"):
            for depth in (1, 8, 16):
                n_w, n_r = (0, depth) if kind == "read" else (depth, 0)
                items = self._out_items(rng, "JTAG", n_w, n_r)
                self._give_ids(items, [i % 4 for i in range(depth)])
                plan = {"JTAG": items}
                concurrent = kind == "read" and depth == 8
                saved_decerr = None
                if concurrent:
                    monitor = self._env.axi_monitor
                    saved_decerr = set(monitor.expected_decerr_addrs)
                    for port in ("SYS", "SEP"):
                        plan[port] = self._outside_items(rng, port, 8)
                w0, r0 = output_responder_counts()
                mark = self.sampler.mark()
                try:
                    out = await self._groups(plan)
                finally:
                    if saved_decerr is not None:
                        monitor.expected_decerr_addrs.clear()
                        monitor.expected_decerr_addrs.update(saved_decerr)
                w1, r1 = output_responder_counts()
                seen = self._out_window_events(mark)
                assert [e.chan for e in seen].count("aw") == n_w and [e.chan for e in seen].count(
                    "ar"
                ) == n_r, f"S9 JTAG {kind} depth {depth}: OUT2 handshakes {len(seen)}"
                if concurrent:
                    others.append(
                        "JTAG depth-8 read group outstanding: "
                        + "; ".join(
                            f"{PORT_NAME[p]} codes {[RESP_NAMES[i.resp_code] for i in plan[p]]}"
                            for p in ("SYS", "SEP")
                        )
                        + f"; responder counter deltas beyond the 8 JTAG reads: write {w1 - w0}, read {r1 - r0 - 8}"
                    )
                else:
                    assert (w1 - w0, r1 - r0) == (n_w, n_r), (
                        f"S9 JTAG {kind} depth {depth}: responder counters advanced "
                        f"{w1 - w0} writes {r1 - r0} reads, issued {n_w}/{n_r}"
                    )
                deep.append(f"{kind} depth {depth}: {out['JTAG']}")
        # (c) JTAG split between SPM2 and OUT2 with SYS_IN and SEP_IN local traffic.
        local = self._spm_items(rng, "JTAG", 4, 4, regs=False)
        remote = self._out_items(rng, "JTAG", 4, 4)
        jtag = local + remote
        rng.shuffle(jtag)
        self._give_ids(jtag, [i % 4 for i in range(16)])
        plan = {"JTAG": jtag}
        for port in ("SYS", "SEP"):
            items = self._spm_items(rng, port, 8, 8)
            self._give_ids(items, self._ids(rng, port, 16))
            plan[port] = items
        w0, r0 = output_responder_counts()
        mark = self.sampler.mark()
        out = await self._groups(plan)
        w1, r1 = output_responder_counts()
        seen = self._out_window_events(mark)
        assert len(seen) == 8, f"S9 three-task group: {len(seen)} OUT2 handshakes, issued 8"
        assert (w1 - w0, r1 - r0) == (4, 4), (
            f"S9 three-task group: responder counters advanced {w1 - w0}/{r1 - r0}, JTAG issued 4/4"
        )
        deep.append("three tasks: " + "; ".join(out.values()))
        return (
            "JTAG groups of depth 1, 8, 16 of reads then writes (50 accesses) and the JTAG split "
            "between SPM2 and OUT2 completed within the guard; per AxID the B count and returned "
            "words match the requests, every OKAY read word equals the responder word of its own "
            "address, the responder write and read counters and the OUT2 AW/AR handshakes advanced "
            "by exactly the JTAG accesses issued to OUT2 in each group, local SYS_IN and SEP_IN "
            "traffic returned its own words; response order is printed and not graded, as is the "
            "depth beyond what the fabric admits: " + " | ".join(deep)
        ), (
            "all 16 SYS_IN and SEP_IN accesses at OUT0 and OUT1 presented while the JTAG depth-8 "
            "group was outstanding completed within the guard at their own port; response codes "
            "and counter deltas printed, nothing graded on them; the "
            "concurrent JTAG group still returned its own words and IDs: " + " | ".join(others)
        )

    async def _s10(self) -> str:
        rng = self._rng(10)
        mem = self.mem
        notes = []
        profiles = (
            ("delay 1-8", lambda: mem.set_response_delay([rng.randint(1, 8) for _ in range(24)])),
            (
                "delay 32-64",
                lambda: mem.set_response_delay([rng.randint(32, 64) for _ in range(24)]),
            ),
            (
                "aw/ar stall 16",
                lambda: mem.enable_backpressure(channels=("aw", "ar"), stall_cycles=16),
            ),
            (
                "delay 0-64 depth 8",
                lambda: mem.set_response_delay([rng.randint(0, 64) for _ in range(24)]),
            ),
        )
        for label, arm in profiles:
            items = self._out_items(rng, "JTAG", 12, 12)
            self._give_ids(items, [i % 4 for i in range(24)])
            w0, r0 = output_responder_counts()
            mark = self.sampler.mark()
            arm()
            try:
                out = await self._groups({"JTAG": items})
            finally:
                mem.clear_response_delay()
                mem.disable_backpressure()
            w1, r1 = output_responder_counts()
            seen = self.sampler.since(mark)
            issued_w = sorted(i.addr for i in items if i.op is SmcSysAxiOp.WRITE)
            issued_r = sorted(i.addr for i in items if i.op is SmcSysAxiOp.READ)
            assert sorted(e.addr for e in seen if e.chan == "aw") == issued_w, (
                f"S10 {label}: AW addresses at the responder differ from the writes issued"
            )
            assert sorted(e.addr for e in seen if e.chan == "ar") == issued_r, (
                f"S10 {label}: AR addresses at the responder differ from the reads issued"
            )
            assert (w1 - w0, r1 - r0) == (12, 12), (
                f"S10 {label}: responder counters advanced {w1 - w0} writes {r1 - r0} reads, "
                f"issued 12/12"
            )
            notes.append(f"{label}: {out['JTAG']}")
        return (
            "under the four profiles all 96 JTAG accesses completed within the guard, per AxID the "
            "B count and returned words match the requests, every OKAY read word equals the "
            "responder word of its address, the AW and AR address sets at the responder equal the "
            "sets issued and the responder counters advanced by 24 per profile; response order "
            "under each profile is printed and not graded: " + " | ".join(notes)
        )

    def _inject(self, item, code: int) -> None:
        is_read = item.op is SmcSysAxiOp.READ
        self.mem.inject_error(item.addr, code, read=is_read, write=not is_read)
        item.observe = True

    @staticmethod
    def _tally(items, injected: dict) -> Counter:
        want: Counter = Counter()
        for index, code in injected.items():
            want[
                ("r_" if items[index].op is SmcSysAxiOp.READ else "b_") + RESP_NAMES[code].lower()
            ] += 1
        return want

    def _check_monitor(self, before: dict, after: dict, want: Counter, label: str) -> None:
        for key in ("b_slverr", "b_decerr", "r_slverr", "r_decerr"):
            assert after[key] - before[key] == want.get(key, 0), (
                f"S11 {label}: responder monitor counted {after[key] - before[key]} {key}, "
                f"injected {want.get(key, 0)}"
            )

    async def _s11(self) -> tuple[str, str]:
        rng = self._rng(11)
        mon = self._env.output_axi_monitor
        mon.allow_slverr = True
        mon.allow_decerr = True
        seen = []
        # (a) one-shot injections, each followed by an ordinary write-then-read.
        count = 0
        for rnd in range(3):
            for label, code, is_read in (
                ("wr_slverr", SLVERR, False),
                ("wr_decerr", DECERR, False),
                ("rd_slverr", SLVERR, True),
                ("rd_decerr", DECERR, True),
            ):
                addr = OUT["JTAG"] + self._out_next["JTAG"]
                self._out_next["JTAG"] += 8
                ident = count % 4
                count += 1
                before = mon.snapshot()
                self.mem.inject_error(addr, code, read=is_read, write=not is_read)
                attrs = {
                    "axi_id": ident,
                    "allow_error": True,
                    "observe": True,
                    "capture_resp_id": True,
                }
                if is_read:
                    item = self._mk("JTAG", SmcSysAxiOp.READ, addr, **attrs)
                else:
                    item = self._mk("JTAG", SmcSysAxiOp.WRITE, addr, rng=rng, **attrs)
                await self._one("JTAG", item)
                got_id = item.rid if is_read else item.bid
                assert got_id == ident, (
                    f"S11 {label} round {rnd}: response ID {got_id}, request ID {ident}"
                )
                key = ("r_" if is_read else "b_") + RESP_NAMES[code].lower()
                self._check_monitor(
                    before, mon.snapshot(), Counter({key: 1}), f"{label} round {rnd}"
                )
                wr = self._mk("JTAG", SmcSysAxiOp.WRITE, addr, rng=rng, axi_id=ident)
                await self._one("JTAG", wr)
                rd = self._mk("JTAG", SmcSysAxiOp.READ, addr, axi_id=ident)
                await self._one("JTAG", rd)
                assert wr.resp_code == 0 and rd.resp_code == 0 and rd.rdata == wr.wdata, (
                    f"S11 {label} round {rnd}: ordinary write {wr.resp_code} read {rd.resp_code} "
                    f"0x{rd.rdata:x}, wrote 0x{wr.wdata:x}"
                )
                seen.append(f"{label}->{RESP_NAMES[item.resp_code]}")
        # (b) one group of 24 with a seeded third injected.
        items = self._out_items(rng, "JTAG", 12, 12, allow_error=True)
        self._give_ids(items, [i % 4 for i in range(24)])
        injected = {i: rng.choice((SLVERR, DECERR)) for i in sorted(rng.sample(range(24), 8))}
        for index, code in injected.items():
            self._inject(items[index], code)
        before = mon.snapshot()
        out_b = await self._groups({"JTAG": items})
        self._check_monitor(before, mon.snapshot(), self._tally(items, injected), "group of 24")
        pairs_b = [
            f"{items[i].op.value[0]}{items[i].axi_id}:{RESP_NAMES[c]}->{RESP_NAMES[items[i].resp_code]}"
            for i, c in injected.items()
        ]
        errors_text = (
            f"the 12 one-shot injections [{' '.join(seen)}] and the injected third of the group of "
            f"24 [{' '.join(pairs_b)}] each completed within the guard at the originating port "
            f"with its own ID, the responder monitor counted exactly the injected codes on the "
            f"wire, and each ordinary write-then-read after an injection answered OKAY and returned "
            f"the word written; the code at the inbound port is printed next to the injected one, "
            f"not graded; {out_b['JTAG']}"
        )
        # (c) delay, ready stall and reorder with injected errors while local traffic is outstanding.
        items = self._out_items(rng, "JTAG", 12, 12, allow_error=True)
        self._give_ids(items, [i % 4 for i in range(24)])
        injected = {i: rng.choice((SLVERR, DECERR)) for i in sorted(rng.sample(range(24), 8))}
        for index, code in injected.items():
            self._inject(items[index], code)
        self.mem.set_response_delay([rng.randint(0, 64) for _ in range(24)])
        stall = rng.choice((4, 8, 16))
        self.mem.enable_backpressure(channels=("aw", "ar"), stall_cycles=stall)
        plan = {"JTAG": items}
        for port in ("SYS", "SEP"):
            local = self._spm_items(rng, port, 6, 6)
            self._give_ids(local, self._ids(rng, port, 12))
            plan[port] = local
        before = mon.snapshot()
        out_c = await self._groups(plan)
        self._check_monitor(before, mon.snapshot(), self._tally(items, injected), "stressed group")
        for port in ("SYS", "SEP"):
            assert all(i.resp_code == 0 for i in plan[port]), (
                f"S11 {PORT_NAME[port]} local access not OKAY while the responder is stressed: "
                f"{[RESP_NAMES[i.resp_code] for i in plan[port]]}"
            )
        pairs_c = [
            f"{items[i].op.value[0]}{items[i].axi_id}:{RESP_NAMES[c]}->{RESP_NAMES[items[i].resp_code]}"
            for i, c in injected.items()
        ]
        combined_text = (
            f"with response delay 0-64, aw/ar ready stall {stall}, the depth-8 reorder and the "
            f"injected third [{' '.join(pairs_c)}] on the JTAG group of 24 at OUT2, all 24 SYS_IN "
            f"and SEP_IN accesses answered OKAY within the guard at their own port with the golden "
            f"word of their own address, every JTAG access completed at the JTAG port with its own "
            f"ID (code and order are printed and not graded) and "
            f"every OKAY JTAG read word equals the responder word of its address: "
            + "; ".join(out_c.values())
        )
        return errors_text, combined_text

    async def _s12(self) -> None:
        mon = self._env.output_axi_monitor
        mon.allow_slverr = False
        mon.allow_decerr = False
        self.mem.clear_errors()
        self.mem.disable_backpressure()
        self.mem.clear_response_delay()
        await self._program_filter(RESET_CFG, RESET_START, RESET_END)
        for symbol, count in ((_SCRATCH, 8), (_WARM, 4)):
            for index in range(count):
                await self._csr4(smc_indexed_addr(symbol, index), 0)
        for rec in self.rec.values():
            rec.stop = True
        self.sampler.stop = True
        for task in self._watchers:
            await task

    async def _csr4(self, addr: int, data: int) -> None:
        item = self._mk("SEP", SmcSysAxiOp.WRITE, addr, size=4, data=data.to_bytes(4, "little"))
        await self._one("SEP", item)

    # ---------------------------------------------------------------------- body
    async def body(self) -> None:
        await self._s1()
        self._mark_step("S1")

        self._step = "S2"
        text = await self._s2()
        self._mark_step("S2")
        self._log_chk("CHK-RAND-ID-ECHO", text)

        self._step = "S3"
        text = await self._s3()
        self._mark_step("S3")
        self._log_chk("CHK-RAND-ATTR-OWN-WORD", text)

        self._step = "S4"
        text = await self._s4()
        self._mark_step("S4")
        self._log_chk("CHK-RAND-LOCK-OBS", text)

        self._step = "S5"
        text = await self._s5()
        self._mark_step("S5")
        self._log_chk("CHK-RAND-OUT-SIDEBAND", text)

        self._step = "S6"
        notes6 = await self._s6()
        self._mark_step("S6")

        self._step = "S7"
        await self._s7()
        self._mark_step("S7")
        self._log_shape_rows()
        floors = {
            "S6": [self._compare_floor("S6", p, every=True) for p in PORTS],
            "S7": [self._compare_floor("S7", p) for p in PORTS],
        }
        self._log_chk(
            "CHK-RAND-SHAPE-BY-ADDR",
            f"all {self._step_accesses['S6']} + {self._step_accesses['S7']} accesses of steps 6 and "
            f"7 completed within the guard with defined data, each beat count equals AxLEN+1, every "
            f"OKAY read at a KNOWN byte returned the golden byte of its own address (reads at KNOWN "
            f"bytes compared/issued: step 6 {', '.join(floors['S6'])}, step 7 "
            f"{', '.join(floors['S7'])}; {self._cmp_bytes['S6'] + self._cmp_bytes['S7']} bytes "
            f"compared), recovery write-then-reads returned the fresh "
            f"word; responses of FIXED, WRAP, narrow register and AxLOCK 1 accesses printed "
            f"are printed and not graded: {self._shape_text()}; " + " | ".join(notes6),
        )

        self._step = "S8"
        text = await self._s8()
        self._mark_step("S8")
        self._log_chk("CHK-RAND-LOCAL-DEEP", text)

        self._step = "S9"
        deep, others = await self._s9()
        self._mark_step("S9")
        self._log_chk("CHK-RAND-OUT-DEEP", deep)
        self._log_chk("CHK-RAND-OUT-OTHER-PORTS-OBS", others)

        self._step = "S10"
        text = await self._s10()
        self._mark_step("S10")
        self._log_chk("CHK-RAND-RESP-TIMING", text)

        self._step = "S11"
        errors_text, combined_text = await self._s11()
        self._mark_step("S11")
        self._log_chk("CHK-RAND-RESP-ERRORS-OBS", errors_text)
        self._log_chk("CHK-RAND-RESP-COMBINED", combined_text)

        self._step = "S12"
        await self._s12()
        self._mark_step("S12")

        self._log_chk(
            "CHK-TIMEOUT-PATHS",
            f"bounded waits: fuse sense {FUSE_SENSE_BOUND} smc cycles; every access is bounded by "
            f"the {AXI_TIMEOUT_NS} ns driver guard and its expiry raises AssertionError naming the "
            f"port, step and address; no other wait is used",
        )
        self._nonvac_fence()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == STEPS, f"step ids {ids}, want {STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        marks = [(c, t) for c, t in self._chk_marks if c != "CHK-TIMEOUT-PATHS"]
        assert tuple(c for c, _ in marks) == tuple(c for c, _ in CHECKERS), (
            f"checker lines {[c for c, _ in marks]}"
        )
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(marks, CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        for port in PORTS:
            assert self.rec[port].events, f"the {PORT_NAME[port]} recorder saw no response"
        assert any(e.chan == "aw" for e in self.sampler.events), (
            "no AW handshake sampled at SYS_OUT"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; RAND-SEED %d; checker lines %s; recorder responses %s; "
            "AW handshakes at the responder %d; accesses %d; stamps %s",
            "<".join(STEPS),
            self.seed,
            ",".join(c for c, _ in self._chk_marks),
            {PORT_NAME[p]: len(self.rec[p].events) for p in PORTS},
            sum(1 for e in self.sampler.events if e.chan == "aw"),
            self.accesses,
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
