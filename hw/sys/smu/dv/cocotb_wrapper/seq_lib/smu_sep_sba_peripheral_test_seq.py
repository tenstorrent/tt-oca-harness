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
S5: the SEP SPI host (``spi_host.hjson``, ``hw/sys/sep/doc/spi.adoc``). With
    the host enabled and its output driven, a quad-speed transmit of four
    bytes drives every data lane and its output enable, and a quad-speed
    receive, which completes with the host idle, leaves the enables low. With
    EVENT_ENABLE.IDLE set, INTR_STATE.SPI_EVENT follows the idle event and
    the interrupt line is high while INTR_ENABLE.SPI_EVENT is set; a write to
    INTR_STATE.SPI_EVENT, which the RDL makes read-only, leaves both high,
    and clearing EVENT_ENABLE.IDLE drops both (``spi.adoc``: SPI_EVENT
    "follows the level of the events selected by EVENT_ENABLE").
    The LSIO trigger level with the TX FIFO empty, and the values GPIO pads
    0..3 return on the SPI receive lanes, are recorded: no specification
    states when the trigger rises or assigns the SEP SPI a pad.
S6: the security-disable token (``hw/sys/sep/doc/security_disable.adoc``).
    The bench binds the SHA-256 of the all-zero token as the SEP's expected
    digest (``tb_wrapper_top.sv``), so writing that token and its GO strobe
    reports the match code in SEC_DISABLE_TOKEN_MATCH and raises the SEP
    security-disable output; a token one bit off then reports the mismatch
    code (``efuse_mmr.rdl``: "Match = 6'b010101, Mismatch = 6'b101010"). The
    one security-disable net is read at the SEP eFuse controller that drives
    it, the SMU wire and the SMC input before the token, where all three are 0, and after
    the match, where all three are 1, so the net is shown to carry both values
    from the SEP into the SMC. The security-disable level after the mismatch
    is recorded: no specification states whether a mismatch withdraws an
    earlier match.
