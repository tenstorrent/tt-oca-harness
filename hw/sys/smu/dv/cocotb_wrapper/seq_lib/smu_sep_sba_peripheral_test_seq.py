# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP peripherals whose outputs cross the SMU, driven from the SEP debug system bus.

S0..S3 are ``smu_dtp_sep_dm_dmi_test``. Every later access is a system-bus access
(RISC-V Debug Specification 0.13).

S4: the SEP-to-SMC mailboxes. Each outbound mailbox raises its interrupt to the
    SMC while its write FIFO holds more words than WIRQT with the write-threshold
    interrupt enabled (``axil_mailbox`` register description). For every mailbox
    a word written with WIRQT 0 and IRQEN.wtirq set raises the mailbox's lane of
    the SEP mailbox interrupt vector alone; flushing the FIFO, acknowledging
    IRQS and clearing IRQEN drops it.
S5: the SEP SPI host (``spi_host.hjson``). With the host enabled and its output
    driven, a quad-speed transmit of four bytes drives every data lane and its
    output enable, and a quad-speed receive turns the enables off; the TX
    watermark raises the host's LSIO trigger while the FIFO is empty, and the
    IDLE event raises the host interrupt, which INTR_STATE clears. With the
    host not driving them the four data pads are inputs (``smc_padring.sv``),
    and values the bench drives on GPIO pads 0..3 return on the SPI receive
    lanes.
S6: the security-disable token (``efuse_token_processing.sv``). The bench binds
    the SHA-256 of the all-zero token as the SEP's expected digest
    (``tb_wrapper_top.sv``), so writing that token and its GO strobe reports the
    match code in SEC_DISABLE_TOKEN_MATCH and raises the SEP security-disable
    output; a token one bit off then reports a mismatch and drops it.
S7: the SEP watchdog (OpenTitan ``aon_timer``). With WDOG_CTRL.enable set and a
    small bite threshold, the watchdog bites and requests the SMC watchdog reset.
    The request is sticky until the watchdog's reset (``aon_timer.sv``), which
    is the SMC primary reset the SEP runs on (``smu.sv``); holding the cool
    reset pin, which asserts that reset, drops it.
S8: the SMU ties off the input enables of SPI lanes 4..7, the DQS pad and the
    rebar loopback (``smu.sv``), so with the bench driving those pads high they
    read 0 while the chip runs. In cold reset the GPIO wraps enable every pad
    input (``gpio.sv`` INPUT_BY_DEFAULT) and pass it through, so the lanes read
    the pads; once the cold-stable reset the GPIO wraps run on releases, they
    read 0 again.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.smu_addr_map import c_header_u32
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_dtp_sep_dm_sba_test_seq import _REPO_ROOT, _SEP_ADDR_H, _indexed_addr
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import smu_sep_sba_fabric_sweep_test_seq
from seq_lib.smu_tb_pins import smu_scope

_MBOX_C = _REPO_ROOT / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c"
_MBOX_ADDR_H = _MBOX_C / "axil_mailbox_addr.h"
_MBOX_H = _MBOX_C / "axil_mailbox.h"
_MMR_H = _REPO_ROOT / "hw" / "ip" / "efuse" / "regs" / "gen" / "c" / "efuse_mmr.h"


def _sep(symbol: str) -> int:
    return c_header_u32(_SEP_ADDR_H, f"OCH_SEP_TOP_{symbol}")


def _mbox_off(name: str) -> int:
    return c_header_u32(_MBOX_ADDR_H, f"AXIL_MAILBOX_{name}_BASE_ADDR")


