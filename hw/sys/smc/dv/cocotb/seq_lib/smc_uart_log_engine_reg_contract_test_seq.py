# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine bank, wrapper CTRL and UART reset words on four wrapper instances.

Contract SMC_UART_LOG_ENGINE_009, anchor smc_uart_log_engine_reg_contract_test.
Allocated scenarios: LOGENG-REGMAP-RESET.S1-S3, LOGENG-REGMAP-RW.S1-S4/S6/S7,
LOGENG-REGMAP-ACCESS.S2-S5, LOGENG-UART-EN-CTRL.S1, LOGENG-INSTANCE-MAP.S1.
Spec sources: hw/ip/uart/log_engine/regs/log_engine.rdl, hw/ip/uart/uart_log_engine_wrap/regs,
hw/ip/uart/uart_wrap/regs/uart_wrap.rdl, hw/sys/smc/doc/periphs.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _LOG_ENGINE_H, _field_mask, log_engine_u32, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    IIR_PENDING,
    LSR_TEMT,
    LSR_THRE,
    NUM_LOG_ENTRIES,
    UART_EN,
    WRAP,
    WRAP_NUM,
    WRAP_STRIDE_SYMBOL,
    engine_reg,
    uart_reg,
    wrap_ctrl_reg,
)

_LOG_ENGINE_ADDR_H = _LOG_ENGINE_H.with_name("log_engine_addr.h")
_WORD_MASK = 0xFFFF_FFFF
_ENGINE_BASE_SYMBOL = f"{WRAP}LOG_ENGINE_BASE_ADDR"

CTRL_EN = log_engine_u32("LOG_ENGINE__CTRL__EN_bm")
SIZE_MASK = log_engine_u32("LOG_ENGINE__LOG_REGION_SIZE__LOG_REGION_SIZE_bm")
SIZE_BITS = log_engine_u32("LOG_ENGINE__LOG_REGION_SIZE__LOG_REGION_SIZE_bw")
ADDR_LO_MASK = log_engine_u32("LOG_ENGINE__LOG_REGION_ADDR__LOG_REGION_ADDR_LO_bm")
ADDR_LO_BITS = log_engine_u32("LOG_ENGINE__LOG_REGION_ADDR__LOG_REGION_ADDR_LO_bw")
ADDR_HI_BITS = log_engine_u32("LOG_ENGINE__LOG_REGION_ADDR__LOG_REGION_ADDR_HI_bw")
ADDR_HI_MASK = (1 << ADDR_HI_BITS) - 1
WRITE_ADDR_BITS = 32
FETCH_ERR = log_engine_u32("LOG_ENGINE__INTR_ENABLE__LOG_FETCH_ERR_bm")
WRITE_ERR = log_engine_u32("LOG_ENGINE__INTR_ENABLE__LOG_WRITE_ERR_bm")
INTR_BOTH = FETCH_ERR | WRITE_ERR
LSR_RESET = LSR_THRE | LSR_TEMT
IIR_RESET = IIR_PENDING
SCR_MASK = _WORD_MASK & 0xFF

# Distinct per-instance words for the isolation step; the INTR_ENABLE words use the
# four distinct values the two implemented bits can hold.
INTR_ENABLE_SIGNATURES = (FETCH_ERR, WRITE_ERR, INTR_BOTH, 0)

STEPS = tuple(f"S{n}" for n in range(1, 13))
CHECKERS = (
    ("CHK-LOGENG-RESET-ZERO", "S2"),
    ("CHK-LOGENG-RESET-UART", "S3"),
    ("CHK-LOGENG-RW-EN-SIZE", "S5"),
    ("CHK-LOGENG-RW-ADDR", "S7"),
    ("CHK-LOGENG-RW-INTR-ENABLE", "S8"),
    ("CHK-LOGENG-RW-ISOLATION", "S9"),
    ("CHK-LOGENG-ACCESS-INTR-TEST-READ", "S10"),
    ("CHK-LOGENG-ACCESS-PULSE-W1C", "S10"),
    ("CHK-LOGENG-ACCESS-UNIMPL", "S11"),
    ("CHK-LOGENG-UART-EN-RW", "S12"),
    ("CHK-LOGENG-BANK-PLACEMENT", "S12"),
)
FENCE_TERMS = " < ".join(chk for chk, _ in CHECKERS)


