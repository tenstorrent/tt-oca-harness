# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I3C window response across the peripheral clock gate (register access only).

Contract SMC_I3C_SPI_011, anchor smc_i3c_clock_gate_window_test.
Scenarios I3CSPI-GATE-RESPONSE.S1-S5, I3CSPI-GATE-RESTORE.S1-S4, I3CSPI-GATE-INFLIGHT.S1-S4.
Sources: smc_base_config.rdl CLOCK_GATE_CONTROL.i3c_cg_en, clk_rst.adoc access gates, memmap.adoc.

While CLOCK_GATE_CONTROL.i3c_cg_en is set every access to an I3C window answers SLVERR with
read data 0xBADCAB1E; the GPIO interface and UART windows keep answering OKAY, and each I3C
window answers OKAY with its HCI_VERSION reset again after the enable is cleared. The
retention of a DAT word written while gated (SF-026) and the response of accesses queued
around the gate write (SF-025) are measured and printed, not asserted.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import CLOCK_GATE_CONTROL, I2C_CG_EN, I3C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i3c_to_fabric_test_seq import HCI_VERSION_OFFSET, I3C_HCI_VERSION_RESET

AXI_RESP_OKAY = 0
AXI_RESP_SLVERR = 2
GATED_RDATA = SmcCsrSeq.ERR_SLAVE_SIGNATURE
ALL_ONES = 0xFFFF_FFFF
WINDOW_OFFSETS = (0x000, 0xFFC, 0x400, 0x800, 0x0B4)
FIRST_ACCESS_BOUND_NS = 5_000
GROUP_BOUND_NS = 10_000
CYCLES_AFTER_FIRST = 8
DAT_SLOT = 15

_I3C_RDL = (
    Path(__file__).resolve().parents[6]
    / "vendor"
    / "chipsalliance"
    / "i3c-core"
    / "upstream"
    / "src"
    / "rdl"
    / "DAT_structure.rdl"
)
_FIELD_RE = re.compile(r"\}\s*(\w+)\s*\[(\d+):(\d+)\]\s*;")
_REGWIDTH_RE = re.compile(r"regwidth\s*=\s*(\d+)\s*;")


def _dat_structure() -> tuple[int, int]:
    """Return ``(declared field mask, entry width in bits)`` of a DAT entry."""
    text = _I3C_RDL.read_text(encoding="utf-8")
    width = int(_REGWIDTH_RE.search(text).group(1))
    mask = 0
    for _field, msb, lsb in _FIELD_RE.findall(text):
        mask |= ((1 << (int(msb) - int(lsb) + 1)) - 1) << int(lsb)
    assert mask, f"{_I3C_RDL} declares no field"
    return mask, width


DAT_MASK, DAT_BITS = _dat_structure()
DAT_WORD0_MASK = DAT_MASK & ALL_ONES
NUM_I3C = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_NUM")
GPIO_PROBE = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)
UART_PROBE = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
)

# Fence terms in contract order: (term, step, checker printed after the term).
FENCE = (
    ("GATE_CLEAR_CONTROL", "S1", None),
    ("GATED_SLVERR", "S2", "CHK-I3C-GATED-SLVERR"),
    ("GATED_WRITE_RETAINED", "S3", "CHK-I3C-GATED-WRITE-RETAINED"),
    ("OTHER_WINDOWS", "S4", "CHK-I3C-GATE-OTHER-WINDOWS"),
    ("RESTORE_CYCLES", "S5", "CHK-I3C-GATE-RESTORE-DECODE"),
    ("FIRST_ACCESS", "S6", "CHK-I3C-GATE-FIRST-ACCESS-BOUND"),
    ("POST_WRITE_SLVERR", "S7", "CHK-I3C-GATE-POST-WRITE-SLVERR"),
    ("IDEMPOTENT", "S7", "CHK-I3C-GATE-IDEMPOTENT"),
    ("INFLIGHT_GROUPS", "S8", "CHK-I3C-GATE-INFLIGHT-GROUPS"),
)


