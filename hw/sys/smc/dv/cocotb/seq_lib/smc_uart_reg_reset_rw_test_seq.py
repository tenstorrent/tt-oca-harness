# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART register reset values, field read/write and instance isolation over SEP_IN.

Spec sources: hw/ip/uart/uart_16550/regs/{uart_16550_main,uart_16550_dl}.rdl,
hw/ip/uart/uart_wrap/regs/uart_wrap.rdl, hw/sys/smc/doc/periphs.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import CLOCK_GATE_CONTROL, UART_CG_EN, uart_16550_main_u32
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    DLL_OFFSET,
    DLM_OFFSET,
    IIR_PENDING,
    LCR_DLAB,
    LSR_TEMT,
    LSR_THRE,
    MSR_CTS,
    MSR_DCD,
    MSR_DELTAS,
    MSR_DSR,
    MSR_RI,
    uart_base,
    uart_reg,
)

INSTANCES = (0, 1, 2, 3)
MAIN = "UART_16550_MAIN__"
IER_BITS = tuple(
    uart_16550_main_u32(f"{MAIN}IER__{f}_bm") for f in ("ERBFI", "ETBEI", "ELSI", "EDSSI", "EFEI")
)
IER_DEFINED = 0
for _bit in IER_BITS:
    IER_DEFINED |= _bit
LCR_WLS = uart_16550_main_u32(f"{MAIN}LCR__WLS_bm")
LCR_FLAGS = tuple(
    uart_16550_main_u32(f"{MAIN}LCR__{f}_bm") for f in ("STB", "PEN", "EPS", "STICK_PARITY")
)
LCR_SET_BREAK = uart_16550_main_u32(f"{MAIN}LCR__SET_BREAK_bm")
LCR_DEFINED = LCR_WLS | LCR_DLAB
for _bit in LCR_FLAGS:
    LCR_DEFINED |= _bit
MCR_BITS = tuple(
    uart_16550_main_u32(f"{MAIN}MCR__{f}_bm")
    for f in ("DTR", "RTS", "OUT1", "OUT2", "LOOP", "LINE_LOOPBACK")
)
MCR_DEFINED = 0
for _bit in MCR_BITS:
    MCR_DEFINED |= _bit
ECR_DEFINED = uart_16550_main_u32(f"{MAIN}ECR__RCVR_TRIGGER_MS2B_bm")
ITR_BITS = tuple(
    uart_16550_main_u32(f"{MAIN}ITR__{f}_bm")
    for f in ("TRBFI", "TTBEI", "TLSI", "TDSSI", "TFEI", "TRTI")
)
ITR_DEFINED = 0
for _bit in ITR_BITS:
    ITR_DEFINED |= _bit

IIR_RESET = IIR_PENDING
LSR_RESET = LSR_THRE | LSR_TEMT
DL_PATTERNS = (0x00, 0xFF, 0xA5, 0x5A)
MAIN_REGS = ("RBR", "IER", "IIR", "LCR", "MCR", "LSR", "MSR", "SCR", "ECR", "ITR")
RESET_EXPECT = {"IIR": IIR_RESET, "LSR": LSR_RESET}
ISO_REGS = ("IER", "LCR", "MCR", "SCR", "ECR")
ISO_ALL = ISO_REGS + ("DLL", "DLM")

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
CHECKERS = (
    ("CHK-UART-RESET-VALUES", "S2"),
    ("CHK-UART-RESET-MSR", "S2"),
    ("CHK-UART-RESET-DL", "S3"),
    ("CHK-UART-RESET-INSTANCES", "S3"),
    ("CHK-UART-RW-IER", "S4"),
    ("CHK-UART-RW-LCR", "S5"),
    ("CHK-UART-RW-MCR", "S6"),
    ("CHK-UART-RW-ECR-ITR", "S7"),
    ("CHK-UART-RW-DL", "S8"),
    ("CHK-UART-RW-ISOLATION", "S9"),
)
NONVAC_TERMS = (
    "CLOCK_UNGATED < RESET_VECTORS_READ < DL_RESET_READ < IER_RW < LCR_RW < MCR_RW "
    "< ECR_ITR_RW < DL_RW < ISOLATION"
)


def _pattern(k: int) -> dict[str, int]:
    return {
        "IER": IER_BITS[k] | IER_BITS[4],
        "LCR": (0x03, 0x0B, 0x1B, 0x3B)[k],
        "MCR": MCR_BITS[k],
        "SCR": 0xA0 | (k << 1) | 1,
        "ECR": (k % 3) + 1,
        "DLL": 0x11 * (k + 1),
        "DLM": 0x21 * (k + 1) & 0xFF,
    }


