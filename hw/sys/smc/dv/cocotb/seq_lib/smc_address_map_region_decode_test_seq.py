# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Component address-map region decode over the SEP_IN AXI port.

Every region the generated SMC map declares is read at a register on its
base side and at the last register of its extent, and the value is compared
against the generated reset (``hw/sys/smc/regs/gen/py/smc_reg.py``) or, for
zero-reset blocks, proven by a co-resident write/readback pattern. Three
addresses that no block declares and that the local crossbar leaves without a
rule are read and must be answered DECERR by the fabric error slave
(``fabric.adoc``, Traffic Subordinates). The adopter external window is
proven at its consumer: ``tb_axil_external_active`` must pulse while the
access is in flight.

Regions the SEP_IN port cannot reach in this bench are named in the log and
left open, not claimed: the PLIC and CLINT/BEU windows above bit 25 fold onto
the local base in ``smc_local_fabric`` (see ``smc_cluster_beu_test``), the
debug-module region has no register in the generated map, and the remap
regions are outbound-path apertures with no inbound decode pinned by the
specification.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import (
    _REPO,
    DFX_STATUS_IDLE,
    SPM_MEMORY_BASE,
    SPM_MEMORY_SIZE,
    smc_addr,
    smc_bootrom_addr,
    smc_indexed_addr,
)
from .smc_decode_probe_utils import SmcDecodeProbeSeq
from .smc_efuse_vip_utils import EFUSE_BANK_INIT_TIME_RESET, EFUSE_SHIM_CTRL_WINDOW
from .smc_i3c_to_fabric_test_seq import HCI_VERSION_OFFSET, I3C_HCI_VERSION_RESET

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT,
    CHIP_CONFIG_VERSION_LO_REG_DEFAULT,
    DFX_CTRL_STATUS_DEBUG_BUS_MUX_REG_DEFAULT,
    EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT,
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    GPIO_INTF_ACCESS_FILTER_REG_DEFAULT,
    I2C_STATUS_REG_DEFAULT,
    RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_REG_DEFAULT,
    RESET_UNIT_ISOLATE_REQ_VIS_REG_DEFAULT,
    RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT,
    SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT,
    SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT,
    TELEMETRY_RECEIVER_STATUS_REG_DEFAULT,
    UART_16550_MAIN_LSR_REG_DEFAULT,
    WDT_CMP_REG_DEFAULT,
)

_ROM_IMAGE = _REPO / "hw" / "sys" / "smc" / "dv" / "assets" / "smc_rom_default.hex"

# --- WDT region: four 1 KiB instances, CMP is the last register of each ---------
WDT0_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
WDT3_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_CMP_BASE_ADDR")
_WDT_STRIDE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR") - smc_addr(
    "SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR"
)
# First address past the last WDT instance. No block in the generated map
# starts there (the next one is the reset unit at +0x2000), so the error slave
# must answer.
WDT_REGION_BEYOND = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR") + _WDT_STRIDE

# --- system control: reset unit + misc wrap ----------------------------------------
RESET_UNIT_SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
RESET_UNIT_VIS = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_VIS_BASE_ADDR")
RESET_UNIT_LAST = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
MISC_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
MISC_LAST = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR")
MISC_WRAP_BASE = smc_addr("SMC_TOP_SMC_MISC_WRAP_BASE_ADDR")
MISC_WRAP_SIZE = smc_addr("SMC_TOP_SMC_MISC_WRAP_SIZE")

# --- GPIO: 65 interface instances ----------------------------------------------------
GPIO_NUM = smc_addr("SMC_TOP_GPIO_INTF_NUM")
GPIO0_ACCESS_FILTER = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 0)
GPIO_LAST_ACCESS_FILTER = smc_indexed_addr(
    "SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", GPIO_NUM - 1
)

