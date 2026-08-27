# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Constants for the dual-SMC OCCP unsecure-boot flow.

Every value here is a contract with something else in the tree, cited at its
definition. Nothing is invented for the convenience of the test.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

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
# NOT usable for staging over AXI, which is the obvious thing to try. The
# cluster boundary only opens when EVERY core is out of reset --
# smc_4core_cpu.sv:162, cluster_boundary_ready = init_mem_complete &
# (&rst_core_ni) & rst_uncore_ni -- so holding any core leaves the boundary
# isolated and AXI into the scratch window simply never answers. Measured: the
# first 64-byte chunk timed out after 20 us with the cores held this way.
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

# Controller side, the firmware RNG seed. SEED_REG in fw/include/smc_test.h:22;
# init_test() loads it into _RANDOM_LFSR
# (:121-123) at the very start of main(), so it has to be written BEFORE the
# controller's cores are released.
#
# Leaving it 0 is not neutral: 0 is a fixed point of the LFSR at smc_test.h:138-142
# (bit = (0^0^0^0)&1 = 0, next = (0>>1)|(0<<31) = 0), so every get_random_int()
# returns 0 forever. Measured consequence before this was seeded: all 15 OCCP
# WRITEs carried no body CRC, and the controller picked I3C channel 0 every run,
# leaving channels 1 and 3 wired in the testbench but never exercised.
SCRATCH_FW_SEED = SMC_CPU_CTRL_SCRATCH_3__REG_ADDR

# Controller side: the OCCP unsecure-boot host protocol. Read by
# hw/sys/smc/dv/fw/tests/occp_unsecure_boot_test/main.c:35-40.
SCRATCH_BOOTCODE_ADDR = SMC_CPU_CTRL_SCRATCH_5__REG_ADDR
SCRATCH_BOOTCODE_SIZE = SMC_CPU_CTRL_SCRATCH_6__REG_ADDR
SCRATCH_TARGET_ADDR = SMC_CPU_CTRL_SCRATCH_7__REG_ADDR
SCRATCH_ENTRY_OFFSET = SMC_CPU_CTRL_SCRATCH_8__REG_ADDR

# Proof that the transferred image ran rests on the target's scratch 0 alone,
# which is the same source the reference environment uses. That is not a weak
# check here:
#   * the transferred payload's whole body is test_pass(0) -> scratch 0
#     (hw/sys/smc/dv/fw/tests/hello_world/hello_world.c:11);
#   * the production boot ROM never writes it -- smc_scratchpad_set_sim_pass_fail
#     (bootrom/prod/lib/src/smc_scratchpad.c:117) has zero call sites in the
#     whole tree, and SMC_BOOT_SUCCESS is never stored to scratch either;
#   * the test asserts scratch 0 is not already TEST_PASS before the transfer;
#   * and it independently requires the target's retired PC to land inside the
#     transferred image, which the reference does not check at all.
#
# TEST_PASS from hw/sys/smc/dv/fw/include/smc_test.h, and the same value the
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
# SMC_STATUS_GPIO. The controller firmware spins on this forever before it
# touches the host protocol -- wait_for_target_up_gpio() in
# fw/common/occp/occp_interfaces.c:79-87 loops while pad2core == 0, from inside
# initialize_interface(), which runs before scratch 5-8 are read. Holding it low
# is therefore the testbench's only lever for "controller running, but not yet
# looking at the host protocol", which is exactly the window the payload has to
# be staged in: staging needs all four cores out of reset (see
# CPU_RESET_CTRL_HOLD_CORES) yet must complete before the firmware reads
# scratch 5-8.
#
# In normal operation the TARGET drives this pad, from set_gpio_status() on the
# success path of its OCCP init (bootrom/prod/lib/src/occp.c:259-279 -- by pad
# number, not via the SMC_STATUS_GPIO macro, which is why that macro looks
# unused). tb_top_dual.sv resolves the undriven value LOW, so a target that
# never asserts readiness leaves the controller waiting, as it would in silicon.
CTRL_TARGET_READY_PAD = 58

# Upper bound of the standardised OCCP test window, from the firmware's own
# header (fw/common/occp/occp_test_common.h:51,53 -- same two values the
# reference environment uses in its smc_defines.py).
OCCP_SRAM_UPPER = 0xC016_0000

# Floor for staging inside the CONTROLLER's SRAM. Unlike the target address,
# this one cannot use the whole window: it has to clear the controller image's
# own .data/.bss/stack, or the payload would be overwritten by the firmware that
# is supposed to read it.
#
# Measured from occp_unsecure_boot_test.rom.sym:
#   metal_segment_bss_target_end = 0xC006FE30
#   _sp                          = 0xC0070E30   (__stack_size = 0x1000)
# so the image occupies up to 0xC0070E30. Rounded up to the next 4 KB.
#
# Note the reference environment draws its staging address from the full window
# starting at 0xC0066400 (smc_rom_test_master_bfm_binary_loader.py:46-48), which
# overlaps that region. Deliberate deviation, not an oversight.
BFM_STAGING_FLOOR = 0xC007_1000

def pick_payload_addresses(seed: int, payload_size: int) -> tuple[int, int]:
    """Draw this run's staging and target addresses, 8-byte aligned.

    Both were compile-time constants until 2026-08-24, and the target one was
    OCCP_SRAM_BASE exactly -- which is also SMC_ROM_STACK_END, the first address
    the ROM will accept. That made two behaviours indistinguishable: a ROM that
    reads the OCCP WRITE command's address field, and a ROM that ignores it and
    always writes from the bottom of the window. Drawing the address per run is
    what tells them apart, and it is what the reference environment does
    (smc_rom_test_master_bfm_binary_loader.py:46-48, :55-57).

    The transferred image does not have to be linked at the address it lands on:
    the JUMP enters `main`, which is position independent (it materialises both
    the scratch address and TEST_PASS from immediates and parks in a relative
    branch -- see hello_world.sram.dis). Only crt0 would care about the link
    base, and the JUMP deliberately skips it.

    Deterministic in `seed` so a failure is reproducible from the run's log.
    """
    rng = random.Random(seed)

    def draw(low: int, high: int) -> int:
        top = high - payload_size
        if top < low:
            raise AssertionError(
                f"payload of {payload_size} bytes does not fit in "
                f"[{low:#x}, {high:#x})"
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
# Shared I3C channels wired between the two instances, in the order
# tb_top_dual.sv's SharedI3cIdx lists them. Both firmware halves select from
# exactly this set.
# --------------------------------------------------------------------------
SHARED_I3C_CHANNELS = (0, 1, 3)