NUM_MAILBOXES = 8
MBOX_WRITE_DATA = _mbox_off("WRITE_DATA")
MBOX_WIRQT = _mbox_off("WIRQT")
MBOX_IRQS = _mbox_off("IRQS")
MBOX_IRQEN = _mbox_off("IRQEN")
MBOX_CTRL = _mbox_off("CTRL")
MBOX_WTIRQ = c_header_u32(_MBOX_H, "AXIL_MAILBOX__IRQEN__WTIRQ_bm")
MBOX_ALL_IRQS = (
    c_header_u32(_MBOX_H, "AXIL_MAILBOX__IRQS__WTIRQ_bm")
    | c_header_u32(_MBOX_H, "AXIL_MAILBOX__IRQS__RTIRQ_bm")
    | c_header_u32(_MBOX_H, "AXIL_MAILBOX__IRQS__EIRQ_bm")
)
MBOX_FLUSH = c_header_u32(_MBOX_H, "AXIL_MAILBOX__CTRL__WFLUSH_bm") | c_header_u32(
    _MBOX_H, "AXIL_MAILBOX__CTRL__RFLUSH_bm"
)
MBOX_IRQ_PATH = "sep_mailbox_interrupts"

SPI_INTR_STATE = _sep("SPI_CONTROLLER_INTR_STATE_BASE_ADDR")
SPI_INTR_ENABLE = _sep("SPI_CONTROLLER_INTR_ENABLE_BASE_ADDR")
SPI_CONTROL = _sep("SPI_CONTROLLER_CONTROL_BASE_ADDR")
SPI_STATUS = _sep("SPI_CONTROLLER_STATUS_BASE_ADDR")
SPI_CONFIGOPTS = _sep("SPI_CONTROLLER_CONFIGOPTS_BASE_ADDR")
SPI_CSID = _sep("SPI_CONTROLLER_CSID_BASE_ADDR")
SPI_COMMAND = _sep("SPI_CONTROLLER_COMMAND_BASE_ADDR")
SPI_EVENT_ENABLE = _sep("SPI_CONTROLLER_EVENT_ENABLE_BASE_ADDR")
# spi_host.hjson: the RXDATA and TXDATA windows follow COMMAND.
SPI_TXDATA = SPI_COMMAND + 0x8
SPI_SPIEN = 1 << 31
SPI_OUTPUT_EN = 1 << 29
SPI_TX_WATERMARK = 4 << 8
SPI_ACTIVE = 1 << 30
SPI_EVENT_IDLE = 1 << 5
SPI_INTR_EVENT = 1 << 1
SPI_SPEED_QUAD = 2
SPI_DIR_RX = 1
SPI_DIR_TX = 2
SPI_REQ_PATH = "sep_io_spi_req"
# SPI data lanes 0..3 return through GPIO pads 0..3 (smc_padring.sv), whose input
# is enabled whenever the host is not driving them.
RX_PATH = "sep_spi_rxd"
RX_PAD_MASK = 0xF
RX_PAD_PATTERNS = [0xF, 0x0, 0x5, 0xA, 0x0]
RX_PAD_HOLD_CYCLES = 256
# GPIO pads 4..7 (SPI lanes 4..7), 10 (DQS) and 54 (rebar loopback) in
# smc_padring.sv; the SMU ties their input enables off (smu.sv).
UNUSED_PAD_MASK = (0xF << 4) | (1 << 10) | (1 << 54)
COLD_RESET_HOLD_REF_CYCLES = 64
COLD_RELEASE_POLLS = 2000
SPI_POLLS = 64

TOKEN_WORDS = [
    _indexed_addr("OCH_SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_I_BASE_ADDR", i) for i in range(8)
]
TOKEN_EOP = _sep("EFUSE_MMR_TOKEN_EOP_BASE_ADDR")
TOKEN_MATCH = _sep("EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_BASE_ADDR")
TOKEN_GO = c_header_u32(_MMR_H, "EFUSE_MMR__TOKEN_EOP__SECURE_DISABLE_TOKEN_GO_bm")
TOKEN_MATCH_CODE = 0b010101
SECURITY_DISABLE_PATH = "sep_security_disable"