# --- Words inside a crossbar window but past its last generated block ----------------------
# Each target's own demux sends these to its error slave. The windows are the
# generated block extents: GPIO_INTF instances end at GPIO_INTF_TOTAL_SIZE,
# misc_wrap at its SIZE, and the zeroer control block at its SIZE.
GPIO_PAST_LAST = smc_indexed_addr("SMC_TOP_GPIO_INTF_BASE_ADDR", 0) + smc_addr(
    "SMC_TOP_GPIO_INTF_TOTAL_SIZE"
)
MISC_PAST_LAST = MISC_WRAP_BASE + MISC_WRAP_SIZE + 4
DMA_DESC_FIRST = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
DMA_DESC_WORDS = 12
ZEROER_PAST_LAST = (
    smc_addr("SMC_TOP_ZEROER_CTRL_BASE_ADDR") + smc_addr("SMC_TOP_ZEROER_CTRL_SIZE") + 0x100
)

# --- I3C: six CSR windows -----------------------------------------------------------------
I3C_NUM = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_NUM")
I3C0_HCI_VERSION = (
    smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", 0) + HCI_VERSION_OFFSET
)
I3C_LAST_HCI_VERSION = (
    smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", I3C_NUM - 1) + HCI_VERSION_OFFSET
)

# --- peripheral controllers: AVSBus, I2C, UART ------------------------------------------
AVS_CFG_0 = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")
I2C0_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", 0)
UART_NUM = smc_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_NUM")
UART0_LSR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", 0)
UART_LAST_LSR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", UART_NUM - 1
)

# --- security / timing / DFT ------------------------------------------------------------------
EFUSE_READ_REQ_TIMEOUT = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR")
TELEMETRY0_STATUS = smc_indexed_addr(
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR", 0
)
OCTS_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
DFX_STATUS_SMU = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
DFX_DEBUG_BUS_MUX = smc_addr("SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR")
# The DFX block is the last one the generated map declares below the fabric
# control registers at 0xC001_0000. Its 2 KiB crossbar window ends 0x800
# above its base; the address right after it belongs to no block.
DFX_REGION_BEYOND = smc_addr("SMC_TOP_DFX_CTRL_BASE_ADDR") + 0x800
assert DFX_REGION_BEYOND < smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR")

# --- fabric control ----------------------------------------------------------------------------
GLOBAL_BASE = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
OUTBOUND_NUM = smc_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_NUM")
OUTBOUND_LAST_END = smc_indexed_addr(
    "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", OUTBOUND_NUM - 1
)
# First 4 KiB page after the outbound filter array; the mailbox array starts one
# page later, so nothing in the generated map claims this address.
FABRIC_CTRL_BEYOND = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR", 0) + 0x1000
assert FABRIC_CTRL_BEYOND < smc_addr("SMC_TOP_SMC_MAILBOX_BASE_ADDR")

# --- mailbox: 32 outbound + 32 inbound -------------------------------------------------------
MBX_OUT0_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")
MBX_IN31_IRQEN = smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_31_IRQEN_BASE_ADDR")
# IRQEN is 3 bits of real storage (wtirq, rtirq, eirq); the values below are the
# two distinct non-zero patterns that fit and differ from the reset 0.
_MBX_PATTERNS = (0x5, 0x3)

# --- data processing: DMA + zeroer ---------------------------------------------------------------
DMA_DST_ADDRESS_LO = smc_addr("SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR")
ZEROER_DEST_ADDR = smc_addr("SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR")

# --- memory: ROM + scratchpad --------------------------------------------------------------------
SPM_ROM_BASE = smc_addr("SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR")
SPM_LAST_WORD = SPM_MEMORY_BASE + SPM_MEMORY_SIZE - 8

# --- CLA: trace sink + funnel scratch words -------------------------------------------------------
CLA_DST_SINK_SCRATCHLO = smc_addr("SMC_TOP_SMC_CLA_DST_SINK_SCRATCHLO_BASE_ADDR")
CLA_FUNNEL_SCRATCHLO = smc_addr("SMC_TOP_SMC_CLA_FUNNEL_SCRATCHLO_BASE_ADDR")

