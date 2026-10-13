# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox aperture decode, reset values, attributes and enabled-gate access.

Contract SMC_MAILBOX_010, anchor smc_mailbox_register_map_reset_test.
Scenarios: MBX-ADDR-MAP S1-S5, MBX-RESET-STATE S1-S4, MBX-ATTRIBUTES S1-S3,
MBX-CG-ENABLED-ACCESS S1/S2/S3/S5.
Sources: axi_lite_mailbox_unit axil_mailbox.rdl, memmap.adoc, interface.adoc, architecture.adoc;
smc clk_rst.adoc, interrupts.adoc, periphs.adoc; open SF-017/023/025.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_addr_symbols
from .smc_csr_seq_utils import SmcCsrSeq

_AXIL_MAILBOX_H = (
    _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
SMC_ATTRIBUTES = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h",
    "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm",
)
EIRQ = _field_mask(_AXIL_MAILBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")

FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
AXI_SLVERR = 2
EMPTY_ERROR_LOW = 0xFEEDDEAD
WRITE_DATA_EMPTY_LOW = 0xFEEDC0DE
MAILBOX_BASE = 0xC001_8000
PAIR_STRIDE = 0x1000
INBOUND_OFFSET = 0x800
IDLE_GAP_CYCLES = 512
POLL_CAP = 64
NUM_PAIRS = 32
REPRESENTATIVE = (0, 1, 15, 16, 31)
SIDE = {"A": "OUTBOUND", "B": "INBOUND"}
OKAY, ERROR = "okay", "error"
# Register, defined-bit mask and reset value; the bits above the mask are reserved (SF-022).
RESET_REGS = (
    ("STATUS", 0xF, 0x1),
    ("ERROR_FLAGS", 0x3, 0),
    ("WIRQT", 0xFF, 0),
    ("RIRQT", 0xFF, 0),
    ("IRQS", 0x7, 0),
    ("IRQEN", 0x7, 0),
    ("IRQP", 0x7, 0),
    ("CTRL", 0x3, 0),
)
_OUTBOUND_SYMBOLS = smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_\d+_BASE_ADDR")
_INBOUND_SYMBOLS = smc_addr_symbols(r"SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_\d+_BASE_ADDR")
assert len(_OUTBOUND_SYMBOLS) == len(_INBOUND_SYMBOLS) == NUM_PAIRS

_STEPS = tuple(f"S{n}" for n in range(1, 16))
_STEP_NAMES = (
    "BRING_UP<GATE_RESET_AND_SET<VECTORS_LOW<RESET_REGS<RESET_64<RESET_EMPTY_READS<DECODE<"
    "OFFSETS<PER_APERTURE<ADDRESS_EXAMPLES<ATTRIBUTES_LOGGED<PAIR31<IDLE_FIRST_ACCESS<"
    "IDLE_RETENTION<BACK_TO_BACK"
)
_CHECKERS = (
    ("CHK-CG-ENABLE-RESET-AND-SET", "S2"),
    ("CHK-RESET-REGISTERS-REPRESENTATIVE-PAIRS", "S4"),
    ("CHK-RESET-ALL-64-APERTURES", "S5"),
    ("CHK-RESET-EMPTY-READ-BOTH-DIRECTIONS", "S6"),
    ("CHK-APERTURE-DECODE-OUTBOUND", "S7"),
    ("CHK-APERTURE-DECODE-INBOUND", "S7"),
    ("CHK-REGISTER-OFFSETS-PAIR0", "S8"),
    ("CHK-REGISTER-STATE-PER-APERTURE", "S9"),
    ("CHK-ADDRESS-EXAMPLES-PAIR0", "S10"),
    ("CHK-ATTRIBUTES-OBSERVED", "S11"),
    ("CHK-ATTRIBUTES-MATCH-OBSERVED-UNIT", "S12"),
    ("CHK-IRQ-VECTORS-LOW-AT-RESET", "S3"),
    ("CHK-CG-FIRST-ACCESS-AFTER-IDLE", "S13"),
    ("CHK-CG-RETENTION-ACROSS-IDLE", "S14"),
    ("CHK-CG-BACK-TO-BACK-IN-ORDER", "S15"),
)


def _addr(pair: int, side: str, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{SIDE[side]}_MAILBOX_{pair}_{reg}_BASE_ADDR")


class smc_mailbox_register_map_reset_test_seq(SmcCsrSeq):
    """Sweep reset state, decode and enabled-gate access of the 64 mailbox apertures."""

    def __init__(self, name: str = "smc_mailbox_register_map_reset_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._latency = [0, 0]
        self._waits: dict[str, tuple] = {}

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _item(name, op, pair, side, reg, data=0, mode=OKAY, expected=None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value[0]}_{name}")
        item.op, item.addr, item.length = op, _addr(pair, side, reg), 8
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

    async def _send(self, item: SmcSysAxiItem, mode: str) -> SmcSysAxiItem:
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return self._check(item, mode)

    async def _wr(self, name, pair, side, reg, data, mode=OKAY):
        item = self._item(name, SmcSysAxiOp.WRITE, pair, side, reg, data, mode)
        return await self._send(item, mode)

    async def _rd(self, name, pair, side, reg, mode=OKAY, expected=None):
        item = self._item(name, SmcSysAxiOp.READ, pair, side, reg, 0, mode, expected)
        return await self._send(item, mode)

    async def _val(self, name, pair, side, reg) -> int:
        return (await self._rd(name, pair, side, reg)).rdata

    async def _pop(self, name, pair, side, expected):
        return await self._rd(name, pair, side, "READ_DATA", expected=expected)

    async def _empty_read(self, name, pair, side) -> int:
        item = await self._rd(name, pair, side, "READ_DATA", mode=ERROR)
        assert item.rdata & 0xFFFF_FFFF == EMPTY_ERROR_LOW, f"{name}: data 0x{item.rdata:x}"
        return item.rdata

    async def _group(self, name, members) -> None:
        group = SmcSysAxiGroupItem(name, members)
        await self.start_item(group)
        await self.finish_item(group)
        self.accesses += len(members)
        for member in members:
            self._check(member, OKAY)

    @staticmethod
    def _probe(name: str) -> int:
        raw = getattr(cocotb.top, name).value
        assert raw.is_resolvable, f"{name} is X/Z: {raw}"
        return int(raw)

    def _vectors(self) -> tuple[int, int, int]:
        cpu = (self._probe("tb_cpu_interrupts") >> 288) & 0xFFFF_FFFF
        return self._probe("tb_mailbox_interrupts"), self._probe("tb_ext_mailbox_interrupts"), cpu

    async def _poll_vectors(self, tag: str, want_in: int, want_ext: int) -> tuple:
        """Sample each clk_smc_i cycle until the vectors match; expiry raises."""
        for n in range(POLL_CAP + 1):
            vec = self._vectors()
            self._waits[tag] = (POLL_CAP, n, vec)
            if vec[:2] == (want_in, want_ext) and vec[2] == want_in:
                return n, vec
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(f"{tag}: want in=0x{want_in:x} ext=0x{want_ext:x}, last {vec}")

    async def _idle_gap(self) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, IDLE_GAP_CYCLES)

    async def _timed_write(self, pair: int, data: int) -> None:
        count = [0]

        async def counter() -> None:
            while True:
                await RisingEdge(cocotb.top.clk_smc_i)
                count[0] += 1

        task = cocotb.start_soon(counter())
        try:
            await self._wr("IDLE_FIRST", pair, "A", "WRITE_DATA", data)
        finally:
            task.cancel()
        self._latency = [count[0], 0]

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        cocotb.log.info("seed: %s", os.environ.get("RANDOM_SEED", "1"))
        self._mark_step("S1")

        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        assert cg & MAILBOX_CG_EN == 0, f"mailbox_cg_en reset 0x{cg:x}, want 0"
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        cg_rb = await self.csr_read("CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL)
        assert cg_rb & MAILBOX_CG_EN, f"mailbox_cg_en readback 0x{cg_rb:x}, want bit 1 set"
        self._mark_step("S2")
        self._log_chk(
            "CHK-CG-ENABLE-RESET-AND-SET",
            f"set: mailbox_cg_en reset value {cg >> 1 & 1}; observed: CLOCK_GATE_CONTROL read "
            f"0x{cg:x}; cleared: write sets bit 1; checked_cleared: read back 0x{cg_rb:x} "
            f"bit 1 = {cg_rb >> 1 & 1}",
        )

        first = self._vectors()
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        second = self._vectors()
        assert first == (0, 0, 0) and second == (0, 0, 0), f"vectors {first} then {second}"
        self._mark_step("S3")
        reads, upper = 0, {}
        for pair in REPRESENTATIVE:
            for side in "AB":
                for reg, mask, reset in RESET_REGS:
                    val = await self._val(f"RST_{reg}_{pair}{side}", pair, side, reg)
                    assert val & mask == reset, (
                        f"pair {pair} {side} {reg} 0x{val:x}, want 0x{reset:x} under 0x{mask:x}"
                    )
                    reads += 1
                    if val & ~mask:
                        upper[f"{pair}{side}.{reg}"] = val & ~mask
        self._mark_step("S4")
        self._log_chk(
            "CHK-RESET-REGISTERS-REPRESENTATIVE-PAIRS",
            f"{reads} reads on {2 * len(REPRESENTATIVE)} apertures: STATUS[3:0]==0x1 and "
            f"ERROR_FLAGS[1:0], WIRQT[7:0], RIRQT[7:0], IRQS[2:0], IRQEN[2:0], IRQP[2:0], "
            f"CTRL[1:0]==0; reserved upper bits nonzero in {len(upper)} reads {upper} (SF-022)",
        )

        reads = 0
        for pair in range(NUM_PAIRS):
            for side in "AB":
                st = await self._val(f"S5_STATUS_{pair}{side}", pair, side, "STATUS")
                irqs = await self._val(f"S5_IRQS_{pair}{side}", pair, side, "IRQS")
                assert st & 0xF == 0x1 and irqs & 0x7 == 0, (
                    f"pair {pair} {side}: STATUS 0x{st:x} IRQS 0x{irqs:x}"
                )
                reads += 2
        self._mark_step("S5")
        self._log_chk(
            "CHK-RESET-ALL-64-APERTURES",
            f"{reads} reads on 64 apertures: STATUS[3:0]==0x1 and IRQS[2:0]==0 on every one",
        )

        empties = {}
        for pair in (0, 31):
            for side in "AB":
                empties[f"{pair}{side}"] = await self._empty_read(f"S6_{pair}{side}", pair, side)
        for pair in (0, 31):
            for side in "AB":
                latched = await self._val(f"S6_IRQS_{pair}{side}", pair, side, "IRQS")
                flags = await self._val(f"S6_EF_CLEAN_{pair}{side}", pair, side, "ERROR_FLAGS")
                assert latched & EIRQ and flags & 1, f"IRQS 0x{latched:x} flags {flags}"
                await self._wr(f"S6_IRQS_CLEAN_{pair}{side}", pair, side, "IRQS", EIRQ)
        self._mark_step("S6")
        self._log_chk(
            "CHK-RESET-EMPTY-READ-BOTH-DIRECTIONS",
            f"READ_DATA of 4 apertures answered SLVERR with rdata[31:0]=0x{EMPTY_ERROR_LOW:08x} "
            f"on each: " + ",".join(f"{k}=0x{v & 0xFFFFFFFF:08x}" for k, v in empties.items()),
        )

        out_addrs, in_addrs = [], []
        for pair in REPRESENTATIVE:
            out_addrs.append(smc_addr(f"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_{pair}_BASE_ADDR"))
            in_addrs.append(smc_addr(f"SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_{pair}_BASE_ADDR"))
            want = MAILBOX_BASE + pair * PAIR_STRIDE
            assert out_addrs[-1] == want, f"outbound {pair} 0x{out_addrs[-1]:x}, want 0x{want:x}"
            assert in_addrs[-1] == want + INBOUND_OFFSET, f"inbound {pair} 0x{in_addrs[-1]:x}"
        decode = {}
        for tag, driven, other in (("OUT", "A", "B"), ("IN", "B", "A")):
            for idx, pair in enumerate(REPRESENTATIVE):
                await self._wr(f"S7_{tag}_{pair}", pair, driven, "IRQEN", idx + 1)
            got = [
                await self._val(f"S7_{tag}_RB_{p}", p, driven, "IRQEN") & 7 for p in REPRESENTATIVE
            ]
            idle = [
                await self._val(f"S7_{tag}_OTHER_{p}", p, other, "IRQEN") & 7
                for p in REPRESENTATIVE
            ]
            assert got == [1, 2, 3, 4, 5], f"{tag} IRQEN readback {got}"
            assert idle == [0] * 5, f"{tag} other-side IRQEN {idle}"
            for pair in REPRESENTATIVE:
                await self._wr(f"S7_{tag}_RESTORE_{pair}", pair, driven, "IRQEN", 0)
            decode[tag] = (got, idle)
        self._mark_step("S7")
        out_hex = ",".join(f"0x{a:08x}" for a in out_addrs)
        in_hex = ",".join(f"0x{a:08x}" for a in in_addrs)
        self._log_chk(
            "CHK-APERTURE-DECODE-OUTBOUND",
            f"addresses {out_hex} equal 0xC0018000+m*0x1000; outbound IRQEN of pairs "
            f"{REPRESENTATIVE} read {decode['OUT'][0]}, inbound IRQEN read {decode['OUT'][1]}",
        )
        self._log_chk(
            "CHK-APERTURE-DECODE-INBOUND",
            f"addresses {in_hex} equal outbound+0x800; inbound IRQEN of pairs "
            f"{REPRESENTATIVE} read {decode['IN'][0]}, outbound IRQEN read {decode['IN'][1]}",
        )

        seen = {}
        for side in "AB":
            wd = await self._rd(f"S8_WD_{side}", 0, side, "WRITE_DATA")
            assert wd.rdata & 0xFFFF_FFFF == WRITE_DATA_EMPTY_LOW, f"WRITE_DATA 0x{wd.rdata:x}"
            st = await self._val(f"S8_STATUS_{side}", 0, side, "STATUS")
            assert st & 0xF == 0x1, f"STATUS 0x{st:x}"
            for reg, mask in (("ERROR_FLAGS", 3), ("IRQS", 7), ("IRQP", 7), ("CTRL", 3)):
                val = await self._val(f"S8_{reg}_{side}", 0, side, reg)
                assert val & mask == 0, f"pair 0 {side} {reg} 0x{val:x}"
            for reg, value, mask in (("WIRQT", 1, 0xFF), ("RIRQT", 1, 0xFF), ("IRQEN", 5, 7)):
                await self._wr(f"S8_{reg}_{side}", 0, side, reg, value)
                for other, omask, _ in RESET_REGS:
                    if other in ("WIRQT", "RIRQT", "IRQEN"):
                        val = await self._val(f"S8_RB_{reg}_{other}_{side}", 0, side, other)
                        want = value if other == reg else 0
                        assert val & omask == want, f"{reg}={value}: {other} read 0x{val:x}"
                await self._wr(f"S8_{reg}_ZERO_{side}", 0, side, reg, 0)
            seen[side] = await self._empty_read(f"S8_RD_{side}", 0, side)
            await self._val(f"S8_EF_{side}", 0, side, "ERROR_FLAGS")
            await self._wr(f"S8_ACK_{side}", 0, side, "IRQS", EIRQ)
        self._mark_step("S8")
        self._log_chk(
            "CHK-REGISTER-OFFSETS-PAIR0",
            f"pair 0 A and B: WRITE_DATA read OKAY 0x{WRITE_DATA_EMPTY_LOW:08x}, READ_DATA read "
            f"SLVERR 0x{seen['A'] & 0xFFFFFFFF:08x}/0x{seen['B'] & 0xFFFFFFFF:08x}, STATUS[3:0]=1, "
            "ERROR_FLAGS/IRQS/IRQP/CTRL 0, WIRQT/RIRQT/IRQEN each read back only its own value",
        )

        await self._wr("S9_WIRQT", 15, "A", "WIRQT", 1)
        w9 = {}
        for pair, side in ((15, "A"), (15, "B"), (14, "A"), (16, "A")):
            w9[f"{pair}{side}"] = await self._val(f"S9_RB_{pair}{side}", pair, side, "WIRQT") & 0xFF
        assert w9 == {"15A": 1, "15B": 0, "14A": 0, "16A": 0}, f"WIRQT readbacks {w9}"
        await self._wr("S9_RESTORE", 15, "A", "WIRQT", 0)
        self._mark_step("S9")
        self._log_chk(
            "CHK-REGISTER-STATE-PER-APERTURE",
            f"WIRQT after writing pair-15 outbound: pair-15 outbound/inbound, pair-14 outbound, "
            f"pair-16 outbound read {w9}",
        )

        rd_out = _addr(0, "A", "READ_DATA")
        rd_in = _addr(0, "B", "READ_DATA")
        assert (rd_out, rd_in) == (0xC001_8008, 0xC001_8808), f"READ_DATA 0x{rd_out:x}/0x{rd_in:x}"
        x, y = 0x0123_4567_89AB_CDEF, 0xFEDC_BA98_7654_3210
        await self._wr("S10_PUSH_X", 0, "A", "WRITE_DATA", x)
        await self._pop("S10_POP_X", 0, "B", x)
        await self._wr("S10_PUSH_Y", 0, "B", "WRITE_DATA", y)
        await self._pop("S10_POP_Y", 0, "A", y)
        self._mark_step("S10")
        self._log_chk(
            "CHK-ADDRESS-EXAMPLES-PAIR0",
            f"outbound READ_DATA 0x{rd_out:08x}, inbound READ_DATA 0x{rd_in:08x}; outbound push "
            f"popped 0x{x:016x} at the inbound address, inbound push popped 0x{y:016x} at the "
            "outbound address",
        )

        attrs = await self.csr_read("SMC_ATTRIBUTES", SMC_ATTRIBUTES, length=8)
        assert isinstance(attrs, int), f"SMC_ATTRIBUTES unresolved {attrs}"
        self._mark_step("S11")
        self._log_chk(
            "CHK-ATTRIBUTES-OBSERVED",
            f"SMC_ATTRIBUTES=0x{attrs:016x} mailbox_depth[39:36]={attrs >> 36 & 0xF} "
            f"num_mailboxes[45:40]={attrs >> 40 & 0x3F} (raw, no compare, SF-017)",
        )

        w0, w1, w2 = 0x3100_0000_0000_0000, 0x3100_0000_0000_0001, 0x3100_0000_0000_0002
        await self._wr("S12_W0", 31, "A", "WRITE_DATA", w0)
        await self._wr("S12_W1", 31, "A", "WRITE_DATA", w1)
        await self._wr("S12_EN", 31, "A", "IRQEN", EIRQ)
        third = await self._wr("S12_W2", 31, "A", "WRITE_DATA", w2, ERROR)
        rise, vec_on = await self._poll_vectors("S12_rise", 0, 1 << 31)
        await self._pop("S12_P0", 31, "B", w0)
        await self._pop("S12_P1", 31, "B", w1)
        await self._val("S12_EF", 31, "A", "ERROR_FLAGS")
        await self._wr("S12_ACK", 31, "A", "IRQS", 7)
        await self._wr("S12_EN0", 31, "A", "IRQEN", 0)
        fall, vec_off = await self._poll_vectors("S12_fall", 0, 0)
        await self._wr("S12_IN_EN", 31, "B", "IRQEN", EIRQ)
        await self._empty_read("S12_IN_EMPTY", 31, "B")
        rise_in, vec_in_on = await self._poll_vectors("S12_in_rise", 1 << 31, 0)
        await self._wr("S12_IN_ACK", 31, "B", "IRQS", 7)
        await self._wr("S12_IN_EN0", 31, "B", "IRQEN", 0)
        fall_in, vec_in_off = await self._poll_vectors("S12_in_fall", 0, 0)
        await self._val("S12_IN_EF", 31, "B", "ERROR_FLAGS")
        self._mark_step("S12")
        self._log_chk(
            "CHK-ATTRIBUTES-MATCH-OBSERVED-UNIT",
            f"pair 31: two writes OKAY popped 0x{w0:016x} then 0x{w1:016x} at the inbound "
            f"aperture; third write answered SLVERR (resp {third.resp_code})",
        )
        self._log_chk(
            "CHK-IRQ-VECTORS-LOW-AT-RESET",
            f"set: no IRQS source latched; observed: tb_mailbox_interrupts=0x{first[0]:08x} "
            f"tb_ext_mailbox_interrupts=0x{first[1]:08x} tb_cpu_interrupts[319:288]="
            f"0x{first[2]:08x}; cleared: not applicable; checked_cleared: second sample "
            f"0x{second[0]:08x}/0x{second[1]:08x}/0x{second[2]:08x}; positive control: pair-31 "
            f"outbound IRQS[2] with IRQEN[2] set raised tb_ext_mailbox_interrupts=0x"
            f"{vec_on[1]:08x} (in=0x{vec_on[0]:08x} cpu=0x{vec_on[2]:08x}) after {rise} cycles "
            f"and read 0x{vec_off[0]:08x}/0x{vec_off[1]:08x}/0x{vec_off[2]:08x} after the "
            f"acknowledge and IRQEN clear ({fall} cycles); positive control: outbound bit 31 "
            f"rose after {rise} rises (vectors {vec_on}) and fell after {fall} rises; inbound "
            f"bit 31 rose after {rise_in} rises (vectors {vec_in_on}, cpu[319]=1) and fell "
            f"after {fall_in} rises (vectors {vec_in_off})",
        )

        word = 0x5000_0000_0000_0005
        await self._idle_gap()
        await self._timed_write(5, word)
        await self._pop("S13_POP", 5, "B", word)
        self._mark_step("S13")
        self._log_chk(
            "CHK-CG-FIRST-ACCESS-AFTER-IDLE",
            f"idle gap {IDLE_GAP_CYCLES} clk_smc_i cycles (stimulus); write answered OKAY and "
            f"the pop returned 0x{word:016x}; completion latency={self._latency[0]} clk_smc_i "
            "cycles (measured, SF-023)",
        )

        word = 0x6000_0000_0000_0006
        await self._wr("S14_PUSH", 6, "A", "WRITE_DATA", word)
        await self._wr("S14_WIRQT", 6, "A", "WIRQT", 1)
        await self._wr("S14_IRQEN", 6, "A", "IRQEN", 5)
        await self._idle_gap()
        wirqt = await self._val("S14_WIRQT_RB", 6, "A", "WIRQT") & 0xFF
        irqen = await self._val("S14_IRQEN_RB", 6, "A", "IRQEN") & 0x7
        assert (wirqt, irqen) == (1, 5), f"after idle WIRQT 0x{wirqt:x} IRQEN 0x{irqen:x}"
        await self._pop("S14_POP", 6, "B", word)
        await self._wr("S14_WIRQT_ZERO", 6, "A", "WIRQT", 0)
        await self._wr("S14_IRQEN_ZERO", 6, "A", "IRQEN", 0)
        await self._wr("S14_ACK", 6, "A", "IRQS", 7)
        self._mark_step("S14")
        self._log_chk(
            "CHK-CG-RETENTION-ACROSS-IDLE",
            f"after {IDLE_GAP_CYCLES} idle cycles WIRQT[7:0]={wirqt} IRQEN[2:0]=0x{irqen:x} "
            f"and the queued word popped unchanged 0x{word:016x}",
        )

        a, b = 0x8000_0000_0000_000A, 0x8000_0000_0000_000B
        writes = [
            self._item(f"S15_W{n}", SmcSysAxiOp.WRITE, 8, "A", "WRITE_DATA", v)
            for n, v in enumerate((a, b))
        ]
        reads = [
            self._item(f"S15_R{n}", SmcSysAxiOp.READ, 8, "B", "READ_DATA", expected=v)
            for n, v in enumerate((a, b))
        ]
        await self._group("S15_writes", writes)
        await self._group("S15_reads", reads)
        self._mark_step("S15")
        self._log_chk(
            "CHK-CG-BACK-TO-BACK-IN-ORDER",
            f"two grouped writes resp {[m.resp_code for m in writes]} then two grouped reads "
            f"resp {[m.resp_code for m in reads]} returned "
            f"0x{reads[0].rdata:016x} then 0x{reads[1].rdata:016x}",
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
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            _STEP_NAMES,
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
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry; %s; "
            "own waits: probe polls %s; %d-cycle idle gaps on clk_smc_i (fixed stimulus) x2, "
            "one-cycle vector resample x1, and a cycle counter cancelled at the response of the "
            "first write after the gap (last[%d cycles]); SEP_IN CSR accesses "
            "(CLOCK_GATE_CONTROL, SMC_ATTRIBUTES, mailbox WRITE_DATA, READ_DATA, STATUS, "
            "ERROR_FLAGS, WIRQT, RIRQT, IRQS, IRQEN, IRQP, CTRL, grouped accesses) x%d "
            "bound=%d ns allow_timeout False last[%d accesses completed]",
            fuse,
            "; ".join(
                f"{t} (AssertionError on expiry) bound={c} cycles last[cycles={n} vec={v}]"
                for t, (c, n, v) in self._waits.items()
            ),
            IDLE_GAP_CYCLES,
            self._latency[0],
            self.accesses,
            AXI_TIMEOUT_NS,
            self.accesses,
        )
