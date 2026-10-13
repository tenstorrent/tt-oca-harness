# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox IRQS acknowledge, IRQP OR and the 32 inbound and 32 outbound interrupt outputs.

Contract SMC_MAILBOX_014, anchor smc_mailbox_irq_ack_output_test.
Scenarios: MBX-IRQS-ACK S1-S7, MBX-IRQ-OR S1-S3, MBX-IRQ-INBOUND-OUT S1-S4,
MBX-IRQ-OUTBOUND-OUT S1-S4, MBX-CG-ENABLED-ACCESS S4.
Sources: axi_lite_mailbox_unit architecture.adoc, interface.adoc; smc interrupts.adoc;
open SF-016/024/025.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import ClockCycles
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
WTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
RTIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__RTIRQ_bm")
EIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")
READ_ERROR = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__ERROR__READ_ERROR_bm")
THR_MASK = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__WIRQT__WIRQT_bm")
IRQ_ALL = WTIRQ | RTIRQ | EIRQ

FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
AXI_SLVERR = 2
EMPTY_ERROR_LOW = 0xFEEDDEAD
POLL_CAP = 128
ACK_READS = 16
LEVEL_CYCLES = 16
IDLE_CYCLES = 512
REPS = (0, 1, 15, 16, 31)
OKAY, ERROR = "okay", "error"
W1, W2, W3 = 0x1111_2222_3333_4444, 0x5555_6666_7777_8888, 0x99AA_BBCC_DDEE_FF01
_SRC_BIT = {"W": WTIRQ, "R": RTIRQ, "E": EIRQ}
_STEPS = tuple(f"S{n}" for n in range(1, 17))
_CHECKERS = (
    ("CHK-ACK-CLEARS-ONLY-WRITTEN-BITS", "S3"),
    ("CHK-IRQS-READ-DOES-NOT-CLEAR", "S3"),
    ("CHK-ACK-REASSERTS-OBSERVED", "S4"),
    ("CHK-ACK-AFTER-CONDITION-STAYS-CLEAR", "S5"),
    ("CHK-ACK-ERROR-BIT-SEPARATELY", "S6"),
    ("CHK-ACK-VS-EVENT-OBSERVED", "S7"),
    ("CHK-OR-EACH-SOURCE-ALONE", "S8"),
    ("CHK-OR-LATCHED-NOT-ENABLED", "S9"),
    ("CHK-OR-CLEAR-ONE-OF-TWO", "S10"),
    ("CHK-INBOUND-RAISES-OWN-BIT", "S11"),
    ("CHK-OUTBOUND-RAISES-OWN-BIT", "S12"),
    ("CHK-OUTPUT-IS-LEVEL-AND-FALLS", "S13"),
    ("CHK-CROSS-ISOLATION-INBOUND-OUTBOUND", "S14"),
    ("CHK-TWO-PAIRS-INDEPENDENT", "S15"),
    ("CHK-OUTPUT-HOLDS-ACROSS-IDLE", "S16"),
)


def _addr(target, reg: str) -> int:
    direction, pair = target
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{direction}_MAILBOX_{pair}_{reg}_BASE_ADDR")


def _inb(m: int):
    return ("INBOUND", m)


def _outb(m: int):
    return ("OUTBOUND", m)


def _peer(target):
    return (_outb if target[0] == "INBOUND" else _inb)(target[1])