class smc_uart_log_engine_reg_contract_test_seq(SmcCsrSeq):
    """Register contract of the log-engine bank and wrapper on instances 0..3."""

    def __init__(self, name: str = "smc_uart_log_engine_reg_contract_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.wraps = tuple(range(smc_addr(WRAP_NUM)))
        self.intr_test_reads: list[str] = []
        self.reset_reads = 0
        self.slot_reads = 0

    def _step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step_id: str, text: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step_id, (
            f"{chk_id} printed before its step {step_id} completed; stamps {self.stamps}"
        )
        self.chk_marks.append((chk_id, len(self.stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    async def _expect(self, name: str, addr: int, expected: int) -> int:
        got = await self.csr_read(name, addr, expected=expected)
        assert got == expected, f"{name} @ 0x{addr:08x}: read 0x{got:08x}, expected 0x{expected:x}"
        return got

    async def _write_expect(self, name: str, addr: int, data: int, expected: int) -> None:
        await self.csr_write(name, addr, data)
        await self._expect(f"{name}_RB", addr, expected)

    async def _read_measured(self, name: str, addr: int) -> tuple[int, int]:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name} @ 0x{addr:08x}: read returned no response"
        return item.resp_code, item.rdata

    async def _measure_intr_test(self, label: str, wrap: int) -> None:
        resp, data = await self._read_measured(f"{label}_W{wrap}", engine_reg(wrap, "INTR_TEST"))
        self.intr_test_reads.append(f"{label}[w{wrap}]=resp{resp}/0x{data:08x}")

    async def _s1(self) -> None:
        for wrap in self.wraps:
            regs = (
                ("CTRL", engine_reg(wrap, "CTRL")),
                ("SIZE", engine_reg(wrap, "LOG_REGION_SIZE")),
                ("ADDR_LO", self._addr_lo(wrap)),
                ("ADDR_HI", self._addr_hi(wrap)),
                ("WRITE_ADDR", engine_reg(wrap, "LOG_WRITE_ADDR")),
                ("INTR_STATUS", engine_reg(wrap, "INTR_STATUS")),
                ("INTR_ENABLE", engine_reg(wrap, "INTR_ENABLE")),
                ("WRAP_CTRL", wrap_ctrl_reg(wrap)),
            )
            for label, addr in regs:
                await self._expect(f"S1_W{wrap}_{label}", addr, 0)
                self.reset_reads += 1
        for wrap in self.wraps:
            await self._measure_intr_test("reset", wrap)
        self._step("S1")

    def _addr_lo(self, wrap: int) -> int:
        return engine_reg(wrap, "LOG_REGION_ADDR")

    def _addr_hi(self, wrap: int) -> int:
        return self._addr_lo(wrap) + ADDR_LO_BITS // 8

    def _log_ctrl(self, wrap: int, element: int) -> int:
        return smc_indexed_addr(_ENGINE_BASE_SYMBOL, wrap) + smc_indexed_addr(
            "LOG_ENGINE_LOG_CTRL_BASE_ADDR", element, _LOG_ENGINE_ADDR_H
        )

    async def _s2(self) -> None:
        for wrap in self.wraps:
            for element in range(NUM_LOG_ENTRIES):
                addr = self._log_ctrl(wrap, element)
                await self._expect(f"S2_W{wrap}_LOG_CTRL{element}", addr, 0)
                self.slot_reads += 1
        self._step("S2")
        self._chk(
            "CHK-LOGENG-RESET-ZERO",
            "S2",
            "%d register reads (8 registers on %d instances) and %d LOG_CTRL slot reads "
            "(%d slots on %d instances) read 0x0 with OKAY responses before any write; "
            "INTR_TEST read before any write: %s (SF-016)",
            self.reset_reads,
            len(self.wraps),
            self.slot_reads,
            NUM_LOG_ENTRIES,
            len(self.wraps),
            ", ".join(self.intr_test_reads),
        )

    async def _s3(self) -> None:
        words = []
        for wrap in self.wraps:
            lsr = await self._expect(f"S3_W{wrap}_LSR", uart_reg(wrap, "LSR"), LSR_RESET)
            iir = await self._expect(f"S3_W{wrap}_IIR", uart_reg(wrap, "IIR"), IIR_RESET)
            words.append(f"w{wrap}:LSR=0x{lsr:02x},IIR=0x{iir:02x}")
        self._step("S3")
        self._chk(
            "CHK-LOGENG-RESET-UART",
            "S3",
            "every instance reads LSR 0x%02x and IIR 0x%02x: %s",
            LSR_RESET,
            IIR_RESET,
            " ".join(words),
        )

    async def _s4(self) -> None:
        for wrap in self.wraps:
            ctrl = engine_reg(wrap, "CTRL")
            await self._write_expect(f"S4_W{wrap}_EN", ctrl, CTRL_EN, CTRL_EN)
            await self._write_expect(f"S4_W{wrap}_ABOVE_EN", ctrl, _WORD_MASK & ~CTRL_EN, 0)
            await self._write_expect(f"S4_W{wrap}_CLEAR", ctrl, 0, 0)
        self._step("S4")

    async def _s5(self) -> None:
        size = engine_reg(0, "LOG_REGION_SIZE")
        patterns = [1 << bit for bit in range(SIZE_BITS)] + [_WORD_MASK]
        for pattern in patterns:
            await self._write_expect(f"S5_SIZE_{pattern:x}", size, pattern, pattern & SIZE_MASK)
        await self._write_expect("S5_SIZE_RESTORE", size, 0, 0)
        self._step("S5")
        self._chk(
            "CHK-LOGENG-RW-EN-SIZE",
            "S5",
            "CTRL read 0x%x, 0x0 and 0x0 after writes of 0x%x, 0x%08x and 0x0 on %d instances; "
            "LOG_REGION_SIZE returned each of %d single bits and 0x%08x masked to 0x%x "
            "(bits above [%d:0] read 0)",
            CTRL_EN,
            CTRL_EN,
            _WORD_MASK & ~CTRL_EN,
            len(self.wraps),
            SIZE_BITS,
            _WORD_MASK,
            SIZE_MASK,
            SIZE_BITS - 1,
        )

    async def _s6(self) -> None:
        lo, hi = self._addr_lo(0), self._addr_hi(0)
        for bit in range(ADDR_LO_BITS):
            await self._write_expect(f"S6_LO_{bit}", lo, 1 << bit, 1 << bit)
        await self._write_expect("S6_LO_RESTORE", lo, 0, 0)
        hi_patterns = [1 << bit for bit in range(ADDR_HI_BITS)] + [_WORD_MASK]
        for pattern in hi_patterns:
            await self._write_expect(f"S6_HI_{pattern:x}", hi, pattern, pattern & ADDR_HI_MASK)
        await self._write_expect("S6_HI_RESTORE", hi, 0, 0)
        self._step("S6")

    async def _s7(self) -> None:
        write_addr = engine_reg(0, "LOG_WRITE_ADDR")
        for bit in range(WRITE_ADDR_BITS):
            await self._write_expect(f"S7_WA_{bit}", write_addr, 1 << bit, 1 << bit)
        await self._write_expect("S7_WA_RESTORE", write_addr, 0, 0)
        self._step("S7")
        self._chk(
            "CHK-LOGENG-RW-ADDR",
            "S7",
            "LOG_REGION_ADDR low returned each of %d single bits, its high half each of %d "
            "single bits and 0x%08x masked to 0x%06x (bits above [%d:0] read 0), "
            "LOG_WRITE_ADDR returned each of %d single bits",
            ADDR_LO_BITS,
            ADDR_HI_BITS,
            _WORD_MASK,
            ADDR_HI_MASK,
            ADDR_HI_BITS - 1,
            WRITE_ADDR_BITS,
        )

    async def _s8(self) -> None:
        intr_enable = engine_reg(0, "INTR_ENABLE")
        for value in (FETCH_ERR, WRITE_ERR, INTR_BOTH, 0):
            await self._write_expect(f"S8_IE_{value:x}", intr_enable, value, value)
        self._step("S8")
        self._chk(
            "CHK-LOGENG-RW-INTR-ENABLE",
            "S8",
            "INTR_ENABLE read exactly 0x%02x, 0x%02x, 0x%02x and 0x00 after writes of those values",
            FETCH_ERR,
            WRITE_ERR,
            INTR_BOTH,
        )

    def _signatures(self, wrap: int) -> tuple[tuple[str, int, int], ...]:
        return (
            ("SIZE", engine_reg(wrap, "LOG_REGION_SIZE"), (0x11111 * (wrap + 1)) & SIZE_MASK),
            ("ADDR_LO", self._addr_lo(wrap), 0xA5A5_0000 | (wrap + 1) << 4 | wrap),
            ("WRITE_ADDR", engine_reg(wrap, "LOG_WRITE_ADDR"), 0x5A5A_0000 | (wrap + 1) << 8),
            ("INTR_ENABLE", engine_reg(wrap, "INTR_ENABLE"), INTR_ENABLE_SIGNATURES[wrap]),
        )

    async def _s9(self) -> None:
        for wrap in self.wraps:
            for label, addr, value in self._signatures(wrap):
                await self.csr_write(f"S9_W{wrap}_{label}", addr, value)
        checks = 0
        for wrap in self.wraps:
            for label, addr, value in self._signatures(wrap):
                await self._expect(f"S9_W{wrap}_{label}_RB", addr, value)
                checks += 1
        for wrap in self.wraps:
            for label, addr, _value in self._signatures(wrap):
                await self._write_expect(f"S9_W{wrap}_{label}_RESTORE", addr, 0, 0)
        self._step("S9")
        self._chk(
            "CHK-LOGENG-RW-ISOLATION",
            "S9",
            "%d registers (4 per instance on %d instances) read their own signature after all "
            "instances were programmed, so each of %d ordered instance pairs is free of aliasing",
            checks,
            len(self.wraps),
            len(self.wraps) * (len(self.wraps) - 1),
        )

    async def _force_status(self, label: str, wrap: int) -> None:
        await self.csr_write(f"{label}_FORCE", engine_reg(wrap, "INTR_TEST"), INTR_BOTH)
        await self._expect(f"{label}_FORCED", engine_reg(wrap, "INTR_STATUS"), INTR_BOTH)

    async def _s10(self) -> None:
        test, status = engine_reg(0, "INTR_TEST"), engine_reg(0, "INTR_STATUS")
        raised = []
        for value in (FETCH_ERR, WRITE_ERR, INTR_BOTH):
            await self.csr_write(f"S10_TEST_{value:x}", test, value)
            if value == INTR_BOTH:
                await self._measure_intr_test("after_0x11", 0)
            await self._expect(f"S10_STATUS_{value:x}", status, value)
            raised.append(f"0x{value:02x}")
            await self._write_expect(f"S10_CLEAR_{value:x}", status, INTR_BOTH, 0)
        cleared = []
        for value in (0, FETCH_ERR, WRITE_ERR, INTR_BOTH):
            await self._force_status(f"S10_W1C_{value:x}", 0)
            left = INTR_BOTH & ~value
            await self._write_expect(f"S10_W1C_{value:x}", status, value, left)
            cleared.append(f"0x{value:02x}->0x{left:02x}")
            await self._write_expect(f"S10_W1C_{value:x}_DRAIN", status, INTR_BOTH, 0)
        self._step("S10")
        self._chk(
            "CHK-LOGENG-ACCESS-INTR-TEST-READ",
            "S10",
            "INTR_TEST reads completed with resolvable data, measured as resp/data "
            "(0 OKAY, 2 SLVERR, 3 DECERR): %s (owner answer SF-016 open)",
            ", ".join(self.intr_test_reads),
        )
        self._chk(
            "CHK-LOGENG-ACCESS-PULSE-W1C",
            "S10",
            "with INTR_ENABLE 0 INTR_TEST writes %s left INTR_STATUS equal to each written "
            "value; from status 0x%02x a W1C write left %s",
            ",".join(raised),
            INTR_BOTH,
            ",".join(cleared),
        )

    async def _s11(self) -> None:
        status, intr_enable = engine_reg(0, "INTR_STATUS"), engine_reg(0, "INTR_ENABLE")
        await self._write_expect("S11_STATUS_CLEAR", status, _WORD_MASK, 0)
        await self._force_status("S11_STATUS", 0)
        await self._write_expect("S11_STATUS_FORCED", status, _WORD_MASK, 0)
        await self._write_expect("S11_ENABLE", intr_enable, _WORD_MASK, INTR_BOTH)
        await self._write_expect("S11_ENABLE_RESTORE", intr_enable, 0, 0)
        self._step("S11")
        self._chk(
            "CHK-LOGENG-ACCESS-UNIMPL",
            "S11",
            "after a write of 0x%08x INTR_ENABLE read 0x%08x and INTR_STATUS read 0x0 both from "
            "clear and with 0x%02x forced (partial strobes: SF-022 open)",
            _WORD_MASK,
            INTR_BOTH,
            INTR_BOTH,
        )

    async def _s12(self) -> None:
        stride = smc_addr(WRAP_STRIDE_SYMBOL)
        window = wrap_ctrl_reg(0)
        scr_offset = uart_reg(0, "SCR") - window
        size_offset = (
            smc_indexed_addr(_ENGINE_BASE_SYMBOL, 0)
            - window
            + _field_mask(_LOG_ENGINE_ADDR_H, "LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR")
        )
        for wrap in self.wraps:
            ctrl = wrap_ctrl_reg(wrap)
            await self._write_expect(f"S12_W{wrap}_EN", ctrl, UART_EN, UART_EN)
            await self._write_expect(f"S12_W{wrap}_DIS", ctrl, 0, 0)
        placed = []
        for wrap in self.wraps:
            base = window + wrap * stride
            words = (
                ("CTRL", base, wrap_ctrl_reg(wrap), UART_EN),
                ("SCR", base + scr_offset, uart_reg(wrap, "SCR"), (0x30 + wrap) & SCR_MASK),
                (
                    "SIZE",
                    base + size_offset,
                    engine_reg(wrap, "LOG_REGION_SIZE"),
                    (0x700 + wrap) & SIZE_MASK,
                ),
            )
            for label, arithmetic, generated, value in words:
                assert arithmetic == generated, (
                    f"instance {wrap} {label}: window arithmetic gives 0x{arithmetic:08x}, the "
                    f"generated map 0x{generated:08x}"
                )
                await self.csr_write(f"S12_W{wrap}_{label}_ARITH", arithmetic, value)
                await self._expect(f"S12_W{wrap}_{label}_MAP", generated, value)
                for other in self.wraps:
                    if other != wrap:
                        stray = {
                            "CTRL": wrap_ctrl_reg(other),
                            "SCR": uart_reg(other, "SCR"),
                            "SIZE": engine_reg(other, "LOG_REGION_SIZE"),
                        }[label]
                        await self._expect(f"S12_W{other}_{label}_STRAY", stray, 0)
                await self._write_expect(f"S12_W{wrap}_{label}_RESTORE", arithmetic, 0, 0)
            placed.append(f"w{wrap}:0x{base:08x}")
        self._step("S12")
        self._chk(
            "CHK-LOGENG-UART-EN-RW",
            "S12",
            "wrapper CTRL read 0x0 at reset (S1) and 0x%x after a write of 0x%x and 0x0 after a "
            "write of 0 on %d instances",
            UART_EN,
            UART_EN,
            len(self.wraps),
        )
        self._chk(
            "CHK-LOGENG-BANK-PLACEMENT",
            "S12",
            "signatures written at window_base+n*0x%x+{0x0,0x%x,0x%x} read back at the "
            "generated CTRL, UART SCR and LOG_REGION_SIZE address of the same instance and 0 "
            "at every other instance: %s",
            stride,
            scr_offset,
            size_offset,
            " ".join(placed),
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
        await self._s10()
        await self._s11()
        await self._s12()

        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        self.assert_all_reachable(self.accesses, "UART_LOG_ENGINE_REG_CONTRACT")
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            FENCE_TERMS,
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )
