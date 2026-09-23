# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Constants and helpers shared by the dual-SMC OCCP cocotb tests."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import cocotb

# The generated register map is not an installed package.
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    CPU_CTRL_RESET_CTRL_REG_DEFAULT,
    CPU_CTRL_RESET_VECTOR_REG_DEFAULT,
    SMC_CPU_CTRL_RESET_CTRL_REG_ADDR,
    SMC_CPU_CTRL_RESET_TIMEOUT_REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_1__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_2__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_3__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_1__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_3__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_4__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_5__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_6__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_7__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_8__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_9__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_10__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_11__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_12__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_13__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_15__REG_ADDR,
)

CPU_CTRL_RESET_VECTOR = (
    SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_1__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_2__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_3__REG_ADDR,
)
CPU_CTRL_RESET_CTRL = SMC_CPU_CTRL_RESET_CTRL_REG_ADDR
CPU_CTRL_RESET_TIMEOUT = SMC_CPU_CTRL_RESET_TIMEOUT_REG_ADDR

CPU_RESET_VECTOR_ROM = CPU_CTRL_RESET_VECTOR_REG_DEFAULT & 0xFFFF_FFFF
CPU_RESET_CTRL_DEFAULT = CPU_CTRL_RESET_CTRL_REG_DEFAULT & 0xFFFF_FFFF
# Holds all four cores; AXI into the scratch window never answers while any core is held.
CPU_RESET_CTRL_HOLD_CORES = 0x0000_0100
CPU_RESET_TIMEOUT_FORCE = 0x0001_0020

# Pulsing core reset is the only way to relatch RESET_VECTOR once boot_stall is low.
CPU_RESET_CTRL_PULSE_CORES = 0x0000_00F0

SCRATCH_PASS_FAIL = SMC_CPU_CTRL_SCRATCH_0__REG_ADDR
SCRATCH_POST_CODE = SMC_CPU_CTRL_SCRATCH_1__REG_ADDR

# Write before releasing the cores; 0 is an LFSR fixed point that pins every random choice.
SCRATCH_FW_SEED = SMC_CPU_CTRL_SCRATCH_3__REG_ADDR

SCRATCH_BOOTCODE_ADDR = SMC_CPU_CTRL_SCRATCH_5__REG_ADDR
SCRATCH_BOOTCODE_SIZE = SMC_CPU_CTRL_SCRATCH_6__REG_ADDR
SCRATCH_TARGET_ADDR = SMC_CPU_CTRL_SCRATCH_7__REG_ADDR
SCRATCH_ENTRY_OFFSET = SMC_CPU_CTRL_SCRATCH_8__REG_ADDR

# The status buffer address is an offset from SMC_SRAM_BASE, not an absolute address.
SCRATCH_STATUS_TO_SEP = SMC_CPU_CTRL_SCRATCH_9__REG_ADDR
SCRATCH_STATUS_BUFFER_ADDR = SMC_CPU_CTRL_SCRATCH_11__REG_ADDR

# Controller only: on the target these two indices carry ROM status.
SCRATCH_SEP_RB_READY = SMC_CPU_CTRL_SCRATCH_10__REG_ADDR
SCRATCH_SEP_RB_COUNT = SMC_CPU_CTRL_SCRATCH_12__REG_ADDR

# Firmware sets this around GET_SEP_STATUS; leave the shadow buffer alone while it is set.
SCRATCH_SEP_RB_GUARD = SMC_CPU_CTRL_SCRATCH_13__REG_ADDR

# Controller only: the two OCCP I2C target addresses, one byte per channel in channel order.
SCRATCH_I2C_TARGET_IDS = SMC_CPU_CTRL_SCRATCH_4__REG_ADDR

# Target side: write the entry offset first; the controller proceeds once the base is non-zero.
SCRATCH_JUMP_BASE = SMC_CPU_CTRL_SCRATCH_4__REG_ADDR
SCRATCH_JUMP_ENTRY_OFFSET = SMC_CPU_CTRL_SCRATCH_5__REG_ADDR

# The ROM echoes the manifest address as an offset from SMC_SRAM_BASE, not absolute.
SCRATCH_MANIFEST_ADDR = SMC_CPU_CTRL_SCRATCH_8__REG_ADDR
SEP_STATUS_MANIFEST_READY_BIT = 1

