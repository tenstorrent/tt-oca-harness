/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP-side interface for accessing SMC resources.
//
// SEP accesses SMC through the outbound AXI path.  The base address is fixed
// at 0x40000000 — the sep_local_axi_xbar routes [0x40000000, 0xC0000000) to
// sep_system_peripherals which forwards to the SMC via the output fabric.
//
// IMPORTANT: SEP must NOT include SMC-internal headers (e.g. smc_rom_defs.h).
// The constants here define the SEP↔SMC *interface contract* — register
// offsets and bit-field positions that both sides agree on.

#pragma once

#include <stdint.h>

#include "rom_mmio.h"
#include "rom_virt_console.h"
#include "sep.h"

// ---------------------------------------------------------------------------
// SMC base address (fixed in crossbar configuration)
// ---------------------------------------------------------------------------

// SMC global base address as seen by SEP CPU.
// The xbar routes [0x40000000, 0xC0000000) to sep_system_peripherals
// (external_smu port), which forwards to SMC via the output fabric.
#define SEP_SMC_GLOBAL_BASE 0x40000000u

static inline uint32_t sep_get_smc_base(void) {
    return SEP_SMC_GLOBAL_BASE;
}

// ---------------------------------------------------------------------------
// SMC register offsets (relative to SMC base)
// ---------------------------------------------------------------------------

// Latched strap values (32-bit LO + 32-bit HI). Live in the smc_external_supplementary window
#define SMC_STRAPS_LO_OFFSET 0x404800u
#define SMC_STRAPS_HI_OFFSET 0x404804u

// CPU_CTRL scratch registers (64-bit stride: index * 8).
//
// 0x39080 is SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR (smc_addr.h), 0xC0039080
// SMC-local, 16 entries of 8 bytes (SMC_CPU_CTRL_SCRATCH_NUM = 0x10) -- exactly
// the shape the index<<3 accessor below assumes, up to the highest index used
// (15, MEM_REPAIR_STATUS).
//
// Was 0x10100, which is unmapped in this design: it falls in the gap between
// SMC_BASE_CONFIG (ends 0xC001004C) and SMC_ALIAS_REMAP (0xC0012000). Every
// scratch access -- post code, virtual console, the manifest-address and
// status-to-SEP handshake, the MBIST failure publication -- therefore went to a
// hole. DV could not see it: the testbench models the SMC as a flat axi_sim_mem
// seeded at whatever address the ROM reads, so any offset "works" in simulation.
#define SMC_SCRATCH_BASE_OFFSET 0x39080u

// Chip config block (VERSION_LO/HI, CHIP_ID, LC_STATE).
#define SMC_CHIP_ID_OFFSET 0x2908u

// SMC fuse map — chiplet/package ID for usage constraints ([S23]).
// 8 × 32-bit words each. SEP reads via AXI: smc_base + offset.
//
// 0x7008 / 0x7028 are SMC_TOP_SMC_EFUSE_MAP_CHIPLET_ID / _PACKAGE_ID
// (smc_addr.h), 0xC0007008 / 0xC0007028 SMC-local, inside SMC_EFUSE_MAP at
// 0xC0007000.
//
// Were 0xB008 / 0xB028, which are unmapped here: that range lies between
// DTP_CTRL_REG (0xC000B000) and DFX_CTRL (0xC000B800). Note the low 12 bits were
// already right -- only the block base moved, 0xB000 -> 0x7000 -- which is the
// same shape of drift as the DFX register below.
#define SMC_FUSE_MAP_CHIPLET_ID_OFFSET 0x7008u
#define SMC_FUSE_MAP_PACKAGE_ID_OFFSET 0x7028u
#define SMC_LC_STATE_OFFSET 0x290Cu

// SMC SRAM (SPM memory).
#define SMC_SRAM_OFFSET 0x60000u
#define SMC_SRAM_SIZE_BYTES 0x100000u // 1 MiB