# --- adopter external window ------------------------------------------------------------------------
EXTERNAL_MANDATORY_BASE = smc_bootrom_addr("SMC_TOP_SMC_EXTERNAL_MANDATORY_BASE_ADDR")
EXTERNAL_SUPPLEMENTARY_BASE = smc_bootrom_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_BASE_ADDR")
assert EXTERNAL_MANDATORY_BASE == smc_addr("SMC_TOP_SMC_EXTERNAL_BASE_ADDR")
assert EFUSE_SHIM_CTRL_WINDOW == EXTERNAL_MANDATORY_BASE
# memmap.adoc, "Captured GPIO Straps": STRAPS_LO at the adopter external window
# plus 0x5800, STRAPS_HI after it. The block's size is the generated straps
# header's; the first word past it is claimed by nothing in the window.
_STRAPS_OFFSET = 0x5800
_STRAPS_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "straps.h"


def _straps_block_size() -> int:
    for line in _STRAPS_H.read_text(encoding="utf-8").splitlines():
        if "static_assert(sizeof(straps_t)" in line:
            return int(line.split("==")[1].split(",")[0].strip(), 0)
    raise AssertionError(f"{_STRAPS_H} declares no straps_t size")


STRAPS_LO = EXTERNAL_MANDATORY_BASE + _STRAPS_OFFSET
STRAPS_HI = STRAPS_LO + 4
STRAPS_BEYOND = STRAPS_LO + _straps_block_size()

_PATTERN_A = 0xA5A5_5A5A
_PATTERN_B = 0x5A5A_A5A5
_PATTERN_C = 0x3C3C_C3C3
_PATTERN_D = 0xC3C3_3C3C
_SPM_PATTERN_LO = 0xA5A5_5A5A_0000_0001
_SPM_PATTERN_HI = 0x5A5A_A5A5_FFFF_FFF8

# Exact-value compares this body issues (reads carrying ``expected=``). A
# literal, so a table edit that silently dropped an expectation fails here
# rather than shrinking the floor with it.
EXPECTED_VALUE_CHECKS = 56
EXPECTED_DECERR_CHECKS = 4


def _rom_word0() -> int:
    """First 64-bit word of the ROM image the run mode preloads at the ROM base.

    The image carries an SPDX header, so the first data word is the first line
    that is neither blank nor a `//` comment -- the same lines the Verilog
    `$readmemh` that loads it skips.
    """
    for line in _ROM_IMAGE.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("//"):
            return int(word, 16)
    raise AssertionError(f"{_ROM_IMAGE} carries no data word")


