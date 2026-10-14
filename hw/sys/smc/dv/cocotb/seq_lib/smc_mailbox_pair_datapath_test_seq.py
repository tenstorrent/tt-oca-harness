# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Paired mailbox FIFO data path, partial-write lanes and push with pop on one FIFO.

Sources: axi_lite_mailbox_unit architecture.adoc, interface.adoc.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h",
    "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm",
)

FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
AXI_SLVERR = 2
EMPTY_ERROR_DATA = 0xFEEDDEAD
PAIRS = (0, 1, 15, 16, 31)
ISOLATION_PAIRS = (0, 1, 16, 31)
DRAIN_LIMIT = 4
_STEPS = tuple(f"S{n}" for n in range(1, 13))
_CHECKERS = (
    ("CHK-PAIR-FORWARD-PAIRS", "S2"),
    ("CHK-PAIR-REVERSE-PAIRS", "S3"),
    ("CHK-PAIR-OWN-READ-FIFO-EMPTY", "S4"),
    ("CHK-PAIR-ISOLATION", "S4"),
    ("CHK-PAIR-BOTH-DIRECTIONS", "S5"),
    ("CHK-PARTIAL-LANES-ZERO", "S6"),
    ("CHK-PARTIAL-NO-MERGE", "S7"),
    ("CHK-PARTIAL-ZERO-STROBE-OBSERVED", "S8"),
    ("CHK-PARTIAL-FILLS-FIFO", "S9"),
    ("CHK-PUSHPOP-OCCUPANCY-ONE", "S10"),
    ("CHK-PUSHPOP-FULL-OBSERVED", "S11"),
    ("CHK-PUSHPOP-EMPTY-OBSERVED", "S12"),
)

OKAY, ERROR, OBSERVE = "okay", "error", "observe"