// DFX_CTRL_STATUS_SMU register — memory repair + MBIST status (merged into single register).
//
// 0xB800 is SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR (smc_addr.h), 0xC000B800
// SMC-local, the first register of the DFX_CTRL block (base 0xC000B800,
// size 0x18: STATUS_SMU, DEBUG_CTRL at +8, DEBUG_BUS_MUX at +0x10).
//
// Was 0xF800, unmapped in this design -- the gap between DFX_CTRL_DEBUG_BUS_MUX
// (0xC000B810) and SMC_BASE_CONFIG (0xC0010000). The pre-C boot gate in vector.S
// reads this register and fails closed, so on real silicon an unmapped read
// returning 0 would halt every boot with mem_repair_success clear.
//
// A SEP->SMC address remap cannot account for the difference: output_remap.sv
// substitutes only bits [55:IdxStart] and passes [IdxStart-1:0] through
// unchanged, with IdxStart = 19 (sep_pkg.sv, 512 KB granularity). Both 0xF800
// and 0xB800 lie inside those preserved low bits.
#define SMC_DFX_CTRL_STATUS_SMU_OFFSET 0xB800u

// DFX_CTRL_STATUS bitfield (same for SOC and SEP_SMC views).
#define DFT_STATUS_MEM_REPAIR_DONE_BIT 0
#define DFT_STATUS_MEM_REPAIR_SUCCESS_BIT 1
#define DFT_STATUS_MEM_REPAIR_ABORT_BIT 2
#define DFT_STATUS_MEM_REPAIR_DONE_MASK (1u << 0)
#define DFT_STATUS_MEM_REPAIR_SUCCESS_MASK (1u << 1)
#define DFT_STATUS_MEM_REPAIR_ABORT_MASK (1u << 2)

// ---------------------------------------------------------------------------
// Strap bit definitions (SEP↔SMC interface contract)
// ---------------------------------------------------------------------------

// STRAPS_LO (GPIO 0-31, bit index == GPIO index):
#define SMC_STRAP_MEM_REPAIR_BYPASS_BIT 13
#define SMC_STRAP_BOOT_RECOVERY_BIT 19
#define SMC_STRAP_BL0_PLLCLK_BIT 20
#define SMC_STRAP_STATUS_RPT_DISABLE_BIT 21
#define SMC_STRAP_PRIMARY_CHIPLET_BIT 25

// STRAPS_HI (GPIO 32-60, bit index == GPIO index - 32):
#define SMC_STRAP_MBIST_BYPASS_BIT_HI 22  // GPIO 54
#define SMC_STRAP_ROTATE_UPDATE_BIT_HI 26 // GPIO 58

// Masks (applied to the corresponding 32-bit register read).
#define SMC_STRAP_MEM_REPAIR_BYPASS_MASK (1u << SMC_STRAP_MEM_REPAIR_BYPASS_BIT)
#define SMC_STRAP_BOOT_RECOVERY_MASK (1u << SMC_STRAP_BOOT_RECOVERY_BIT)
#define SMC_STRAP_BL0_PLLCLK_MASK (1u << SMC_STRAP_BL0_PLLCLK_BIT)
#define SMC_STRAP_STATUS_RPT_DISABLE_MASK (1u << SMC_STRAP_STATUS_RPT_DISABLE_BIT)
#define SMC_STRAP_PRIMARY_CHIPLET_MASK (1u << SMC_STRAP_PRIMARY_CHIPLET_BIT)
#define SMC_STRAP_MBIST_BYPASS_MASK (1u << SMC_STRAP_MBIST_BYPASS_BIT_HI)
#define SMC_STRAP_ROTATE_UPDATE_MASK (1u << SMC_STRAP_ROTATE_UPDATE_BIT_HI)

// ---------------------------------------------------------------------------
// Scratch register indices (SEP↔SMC coordination protocol)
// ---------------------------------------------------------------------------

