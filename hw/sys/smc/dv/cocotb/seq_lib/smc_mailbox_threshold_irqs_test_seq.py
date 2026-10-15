# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox threshold programming, IRQS latching and IRQEN gating into IRQP on pair 6.

Sources: axi_lite_mailbox_unit architecture.adoc, axil_mailbox.rdl.
"""

from __future__ import annotations

import os

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
WRITE_ABOVE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm")
READ_ABOVE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__READ_LEVEL_ABOVE_THRESH_bm")
WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
RTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__RTIRQ_bm")
EIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")
THR_MASK = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__WIRQT__WIRQT_bm")
IRQ_ALL = WTIRQ | RTIRQ | EIRQ

FUSE_SENSE_RISES = 200_000
AXI_SLVERR = 2
EMPTY_ERROR_LOW = 0xFEEDDEAD
DRAIN_LIMIT = 6
PAIR = 6
A, B = ("OUTBOUND", PAIR), ("INBOUND", PAIR)
IDLE_PAIRS = (0, 1, 15, 16, 31)
OKAY, ERROR, OBSERVE = "okay", "error", "observe"
W1, W2, W3 = 0x1111_2222_3333_4444, 0x5555_6666_7777_8888, 0x99AA_BBCC_DDEE_FF01
_STEPS = tuple(f"S{n}" for n in range(1, 15))
_CHECKERS = (
    ("CHK-THRESHOLD-RESET-AND-INRANGE", "S2"),
    ("CHK-IRQS-ZERO-AFTER-RESET", "S2"),
    ("CHK-THRESHOLD-CLAMP-BEHAVIOUR", "S3"),
    ("CHK-THRESHOLD-WIDE-VALUE-OBSERVED", "S4"),
    ("CHK-THRESHOLD-ZERO-DETECTS-ANY-WORD", "S5"),
    ("CHK-THRESHOLD-MAX-FIRES-ONLY-FULL", "S6"),
    ("CHK-THRESHOLD-INDEPENDENT-PER-REGISTER", "S7"),
    ("CHK-IRQS-STAYS-AFTER-CONDITION-ENDS", "S8"),
    ("CHK-IRQS-LATCHES-OWN-SOURCE", "S10"),
    ("CHK-IRQS-OVERLAPPING-SOURCES", "S11"),
    ("CHK-IRQP-IS-IRQS-AND-IRQEN", "S12"),
    ("CHK-IRQP-RAISES-ON-ENABLE-AT-ONCE", "S13"),
    ("CHK-IRQP-FALLS-ON-DISABLE-IRQS-KEEPS", "S13"),
    ("CHK-IRQP-FOLLOWS-LIVE-ENABLE-CHANGE", "S14"),
)


def _addr(target, reg: str) -> int:
    direction, pair = target
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{direction}_MAILBOX_{pair}_{reg}_BASE_ADDR")


class smc_mailbox_threshold_irqs_test_seq(SmcCsrSeq):
    """Program thresholds on pair 6, latch the three IRQS sources and gate them through IRQEN."""

    def __init__(self, name: str = "smc_mailbox_threshold_irqs_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _item(name, op, target, reg, data=0, mode=OKAY, expected=None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value[0]}_{name}")
        item.op, item.addr, item.length = op, _addr(target, reg), 8
        item.wdata, item.expected = data, expected
        item.allow_error = mode == OBSERVE
        item.expect_error = mode == ERROR
        item.expected_resp = AXI_SLVERR if mode == ERROR else None
        return item

    @staticmethod
    def _check(item: SmcSysAxiItem, mode: str) -> SmcSysAxiItem:
        if mode == OBSERVE:
            assert item.resp_code is not None, f"{item.name}: no response"
            return item
        want = AXI_SLVERR if mode == ERROR else 0
        assert item.resp_code == want, f"{item.name}: resp {item.resp_code}, want {want}"
        if item.op is SmcSysAxiOp.READ:
            assert isinstance(item.rdata, int), f"{item.name}: unresolved read data"
            if mode == ERROR:
                assert item.rdata & 0xFFFF_FFFF == EMPTY_ERROR_LOW, (
                    f"{item.name}: error rdata 0x{item.rdata:x}, want low word "
                    f"0x{EMPTY_ERROR_LOW:x}"
                )
            if item.expected is not None:
                assert item.rdata == item.expected, (
                    f"{item.name}: rdata 0x{item.rdata:x}, want 0x{item.expected:x}"
                )
        return item

    async def _do(self, name, op, target, reg, data=0, mode=OKAY, expected=None):
        item = self._item(name, op, target, reg, data, mode, expected)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return self._check(item, mode)

    async def _wr(self, name, target, reg, data, mode=OKAY):
        return await self._do(name, SmcSysAxiOp.WRITE, target, reg, data, mode)

    async def _val(self, name, target, reg) -> int:
        return (await self._do(name, SmcSysAxiOp.READ, target, reg)).rdata

    async def _bits(self, name, target, reg, mask) -> int:
        return await self._val(name, target, reg) & mask

    async def _push(self, name, target, data, mode=OKAY):
        return await self._wr(name, target, "WRITE_DATA", data, mode)

    async def _pop(self, name, target, expected):
        return await self._do(name, SmcSysAxiOp.READ, target, "READ_DATA", expected=expected)

    async def _group(self, name, members) -> None:
        group = SmcSysAxiGroupItem(name, [m for m, _ in members])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        for member, mode in members:
            self._check(member, mode)

    async def _ack(self, tag: str) -> None:
        """Acknowledge every IRQS bit of A and B; both must then read 0."""
        for side, target in (("A", A), ("B", B)):
            await self._wr(f"{tag}_ACK_{side}", target, "IRQS", IRQ_ALL)
            got = await self._bits(f"{tag}_CLR_{side}", target, "IRQS", IRQ_ALL)
            assert got == 0, f"{tag}: IRQS of {side} reads 0x{got:x} after acknowledge"

    async def _fill(self, tag, status_target, mask, irqs_target=None, irqs_mask=0):
        """A sends two words one at a time and B pops both; levels read after each word."""
        levels = []
        for n, word in enumerate((W1, W2)):
            await self._push(f"{tag}_W{n}", A, word)
            st = await self._bits(f"{tag}_ST{n}", status_target, "STATUS", mask) != 0
            irq = None
            if irqs_target is not None:
                irq = await self._bits(f"{tag}_IRQS{n}", irqs_target, "IRQS", irqs_mask) != 0
            levels.append((st, irq))
        for n, word in enumerate((W1, W2)):
            await self._pop(f"{tag}_POP{n}", B, word)
        return levels

    async def _thr(self, tag, target, reg, value) -> None:
        await self._wr(f"{tag}_{reg}", target, reg, value)

    async def body(self) -> None:
        await self.wait_fuse_sense_done(max_cycles=FUSE_SENSE_RISES)
        seed = int(os.environ.get("RANDOM_SEED", "1"))
        cocotb.log.info("SEED RANDOM_SEED=%d", seed)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN
        )
        self._mark_step("S1")

        idle = {}
        for m in (*IDLE_PAIRS, PAIR):
            for direction in ("OUTBOUND", "INBOUND"):
                got = await self._bits(f"IRQS0_{direction}_{m}", (direction, m), "IRQS", IRQ_ALL)
                assert got == 0, f"pair {m} {direction}: IRQS 0x{got:x} before traffic"
                idle[f"{direction[0]}{m}"] = got
        resets = {}
        for side, target in (("A", A), ("B", B)):
            for reg in ("WIRQT", "RIRQT"):
                resets[f"{reg}_{side}"] = await self._bits(
                    f"{reg}_RESET_{side}", target, reg, THR_MASK
                )
        assert not any(resets.values()), f"threshold reset values {resets}"
        for side, target in (("A", A), ("B", B)):
            for reg in ("WIRQT", "RIRQT"):
                for value in (0, 1, 0):
                    await self._wr(f"{reg}_{side}_{value}", target, reg, value)
                    got = await self._bits(f"{reg}_{side}_RB{value}", target, reg, THR_MASK)
                    assert got == value, f"{reg} of {side}: wrote {value}, read {got}"
        self._mark_step("S2")
        self._log_chk(
            "CHK-THRESHOLD-RESET-AND-INRANGE",
            f"WIRQT/RIRQT of A and B read {sorted(set(resets.values()))} at reset (all 64 bits) "
            "and read back exactly 0, 1, 0 after those writes on all four registers; the zero "
            "reset values cannot fail on a missing reset under the 2-state build (bench limit)",
        )
        self._log_chk(
            "CHK-IRQS-ZERO-AFTER-RESET",
            f"set: no source after reset; observed: IRQS[2:0]=0 on {len(idle)} apertures "
            f"{sorted(idle)}, every response OKAY; cleared: not applicable; "
            "checked_cleared: same reads before the first access; the zero reset values cannot "
            "fail on a missing reset under the 2-state build (bench limit)",
        )

        clamp = {}
        for reg, status_target, mask in (("WIRQT", A, WRITE_ABOVE), ("RIRQT", B, READ_ABOVE)):
            thr_target = A if reg == "WIRQT" else B
            for value in (2, 5, 0xFF):
                await self._thr("CLAMP", thr_target, reg, value)
                (one, _), (two, _) = await self._fill(f"CL_{reg}_{value}", status_target, mask)
                assert (one, two) == (False, True), f"{reg}={value}: bits one={one} two={two}"
                rb = await self._bits(f"{reg}_{value}_RB", thr_target, reg, THR_MASK)
                clamp[f"{reg}={value}"] = (int(one), int(two), rb)
                await self._ack("CL")
            await self._thr("CLAMP_RESTORE", thr_target, reg, 0)
        self._mark_step("S3")
        self._log_chk(
            "CHK-THRESHOLD-CLAMP-BEHAVIOUR",
            "STATUS above-threshold bit (one word, two words, readback) "
            f"{clamp}; bit 0 at one word and 1 at two words for every value; readback logged "
            "(not specified, measured)",
        )

        wide = {}
        for value in (0x100, 0x1_0000):
            await self._thr("WIDE", A, "WIRQT", value)
            await self._push(f"WIDE_{value:x}", A, W1)
            st = await self._bits(f"WIDE_ST_{value:x}", A, "STATUS", WRITE_ABOVE) != 0
            rb = await self._val(f"WIDE_RB_{value:x}", A, "WIRQT")
            await self._pop(f"WIDE_POP_{value:x}", B, W1)
            wide[f"0x{value:x}"] = (int(st), f"0x{rb:x}")
            await self._ack("WIDE")
        await self._thr("WIDE_RESTORE", A, "WIRQT", 0)
        self._mark_step("S4")
        self._log_chk(
            "CHK-THRESHOLD-WIDE-VALUE-OBSERVED",
            f"measured (STATUS[2] with one word, WIRQT readback) {wide}; no compare",
        )

        await self._ack("ZERO")
        await self._push("ZA_W", A, W1)
        za_st = await self._bits("ZA_ST", A, "STATUS", WRITE_ABOVE)
        za_irq = await self._bits("ZA_IRQS", A, "IRQS", WTIRQ)
        await self._pop("ZA_POP", B, W1)
        za_end = await self._bits("ZA_ST_END", A, "STATUS", WRITE_ABOVE)
        assert (za_st != 0, za_irq != 0, za_end) == (True, True, 0), (za_st, za_irq, za_end)
        await self._ack("ZERO_A")
        await self._push("ZB_W", A, W1)
        zb_st = await self._bits("ZB_ST", B, "STATUS", READ_ABOVE)
        zb_irq = await self._bits("ZB_IRQS", B, "IRQS", RTIRQ)
        await self._pop("ZB_POP", B, W1)
        zb_end = await self._bits("ZB_ST_END", B, "STATUS", READ_ABOVE)
        assert (zb_st != 0, zb_irq != 0, zb_end) == (True, True, 0), (zb_st, zb_irq, zb_end)
        await self._ack("ZERO_B")
        self._mark_step("S5")
        self._log_chk(
            "CHK-THRESHOLD-ZERO-DETECTS-ANY-WORD",
            f"set: one word above threshold 0; observed: A STATUS[2]={za_st >> 2} "
            f"IRQS[0]={za_irq}, B STATUS[3]={zb_st >> 3} IRQS[1]={zb_irq >> 1}; cleared: pops "
            f"and IRQS acknowledge; checked_cleared: STATUS[2]={za_end >> 2} "
            f"STATUS[3]={zb_end >> 3} after the pops, IRQS 0 after acknowledge",
        )

        await self._thr("MAX", A, "WIRQT", 1)
        (w1, i1), (w2, i2) = await self._fill("MAX_W", A, WRITE_ABOVE, A, WTIRQ)
        assert (w1, i1, w2, i2) == (False, False, True, True), (w1, i1, w2, i2)
        await self._ack("MAX_W")
        await self._thr("MAX_W_RESTORE", A, "WIRQT", 0)
        await self._thr("MAX", B, "RIRQT", 1)
        (r1, j1), (r2, j2) = await self._fill("MAX_R", B, READ_ABOVE, B, RTIRQ)
        assert (r1, j1, r2, j2) == (False, False, True, True), (r1, j1, r2, j2)
        await self._ack("MAX_R")
        await self._thr("MAX_R_RESTORE", B, "RIRQT", 0)
        self._mark_step("S6")
        self._log_chk(
            "CHK-THRESHOLD-MAX-FIRES-ONLY-FULL",
            f"threshold 1: A one word STATUS[2]={int(w1)} IRQS[0]={int(i1)}, full "
            f"{int(w2)}/{int(i2)}; B one word STATUS[3]={int(r1)} IRQS[1]={int(j1)}, full "
            f"{int(r2)}/{int(j2)}",
        )

        regs = (("WIRQT", A), ("RIRQT", A), ("WIRQT", B), ("RIRQT", B))

        async def read_four(tag):
            return [await self._bits(f"{tag}_{r}_{t[0][0]}", t, r, THR_MASK) for r, t in regs]

        for (reg, target), value in zip(regs, (1, 0, 0, 0)):
            await self._thr("IND", target, reg, value)
        first = await read_four("IND1")
        assert first == [1, 0, 0, 0], f"first read {first}"
        await self._thr("IND", A, "RIRQT", 1)
        second = await read_four("IND2")
        assert second == [1, 1, 0, 0], f"second read {second}"
        await self._thr("IND_RESTORE", A, "WIRQT", 0)
        await self._thr("IND_RESTORE", A, "RIRQT", 0)
        self._mark_step("S7")
        self._log_chk(
            "CHK-THRESHOLD-INDEPENDENT-PER-REGISTER",
            f"[WIRQT A, RIRQT A, WIRQT B, RIRQT B] read {first}; after RIRQT of A = 1 read "
            f"{second}; the two other registers and WIRQT of A unchanged",
        )

        await self._ack("L1")
        await self._wr("IRQEN_A_0", A, "IRQEN", 0)
        await self._push("L1_W", A, W1)
        l1_irqs = await self._bits("L1_IRQS", A, "IRQS", IRQ_ALL)
        l1_irqp = await self._bits("L1_IRQP", A, "IRQP", IRQ_ALL)
        await self._pop("L1_POP", B, W1)
        l1_irqs_end = await self._bits("L1_IRQS_END", A, "IRQS", IRQ_ALL)
        l1_st_end = await self._bits("L1_ST_END", A, "STATUS", WRITE_ABOVE)
        assert (l1_irqs, l1_irqp) == (WTIRQ, 0), f"IRQS 0x{l1_irqs:x} IRQP 0x{l1_irqp:x}"
        assert (l1_irqs_end & WTIRQ, l1_st_end) == (WTIRQ, 0), (l1_irqs_end, l1_st_end)
        self._mark_step("S8")
        self._log_chk(
            "CHK-IRQS-STAYS-AFTER-CONDITION-ENDS",
            f"set: one queued word latched IRQS[0]; observed: IRQS=0x{l1_irqs:x}; cleared: B "
            f"popped the word; checked_cleared: IRQS=0x{l1_irqs_end:x} while STATUS[2]="
            f"{l1_st_end >> 2}",
        )

        await self._ack("L2")
        await self._push("L2_W", A, W1)
        l2_irqs = await self._bits("L2_IRQS", B, "IRQS", IRQ_ALL)
        l2_irqp = await self._bits("L2_IRQP", B, "IRQP", IRQ_ALL)
        await self._pop("L2_POP", B, W1)
        assert (l2_irqs, l2_irqp) == (RTIRQ, 0), f"IRQS 0x{l2_irqs:x} IRQP 0x{l2_irqp:x}"
        self._mark_step("S9")

        await self._ack("L3")
        await self._do("L3_EMPTY", SmcSysAxiOp.READ, A, "READ_DATA", mode=ERROR)
        l3_empty = await self._bits("L3_IRQS", A, "IRQS", IRQ_ALL)
        assert l3_empty == EIRQ, f"empty read IRQS 0x{l3_empty:x}"
        await self._ack("L3B")
        await self._thr("L3", A, "WIRQT", 1)
        await self._push("L3_W0", A, W1)
        await self._push("L3_W1", A, W2)
        await self._push("L3_FULL", A, W3, mode=ERROR)
        l3_full = await self._bits("L3_IRQS_FULL", A, "IRQS", IRQ_ALL)
        assert l3_full == WTIRQ | EIRQ, f"full write IRQS 0x{l3_full:x}"
        await self._pop("L3_POP0", B, W1)
        await self._pop("L3_POP1", B, W2)
        await self._ack("L3C")
        await self._thr("L3_RESTORE", A, "WIRQT", 0)
        self._mark_step("S10")
        self._log_chk(
            "CHK-IRQS-LATCHES-OWN-SOURCE",
            f"IRQEN=0; set: occupancy above threshold or access error; observed: queued word "
            f"IRQS=0x{l1_irqs:x} IRQP=0x{l1_irqp:x}, received word IRQS=0x{l2_irqs:x} "
            f"IRQP=0x{l2_irqp:x}, empty read IRQS=0x{l3_empty:x}, full write above WIRQT 1 "
            f"IRQS=0x{l3_full:x}; cleared: IRQS acknowledged between sub-cases; "
            "checked_cleared: IRQS read 0 after each acknowledge",
        )

        await self._ack("O")
        await self._thr("O", A, "WIRQT", 1)
        await self._push("O_W0", A, W1)
        base = await self._bits("O_IRQS_BASE", A, "IRQS", IRQ_ALL)
        assert base == 0, f"baseline IRQS 0x{base:x}"
        cross = self._item("O_CROSS", SmcSysAxiOp.WRITE, A, "WRITE_DATA", W2)
        full = self._item("O_FULL", SmcSysAxiOp.WRITE, A, "WRITE_DATA", W2, mode=ERROR)
        await self._group("overlap", [(cross, OKAY), (full, ERROR)])
        overlap = await self._bits("O_IRQS", A, "IRQS", IRQ_ALL)
        assert overlap == WTIRQ | EIRQ, f"overlap IRQS 0x{overlap:x}"
        await self._pop("O_POP0", B, W1)
        await self._pop("O_POP1", B, W2)
        await self._ack("O_END")
        await self._thr("O_RESTORE", A, "WIRQT", 0)
        self._mark_step("S11")
        self._log_chk(
            "CHK-IRQS-OVERLAPPING-SOURCES",
            f"group write resp={cross.resp_code} and full write resp={full.resp_code}; "
            f"IRQS[2:0]=0x{overlap:x}; no same-cycle alignment claimed (not specified, measured)",
        )

        await self._ack("Q")
        await self._thr("Q", A, "WIRQT", 1)
        await self._push("Q_W0", A, W1)
        await self._push("Q_W1", A, W2)
        await self._push("Q_FULL", A, W3, mode=ERROR)
        await self._push("Q_PEER", B, W3)
        latched = await self._bits("Q_IRQS", A, "IRQS", IRQ_ALL)
        assert latched == IRQ_ALL, f"IRQS 0x{latched:x}, want 0x7"
        and_rows = []
        for en in range(8):
            await self._wr(f"Q_EN{en}", A, "IRQEN", en)
            ren = await self._bits(f"Q_EN{en}_RB", A, "IRQEN", IRQ_ALL)
            rs = await self._bits(f"Q_EN{en}_IRQS", A, "IRQS", IRQ_ALL)
            rp = await self._bits(f"Q_EN{en}_IRQP", A, "IRQP", IRQ_ALL)
            assert (ren, rs, rp) == (en, IRQ_ALL, rs & ren), f"IRQEN {en}: {ren} {rs} {rp}"
            and_rows.append(f"{en}:{rs:x}&{ren:x}={rp:x}")
        self._mark_step("S12")
        self._log_chk(
            "CHK-IRQP-IS-IRQS-AND-IRQEN",
            f"set: IRQS latched 0x{latched:x}; observed: IRQEN:IRQS&IRQEN=IRQP {and_rows}; "
            "cleared: IRQEN rewritten for each value; checked_cleared: IRQP equalled the "
            "new AND each time",
        )

        await self._wr("R_EN0", A, "IRQEN", 0)
        before = await self._bits("R_IRQP_BEFORE", A, "IRQP", IRQ_ALL)
        await self._wr("R_EN7", A, "IRQEN", IRQ_ALL)
        at_once = await self._bits("R_IRQP_AT_ONCE", A, "IRQP", IRQ_ALL)
        await self._wr("R_EN0_AGAIN", A, "IRQEN", 0)
        after = await self._bits("R_IRQP_AFTER", A, "IRQP", IRQ_ALL)
        irqs_kept = await self._bits("R_IRQS_KEPT", A, "IRQS", IRQ_ALL)
        assert (before, at_once) == (0, IRQ_ALL), f"IRQP before 0x{before:x} at once 0x{at_once:x}"
        assert (after, irqs_kept) == (0, IRQ_ALL), f"IRQP 0x{after:x} IRQS 0x{irqs_kept:x}"
        await self._pop("R_POP0", B, W1)
        await self._pop("R_POP1", B, W2)
        await self._pop("R_PEER", A, W3)
        await self._ack("R_END")
        await self._thr("R_RESTORE", A, "WIRQT", 0)
        self._mark_step("S13")
        self._log_chk(
            "CHK-IRQP-RAISES-ON-ENABLE-AT-ONCE",
            f"set: IRQS 0x7 latched with IRQEN 0; observed: IRQP=0x{before:x}; cleared: IRQEN "
            f"written 0x7; checked_cleared: the first IRQP read returned 0x{at_once:x}",
        )
        self._log_chk(
            "CHK-IRQP-FALLS-ON-DISABLE-IRQS-KEEPS",
            f"set: IRQEN 0x7; observed: IRQP=0x{at_once:x}; cleared: IRQEN written 0; "
            f"checked_cleared: IRQP=0x{after:x} while IRQS=0x{irqs_kept:x}",
        )

        await self._ack("G")
        await self._push("G_W0", A, W1)
        rows = []
        for tag, en, second in (("ON", 1, ("WRITE", W2)), ("OFF", 0, ("STATUS", 0))):
            enable = self._item(f"G_{tag}_EN", SmcSysAxiOp.WRITE, A, "IRQEN", en)
            if second[0] == "WRITE":
                other = self._item(f"G_{tag}_W", SmcSysAxiOp.WRITE, A, "WRITE_DATA", second[1])
            else:
                other = self._item(f"G_{tag}_ST", SmcSysAxiOp.READ, A, "STATUS")
            await self._group(f"irqen_{tag}", [(enable, OKAY), (other, OKAY)])
            rs = await self._bits(f"G_{tag}_IRQS", A, "IRQS", IRQ_ALL)
            ren = await self._bits(f"G_{tag}_IRQEN", A, "IRQEN", IRQ_ALL)
            rp = await self._bits(f"G_{tag}_IRQP", A, "IRQP", IRQ_ALL)
            assert (ren, rs, rp) == (en, WTIRQ, WTIRQ & en), (
                f"{tag}: IRQEN {ren} IRQS 0x{rs:x} IRQP 0x{rp:x}"
            )
            rows.append(f"{tag}: IRQS={rs:x} IRQEN={ren:x} IRQP={rp:x}")
        await self._pop("G_POP0", B, W1)
        await self._pop("G_POP1", B, W2)
        await self._ack("G_END")
        self._mark_step("S14")
        self._log_chk(
            "CHK-IRQP-FOLLOWS-LIVE-ENABLE-CHANGE",
            f"after each group IRQS was 0b001 and IRQP[2:0] equalled 0b001 AND IRQEN: {rows}; "
            "reads made after the group completed; no same-cycle claim (not specified, measured)",
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
            "CHK-NONVAC: ordered fence GATE_ENABLED<RESET_AND_INRANGE<CLAMP<WIDE<ZERO<MAX<"
            "INDEPENDENT<LATCH_WRITE<LATCH_READ<LATCH_ERROR<OVERLAP<IRQP_AND<IRQP_ENABLE<"
            "IRQP_LIVE; checker lines %s; stamps %s",
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
            "SEP_IN CSR accesses (CLOCK_GATE_CONTROL, mailbox WIRQT, RIRQT, IRQS, IRQEN, IRQP, "
            "STATUS, WRITE_DATA, READ_DATA, grouped accesses) x%d bound=%d ns allow_timeout "
            "False last[%d accesses completed]; the sequence has no wait of its own",
            waits,
            self.accesses,
            self.cfg.axi_timeout_ns,
            self.accesses,
        )
