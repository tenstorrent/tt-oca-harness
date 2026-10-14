# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox access results, ERROR_FLAGS read-to-clear and channel coincidence on pair 2.

Sources: axi_lite_mailbox_unit interface.adoc, architecture.adoc, axil_mailbox.rdl.
"""

from __future__ import annotations

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
READ_ERROR = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__ERROR__READ_ERROR_bm")
WRITE_ERROR = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__ERROR__WRITE_ERROR_bm")
WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
RTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__RTIRQ_bm")
EIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")
IRQ_ALL = WTIRQ | RTIRQ | EIRQ
STATUS_THRESH = _field_mask(
    _AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm"
) | _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__READ_LEVEL_ABOVE_THRESH_bm")
WFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__WFLUSH_bm")

FUSE_SENSE_RISES = 200_000
AXI_SLVERR = 2
EMPTY_ERROR_LOW = 0xFEEDDEAD
WRITE_DATA_EMPTY_LOW = 0xFEEDC0DE
PAIR = 2
SIDE = {"A": "OUTBOUND", "B": "INBOUND"}
OKAY, ERROR = "okay", "error"
_STEPS = tuple(f"S{n}" for n in range(1, 17))
_CHECKERS = (
    ("CHK-EMPTY-READ-SLVERR-DATA", "S2"),
    ("CHK-EMPTY-READ-FLAGS", "S3"),
    ("CHK-EMPTY-READ-NO-SIDE-EFFECT", "S4"),
    ("CHK-FULL-WRITE-FLAGS", "S6"),
    ("CHK-ERRFLAGS-BOTH-THEN-ZERO", "S7"),
    ("CHK-ERRFLAGS-READ-KEEPS-IRQS-ERROR", "S7"),
    ("CHK-ERRFLAGS-STICKY-ONE-READ-CLEARS", "S8"),
    ("CHK-FULL-WRITE-RECOVERS", "S9"),
    ("CHK-ERRFLAGS-PER-APERTURE", "S10"),
    ("CHK-WRITE-DATA-READ-EMPTY", "S11"),
    ("CHK-WRITE-DATA-READ-NO-EFFECT", "S12"),
    ("CHK-READ-ONLY-WRITES-REJECTED", "S13"),
    ("CHK-READ-ONLY-WRITES-NO-SIDE-EFFECT-OBSERVED", "S13"),
    ("CHK-CHANNELS-WRITE-WITH-STATUS", "S14"),
    ("CHK-CHANNELS-WRITE-WITH-READ", "S15"),
    ("CHK-CHANNELS-CTRL-WITH-IRQS", "S16"),
    ("CHK-CHANNELS-COMPLETE-BOUNDED", "S16"),
)


def _addr(side: str, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{SIDE[side]}_MAILBOX_{PAIR}_{reg}_BASE_ADDR")


class smc_mailbox_access_error_test_seq(SmcCsrSeq):
    """Cause access errors on aperture A of pair 2 and read the results from A and from B."""

    def __init__(self, name: str = "smc_mailbox_access_error_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._groups: list[SmcSysAxiGroupItem] = []

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _item(name, op, side, reg, data=0, mode=OKAY, expected=None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value[0]}_{name}")
        item.op, item.addr, item.length = op, _addr(side, reg), 8
        item.wdata, item.expected = data, expected
        item.expect_error = item.allow_error = mode == ERROR
        item.expected_resp = AXI_SLVERR if mode == ERROR else None
        return item

    @staticmethod
    def _check(item: SmcSysAxiItem, mode: str) -> SmcSysAxiItem:
        want = AXI_SLVERR if mode == ERROR else 0
        assert item.resp_code == want, f"{item.name}: resp {item.resp_code}, want {want}"
        if item.op is SmcSysAxiOp.READ:
            assert isinstance(item.rdata, int), f"{item.name}: unresolved read data"
            if item.expected is not None:
                assert item.rdata == item.expected, (
                    f"{item.name}: rdata 0x{item.rdata:x}, want 0x{item.expected:x}"
                )
        return item

    async def _do(self, name, op, side, reg, data=0, mode=OKAY, expected=None):
        item = self._item(name, op, side, reg, data, mode, expected)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return self._check(item, mode)

    async def _wr(self, name, side, reg, data, mode=OKAY):
        return await self._do(name, SmcSysAxiOp.WRITE, side, reg, data, mode)

    async def _rd(self, name, side, reg, mode=OKAY, expected=None):
        return await self._do(name, SmcSysAxiOp.READ, side, reg, mode=mode, expected=expected)

    async def _val(self, name, side, reg) -> int:
        return (await self._rd(name, side, reg)).rdata

    async def _push(self, name, side, data, mode=OKAY):
        return await self._wr(name, side, "WRITE_DATA", data, mode)

    async def _pop(self, name, side, expected):
        return await self._rd(name, side, "READ_DATA", expected=expected)

    async def _empty_read(self, name, side="A"):
        item = await self._rd(name, side, "READ_DATA", mode=ERROR)
        assert item.rdata & 0xFFFF_FFFF == EMPTY_ERROR_LOW, f"{name}: data 0x{item.rdata:x}"
        return item

    async def _flags(self, name, side) -> int:
        return await self._val(name, side, "ERROR_FLAGS") & (READ_ERROR | WRITE_ERROR)

    async def _group(self, name, members) -> SmcSysAxiGroupItem:
        group = SmcSysAxiGroupItem(name, members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        for member in members:
            self._check(member, OKAY)
        self._groups.append(group)
        return group

    async def body(self) -> None:
        await self.wait_fuse_sense_done(max_cycles=FUSE_SENSE_RISES)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN
        )
        self._mark_step("S1")

        ea = await self._empty_read("EMPTY_A", "A")
        eb = await self._empty_read("EMPTY_B", "B")
        self._mark_step("S2")
        self._log_chk(
            "CHK-EMPTY-READ-SLVERR-DATA",
            f"READ_DATA of A and B answered SLVERR (resp {ea.resp_code}, {eb.resp_code}) with "
            f"rdata[31:0]=0x{ea.rdata & 0xFFFFFFFF:08x},0x{eb.rdata & 0xFFFFFFFF:08x}; "
            f"rdata[63:32]=0x{ea.rdata >> 32:08x},0x{eb.rdata >> 32:08x} "
            "(not specified, measured)",
        )

        fa = await self._flags("EF_A", "A")
        fb = await self._flags("EF_B", "B")
        ia = await self._val("IRQS_A", "A", "IRQS") & IRQ_ALL
        ib = await self._val("IRQS_B", "B", "IRQS") & IRQ_ALL
        assert (fa, fb) == (READ_ERROR, READ_ERROR), f"ERROR_FLAGS A 0b{fa:02b} B 0b{fb:02b}"
        assert (ia, ib) == (EIRQ, EIRQ), f"IRQS A 0b{ia:03b} B 0b{ib:03b}, want 0b100"
        for side in "AB":
            await self._wr(f"ACK_{side}", side, "IRQS", EIRQ)
        ca = await self._val("IRQS_ACK_A", "A", "IRQS") & IRQ_ALL
        cb = await self._val("IRQS_ACK_B", "B", "IRQS") & IRQ_ALL
        assert (ca, cb) == (0, 0), f"IRQS after acknowledge A 0b{ca:03b} B 0b{cb:03b}"
        self._mark_step("S3")
        self._log_chk(
            "CHK-EMPTY-READ-FLAGS",
            f"set: empty READ_DATA read; observed: ERROR_FLAGS A=0b{fa:02b} B=0b{fb:02b}, "
            f"IRQS A=0b{ia:03b} B=0b{ib:03b}; cleared: write 0x4 to IRQS; "
            f"checked_cleared: IRQS A=0b{ca:03b} B=0b{cb:03b}",
        )

        s0 = {s: await self._val(f"STATUS0_{s}", s, "STATUS") for s in "AB"}
        await self._empty_read("EMPTY_STATUS", "A")
        s1 = await self._val("STATUS1_A", "A", "STATUS")
        assert all(v & STATUS_THRESH == 0 for v in (s0["A"], s0["B"], s1)), (
            f"STATUS threshold bits A 0x{s0['A']:x} B 0x{s0['B']:x} after 0x{s1:x}"
        )
        x, y = 0x0123_4567_89AB_CDEF, 0xFEDC_BA98_7654_3210
        await self._push("X", "B", x)
        await self._pop("X", "A", x)
        await self._push("Y", "A", y)
        await self._pop("Y", "B", y)
        self._mark_step("S4")
        self._log_chk(
            "CHK-EMPTY-READ-NO-SIDE-EFFECT",
            f"STATUS[3:2] A/B before 0b{s0['A'] >> 2 & 3:02b}/0b{s0['B'] >> 2 & 3:02b}, A after "
            f"0b{s1 >> 2 & 3:02b}; STATUS[1:0] measured A/B/after "
            f"{s0['A'] & 3}/{s0['B'] & 3}/{s1 & 3} "
            f"(not specified, measured); B->A returned 0x{x:016x}, "
            f"A->B returned 0x{y:016x}",
        )

        for side in "AB":
            await self._flags(f"EF_CLEAN_{side}", side)
            await self._wr(f"IRQS_CLEAN_{side}", side, "IRQS", IRQ_ALL)
        self._mark_step("S5")

        w = [0x1000_0000_0000_0000 + n for n in range(10)]
        await self._push("W0", "A", w[0])
        await self._push("W1", "A", w[1])
        third = await self._push("W2", "A", w[2], ERROR)
        i6 = await self._val("IRQS_FULL", "A", "IRQS") & IRQ_ALL
        f6a = await self._flags("EF_FULL_1", "A")
        f6b = await self._flags("EF_FULL_2", "A")
        assert i6 == WTIRQ | EIRQ, f"IRQS 0b{i6:03b}, want 0b101"
        assert (f6a, f6b) == (WRITE_ERROR, 0), f"ERROR_FLAGS 0b{f6a:02b}, 0b{f6b:02b}"
        self._mark_step("S6")
        self._log_chk(
            "CHK-FULL-WRITE-FLAGS",
            f"set: third write resp {third.resp_code}; observed: IRQS=0b{i6:03b} "
            f"ERROR_FLAGS=0b{f6a:02b}; cleared: that ERROR_FLAGS read; checked_cleared: "
            f"second ERROR_FLAGS read 0b{f6b:02b}",
        )

        await self._empty_read("EMPTY_7")
        await self._push("FULL_7", "A", w[3], ERROR)
        f7a = await self._flags("EF_7_1", "A")
        f7b = await self._flags("EF_7_2", "A")
        i7 = await self._val("IRQS_7", "A", "IRQS") & IRQ_ALL
        await self._wr("ACK_7", "A", "IRQS", EIRQ)
        i7c = await self._val("IRQS_7_ACK", "A", "IRQS") & IRQ_ALL
        assert (f7a, f7b) == (READ_ERROR | WRITE_ERROR, 0), f"flags 0b{f7a:02b}, 0b{f7b:02b}"
        assert i7 & EIRQ and not i7c & EIRQ, f"IRQS[2] before 0b{i7:03b} after ack 0b{i7c:03b}"
        self._mark_step("S7")
        self._log_chk(
            "CHK-ERRFLAGS-BOTH-THEN-ZERO",
            f"set: empty read and full write; observed: first ERROR_FLAGS read 0b{f7a:02b}; "
            f"cleared: that read; checked_cleared: second read 0b{f7b:02b}",
        )
        self._log_chk(
            "CHK-ERRFLAGS-READ-KEEPS-IRQS-ERROR",
            f"set: the empty read and full write (SLVERR) raised IRQS[2]; observed: "
            f"IRQS=0b{i7:03b} after two ERROR_FLAGS reads; cleared: write 0x4 to IRQS; "
            f"checked_cleared: IRQS=0b{i7c:03b}",
        )

        for n in range(2):
            await self._empty_read(f"EMPTY_8_{n}")
            await self._push(f"FULL_8_{n}", "A", w[4 + n], ERROR)
        f8a = await self._flags("EF_8_1", "A")
        f8b = await self._flags("EF_8_2", "A")
        assert (f8a, f8b) == (READ_ERROR | WRITE_ERROR, 0), f"flags 0b{f8a:02b}, 0b{f8b:02b}"
        self._mark_step("S8")
        self._log_chk(
            "CHK-ERRFLAGS-STICKY-ONE-READ-CLEARS",
            f"set: two more empty reads and two more full writes; observed: first "
            f"ERROR_FLAGS read 0b{f8a:02b}; cleared: that read; checked_cleared: next read "
            f"0b{f8b:02b}",
        )

        await self._pop("W0", "B", w[0])
        await self._push("W3", "A", w[6])
        await self._pop("W1", "B", w[1])
        await self._pop("W3", "B", w[6])
        self._mark_step("S9")
        self._log_chk(
            "CHK-FULL-WRITE-RECOVERS",
            f"B popped 0x{w[0]:016x}, write after the pop answered OKAY, B then popped "
            f"0x{w[1]:016x} and 0x{w[6]:016x} in write order",
        )

        f10a = await self._flags("EF_B_1", "B")
        f10b = await self._flags("EF_B_2", "B")
        assert (f10a, f10b) == (0, 0), f"B ERROR_FLAGS 0b{f10a:02b}, 0b{f10b:02b}"
        self._mark_step("S10")
        self._log_chk(
            "CHK-ERRFLAGS-PER-APERTURE",
            f"set: errors caused in A only; observed: B ERROR_FLAGS 0b{f10a:02b}; cleared: "
            f"not applicable; checked_cleared: second B read 0b{f10b:02b}",
        )

        e11 = await self._rd("WD_EMPTY", "A", "WRITE_DATA")
        assert e11.rdata & 0xFFFF_FFFF == WRITE_DATA_EMPTY_LOW, f"WRITE_DATA 0x{e11.rdata:x}"
        self._mark_step("S11")
        self._log_chk(
            "CHK-WRITE-DATA-READ-EMPTY",
            f"WRITE_DATA read OKAY resp {e11.resp_code} rdata[31:0]=0x{e11.rdata & 0xFFFFFFFF:08x} "
            f"rdata[63:32]=0x{e11.rdata >> 32:08x} (not specified, measured)",
        )

        await self._wr("IRQS_CLEAN_12", "A", "IRQS", IRQ_ALL)
        await self._push("W5", "A", w[7])
        i0 = await self._val("IRQS_WD_0", "A", "IRQS") & IRQ_ALL
        one = await self._rd("WD_ONE", "A", "WRITE_DATA")
        i1 = await self._val("IRQS_WD_1", "A", "IRQS") & IRQ_ALL
        await self._push("W6", "A", w[8])
        i2 = await self._val("IRQS_WD_2", "A", "IRQS") & IRQ_ALL
        full = await self._rd("WD_FULL", "A", "WRITE_DATA")
        i3 = await self._val("IRQS_WD_3", "A", "IRQS") & IRQ_ALL
        f12 = await self._flags("EF_WD", "A")
        assert i0 == i1 and i2 == i3 and f12 == 0, (
            f"IRQS 0b{i0:03b}/0b{i1:03b}/0b{i2:03b}/0b{i3:03b} ERROR_FLAGS 0b{f12:02b}"
        )
        assert not (i1 | i3) & EIRQ, f"WRITE_DATA read raised IRQS[2]: 0b{i1:03b}/0b{i3:03b}"
        await self._pop("W5", "B", w[7])
        await self._pop("W6", "B", w[8])
        self._mark_step("S12")
        self._log_chk(
            "CHK-WRITE-DATA-READ-NO-EFFECT",
            f"WRITE_DATA reads OKAY (one word resp {one.resp_code}, full resp {full.resp_code}); "
            f"IRQS before/after 0b{i0:03b}/0b{i1:03b} and 0b{i2:03b}/0b{i3:03b}; "
            f"ERROR_FLAGS 0b{f12:02b}; B popped 0x{w[7]:016x} then 0x{w[8]:016x}",
        )

        irqen = await self._val("IRQEN_RESET", "A", "IRQEN")
        await self._wr("IRQEN_1", "A", "IRQEN", WTIRQ)
        await self._push("W7", "A", w[9])
        await self._empty_read("EMPTY_13")
        before_flags = await self._flags("EF_13_BEFORE", "A")
        await self._empty_read("EMPTY_13_AGAIN")
        st_before = await self._val("STATUS_13_BEFORE", "A", "STATUS")
        irqs_before = await self._val("IRQS_13_BEFORE", "A", "IRQS") & IRQ_ALL
        resps = [
            (await self._wr("RO_STATUS", "A", "STATUS", (1 << 64) - 1, ERROR)).resp_code,
            (await self._wr("RO_ERROR_FLAGS", "A", "ERROR_FLAGS", 0, ERROR)).resp_code,
            (await self._wr("RO_IRQP", "A", "IRQP", 0, ERROR)).resp_code,
        ]
        st_after = await self._val("STATUS_13_AFTER", "A", "STATUS")
        ef_after = await self._flags("EF_13_AFTER", "A")
        irqp_after = await self._val("IRQP_13_AFTER", "A", "IRQP") & IRQ_ALL
        irqs_after = await self._val("IRQS_13_AFTER", "A", "IRQS") & IRQ_ALL
        assert st_before & STATUS_THRESH == st_after & STATUS_THRESH, "STATUS[3:2] changed"
        assert ef_after & READ_ERROR, f"ERROR_FLAGS 0b{ef_after:02b} lost read_error"
        assert irqp_after == WTIRQ, f"IRQP 0b{irqp_after:03b}, want 0b001"
        await self._pop("W7", "B", w[9])
        await self._wr("IRQEN_RESTORE", "A", "IRQEN", irqen)
        self._mark_step("S13")
        self._log_chk(
            "CHK-READ-ONLY-WRITES-REJECTED",
            f"writes to STATUS, ERROR_FLAGS, IRQP answered resp {resps}; STATUS[3:2] "
            f"0b{st_before >> 2 & 3:02b} -> 0b{st_after >> 2 & 3:02b}; ERROR_FLAGS[0] still "
            f"{ef_after & 1}; IRQP[2:0] 0b{irqp_after:03b}",
        )
        self._log_chk(
            "CHK-READ-ONLY-WRITES-NO-SIDE-EFFECT-OBSERVED",
            f"ERROR_FLAGS[1] before={before_flags >> 1 & 1} after={ef_after >> 1 & 1}; "
            f"IRQS before=0b{irqs_before:03b} after=0b{irqs_after:03b}; "
            "no compare (not specified, measured)",
        )

        st14 = await self._val("STATUS_14_BEFORE", "A", "STATUS")
        wr = self._item("G14_WR", SmcSysAxiOp.WRITE, "A", "WRITE_DATA", 0x1400_0000_0000_0014)
        rd = self._item("G14_STATUS", SmcSysAxiOp.READ, "A", "STATUS")
        await self._group("write_with_status", [wr, rd])
        await self._pop("G14", "B", 0x1400_0000_0000_0014)
        self._mark_step("S14")
        self._log_chk(
            "CHK-CHANNELS-WRITE-WITH-STATUS",
            f"grouped write resp {wr.resp_code}, grouped STATUS read resp {rd.resp_code}; "
            f"STATUS before=0x{st14:x} grouped=0x{rd.rdata:x} "
            "(not specified, measured); B popped the "
            "word; no same-cycle claim (not specified, measured)",
        )

        x2, w8 = 0x2000_0000_0000_0002, 0x8000_0000_0000_0008
        await self._push("X2", "B", x2)
        wr = self._item("G15_WR", SmcSysAxiOp.WRITE, "A", "WRITE_DATA", w8)
        rd = self._item("G15_RD", SmcSysAxiOp.READ, "A", "READ_DATA", expected=x2)
        await self._group("write_with_read", [wr, rd])
        await self._pop("G15", "B", w8)
        self._mark_step("S15")
        self._log_chk(
            "CHK-CHANNELS-WRITE-WITH-READ",
            f"grouped read returned 0x{rd.rdata:016x} (X2), grouped write resp {wr.resp_code}, "
            f"B popped 0x{w8:016x} (W8): each on its own FIFO",
        )

        wr = self._item("G16_CTRL", SmcSysAxiOp.WRITE, "A", "CTRL", WFLUSH)
        rd = self._item("G16_IRQS", SmcSysAxiOp.READ, "A", "IRQS")
        await self._group("ctrl_with_irqs", [wr, rd])
        self._mark_step("S16")
        self._log_chk(
            "CHK-CHANNELS-CTRL-WITH-IRQS",
            f"grouped CTRL write resp {wr.resp_code}, grouped IRQS read resp {rd.resp_code} "
            f"IRQS=0x{rd.rdata & IRQ_ALL:x}; no same-cycle claim (not specified, measured)",
        )
        members = [m for g in self._groups for m in g.items]
        assert len(members) == 6 and all(m.resp_code is not None for m in members)
        self._log_chk(
            "CHK-CHANNELS-COMPLETE-BOUNDED",
            f"{len(self._groups)} groups, {len(members)} members all completed with resp "
            f"{[m.resp_code for m in members]} under the {self.cfg.axi_timeout_ns} ns driver "
            "limit; "
            "no cycle count assumed",
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
            "CHK-NONVAC: ordered fence GATE_ENABLED<EMPTY_READ<FLAGS<NO_EFFECT<CLEAN<FULL_WRITE<"
            "BOTH_FLAGS<STICKY<RECOVER<PER_APERTURE<WRDATA_EMPTY<WRDATA_BUSY<RO_WRITES<GROUPS; "
            "checker lines %s; stamps %s",
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
            "ERROR_FLAGS, IRQS, IRQEN, IRQP, CTRL, grouped accesses) x%d bound=%d ns "
            "allow_timeout False last[%d accesses completed]; the sequence has no wait of its own",
            waits,
            self.accesses,
            self.cfg.axi_timeout_ns,
            self.accesses,
        )
