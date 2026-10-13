# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox CTRL flush strobes, flush effects and live STATUS threshold levels on pair 4.

Contract SMC_MAILBOX_012, anchor smc_mailbox_flush_status_test.
Scenarios: MBX-STATUS-LEVEL S5, MBX-STATUS-THRESH S2-S4, MBX-CTRL-READBACK S1-S3,
MBX-FLUSH-WRITE S1-S4, MBX-FLUSH-READ S1-S4, MBX-CONTEST-FLUSHPUSH S1-S3.
Sources: axi_lite_mailbox_unit interface.adoc, architecture.adoc, axil_mailbox.rdl;
open SF-012/018/022/024.
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
WRITE_ABOVE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__WRITE_LEVEL_ABOVE_THRESH_bm")
READ_ABOVE = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__STATUS__READ_LEVEL_ABOVE_THRESH_bm")
WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
WFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__WFLUSH_bm")
RFLUSH = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__CTRL__RFLUSH_bm")
IRQ_ALL = 0x7
CTRL_BITS = WFLUSH | RFLUSH

FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
AXI_SLVERR = 2
EMPTY_ERROR_LOW = 0xFEEDDEAD
DRAIN_LIMIT = 6
PAIR = 4
SIDE = {"A": "OUTBOUND", "B": "INBOUND"}
OKAY, ERROR, OBSERVE = "okay", "error", "observe"
_STEPS = tuple(f"S{n}" for n in range(1, 17))
_CHECKERS = (
    ("CHK-CTRL-ZERO-AT-RESET", "S2"),
    ("CHK-WRITE-THRESHOLD-STRICT", "S3"),
    ("CHK-STATUS-FOLLOWS-OCCUPANCY-NO-ACK", "S3"),
    ("CHK-READ-THRESHOLD-STRICT", "S4"),
    ("CHK-THRESHOLD-BITS-FALL-LIVE", "S4"),
    ("CHK-CTRL-READS-ZERO-AFTER-WRITE", "S5"),
    ("CHK-CTRL-BOTH-BITS-OBSERVED", "S6"),
    ("CHK-WFLUSH-DISCARDS-PEER-WORDS", "S7"),
    ("CHK-WFLUSH-CLEARS-FULL", "S7"),
    ("CHK-WFLUSH-KEEPS-OWN-READ-FIFO", "S8"),
    ("CHK-WFLUSH-EMPTY-HARMLESS", "S9"),
    ("CHK-RFLUSH-EMPTIES-OWN-READ-FIFO", "S10"),
    ("CHK-RFLUSH-FREES-PEER", "S11"),
    ("CHK-RFLUSH-KEEPS-OWN-WRITE-FIFO", "S12"),
    ("CHK-RFLUSH-EMPTY-HARMLESS", "S13"),
    ("CHK-WFLUSH-VS-PUSH-CONSISTENT", "S14"),
    ("CHK-RFLUSH-VS-PUSH-CONSISTENT", "S15"),
    ("CHK-FLUSH-VS-POP-NO-STALE-NO-STUCK", "S16"),
)


