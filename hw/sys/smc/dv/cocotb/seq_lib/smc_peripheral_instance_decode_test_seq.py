# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Peripheral block and instance-stride decode over the SEP_IN AXI port.

Every peripheral block the generated map declares is read at a register whose
reset value is non-zero, and every multi-instance peripheral is proven at every
probed instance: single-instance blocks by their generated reset,
multi-instance ones additionally by distinct patterns written to all probed
instances before any is read back, so a stride that aliases two instances
returns a neighbour's pattern and fails. A reset read alone cannot tell N
registers from one aliased register, so the watchdog, I2C, UART and telemetry
instances each carry a co-resident pattern leg as well (the watchdog through
its KEY unlock, one key write per register write). The PVT wrapper is proven at the
adopter external port (``tb_axil_external_active`` pulses while the access is
in flight; the bench PVT model answers OKAY with zero data).

The DTP control window is not probed: ``tb_top`` leaves its AXI-Lite response
idle, so an access there would never complete. The four bus error units lie
outside the local and global apertures at the reset ``REGION_SIZE`` and answer
DECERR from SEP_IN (see ``smc_cluster_beu_test``); this leaf does not widen it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import (
    _REPO,
    DFX_STATUS_IDLE,
    gpio_intf_u32,
    reg_field_encode,
    smc_addr,
    smc_indexed_addr,
)
from .smc_decode_probe_utils import SmcDecodeProbeSeq
from .smc_efuse_vip_utils import efuse_preload_word_at
from .smc_i3c_to_fabric_test_seq import (
    HCI_VERSION_OFFSET,
    I3C_HCI_VERSION_RESET,
    _i3c_multifield_reg_from_rdl,
)

_I2C_H = _REPO / "hw" / "ip" / "i2c" / "regs" / "gen" / "c" / "i2c.h"
_TELEMETRY_RECEIVER_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT,
    CHIP_CONFIG_VERSION_LO_REG_DEFAULT,
    EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT,
    GPIO_INTF_ACCESS_FILTER_REG_DEFAULT,
    I2C_STATUS_REG_DEFAULT,
    I2C_TARGET_ID_REG_DEFAULT,
    LOG_ENGINE_LOG_REGION_SIZE_REG_DEFAULT,
    RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT,
    SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT,
    TELEMETRY_RECEIVER_INTR_ENABLE_REG_DEFAULT,
    TELEMETRY_RECEIVER_STATUS_REG_DEFAULT,
    UART_16550_MAIN_LSR_REG_DEFAULT,
    UART_16550_MAIN_SCR_REG_DEFAULT,
    WDT_CMP_REG_DEFAULT,
)

# --- I3C: six CSR windows, HCI_VERSION reset plus a per-instance RW pattern ------------
I3C_NUM = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_NUM")
_I3C_DEV_ADDR_OFFSET, _I3C_DEV_ADDR_RESET, _I3C_DEV_ADDR_MASKS = _i3c_multifield_reg_from_rdl(
    "CONTROLLER_DEVICE_ADDR"
)
_I3C_DYNAMIC_ADDR_MASK = _I3C_DEV_ADDR_MASKS["DYNAMIC_ADDR"]
_I3C_DYNAMIC_ADDR_LSB = (_I3C_DYNAMIC_ADDR_MASK & -_I3C_DYNAMIC_ADDR_MASK).bit_length() - 1