WDOG_CTRL = _sep("WDT_TIMER_WDOG_CTRL_BASE_ADDR")
WDOG_BARK = _sep("WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR")
WDOG_BITE = _sep("WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR")
WDOG_COUNT = _sep("WDT_TIMER_WDOG_COUNT_BASE_ADDR")
WDOG_ENABLE = 1
WDOG_THOLD = 0x20
WDT_REQ_PATH = "sep_wdt_timer_rst_req"
WDT_BOUND = 200000
COOL_RESET_HOLD_REF_CYCLES = 256
POLL_CYCLES = 200


# ``sep_io_pkg::sep_io_spi_req_t`` packed layout, LSB first: (field, width).
_SPI_REQ_FIELDS = (
    ("lsio_trigger", 1),
    ("irq", 1),
    ("sd_oe", 4),
    ("sd", 4),
    ("cs_oe", 1),
    ("cs_n", 1),
    ("sck_oe", 1),
    ("sck", 1),
)


def _spi_field(handle, name: str) -> int:
    """Return one field of the packed SPI request struct."""
    value = int(handle.value)
    lsb = 0
    for field, width in _SPI_REQ_FIELDS:
        if field == name:
            return (value >> lsb) & ((1 << width) - 1)
        lsb += width
    raise KeyError(name)