#define SMC_SCRATCH_POST_CODE_IDX 1
#define SMC_SCRATCH_VIRT_CONSOLE_IDX 2
#define SMC_SCRATCH_MANIFEST_ADDR_IDX 8
#define SMC_SCRATCH_STATUS_TO_SEP_IDX 9
#define SMC_SCRATCH_MBIST_FAILURE_IDX 10
#define SMC_SCRATCH_STATUS_BUFFER_ADDR_IDX 11
#define SMC_SCRATCH_SEP_SAFE_SRAM_START_IDX 13
#define SMC_SCRATCH_SEP_SAFE_SRAM_SIZE_IDX 14
#define SMC_SCRATCH_MEM_REPAIR_STATUS_IDX 15

// ---------------------------------------------------------------------------
// SMC→SEP status flags (scratch[9] bitfield)
// ---------------------------------------------------------------------------

#define SMC_SEP_STATUS_SRAM_INIT (1u << 0)
#define SMC_SEP_STATUS_MANIFEST_READY (1u << 1)
#define SMC_SEP_STATUS_BUFFER_READY (1u << 2)
#define SMC_SEP_STATUS_SRAM_PROTECTED (1u << 3)

// ---------------------------------------------------------------------------
// MEM_REPAIR status values (scratch[15])
// ---------------------------------------------------------------------------

#define SMC_MEM_REPAIR_STATUS_PASSED 0x600DCAFEu
#define SMC_MEM_REPAIR_STATUS_FAILED 0xBADC0FFEu
#define SMC_MEM_REPAIR_STATUS_BYPASSED 0x12340001u

// ---------------------------------------------------------------------------
// Lifecycle state
// ---------------------------------------------------------------------------

#define SMC_LC_STATE_MASK 0xFu

// ---------------------------------------------------------------------------
// Inline accessors
// ---------------------------------------------------------------------------

static inline uint32_t smc_read_straps_lo(void) {
    return mmio_read32(sep_get_smc_base() + SMC_STRAPS_LO_OFFSET);
}

static inline uint32_t smc_read_straps_hi(void) {
    return mmio_read32(sep_get_smc_base() + SMC_STRAPS_HI_OFFSET);
}

static inline uint32_t smc_scratch_read(uint32_t index) {
    return mmio_read32(sep_get_smc_base() + SMC_SCRATCH_BASE_OFFSET + (index << 3));
}

static inline void smc_scratch_write(uint32_t index, uint32_t value) {
    mmio_write32(sep_get_smc_base() + SMC_SCRATCH_BASE_OFFSET + (index << 3), value);
}

static inline uint32_t smc_read_chip_id(void) {
    return mmio_read32(sep_get_smc_base() + SMC_CHIP_ID_OFFSET);
}

static inline uint32_t smc_read_lc_state(void) {
    return mmio_read32(sep_get_smc_base() + SMC_LC_STATE_OFFSET) & SMC_LC_STATE_MASK;
}

static inline uint32_t smc_read_dft_status(void) {
    return mmio_read32(sep_get_smc_base() + SMC_DFX_CTRL_STATUS_SMU_OFFSET);
}

// Fuse-sense completion is bit 0 of the SEP-local SMC_FUSE_SENSE_STATUS register;
// the SMC senses the eFuse array and SEP observes the completion here.
#define SMC_FUSE_SENSE_DONE_MASK 0x1u

// Every fuse shadow read in the boot flow is downstream of this wait. A shadow
// read taken before sensing completes returns zero, and zero is a legal encoding
// for the fields that gate security: LC_STATE zero decodes as TEST_DEV, where
// secure boot is optional, so an early lifecycle read fails open. Polled without
// timeout -- the hang is the accepted failure mode ([SEP-ROM-CPU-080]).
static inline void smc_wait_fuse_sense(void) {
    while ((mmio_read32(OCH_SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR) &
            SMC_FUSE_SENSE_DONE_MASK) == 0u) {
        // spin
    }
}

static inline uint32_t sep_get_smc_sram_base(void) {
    return sep_get_smc_base() + SMC_SRAM_OFFSET;
}