def _i3c_csr(idx: int, offset: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_BASE_ADDR", idx) + offset


def _i3c_dynamic_addr_pattern(idx: int) -> int:
    """Distinct dynamic address per instance; DYNAMIC_ADDR_VALID stays clear."""
    value = ((0x21 + idx) << _I3C_DYNAMIC_ADDR_LSB) & _I3C_DYNAMIC_ADDR_MASK
    assert value, f"I3C dynamic-address pattern for instance {idx} is empty"
    return (_I3C_DEV_ADDR_RESET & ~_I3C_DYNAMIC_ADDR_MASK) | value


# --- GPIO: instances 0 and 64 ------------------------------------------------------------------
GPIO_NUM = smc_addr("SMC_TOP_GPIO_INTF_NUM")
GPIO_STRIDE = smc_addr("SMC_TOP_GPIO_INTF_STRIDE")
# ACCESS_FILTER's two *PROT_REQUIREMENT fields are plain storage and take
# effect only while the matching filter-enable bit is set, which stays 0 here.
# DATA_CTRL is not used: its lsio_enable/pad2core bits are hardware-driven and
# differ per wrap. Positions come from the generated gpio_intf.h.
_GPIO_AWPROT_BP = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_bp")
_GPIO_ARPROT_BP = gpio_intf_u32("GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bp")
_GPIO_PATTERNS = (
    (2 << _GPIO_AWPROT_BP) | (2 << _GPIO_ARPROT_BP),
    (4 << _GPIO_AWPROT_BP) | (4 << _GPIO_ARPROT_BP),
)

# --- mailbox: pairs 0 and 31, IRQEN is 3 bits of real storage ---------------------------------
_MBX = {
    "OUT0": smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR"),
    "IN0": smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_IRQEN_BASE_ADDR"),
    "OUT31": smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_31_IRQEN_BASE_ADDR"),
    "IN31": smc_addr("SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_31_IRQEN_BASE_ADDR"),
}
_MBX_PATTERNS = {"OUT0": 0x1, "IN0": 0x2, "OUT31": 0x4, "IN31": 0x7}

# --- log engines: four instances, LOG_REGION_SIZE is a 20-bit RW field -----------------------
LOGENG_NUM = smc_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_NUM")
_LOGENG_PATTERNS = (0xA0001, 0xB0002, 0xC0003, 0xD0004)
assert all(p < (1 << 20) for p in _LOGENG_PATTERNS)

# --- watchdogs: four cores, CMP behind the KEY unlock -----------------------------------------
# wdt.rdl KEY: "Magic key (0x51F15E) must be written to this register before a
# write to any other register in this addrmap. Must be written every time."
# CMP.wdogcmp0 is 16 bits of plain rw storage (reset 0x1000); the patterns stay
# inside it and differ from the reset and from each other.
WDT_NUM = 4
WDT_KEY_MAGIC = 0x51F15E
_WDT_CMP_PATTERNS = (0x1100, 0x1200, 0x1300, 0x1400)
assert all(p < (1 << 16) and p != WDT_CMP_REG_DEFAULT for p in _WDT_CMP_PATTERNS)
# --- I2C: three controllers, TARGET_ID is plain rw storage ------------------------------------
_I2C_TARGET_ID_RESET = I2C_TARGET_ID_REG_DEFAULT
# --- UART: four wraps, SCR is the 8-bit scratch register --------------------------------------
_UART_SCR_PATTERNS = (0xA1, 0xB2, 0xC3, 0xD4)
_UART_SCR_RESET = UART_16550_MAIN_SCR_REG_DEFAULT
# --- telemetry: three receivers, INTR_ENABLE holds two plain rw bits --------------------------
_TELEMETRY_INTR_ENABLE_RESET = TELEMETRY_RECEIVER_INTR_ENABLE_REG_DEFAULT
# --- single-instance blocks with a non-zero generated reset -----------------------------------
AVS_CFG_0 = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_CFG_0_BASE_ADDR")
I2C_NUM = smc_addr("SMC_TOP_SMC_I2C_WRAP_I2C_NUM")
UART_NUM = smc_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_NUM")
EFUSE_MAP_LOCKS = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
EFUSE_READ_REQ_TIMEOUT = smc_addr("SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR")
TELEMETRY_NUM = smc_addr("SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_NUM")
OCTS_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
DFX_STATUS_SMU = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
RESET_UNIT_SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
MISC_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
CLA_DST_SINK_SCRATCHLO = smc_addr("SMC_TOP_SMC_CLA_DST_SINK_SCRATCHLO_BASE_ADDR")
CLA_FUNNEL_SCRATCHLO = smc_addr("SMC_TOP_SMC_CLA_FUNNEL_SCRATCHLO_BASE_ADDR")
PVT_WRAP_BASE = smc_addr("SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_SMC_PVT_WRAP_BASE_ADDR")
# The bench PVT model (hw/sys/smc/dv/models/pvt_wrap.sv) answers every access
# OKAY with all-zero data; the decode proof is the external-port activity.
PVT_MODEL_RDATA = 0

_CLA_PATTERNS = (0x3C3C_C3C3, 0xC3C3_3C3C)

# One word past the middle of each aperture, well beyond the unit's decoded
# extent (smc_addr.h *_SIZE) and inside its aperture (smc.rdl ocah_aperture_size).
WDT0_BASE = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR")
WDT_DECODED_EXTENT = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_SIZE")
WDT0_PAST_EXTENT = WDT0_BASE + 0x200
assert WDT_DECODED_EXTENT < 0x200 < 0x400
WDT0_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR")
CPU_CTRL_BASE = smc_addr("SMC_TOP_SMC_CPU_CTRL_BASE_ADDR")
CPU_CTRL_DECODED_EXTENT = smc_addr("SMC_TOP_SMC_CPU_CTRL_SIZE")
CPU_CTRL_PAST_EXTENT = CPU_CTRL_BASE + 0x800
assert CPU_CTRL_DECODED_EXTENT < 0x800 < 0x1000

# Literal floors: exact-value compares and total accesses the body issues.
EXPECTED_VALUE_CHECKS = 93
EXPECTED_ACCESSES = 169


class smc_peripheral_instance_decode_test_seq(SmcDecodeProbeSeq):
    """Block decode plus first/last-instance stride decode for every peripheral."""

    def __init__(self, name: str = "smc_peripheral_instance_decode_test_seq") -> None:
        super().__init__(name)
        self.value_checks_measured = 0
        self.pvt_external_hits = 0

    async def _i3c_instances(self) -> None:
        for idx in range(I3C_NUM):
            await self.read_reset(
                f"I3C{idx}_HCI_VERSION", _i3c_csr(idx, HCI_VERSION_OFFSET), I3C_HCI_VERSION_RESET
            )
        await self.rw_coresident(
            [
                (
                    f"I3C{idx}_CONTROLLER_DEVICE_ADDR",
                    _i3c_csr(idx, _I3C_DEV_ADDR_OFFSET),
                    _i3c_dynamic_addr_pattern(idx),
                    _I3C_DEV_ADDR_RESET,
                )
                for idx in range(I3C_NUM)
            ]
        )
        self.close_cell(
            "i3c-decode",
            f"all {I3C_NUM} I3C CSR windows read HCI_VERSION 0x{I3C_HCI_VERSION_RESET:x}",
        )
        self.close_cell(
            "i3c-instance-0",
            f"I3C0 CONTROLLER_DEVICE_ADDR held 0x{_i3c_dynamic_addr_pattern(0):08x} co-resident",
        )
        self.close_cell(
            f"i3c-instance-{I3C_NUM - 1}",
            f"I3C{I3C_NUM - 1} CONTROLLER_DEVICE_ADDR held "
            f"0x{_i3c_dynamic_addr_pattern(I3C_NUM - 1):08x} co-resident",
        )
        self.close_cell(
            f"i3c-count-{I3C_NUM}",
            f"{I3C_NUM} distinct CONTROLLER_DEVICE_ADDR patterns were simultaneously resident, one "
            f"per configured instance",
        )

    async def _gpio_instances(self) -> None:
        first = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", 0)
        last = smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", GPIO_NUM - 1)
        assert last - first == (GPIO_NUM - 1) * GPIO_STRIDE
        await self.rw_coresident(
            [
                (
                    "GPIO_INTF0_ACCESS_FILTER",
                    first,
                    _GPIO_PATTERNS[0],
                    GPIO_INTF_ACCESS_FILTER_REG_DEFAULT,
                ),
                (
                    f"GPIO_INTF{GPIO_NUM - 1}_ACCESS_FILTER",
                    last,
                    _GPIO_PATTERNS[1],
                    GPIO_INTF_ACCESS_FILTER_REG_DEFAULT,
                ),
            ]
        )
        self.close_cell(
            "gpio-interface-decode",
            f"GPIO_INTF[0] @0x{first:08x} and GPIO_INTF[{GPIO_NUM - 1}] @0x{last:08x} "
            f"(stride 0x{GPIO_STRIDE:x}) held distinct co-resident ACCESS_FILTER patterns and "
            f"restored to 0x{GPIO_INTF_ACCESS_FILTER_REG_DEFAULT:x}",
        )
        self.close_cell(
            "gpio-instance-0", f"ACCESS_FILTER pattern 0x{_GPIO_PATTERNS[0]:08x} at instance 0"
        )
        self.close_cell(
            f"gpio-instance-{GPIO_NUM - 1}",
            f"ACCESS_FILTER pattern 0x{_GPIO_PATTERNS[1]:08x} at instance {GPIO_NUM - 1}",
        )

    async def _mailbox_pairs(self) -> None:
        await self.rw_coresident(
            [
                (f"MAILBOX_{k}_IRQEN", _MBX[k], _MBX_PATTERNS[k], 0)
                for k in ("OUT0", "IN0", "OUT31", "IN31")
            ]
        )
        self.close_cell(
            "mailbox-pair-0",
            f"outbound/inbound mailbox 0 IRQEN held {_MBX_PATTERNS['OUT0']}/{_MBX_PATTERNS['IN0']}",
        )
        self.close_cell(
            "mailbox-pair-31",
            f"outbound/inbound mailbox 31 IRQEN held {_MBX_PATTERNS['OUT31']}/{_MBX_PATTERNS['IN31']}",
        )

    async def _wdt_write_unlocked(self, label: str, core: int, value: int) -> None:
        """One KEY write then one CMP write: the lock re-engages after every write."""
        await self.csr_write(
            f"WDT{core}_KEY_{label}",
            smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_KEY_BASE_ADDR"),
            WDT_KEY_MAGIC,
        )
        await self.csr_write(
            f"WDT{core}_CMP_{label}",
            smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_CMP_BASE_ADDR"),
            value,
        )

    async def _wdt_instances(self) -> None:
        cmp_addrs = [
            smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_CMP_BASE_ADDR") for core in range(WDT_NUM)
        ]
        for core, addr in enumerate(cmp_addrs):
            await self.read_reset(f"WDT{core}_CMP", addr, WDT_CMP_REG_DEFAULT)
        # Co-resident patterns through the KEY unlock: every CMP is written
        # before any is read back, so an aliased pair holds the last pattern
        # written and the first readback of the pair fails.
        for core in range(WDT_NUM):
            await self._wdt_write_unlocked("PATTERN", core, _WDT_CMP_PATTERNS[core])
        for core, addr in enumerate(cmp_addrs):
            await self.csr_read(f"WDT{core}_CMP_PATTERN_RB", addr, expected=_WDT_CMP_PATTERNS[core])
        for core in range(WDT_NUM):
            await self._wdt_write_unlocked("RESTORE", core, WDT_CMP_REG_DEFAULT)
        for core, addr in enumerate(cmp_addrs):
            await self.csr_read(f"WDT{core}_CMP_RESTORE_RB", addr, expected=WDT_CMP_REG_DEFAULT)
        self.close_cell(
            "wdt-instance-3",
            f"CLUSTER_CORE0..3_WDT.CMP each read 0x{WDT_CMP_REG_DEFAULT:x}, then held "
            f"{', '.join(f'{p:#x}' for p in _WDT_CMP_PATTERNS)} co-resident (KEY-unlocked "
            f"writes) and read back the reset after the restore",
        )

    async def _log_engines(self) -> None:
        await self.rw_coresident(
            [
                (
                    f"LOG_ENGINE{idx}_LOG_REGION_SIZE",
                    smc_indexed_addr(
                        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR",
                        idx,
                    ),
                    _LOGENG_PATTERNS[idx],
                    LOG_ENGINE_LOG_REGION_SIZE_REG_DEFAULT,
                )
                for idx in range(LOGENG_NUM)
            ]
        )
        self.close_cell(
            "logengine-instance-0", f"LOG_ENGINE0 LOG_REGION_SIZE held 0x{_LOGENG_PATTERNS[0]:x}"
        )
        self.close_cell(
            f"logengine-instance-{LOGENG_NUM - 1}",
            f"LOG_ENGINE{LOGENG_NUM - 1} LOG_REGION_SIZE held 0x{_LOGENG_PATTERNS[LOGENG_NUM - 1]:x}",
        )

    async def _single_blocks(self) -> None:
        await self.read_reset("AVSBUS_CFG_0", AVS_CFG_0, AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT)
        self.close_cell(
            "avsbus-decode", f"AVS_CFG_0 == 0x{AVSBUS_CONTROLLER_AVS_CFG_0_REG_DEFAULT:x}"
        )
        for idx in range(I2C_NUM):
            await self.read_reset(
                f"I2C{idx}_STATUS",
                smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR", idx),
                I2C_STATUS_REG_DEFAULT,
            )
        await self.rw_coresident(
            [
                (
                    f"I2C{idx}_TARGET_ID",
                    smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR", idx),
                    reg_field_encode(_I2C_H, "I2C", "TARGET_ID", address0=0x21 + idx, mask0=0x7F),
                    _I2C_TARGET_ID_RESET,
                )
                for idx in range(I2C_NUM)
            ]
        )
        self.close_cell(
            "i2c-decode",
            f"I2C 0..{I2C_NUM - 1} STATUS == 0x{I2C_STATUS_REG_DEFAULT:x}, and each TARGET_ID "
            f"held its own address pattern co-resident with the other two",
        )
        for idx in range(UART_NUM):
            await self.read_reset(
                f"UART{idx}_LSR",
                smc_indexed_addr(
                    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", idx
                ),
                UART_16550_MAIN_LSR_REG_DEFAULT,
            )
        await self.rw_coresident(
            [
                (
                    f"UART{idx}_SCR",
                    smc_indexed_addr(
                        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR", idx
                    ),
                    _UART_SCR_PATTERNS[idx],
                    _UART_SCR_RESET,
                )
                for idx in range(UART_NUM)
            ]
        )
        self.close_cell(
            "uart-decode",
            f"UART 0..{UART_NUM - 1} LSR == 0x{UART_16550_MAIN_LSR_REG_DEFAULT:x}, and each SCR "
            f"held its own pattern co-resident with the other three",
        )
        locks = efuse_preload_word_at(EFUSE_MAP_LOCKS)
        await self.read_reset("EFUSE_MAP_LOCKS_LO", EFUSE_MAP_LOCKS, locks)
        self.close_cell("efuse-map-decode", f"LOCKS[31:0] == preload image word 0x{locks:08x}")
        await self.read_reset(
            "EFUSE_INTERFACE_READ_REQ_TIMEOUT",
            EFUSE_READ_REQ_TIMEOUT,
            EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT,
        )
        self.close_cell(
            "efuse-interface-decode",
            f"READ_REQ_TIMEOUT == 0x{EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT:x}",
        )
        for idx in range(TELEMETRY_NUM):
            await self.read_reset(
                f"TELEMETRY{idx}_STATUS",
                smc_indexed_addr(
                    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_STATUS_BASE_ADDR", idx
                ),
                TELEMETRY_RECEIVER_STATUS_REG_DEFAULT,
            )
        # INTR_ENABLE has two rw bits (MISSING_LAST, BUFFER_THRESHOLD); the three
        # non-zero combinations give one distinct pattern per receiver.
        telemetry_patterns = [
            reg_field_encode(_TELEMETRY_RECEIVER_H, "TELEMETRY_RECEIVER", "INTR_ENABLE", **fields)
            for fields in (
                {"missing_last": 1},
                {"buffer_threshold": 1},
                {"missing_last": 1, "buffer_threshold": 1},
            )
        ]
        assert TELEMETRY_NUM == len(telemetry_patterns)
        await self.rw_coresident(
            [
                (
                    f"TELEMETRY{idx}_INTR_ENABLE",
                    smc_indexed_addr(
                        "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_INTR_ENABLE_BASE_ADDR",
                        idx,
                    ),
                    telemetry_patterns[idx],
                    _TELEMETRY_INTR_ENABLE_RESET,
                )
                for idx in range(TELEMETRY_NUM)
            ]
        )
        self.close_cell(
            "telemetry-decode",
            f"receivers 0..{TELEMETRY_NUM - 1} STATUS == "
            f"0x{TELEMETRY_RECEIVER_STATUS_REG_DEFAULT:x}, and each INTR_ENABLE held its own "
            f"pattern co-resident with the other two",
        )
        await self.read_reset("OCTS_CTRL", OCTS_CTRL, SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT)
        self.close_cell("octs-decode", f"OCTS CTRL == 0x{SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT:x}")
        await self.read_reset("DFX_STATUS_SMU", DFX_STATUS_SMU, DFX_STATUS_IDLE)
        self.close_cell(
            "dfx-status-decode",
            f"STATUS_SMU == 0x{DFX_STATUS_IDLE:x} (the four DFT-done inputs the bench ties high)",
        )
        await self.read_reset(
            "RESET_UNIT_SS_WARM", RESET_UNIT_SS_WARM, RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT
        )
        self.close_cell(
            "reset-unit-decode", f"SS_WARM_RESET_N == 0x{RESET_UNIT_SS_WARM_RESET_N_REG_DEFAULT:x}"
        )
        await self.read_reset(
            "MISC_VERSION_LO", MISC_VERSION_LO, CHIP_CONFIG_VERSION_LO_REG_DEFAULT
        )
        self.close_cell(
            "misc-wrap-decode", f"VERSION_LO == 0x{CHIP_CONFIG_VERSION_LO_REG_DEFAULT:x}"
        )
        await self.rw_coresident(
            [
                ("CLA_DST_SINK_SCRATCHLO", CLA_DST_SINK_SCRATCHLO, _CLA_PATTERNS[0], 0),
                ("CLA_FUNNEL_SCRATCHLO", CLA_FUNNEL_SCRATCHLO, _CLA_PATTERNS[1], 0),
            ]
        )
        self.close_cell(
            "cla-decode", "trace sink and funnel SCRATCHLO held distinct co-resident patterns"
        )

    async def _pvt_wrapper(self) -> None:
        rdata, hits = await self.read_external_routed(
            "PVT_WRAP_BASE", PVT_WRAP_BASE, expected=PVT_MODEL_RDATA
        )
        self.pvt_external_hits = hits
        evidence = (
            f"0x{PVT_WRAP_BASE:08x} was presented on smc_external_req_o as a read request for "
            f"{hits} clk_smc_i cycle(s) and the "
            f"bench PVT model answered OKAY 0x{rdata:08x}"
        )
        # One cell for one measurement: closing a second name on the same
        # routed read would inflate the printed cell count.
        self.close_cell("pvt-wrapper-decodes", evidence)

    async def _past_decoded_extent(self) -> None:
        """Offsets inside a unit's aperture but past its decoded extent are refused.

        memmap.adoc (Address Space Organization): the fabric refuses an address
        past a unit's decoded extent. The watchdog and CPU-control windows are
        the units in their layout regions whose extent ends well short of the
        aperture; a read and a write past each must answer an error, and the
        unit's last decoded register must keep its value across them.
        """
        monitor = getattr(self.env, "axi_monitor", None)
        for label, addr, live, restore in (
            ("WDT0_PAST_EXTENT", WDT0_PAST_EXTENT, WDT0_CMP, WDT_CMP_REG_DEFAULT),
            ("CPU_CTRL_PAST_EXTENT", CPU_CTRL_PAST_EXTENT, None, None),
        ):
            if monitor is not None:
                monitor.expected_decerr_addrs.add(addr)
            await self.csr_read_expect_error(f"{label}_RD", addr)
            await self.csr_write_expect_error(f"{label}_WR", addr, 0xFFFF_FFFF)
            if live is not None:
                await self.csr_read(f"{label}_LIVE_AFTER", live, expected=restore)
        self.close_cell(
            "past-decoded-extent-refused",
            f"reads and writes at 0x{WDT0_PAST_EXTENT:08x} (past the core 0 watchdog's "
            f"0x{WDT_DECODED_EXTENT:x}-byte extent) and 0x{CPU_CTRL_PAST_EXTENT:08x} (past "
            f"smc_cpu_ctrl's 0x{CPU_CTRL_DECODED_EXTENT:x}-byte extent) answered an error, and "
            f"WDT0 CMP still read 0x{WDT_CMP_REG_DEFAULT:x}",
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen

        await self._i3c_instances()
        await self._gpio_instances()
        await self._mailbox_pairs()
        await self._wdt_instances()
        await self._log_engines()
        await self._single_blocks()
        await self._pvt_wrapper()
        await self._past_decoded_extent()

        self.leave_open(
            "dtp-ctrl-decode",
            "tb_top ties axil_dtp_csr_resp to zero (no responder), so an access into the DTP "
            "control window would never complete",
        )
        self.leave_open(
            "beu-instance-3",
            "the BEU window 0xC801_x000 lies outside the local and global apertures at the reset "
            "REGION_SIZE and answers DECERR, so no SEP_IN access here reaches a bus error unit",
        )

        self.value_checks_measured = sb.sys_axi_value_checks_seen - value_checks_before
        assert self.value_checks_measured >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {self.value_checks_measured} exact-value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        self.assert_all_reachable(EXPECTED_ACCESSES, "PERIPHERAL_INSTANCE_DECODE")
        self.report_cells("CHK-PERIPHERAL-INSTANCE")
        cocotb.log.info(
            "CHK-PERIPHERAL-INSTANCE-DECODE: %d cells closed with %d scoreboard exact-value "
            "compares (floor %d) over %d SEP_IN accesses; PVT external port active %d cycle(s); "
            "%d cells left open",
            len(self.cells),
            self.value_checks_measured,
            EXPECTED_VALUE_CHECKS,
            self.accesses,
            self.pvt_external_hits,
            len(self.unreachable),
        )