def _addr(side: str, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{SIDE[side]}_MAILBOX_{PAIR}_{reg}_BASE_ADDR")


def _hex(value) -> str:
    return "None" if value is None else f"0x{value:016x}"


class smc_mailbox_flush_status_test_seq(SmcCsrSeq):
    """Flush the FIFOs of pair 4 from aperture A and read the effects from A and from B."""

    def __init__(self, name: str = "smc_mailbox_flush_status_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._irqs_writes = 0

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

    async def _do(self, name, op, side, reg, data=0, mode=OKAY, expected=None):
        item = self._item(name, op, side, reg, data, mode, expected)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return self._check(item, mode)

    async def _wr(self, name, side, reg, data, mode=OKAY):
        if reg == "IRQS":
            self._irqs_writes += 1
        return await self._do(name, SmcSysAxiOp.WRITE, side, reg, data, mode)

    async def _rd(self, name, side, reg, mode=OKAY, expected=None):
        return await self._do(name, SmcSysAxiOp.READ, side, reg, mode=mode, expected=expected)

    async def _val(self, name, side, reg) -> int:
        return (await self._rd(name, side, reg)).rdata

    async def _push(self, name, side, data):
        return await self._wr(name, side, "WRITE_DATA", data)

    async def _pop(self, name, side, expected):
        return await self._rd(name, side, "READ_DATA", expected=expected)

    async def _empty_read(self, name, side):
        return await self._rd(name, side, "READ_DATA", mode=ERROR)

    async def _drain(self, name, side) -> list[int]:
        """Read until the empty error; every OKAY word before it is returned."""
        words = []
        for n in range(DRAIN_LIMIT):
            item = await self._rd(f"{name}_{n}", side, "READ_DATA", mode=OBSERVE)
            if item.resp_code == AXI_SLVERR:
                assert item.rdata & 0xFFFF_FFFF == EMPTY_ERROR_LOW, f"{name}: bad empty data"
                return words
            assert item.resp_code == 0, f"{name}_{n}: resp {item.resp_code}"
            words.append(item.rdata)
        raise AssertionError(f"{name}: no empty error within {DRAIN_LIMIT} reads: {words}")

    async def _ctrl_zero(self, name, side) -> int:
        item = await self._rd(name, side, "CTRL")
        assert item.rdata & CTRL_BITS == 0, f"{name}: CTRL bits 0x{item.rdata:x}"
        return item.rdata & CTRL_BITS

    async def _flags(self, name, side) -> int:
        return await self._val(name, side, "ERROR_FLAGS") & 0x3

    async def _baseline(self, tag: str) -> tuple[int, int]:
        """Clear A's flags and IRQS, then read both; both must be zero."""
        await self._flags(f"{tag}_EF_CLEAR", "A")
        await self._wr(f"{tag}_ACK", "A", "IRQS", IRQ_ALL)
        flags = await self._flags(f"{tag}_EF_BASE", "A")
        irqs = await self._val(f"{tag}_IRQS_BASE", "A", "IRQS") & IRQ_ALL
        assert (flags, irqs) == (0, 0), f"{tag}: baseline ERROR_FLAGS {flags} IRQS {irqs}"
        return flags, irqs

    async def _group(self, name, members) -> SmcSysAxiGroupItem:
        group = SmcSysAxiGroupItem(name, [m for m, _ in members])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        for member, mode in members:
            self._check(member, mode)
        return group

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN
        )
        self._mark_step("S1")

        ca = await self._ctrl_zero("CTRL_RESET_A", "A")
        cb = await self._ctrl_zero("CTRL_RESET_B", "B")
        self._mark_step("S2")
        self._log_chk(
            "CHK-CTRL-ZERO-AT-RESET",
            f"CTRL of A and B read OKAY with bits[1:0] A={ca} B={cb} at reset",
        )

        w = [0x3000_0000_0000_0000 + n for n in range(16)]
        assert await self._val("IRQEN_A", "A", "IRQEN") & IRQ_ALL == 0, "IRQEN A not zero"
        irqs_start = self._irqs_writes
        await self._wr("WIRQT_1", "A", "WIRQT", 1)
        await self._push("S3_W0", "A", w[0])
        st1 = await self._val("S3_STATUS_1", "A", "STATUS")
        await self._push("S3_W1", "A", w[1])
        st2 = await self._val("S3_STATUS_2", "A", "STATUS")
        await self._pop("S3_P0", "B", w[0])
        st3 = await self._val("S3_STATUS_3", "A", "STATUS")
        irqs3 = await self._val("S3_IRQS", "A", "IRQS") & IRQ_ALL
        await self._pop("S3_P1", "B", w[1])
        st4 = await self._val("S3_STATUS_4", "A", "STATUS")
        bits = [s & WRITE_ABOVE for s in (st1, st2, st3, st4)]
        assert bits == [0, WRITE_ABOVE, 0, 0], f"STATUS[2] at 1,2,1,0 words: {bits}"
        assert irqs3 & WTIRQ, f"IRQS 0b{irqs3:03b}: IRQS[0] not latched while above WIRQT"
        assert self._irqs_writes == irqs_start, "IRQS written during S3"
        self._mark_step("S3")
        self._log_chk(
            "CHK-WRITE-THRESHOLD-STRICT",
            f"WIRQT=1: STATUS[2] one word={bits[0] >> 2} two words={bits[1] >> 2}; set: two "
            f"queued words; observed: STATUS[2]=1; cleared: B popped one word; checked_cleared: "
            f"STATUS[2]={bits[2] >> 2}; STATUS[1:0] logged 0x{st1 & 3:x}/0x{st2 & 3:x}/"
            f"0x{st3 & 3:x}/0x{st4 & 3:x} (SF-008)",
        )
        self._log_chk(
            "CHK-STATUS-FOLLOWS-OCCUPANCY-NO-ACK",
            f"set: two words above WIRQT=1 latched IRQS[0]; observed: IRQS=0b{irqs3:03b} with "
            f"STATUS[2]={bits[1] >> 2}; cleared: B pop with no IRQS write (IRQEN=0); "
            f"checked_cleared: STATUS[2]={bits[2] >> 2} while IRQS[0]={irqs3 & 1}; "
            f"STATUS[2] after the last pop={bits[3] >> 2}",
        )

        await self._wr("RIRQT_0", "B", "RIRQT", 0)
        await self._push("S4_W0", "A", w[2])
        r1 = await self._val("S4_STATUS_B_0", "B", "STATUS")
        await self._pop("S4_P0", "B", w[2])
        await self._wr("RIRQT_1", "B", "RIRQT", 1)
        await self._push("S4_W1", "A", w[3])
        r2 = await self._val("S4_STATUS_B_1", "B", "STATUS")
        await self._push("S4_W2", "A", w[4])
        r3 = await self._val("S4_STATUS_B_2", "B", "STATUS")
        await self._pop("S4_P1", "B", w[3])
        r4 = await self._val("S4_STATUS_B_3", "B", "STATUS")
        await self._pop("S4_P2", "B", w[4])
        rbits = [s & READ_ABOVE for s in (r1, r2, r3, r4)]
        assert rbits == [READ_ABOVE, 0, READ_ABOVE, 0], f"B STATUS[3] points: {rbits}"
        assert self._irqs_writes == irqs_start, "IRQS written during S3 or S4"
        self._mark_step("S4")
        self._log_chk(
            "CHK-READ-THRESHOLD-STRICT",
            f"B.STATUS[3]: RIRQT=0 one word={rbits[0] >> 3}; RIRQT=1 one word={rbits[1] >> 3}, "
            f"two words={rbits[2] >> 3}; set: received occupancy above RIRQT; observed: bit 3 = "
            f"1; cleared: B popped; checked_cleared: bit 3 = {rbits[3] >> 3}",
        )
        self._log_chk(
            "CHK-THRESHOLD-BITS-FALL-LIVE",
            f"STATUS[2] 1->{bits[2] >> 2}->{bits[3] >> 2} and B STATUS[3] 1->{rbits[3] >> 3} as "
            f"occupancy fell; IRQS writes between S3 and S4 end = {self._irqs_writes - irqs_start}",
        )

        outcomes = []
        for val in (WFLUSH, RFLUSH):
            wr = await self._wr(f"CTRL_{val}", "A", "CTRL", val)
            outcomes.append((wr.resp_code, await self._ctrl_zero(f"CTRL_RB_{val}", "A")))
        self._mark_step("S5")
        self._log_chk(
            "CHK-CTRL-READS-ZERO-AFTER-WRITE",
            f"CTRL writes 0x1 and 0x2 answered OKAY; later CTRL reads OKAY with bits[1:0] "
            f"{outcomes[0][1]} and {outcomes[1][1]}",
        )

        await self._push("S6_AW0", "A", w[5])
        await self._push("S6_AW1", "A", w[6])
        await self._push("S6_BW0", "B", w[7])
        await self._push("S6_BW1", "B", w[8])
        both = await self._wr("CTRL_BOTH", "A", "CTRL", CTRL_BITS, mode=OBSERVE)
        words_a = await self._drain("S6_DRAIN_A", "A")
        words_b = await self._drain("S6_DRAIN_B", "B")
        self._mark_step("S6")
        self._log_chk(
            "CHK-CTRL-BOTH-BITS-OBSERVED",
            f"CTRL=0x3 resp={both.resp_code}; A.READ_DATA words {[_hex(x) for x in words_a]} "
            f"(sent by B: {_hex(w[7])},{_hex(w[8])}); B.READ_DATA words "
            f"{[_hex(x) for x in words_b]} (sent by A: {_hex(w[5])},{_hex(w[6])}); both drains "
            "ended in the empty error; no compare (SF-018 open)",
        )

        await self._flags("S7_EF_A", "A")
        await self._flags("S7_EF_B", "B")
        await self._wr("S7_ACK_A", "A", "IRQS", IRQ_ALL)
        await self._wr("S7_ACK_B", "B", "IRQS", IRQ_ALL)
        await self._push("S7_W0", "A", w[9])
        await self._push("S7_W1", "A", w[10])
        await self._wr("S7_WFLUSH", "A", "CTRL", WFLUSH)
        peer = await self._empty_read("S7_PEER", "B")
        sb = await self._val("S7_STATUS_B", "B", "STATUS")
        sa = await self._val("S7_STATUS_A", "A", "STATUS")
        wr2 = await self._push("S7_W2", "A", w[11])
        await self._pop("S7_P2", "B", w[11])
        self._mark_step("S7")
        self._log_chk(
            "CHK-WFLUSH-DISCARDS-PEER-WORDS",
            f"after wflush on A the peer READ_DATA answered resp {peer.resp_code} with "
            f"rdata[31:0]=0x{peer.rdata & 0xFFFFFFFF:08x} although {_hex(w[9])} and "
            f"{_hex(w[10])} had been queued; STATUS[1:0] B=0x{sb & 3:x} A=0x{sa & 3:x} "
            "(SF-008)",
        )
        self._log_chk(
            "CHK-WFLUSH-CLEARS-FULL",
            f"after wflush of the full write FIFO the next write answered resp {wr2.resp_code} "
            f"and B popped {_hex(w[11])}; STATUS full bit A={sa >> 1 & 1} B={sb >> 1 & 1} "
            "(SF-008)",
        )

        await self._push("S8_X", "B", w[12])
        await self._wr("S8_WFLUSH", "A", "CTRL", WFLUSH)
        own = await self._pop("S8_OWN", "A", w[12])
        self._mark_step("S8")
        self._log_chk(
            "CHK-WFLUSH-KEEPS-OWN-READ-FIFO",
            f"A.READ_DATA returned {_hex(own.rdata)} (X) after wflush on A, resp {own.resp_code}",
        )

        before = await self._baseline("S9")
        await self._wr("S9_WFLUSH", "A", "CTRL", WFLUSH)
        f9 = await self._flags("S9_EF_AFTER", "A")
        i9 = await self._val("S9_IRQS_AFTER", "A", "IRQS") & IRQ_ALL
        assert (f9, i9) == (0, 0), f"after empty wflush ERROR_FLAGS {f9} IRQS 0b{i9:03b}"
        self._mark_step("S9")
        self._log_chk(
            "CHK-WFLUSH-EMPTY-HARMLESS",
            f"set: baseline acknowledged; observed: ERROR_FLAGS={before[0]} IRQS={before[1]} "
            f"before; cleared: not applicable; checked_cleared: ERROR_FLAGS={f9} "
            f"IRQS=0b{i9:03b} after wflush of an empty write FIFO",
        )

        await self._push("S10_X1", "B", w[13])
        await self._wr("S10_RFLUSH", "A", "CTRL", RFLUSH)
        own = await self._empty_read("S10_OWN", "A")
        s10 = await self._val("S10_STATUS_A", "A", "STATUS")
        self._mark_step("S10")
        self._log_chk(
            "CHK-RFLUSH-EMPTIES-OWN-READ-FIFO",
            f"after rflush on A, A.READ_DATA answered resp {own.resp_code} with "
            f"rdata[31:0]=0x{own.rdata & 0xFFFFFFFF:08x} although B had sent {_hex(w[13])}; "
            f"STATUS[1:0] A=0x{s10 & 3:x} (SF-008)",
        )

        await self._push("S11_Y0", "B", w[0])
        await self._push("S11_Y1", "B", w[1])
        await self._wr("S11_RFLUSH", "A", "CTRL", RFLUSH)
        wr11 = await self._push("S11_Y2", "B", w[14])
        await self._pop("S11_P2", "A", w[14])
        s11 = await self._val("S11_STATUS_B", "B", "STATUS")
        self._mark_step("S11")
        self._log_chk(
            "CHK-RFLUSH-FREES-PEER",
            f"after rflush of A's full read FIFO the peer write answered resp {wr11.resp_code} "
            f"and A popped {_hex(w[14])}; STATUS full bit B={s11 >> 1 & 1} (SF-008)",
        )

        await self._push("S12_W", "A", w[15])
        await self._wr("S12_RFLUSH", "A", "CTRL", RFLUSH)
        kept = await self._pop("S12_PEER", "B", w[15])
        self._mark_step("S12")
        self._log_chk(
            "CHK-RFLUSH-KEEPS-OWN-WRITE-FIFO",
            f"B popped {_hex(kept.rdata)} (W) after rflush on A, resp {kept.resp_code}",
        )

        before = await self._baseline("S13")
        await self._wr("S13_RFLUSH", "A", "CTRL", RFLUSH)
        f13 = await self._flags("S13_EF_AFTER", "A")
        i13 = await self._val("S13_IRQS_AFTER", "A", "IRQS") & IRQ_ALL
        assert (f13, i13) == (0, 0), f"after empty rflush ERROR_FLAGS {f13} IRQS 0b{i13:03b}"
        self._mark_step("S13")
        self._log_chk(
            "CHK-RFLUSH-EMPTY-HARMLESS",
            f"set: baseline acknowledged; observed: ERROR_FLAGS={before[0]} IRQS={before[1]} "
            f"before; cleared: not applicable; checked_cleared: ERROR_FLAGS={f13} "
            f"IRQS=0b{i13:03b} after rflush of an empty read FIFO",
        )

        v = [0x4000_0000_0000_0000 + n for n in range(3)]
        await self._push("S14_V0", "A", v[0])
        g_ctrl = self._item("G14_CTRL", SmcSysAxiOp.WRITE, "A", "CTRL", WFLUSH)
        g_wr = self._item("G14_V1", SmcSysAxiOp.WRITE, "A", "WRITE_DATA", v[1])
        await self._group("wflush_with_push", [(g_ctrl, OKAY), (g_wr, OKAY)])
        words = await self._drain("S14_DRAIN", "B")
        assert all(x == v[1] for x in words) and len(words) <= 1, f"S14 words {words}"
        await self._push("S14_V2", "A", v[2])
        await self._pop("S14_P2", "B", v[2])
        self._mark_step("S14")
        self._log_chk(
            "CHK-WFLUSH-VS-PUSH-CONSISTENT",
            f"group resp CTRL={g_ctrl.resp_code} WRITE_DATA={g_wr.resp_code}; V0 not popped; "
            f"V1 {'kept' if words else 'discarded'} (measured, SF-012); drain words "
            f"{[_hex(x) for x in words]} ended in the empty error; V2 round trip "
            f"{_hex(v[2])}; no same-cycle claim (SF-024)",
        )

        u = [0x5000_0000_0000_0000 + n for n in range(3)]
        await self._push("S15_U0", "B", u[0])
        g_ctrl = self._item("G15_CTRL", SmcSysAxiOp.WRITE, "A", "CTRL", RFLUSH)
        g_wr = self._item("G15_U1", SmcSysAxiOp.WRITE, "B", "WRITE_DATA", u[1])
        await self._group("rflush_with_push", [(g_ctrl, OKAY), (g_wr, OKAY)])
        words = await self._drain("S15_DRAIN", "A")
        assert all(x == u[1] for x in words) and len(words) <= 1, f"S15 words {words}"
        await self._push("S15_U2", "B", u[2])
        await self._pop("S15_P2", "A", u[2])
        self._mark_step("S15")
        self._log_chk(
            "CHK-RFLUSH-VS-PUSH-CONSISTENT",
            f"group resp CTRL={g_ctrl.resp_code} WRITE_DATA={g_wr.resp_code}; U0 not popped; "
            f"U1 {'kept' if words else 'discarded'} (measured, SF-012); drain words "
            f"{[_hex(x) for x in words]} ended in the empty error; U2 round trip "
            f"{_hex(u[2])}",
        )

        z = [0x6000_0000_0000_0000 + n for n in range(2)]
        await self._push("S16_Z0", "B", z[0])
        g_ctrl = self._item("G16_CTRL", SmcSysAxiOp.WRITE, "A", "CTRL", RFLUSH)
        g_rd = self._item("G16_READ", SmcSysAxiOp.READ, "A", "READ_DATA")
        await self._group("rflush_with_pop", [(g_ctrl, OKAY), (g_rd, OBSERVE)])
        await self._empty_read("S16_STALE", "A")
        await self._push("S16_Z1", "B", z[1])
        await self._pop("S16_P1", "A", z[1])
        self._mark_step("S16")
        self._log_chk(
            "CHK-FLUSH-VS-POP-NO-STALE-NO-STUCK",
            f"group CTRL resp {g_ctrl.resp_code}, grouped READ_DATA resp {g_rd.resp_code} "
            f"data={_hex(g_rd.rdata)} (measured, SF-024); afterwards A.READ_DATA answered "
            f"SLVERR with no stale Z0; Z1 round trip {_hex(z[1])}",
        )

        await self._wr("WIRQT_RESTORE", "A", "WIRQT", 0)
        await self._wr("RIRQT_RESTORE", "B", "RIRQT", 0)
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
            "CHK-NONVAC: ordered fence GATE_ENABLED<CTRL_ZERO<STATUS_WRITE_SIDE<STATUS_READ_SIDE<"
            "CTRL_AFTER_WRITE<CTRL_BOTH<WFLUSH_PEER<WFLUSH_OWN<WFLUSH_EMPTY<RFLUSH_EMPTIES<"
            "RFLUSH_PEER<RFLUSH_OWN<RFLUSH_EMPTY<RACE_WRITE<RACE_READ<RACE_POP; "
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
            "ERROR_FLAGS, IRQS, IRQEN, WIRQT, RIRQT, CTRL, grouped accesses) x%d bound=%d ns "
            "allow_timeout False last[%d accesses completed]; the drain loops are bounded by "
            "%d reads and raise AssertionError on expiry; the sequence has no other wait",
            waits,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.accesses,
            DRAIN_LIMIT,
        )