class smu_sep_sba_peripheral_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """SEP mailbox, SPI host, security-disable token and watchdog from the debug bus."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"s4": False, "s5": False, "s6": False, "s7": False, "s8": False}

    def _smu(self, path: str) -> int:
        return sample(hier(smu_scope(self.dut), path), path)

    async def _settle(self, path: str, want: int, bound: int = POLL_CYCLES) -> int:
        value = self._smu(path)
        for _ in range(bound):
            if value == want:
                break
            await ClockCycles(self.dut.clk_smu_i, 1)
            value = self._smu(path)
        return value

    async def _mailboxes(self, jtag, sb) -> None:
        observed, want = {}, {}
        for mbox in range(NUM_MAILBOXES):
            base = _sep(f"AXIL_MAILBOX_OUTBOUND_MAILBOX_{mbox}_BASE_ADDR")
            await self._sb_ok(jtag, base + MBOX_WIRQT, 2, 0)
            await self._sb_ok(jtag, base + MBOX_IRQEN, 2, MBOX_WTIRQ)
            await self._sb_ok(jtag, base + MBOX_WRITE_DATA, 3, 0x0B0B_0000 | mbox)
            raised = await self._settle(MBOX_IRQ_PATH, 1 << mbox)
            await self._sb_ok(jtag, base + MBOX_CTRL, 2, MBOX_FLUSH)
            await self._sb_ok(jtag, base + MBOX_IRQS, 2, MBOX_ALL_IRQS)
            await self._sb_ok(jtag, base + MBOX_IRQEN, 2, 0)
            dropped = await self._settle(MBOX_IRQ_PATH, 0)
            observed[mbox] = (raised, dropped)
            want[mbox] = (1 << mbox, 0)
        self._log(f"CHK-SEP-MBOX-IRQ {observed}")
        sb.expect_eq("CHK-SEP-MBOX-IRQ", observed, want, evidence="CHK-SEP-MBOX-IRQ")
        self.steps["s4"] = True

    async def _spi_wait_idle(self, jtag) -> int:
        status = SPI_ACTIVE
        for _ in range(SPI_POLLS):
            _, status = await self._sb(jtag, SPI_STATUS, 2)
            if not status & SPI_ACTIVE:
                break
        return status

    async def _spi_host(self, jtag, sb) -> None:
        await self._sb_ok(jtag, SPI_CONTROL, 2, SPI_SPIEN | SPI_OUTPUT_EN | SPI_TX_WATERMARK)
        await self._sb_ok(jtag, SPI_CONFIGOPTS, 2, 1)
        await self._sb_ok(jtag, SPI_CSID, 2, 0)
        await self._sb_ok(jtag, SPI_EVENT_ENABLE, 2, SPI_EVENT_IDLE)
        await self._sb_ok(jtag, SPI_INTR_ENABLE, 2, SPI_INTR_EVENT)
        req = hier(smu_scope(self.dut), SPI_REQ_PATH)
        trigger_empty = _spi_field(req, "lsio_trigger")
        lanes = {"tx_sd": 0, "tx_oe": 0, "rx_oe": 0}
        phase = ["tx"]
        stop = [False]

        async def watch() -> None:
            while not stop[0]:
                await ClockCycles(self.dut.clk_smu_i, 1)
                oe = _spi_field(req, "sd_oe")
                if phase[0] == "tx":
                    lanes["tx_sd"] |= _spi_field(req, "sd")
                    lanes["tx_oe"] |= oe
                else:
                    lanes["rx_oe"] |= oe

        watcher = cocotb.start_soon(watch())
        for word in (0xA5A5_5A5A, 0x0F0F_F0F0):
            await self._sb_ok(jtag, SPI_TXDATA, 2, word)
            await self._sb_ok(
                jtag, SPI_COMMAND, 2, (3 << 5) | (SPI_DIR_TX << 3) | (SPI_SPEED_QUAD << 1)
            )
            await self._spi_wait_idle(jtag)
        phase[0] = "rx"
        await self._sb_ok(
            jtag, SPI_COMMAND, 2, (3 << 5) | (SPI_DIR_RX << 3) | (SPI_SPEED_QUAD << 1)
        )
        status = await self._spi_wait_idle(jtag)
        stop[0] = True
        await watcher
        seen_sd, seen_oe, oe_in_rx = lanes["tx_sd"], lanes["tx_oe"], lanes["rx_oe"]
        irq = _spi_field(req, "irq")
        await self._sb_ok(jtag, SPI_INTR_STATE, 2, SPI_INTR_EVENT)
        await self._sb_ok(jtag, SPI_INTR_ENABLE, 2, 0)
        await ClockCycles(self.dut.clk_smu_i, 16)
        irq_cleared = _spi_field(req, "irq")
        rx_lanes = await self._drive_rx_pads()
        await self._sb_ok(jtag, SPI_CONTROL, 2, 0)
        self._log(
            f"CHK-SEP-SPI-QUAD sd=0x{seen_sd:x} oe=0x{seen_oe:x} rx_oe=0x{oe_in_rx:x} "
            f"trigger_empty={trigger_empty} irq={irq}->{irq_cleared} status=0x{status:08x} "
            f"rx_lanes={rx_lanes}"
        )
        sb.expect_eq(
            "CHK-SEP-SPI-QUAD",
            (seen_sd, seen_oe, oe_in_rx, trigger_empty, irq, irq_cleared, rx_lanes),
            (0xF, 0xF, 0, 1, 1, 0, RX_PAD_PATTERNS),
            evidence="CHK-SEP-SPI-QUAD",
        )
        self.steps["s5"] = True

    async def _drive_rx_pads(self) -> list[int]:
        """Drive the four SPI data pads from the bench and read each value back."""
        dut = self.dut
        en_before = int(dut.tb_gpio_drive_en.value)
        val_before = int(dut.tb_gpio_drive_val.value)
        seen = []
        try:
            dut.tb_gpio_drive_en.value = en_before | RX_PAD_MASK
            for pattern in RX_PAD_PATTERNS:
                dut.tb_gpio_drive_val.value = (val_before & ~RX_PAD_MASK) | pattern
                await ClockCycles(dut.clk_smu_i, RX_PAD_HOLD_CYCLES)
                seen.append(self._smu(RX_PATH) & RX_PAD_MASK)
        finally:
            dut.tb_gpio_drive_en.value = en_before
            dut.tb_gpio_drive_val.value = val_before
        return seen

    async def _unused_lanes_in_cold_reset(self, sb) -> None:
        """S8: SPI lanes 4..7, DQS and the rebar loopback read their pads only in cold reset."""
        dut = self.dut
        en_before = int(dut.tb_gpio_drive_en.value)
        val_before = int(dut.tb_gpio_drive_val.value)
        dut.tb_gpio_drive_en.value = en_before | UNUSED_PAD_MASK
        dut.tb_gpio_drive_val.value = val_before | UNUSED_PAD_MASK
        await ClockCycles(dut.clk_smu_i, RX_PAD_HOLD_CYCLES)
        running = self._unused_lanes()
        dut.rst_cold_ni.value = 0
        await ClockCycles(dut.clk_ref_i, COLD_RESET_HOLD_REF_CYCLES)
        in_reset = self._unused_lanes()
        dut.rst_cold_ni.value = 1
        released = self._unused_lanes()
        for _ in range(COLD_RELEASE_POLLS):
            if released == (0, 0, 0):
                break
            await ClockCycles(dut.clk_ref_i, COLD_RESET_HOLD_REF_CYCLES)
            released = self._unused_lanes()
        dut.tb_gpio_drive_en.value = en_before
        dut.tb_gpio_drive_val.value = val_before
        observed = (running, in_reset, released)
        self._log(f"CHK-SEP-SPI-UNUSED-LANES {observed}")
        sb.expect_eq(
            "CHK-SEP-SPI-UNUSED-LANES",
            observed,
            ((0, 0, 0), (0xF, 1, 1), (0, 0, 0)),
            evidence="CHK-SEP-SPI-UNUSED-LANES",
        )
        self.steps["s8"] = True

    def _unused_lanes(self) -> tuple[int, int, int]:
        return (
            (self._smu(RX_PATH) >> 4) & 0xF,
            self._smu("sep_spi_rxds"),
            self._smu("sep_spi_mem_rebar_ipad"),
        )

    async def _security_disable(self, jtag, sb) -> None:
        observed = []
        for token in ([0] * 8, [1] + [0] * 7):
            for addr, word in zip(TOKEN_WORDS, token):
                await self._sb_ok(jtag, addr, 2, word)
            await self._sb_ok(jtag, TOKEN_EOP, 2, TOKEN_GO)
            match = 0
            for _ in range(SPI_POLLS):
                _, match = await self._sb(jtag, TOKEN_MATCH, 2)
                if match & 0x3F:
                    break
            level = await self._settle(SECURITY_DISABLE_PATH, int(token == [0] * 8))
            observed.append((match & 0x3F == TOKEN_MATCH_CODE, level))
        self._log(f"CHK-SEP-SECURITY-DISABLE {observed}")
        sb.expect_eq(
            "CHK-SEP-SECURITY-DISABLE",
            observed,
            [(True, 1), (False, 0)],
            evidence="CHK-SEP-SECURITY-DISABLE",
        )
        self.steps["s6"] = True

    async def _watchdog_bite(self, jtag, sb) -> None:
        idle = self._smu(WDT_REQ_PATH)
        await self._sb_ok(jtag, WDOG_BARK, 2, WDOG_THOLD)
        await self._sb_ok(jtag, WDOG_BITE, 2, WDOG_THOLD)
        await self._sb_ok(jtag, WDOG_COUNT, 2, 0)
        await self._sb_ok(jtag, WDOG_CTRL, 2, WDOG_ENABLE)
        bitten = await self._settle(WDT_REQ_PATH, 1, WDT_BOUND)
        dut = self.dut
        dut.tb_cool_reset_pin.value = 1
        await ClockCycles(dut.clk_ref_i, COOL_RESET_HOLD_REF_CYCLES)
        dut.tb_cool_reset_pin.value = 0
        released = await self._settle(WDT_REQ_PATH, 0, WDT_BOUND)
        self._log(f"CHK-SEP-WDT-BITE idle={idle} bitten={bitten} released={released}")
        sb.expect_eq(
            "CHK-SEP-WDT-BITE",
            (idle, bitten, released),
            (0, 1, 0),
            evidence="CHK-SEP-WDT-BITE",
        )
        self.steps["s7"] = True

    async def run(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        sb = self.test.env.scoreboard
        jtag = self.jtag
        await self._mailboxes(jtag, sb)
        await self._spi_host(jtag, sb)
        await self._security_disable(jtag, sb)
        await self._watchdog_bite(jtag, sb)
        await self._unused_lanes_in_cold_reset(sb)