def window(instance: int, offset: int = 0) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", instance) + offset


def hci_version(instance: int) -> int:
    return window(instance, HCI_VERSION_OFFSET)


def dat_slot_word0(instance: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_BASE_ADDR", instance) + DAT_SLOT * (
        DAT_BITS // 8
    )


def dat_pattern(instance: int) -> int:
    return (0x5A3C_96F0 ^ (0x0101_0101 * (instance + 1))) & DAT_WORD0_MASK


class smc_i3c_clock_gate_window_test_seq(SmcCsrSeq):
    """Set and clear i3c_cg_en and hold the I3C windows to SLVERR or OKAY accordingly."""

    def __init__(self, name: str = "smc_i3c_clock_gate_window_test_seq") -> None:
        super().__init__(name)
        self.events: list[tuple[str, str, int]] = []
        self.waits: list[tuple[str, int, str]] = []
        self.restore_value: int | None = None
        self.gate_sets = 0
        self.hci_ok_reads = 0

    # ---- access helpers -------------------------------------------------------------
    def _item(self, op, name, addr, data, mode, timeout_ns, length=4) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.timeout_ns = timeout_ns
        if mode == "slverr":
            item.allow_error = True
            item.expect_error = True
            item.expected_resp = AXI_RESP_SLVERR
        elif mode == "any":
            item.allow_error = True
        return item

    async def _access(self, op, name, addr, data=0, mode="okay", timeout_ns=None) -> SmcSysAxiItem:
        item = self._item(op, name, addr, data, mode, timeout_ns)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out, f"{name} @ 0x{addr:08x} timed out"
        assert item.resp_code is not None, f"{name} @ 0x{addr:08x}: no response code"
        if mode == "okay":
            assert item.resp_code == AXI_RESP_OKAY, (
                f"{name} @ 0x{addr:08x}: expected OKAY, got resp={item.resp_code}"
            )
        elif mode == "slverr":
            assert item.resp_code == AXI_RESP_SLVERR, (
                f"{name} @ 0x{addr:08x}: expected SLVERR, got resp={item.resp_code}"
            )
        return item

    async def _read_ok(self, name, addr, expected=None, timeout_ns=None) -> int:
        item = await self._access(SmcSysAxiOp.READ, name, addr, mode="okay", timeout_ns=timeout_ns)
        got = item.rdata & ALL_ONES
        assert expected is None or got == expected, (
            f"{name} @ 0x{addr:08x}: expected 0x{expected:08x}, got 0x{got:08x}"
        )
        return got

    async def _read_gated(self, name, addr, timeout_ns=None) -> None:
        item = await self._access(
            SmcSysAxiOp.READ, name, addr, mode="slverr", timeout_ns=timeout_ns
        )
        got = item.rdata & ALL_ONES
        assert got == GATED_RDATA, (
            f"{name} @ 0x{addr:08x}: SLVERR data 0x{got:08x}, expected 0x{GATED_RDATA:08x}"
        )

    async def _write_ok(self, name, addr, data) -> None:
        await self._access(SmcSysAxiOp.WRITE, name, addr, data, mode="okay")

    async def _write_gated(self, name, addr, data) -> None:
        await self._access(SmcSysAxiOp.WRITE, name, addr, data, mode="slverr")

    async def _set_gate(self, name: str) -> int:
        word = self.restore_value | I3C_CG_EN
        self.gate_sets += 1
        await self._write_ok(f"CG_SET_{name}", CLOCK_GATE_CONTROL, word)
        return word

    async def _clear_gate(self, name: str) -> int:
        word = self.restore_value & ~I3C_CG_EN
        await self._write_ok(f"CG_CLEAR_{name}", CLOCK_GATE_CONTROL, word)
        return word

    async def _all_hci_ok(self, tag: str) -> list[int]:
        self.hci_ok_reads += NUM_I3C
        return [
            await self._read_ok(f"HCI_VERSION_{tag}_I{i}", hci_version(i), I3C_HCI_VERSION_RESET)
            for i in range(NUM_I3C)
        ]

    # ---- fence and evidence ---------------------------------------------------------
    def _mark(self, term: str) -> None:
        self.events.append(("term", term, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args) -> None:
        self.events.append(("chk", chk_id, int(get_sim_time("ps"))))
        cocotb.log.info("%s: " + text, chk_id, *args)

    def _wait_note(self, name: str, bound_ns: int, last: str) -> None:
        self.waits.append((name, bound_ns, last))

    def _assert_fence(self) -> None:
        expected = []
        for term, _step, chk in FENCE:
            expected.append(("term", term))
            if chk is not None:
                expected.append(("chk", chk))
        got = [(kind, label) for kind, label, _t in self.events]
        assert got == expected, f"fence events {got} differ from contract order {expected}"
        stamps = [t for kind, _l, t in self.events if kind == "term"]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), (
            f"fence stamps not strictly increasing: {stamps}"
        )
        for (kind, label, t), (_k2, _l2, t_prev) in zip(self.events[1:], self.events):
            assert t >= t_prev, f"{label} stamped before its predecessor"

    # ---- scenario -------------------------------------------------------------------
    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        original = await self._read_ok("CG_SAVE", CLOCK_GATE_CONTROL)
        self.restore_value = original
        try:
            await self._scenario(original)
        finally:
            if self.restore_value is not None:
                await self._write_ok("CG_RESTORE", CLOCK_GATE_CONTROL, original)
                await self._read_ok("CG_RESTORE_RB", CLOCK_GATE_CONTROL, original)

    async def _scenario(self, original: int) -> None:
        default_bound = self.env.cfg.axi_timeout_ns
        instances = range(NUM_I3C)
        assert not original & I3C_CG_EN, f"i3c_cg_en entered set: CLOCK_GATE_CONTROL 0x{original:x}"
        assert not original & I2C_CG_EN, f"i2c_cg_en entered set: CLOCK_GATE_CONTROL 0x{original:x}"
        patterns = [dat_pattern(i) for i in instances]
        assert len(set(patterns)) == NUM_I3C and all(patterns), f"DAT patterns {patterns}"

        # S1 gate clear positive control
        for i in instances:
            await self._write_ok(f"DAT_SLOT_I{i}", dat_slot_word0(i), patterns[i])
        for i in instances:
            await self._read_ok(f"DAT_SLOT_RB_I{i}", dat_slot_word0(i), patterns[i])
        self._mark("GATE_CLEAR_CONTROL")

        # S2 gated window reads and writes
        gated = await self._set_gate("S2")
        reads = writes = 0
        for i in instances:
            for off in WINDOW_OFFSETS:
                await self._read_gated(f"GATED_RD_I{i}_{off:03X}", window(i, off))
                reads += 1
            for off in WINDOW_OFFSETS:
                await self._write_gated(f"GATED_WR_I{i}_{off:03X}", window(i, off), ALL_ONES)
                writes += 1
        assert (reads, writes) == (6 * len(WINDOW_OFFSETS),) * 2
        self._mark("GATED_SLVERR")
        self._chk(
            "CHK-I3C-GATED-SLVERR",
            "CLOCK_GATE_CONTROL=0x%x i3c_cg_en set: %d reads (%d windows x offsets %s) answered "
            "SLVERR(2) with 0x%08X and %d writes of 0x%08X answered SLVERR(2); entry state "
            "(gate clear) DAT slot writes/readbacks answered OKAY",
            gated,
            reads,
            NUM_I3C,
            ",".join(f"0x{o:03X}" for o in WINDOW_OFFSETS),
            GATED_RDATA,
            writes,
            ALL_ONES,
        )

        # S3 gated DAT write, retention measured
        for i in instances:
            await self._write_gated(f"GATED_DAT_WR_I{i}", dat_slot_word0(i), ALL_ONES)
        await self._clear_gate("S3")
        after = [await self._read_ok(f"DAT_AFTER_I{i}", dat_slot_word0(i)) for i in instances]
        self._mark("GATED_WRITE_RETAINED")
        self._chk(
            "CHK-I3C-GATED-WRITE-RETAINED",
            "%d gated DAT slot %d word 0 writes of 0x%08X answered SLVERR; after the clear every "
            "slot read answered OKAY: %s (SF-026: retention not asserted)",
            NUM_I3C,
            DAT_SLOT,
            ALL_ONES,
            " ".join(
                f"I{i}=0x{after[i]:08x}(D_n=0x{patterns[i]:08x},"
                f"{'equal' if after[i] & DAT_WORD0_MASK == patterns[i] else 'differs'})"
                for i in instances
            ),
        )

        # S4 other windows unaffected
        await self._set_gate("S4")
        gpio = await self._read_ok("GPIO_PROBE_GATED", GPIO_PROBE)
        uart = await self._read_ok("UART_PROBE_GATED", UART_PROBE)
        assert gpio != GATED_RDATA and uart != GATED_RDATA, (
            f"GPIO 0x{gpio:08x} or UART 0x{uart:08x} returned the error word"
        )
        await self._clear_gate("S4")
        i2c_only = (original & ~I3C_CG_EN) | I2C_CG_EN
        await self._write_ok("CG_I2C_ONLY", CLOCK_GATE_CONTROL, i2c_only)
        await self._read_ok("HCI_VERSION_I2C_ONLY", hci_version(0), I3C_HCI_VERSION_RESET)
        await self._write_ok("CG_I2C_RESTORE", CLOCK_GATE_CONTROL, original)
        self._mark("OTHER_WINDOWS")
        self._chk(
            "CHK-I3C-GATE-OTHER-WINDOWS",
            "i3c_cg_en set: GPIO @ 0x%08x OKAY 0x%08x and UART @ 0x%08x OKAY 0x%08x, neither "
            "0x%08X; only i2c_cg_en set (CLOCK_GATE_CONTROL=0x%x): I3C0 HCI_VERSION OKAY 0x%08x",
            GPIO_PROBE,
            gpio,
            UART_PROBE,
            uart,
            GATED_RDATA,
            i2c_only,
            I3C_HCI_VERSION_RESET,
        )

        # S5 restore cycles
        sets_before, hci_before, gated_reads = self.gate_sets, self.hci_ok_reads, 0
        await self._set_gate("S5_PRE")
        await self._clear_gate("S5_FIRST")
        await self._all_hci_ok("S5_FIRST")
        for c in range(CYCLES_AFTER_FIRST):
            await self._set_gate(f"S5_C{c}")
            await self._read_gated(f"S5_C{c}_GATED", hci_version(c % NUM_I3C))
            gated_reads += 1
            await self._clear_gate(f"S5_C{c}")
            await self._all_hci_ok(f"S5_C{c}")
        self._mark("RESTORE_CYCLES")
        self._chk(
            "CHK-I3C-GATE-RESTORE-DECODE",
            "after the first clear and each of %d further cycles all %d instances answered OKAY "
            "HCI_VERSION 0x%08x (%d OKAY reads); %d sets were issued (the first followed by the "
            "clear only) and %d gated window reads answered SLVERR 0x%08X",
            CYCLES_AFTER_FIRST,
            NUM_I3C,
            I3C_HCI_VERSION_RESET,
            self.hci_ok_reads - hci_before,
            self.gate_sets - sets_before,
            gated_reads,
            GATED_RDATA,
        )

        # S6 first access after the clearing write
        await self._set_gate("S6_PRE")
        await self._read_gated("S6_PRE_GATED", hci_version(0))
        await self._clear_gate("S6")
        t0 = get_sim_time("ns")
        await self._read_ok(
            "HCI_VERSION_FIRST", hci_version(0), I3C_HCI_VERSION_RESET, FIRST_ACCESS_BOUND_NS
        )
        first_ns = get_sim_time("ns") - t0
        assert first_ns <= FIRST_ACCESS_BOUND_NS, f"first access took {first_ns} ns"
        self._wait_note("S6_first_read", FIRST_ACCESS_BOUND_NS, f"OKAY 0x{I3C_HCI_VERSION_RESET:x}")
        self._mark("FIRST_ACCESS")
        self._chk(
            "CHK-I3C-GATE-FIRST-ACCESS-BOUND",
            "I3C0 HCI_VERSION read after the clearing write answered OKAY 0x%08x in %.1f ns "
            "(bound %d ns)",
            I3C_HCI_VERSION_RESET,
            first_ns,
            FIRST_ACCESS_BOUND_NS,
        )

        # S7 post-write response and idempotence
        set_word = await self._set_gate("S7")
        t0 = get_sim_time("ns")
        await self._read_gated("S7_POST_SET", window(0), FIRST_ACCESS_BOUND_NS)
        post_ns = get_sim_time("ns") - t0
        assert post_ns <= FIRST_ACCESS_BOUND_NS, f"post-write read took {post_ns} ns"
        self._wait_note("S7_post_set_read", FIRST_ACCESS_BOUND_NS, f"SLVERR 0x{GATED_RDATA:x}")
        self._mark("POST_WRITE_SLVERR")
        self._chk(
            "CHK-I3C-GATE-POST-WRITE-SLVERR",
            "I3C0 window read presented after the set write answered SLVERR 0x%08X in %.1f ns "
            "(bound %d ns)",
            GATED_RDATA,
            post_ns,
            FIRST_ACCESS_BOUND_NS,
        )
        first_rb = await self._read_ok("CG_SET_FIRST_RB", CLOCK_GATE_CONTROL, set_word)
        await self._write_ok("CG_SET_AGAIN", CLOCK_GATE_CONTROL, set_word)
        set_rb = await self._read_ok("CG_SET_AGAIN_RB", CLOCK_GATE_CONTROL, set_word)
        clear_word = original & ~I3C_CG_EN
        clear_rbs = []
        for k in range(2):
            await self._write_ok(f"CG_CLEAR_TWICE_{k}", CLOCK_GATE_CONTROL, clear_word)
            rb = await self._read_ok(f"CG_CLEAR_RB_{k}", CLOCK_GATE_CONTROL, clear_word)
            clear_rbs.append(rb)
        await self._read_ok("HCI_VERSION_AFTER_CLEAR", hci_version(0), I3C_HCI_VERSION_RESET)
        self._mark("IDEMPOTENT")
        self._chk(
            "CHK-I3C-GATE-IDEMPOTENT",
            "i3c_cg_en written 1 twice: window SLVERR after the first, field read 1 after each "
            "(CLOCK_GATE_CONTROL=0x%08x, 0x%08x); written 0 twice: field read 0 after each "
            "(0x%08x, 0x%08x) and the window answered OKAY 0x%08x after the last",
            first_rb,
            set_rb,
            clear_rbs[0],
            clear_rbs[1],
            I3C_HCI_VERSION_RESET,
        )

        # S8 outstanding groups: (b) first, then the clear and read, then (a) last
        def member(op, name, addr, data=0):
            return self._item(op, name, addr, data, "any", GROUP_BOUND_NS)

        rd, wr = SmcSysAxiOp.READ, SmcSysAxiOp.WRITE
        group_b = [
            member(wr, "GB_CG_SET", CLOCK_GATE_CONTROL, set_word),
            member(rd, "GB_HCI_I0_SET", hci_version(0)),
            member(rd, "GB_HCI_I1_SET", hci_version(1)),
            member(wr, "GB_CG_CLEAR", CLOCK_GATE_CONTROL, clear_word),
            member(rd, "GB_HCI_I0_CLR", hci_version(0)),
            member(rd, "GB_HCI_I1_CLR", hci_version(1)),
        ]
        report = []
        group = SmcSysAxiGroupItem("group_b", group_b)
        t0 = get_sim_time("ns")
        await self.start_item(group)
        await self.finish_item(group)
        elapsed = get_sim_time("ns") - t0
        assert elapsed <= GROUP_BOUND_NS, f"group b took {elapsed} ns"
        self.accesses += len(group_b)
        for m in group_b:
            assert not m.timed_out and m.resp_code in (AXI_RESP_OKAY, AXI_RESP_SLVERR), (
                f"group b member {m.get_name()} resp={m.resp_code}"
            )
            data = f"0x{m.rdata & ALL_ONES:08x}" if m.op is rd else "-"
            report.append(f"b:{m.get_name()}=resp{m.resp_code}/{data}")
        self._wait_note("S8_group_b", GROUP_BOUND_NS, f"{elapsed:.1f}ns done")
        await self._write_ok("CG_CLEAR_AFTER_B", CLOCK_GATE_CONTROL, clear_word)
        await self._read_ok("HCI_VERSION_AFTER_B", hci_version(0), I3C_HCI_VERSION_RESET)

        def tolerant_read(name):
            item = member(rd, name, hci_version(0))
            item.allow_timeout = True
            return item

        def outcome(item) -> str:
            if item.timed_out:
                return f"no completion in {GROUP_BOUND_NS} ns (LINKED-ISSUE RTL-101)"
            return f"resp{item.resp_code}/0x{item.rdata & ALL_ONES:08x}"

        read_a = tolerant_read("GA_HCI_I0_TOLERANT")
        write_a = member(wr, "GA_CG_SET", CLOCK_GATE_CONTROL, set_word)
        t0 = get_sim_time("ns")
        group_a = SmcSysAxiGroupItem("group_a", [read_a, write_a])
        await self.start_item(group_a)
        await self.finish_item(group_a)
        a_ns = get_sim_time("ns") - t0
        self.accesses += 2
        assert not write_a.timed_out and write_a.resp_code == AXI_RESP_OKAY, (
            f"group a set write resp={write_a.resp_code} timed_out={write_a.timed_out}"
        )
        self._wait_note("S8_group_a_set_write", GROUP_BOUND_NS, "OKAY")
        self._wait_note("S8_group_a_read_tolerant", GROUP_BOUND_NS, outcome(read_a))
        await self._write_ok("CG_CLEAR_AFTER_A", CLOCK_GATE_CONTROL, clear_word)
        final = tolerant_read("FINAL_HCI_I0_TOLERANT")
        await self.start_item(final)
        await self.finish_item(final)
        self.accesses += 1
        self._wait_note("S8_final_read_tolerant", GROUP_BOUND_NS, outcome(final))
        self._mark("INFLIGHT_GROUPS")
        self._chk(
            "CHK-I3C-GATE-INFLIGHT-GROUPS",
            "group b: all %d members completed inside %d ns with OKAY or SLVERR (SF-025, printed "
            "not asserted): %s; after the clear HCI_VERSION answered OKAY 0x%08x; group a (read "
            "issued with the set write, read first): set write OKAY, in-flight read %s after "
            "%.1f ns (a beat arriving after the bound is discarded by the driver and not "
            "observable here); clearing write OKAY; final tolerant HCI_VERSION read %s",
            len(group_b),
            GROUP_BOUND_NS,
            " ".join(report),
            I3C_HCI_VERSION_RESET,
            outcome(read_a),
            a_ns,
            outcome(final),
        )

        # CHK-TIMEOUT-PATHS and CHK-NONVAC
        self._wait_note("SEP_IN_default", default_bound, "every other access answered")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; expiry raises AssertionError "
            "naming the outstanding member, except the two tolerant S8 group (a) reads whose "
            "expiry is printed LINKED-ISSUE RTL-101",
            len(self.waits),
            " ".join(f"{n}={b}ns last={s}" for n, b, s in self.waits),
        )
        self._assert_fence()
        stamps = [(label, t) for kind, label, t in self.events if kind == "term"]
        chk_ids = [label for kind, label, _t in self.events if kind == "chk"]
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(label for label, _t in stamps),
            ",".join(chk_ids),
            ",".join(f"{label}={t}ps" for label, t in stamps),
        )