S7: the SEP watchdog (OpenTitan ``aon_timer``). With WDOG_CTRL.enable set and a
    small bite threshold, the watchdog bites and requests a reset ("A bite
    triggers a reset", ``aon_timer.hjson``). The request level after the cool
    reset pin is held is recorded: no specification states what clears it.
S8: the bench drives GPIO pads 4..7, 10 and 54 high while the chip runs, in
    cold reset and after it, and records what SPI receive lanes 4..7, DQS and
    the rebar loopback read. The GPIO pin table assigns those pads to the SMC
    SPI (``doc/integrator/meta/ocah_gpio_table.adoc``), no specification
    states what the SEP lanes read from them, and a GPIO pad's receiver is
    enabled while cold reset is asserted (``hw/ip/gpio/doc/memmap.adoc``).
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
_OT_REGS = _REPO_ROOT / "vendor" / "lowRISC" / "opentitan" / "overlay" / "regs"
_SPI_H = _OT_REGS / "spi_controller" / "regs" / "gen" / "c" / "spi_controller.h"
_AON_H = _OT_REGS / "aon_timer" / "regs" / "gen" / "c" / "aon_timer.h"


def _sep(symbol: str) -> int:
    return c_header_u32(_SEP_ADDR_H, f"OCH_SEP_TOP_{symbol}")


def _spi(symbol: str) -> int:
    return c_header_u32(_SPI_H, f"SPI_CONTROLLER__{symbol}")


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
SPI_TXDATA = _indexed_addr("OCH_SEP_TOP_SPI_CONTROLLER_TXDATA_BASE_ADDR", 0)
SPI_SPIEN = _spi("CONTROL__SPIEN_bm")
SPI_OUTPUT_EN = _spi("CONTROL__OUTPUT_EN_bm")
SPI_TX_WATERMARK = 4 << _spi("CONTROL__TX_WATERMARK_bp")
SPI_ACTIVE = _spi("STATUS__ACTIVE_bm")
SPI_EVENT_IDLE = _spi("EVENT_ENABLE__IDLE_bm")
SPI_INTR_EVENT = _spi("INTR_STATE__SPI_EVENT_bm")
SPI_LEN_SHIFT = _spi("COMMAND__LEN_bp")
SPI_DIRECTION_SHIFT = _spi("COMMAND__DIRECTION_bp")
SPI_SPEED_SHIFT = _spi("COMMAND__SPEED_bp")
# spi_host.hjson COMMAND encodings.
SPI_SPEED_QUAD = 2
SPI_DIR_RX = 1
SPI_DIR_TX = 2
SPI_REQ_PATH = "sep_io_spi_req"
RX_PATH = "sep_spi_rxd"
RX_PAD_MASK = 0xF
RX_PAD_PATTERNS = [0xF, 0x0, 0x5, 0xA, 0x0]
RX_PAD_HOLD_CYCLES = 256
# GPIO pads 4..7, 10 and 54, the SMC SPI DATA[7:4], DQS and DQS loopback rows of
# the GPIO pin table.
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
TOKEN_STATUS_MASK = c_header_u32(_MMR_H, "EFUSE_MMR__TOKEN_MATCH__TOKEN_MATCH_STATUS_bm")
# efuse_mmr.rdl SEC_DISABLE_TOKEN_MATCH: "Match = 6'b010101, Mismatch = 6'b101010".
TOKEN_MATCH_CODE = 0b010101
TOKEN_MISMATCH_CODE = 0b101010
SECURITY_DISABLE_PATH = "sep_security_disable"
SECURITY_DISABLE_SMC_PATH = "u_smc.sep_security_disable_i"
SECURITY_DISABLE_SEP_PATH = (
    "gen_sep.u_sep.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.security_disable_o"
)

WDOG_CTRL = _sep("WDT_TIMER_WDOG_CTRL_BASE_ADDR")
WDOG_BARK = _sep("WDT_TIMER_WDOG_BARK_THOLD_BASE_ADDR")
WDOG_BITE = _sep("WDT_TIMER_WDOG_BITE_THOLD_BASE_ADDR")
WDOG_COUNT = _sep("WDT_TIMER_WDOG_COUNT_BASE_ADDR")
WDOG_ENABLE = c_header_u32(_AON_H, "AON_TIMER__WDOG_CTRL__ENABLE_bm")
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

    async def _read_ok(self, jtag, addr: int) -> int:
        err, value = await self._sb(jtag, addr, 2)
        if err:
            raise AssertionError(f"system-bus read 0x{addr:08x}: sberror={err}")
        return value

    async def _spi_wait_idle(self, jtag) -> bool:
        for _ in range(SPI_POLLS):
            if not await self._read_ok(jtag, SPI_STATUS) & SPI_ACTIVE:
                return True
        return False

    @staticmethod
    def _command(direction: int) -> int:
        return (
            (3 << SPI_LEN_SHIFT)
            | (direction << SPI_DIRECTION_SHIFT)
            | (SPI_SPEED_QUAD << SPI_SPEED_SHIFT)
        )

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
        idle = []
        for word in (0xA5A5_5A5A, 0x0F0F_F0F0):
            await self._sb_ok(jtag, SPI_TXDATA, 2, word)
            await self._sb_ok(jtag, SPI_COMMAND, 2, self._command(SPI_DIR_TX))
            idle.append(await self._spi_wait_idle(jtag))
        phase[0] = "rx"
        await self._sb_ok(jtag, SPI_COMMAND, 2, self._command(SPI_DIR_RX))
        idle.append(await self._spi_wait_idle(jtag))
        stop[0] = True
        await watcher
        seen_sd, seen_oe, oe_in_rx = lanes["tx_sd"], lanes["tx_oe"], lanes["rx_oe"]
        intr = []
        intr.append((await self._read_ok(jtag, SPI_INTR_STATE), _spi_field(req, "irq")))
        await self._sb_ok(jtag, SPI_INTR_STATE, 2, SPI_INTR_EVENT)
        await ClockCycles(self.dut.clk_smu_i, 16)
        intr.append((await self._read_ok(jtag, SPI_INTR_STATE), _spi_field(req, "irq")))
        await self._sb_ok(jtag, SPI_EVENT_ENABLE, 2, 0)
        await ClockCycles(self.dut.clk_smu_i, 16)
        intr.append((await self._read_ok(jtag, SPI_INTR_STATE), _spi_field(req, "irq")))
        await self._sb_ok(jtag, SPI_INTR_ENABLE, 2, 0)
        intr = [(state & SPI_INTR_EVENT, irq) for state, irq in intr]
        rx_lanes = await self._drive_rx_pads()
        await self._sb_ok(jtag, SPI_CONTROL, 2, 0)
        self._log(
            f"CHK-SEP-SPI-QUAD sd=0x{seen_sd:x} oe=0x{seen_oe:x} rx_oe=0x{oe_in_rx:x} "
            f"idle={idle} intr_state_irq={intr}"
        )
        self._log(f"OBSERVATION SEP SPI trigger_empty={trigger_empty} rx_lanes={rx_lanes}")
        sb.expect_eq(
            "CHK-SEP-SPI-QUAD",
            (seen_sd, seen_oe, oe_in_rx, idle, intr),
            (
                0xF,
                0xF,
                0,
                [True, True, True],
                [(SPI_INTR_EVENT, 1), (SPI_INTR_EVENT, 1), (0, 0)],
            ),
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
        """S8: record what SPI lanes 4..7, DQS and the rebar loopback read across cold reset."""
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
            if released == running:
                break
            await ClockCycles(dut.clk_ref_i, COLD_RESET_HOLD_REF_CYCLES)
            released = self._unused_lanes()
        dut.tb_gpio_drive_en.value = en_before
        dut.tb_gpio_drive_val.value = val_before
        self._log(
            f"OBSERVATION SEP SPI unused lanes running={running} "
            f"in_cold_reset={in_reset} released={released}"
        )
        self.steps["s8"] = True

    def _unused_lanes(self) -> tuple[int, int, int]:
        return (
            (self._smu(RX_PATH) >> 4) & 0xF,
            self._smu("sep_spi_rxds"),
            self._smu("sep_spi_mem_rebar_ipad"),
        )

    def _security_disable_net(self) -> tuple[int, int, int]:
        """(SMU wire, SMC input, SEP eFuse controller output) of the security-disable net."""
        return (
            self._smu(SECURITY_DISABLE_PATH),
            self._smu(SECURITY_DISABLE_SMC_PATH),
            self._smu(SECURITY_DISABLE_SEP_PATH),
        )

    async def _security_disable(self, jtag, sb) -> None:
        observed, levels = [], []
        net = [self._security_disable_net()]
        for token in ([0] * 8, [1] + [0] * 7):
            for addr, word in zip(TOKEN_WORDS, token):
                await self._sb_ok(jtag, addr, 2, word)
            await self._sb_ok(jtag, TOKEN_EOP, 2, TOKEN_GO)
            status = 0
            for _ in range(SPI_POLLS):
                status = await self._read_ok(jtag, TOKEN_MATCH) & TOKEN_STATUS_MASK
                if status:
                    break
            levels.append(await self._settle(SECURITY_DISABLE_PATH, int(token == [0] * 8)))
            observed.append(status)
            if len(net) == 1:
                net.append(self._security_disable_net())
        self._log(
            f"security disable status={observed} level_after_match={levels[0]} "
            f"net (wire, smc, sep) before/after the match={net}"
        )
        self._log(f"OBSERVATION security disable level after the mismatch={levels[1]}")
        sb.expect_eq(
            "CHK-SEP-SECURITY-DISABLE",
            (observed, levels[0], net),
            ([TOKEN_MATCH_CODE, TOKEN_MISMATCH_CODE], 1, [(0, 0, 0), (1, 1, 1)]),
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
        self._log(f"CHK-SEP-WDT-BITE idle={idle} bitten={bitten}")
        self._log(f"OBSERVATION SEP watchdog request after the cool reset={released}")
        sb.expect_eq(
            "CHK-SEP-WDT-BITE",
            (idle, bitten),
            (0, 1),
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
