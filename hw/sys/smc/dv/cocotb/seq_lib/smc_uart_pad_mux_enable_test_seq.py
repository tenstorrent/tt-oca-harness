# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 transmit on pad 12 with CTRL.UART_EN set, cleared and set again.

Sources hw/ip/uart/uart_log_engine_wrap/regs/uart_log_engine_ctrl.rdl (CTRL.UART_EN),
hw/ip/uart/uart_16550/regs/uart_16550_main.rdl (LSR.THRE, LSR.TEMT), the integrator GPIO pad table
(pad 12 = UART[0].TX) and hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL).

The documents do not state the pad 12 behaviour with UART_EN clear: the frames the pad VIP decodes
and the pad level in that state are measured and never compared. The frames of the two UART_EN = 1
legs are the positive controls of the clear leg: they prove the THR write, the transmitter and the
pad decoder work.
"""

from __future__ import annotations

from itertools import groupby

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    UART_CG_EN,
    gpio_intf_u32,
    smc_indexed_addr,
    uart_16550_main_u32,
    uart_log_engine_ctrl_u32,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import pad_function
from .smc_uart_loopback_test_seq import (
    BAUD,
    CAPTURE_TIMEOUT_US,
    CLOCK_GATE_CONTROL,
    LCR_8N1,
    LCR_DLAB,
    TX_BYTE,
    UART0_IER,
    UART0_LCR,
    UART0_LSR,
    UART0_THR,
    UART_LOG_ENGINE_CTRL,
)
from .smc_uart_protocol_vip import SmcUartVip, SmcUartVipError

TX_PAD = 12
TX_PAD_FUNCTION = "UART[0].TX"
GPIO_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", TX_PAD)

UART_EN = uart_log_engine_ctrl_u32("UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
LSR_THRE = uart_16550_main_u32("UART_16550_MAIN__LSR__THRE_bm")
LSR_TEMT = uart_16550_main_u32("UART_16550_MAIN__LSR__TEMT_bm")

DC_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
DC_ENABLE_RX_TX = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bm")
DC_ENABLE_RX_TX_LSB = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
DC_INTERFACE_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
DC_FIELDS = (
    ("interface_enable", DC_INTERFACE_ENABLE),
    ("enable_rx_tx", DC_ENABLE_RX_TX),
    ("core2pad", DC_CORE2PAD),
)

FRAME_BITS = 10
WINDOW_FRAMES = 3
POLL_CYCLES = 64
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6")
CHK_ORDER = (
    ("S2", "CHK-UART-PADMUX-FRAME-ON"),
    ("S3", "CHK-UART-PADMUX-OFF-TX-SHIFTED"),
    ("S3", "CHK-UART-PADMUX-OFF-PAD-MEASURED"),
    ("S4", "CHK-UART-PADMUX-GPIO-LEVEL-MEASURED"),
    ("S5", "CHK-UART-PADMUX-FRAME-RECOVER"),
)


def _now_us() -> float:
    return get_sim_time("ns") / 1000.0


class smc_uart_pad_mux_enable_test_seq(SmcCsrSeq):
    """Drive THR with UART_EN = 1, 0, 1 and watch pad 12 through the pad VIP."""

    def __init__(self, name: str = "smc_uart_pad_mux_enable_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.divisor = 0
        self.vip: SmcUartVip | None = None
        self.levels: list[int] = []
        self.unresolved = 0
        self.cg_saved = 0
        self.ctrl_saved = 0
        self.dc_saved = 0

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _sample_levels(self) -> None:
        pad = cocotb.top.tb_uart0_tx_from_dut
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            try:
                self.levels.append(int(pad.value) & 1)
            except ValueError:
                self.unresolved += 1

    def _pad_level(self) -> int:
        try:
            return int(cocotb.top.tb_uart0_tx_from_dut.value) & 1
        except ValueError as exc:
            raise AssertionError("tb_uart0_tx_from_dut sampled as X/Z") from exc

    async def _lsr(self, label: str) -> tuple[int, int]:
        lsr = await self.csr_read(label, UART0_LSR)
        assert isinstance(lsr, int), f"{label}: unresolved LSR {lsr!r}"
        return int(bool(lsr & LSR_TEMT)), int(bool(lsr & LSR_THRE))

    async def _set_uart_en(self, label: str, value: int) -> int:
        await self.csr_write(label, UART_LOG_ENGINE_CTRL, value)
        got = await self.csr_read(f"{label}_RB", UART_LOG_ENGINE_CTRL)
        return int(bool(got & UART_EN))

    async def _poll_idle(self, label: str, t0_us: float) -> list[tuple[int, int]]:
        """LSR reads after a THR write until TEMT and THRE both read 1 or the bound passes."""
        reads: list[tuple[int, int]] = []
        while True:
            reads.append(await self._lsr(label))
            if reads[-1] == (1, 1):
                return reads
            assert _now_us() - t0_us < CAPTURE_TIMEOUT_US, (
                f"{label}: TEMT/THRE not both 1 within {CAPTURE_TIMEOUT_US} us, last {reads[-1]}"
            )
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)

    async def _frame_leg(self, label: str, expect_en: int) -> tuple[int, int, int]:
        """UART_EN = 1, one THR write, one decoded frame; returns (frames, byte, readback)."""
        vip = self.vip
        readback = await self._set_uart_en(f"{label}_UART_EN", expect_en)
        vip.sink.clear()
        vip.sink.clear_history()
        t0_us = _now_us()
        await self.csr_write(f"{label}_THR", UART0_THR, TX_BYTE)
        byte = await vip.capture_frame(timeout_us=CAPTURE_TIMEOUT_US)
        await self._poll_idle(f"{label}_LSR", t0_us)
        # A repeated transmit would start within one frame time of the first frame ending.
        await Timer(FRAME_BITS * vip.sink.bit_ns, "ns")
        frames = vip.sink.get_frames()
        assert len(frames) == 1, f"{label}: {len(frames)} frames decoded on pad {TX_PAD}, want 1"
        assert not frames[0].framing_error, f"{label}: frame has a framing error"
        return len(frames), byte, readback

    async def _s1(self) -> None:
        function = pad_function(TX_PAD)
        assert function == TX_PAD_FUNCTION, (
            f"the integrator pad table gives pad {TX_PAD} the function {function!r}, not "
            f"{TX_PAD_FUNCTION!r}"
        )
        periph_ns = int(getattr(self.cfg, "periph_clk_period_ns", 10) or 10)
        self.divisor = max(1, int(1.0 / ((periph_ns * 1e-9) * 16 * BAUD) + 0.5) - 1)
        self.cg_saved = await self.csr_read("UART_CG_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, self.cg_saved & ~UART_CG_EN)
        await self.csr_write("UART0_LCR_DLAB", UART0_LCR, LCR_8N1 | LCR_DLAB)
        await self.csr_write("UART0_DLL", UART0_THR, self.divisor & 0xFF)
        await self.csr_write("UART0_DLM", UART0_IER, (self.divisor >> 8) & 0xFF)
        await self.csr_write("UART0_LCR_8N1", UART0_LCR, LCR_8N1)
        await ClockCycles(cocotb.top.clk_smc_i, max(64, self.divisor * 16))
        temt, thre = await self._lsr("LSR_IDLE_SETUP")
        assert (temt, thre) == (1, 1), f"LSR at setup reads TEMT={temt} THRE={thre}, want 1 and 1"
        try:
            self.vip = SmcUartVip(baud=BAUD)
        except SmcUartVipError as exc:
            raise AssertionError(f"UART VIP bind failed: {exc}") from exc
        self.ctrl_saved = await self.csr_read("CTRL_SAVE", UART_LOG_ENGINE_CTRL)
        self.dc_saved = await self.csr_read("DATA_CTRL_SAVE", GPIO_DATA_CTRL)
        cocotb.log.info(
            "UART pad mux: periph_clk=%dns baud=%d divisor=%d bit=%d ns",
            periph_ns,
            BAUD,
            self.divisor,
            self.vip.sink.bit_ns,
        )

    async def _s2(self) -> None:
        frames, byte, readback = await self._frame_leg("A", 1)
        assert readback == 1, f"CTRL.UART_EN reads {readback} after writing 1"
        assert byte == TX_BYTE, f"pad {TX_PAD} frame 0x{byte:02X}, want 0x{TX_BYTE:02X}"
        self._mark("S2")
        self._chk(
            "S2",
            "CHK-UART-PADMUX-FRAME-ON",
            f"CTRL.UART_EN read back {readback} and THR 0x{TX_BYTE:02X} produced {frames} frame "
            f"on pad {TX_PAD} decoded as 0x{byte:02X} within the {CAPTURE_TIMEOUT_US} us bound",
        )

    async def _s3(self) -> None:
        vip = self.vip
        temt, thre = await self._lsr("LSR_IDLE_BEFORE_TOGGLE")
        assert (temt, thre) == (1, 1), f"LSR before the toggle TEMT={temt} THRE={thre}"
        readback = await self._set_uart_en("B_UART_EN", 0)
        assert readback == 0, f"CTRL.UART_EN reads {readback} after writing 0"
        idle = await self._lsr("LSR_IDLE_BEFORE_THR")
        assert idle == (1, 1), f"LSR before the THR write TEMT={idle[0]} THRE={idle[1]}"
        vip.sink.clear()
        vip.sink.clear_history()
        self.levels = []
        self.unresolved = 0
        sampler = cocotb.start_soon(self._sample_levels())
        t0_us = _now_us()
        window_ns = WINDOW_FRAMES * FRAME_BITS * vip.sink.bit_ns
        await self.csr_write("B_THR", UART0_THR, TX_BYTE)
        reads = await self._poll_idle("B_LSR", t0_us)
        left_ns = int(window_ns - (_now_us() - t0_us) * 1000)
        if left_ns > 0:
            await Timer(left_ns, "ns")
        sampler.cancel()
        self._mark("S3")
        temt_seen = [i for i, (t, _) in enumerate(reads) if t == 0]
        assert temt_seen, f"TEMT never read 0 in {len(reads)} LSR reads after the THR write"
        assert reads[-1] == (1, 1)
        runs = [f"({t},{h})x{len(list(g))}" for (t, h), g in groupby(reads)]
        self._chk(
            "S3",
            "CHK-UART-PADMUX-OFF-TX-SHIFTED",
            f"CTRL.UART_EN read back {readback}; the idle LSR reads before the write were "
            f"TEMT=1 THRE=1; after the THR write {len(reads)} LSR reads showed TEMT=0 first at "
            f"read {temt_seen[0]} and TEMT=1 THRE=1 together at the last read; LSR (TEMT,THRE) "
            f"runs {' '.join(runs)}",
        )
        assert self.levels and not self.unresolved, (
            f"pad {TX_PAD} window: {len(self.levels)} samples, {self.unresolved} unresolved"
        )
        frames = vip.sink.get_frames()
        byte_list = ",".join(f"0x{f.data & 0xFF:02X}" for f in frames) or "none"
        self._chk(
            "S3",
            "CHK-UART-PADMUX-OFF-PAD-MEASURED",
            f"measured UART_EN={readback} window={window_ns} ns frames={len(frames)} "
            f"bytes={byte_list} framing_errors={sum(1 for f in frames if f.framing_error)} "
            f"samples={len(self.levels)} level_min={min(self.levels)} level_max={max(self.levels)}",
        )

    async def _s4(self) -> None:
        write_words = (
            DC_INTERFACE_ENABLE | DC_ENABLE_RX_TX_LSB | DC_CORE2PAD,
            DC_INTERFACE_ENABLE | DC_ENABLE_RX_TX_LSB,
        )
        samples: list[str] = []
        parts: list[str] = []
        for tag, word in zip(("core2pad1", "core2pad0"), write_words):
            await self.csr_write(f"GPIO_DC_{tag}", GPIO_DATA_CTRL, word)
            await RisingEdge(cocotb.top.clk_smc_i)
            samples.append(f"{tag}_after_write={self._pad_level()}")
            got = await self.csr_read(f"GPIO_DC_{tag}_RB", GPIO_DATA_CTRL)
            await RisingEdge(cocotb.top.clk_smc_i)
            samples.append(f"{tag}_after_read={self._pad_level()}")
            for fname, mask in DC_FIELDS:
                assert got & mask == word & mask, (
                    f"DATA_CTRL pad {TX_PAD} {fname} reads 0x{got & mask:x} after writing "
                    f"0x{word & mask:x} ({tag})"
                )
            fields = " ".join(f"{n}=0x{(got & m) // (m & -m):x}" for n, m in DC_FIELDS)
            parts.append(f"{tag}: {fields}")
        await self.csr_write("GPIO_DC_RESTORE", GPIO_DATA_CTRL, self.dc_saved)
        back = await self.csr_read("GPIO_DC_RESTORE_RB", GPIO_DATA_CTRL)
        for fname, mask in DC_FIELDS:
            assert back & mask == self.dc_saved & mask, (
                f"DATA_CTRL pad {TX_PAD} {fname} reads 0x{back & mask:x} after the restore, "
                f"saved 0x{self.dc_saved & mask:x}"
            )
        self._mark("S4")
        self._chk(
            "S4",
            "CHK-UART-PADMUX-GPIO-LEVEL-MEASURED",
            f"measured pad {TX_PAD} level {' '.join(samples)} (UART_EN=0, not compared); "
            f"DATA_CTRL read-backs compared equal to the written values: {'; '.join(parts)}; "
            f"restore read back equal to the saved value",
        )

    async def _s5(self) -> None:
        frames, byte, readback = await self._frame_leg("D", 1)
        assert readback == 1, f"CTRL.UART_EN reads {readback} after writing 1 again"
        assert byte == TX_BYTE, f"pad {TX_PAD} frame 0x{byte:02X}, want 0x{TX_BYTE:02X}"
        self._mark("S5")
        self._chk(
            "S5",
            "CHK-UART-PADMUX-FRAME-RECOVER",
            f"CTRL.UART_EN read back {readback} after the clear and THR 0x{TX_BYTE:02X} produced "
            f"{frames} frame on pad {TX_PAD} decoded as 0x{byte:02X} within the "
            f"{CAPTURE_TIMEOUT_US} us bound",
        )

    async def _s6(self) -> None:
        await self.csr_write("CTRL_RESTORE", UART_LOG_ENGINE_CTRL, self.ctrl_saved)
        got = await self.csr_read("CTRL_RESTORE_RB", UART_LOG_ENGINE_CTRL)
        assert got & UART_EN == self.ctrl_saved & UART_EN, f"CTRL reads 0x{got:x} after restore"
        await self.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, self.cg_saved)
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S6")
        self._nonvac()

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1 < S2 < S3 < S4 < S5 < S6, step stamps strictly "
            "increasing, each checker line after its own step; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )

    async def body(self) -> None:
        await self._s1()
        self._mark("S1")
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