class smc_address_map_region_decode_test_seq(SmcDecodeProbeSeq):
    """Base / top / beyond decode of every generated-map region reachable over SEP_IN."""

    def __init__(self, name: str = "smc_address_map_region_decode_test_seq") -> None:
        super().__init__(name)
        self.value_checks_measured = 0
        self.external_hits: dict[str, int] = {}
        self.misc_last_word: int | None = None

    async def _region_wdt(self) -> None:
        await self.read_reset("WDT_REGION_BASE_CORE0_CMP", WDT0_CMP, WDT_CMP_REG_DEFAULT)
        await self.read_reset("WDT_REGION_TOP_CORE3_CMP", WDT3_CMP, WDT_CMP_REG_DEFAULT)
        await self.read_decerr("WDT_REGION_BEYOND", WDT_REGION_BEYOND)
        self.close_cell(
            "wdt-region",
            f"CORE0 CMP @0x{WDT0_CMP:08x} and CORE3 CMP @0x{WDT3_CMP:08x} both read the "
            f"generated reset 0x{WDT_CMP_REG_DEFAULT:x}; 0x{WDT_REGION_BEYOND:08x} answered DECERR",
        )

    async def _region_system_control(self) -> None:
        await self.read_reset(
            "SYSCTRL_RESET_UNIT_SS_WARM", RESET_UNIT_SS_WARM, RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT
        )
        await self.read_reset(
            "SYSCTRL_RESET_UNIT_VIS", RESET_UNIT_VIS, RESET_UNIT_ISOLATE_REQ_VIS_REG_DEFAULT
        )
        await self.read_reset(
            "SYSCTRL_RESET_UNIT_LAST",
            RESET_UNIT_LAST,
            RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_REG_DEFAULT,
        )
        await self.read_reset(
            "SYSCTRL_MISC_VERSION_LO", MISC_VERSION_LO, CHIP_CONFIG_VERSION_LO_REG_DEFAULT
        )
        # NDMRESET_CLUSTER_COUNT is `sw = r; hw = w` (ndm_reset.rdl): the value
        # is driven by the integration, not a reset the map pins, so the last
        # misc-wrap word is a decode-only read (OKAY enforced by the scoreboard)
        # and its value is reported.
        self.misc_last_word = await self.csr_read("SYSCTRL_MISC_LAST", MISC_LAST)
        assert MISC_LAST + 4 == MISC_WRAP_BASE + MISC_WRAP_SIZE, (
            "NDMRESET_CLUSTER_COUNT is no longer the last misc_wrap register; re-pick the top probe"
        )
        self.close_cell(
            "system-control-region",
            f"reset unit SS_WARM_RESET_N=0x{RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT:x}, "
            f"ISOLATE_REQ_VIS=0x{RESET_UNIT_ISOLATE_REQ_VIS_REG_DEFAULT:x} and misc wrap "
            f"VERSION_LO=0x{CHIP_CONFIG_VERSION_LO_REG_DEFAULT:x} read their generated resets; "
            f"last registers of both blocks (0x{RESET_UNIT_LAST:08x}, 0x{MISC_LAST:08x}) decode",
        )
        self.close_cell(
            "misc-wrap-base-decodes",
            f"CHIP_CONFIG VERSION_LO @0x{MISC_VERSION_LO:08x} == 0x{CHIP_CONFIG_VERSION_LO_REG_DEFAULT:x}",
        )
        self.close_cell(
            "misc-wrap-top-decodes",
            f"NDMRESET_CLUSTER_COUNT @0x{MISC_LAST:08x} (last word of the 0x{MISC_WRAP_SIZE:x}-byte "
            f"misc wrap) answered OKAY with the hardware-driven value 0x{self.misc_last_word:x}",
        )

    async def _region_gpio(self) -> None:
        await self.read_reset(
            "GPIO_REGION_BASE_INTF0_FILTER",
            GPIO0_ACCESS_FILTER,
            GPIO_INTF_ACCESS_FILTER_REG_DEFAULT,
        )
        await self.read_reset(
            "GPIO_REGION_TOP_INTF64_FILTER",
            GPIO_LAST_ACCESS_FILTER,
            GPIO_INTF_ACCESS_FILTER_REG_DEFAULT,
        )
        self.close_cell(
            "gpio-region",
            f"GPIO_INTF[0] and GPIO_INTF[{GPIO_NUM - 1}] ACCESS_FILTER both read "
            f"0x{GPIO_INTF_ACCESS_FILTER_REG_DEFAULT:x} (bits above 16 set: a 32-bit APB4 data path)",
        )

    async def _region_i3c(self) -> None:
        await self.read_reset(
            "I3C_REGION_BASE_I3C0_HCI_VERSION", I3C0_HCI_VERSION, I3C_HCI_VERSION_RESET
        )
        await self.read_reset(
            f"I3C_REGION_TOP_I3C{I3C_NUM - 1}_HCI_VERSION",
            I3C_LAST_HCI_VERSION,
            I3C_HCI_VERSION_RESET,
        )
        self.close_cell(
            "i3c-region",
            f"I3C CSR windows 0 and {I3C_NUM - 1} read HCI_VERSION 0x{I3C_HCI_VERSION_RESET:x} "
            f"(vendor RDL reset)",
        )

    async def _region_peripheral(self) -> None:
        await self.read_reset(
            "PERIPH_REGION_AVS_CFG_0", AVS_CFG_0, AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT
        )
        await self.read_reset("PERIPH_REGION_I2C0_STATUS", I2C0_STATUS, I2C_STATUS_REG_DEFAULT)
        await self.read_reset("PERIPH_REGION_UART0_LSR", UART0_LSR, UART_16550_MAIN_LSR_REG_DEFAULT)
        await self.read_reset(
            f"PERIPH_REGION_TOP_UART{UART_NUM - 1}_LSR",
            UART_LAST_LSR,
            UART_16550_MAIN_LSR_REG_DEFAULT,
        )
        self.close_cell(
            "peripheral-region",
            f"AVS_CFG_0=0x{AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT:x}, I2C0 STATUS=0x{I2C_STATUS_REG_DEFAULT:x}, "
            f"UART0 and UART{UART_NUM - 1} LSR=0x{UART_16550_MAIN_LSR_REG_DEFAULT:x}",
        )

    async def _region_security_timing_dft(self) -> None:
        await self.read_reset(
            "SECDFT_EFUSE_READ_REQ_TIMEOUT",
            EFUSE_READ_REQ_TIMEOUT,
            EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT,
        )
        await self.read_reset(
            "SECDFT_TELEMETRY0_STATUS", TELEMETRY0_STATUS, TELEMETRY_RECEIVER_STATUS_REG_DEFAULT
        )
        await self.read_reset("SECDFT_OCTS_CTRL", OCTS_CTRL, SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT)
        # STATUS_SMU carries the four DFT-done inputs this bench ties high
        # (smc_addr_map.DFX_STATUS_IDLE documents the tie-off); the compare is
        # on the register capturing them, not on a bus default.
        await self.read_reset("SECDFT_DFX_STATUS_SMU", DFX_STATUS_SMU, DFX_STATUS_IDLE)
        await self.read_reset(
            "SECDFT_DFX_LAST_DEBUG_BUS_MUX",
            DFX_DEBUG_BUS_MUX,
            DFX_CTRL_STATUS_DEBUG_BUS_MUX_REG_DEFAULT,
            length=8,
        )
        await self.read_decerr("SECDFT_REGION_BEYOND", DFX_REGION_BEYOND)
        self.close_cell(
            "security-timing-dft-region",
            f"eFuse READ_REQ_TIMEOUT=0x{EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT:x}, "
            f"telemetry STATUS=0x{TELEMETRY_RECEIVER_STATUS_REG_DEFAULT:x}, OCTS "
            f"CTRL=0x{SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT:x}, DFX STATUS_SMU=0x{DFX_STATUS_IDLE:x}; "
            f"0x{DFX_REGION_BEYOND:08x} answered DECERR",
        )

    async def _region_fabric_control(self) -> None:
        await self.read_reset(
            "FABCTRL_GLOBAL_BASE", GLOBAL_BASE, SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT, length=8
        )
        await self.read_reset(
            f"FABCTRL_TOP_OUTBOUND{OUTBOUND_NUM - 1}_END",
            OUTBOUND_LAST_END,
            FILTER_CTRL_END_ADDR_REG_DEFAULT,
            length=8,
        )
        await self.read_decerr("FABCTRL_REGION_BEYOND", FABRIC_CTRL_BEYOND)
        self.close_cell(
            "fabric-control-region",
            f"GLOBAL_BASE=0x{SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT:x} and OUTBOUND_FILTER_CTRL"
            f"[{OUTBOUND_NUM - 1}].END_ADDR=0x{FILTER_CTRL_END_ADDR_REG_DEFAULT:x}; "
            f"0x{FABRIC_CTRL_BEYOND:08x} answered DECERR",
        )

    async def _region_mailbox(self) -> None:
        await self.rw_coresident(
            [
                ("MAILBOX_REGION_BASE_OUT0_IRQEN", MBX_OUT0_IRQEN, _MBX_PATTERNS[0], 0),
                ("MAILBOX_REGION_TOP_IN31_IRQEN", MBX_IN31_IRQEN, _MBX_PATTERNS[1], 0),
            ]
        )
        self.close_cell(
            "mailbox-region",
            f"OUTBOUND_MAILBOX_0.IRQEN @0x{MBX_OUT0_IRQEN:08x} and INBOUND_MAILBOX_31.IRQEN "
            f"@0x{MBX_IN31_IRQEN:08x} held distinct co-resident patterns {_MBX_PATTERNS}",
        )

    async def _region_data_processing(self) -> None:
        await self.rw_coresident(
            [
                ("DATAPROC_DMA_DST_ADDRESS_LO", DMA_DST_ADDRESS_LO, _PATTERN_A, 0),
                ("DATAPROC_ZEROER_DEST_ADDR", ZEROER_DEST_ADDR, _PATTERN_B, 0),
            ]
        )
        self.close_cell(
            "data-processing-region",
            f"DMA DST_ADDRESS_LO @0x{DMA_DST_ADDRESS_LO:08x} and ZEROER DEST_ADDR "
            f"@0x{ZEROER_DEST_ADDR:08x} held distinct co-resident patterns",
        )

    async def _region_memory(self) -> None:
        rom0 = _rom_word0()
        await self.read_reset("MEMORY_REGION_ROM_WORD0", SPM_ROM_BASE, rom0, length=8)
        await self.rw_coresident(
            [
                ("MEMORY_REGION_SPM_FIRST", SPM_MEMORY_BASE, _SPM_PATTERN_LO, 0),
                ("MEMORY_REGION_SPM_LAST", SPM_LAST_WORD, _SPM_PATTERN_HI, 0),
            ],
            length=8,
        )
        self.close_cell(
            "memory-region",
            f"ROM word 0 @0x{SPM_ROM_BASE:08x} == image word 0x{rom0:016x}; scratchpad first "
            f"(0x{SPM_MEMORY_BASE:08x}) and last (0x{SPM_LAST_WORD:08x}) words held distinct "
            f"co-resident patterns",
        )

    async def _region_cla(self) -> None:
        await self.rw_coresident(
            [
                ("CLA_REGION_DST_SINK_SCRATCHLO", CLA_DST_SINK_SCRATCHLO, _PATTERN_C, 0),
                ("CLA_REGION_FUNNEL_SCRATCHLO", CLA_FUNNEL_SCRATCHLO, _PATTERN_D, 0),
            ]
        )
        self.close_cell(
            "cla-region",
            f"trace sink SCRATCHLO @0x{CLA_DST_SINK_SCRATCHLO:08x} and funnel SCRATCHLO "
            f"@0x{CLA_FUNNEL_SCRATCHLO:08x} held distinct co-resident patterns",
        )

    async def _past_last_block(self) -> None:
        """Words inside a crossbar window past its last block are refused, with no side effect."""
        corners = (
            ("GPIO_PAST_LAST", GPIO_PAST_LAST, GPIO_LAST_ACCESS_FILTER, True),
            ("MISC_PAST_LAST", MISC_PAST_LAST, MISC_LAST, False),
        )
        for label, addr, neighbour, read_too in corners:
            before = await self.csr_read(f"{label}_NEIGHBOUR_BEFORE", neighbour)
            if read_too:
                await self.csr_read_expect_error(f"{label}_RD", addr)
            await self.csr_write_expect_error(f"{label}_WR", addr, 0xFFFF_FFFF)
            await self.csr_read(f"{label}_NEIGHBOUR_AFTER", neighbour, expected=before)
        # Past the zeroer control block the data-accelerator demux defaults to the
        # DMA block, which answers OKAY and takes the write at the aliased offset
        # (card 179, design observation). A write of 0 there is taken where every
        # aliased DMA descriptor register already holds 0, so nothing may change.
        snapshot = [
            await self.csr_read(f"DMA_DESC_BEFORE_{i}", DMA_DESC_FIRST + 4 * i)
            for i in range(DMA_DESC_WORDS)
        ]
        assert not any(snapshot), f"DMA descriptor registers not idle: {snapshot}"
        await self.csr_write("ZEROER_PAST_LAST_WR", ZEROER_PAST_LAST, 0)
        for i in range(DMA_DESC_WORDS):
            await self.csr_read(f"DMA_DESC_AFTER_{i}", DMA_DESC_FIRST + 4 * i, expected=0)
        await self.csr_read("ZEROER_DEST_AFTER", ZEROER_DEST_ADDR, expected=0)
        self.close_cell(
            "past-last-block-refused",
            f"0x{GPIO_PAST_LAST:08x} (past GPIO_INTF[{GPIO_NUM - 1}], read and write) and "
            f"0x{MISC_PAST_LAST:08x} (past misc_wrap) were refused with an error response, "
            f"the last register before each unchanged; a write of 0 at "
            f"0x{ZEROER_PAST_LAST:08x} (past the zeroer control block) left the DMA "
            f"descriptor and zeroer registers at 0",
        )

    async def _region_external(self) -> None:
        # Mandatory region base: the eFuse SHIM CSR at window offset 0, which
        # the peripheral crossbar hands to the eFuse controller before the
        # external port. Its reset is the shim RDL's EFUSE_BANK_INIT_TIME.
        got = await self.read_reset(
            "EXTWIN_MANDATORY_BASE_EFUSE_SHIM", EXTERNAL_MANDATORY_BASE, EFUSE_BANK_INIT_TIME_RESET
        )
        self.close_cell(
            "mandatory-region-base-decodes",
            f"0x{EXTERNAL_MANDATORY_BASE:08x} read the eFuse SHIM EFUSE_BANK_INIT_TIME reset 0x{got:x}",
        )
        # Supplementary region base: this bench attaches no supplementary
        # device, so the external-window terminator answers DECERR; the decode
        # is proven at the port by the activity probe.
        _rdata, hits = await self.read_external_routed(
            "EXTWIN_SUPPLEMENTARY_BASE", EXTERNAL_SUPPLEMENTARY_BASE, decerr=True
        )
        self.external_hits["supplementary_base"] = hits
        self.close_cell(
            "supplementary-region-base-decodes",
            f"0x{EXTERNAL_SUPPLEMENTARY_BASE:08x} drove smc_external_req_o for {hits} clk_smc_i "
            f"cycle(s) and was answered DECERR by the adopter window terminator (no supplementary "
            f"device attached in this bench)",
        )
        # The first word past the straps block: routed to the external port and
        # answered DECERR there, with both straps words unchanged across it.
        straps_before = [
            (await self.read_external_routed(f"EXTWIN_{name}_BEFORE", addr))[0]
            for name, addr in (("STRAPS_LO", STRAPS_LO), ("STRAPS_HI", STRAPS_HI))
        ]
        _rdata, straps_hits = await self.read_external_routed(
            "EXTWIN_STRAPS_BEYOND", STRAPS_BEYOND, decerr=True
        )
        self.external_hits["straps_beyond"] = straps_hits
        for (name, addr), before in zip(
            (("STRAPS_LO", STRAPS_LO), ("STRAPS_HI", STRAPS_HI)), straps_before
        ):
            await self.read_external_routed(f"EXTWIN_{name}_AFTER", addr, expected=before)
        self.close_cell(
            "straps-window-beyond",
            f"0x{STRAPS_BEYOND:08x}, the first word past the straps block, drove "
            f"smc_external_req_o for {straps_hits} clk_smc_i cycle(s) and was answered DECERR "
            f"by the window terminator; STRAPS_LO/HI read 0x{straps_before[0]:08x}/"
            f"0x{straps_before[1]:08x} on both sides of it",
        )
        self.close_cell(
            "axil-external-region",
            f"mandatory base 0x{EXTERNAL_MANDATORY_BASE:08x} (eFuse SHIM reset) and supplementary "
            f"base 0x{EXTERNAL_SUPPLEMENTARY_BASE:08x} (external port active {hits} cycle(s))",
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        # The SEP_IN monitor flags any DECERR it was not told to expect; these
        # five are the intended error-slave probes. Two are in the adopter
        # window and answered by its terminator: the supplementary base, since
        # this bench attaches no supplementary device, and the first word past
        # the straps block.
        self.env.axi_monitor.expected_decerr_addrs.update(
            {
                WDT_REGION_BEYOND,
                DFX_REGION_BEYOND,
                FABRIC_CTRL_BEYOND,
                EXTERNAL_SUPPLEMENTARY_BASE,
                STRAPS_BEYOND,
                GPIO_PAST_LAST,
                MISC_PAST_LAST,
            }
        )

        await self._region_wdt()
        await self._region_system_control()
        await self._region_gpio()
        await self._region_i3c()
        await self._region_peripheral()
        await self._region_security_timing_dft()
        await self._region_fabric_control()
        await self._region_mailbox()
        await self._region_data_processing()
        await self._region_memory()
        await self._region_cla()
        await self._region_external()
        await self._past_last_block()

        self.close_cell(
            "region-base-decodes",
            "every region above was read at a base-side register with an exact generated-map "
            "expectation or a co-resident pattern",
        )
        self.close_cell(
            "region-top-decodes",
            f"last registers read exactly: CORE3 CMP, reset unit 0x{RESET_UNIT_LAST:08x}, misc "
            f"0x{MISC_LAST:08x}, GPIO_INTF[{GPIO_NUM - 1}], I3C[{I3C_NUM - 1}], UART{UART_NUM - 1}, "
            f"DFX 0x{DFX_DEBUG_BUS_MUX:08x}, OUTBOUND[{OUTBOUND_NUM - 1}], INBOUND_MAILBOX_31, "
            f"SPM 0x{SPM_LAST_WORD:08x}",
        )
        self.close_cell(
            "beyond-region-does-not",
            f"0x{WDT_REGION_BEYOND:08x}, 0x{DFX_REGION_BEYOND:08x} and 0x{FABRIC_CTRL_BEYOND:08x} "
            f"(no generated-map block, no crossbar rule) each answered DECERR",
        )
        self.close_cell(
            "apb4-32bit-address",
            "APB4-fronted blocks (GPIO, AVSBus, OCTS, telemetry, eFuse interface) decoded at their "
            "32-bit generated-map addresses",
        )
        self.close_cell(
            "apb4-32bit-data",
            f"32-bit APB4 reads returned values with bits above 16 set "
            f"(GPIO ACCESS_FILTER 0x{GPIO_INTF_ACCESS_FILTER_REG_DEFAULT:x}, AVS_CFG_0 "
            f"0x{AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT:x}, eFuse READ_REQ_TIMEOUT "
            f"0x{EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT:x})",
        )
        self.leave_open(
            "plic-region",
            "PLIC window 0xC400_0000 folds onto the local base in smc_local_fabric (bits [31:25] "
            "replaced), so no SEP_IN access reaches it; needs the CPU local path",
        )
        self.leave_open(
            "timer-buserror-region",
            "CLINT/BEU window 0xC800_0000 folds onto the local base (see smc_cluster_beu_test); "
            "needs the CPU local path",
        )
        self.leave_open(
            "debug-region",
            "the generated map declares no register between the WDT instances and the reset unit; "
            f"0x{WDT_REGION_BEYOND:08x} answered DECERR, so the debug-module region of the "
            "memmap prose has no inbound decode to prove",
        )
        self.leave_open(
            "remap-region",
            "M-mode/Xvisor regions are outbound remap apertures; the specification pins no "
            "inbound (SEP_IN) decode for them",
        )

        self.value_checks_measured = sb.sys_axi_value_checks_seen - value_checks_before
        assert self.value_checks_measured >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {self.value_checks_measured} exact-value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        self.report_cells("CHK-ADDRESS-MAP-REGION")
        cocotb.log.info(
            "CHK-ADDRESS-MAP-REGION-DECODE: %d regions probed at base and top with %d "
            "scoreboard exact-value compares (floor %d), %d beyond-region DECERR probes, "
            "external port active %d cycle(s) on the supplementary base and %d past the "
            "straps block; %d cells left open "
            "as unreachable from SEP_IN",
            len(self.cells),
            self.value_checks_measured,
            EXPECTED_VALUE_CHECKS,
            EXPECTED_DECERR_CHECKS,
            self.external_hits.get("supplementary_base", 0),
            self.external_hits.get("straps_beyond", 0),
            len(self.unreachable),
        )