class smc_mailbox_irq_ack_output_test_seq(SmcCsrSeq):
    """Acknowledge IRQS bits and watch the interrupt outputs of representative pairs."""

    def __init__(self, name: str = "smc_mailbox_irq_ack_output_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, list] = {}

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _probe(name: str) -> int:
        raw = getattr(cocotb.top, name).value
        assert raw.is_resolvable, f"{name} is X/Z: {raw}"
        return int(raw)

    def _vectors(self) -> tuple[int, int, int]:
        cpu = (self._probe("tb_cpu_interrupts") >> 288) & 0xFFFF_FFFF
        return self._probe("tb_mailbox_interrupts"), self._probe("tb_ext_mailbox_interrupts"), cpu

    async def _poll(self, tag: str, want_in: int, want_ext: int) -> tuple[int, int, int]:
        """Sample each clk_smc_i cycle until both vectors match; expiry raises."""
        for n in range(POLL_CAP + 1):
            vec = self._vectors()
            self._waits[tag] = [POLL_CAP, n, vec[0], vec[1]]
            if vec[:2] == (want_in, want_ext):
                return n, *vec
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{tag}: want in=0x{want_in:08x} ext=0x{want_ext:08x} within {POLL_CAP} cycles, "
            f"last in=0x{vec[0]:08x} ext=0x{vec[1]:08x}"
        )

    async def _hold(self, tag: str, want_in: int, want_ext: int, cycles: int) -> None:
        """Sample every clk_smc_i cycle; any deviation raises."""
        for n in range(cycles):
            vec = self._vectors()
            self._waits[tag] = [cycles, n, vec[0], vec[1]]
            assert vec[:2] == (want_in, want_ext), (
                f"{tag}: cycle {n} in=0x{vec[0]:08x} ext=0x{vec[1]:08x}, "
                f"want in=0x{want_in:08x} ext=0x{want_ext:08x}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, 1)

    @staticmethod
    def _item(name, op, target, reg, data=0, mode=OKAY, expected=None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value[0]}_{name}")
        item.op, item.addr, item.length = op, _addr(target, reg), 8
        item.wdata, item.expected = data, expected
        item.allow_error = False
        item.expect_error = mode == ERROR
        item.expected_resp = AXI_SLVERR if mode == ERROR else None
        return item

    @staticmethod
    def _check(item: SmcSysAxiItem, mode: str) -> SmcSysAxiItem:
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

    async def _wr(self, name, target, reg, data):
        return await self._do(name, SmcSysAxiOp.WRITE, target, reg, data)

    async def _val(self, name, target, reg) -> int:
        return (await self._do(name, SmcSysAxiOp.READ, target, reg)).rdata

    async def _irqs(self, name, target, mask=IRQ_ALL) -> int:
        return await self._val(name, target, "IRQS") & mask

    async def _pop(self, name, target, expected):
        await self._do(name, SmcSysAxiOp.READ, target, "READ_DATA", expected=expected)

    async def _group(self, name, members) -> None:
        group = SmcSysAxiGroupItem(name, [m for m, _ in members])
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        for member, mode in members:
            self._check(member, mode)

    async def _ack(self, tag, target, bits=IRQ_ALL) -> None:
        await self._wr(f"{tag}_ACK", target, "IRQS", bits)

    async def _quiesce(self, tag, target) -> None:
        """Acknowledge every IRQS bit of the aperture and its peer; both read 0."""
        for side in (target, _peer(target)):
            await self._ack(tag, side)
            got = await self._irqs(f"{tag}_CLR", side)
            assert got == 0, f"{tag}: IRQS of {side} reads 0x{got:x} after acknowledge"

    async def _raise(self, tag, target, kind) -> None:
        """Latch one IRQS source on the aperture: W queued word, R received word, E empty read."""
        if kind == "W":
            await self._wr(f"{tag}_W", target, "WRITE_DATA", W1)
        elif kind == "R":
            await self._wr(f"{tag}_R", _peer(target), "WRITE_DATA", W2)
        else:
            await self._do(f"{tag}_E", SmcSysAxiOp.READ, target, "READ_DATA", mode=ERROR)

    async def _end(self, tag, target, kind) -> None:
        """End the occupancy condition raised by _raise."""
        if kind == "W":
            await self._pop(f"{tag}_END", _peer(target), W1)
        elif kind == "R":
            await self._pop(f"{tag}_END", target, W2)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        seed = int(os.environ.get("RANDOM_SEED", "1"))
        cocotb.log.info("SEED RANDOM_SEED=%d", seed)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN
        )
        self._mark_step("S1")

        await self._hold("S2_baseline", 0, 0, 4)
        self._mark_step("S2")

        A, B = _outb(1), _inb(1)
        await self._wr("IRQEN_A0", A, "IRQEN", 0)
        await self._wr("IRQEN_B0", B, "IRQEN", 0)
        await self._wr("RIRQT_A0", A, "RIRQT", 0)
        await self._quiesce("S3P", A)
        await self._wr("A_W0", A, "WRITE_DATA", W1)
        await self._wr("A_W1", A, "WRITE_DATA", W2)
        await self._do("A_FULL", SmcSysAxiOp.WRITE, A, "WRITE_DATA", W3, mode=ERROR)
        await self._wr("B_TO_A", B, "WRITE_DATA", W3)
        built = await self._irqs("S3_BUILT", A)
        again = await self._irqs("S3_AGAIN", A)
        await self._ack("S3_ZERO", A, 0)
        after_zero = await self._irqs("S3_AFTER_ZERO", A)
        await self._ack("S3_BIT2", A, EIRQ)
        after_bit2 = await self._irqs("S3_AFTER_BIT2", A)
        assert (built, again) == (IRQ_ALL, IRQ_ALL), f"IRQS reads 0x{built:x} 0x{again:x}"
        assert (after_zero, after_bit2) == (IRQ_ALL, WTIRQ | RTIRQ), (after_zero, after_bit2)
        self._mark_step("S3")
        self._log_chk(
            "CHK-ACK-CLEARS-ONLY-WRITTEN-BITS",
            f"set: three sources latched; observed: IRQS[2:0]=0b{built:03b}, 0b{after_zero:03b} "
            f"after writing 0x0; cleared: write 0x4; checked_cleared: IRQS[2:0]=0b{after_bit2:03b}",
        )
        self._log_chk(
            "CHK-IRQS-READ-DOES-NOT-CLEAR",
            f"two consecutive IRQS reads returned 0b{built:03b} and 0b{again:03b}",
        )

        await self._ack("S4_ACK", A, WTIRQ | RTIRQ)
        reads = 0
        got = 0
        while reads < ACK_READS and got != (WTIRQ | RTIRQ):
            got = await self._irqs(f"S4_RD{reads}", A, WTIRQ | RTIRQ)
            reads += 1
        assert got == (WTIRQ | RTIRQ), f"IRQS[1:0] not set again within {ACK_READS} reads"
        self._mark_step("S4")
        self._log_chk(
            "CHK-ACK-REASSERTS-OBSERVED",
            f"set: occupancy above both thresholds; observed: IRQS[1:0]=0b{got:02b} again "
            f"after write 0x3 and {reads} reads (timing not compared, SF-016); cleared: write 0x3; "
            f"checked_cleared: IRQS[1:0] read 0b{got:02b} within {ACK_READS} reads",
        )

        await self._pop("S5_POP_B0", B, W1)
        await self._pop("S5_POP_B1", B, W2)
        await self._pop("S5_POP_A", A, W3)
        latched = await self._irqs("S5_LATCHED", A, WTIRQ | RTIRQ)
        await self._ack("S5_ACK", A, WTIRQ | RTIRQ)
        clear1 = await self._irqs("S5_CLR1", A, WTIRQ | RTIRQ)
        clear2 = await self._irqs("S5_CLR2", A, WTIRQ | RTIRQ)
        assert (latched, clear1, clear2) == (WTIRQ | RTIRQ, 0, 0), (latched, clear1, clear2)
        await self._quiesce("S5_END", B)
        self._mark_step("S5")
        self._log_chk(
            "CHK-ACK-AFTER-CONDITION-STAYS-CLEAR",
            f"set: latched bits with the conditions ended; observed: IRQS[1:0]=0b{latched:02b} "
            f"after the pops; cleared: write 0x3; checked_cleared: IRQS[1:0]={clear1} then "
            f"{clear2}",
        )

        drained = await self._val("S6_DRAIN", A, "ERROR_FLAGS") & 0x3
        await self._raise("S6", A, "E")
        irqs_err = await self._irqs("S6_IRQS1", A)
        flags = await self._val("S6_FLAGS", A, "ERROR_FLAGS") & 0x3
        irqs_kept = await self._irqs("S6_IRQS2", A)
        await self._ack("S6_ACK", A, EIRQ)
        irqs_clr = await self._irqs("S6_IRQS3", A)
        assert (irqs_err, flags, irqs_kept, irqs_clr) == (EIRQ, READ_ERROR, EIRQ, 0), (
            irqs_err,
            flags,
            irqs_kept,
            irqs_clr,
        )
        self._mark_step("S6")
        self._log_chk(
            "CHK-ACK-ERROR-BIT-SEPARATELY",
            f"set: empty read latched IRQS[2]; observed: IRQS=0b{irqs_err:03b}, ERROR_FLAGS="
            f"0b{flags:02b} (earlier flags drained 0b{drained:02b}), IRQS=0b{irqs_kept:03b} after "
            f"the ERROR_FLAGS read; cleared: write 0x4; checked_cleared: IRQS=0b{irqs_clr:03b}",
        )

        irqs_before = await self._irqs("S7_BEFORE", A)
        assert irqs_before == 0, f"IRQS 0x{irqs_before:x} before the group"
        ack = self._item("S7_ACK", SmcSysAxiOp.WRITE, A, "IRQS", WTIRQ)
        push = self._item("S7_PUSH", SmcSysAxiOp.WRITE, A, "WRITE_DATA", W1)
        await self._group("ack_vs_event", [(ack, OKAY), (push, OKAY)])
        bit0 = await self._irqs("S7_AFTER", A, WTIRQ)
        await self._pop("S7_POP", B, W1)
        await self._quiesce("S7_END", A)
        await self._quiesce("S7_END", B)
        self._mark_step("S7")
        self._log_chk(
            "CHK-ACK-VS-EVENT-OBSERVED",
            f"IRQS[0]={bit0} after the group {{IRQS write 0x1, WRITE_DATA write}}; responses "
            f"ack={ack.resp_code} write={push.resp_code}; no compare (SF-016), no same-cycle "
            "alignment claimed (SF-024)",
        )

        X, Y = B, A
        alone = []
        for kind in "WRE":
            await self._wr(f"S8_EN_{kind}", X, "IRQEN", _SRC_BIT[kind])
            await self._raise(f"S8_{kind}", X, kind)
            n, vin, vext, _ = await self._poll(f"S8_rise_{kind}", 0x2, 0)
            irqp = await self._val(f"S8_IRQP_{kind}", X, "IRQP") & IRQ_ALL
            assert irqp == _SRC_BIT[kind], f"{kind}: IRQP 0x{irqp:x}"
            await self._end(f"S8_{kind}", X, kind)
            await self._ack(f"S8_{kind}", X)
            m, _, _, _ = await self._poll(f"S8_fall_{kind}", 0, 0)
            alone.append(f"{kind}:IRQP=0b{irqp:03b} rise@{n} fall@{m}")
            await self._wr(f"S8_EN0_{kind}", X, "IRQEN", 0)
            await self._quiesce(f"S8_Q{kind}", X)
        self._mark_step("S8")
        self._log_chk(
            "CHK-OR-EACH-SOURCE-ALONE",
            f"set: one IRQP bit on X; observed: tb_mailbox_interrupts==0x00000002 for each "
            f"source {alone}; cleared: condition ended and IRQS acknowledged; "
            "checked_cleared: tb_mailbox_interrupts==0",
        )

        latch = []
        for kind in "WRE":
            await self._raise(f"S9_{kind}", X, kind)
            await self._hold(f"S9_low_{kind}", 0, 0, LEVEL_CYCLES)
            irqs = await self._irqs(f"S9_IRQS_{kind}", X)
            assert irqs == _SRC_BIT[kind], f"{kind}: IRQS 0x{irqs:x}, want 0x{_SRC_BIT[kind]:x}"
            await self._end(f"S9_{kind}", X, kind)
            await self._quiesce(f"S9_Q{kind}", X)
            latch.append(f"{kind}:IRQS=0b{irqs:03b}")
        self._mark_step("S9")
        self._log_chk(
            "CHK-OR-LATCHED-NOT-ENABLED",
            f"IRQEN=0; set: source latched {latch} (positive control); observed: "
            f"tb_mailbox_interrupts==0 on {LEVEL_CYCLES} consecutive cycles per source; "
            "cleared: IRQS acknowledged; checked_cleared: output 0 throughout",
        )

        both = []
        for target, label in ((X, "inbound"), (Y, "outbound")):
            want = (0x2, 0) if target is X else (0, 0x2)
            zero = (0, 0)
            await self._wr(f"S10_EN_{label}", target, "IRQEN", IRQ_ALL)
            await self._raise(f"S10_{label}", target, "W")
            await self._raise(f"S10_{label}", target, "E")
            await self._poll(f"S10_rise_{label}", *want)
            irqp = await self._val(f"S10_IRQP_{label}", target, "IRQP") & IRQ_ALL
            assert irqp == WTIRQ | EIRQ, f"{label}: IRQP 0x{irqp:x}"
            await self._end(f"S10_{label}", target, "W")
            await self._ack(f"S10_B0_{label}", target, WTIRQ)
            await self._hold(f"S10_high_{label}", *want, 8)
            left = await self._val(f"S10_IRQP2_{label}", target, "IRQP") & IRQ_ALL
            assert left == EIRQ, f"{label}: IRQP 0x{left:x} after bit 0 acknowledge"
            await self._ack(f"S10_B2_{label}", target, EIRQ)
            await self._poll(f"S10_fall_{label}", *zero)
            await self._wr(f"S10_EN0_{label}", target, "IRQEN", 0)
            await self._quiesce(f"S10_Q_{label}", target)
            both.append(f"{label}:IRQP 0b{irqp:03b}->0b{left:03b}->0")
        self._mark_step("S10")
        self._log_chk(
            "CHK-OR-CLEAR-ONE-OF-TWO",
            f"set: IRQP bits 0 and 2 pending; observed: output bit 1 reads 1 {both}; cleared: "
            "bit 0 then bit 2 acknowledged; checked_cleared: output 1 after the first (8 "
            "cycles) and 0 after the second, on tb_mailbox_interrupts and "
            "tb_ext_mailbox_interrupts",
        )

        async def raise_one(tag, target, bit, direction):
            want_in, want_ext = (bit, 0) if direction == "in" else (0, bit)
            await self._wr(f"{tag}_EN", target, "IRQEN", WTIRQ)
            await self._raise(tag, target, "W")
            n, vin, vext, cpu = await self._poll(f"{tag}_rise", want_in, want_ext)
            return n, vin, vext, cpu

        async def drop_one(tag, target):
            await self._end(tag, target, "W")
            await self._ack(tag, target)
            await self._wr(f"{tag}_EN0", target, "IRQEN", 0)
            await self._poll(f"{tag}_fall", 0, 0)
            await self._quiesce(f"{tag}_Q", target)

        rows = []
        for m in REPS:
            bit = 1 << m
            n, vin, vext, cpu = await raise_one(f"S11_P{m}", _inb(m), bit, "in")
            assert cpu == vin == bit and vext == 0, (m, vin, vext, cpu)
            await drop_one(f"S11_P{m}", _inb(m))
            rows.append(f"pair {m}: in=0x{vin:08x} cpu=0x{cpu:08x} ext=0x{vext:08x} rise@{n}")
        self._mark_step("S11")
        self._log_chk(
            "CHK-INBOUND-RAISES-OWN-BIT",
            f"set: inbound IRQP non-zero; observed: {rows}; cleared: condition ended and IRQS "
            "acknowledged; checked_cleared: tb_mailbox_interrupts==0 for each pair",
        )

        rows = []
        for m in REPS:
            bit = 1 << m
            n, vin, vext, _ = await raise_one(f"S12_P{m}", _outb(m), bit, "ext")
            assert vext == bit and vin == 0, (m, vin, vext)
            await drop_one(f"S12_P{m}", _outb(m))
            rows.append(f"pair {m}: ext=0x{vext:08x} in=0x{vin:08x} rise@{n}")
        self._mark_step("S12")
        self._log_chk(
            "CHK-OUTBOUND-RAISES-OWN-BIT",
            f"set: outbound IRQP non-zero; observed: {rows}; cleared: condition ended and IRQS "
            "acknowledged; checked_cleared: tb_ext_mailbox_interrupts==0 for each pair",
        )

        for m in (15, 16):
            bit = 1 << m
            xi, yo = _inb(m), _outb(m)
            await self._wr(f"S13_ENX{m}", xi, "IRQEN", WTIRQ)
            await self._wr(f"S13_ENY{m}", yo, "IRQEN", WTIRQ)
            await self._raise(f"S13_X{m}", xi, "W")
            await self._raise(f"S13_Y{m}", yo, "W")
            await self._poll(f"S13_rise_{m}", bit, bit)
            irqp_x = await self._val(f"S13_IRQPX{m}", xi, "IRQP") & IRQ_ALL
            irqp_y = await self._val(f"S13_IRQPY{m}", yo, "IRQP") & IRQ_ALL
            assert irqp_x and irqp_y, f"pair {m}: IRQP 0x{irqp_x:x} 0x{irqp_y:x}"
            await self._hold(f"S13_level_{m}", bit, bit, LEVEL_CYCLES)
            await self._pop(f"S13_POPY{m}", yo, W1)
            await self._pop(f"S13_POPX{m}", xi, W1)
            await self._ack(f"S13_ACKX{m}", xi)
            await self._ack(f"S13_ACKY{m}", yo)
            await self._poll(f"S13_fall_{m}", 0, 0)
            await self._wr(f"S13_EN0X{m}", xi, "IRQEN", 0)
            await self._wr(f"S13_EN0Y{m}", yo, "IRQEN", 0)
            await self._quiesce(f"S13_Q{m}", xi)
        self._mark_step("S13")
        self._log_chk(
            "CHK-OUTPUT-IS-LEVEL-AND-FALLS",
            f"set: IRQP non-zero on both apertures of pairs 15 and 16; observed: both outputs "
            f"read 1 on {LEVEL_CYCLES} consecutive cycles per pair; cleared: conditions ended "
            "and IRQS acknowledged; checked_cleared: both outputs read 0",
        )

        bit = 1 << 16
        xi, yo = _inb(16), _outb(16)
        await self._wr("S14_ENX", xi, "IRQEN", WTIRQ)
        await self._wr("S14_ENY", yo, "IRQEN", WTIRQ)
        await self._raise("S14_Y", yo, "W")
        _, out_in, out_ext, _ = await self._poll("S14_outbound_only", 0, bit)
        await self._end("S14_Y", yo, "W")
        await self._ack("S14_ACKY", yo)
        await self._quiesce("S14_QY", xi)
        await self._poll("S14_fall_outbound", 0, 0)
        await self._raise("S14_X", xi, "W")
        _, in_in, in_ext, _ = await self._poll("S14_inbound_only", bit, 0)
        await self._end("S14_X", xi, "W")
        await self._ack("S14_ACKX", xi)
        await self._quiesce("S14_QX", xi)
        await self._poll("S14_fall_inbound", 0, 0)
        await self._wr("S14_EN0X", xi, "IRQEN", 0)
        await self._wr("S14_EN0Y", yo, "IRQEN", 0)
        self._mark_step("S14")
        self._log_chk(
            "CHK-CROSS-ISOLATION-INBOUND-OUTBOUND",
            f"pair 16 outbound-only: in=0x{out_in:08x} ext=0x{out_ext:08x}; inbound-only: "
            f"in=0x{in_in:08x} ext=0x{in_ext:08x}",
        )

        async def two_pairs(tag, make, direction):
            lo, hi = make(0), make(31)
            for t in (lo, hi):
                await self._wr(f"{tag}_EN{t[1]}", t, "IRQEN", WTIRQ)
            for t in (lo, hi):
                await self._raise(f"{tag}_R{t[1]}", t, "W")
            order = (lambda v: (v, 0)) if direction == "in" else (lambda v: (0, v))
            seen = []
            for t, want in ((None, 0x8000_0001), (lo, 0x8000_0000), (hi, 0)):
                if t is not None:
                    await self._end(f"{tag}_E{t[1]}", t, "W")
                    await self._ack(f"{tag}_A{t[1]}", t)
                _, vin, vext, _ = await self._poll(f"{tag}_vec", *order(want))
                seen.append(f"0x{(vin if direction == 'in' else vext):08x}")
            for t in (lo, hi):
                await self._wr(f"{tag}_EN0{t[1]}", t, "IRQEN", 0)
                await self._quiesce(f"{tag}_Q{t[1]}", t)
            return seen

        inbound_seen = await two_pairs("S15I", _inb, "in")
        outbound_seen = await two_pairs("S15O", _outb, "ext")
        self._mark_step("S15")
        self._log_chk(
            "CHK-TWO-PAIRS-INDEPENDENT",
            f"pairs 0 and 31: tb_mailbox_interrupts {inbound_seen}, tb_ext_mailbox_interrupts "
            f"{outbound_seen} (both raised, pair 0 acknowledged, pair 31 acknowledged)",
        )

        xi = _inb(7)
        await self._wr("S16_EN", xi, "IRQEN", WTIRQ)
        await self._raise("S16", xi, "W")
        n, _, _, _ = await self._poll("S16_rise", 0x80, 0)
        await self._hold("S16_idle", 0x80, 0, IDLE_CYCLES)
        await self._end("S16", xi, "W")
        await self._ack("S16_ACK", xi)
        await self._wr("S16_EN0", xi, "IRQEN", 0)
        await self._poll("S16_fall", 0, 0)
        await self._quiesce("S16_Q", xi)
        self._mark_step("S16")
        self._log_chk(
            "CHK-OUTPUT-HOLDS-ACROSS-IDLE",
            f"set: inbound IRQP non-zero on pair 7; observed: tb_mailbox_interrupts==0x00000080 "
            f"on {IDLE_CYCLES} consecutive idle cycles after rising at cycle {n}; cleared: "
            "condition ended and IRQS acknowledged; checked_cleared: output 0; the gate idle "
            "state is not observed (SF-025)",
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
            "CHK-NONVAC: ordered fence GATE_ENABLED<ACK_STATE<ACK_REASSERT<ACK_CLEAR<ACK_ERROR<"
            "ACK_EVENT<OR_ALONE<OR_LATCHED<OR_CLEAR<INBOUND_REPS<OUTBOUND_REPS<LEVEL<CROSS<"
            "TWO_PAIRS<IDLE_HOLD; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    @staticmethod
    def _level(name: str) -> str:
        sig = getattr(cocotb.top, name, None)
        return "absent" if sig is None else str(int(sig.value))

    def _log_timeout_paths(self) -> None:
        subs = ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n")
        fuse = "; ".join(
            f"fuse sense wait {sig} (AssertionError on expiry) bound={FUSE_SENSE_RISES} rises "
            f"last[{sig}={self._level(sig)}]"
            for sig in subs
        )
        own = "; ".join(
            f"{tag} (AssertionError on expiry) bound={cap} cycles last[cycles={used} "
            f"in=0x{vin:08x} ext=0x{vext:08x}]"
            for tag, (cap, used, vin, vext) in self._waits.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry; %s; "
            "own probe waits per clk_smc_i cycle: %s; SEP_IN CSR accesses (CLOCK_GATE_CONTROL, "
            "mailbox WRITE_DATA, READ_DATA, IRQS, IRQEN, IRQP, RIRQT, ERROR_FLAGS, grouped "
            "accesses) x%d bound=%d ns allow_timeout False last[%d accesses completed]",
            fuse,
            own,
            self.accesses,
            AXI_TIMEOUT_NS,
            self.accesses,
        )
