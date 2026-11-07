# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 pads 11 to 14 with CTRL.UART_EN set, cleared and set again.

Sources hw/ip/uart/uart_log_engine_wrap/regs/uart_log_engine_ctrl.rdl (CTRL.UART_EN: "When set,
the pad-mux downstream will be forced to accept UART traffic"), hw/ip/uart/log_engine/doc/index.adoc
(the control block drives uart_en_o from CTRL.UART_EN), hw/ip/gpio/doc/architecture.adoc (GPIO data
and direction selection: a hardware LSIO request outranks the register sources, and with no request
the pad has output data 0, TX disabled and RX by INPUT_BY_DEFAULT),
hw/ip/uart/uart_16550/regs/uart_16550_main.rdl (LSR.THRE, LSR.TEMT, MCR.RTS, MSR.CTS), the
integrator GPIO pad table (pad 11 = UART[0].RX, 12 = TX, 13 = RTS, 14 = CTS) and
hw/ip/gpio/regs/gpio_intf.rdl (DATA_CTRL).

S5 grades the three pads the TX legs leave out. RTS: with UART_EN clear, MCR.RTS set does not
enable the pad-13 driver (`tb_core2pad_en_o[13]` stays 0); with UART_EN set the driver enables and
the pad carries the inverted bit. CTS: with UART_EN clear the pad-14 level does not reach MSR.CTS;
with UART_EN set MSR.CTS follows the pad in opposite polarity. RX: with UART_EN clear a frame driven
on pad 11 does not reach RBR; with UART_EN set it does. INPUT-IDLE: with UART_EN clear and no
LSIO selection on pads 11 and 14 (`tb_lsio_interface_select` of both reads 0 on 64 cycles), the
UART's receive and CTS inputs read high, the serial
idle level (uart_log_engine_ctrl.rdl CTRL.UART_EN; hw/sys/smc/doc/periphs.adoc, GPIO
LSIO_PAD2CORE_IDLE from smc_padring_pkg::LsioIdleLevelMap): MSR.CTS reads 0 with pad 14 low and
with it high, and the receiver reports no character after a receive-FIFO reset, a frame queued on
pad 11 and two frame times.

CTRL.UART_EN is the hardware LSIO request of the UART0 pads (uart_log_engine_ctrl.rdl CTRL.UART_EN;
the SMC programmer's guide, "LSIO" of the GPIO section). With it clear and pad 12 holding no register
override (DATA_CTRL.interface_enable, DATA_CTRL.lsio_select and the DATA_CTRL_ENABLE.use_reg_* bits
all 0) the pad takes the last row of the GPIO data and direction selection: output data 0 with the
transmitter disabled, so a frame the UART shifts out does not reach the pad. S3 grades that with the
register row's own data set to 1 (DATA_CTRL.core2pad and enable_rx_tx[0] written 1 while the selects
stay 0, so a pad that takes the register row shows 1): zero frames decoded, the pad output held at 0
and its output enable held at 0 across the window while LSR.TEMT goes 0 then 1. The frames of the two
UART_EN = 1 legs are the positive controls of the clear leg: they prove the THR write, the
transmitter and the pad decoder work.

With UART_EN clear and DATA_CTRL.interface_enable set, gpio_intf.rdl (DATA_CTRL.interface_enable:
"Setting this chooses register values to drive the PAD") makes core2pad the pad level, so S4
compares the pad against core2pad 1 then 0.

The pad VIP, like any receiver, takes a fall of pad 12 to 0 as a start bit and samples the next
ten bit times from it, so a THR write within one frame time of the pad falling is decoded as part
of that frame. S5 therefore writes the register row (interface_enable, enable_rx_tx[0] and core2pad
1) before its UART_EN toggles: with UART_EN clear the pad carries core2pad 1, with it set the UART's
idle 1, and the line stays at mark. S6 sets UART_EN before it writes the saved DATA_CTRL back, so
the pad goes from the register row's 1 to the UART's idle 1, and every clk_smc_i sample from the
hold to the THR write is compared equal to 1.
"""

from __future__ import annotations

from itertools import groupby

import cocotb
from cocotb.task import Task
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    UART_CG_EN,
    gpio_intf_u32,
    smc_indexed_addr,
    uart_16550_main_u32,
    uart_16550_wo_u32,
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

RX_PAD = 11
TX_PAD = 12
RTS_PAD = 13
CTS_PAD = 14
TX_PAD_FUNCTION = "UART[0].TX"
PAD_FUNCTIONS = {RX_PAD: "UART[0].RX", RTS_PAD: "UART[0].RTS", CTS_PAD: "UART[0].CTS"}
GPIO_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_BASE_ADDR", TX_PAD)
GPIO_DATA_CTRL_ENABLE = smc_indexed_addr(
    "SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_DATA_CTRL_ENABLE_BASE_ADDR", TX_PAD
)
UART0_MCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR", 0)
UART0_MSR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR", 0)
UART0_RBR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", 0)
# FCR is the write-only alias of the IIR address.
UART0_FCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", 0)

UART_EN = uart_log_engine_ctrl_u32("UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
LSR_DR = uart_16550_main_u32("UART_16550_MAIN__LSR__DR_bm")
LSR_THRE = uart_16550_main_u32("UART_16550_MAIN__LSR__THRE_bm")
LSR_TEMT = uart_16550_main_u32("UART_16550_MAIN__LSR__TEMT_bm")
LSR_FLAGS = (
    uart_16550_main_u32("UART_16550_MAIN__LSR__OE_bm")
    | uart_16550_main_u32("UART_16550_MAIN__LSR__PE_bm")
    | uart_16550_main_u32("UART_16550_MAIN__LSR__FE_bm")
    | uart_16550_main_u32("UART_16550_MAIN__LSR__BI_bm")
)
MCR_RTS = uart_16550_main_u32("UART_16550_MAIN__MCR__RTS_bm")
MSR_CTS = uart_16550_main_u32("UART_16550_MAIN__MSR__CTS_bm")
FCR_RX_RESET = uart_16550_wo_u32("UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm") | uart_16550_wo_u32(
    "UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm"
)
# The byte S5 drives into pad 11: not the TX byte, and not the 0x00 a held-low
# line would deliver.
RX_BYTE = 0x3C
# Characters drained from the receiver after the UART_EN=0 frame.
RX_DRAIN_READS = 40

DC_CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
DC_ENABLE_RX_TX = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bm")
DC_ENABLE_RX_TX_LSB = 1 << gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
DC_INTERFACE_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
DC_LSIO_SELECT = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_SELECT_bm")
DC_LSIO_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")
DC_SELECTS = DC_INTERFACE_ENABLE | DC_LSIO_SELECT | DC_LSIO_ENABLE
DC_ROW_DATA = DC_CORE2PAD | DC_ENABLE_RX_TX_LSB
DC_REG_HIGH = DC_INTERFACE_ENABLE | DC_ENABLE_RX_TX_LSB | DC_CORE2PAD
DCE_USE_REG = (
    gpio_intf_u32("GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_CORE2PAD_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_TX_bm")
    | gpio_intf_u32("GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_RX_bm")
)
DC_FIELDS = (
    ("interface_enable", DC_INTERFACE_ENABLE),
    ("enable_rx_tx", DC_ENABLE_RX_TX),
    ("core2pad", DC_CORE2PAD),
)

FRAME_BITS = 10
WINDOW_FRAMES = 3
POLL_CYCLES = 64
PAD_BOUND = 64
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
CHK_ORDER = (
    ("S2", "CHK-UART-PADMUX-FRAME-ON"),
    ("S3", "CHK-UART-PADMUX-OFF-TX-SHIFTED"),
    ("S3", "CHK-UART-PADMUX-OFF-PAD-HELD"),
    ("S4", "CHK-UART-PADMUX-GPIO-LEVEL-MEASURED"),
    ("S5", "CHK-UART-PADMUX-RTS"),
    ("S5", "CHK-UART-PADMUX-CTS"),
    ("S5", "CHK-UART-PADMUX-RX"),
    ("S5", "CHK-UART-PADMUX-INPUT-IDLE"),
    ("S6", "CHK-UART-PADMUX-FRAME-RECOVER"),
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
        self.oe_levels: list[int] = []
        self.unresolved = 0
        self.cg_saved = 0
        self.ctrl_saved = 0
        self.dc_saved = 0
        self.sampler: Task | None = None

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    async def _sample_levels(self) -> None:
        pad = cocotb.top.tb_uart0_tx_from_dut
        oe = cocotb.top.tb_core2pad_en_o
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            try:
                level = int(pad.value) & 1
                oe_level = (int(oe.value) >> TX_PAD) & 1
            except ValueError:
                self.unresolved += 1
                continue
            self.levels.append(level)
            self.oe_levels.append(oe_level)

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
        readback = await self._set_uart_en(f"{label}_UART_EN", UART_EN if expect_en else 0)
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
        await self.csr_write("DATA_CTRL_ROW_DATA", GPIO_DATA_CTRL, self.dc_saved | DC_ROW_DATA)
        dc = await self.csr_read("DATA_CTRL_NO_SELECT", GPIO_DATA_CTRL)
        dce = await self.csr_read("DATA_CTRL_ENABLE_NO_SELECT", GPIO_DATA_CTRL_ENABLE)
        assert dc & DC_SELECTS == 0 and dce & DCE_USE_REG == 0, (
            f"pad {TX_PAD} DATA_CTRL 0x{dc:x} DATA_CTRL_ENABLE 0x{dce:x}: interface_enable, "
            "lsio_select, lsio_enable and use_reg_* must all be 0 for the no-request row"
        )
        assert dc & DC_ROW_DATA == DC_ROW_DATA, (
            f"pad {TX_PAD} DATA_CTRL 0x{dc:x}: core2pad and enable_rx_tx[0] read back 0 after "
            "writing 1"
        )
        idle = await self._lsr("LSR_IDLE_BEFORE_THR")
        assert idle == (1, 1), f"LSR before the THR write TEMT={idle[0]} THRE={idle[1]}"
        vip.sink.clear()
        vip.sink.clear_history()
        self.levels = []
        self.oe_levels = []
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
        await self.csr_write("DATA_CTRL_ROW_RESTORE", GPIO_DATA_CTRL, self.dc_saved)
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
        byte_list = ",".join(f"0x{f.data & 0xFF:02X}" for f in frames)
        assert not frames, (
            f"pad {TX_PAD} carried {len(frames)} frame(s) ({byte_list}) with UART_EN=0 and no "
            "register override; the pad takes output data 0 without a hardware LSIO request"
        )
        assert max(self.levels) == 0, (
            f"pad {TX_PAD} output rose to 1 in {sum(self.levels)} of {len(self.levels)} samples "
            "with UART_EN=0, core2pad=1 and no select set; the pad takes output data 0 without a "
            "hardware LSIO request"
        )
        assert max(self.oe_levels) == 0, (
            f"pad {TX_PAD} output enable rose to 1 in {sum(self.oe_levels)} of "
            f"{len(self.oe_levels)} samples with UART_EN=0, enable_rx_tx[0]=1 and no select set; "
            "the transmitter is disabled without a hardware LSIO request"
        )
        self._chk(
            "S3",
            "CHK-UART-PADMUX-OFF-PAD-HELD",
            f"UART_EN={readback} with pad {TX_PAD} DATA_CTRL=0x{dc:x} (core2pad=1 enable_rx_tx[0]=1, "
            f"interface_enable=0 lsio_select=0 lsio_enable=0) DATA_CTRL_ENABLE=0x{dce:x} (use_reg=0): "
            f"frames decoded compared equal to 0, the pad output compared equal to 0 and its output "
            f"enable compared equal to 0 in all {len(self.levels)} samples of the {window_ns} ns "
            f"window while the transmitter shifted",
        )

    async def _await_pad(self, label: str, want: int) -> int:
        """clk_smc_i cycles until pad 12 reads ``want``; expiry raises."""
        for cycle in range(PAD_BOUND):
            await RisingEdge(cocotb.top.clk_smc_i)
            if self._pad_level() == want:
                return cycle + 1
        raise AssertionError(
            f"{label}: pad {TX_PAD} still {self._pad_level()} {PAD_BOUND} clk_smc_i cycles "
            f"after DATA_CTRL.core2pad = {want} with interface_enable = 1"
        )

    async def _s4(self) -> None:
        write_words = (DC_REG_HIGH, DC_REG_HIGH & ~DC_CORE2PAD)
        samples: list[str] = []
        parts: list[str] = []
        for tag, word in zip(("core2pad1", "core2pad0"), write_words):
            want = int(bool(word & DC_CORE2PAD))
            await self.csr_write(f"GPIO_DC_{tag}", GPIO_DATA_CTRL, word)
            cycles = await self._await_pad(f"GPIO_DC_{tag}", want)
            samples.append(f"{tag}_after_write={self._pad_level()} in {cycles} cycles")
            got = await self.csr_read(f"GPIO_DC_{tag}_RB", GPIO_DATA_CTRL)
            await RisingEdge(cocotb.top.clk_smc_i)
            level = self._pad_level()
            assert level == want, (
                f"pad {TX_PAD} reads {level} after the DATA_CTRL read-back, core2pad = {want} "
                f"with interface_enable = 1 ({tag})"
            )
            samples.append(f"{tag}_after_read={level}")
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
            f"pad {TX_PAD} level compared equal to core2pad with UART_EN=0 and "
            f"interface_enable=1: {' '.join(samples)}; "
            f"DATA_CTRL read-backs compared equal to the written values: {'; '.join(parts)}; "
            f"restore read back equal to the saved value",
        )

    # -- S5: the RX, RTS and CTS pads under UART_EN ---------------------------

    @staticmethod
    def _bus_bit(name: str, pad: int) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z"
        return (int(value) >> pad) & 1

    @staticmethod
    def _drive_pad(pad: int, level: int | None) -> None:
        """Drive ``pad`` to ``level`` through the top-level pad pins, or release it."""
        dut = cocotb.top
        mask = 1 << pad
        en = int(dut.tb_gpio_ext_drive_en.value)
        val = int(dut.tb_gpio_ext_drive_value.value)
        if level is None:
            dut.tb_gpio_ext_drive_en.value = en & ~mask
            dut.tb_gpio_ext_drive_value.value = val & ~mask
            return
        dut.tb_gpio_ext_drive_en.value = en | mask
        dut.tb_gpio_ext_drive_value.value = (val | mask) if level else (val & ~mask)

    async def _await_pad_bits(self, label: str, want: dict[tuple[str, int], int]) -> int:
        """clk_smc_i cycles until every (bus, pad) reads its wanted value; expiry raises."""
        for cycle in range(PAD_BOUND):
            await RisingEdge(cocotb.top.clk_smc_i)
            if all(self._bus_bit(name, pad) == level for (name, pad), level in want.items()):
                return cycle + 1
        got = {f"{name}[{pad}]": self._bus_bit(name, pad) for (name, pad) in want}
        raise AssertionError(f"{label}: {got} after {PAD_BOUND} clk_smc_i cycles, want {want}")

    async def _hold_pad_bits(self, label: str, want: dict[tuple[str, int], int]) -> None:
        """Every (bus, pad) reads its wanted value on each of PAD_BOUND clk_smc_i cycles."""
        for cycle in range(PAD_BOUND):
            await RisingEdge(cocotb.top.clk_smc_i)
            for (name, pad), level in want.items():
                got = self._bus_bit(name, pad)
                assert got == level, (
                    f"{label}: {name}[{pad}] reads {got} on cycle {cycle + 1}, want {level}"
                )

    async def _msr_cts(self, label: str) -> int:
        # The first read clears a stale DCTS; the second carries the level.
        await self.csr_read(f"{label}_MSR_CLR", UART0_MSR)
        return int(bool(await self.csr_read(f"{label}_MSR", UART0_MSR) & MSR_CTS))

    async def _await_cts(self, label: str, want: int) -> int:
        for read in range(1, PAD_BOUND + 1):
            if await self._msr_cts(f"{label}_{read}") == want:
                return read
        raise AssertionError(f"{label}: MSR.CTS never read {want} in {PAD_BOUND} reads")

    async def _rts_leg(self) -> str:
        await self.csr_write("S5_MCR_RTS", UART0_MCR, MCR_RTS)
        await self._hold_pad_bits(
            "S5_RTS_OFF",
            {("tb_core2pad_en_o", RTS_PAD): 0, ("tb_lsio_interface_select", RTS_PAD): 0},
        )
        readback = await self._set_uart_en("S5_RTS_UART_EN", UART_EN)
        assert readback == 1, f"CTRL.UART_EN reads {readback} after writing 1"
        on_cycles = await self._await_pad_bits(
            "S5_RTS_ON",
            {
                ("tb_core2pad_en_o", RTS_PAD): 1,
                ("tb_core2pad_o", RTS_PAD): 0,
                ("tb_lsio_interface_select", RTS_PAD): 1,
            },
        )
        await self.csr_write("S5_MCR_RTS_CLR", UART0_MCR, 0)
        high_cycles = await self._await_pad_bits(
            "S5_RTS_HIGH", {("tb_core2pad_en_o", RTS_PAD): 1, ("tb_core2pad_o", RTS_PAD): 1}
        )
        readback = await self._set_uart_en("S5_RTS_UART_EN_OFF", 0)
        assert readback == 0, f"CTRL.UART_EN reads {readback} after writing 0"
        off_cycles = await self._await_pad_bits(
            "S5_RTS_OFF_AGAIN", {("tb_core2pad_en_o", RTS_PAD): 0}
        )
        return (
            f"UART_EN=0 MCR.RTS=1: core2pad_en[{RTS_PAD}]=0 and lsio_select[{RTS_PAD}]=0 on "
            f"{PAD_BOUND} cycles; UART_EN=1: core2pad_en=1 core2pad=0 (inverted RTS) in "
            f"{on_cycles} cycles, MCR.RTS=0 -> core2pad=1 in {high_cycles} cycles; UART_EN=0: "
            f"core2pad_en=0 in {off_cycles} cycles"
        )

    async def _cts_leg(self) -> tuple[str, str]:
        await self._hold_pad_bits(
            "S5_INPUTS_DESELECTED",
            {("tb_lsio_interface_select", RX_PAD): 0, ("tb_lsio_interface_select", CTS_PAD): 0},
        )
        self._drive_pad(CTS_PAD, 0)
        await ClockCycles(cocotb.top.clk_smc_i, PAD_BOUND)
        cts_low = await self._msr_cts("S5_CTS_OFF_PAD0")
        self._drive_pad(CTS_PAD, 1)
        await ClockCycles(cocotb.top.clk_smc_i, PAD_BOUND)
        cts_high = await self._msr_cts("S5_CTS_OFF_PAD1")
        assert cts_low == cts_high, (
            f"with UART_EN=0 MSR.CTS read {cts_low} with pad {CTS_PAD} low and {cts_high} with "
            f"it high; the pad follows the GPIO selection and does not reach the UART"
        )
        assert (cts_low, cts_high) == (0, 0), (
            f"with UART_EN=0 MSR.CTS read {cts_low} with pad {CTS_PAD} low and {cts_high} with "
            f"it high; the CTS input of a deselected UART reads high, the idle level, so MSR.CTS "
            f"reads 0"
        )
        readback = await self._set_uart_en("S5_CTS_UART_EN", UART_EN)
        assert readback == 1, f"CTRL.UART_EN reads {readback} after writing 1"
        self._drive_pad(CTS_PAD, 0)
        low_reads = await self._await_cts("S5_CTS_ON_PAD0", 1)
        self._drive_pad(CTS_PAD, 1)
        high_reads = await self._await_cts("S5_CTS_ON_PAD1", 0)
        self._drive_pad(CTS_PAD, None)
        readback = await self._set_uart_en("S5_CTS_UART_EN_OFF", 0)
        assert readback == 0, f"CTRL.UART_EN reads {readback} after writing 0"
        return (
            f"UART_EN=0: MSR.CTS={cts_low} with pad {CTS_PAD} low and {cts_high} with it high "
            f"({PAD_BOUND} cycles after each drive); UART_EN=1: pad low -> MSR.CTS=1 in "
            f"{low_reads} reads, pad high -> MSR.CTS=0 in {high_reads} reads",
            f"lsio_select[{RX_PAD}]=0 and lsio_select[{CTS_PAD}]=0 on {PAD_BOUND} cycles; "
            f"MSR.CTS={cts_low} with pad {CTS_PAD} low and {cts_high} with it high ({PAD_BOUND} "
            f"cycles after each drive; the CTS input reads the idle level, high)",
        )

    async def _drain_rx(self, label: str) -> list[tuple[int, int]]:
        drained: list[tuple[int, int]] = []
        for read in range(RX_DRAIN_READS):
            lsr = await self.csr_read(f"{label}_LSR_{read}", UART0_LSR)
            if not lsr & LSR_DR:
                break
            rbr = await self.csr_read(f"{label}_RBR_{read}", UART0_RBR)
            drained.append((int(lsr) & 0xFF, int(rbr) & 0xFF))
        return drained

    async def _rx_leg(self) -> tuple[str, str]:
        vip = self.vip
        frame_ns = FRAME_BITS * vip.sink.bit_ns
        await self.csr_write("S5_RX_FCR_OFF", UART0_FCR, FCR_RX_RESET)
        await vip.drive_frame(bytes([RX_BYTE]))
        # The frame is queued; one frame time carries it on the pad and one more
        # lets a receiver that took it post the character before the drain.
        await Timer(2 * frame_ns, "ns")
        off = await self._drain_rx("S5_RX_OFF")
        assert all(byte != RX_BYTE for _, byte in off), (
            f"with UART_EN=0 the frame 0x{RX_BYTE:02X} driven on pad {RX_PAD} reached RBR "
            f"({off}); the pad follows the GPIO selection and does not reach the UART"
        )
        assert off == [], (
            f"with UART_EN=0 the receiver reported {off} after the receive-FIFO reset, a frame "
            f"queued on pad {RX_PAD} and two frame times; the receive input of a deselected "
            f"UART reads high, the idle level, so no start bit opens a frame"
        )
        readback = await self._set_uart_en("S5_RX_UART_EN", UART_EN)
        assert readback == 1, f"CTRL.UART_EN reads {readback} after writing 1"
        # The receive FIFO is reset one frame time after the pad takes over, so
        # the on leg starts from an empty FIFO whatever the pad carried meanwhile.
        await Timer(frame_ns, "ns")
        await self.csr_write("S5_RX_FCR_ON", UART0_FCR, FCR_RX_RESET)
        await vip.drive_frame(bytes([RX_BYTE]))
        await Timer(frame_ns, "ns")
        on = await self._drain_rx("S5_RX_ON")
        assert on == [(LSR_DR | LSR_THRE | LSR_TEMT, RX_BYTE)], (
            f"with UART_EN=1 the frame 0x{RX_BYTE:02X} driven on pad {RX_PAD} produced {on}; "
            f"want exactly one character 0x{RX_BYTE:02X} with LSR clear of errors"
        )
        readback = await self._set_uart_en("S5_RX_UART_EN_OFF", 0)
        assert readback == 0, f"CTRL.UART_EN reads {readback} after writing 0"
        return (
            f"UART_EN=0: frame 0x{RX_BYTE:02X} on pad {RX_PAD} not in the {len(off)} "
            f"character(s) drained; UART_EN=1: the same frame read back as 0x{RX_BYTE:02X} "
            f"with LSR 0x{on[0][0]:02X}",
            f"no character reported after the receive-FIFO reset, a frame queued on pad {RX_PAD} "
            f"and two frame times ({len(off)} drained; the receive input reads the idle level, high)",
        )

    async def _s5(self) -> None:
        for pad, function in PAD_FUNCTIONS.items():
            got = pad_function(pad)
            assert got == function, (
                f"the integrator pad table gives pad {pad} the function {got!r}, not {function!r}"
            )
        await self.csr_write("S5_DC_HOLD", GPIO_DATA_CTRL, DC_REG_HIGH)
        await self._await_pad("S5_DC_HOLD", 1)
        self.levels = []
        self.oe_levels = []
        self.unresolved = 0
        self.sampler = cocotb.start_soon(self._sample_levels())
        rts = await self._rts_leg()
        cts, cts_obs = await self._cts_leg()
        rx, rx_obs = await self._rx_leg()
        self._mark("S5")
        self._chk("S5", "CHK-UART-PADMUX-RTS", rts)
        self._chk("S5", "CHK-UART-PADMUX-CTS", cts)
        self._chk("S5", "CHK-UART-PADMUX-RX", rx)
        self._chk("S5", "CHK-UART-PADMUX-INPUT-IDLE", f"UART_EN=0: {cts_obs}; {rx_obs}")

    async def _s6(self) -> None:
        readback = await self._set_uart_en("D_UART_EN_HOLD", UART_EN)
        assert readback == 1, f"CTRL.UART_EN reads {readback} after writing 1 again"
        await self.csr_write("D_DC_RESTORE", GPIO_DATA_CTRL, self.dc_saved)
        back = await self.csr_read("D_DC_RESTORE_RB", GPIO_DATA_CTRL)
        for fname, mask in DC_FIELDS:
            assert back & mask == self.dc_saved & mask, (
                f"DATA_CTRL pad {TX_PAD} {fname} reads 0x{back & mask:x} after the restore, "
                f"saved 0x{self.dc_saved & mask:x}"
            )
        await RisingEdge(cocotb.top.clk_smc_i)
        self.sampler.cancel()
        held = len(self.levels)
        assert self.levels and not self.unresolved, (
            f"pad {TX_PAD} hold: {held} samples, {self.unresolved} unresolved"
        )
        assert min(self.levels) == 1, (
            f"pad {TX_PAD} read 0 in {held - sum(self.levels)} of {held} samples between the S5 "
            f"register hold (DATA_CTRL=0x{DC_REG_HIGH:x}) and the THR write; a fall of the line "
            "opens a frame in the pad VIP"
        )
        frames, byte, readback = await self._frame_leg("D", 1)
        assert readback == 1, f"CTRL.UART_EN reads {readback} after writing 1 again"
        assert byte == TX_BYTE, f"pad {TX_PAD} frame 0x{byte:02X}, want 0x{TX_BYTE:02X}"
        self._mark("S6")
        self._chk(
            "S6",
            "CHK-UART-PADMUX-FRAME-RECOVER",
            f"pad {TX_PAD} compared equal to 1 in all {held} clk_smc_i samples from the S5 "
            f"register hold (DATA_CTRL=0x{DC_REG_HIGH:x}) through the UART_EN toggles, the "
            f"UART_EN write and the DATA_CTRL restore (read back equal to the saved value); "
            f"CTRL.UART_EN read back {readback} after the clear and THR 0x{TX_BYTE:02X} produced "
            f"{frames} frame on pad {TX_PAD} decoded as 0x{byte:02X} within the "
            f"{CAPTURE_TIMEOUT_US} us bound",
        )

    async def _s7(self) -> None:
        await self.csr_write("CTRL_RESTORE", UART_LOG_ENGINE_CTRL, self.ctrl_saved)
        got = await self.csr_read("CTRL_RESTORE_RB", UART_LOG_ENGINE_CTRL)
        assert got & UART_EN == self.ctrl_saved & UART_EN, f"CTRL reads 0x{got:x} after restore"
        await self.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, self.cg_saved)
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S7")
        self._nonvac()

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1 < S2 < S3 < S4 < S5 < S6 < S7, step stamps strictly "
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
        await self._s7()