class smc_uart_reg_reset_rw_test_seq(SmcCsrSeq):
    """Reset vectors, field read/write and isolation of the four UART register blocks."""

    def __init__(self, name: str = "smc_uart_reg_reset_rw_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.vectors: dict[int, dict[str, int]] = {}

    def _step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step_id: str, text: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step_id, (
            f"{chk_id} printed before its step {step_id} completed; stamps {self.stamps}"
        )
        self.chk_marks.append((chk_id, len(self.stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    def _addr(self, wrap: int, reg: str) -> int:
        if reg == "DLL":
            return uart_base(wrap) + DLL_OFFSET
        if reg == "DLM":
            return uart_base(wrap) + DLM_OFFSET
        return uart_reg(wrap, reg)

    async def _rd(self, label: str, wrap: int, reg: str) -> int:
        return await self.csr_read(f"{label}_U{wrap}_{reg}", self._addr(wrap, reg))

    async def _wr(self, label: str, wrap: int, reg: str, value: int) -> None:
        await self.csr_write(f"{label}_U{wrap}_{reg}", self._addr(wrap, reg), value)

    async def _readback(self, label: str, wrap: int, reg: str, value: int, mask: int) -> int:
        await self._wr(label, wrap, reg, value)
        got = await self._rd(f"{label}_RB", wrap, reg)
        assert got & mask == value & mask, (
            f"{label}: instance {wrap} {reg} wrote 0x{value:x} read 0x{got:x} under mask 0x{mask:x}"
        )
        return got

    async def _read_dl(self, label: str, wrap: int, lcr: int) -> tuple[int, int]:
        await self._wr(f"{label}_DLAB", wrap, "LCR", lcr | LCR_DLAB)
        dll = await self._rd(label, wrap, "DLL")
        dlm = await self._rd(label, wrap, "DLM")
        await self._wr(f"{label}_DLAB_CLR", wrap, "LCR", lcr)
        return dll, dlm

    async def _s1(self) -> None:
        cg = await self.csr_read("CG_RD", CLOCK_GATE_CONTROL)
        self.cg_original = cg
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        after = await self.csr_read("CG_RB", CLOCK_GATE_CONTROL)
        assert after & UART_CG_EN == 0, f"UART_CG_EN still set after un-gate: 0x{after:x}"
        self._step("S1")

    async def _s2(self) -> None:
        for wrap in INSTANCES:
            vec = {}
            for reg in MAIN_REGS:
                vec[reg] = await self._rd("S2", wrap, reg)
            self.vectors[wrap] = vec
        second = {wrap: await self._rd("S2_MSR2", wrap, "MSR") for wrap in INSTANCES}
        self._step("S2")
        for wrap in INSTANCES:
            vec = self.vectors[wrap]
            for reg in MAIN_REGS:
                if reg == "MSR":
                    continue
                want = RESET_EXPECT.get(reg, 0)
                assert vec[reg] == want, (
                    f"instance {wrap} {reg} reads 0x{vec[reg]:x}, reset value is 0x{want:x}"
                )
        self._chk(
            "CHK-UART-RESET-VALUES",
            "S2",
            "%d instances: RBR IER LCR MCR SCR ECR ITR read 0x00, IIR reads 0x%02x, "
            "LSR reads 0x%02x; the 0x00 reset compares are not reset evidence on the 2-state "
            "bench (zero-initialised flops read 0x00 with or without a reset)",
            len(INSTANCES),
            IIR_RESET,
            LSR_RESET,
        )
        msr_text = []
        for wrap in INSTANCES:
            first = self.vectors[wrap]["MSR"]
            again = second[wrap]
            bad = first & (MSR_DCD | MSR_RI | MSR_DSR)
            assert bad == 0, f"instance {wrap} MSR 0x{first:02x} has DCD/RI/DSR set 0x{bad:x}"
            assert again & MSR_DELTAS == 0, (
                f"instance {wrap} second MSR read 0x{again:02x} still has delta bits"
            )
            assert first & ~MSR_DELTAS == again & ~MSR_DELTAS, (
                f"instance {wrap} MSR level bits changed 0x{first:02x} -> 0x{again:02x}"
            )
            msr_text.append(
                f"u{wrap}=first 0x{first:02x}(CTS={int(bool(first & MSR_CTS))},"
                f"deltas=0x{first & MSR_DELTAS:x}) second 0x{again:02x}"
            )
        self._chk(
            "CHK-UART-RESET-MSR",
            "S2",
            "DCD/RI/DSR read 0 on first read; second read deltas 0 with same level bits; "
            "first-read CTS and deltas measured %s (measured, not compared)",
            " ".join(msr_text),
        )

    async def _s3(self) -> None:
        for wrap in INSTANCES:
            dll, dlm = await self._read_dl("S3", wrap, 0)
            self.vectors[wrap]["DLL"] = dll
            self.vectors[wrap]["DLM"] = dlm
        self._step("S3")
        for wrap in INSTANCES:
            vec = self.vectors[wrap]
            assert vec["DLL"] == 0 and vec["DLM"] == 0, (
                f"instance {wrap} DLL 0x{vec['DLL']:x} DLM 0x{vec['DLM']:x} not reset 0"
            )
        self._chk(
            "CHK-UART-RESET-DL",
            "S3",
            "with DLAB set DLL=0x00 DLM=0x00 on %d instances; the 0x00 reset compares are not "
            "reset evidence on the 2-state bench (zero-initialised flops read 0x00 with or "
            "without a reset)",
            len(INSTANCES),
        )
        ref = self.vectors[0]
        for wrap in INSTANCES[1:]:
            assert self.vectors[wrap] == ref, (
                f"instance {wrap} reset vector {self.vectors[wrap]} differs from instance 0 {ref}"
            )
        text = "; ".join(
            f"u{w}=[" + " ".join(f"{r}=0x{v:02x}" for r, v in self.vectors[w].items()) + "]"
            for w in INSTANCES
        )
        self._chk(
            "CHK-UART-RESET-INSTANCES", "S3", "12-value vectors identical on 4 instances: %s", text
        )

    async def _s4(self) -> None:
        upper = []
        singles = [(f"B{i}", b) for i, b in enumerate(IER_BITS)] + [("ALL", IER_DEFINED)]
        for tag, value in singles:
            got = await self._readback(f"S4_{tag}", 0, "IER", value, IER_DEFINED)
            upper.append(f"{tag}:0x{value:02x}->0x{got:08x}(31:5=0x{got >> 5:x})")
        await self._wr("S4_CLR", 0, "IER", 0)
        self._step("S4")
        self._chk(
            "CHK-UART-RW-IER",
            "S4",
            "IER bits 4:0 read back for 5 single-bit writes and all five set; %s "
            "(not specified, measured)",
            " ".join(upper),
        )

    async def _s5(self) -> None:
        values = list(range(LCR_WLS + 1)) + list(LCR_FLAGS) + [LCR_DLAB]
        values.append(LCR_WLS | LCR_DEFINED)
        seen = []
        for value in values:
            assert value & LCR_SET_BREAK == 0
            got = await self._readback(f"S5_{value:02x}", 0, "LCR", value, LCR_DEFINED)
            assert got & LCR_SET_BREAK == 0, f"LCR wrote 0x{value:x} SET_BREAK set in 0x{got:x}"
            seen.append(f"0x{value:02x}->0x{got:02x}")
        await self._wr("S5_CLR", 0, "LCR", 0)
        self._step("S5")
        self._chk(
            "CHK-UART-RW-LCR",
            "S5",
            "LCR bits 5:0 and 7 read back for %d writes, SET_BREAK clear: %s",
            len(values),
            " ".join(seen),
        )

    async def _s6(self) -> None:
        values = list(MCR_BITS) + [MCR_DEFINED & ~MCR_BITS[4] | MCR_BITS[0] | MCR_BITS[3]]
        seen = []
        for value in values:
            got = await self._readback(f"S6_{value:02x}", 0, "MCR", value, MCR_DEFINED)
            seen.append(f"0x{value:02x}->0x{got:02x}")
        await self._wr("S6_CLR", 0, "MCR", 0)
        self._step("S6")
        self._chk(
            "CHK-UART-RW-MCR",
            "S6",
            "MCR bits 5:0 read back for 6 single-bit writes and a combination: %s",
            " ".join(seen),
        )

    async def _s7(self) -> None:
        seen = []
        for value in range(ECR_DEFINED + 1):
            got = await self._readback(f"S7_ECR{value}", 0, "ECR", value, ECR_DEFINED)
            seen.append(f"ECR 0x{value:x}->0x{got:x}")
        for bit in ITR_BITS:
            got = await self._readback(f"S7_ITR{bit:02x}", 0, "ITR", bit, ITR_DEFINED)
            seen.append(f"ITR 0x{bit:02x}->0x{got:02x}")
        zero = await self._readback("S7_ITR0", 0, "ITR", 0, ITR_DEFINED)
        await self._readback("S7_ECR_CLR", 0, "ECR", 0, ECR_DEFINED)
        self._step("S7")
        self._chk(
            "CHK-UART-RW-ECR-ITR",
            "S7",
            "ECR bits 1:0 and ITR bits 5:0 read back as written, ITR reads 0x%02x after 0: %s",
            zero & ITR_DEFINED,
            " ".join(seen),
        )

    async def _s8(self) -> None:
        wrap = 0
        await self._wr("S8_DLAB", wrap, "LCR", LCR_DLAB)
        seen = []
        for value in DL_PATTERNS:
            await self._wr("S8_DLL", wrap, "DLL", value)
            dlm_after = await self._rd("S8_DLM_XT", wrap, "DLM")
            assert dlm_after == 0, f"DLL write 0x{value:x} moved DLM to 0x{dlm_after:x}"
            dll = await self._rd("S8_DLL_RB", wrap, "DLL")
            assert dll == value, f"DLL wrote 0x{value:x} read 0x{dll:x}"
            await self._wr("S8_DLL_CLR", wrap, "DLL", 0)
            await self._wr("S8_DLM", wrap, "DLM", value)
            dll_after = await self._rd("S8_DLL_XT", wrap, "DLL")
            assert dll_after == 0, f"DLM write 0x{value:x} moved DLL to 0x{dll_after:x}"
            dlm = await self._rd("S8_DLM_RB", wrap, "DLM")
            assert dlm == value, f"DLM wrote 0x{value:x} read 0x{dlm:x}"
            await self._wr("S8_DLM_CLR", wrap, "DLM", 0)
            seen.append(f"0x{value:02x}->DLL 0x{dll:02x} DLM 0x{dlm:02x}")
        await self._wr("S8_DLAB_CLR", wrap, "LCR", 0)
        self._step("S8")
        self._chk(
            "CHK-UART-RW-DL",
            "S8",
            "with DLAB set DLL and DLM read back each pattern independently: %s",
            " ".join(seen),
        )

    async def _read_iso(self, label: str, wrap: int) -> dict[str, int]:
        vec = {}
        for reg in ISO_REGS:
            vec[reg] = await self._rd(label, wrap, reg)
        vec["DLL"], vec["DLM"] = await self._read_dl(label, wrap, vec["LCR"])
        return vec

    async def _write_pattern(self, wrap: int, pat: dict[str, int]) -> None:
        await self._wr("S9_DLAB", wrap, "LCR", LCR_DLAB)
        await self._wr("S9_PAT", wrap, "DLL", pat["DLL"])
        await self._wr("S9_PAT", wrap, "DLM", pat["DLM"])
        for reg in ("LCR", "IER", "MCR", "SCR", "ECR"):
            await self._wr("S9_PAT", wrap, reg, pat[reg])

    async def _restore(self, wrap: int) -> None:
        await self._wr("S9_RDLAB", wrap, "LCR", LCR_DLAB)
        await self._wr("S9_RST", wrap, "DLL", 0)
        await self._wr("S9_RST", wrap, "DLM", 0)
        for reg in ("LCR", "IER", "MCR", "SCR", "ECR"):
            await self._wr("S9_RST", wrap, reg, 0)

    async def _s9(self) -> None:
        zero = {reg: 0 for reg in ISO_ALL}
        seen = []
        for k in INSTANCES:
            others = [w for w in INSTANCES if w != k]
            before = {w: await self._read_iso(f"S9_K{k}_PRE", w) for w in others}
            for w in others:
                assert before[w] == zero, f"instance {w} before pattern k={k}: {before[w]}"
            pat = _pattern(k)
            await self._write_pattern(k, pat)
            observed = await self._read_iso(f"S9_K{k}_OBS", k)
            assert observed == pat, f"instance {k} pattern {pat} read back {observed}"
            for w in others:
                after = await self._read_iso(f"S9_K{k}_POST", w)
                assert after == before[w], (
                    f"pattern on instance {k} changed instance {w}: {before[w]} -> {after}"
                )
            await self._restore(k)
            for w in INSTANCES:
                cleared = await self._read_iso(f"S9_K{k}_CLR", w)
                assert cleared == zero, f"instance {w} after restore of {k}: {cleared}"
            seen.append(f"k={k}:" + ",".join(f"{r}=0x{v:02x}" for r, v in pat.items()))
        self._step("S9")
        self._chk(
            "CHK-UART-RW-ISOLATION",
            "S9",
            "other three instances unchanged after each pattern write; patterns %s; "
            "all four read reset values after restore",
            " ".join(seen),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        await self._s8()
        await self._s9()
        await self.csr_write("UART_REGATE", CLOCK_GATE_CONTROL, self.cg_original)

        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            NONVAC_TERMS,
            " ".join(c for c, _ in CHECKERS),
            " ".join(f"{s}={t}" for s, t in self.stamps),
        )