SCRATCH_MBIST_STATUS = SMC_CPU_CTRL_SCRATCH_15__REG_ADDR

# Also the ROM's SIM pass code; the pass proof holds only while the payload alone writes it.
TEST_PASS = 0xACAF_ACA1
TEST_FAIL = 0xFFFF_FFFF

# The ROM rejects OCCP writes below OCCP_SRAM_BASE.
SMC_SRAM_BASE = 0xC006_0000
OCCP_SRAM_BASE = 0xC006_6400

# Controller firmware waits on this pad before reading scratch 5-8; low holds it off.
CTRL_TARGET_READY_PAD = 58

STRAP_BOOT_I2C = 18
STRAP_PRIMARY_CHIPLET = 25
# Keyed by plusarg name; BOOT_I2C is controller-only and handled separately.
STRAP_BITS = {
    "MEM_REPAIR_BYPASS": 13,
    "TEST_EN": 14,
    "BOOT_RECOVERY": 19,
    "BL0_PLLCLK": 20,
    "STATUS_RPT_DISABLE": 21,
    "SPI_USE_FUSED_CONFIG": 22,
    "SRAM_AUTO_ZERO_DISABLE": 26,
    "MEM_BIST_BYPASS": 54,
    "ROTATE_UPDATE": 58,
}

STRAP_CHIP_ID_BITS = (23, 15, 12, 11)

I2C_ADDR_MIN = 0x08
I2C_ADDR_MAX = 0x77
I2C_ADDR_FALLBACK = 0x55


def chip_id_straps(chip_id: int) -> int:
    value = 0
    for bit, gpio in enumerate(STRAP_CHIP_ID_BITS):
        if (chip_id >> bit) & 1:
            value |= 1 << gpio
    return value


# Valid only while the target's eFuse I2C address slot is unprogrammed.
def occp_i2c_address(chip_id: int, chip_config_id: int = 0) -> int:
    addr = (chip_id & 0xF) | ((chip_config_id & 0x3) << 5)
    if addr < I2C_ADDR_MIN or addr > I2C_ADDR_MAX:
        return I2C_ADDR_FALLBACK
    return addr


STRAPS_LO_ADDR = 0xC040_5800
STRAPS_HI_ADDR = 0xC040_5804
STRAPS_LO_BIT_COUNT = 32


def strap_reg_addr(bit: int) -> tuple[int, int]:
    if bit < STRAPS_LO_BIT_COUNT:
        return STRAPS_LO_ADDR, bit
    return STRAPS_HI_ADDR, bit - STRAPS_LO_BIT_COUNT


OCCP_SRAM_UPPER = 0xC016_0000

# Must clear the controller image's .data/.bss/stack, or the firmware overwrites the payload.
BFM_STAGING_FLOOR = 0xC007_1000


def pick_payload_addresses(seed: int, payload_size: int) -> tuple[int, int]:
    rng = random.Random(seed)

    def draw(low: int, high: int) -> int:
        top = high - payload_size
        if top < low:
            raise AssertionError(
                f"payload of {payload_size} bytes does not fit in [{low:#x}, {high:#x})"
            )
        return rng.randint(low, top) & ~0x7

    # The payload's main() must be position independent: the target address varies per run.
    target = draw(OCCP_SRAM_BASE, OCCP_SRAM_UPPER)
    staging = draw(BFM_STAGING_FLOOR, OCCP_SRAM_UPPER)
    return staging, target


POST_CODE_BOOT_PHASE_SHIFT = 28
POST_CODE_BOOT_PHASE_MASK = 0xF
POST_CODE_ERROR_SHIFT = 16
POST_CODE_ERROR_MASK = 0xF

POST_CODE_BOOT_PHASE_OCCP_PROC = 0x5
POST_CODE_BOOT_PHASE_ERROR = 0x7

POST_CODE_BOOT_PHASE_NAMES = {
    0x0: "INIT",
    0x1: "STRAP_FUSE",
    0x2: "SRAM_SETUP",
    0x3: "IFACE_CONFIG",
    0x4: "OCCP_READY",
    0x5: "OCCP_PROC",
    0x6: "BOOT_COMPLETE",
    0x7: "ERROR",
}

