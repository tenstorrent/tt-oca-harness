# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded one-shot SLVERR and DECERR injections at the SYS_OUT responder per manager.

Sources: AMBA AXI4 (the response of a transaction is the subordinate's); zeroer.adoc
(Outstanding Transaction Management, Status Features); dma.adoc (Submission and Completion).

The seed draws eight passes: five pinned legs (a JTAG single access, a JTAG group, a DMA read, a
DMA write and a zeroer write) in a drawn order and three drawn freely, and per pass the code,
the burst or group member that takes the error and the recovery address. One uninjected zeroer
job and one uninjected DMA copy in S1 give the burst addresses the injections are keyed to.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
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
    DMA_CTRL_STATUS_0,
)
from .smc_output_fabric_vip_utils import (
    RESP_DECERR,
    RESP_OKAY,
    RESP_SLVERR,
    output_fabric_pass_all_cfg_seq,
)
from .smc_zeroer_resp_unchecked_test_seq import (
    STATUS_BM,
    ZEROER_CTRL_STATUS,
    ZEROER_CTRL_STATUS_START,
    ZEROER_DEST_ADDR,
    ZEROER_SIZE,
)

PASSES = 8
MANAGERS = ("JTAG", "DMA", "ZEROER")
POSITIONS = ("first", "middle", "last")
# Pinned legs: (manager, direction, JTAG group); every seed runs each of them once.
PINNED = (
    ("JTAG", None, False),
    ("JTAG", None, True),
    ("DMA", "read", None),
    ("DMA", "write", None),
    ("ZEROER", "write", None),
)
# Source salt of a recovery copy, distinct from the errored copy of the same pass.
RECOVERY_SALT = 0x80
CODES = {RESP_SLVERR: "SLVERR", RESP_DECERR: "DECERR"}
GROUP_MIN = 4
GROUP_MAX = 16
JTAG_IDS = 4
# ID of every JTAG access other than a single injected one (group members, recovery accesses).
# A single injected access draws its ID from 1 to JTAG_IDS - 1.
JTAG_DEFAULT_ID = 0
MIN_BURSTS = 3
JTAG_BASE = 0x0200_0000
JTAG_PASS_SPAN = 0x100
RECOVERY_BASE = 0x0210_0000
RECOVERY_WORDS = 4096
ZEROER_BASE = 0x0220_0000
ZEROER_BYTES = 12 * 1024
DMA_SRC = 0x0230_0000
DMA_DST = 0x0240_0000
DMA_BYTES = 6 * 1024
POISON = 0xA5
FUSE_BOUND = 200_000
ZEROER_POLLS = 40_000
DMA_POLLS = 3000
DMA_ERR_POLLS = 200
DMA_POLL_CYCLES = 50
_STEP_OF = {"JTAG": "S2", "ZEROER": "S3", "DMA": "S4"}
_CHECKERS = (
    ("CHK-SOE-JTAG-CODE", "S2"),
    ("CHK-SOE-ZEROER-CONSUMED", "S3"),
    ("CHK-SOE-DMA-RETIRES", "S4"),
    ("CHK-SOE-MONITOR-TALLY", "S5"),
    ("CHK-SOE-RECOVERY", "S5"),
)


def _pattern(addr: int, salt: int) -> int:
    return ((addr * 29) ^ (addr >> 5) ^ (salt * 0x3B) ^ 0x6D) & 0xFF


class _Pass:
    def __init__(self, n: int) -> None:
        self.n = n
        self.manager = ""
        self.direction = ""
        self.code = RESP_SLVERR
        self.position = ""
        self.group = 0
        self.recovery = 0
        self.axi_id = JTAG_DEFAULT_ID

    def __str__(self) -> str:
        shape = ""
        if self.manager == "JTAG":
            shape = f" group {self.group}" if self.group else f" single ID {self.axi_id}"
        return (
            f"P{self.n} {self.manager} {self.direction} {CODES[self.code]} {self.position}"
            f"{shape} recovery 0x{self.recovery:x}"
        )


