# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Constants for the dual-SMC OCCP unsecure-boot flow.

Every value here is a contract with firmware or RTL elsewhere in the tree, named
at its definition. Nothing is invented for the convenience of the test.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import cocotb

# Generated PeakRDL map, same hookup as the single-instance cocotb tree.
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
    SMC_CPU_CTRL_SCRATCH_5__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_6__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_7__REG_ADDR,
    SMC_CPU_CTRL_SCRATCH_8__REG_ADDR,
)

# --------------------------------------------------------------------------
# CPU control: reset vectors and the release sequence
# --------------------------------------------------------------------------
CPU_CTRL_RESET_VECTOR = (
    SMC_CPU_CTRL_RESET_VECTOR_0__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_1__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_2__REG_ADDR,
    SMC_CPU_CTRL_RESET_VECTOR_3__REG_ADDR,
)
CPU_CTRL_RESET_CTRL = SMC_CPU_CTRL_RESET_CTRL_REG_ADDR
CPU_CTRL_RESET_TIMEOUT = SMC_CPU_CTRL_RESET_TIMEOUT_REG_ADDR

# ROM window base; both images in this flow are entered from ROM.
CPU_RESET_VECTOR_ROM = CPU_CTRL_RESET_VECTOR_REG_DEFAULT & 0xFFFF_FFFF
CPU_RESET_CTRL_DEFAULT = CPU_CTRL_RESET_CTRL_REG_DEFAULT & 0xFFFF_FFFF
# Hold all four cores in reset while bit 8 keeps the uncore out of it. Same
# value as smc_cpu_vip_utils.CPU_RESET_CTRL_HOLD_CORES.
#
# Not usable for staging over AXI: the cluster boundary only opens when every
# core is out of reset, so holding any core leaves the boundary isolated and AXI
# into the scratch window never answers at all.
CPU_RESET_CTRL_HOLD_CORES = 0x0000_0100
# timeout_mode=1 so the reset is force-applied if the cluster never drains
# (same value smc_cpu_vip_utils.CPU_RESET_TIMEOUT_FORCE uses).
CPU_RESET_TIMEOUT_FORCE = 0x0001_0020

# --------------------------------------------------------------------------
# Scratch registers
# --------------------------------------------------------------------------
# Target side. Index 0/1 are the ROM's SIM pass-fail and POST code
# (hw/sys/smc/bootrom/prod/lib/include/smc_scratchpad.h).
SCRATCH_PASS_FAIL = SMC_CPU_CTRL_SCRATCH_0__REG_ADDR
SCRATCH_POST_CODE = SMC_CPU_CTRL_SCRATCH_1__REG_ADDR

# Controller side, the firmware RNG seed (SEED_REG in the DV firmware's
# smc_test.h). init_test() loads it into the LFSR at the start of main(), so it
# has to be written before the controller's cores are released.
#
# Leaving it 0 is not neutral: 0 is a fixed point of that LFSR, so every
# get_random_int() returns 0 forever. That pins two protocol choices for the
# whole run -- no body CRC on any OCCP WRITE, and I3C channel 0 every time,
# leaving channels 1 and 3 wired in the testbench but never exercised.
SCRATCH_FW_SEED = SMC_CPU_CTRL_SCRATCH_3__REG_ADDR

# Controller side: the OCCP unsecure-boot host protocol, read by the DV
# occp_unsecure_boot_test firmware.
SCRATCH_BOOTCODE_ADDR = SMC_CPU_CTRL_SCRATCH_5__REG_ADDR
SCRATCH_BOOTCODE_SIZE = SMC_CPU_CTRL_SCRATCH_6__REG_ADDR
SCRATCH_TARGET_ADDR = SMC_CPU_CTRL_SCRATCH_7__REG_ADDR
SCRATCH_ENTRY_OFFSET = SMC_CPU_CTRL_SCRATCH_8__REG_ADDR

# Proof that the transferred image ran rests on the target's scratch 0, which is
# the same source the reference environment uses. Nothing else in this flow can
# write it: the transferred payload's whole body is test_pass(0), and the
# production boot ROM's own scratch pass/fail setter has no call sites anywhere
# in the tree. The test also asserts scratch 0 does not already hold TEST_PASS
# before the transfer, and separately requires the target's retired PC to land
# inside the transferred image.
#
# TEST_PASS comes from the DV firmware's smc_test.h, and is the same value the
# production ROM calls SMC_SCRATCHPAD_SIM_PASS_CODE.
TEST_PASS = 0xACAF_ACA1
TEST_FAIL = 0xFFFF_FFFF

# --------------------------------------------------------------------------
# Memory map
# --------------------------------------------------------------------------
# Physical SRAM base (SMC_SRAM_BASE in smc_rom_defs.h) and the start of the
# OCCP-writable window (SMC_SRAM_BASE_ADDR = SMC_ROM_STACK_END). The production
# ROM rejects OCCP writes below the latter.
SMC_SRAM_BASE = 0xC006_0000
OCCP_SRAM_BASE = 0xC006_6400