def _addr(direction: str, pair: int, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{direction}_MAILBOX_{pair}_{reg}_BASE_ADDR")


def _lanes(data: int, wstrb: int) -> int:
    return sum(data & (0xFF << (8 * k)) for k in range(8) if wstrb >> k & 1)


class smc_mailbox_pair_datapath_test_seq(SmcCsrSeq):
    """Write one aperture of a pair and read the peer aperture across five checks of the path."""

    def __init__(self, name: str = "smc_mailbox_pair_datapath_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _item(name, op, addr, data=0, wstrb=None, expected=None, mode=OKAY) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value[0]}_{name}")
        item.op, item.addr, item.length = op, addr, 8
        item.wdata, item.wstrb, item.expected = data, wstrb, expected
        item.allow_error = mode == OBSERVE
        item.expect_error = mode == ERROR
        item.expected_resp = AXI_SLVERR if mode == ERROR else None
        return item

    def _check(self, item: SmcSysAxiItem, mode: str) -> SmcSysAxiItem:
        if mode == OBSERVE:
            assert item.resp_code is not None, f"{item.name}: no response"
            return item
        want = AXI_SLVERR if mode == ERROR else 0
        assert item.resp_code == want, f"{item.name}: resp {item.resp_code}, want {want}"
        if mode == ERROR and item.op is SmcSysAxiOp.READ:
            assert item.rdata & 0xFFFF_FFFF == EMPTY_ERROR_DATA, (
                f"{item.name}: error rdata 0x{item.rdata:x}, want low word 0x{EMPTY_ERROR_DATA:x}"
            )
        return item

    async def _do(self, name, op, addr, data=0, wstrb=None, expected=None, mode=OKAY):
        item = self._item(name, op, addr, data, wstrb, expected, mode)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return self._check(item, mode)

    async def _wr(self, name, direction, pair, data, wstrb=None, mode=OKAY):
        return await self._do(
            name, SmcSysAxiOp.WRITE, _addr(direction, pair, "WRITE_DATA"), data, wstrb, mode=mode
        )

    async def _rd(self, name, direction, pair, expected=None, mode=OKAY):
        mode = ERROR if mode == OKAY and expected is None else mode
        return await self._do(
            name,
            SmcSysAxiOp.READ,
            _addr(direction, pair, "READ_DATA"),
            expected=expected,
            mode=mode,
        )

    async def _group(self, name, members, modes) -> None:
        group = SmcSysAxiGroupItem(name, members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        for member, mode in zip(members, modes):
            self._check(member, mode)

    async def _drain(self, name, direction, pair) -> list[tuple[int, int]]:
        """Read until the empty error; every OKAY word before it is returned."""
        words = []
        for n in range(DRAIN_LIMIT):
            item = await self._rd(f"{name}_{n}", direction, pair, mode=OBSERVE)
            if item.resp_code == AXI_SLVERR:
                assert item.rdata & 0xFFFF_FFFF == EMPTY_ERROR_DATA, f"{name}: bad empty data"
                return words
            words.append((item.resp_code, item.rdata))
        raise AssertionError(f"{name}: no empty error within {DRAIN_LIMIT} reads: {words}")

    async def _pair_round(self, wr_dir, rd_dir, rng) -> dict[int, int]:
        words = {}
        for m in PAIRS:
            words[m] = rng.getrandbits(64)
            await self._wr(f"P{m}", wr_dir, m, words[m])
            await self._rd(f"P{m}", rd_dir, m, expected=words[m])
        return words

    @staticmethod
    def _fmt(words: dict[int, int]) -> str:
        return ",".join(f"pair{m}=0x{w:016x}" for m, w in words.items())

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        seed = int(os.environ.get("RANDOM_SEED", "1"))
        rng = random.Random(seed)
        cocotb.log.info("SEED RANDOM_SEED=%d", seed)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN
        )
        self._mark_step("S1")

        fwd = await self._pair_round("OUTBOUND", "INBOUND", rng)
        self._mark_step("S2")
        self._log_chk(
            "CHK-PAIR-FORWARD-PAIRS",
            f"seed {seed}; outbound write OKAY then inbound read "
            f"returned the same word on {len(fwd)} pairs: {self._fmt(fwd)}",
        )
        rev = await self._pair_round("INBOUND", "OUTBOUND", rng)
        self._mark_step("S3")
        self._log_chk(
            "CHK-PAIR-REVERSE-PAIRS",
            f"seed {seed}; inbound write OKAY then outbound read "
            f"returned the same word on {len(rev)} pairs: {self._fmt(rev)}",
        )

        x = 0x0123_4567_89AB_CDEF
        await self._wr("X", "OUTBOUND", 15, x)
        own = await self._rd("OWN", "OUTBOUND", 15)
        status = await self.csr_read("WRITER_STATUS", _addr("OUTBOUND", 15, "STATUS"), length=8)
        iso = 0
        for m in ISOLATION_PAIRS:
            for direction in ("OUTBOUND", "INBOUND"):
                await self._rd(f"ISO_{direction}_{m}", direction, m)
                iso += 1
        await self._rd("PEER_X", "INBOUND", 15, expected=x)
        self._mark_step("S4")
        self._log_chk(
            "CHK-PAIR-OWN-READ-FIFO-EMPTY",
            f"pair 15 writer's own READ_DATA answered "
            f"resp={own.resp_code} rdata=0x{own.rdata & 0xFFFFFFFF:08x}; peer returned X "
            f"0x{x:016x}; writer STATUS=0x{status:016x} (measured, owner value pending)",
        )
        self._log_chk(
            "CHK-PAIR-ISOLATION",
            f"{iso} reads of pairs {ISOLATION_PAIRS} answered SLVERR "
            f"with low word 0x{EMPTY_ERROR_DATA:08x} while X sat in pair 15; pair 15 "
            f"inbound returned 0x{x:016x}",
        )

        p = (0x0A0A_0A0A_0A0A_0A0A, 0x0B0B_0B0B_0B0B_0B0B)
        q = (0x0C0C_0C0C_0C0C_0C0C, 0x0D0D_0D0D_0D0D_0D0D)
        for n in (0, 1):
            await self._wr(f"P{n}", "OUTBOUND", 1, p[n])
        for n in (0, 1):
            await self._wr(f"Q{n}", "INBOUND", 1, q[n])
        for n in (0, 1):
            await self._rd(f"OUT_Q{n}", "OUTBOUND", 1, expected=q[n])
        for n in (0, 1):
            await self._rd(f"IN_P{n}", "INBOUND", 1, expected=p[n])
        self._mark_step("S5")
        self._log_chk(
            "CHK-PAIR-BOTH-DIRECTIONS",
            f"pair 1 with four words queued: outbound returned "
            f"0x{q[0]:016x},0x{q[1]:016x}; inbound returned 0x{p[0]:016x},0x{p[1]:016x}",
        )

        d = 0xA5A5_5A5A_C3C3_3C3C
        popped = []
        for wstrb in (0x0F, 0xF0, 0x01):
            await self._wr(f"D_{wstrb:02x}", "OUTBOUND", 0, d, wstrb=wstrb)
            got = await self._rd(f"D_{wstrb:02x}", "INBOUND", 0, expected=_lanes(d, wstrb))
            popped.append(f"wstrb 0x{wstrb:02x}->0x{got.rdata:016x}")
        self._mark_step("S6")
        self._log_chk(
            "CHK-PARTIAL-LANES-ZERO",
            f"written 0x{d:016x}; "
            + "; ".join(popped)
            + "; inactive lanes zero, active lanes intact",
        )

        f = 0x1122_3344_5566_7788
        await self._wr("F", "OUTBOUND", 0, f, wstrb=0xFF)
        await self._wr("PARTIAL", "OUTBOUND", 0, 0xFFFF_FFFF_99AA_BBCC, wstrb=0x0F)
        await self._rd("F", "INBOUND", 0, expected=f)
        await self._rd("PARTIAL", "INBOUND", 0, expected=0x99AA_BBCC)
        await self._rd("EMPTY", "INBOUND", 0)
        self._mark_step("S7")
        self._log_chk(
            "CHK-PARTIAL-NO-MERGE",
            f"F popped intact 0x{f:016x}, partial popped as "
            "0x0000000099aabbcc, third read was the empty error",
        )

        zero = await self._wr(
            "ZERO_STROBE", "OUTBOUND", 0, 0xDEAD_BEEF_DEAD_BEEF, wstrb=0x00, mode=OBSERVE
        )
        first = await self._rd("ZERO_STROBE_PEER", "INBOUND", 0, mode=OBSERVE)
        rest = await self._drain("ZERO_STROBE_DRAIN", "INBOUND", 0)
        self._mark_step("S8")
        self._log_chk(
            "CHK-PARTIAL-ZERO-STROBE-OBSERVED",
            f"wstrb=0x00 write B resp={zero.resp_code}; "
            f"peer read resp={first.resp_code} data=0x{first.rdata:016x}; further OKAY "
            f"words {[hex(w) for _, w in rest]}; drain ended in the empty error; "
            "no compare",
        )

        await self._wr("F9", "OUTBOUND", 0, f, wstrb=0xFF)
        await self._wr("PARTIAL9", "OUTBOUND", 0, 0xFFFF_FFFF_55AA_55AA, wstrb=0x0F)
        third = await self.csr_write_expect_error(
            "THIRD", _addr("OUTBOUND", 0, "WRITE_DATA"), 0x7777_7777_7777_7777, length=8
        )
        await self._rd("F9", "INBOUND", 0, expected=f)
        await self._rd("PARTIAL9", "INBOUND", 0, expected=0x55AA_55AA)
        await self._rd("EMPTY9", "INBOUND", 0)
        self._mark_step("S9")
        self._log_chk(
            "CHK-PARTIAL-FILLS-FIFO",
            f"two entries held, third write resp={third}; "
            f"peer popped 0x{f:016x} then 0x0000000055aa55aa, then the empty error",
        )

        a, b, c = 0x1000_0000_0000_0001, 0x2000_0000_0000_0002, 0x3000_0000_0000_0003
        await self._wr("A10", "OUTBOUND", 2, a)
        wr = self._item("B10", SmcSysAxiOp.WRITE, _addr("OUTBOUND", 2, "WRITE_DATA"), b)
        rd = self._item("A10", SmcSysAxiOp.READ, _addr("INBOUND", 2, "READ_DATA"), expected=a)
        await self._group("pushpop_one", [wr, rd], [OKAY, OKAY])
        await self._rd("B10", "INBOUND", 2, expected=b)
        await self._rd("EMPTY10", "INBOUND", 2)
        self._mark_step("S10")
        self._log_chk(
            "CHK-PUSHPOP-OCCUPANCY-ONE",
            f"group write resp={wr.resp_code} read "
            f"resp={rd.resp_code} returned older 0x{rd.rdata:016x}; next read returned "
            f"0x{b:016x}; third read was the empty error; no same-cycle alignment claimed",
        )

        await self._wr("A11", "OUTBOUND", 3, a)
        await self._wr("B11", "OUTBOUND", 3, b)
        wr = self._item("C11", SmcSysAxiOp.WRITE, _addr("OUTBOUND", 3, "WRITE_DATA"), c)
        wr.allow_error = True
        rd = self._item("A11", SmcSysAxiOp.READ, _addr("INBOUND", 3, "READ_DATA"), expected=a)
        await self._group("pushpop_full", [wr, rd], [OBSERVE, OKAY])
        words = await self._drain("DRAIN11", "INBOUND", 3)
        self._mark_step("S11")
        self._log_chk(
            "CHK-PUSHPOP-FULL-OBSERVED",
            f"grouped read returned oldest 0x{rd.rdata:016x}; "
            f"push resp={wr.resp_code}; drained words {[hex(w) for _, w in words]} then "
            "the empty error; push outcome not compared (owner value pending)",
        )

        wr = self._item("A12", SmcSysAxiOp.WRITE, _addr("OUTBOUND", 4, "WRITE_DATA"), a)
        rd = self._item("R12", SmcSysAxiOp.READ, _addr("INBOUND", 4, "READ_DATA"))
        wr.allow_error = rd.allow_error = True
        await self._group("pushpop_empty", [wr, rd], [OBSERVE, OBSERVE])
        words = await self._drain("DRAIN12", "INBOUND", 4)
        self._mark_step("S12")
        self._log_chk(
            "CHK-PUSHPOP-EMPTY-OBSERVED",
            f"group write resp={wr.resp_code}; read "
            f"resp={rd.resp_code} data=0x{rd.rdata:016x}; drained words "
            f"{[hex(w) for _, w in words]} then the empty error; outcome not compared "
            "(owner value pending)",
        )

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, cg)
        await self.csr_read("CLOCK_GATE_CONTROL_RESTORED", CLOCK_GATE_CONTROL, expected=cg)
        self._nonvac_fence()
        self._log_timeout_paths()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(y > x for x, y in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == tuple(c for c, _ in _CHECKERS), f"checker lines {chk_ids}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), (_, step) in zip(self._chk_marks, _CHECKERS):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence GATE_ENABLED<PAIR_FORWARD<PAIR_REVERSE<ISOLATION<"
            "BOTH_DIRECTIONS<PARTIAL_LANES<NO_MERGE<ZERO_STROBE<PARTIAL_FILLS<PUSHPOP_1<"
            "PUSHPOP_FULL<PUSHPOP_EMPTY; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        subs = (
            ("fuse sense wait tb_fuse_sense_done", "tb_fuse_sense_done"),
            ("fuse sense wait tb_fuse_reset_n", "tb_fuse_reset_n"),
            ("fuse sense wait tb_rst_warm_smc_clk_n", "tb_rst_warm_smc_clk_n"),
        )
        waits = "; ".join(
            f"{label} (AssertionError on expiry) bound={FUSE_SENSE_RISES} rises "
            f"last[{sig}={self._level(sig)}]"
            for label, sig in subs
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry; %s; "
            "SEP_IN CSR accesses (CLOCK_GATE_CONTROL, mailbox WRITE_DATA, READ_DATA, STATUS, "
            "strobed writes, grouped accesses) x%d bound=%d ns allow_timeout False "
            "last[%d accesses completed]; the sequence has no wait of its own; the empty-error "
            "drain is bounded at %d reads and raises AssertionError on expiry",
            waits,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.accesses,
            DRAIN_LIMIT,
        )