class _Sampler:
    """Records every SYS_OUT AR and AW handshake: (address, AxLEN, AxSIZE)."""

    def __init__(self) -> None:
        self.ar: list[tuple[int, int, int]] = []
        self.aw: list[tuple[int, int, int]] = []

    async def run(self) -> None:
        top = cocotb.top
        ifc = top.u_output_axi_if
        while True:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            for ch, store in (("ar", self.ar), ("aw", self.aw)):
                sigs = [getattr(top, f"tb_output_axi_{ch}{n}") for n in ("valid", "ready", "addr")]
                shape = [getattr(ifc, f"{ch}{n}") for n in ("len", "size")]
                assert all(s.value.is_resolvable for s in sigs + shape), f"{ch} probes are X/Z"
                valid, ready, addr = (int(s.value) for s in sigs)
                if valid and ready:
                    store.append((addr, int(shape[0].value), int(shape[1].value)))


class smc_sys_out_error_inject_rand_test_seq(output_fabric_pass_all_cfg_seq):
    """Drawn SYS_OUT error injections on JTAG, DMA and zeroer traffic, each with recovery."""

    def __init__(self, name: str = "smc_sys_out_error_inject_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.passes: list[_Pass] = []
        self.done_passes = 0
        self.jtag_accesses = 0
        self.chk_seen: dict[str, str] = {}
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._fuse_last: dict[str, int] = {}
        self._last = {"zeroer": "unused", "dma": "unused", "dma_err": "unused"}
        self._lines: dict[str, list[str]] = {c: [] for c, _ in _CHECKERS}
        self.sampler = _Sampler()

    # -- plumbing ---------------------------------------------------------

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, len(self._stamps)))
        self.chk_seen[chk_id] = text

    @property
    def _mem(self):
        responder = self.cfg.sys_out_mem
        assert responder is not None, "SYS_OUT responder not bound"
        return responder

    async def _jtag(self, item) -> None:
        await _OneShot(item, f"{item.get_name()}_os").start(self.env.jtag_axi_agent.sequencer)
        self.jtag_accesses += len(item.items) if isinstance(item, SmcSysAxiGroupItem) else 1

    @staticmethod
    def _burst_bytes(burst: tuple[int, int, int]) -> int:
        return (burst[1] + 1) << burst[2]

    # -- draw -------------------------------------------------------------

    def _draw(self) -> None:
        rng = self.rng
        legs = list(PINNED)
        rng.shuffle(legs)
        legs += [(rng.choice(MANAGERS), None, None) for _ in range(PASSES - len(PINNED))]
        for n, (manager, direction, group) in enumerate(legs):
            p = _Pass(n)
            p.manager = manager
            if manager == "ZEROER":
                p.direction = "write"
            else:
                p.direction = direction or rng.choice(("read", "write"))
            p.code = rng.choice(tuple(CODES))
            p.position = rng.choice(POSITIONS)
            if manager == "JTAG" and (rng.choice((False, True)) if group is None else group):
                p.group = rng.randint(GROUP_MIN, GROUP_MAX)
            if manager == "JTAG" and not p.group:
                p.axi_id = rng.randint(1, JTAG_IDS - 1)
                assert p.axi_id != JTAG_DEFAULT_ID, f"P{n}: single access ID {p.axi_id}"
            p.recovery = RECOVERY_BASE + 8 * rng.randrange(RECOVERY_WORDS)
            self.passes.append(p)
        managers = [p.manager for p in self.passes]
        assert set(managers) == set(MANAGERS), f"managers {managers}"
        jtag = [p for p in self.passes if p.manager == "JTAG"]
        dma = {p.direction for p in self.passes if p.manager == "DMA"}
        assert any(p.group for p in jtag) and not all(p.group for p in jtag), f"JTAG {jtag}"
        assert dma == {"read", "write"}, f"DMA directions {dma}"
        assert all(p.direction == "write" for p in self.passes if p.manager == "ZEROER")
        assert all(GROUP_MIN <= p.group <= GROUP_MAX for p in self.passes if p.group)
        singles = [p for p in jtag if not p.group]
        assert all(1 <= p.axi_id < JTAG_IDS for p in singles), f"single IDs {singles}"
        assert all(p.axi_id == JTAG_DEFAULT_ID for p in self.passes if p not in singles)

    @staticmethod
    def _index(position: str, count: int) -> int:
        return {"first": 0, "middle": count // 2, "last": count - 1}[position]

    # -- zeroer -----------------------------------------------------------

    async def _zeroer_job(self, label: str) -> tuple[int, int]:
        await self.csr_write(
            f"ZEROER_START_{label}", ZEROER_CTRL_STATUS, ZEROER_CTRL_STATUS_START, length=8
        )
        for n in range(ZEROER_POLLS):
            word = await self.csr_read(f"ZEROER_POLL_{label}", ZEROER_CTRL_STATUS, length=8)
            self._last["zeroer"] = f"{label}: STATUS {int(bool(word & STATUS_BM))} after {n} polls"
            if not word & STATUS_BM:
                return word, n
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(f"{label}: zeroer STATUS still 1 after {ZEROER_POLLS} polls")

    def _poison(self, base: int, size: int) -> None:
        self._mem.write(base, bytes([POISON]) * size)

    async def _zeroer_baseline(self) -> None:
        await self.csr_write("ZEROER_DEST", ZEROER_DEST_ADDR, ZEROER_BASE, length=8)
        await self.csr_read("ZEROER_DEST_RB", ZEROER_DEST_ADDR, ZEROER_BASE, length=8)
        await self.csr_write("ZEROER_SIZE", ZEROER_SIZE, ZEROER_BYTES, length=8)
        await self.csr_read("ZEROER_SIZE_RB", ZEROER_SIZE, ZEROER_BYTES, length=8)
        self._poison(ZEROER_BASE, ZEROER_BYTES)
        aw0 = len(self.sampler.aw)
        word, _ = await self._zeroer_job("BASELINE")
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self.zeroer_bursts = list(self.sampler.aw[aw0:])
        assert len(self.zeroer_bursts) >= MIN_BURSTS, (
            f"the {ZEROER_BYTES}-byte zeroer job issued {len(self.zeroer_bursts)} bursts"
        )
        for addr, _, _ in self.zeroer_bursts:
            assert ZEROER_BASE <= addr < ZEROER_BASE + ZEROER_BYTES, f"zeroer AW 0x{addr:x}"
        left = sum(1 for b in self._mem.read(ZEROER_BASE, ZEROER_BYTES) if b)
        assert left == 0, f"baseline zeroer job left {left} non-zero bytes"
        assert word & ~STATUS_BM == ZEROER_CTRL_STATUS_START, f"CTRL_STATUS 0x{word:x}"

    async def _zeroer_pass(self, p: _Pass) -> None:
        idx = self._index(p.position, len(self.zeroer_bursts))
        burst = self.zeroer_bursts[idx]
        self._poison(ZEROER_BASE, ZEROER_BYTES)
        self._mem.inject_error(burst[0], p.code, read=False, write=True)
        word, polls = await self._zeroer_job(f"P{p.n}")
        status = int(bool(word & STATUS_BM))
        other = word & ~STATUS_BM
        assert status == 0 and other == ZEROER_CTRL_STATUS_START, (
            f"P{p.n}: CTRL_STATUS 0x{word:x}: STATUS {status}, other bits 0x{other:x}, want "
            f"STATUS 0 and INT_EN alone (0x{ZEROER_CTRL_STATUS_START:x})"
        )
        size = self._burst_bytes(burst)
        data = bytes(self._mem.read(burst[0], size))
        self._lines["CHK-SOE-ZEROER-CONSUMED"].append(
            f"{p} burst {idx}/{len(self.zeroer_bursts)} @0x{burst[0]:x}: STATUS 0 after "
            f"{polls} polls, CTRL_STATUS outside STATUS 0x{other:x} (INT_EN); errored burst "
            f"bytes printed: {sum(1 for b in data if b)} of {size} non-zero, head {data[:16].hex()}"
        )

    # -- DMA --------------------------------------------------------------

    async def _dma_program(self, label: str) -> None:
        for reg, value in (
            (DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND),
            (DMA_CTRL_DST_ADDRESS_LO, DMA_DST & 0xFFFF_FFFF),
            (DMA_CTRL_DST_ADDRESS_HI, DMA_DST >> 32),
            (DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC & 0xFFFF_FFFF),
            (DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC >> 32),
            (DMA_CTRL_LENGTH_LO, DMA_BYTES),
            (DMA_CTRL_LENGTH_HI, 0),
            (DMA_CTRL_DST_STRIDE_LO, 0),
            (DMA_CTRL_DST_STRIDE_HI, 0),
            (DMA_CTRL_SRC_STRIDE_LO, 0),
            (DMA_CTRL_SRC_STRIDE_HI, 0),
            (DMA_CTRL_NUM_REPETITIONS_LO, 1),
            (DMA_CTRL_NUM_REPETITIONS_HI, 0),
        ):
            await self.csr_write(f"{label}_0x{reg & 0xFFF:03x}", reg, value)

    async def _dma_launch(self, label: str) -> int:
        await self._dma_program(label)
        ident = await self.csr_read(f"{label}_NEXT_ID", DMA_CTRL_NEXT_ID_0)
        assert ident != 0, f"{label}: NEXT_ID_0 returned 0"
        return ident

    async def _dma_poll(self, label: str, ident: int, polls: int, key: str) -> tuple[bool, int]:
        done = -1
        for n in range(polls):
            done = await self.csr_read(f"{label}_DONE", DMA_CTRL_DONE_0)
            self._last[key] = f"{label}: DONE_0 {done}, id {ident}, after {n} polls"
            if done == ident:
                return True, done
            await ClockCycles(cocotb.top.clk_smc_i, DMA_POLL_CYCLES)
        return False, done

    def _dma_seed(self, salt: int) -> bytes:
        src = bytes(_pattern(DMA_SRC + i, salt) for i in range(DMA_BYTES))
        self._mem.write(DMA_SRC, src)
        self._poison(DMA_DST, DMA_BYTES)
        return src

    def _dma_compare(self, label: str, src: bytes) -> None:
        got = bytes(self._mem.read(DMA_DST, DMA_BYTES))
        if got != src:
            idx = next(i for i, (a, b) in enumerate(zip(got, src)) if a != b)
            raise AssertionError(
                f"{label}: destination byte 0x{DMA_DST + idx:x} is 0x{got[idx]:02x}, want "
                f"0x{src[idx]:02x}"
            )

    async def _dma_baseline(self) -> None:
        src = self._dma_seed(0xFF)
        ar0, aw0 = len(self.sampler.ar), len(self.sampler.aw)
        ident = await self._dma_launch("DMA_BASE")
        ok, done = await self._dma_poll("DMA_BASE", ident, DMA_POLLS, "dma")
        assert ok, f"baseline copy id {ident}: DONE_0 {done} after {DMA_POLLS} polls"
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self.dma_bursts = {"read": self.sampler.ar[ar0:], "write": self.sampler.aw[aw0:]}
        for direction, bursts in self.dma_bursts.items():
            assert len(bursts) >= MIN_BURSTS, (
                f"the {DMA_BYTES}-byte copy issued {len(bursts)} {direction} bursts"
            )
        self._dma_compare("DMA_BASE", src)

    async def _dma_pass(self, p: _Pass) -> None:
        bursts = self.dma_bursts[p.direction]
        idx = self._index(p.position, len(bursts))
        burst = bursts[idx]
        err_src = self._dma_seed(p.n)
        is_read = p.direction == "read"
        self._mem.inject_error(burst[0], p.code, read=is_read, write=not is_read)
        err_id = await self._dma_launch(f"P{p.n}_ERR")
        retired, done = await self._dma_poll(f"P{p.n}_ERR", err_id, DMA_ERR_POLLS, "dma_err")
        status = await self.csr_read(f"P{p.n}_ERR_STATUS", DMA_CTRL_STATUS_0)
        offset = burst[0] - (DMA_SRC if is_read else DMA_DST)
        size = self._burst_bytes(burst)
        left = bytes(self._mem.read(DMA_DST + offset, size))
        self._mem.clear_errors()
        src = self._dma_seed(p.n + RECOVERY_SALT)
        rec_id = await self._dma_launch(f"P{p.n}_REC")
        ok, rec_done = await self._dma_poll(f"P{p.n}_REC", rec_id, DMA_POLLS, "dma")
        assert ok, (
            f"P{p.n}: recovery copy id {rec_id} not retired, DONE_0 {rec_done} after "
            f"{DMA_POLLS} polls"
        )
        self._dma_compare(f"P{p.n}_REC", src)
        self._lines["CHK-SOE-DMA-RETIRES"].append(
            f"{p} burst {idx}/{len(bursts)} @0x{burst[0]:x}: recovery id {rec_id} retired and "
            f"{DMA_BYTES} bytes exact; errored copy id {err_id} printed: DONE_0 {done} "
            f"(reached id within {DMA_ERR_POLLS} polls: {retired}), STATUS_0 0x{status:x}, "
            f"destination bytes of the errored burst differing from the source "
            f"{sum(1 for a, b in zip(left, err_src[offset : offset + size]) if a != b)} of "
            f"{size}, "
            f"head {left[:16].hex()}"
        )

    # -- JTAG -------------------------------------------------------------

    def _jtag_item(self, label: str, op: SmcSysAxiOp, addr: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"soe_{label}")
        item.op = op
        item.addr = addr
        item.length = 8
        item.wdata = 0x5E00_0000_0000_0000 | addr
        item.axi_id = JTAG_DEFAULT_ID
        return item

    async def _jtag_pass(self, p: _Pass) -> None:
        op = SmcSysAxiOp.READ if p.direction == "read" else SmcSysAxiOp.WRITE
        base = JTAG_BASE + p.n * JTAG_PASS_SPAN
        is_read = op is SmcSysAxiOp.READ
        if not p.group:
            item = self._jtag_item(f"P{p.n}", op, base)
            item.expect_error = True
            item.allow_error = True
            item.expected_resp = p.code
            item.capture_resp_id = True
            item.axi_id = p.axi_id
            assert item.axi_id != JTAG_DEFAULT_ID, f"P{p.n}: single ID {item.axi_id} is the default"
            self._mem.inject_error(base, p.code, read=is_read, write=not is_read)
            await self._jtag(item)
            got_id = item.rid if is_read else item.bid
            assert item.resp_code == p.code, (
                f"P{p.n}: single {p.direction} answered {item.resp_code}, injected {p.code}"
            )
            assert got_id == item.axi_id, f"P{p.n}: response ID {got_id}, issued {item.axi_id}"
            text = (
                f"single, code {item.resp_code}, ID {got_id} (issued {item.axi_id}, "
                f"default ID of the other JTAG accesses {JTAG_DEFAULT_ID})"
            )
        else:
            hit = self._index(p.position, p.group)
            items = []
            for m in range(p.group):
                item = self._jtag_item(f"P{p.n}_M{m}", op, base + 8 * m)
                item.expected_resp = p.code if m == hit else RESP_OKAY
                item.expect_error = m == hit
                item.allow_error = m == hit
                items.append(item)
            self._mem.inject_error(base + 8 * hit, p.code, read=is_read, write=not is_read)
            await self._jtag(SmcSysAxiGroupItem(f"soe_P{p.n}_group", items))
            codes = [it.resp_code for it in items]
            want = [p.code if m == hit else RESP_OKAY for m in range(p.group)]
            assert codes == want, f"P{p.n}: group codes {codes}, want {want}"
            text = f"group of {p.group}, member {hit} code {p.code}, others OKAY {codes}"
        self._lines["CHK-SOE-JTAG-CODE"].append(f"{p}: {text}")

    # -- pass -------------------------------------------------------------

    async def _recover(self, p: _Pass) -> str:
        self._mem.clear_errors()
        word = 0x7EC0_0000_0000_0000 | (p.n << 32) | p.recovery
        wr = self._jtag_item(f"P{p.n}_REC_W", SmcSysAxiOp.WRITE, p.recovery)
        wr.wdata = word
        wr.expected_resp = RESP_OKAY
        await self._jtag(wr)
        rd = self._jtag_item(f"P{p.n}_REC_R", SmcSysAxiOp.READ, p.recovery)
        rd.expected = word
        rd.expected_resp = RESP_OKAY
        await self._jtag(rd)
        assert wr.resp_code == RESP_OKAY and rd.resp_code == RESP_OKAY, (
            f"P{p.n}: recovery write {wr.resp_code}, read {rd.resp_code}"
        )
        assert rd.rdata == word, f"P{p.n}: recovery read 0x{rd.rdata:016x}, wrote 0x{word:016x}"
        return f"{p}: OKAY write and read of 0x{word:016x}"

    async def _run_pass(self, p: _Pass) -> None:
        mon = self.env.output_axi_monitor
        before = mon.snapshot()
        handler = {"JTAG": self._jtag_pass, "DMA": self._dma_pass, "ZEROER": self._zeroer_pass}
        await handler[p.manager](p)
        self._mark_step(_STEP_OF[p.manager])
        self._lines["CHK-SOE-RECOVERY"].append(await self._recover(p))
        after = mon.snapshot()
        keys = ("b_slverr", "b_decerr", "r_slverr", "r_decerr")
        delta = {k: after[k] - before[k] for k in keys}
        name = f"{'r' if p.direction == 'read' else 'b'}_{CODES[p.code].lower()}"
        want = {k: int(k == name) for k in keys}
        assert delta == want, f"P{p.n}: output monitor counted {delta}, injected {want}"
        self._lines["CHK-SOE-MONITOR-TALLY"].append(f"{p}: {delta}")
        self._mark_step("S5")
        self.done_passes += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_BOUND)
        for sub in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(cocotb.top, sub).value
            assert sig.is_resolvable, f"{sub} is X/Z ({sig})"
            self._fuse_last[sub] = int(sig)
        self._draw()
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: %s", self.seed, "; ".join(str(p) for p in self.passes)
        )
        mon = self.env.output_axi_monitor
        mon.allow_slverr = True
        mon.allow_decerr = True
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        cocotb.start_soon(self.sampler.run())
        await self._zeroer_baseline()
        await self._dma_baseline()
        self._mark_step("S1")

        for p in self.passes:
            await self._run_pass(p)

        drawn = {c: "; ".join(lines) for c, lines in self._lines.items()}
        self._log_chk(
            "CHK-SOE-JTAG-CODE",
            "every injected JTAG access answered the injected code on its own item, single "
            f"accesses with their own drawn ID (1 to {JTAG_IDS - 1}, never the default ID "
            f"{JTAG_DEFAULT_ID} of every other JTAG access), other group members OKAY; "
            f"drawn={drawn['CHK-SOE-JTAG-CODE']}",
        )
        self._log_chk(
            "CHK-SOE-ZEROER-CONSUMED",
            f"every zeroer job with an errored burst reached STATUS 0 within {ZEROER_POLLS} polls "
            f"with CTRL_STATUS outside STATUS equal to INT_EN alone; "
            f"drawn={drawn['CHK-SOE-ZEROER-CONSUMED']}",
        )
        self._log_chk(
            "CHK-SOE-DMA-RETIRES",
            f"every recovery copy after an errored DMA burst retired within {DMA_POLLS} polls "
            f"byte-exact; drawn={drawn['CHK-SOE-DMA-RETIRES']}",
        )
        self._log_chk(
            "CHK-SOE-MONITOR-TALLY",
            "the output monitor counted exactly the injected code of each pass and no other "
            f"error; drawn={drawn['CHK-SOE-MONITOR-TALLY']}",
        )
        self._log_chk(
            "CHK-SOE-RECOVERY",
            f"every recovery write and read answered OKAY with the word written; "
            f"drawn={drawn['CHK-SOE-RECOVERY']}",
        )
        managers = {p.manager for p in self.passes}
        assert self.done_passes == PASSES, f"{self.done_passes} passes"
        assert managers == set(MANAGERS), f"managers drawn {managers}"
        self._finish()

    def _finish(self) -> None:
        bound = self.cfg.axi_timeout_ns
        waits = (
            ("tb_fuse_sense_done", f"{FUSE_BOUND}clk_smc_i", self._fuse_last["tb_fuse_sense_done"]),
            ("sep_in_axi_access", f"{bound}ns", f"{self.accesses} accesses done"),
            ("jtag_axi_access", f"{bound}ns", f"{self.jtag_accesses} accesses done"),
            ("zeroer_status_poll", f"{ZEROER_POLLS}polls", self._last["zeroer"]),
            ("dma_done_poll", f"{DMA_POLLS}polls*{DMA_POLL_CYCLES}clk", self._last["dma"]),
            (
                "dma_errored_done_poll",
                f"{DMA_ERR_POLLS}polls*{DMA_POLL_CYCLES}clk (printed, not failed)",
                self._last["dma_err"],
            ),
        )
        text = " ".join(f"{n}={b} last={s}" for n, b, s in waits)
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError except the "
            "printed errored-copy poll",
            len(waits),
            text,
        )
        self.chk_seen["CHK-TIMEOUT-PATHS"] = text
        steps = [s for s, _ in self._stamps]
        want = ["S1"]
        for p in self.passes:
            want += [_STEP_OF[p.manager], "S5"]
        assert steps == want, f"steps {steps}, want {want}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        printed = tuple(c for c, _ in self._chk_marks)
        assert printed == tuple(c for c, _ in _CHECKERS), f"checker order {printed}"
        for (chk_id, step), (_, seen_at) in zip(_CHECKERS, self._chk_marks):
            last = max(i for i, s in enumerate(steps) if s == step)
            assert seen_at > last, f"{chk_id} printed before the last {step}"
        counts = {m: sum(p.manager == m for p in self.passes) for m in MANAGERS}
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s; %d passes, managers %s",
            " < ".join(steps),
            ",".join(printed),
            ",".join(f"{s}={t}" for s, t in self._stamps),
            self.done_passes,
            counts,
        )
        self.chk_seen["CHK-NONVAC"] = "ordered"