# --------------------------------------------------------------------------
# Pads
# --------------------------------------------------------------------------
# SMC_STATUS_GPIO. The controller firmware's wait_for_target_up_gpio() spins on
# this pad forever from inside initialize_interface(), which runs before scratch
# 5-8 are read. Holding it low is therefore the testbench's only lever for
# "controller running, but not yet looking at the host protocol", which is
# exactly the window the payload has to be staged in: staging needs all four
# cores out of reset (see CPU_RESET_CTRL_HOLD_CORES) yet must complete before the
# firmware reads scratch 5-8.
#
# In normal operation the TARGET drives this pad from set_gpio_status() on the
# success path of its OCCP init. The dual top resolves the undriven value low,
# so a target that never asserts readiness leaves the controller waiting, as it
# would in silicon.
CTRL_TARGET_READY_PAD = 58

# Upper bound of the standardised OCCP test window, from the firmware's own
# occp_test_common.h.
OCCP_SRAM_UPPER = 0xC016_0000

# Floor for staging inside the CONTROLLER's SRAM. Unlike the target address,
# this one cannot use the whole window: it has to clear the controller image's
# own .data/.bss/stack, or the payload would be overwritten by the firmware that
# is supposed to read it. The image's symbol map puts the top of its stack at
# 0xC0070E30, rounded up here to the next 4 KB.
#
# The reference environment stages from the bottom of the full window,
# overlapping that region.
BFM_STAGING_FLOOR = 0xC007_1000


def pick_payload_addresses(seed: int, payload_size: int) -> tuple[int, int]:
    """Draw this run's staging and target addresses, 8-byte aligned.

    A fixed target address of OCCP_SRAM_BASE -- which is also SMC_ROM_STACK_END,
    the first address the ROM will accept -- makes two behaviours
    indistinguishable: a ROM that reads the OCCP WRITE command's address field,
    and a ROM that ignores it and always writes from the bottom of the window.
    Drawing the address per run is what tells them apart.

    The transferred image does not have to be linked at the address it lands on.
    The JUMP enters `main`, which is position independent: it materialises both
    the scratch address and TEST_PASS from immediates and parks in a relative
    branch. Only crt0 would care about the link base, and the JUMP skips it.

    Deterministic in `seed` so a failure is reproducible from the run's log.
    """
    rng = random.Random(seed)

    def draw(low: int, high: int) -> int:
        top = high - payload_size
        if top < low:
            raise AssertionError(
                f"payload of {payload_size} bytes does not fit in [{low:#x}, {high:#x})"
            )
        return rng.randint(low, top) & ~0x7

    # Target: the whole OCCP-writable window. This is the address under test.
    target = draw(OCCP_SRAM_BASE, OCCP_SRAM_UPPER)
    # Controller: above its own image (see BFM_STAGING_FLOOR).
    staging = draw(BFM_STAGING_FLOOR, OCCP_SRAM_UPPER)
    return staging, target


# --------------------------------------------------------------------------
# POST code (target boot ROM progress); see smc_post_code.h.
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Shared I3C channels wired between the two instances, in the order the
# SMC_DUAL half of tb_top.sv lists them in SharedI3cIdx. Both firmware halves
# select from exactly this set.
# --------------------------------------------------------------------------
SHARED_I3C_CHANNELS = (0, 1, 3)


# --------------------------------------------------------------------------
# Helpers shared by every dual-instance OCCP test.
# --------------------------------------------------------------------------
def required_plusarg(name: str, test_name: str) -> str:
    """Fetch a mandatory plusarg, or fail with which test needed it."""
    value = cocotb.plusargs.get(name)
    if value is None:
        raise AssertionError(f"{test_name} requires +{name}=")
    return str(value)


def bus_activity(dut) -> list[tuple[int, int, int]]:
    """(channel, scl_falls, starts) for each cross-wired I3C channel.

    Flat scalars, not an unpacked-array handle: cocotb reads every element of
    the latter as element 0, which silently mis-attributes every per-channel
    count. The instance number comes from the TB too (tb_i3c_channel_id_N), so
    the label cannot drift from what is being counted -- do not substitute
    SHARED_I3C_CHANNELS here, which would reintroduce that drift.
    """
    return [
        (
            int(getattr(dut, f"tb_i3c_channel_id_{pos}").value),
            int(getattr(dut, f"tb_i3c_scl_fall_count_{pos}").value),
            int(getattr(dut, f"tb_i3c_start_count_{pos}").value),
        )
        for pos in range(len(SHARED_I3C_CHANNELS))
    ]


def format_activity(activity) -> str:
    return ", ".join(
        f"I3C{ch}: scl_falls={falls} starts={starts}" for ch, falls, starts in activity
    )