POST_CODE_ERROR_NAMES = {
    0x0: "NONE",
    0x1: "SRAM",
    0x2: "INTERFACE",
    0x3: "COMMAND",
    0x4: "ACCESS",
    0x5: "INVALID_SEC_MODE",
}


def post_code_boot_phase(word: int) -> int:
    return (word >> POST_CODE_BOOT_PHASE_SHIFT) & POST_CODE_BOOT_PHASE_MASK


def post_code_error(word: int) -> int:
    return (word >> POST_CODE_ERROR_SHIFT) & POST_CODE_ERROR_MASK


def describe_post_code(word: int) -> str:
    phase = post_code_boot_phase(word)
    err = post_code_error(word)
    return (
        f"{word:#010x} phase={POST_CODE_BOOT_PHASE_NAMES.get(phase, hex(phase))} "
        f"err={POST_CODE_ERROR_NAMES.get(err, hex(err))}"
    )


# I3C channels the dual top cross-wires; must match the testbench wiring.
SHARED_I3C_CHANNELS = (0, 1, 3)


# The JUMP enters main(), not _enter: rerunning crt0 would corrupt the live boot ROM's state.
PAYLOAD_ENTRY_SYMBOL = "main"
# Must be the ELF entry point, i.e. byte 0 of the .bin.
PAYLOAD_LOAD_SYMBOL = "_enter"


def payload_entry_offset(sym_path: str) -> int:
    addrs: dict[str, int] = {}
    # Expects `nm -B -n` lines: "<addr> <type> <name>".
    for line in Path(sym_path).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in (PAYLOAD_ENTRY_SYMBOL, PAYLOAD_LOAD_SYMBOL):
            addrs[parts[2]] = int(parts[0], 16)
    for want in (PAYLOAD_LOAD_SYMBOL, PAYLOAD_ENTRY_SYMBOL):
        if want not in addrs:
            raise AssertionError(
                f"no {want} symbol in {sym_path}; cannot derive the OCCP JUMP entry offset"
            )
    offset = addrs[PAYLOAD_ENTRY_SYMBOL] - addrs[PAYLOAD_LOAD_SYMBOL]
    if offset < 0:
        raise AssertionError(
            f"{PAYLOAD_ENTRY_SYMBOL} ({addrs[PAYLOAD_ENTRY_SYMBOL]:#x}) is below "
            f"{PAYLOAD_LOAD_SYMBOL} ({addrs[PAYLOAD_LOAD_SYMBOL]:#x}); the entry "
            "point is not inside the image"
        )
    return offset


def required_plusarg(name: str, test_name: str) -> str:
    value = cocotb.plusargs.get(name)
    if value is None:
        raise AssertionError(f"{test_name} requires +{name}=")
    return str(value)


def bus_activity(dut) -> list[tuple[int, int, int]]:
    # Flat scalars: cocotb reads every unpacked-array element as element 0.
    return [
        (
            # Label from the TB, not SHARED_I3C_CHANNELS, so it matches what was counted.
            int(getattr(dut, f"tb_i3c_channel_id_{pos}").value),
            int(getattr(dut, f"tb_i3c_scl_fall_count_{pos}").value),
            int(getattr(dut, f"tb_i3c_start_count_{pos}").value),
        )
        for pos in range(len(SHARED_I3C_CHANNELS))
    ]


# The I2C channels the dual top cross-wires, in the order their counters appear.
SHARED_I2C_CHANNELS = (0, 1)


def i2c_bus_activity(dut) -> list[tuple[int, int, int]]:
    return [
        (
            ch,
            int(getattr(dut, f"tb_i2c_scl_fall_count_{pos}").value),
            int(getattr(dut, f"tb_i2c_start_count_{pos}").value),
        )
        for pos, ch in enumerate(SHARED_I2C_CHANNELS)
    ]


def format_activity(activity, i2c=None) -> str:
    parts = [f"I3C{ch}: scl_falls={falls} starts={starts}" for ch, falls, starts in activity]
    if i2c is not None:
        parts += [f"I2C{ch}: scl_falls={falls} starts={starts}" for ch, falls, starts in i2c]
    return ", ".join(parts)
