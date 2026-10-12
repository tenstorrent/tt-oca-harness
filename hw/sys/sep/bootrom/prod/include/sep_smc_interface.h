/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// SEP-side interface for accessing SMC resources.
//
// SEP accesses SMC through the outbound AXI path. Register offsets come from
// sep_smc_map.h.
//
// IMPORTANT: SEP must NOT include SMC-internal headers (e.g. smc_rom_defs.h).
// The constants here define the SEP↔SMC *interface contract* — bit-field
// positions and scratch usage that both sides agree on.

#pragma once

#include <stdint.h>

#include "rom_mmio.h"
#include "rom_virt_console.h"
#include "sep.h"
#include "sep_smc_map.h"

static inline uint32_t sep_get_smc_base(void) {
    return SEP_SMC_GLOBAL_BASE;
}

// CPU_CTRL.RESET_CTRL is a 64-bit register; the per-core resets
// core0..3_reset_n_n0_scan are bits [3:0] of the low word, active low with
// reset value 1, so clearing a bit holds that core in reset.
#define SMC_CPU_CTRL_RESET_CTRL_CORE_RESET_N_MASK 0xFu

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
    return mmio_read32(sep_get_smc_base() + SMC_SCRATCH_OFFSET(index));
}

static inline void smc_scratch_write(uint32_t index, uint32_t value) {
    mmio_write32(sep_get_smc_base() + SMC_SCRATCH_OFFSET(index), value);
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

// The SMC senses the eFuse array and SEP observes the completion here.
#define SMC_FUSE_SENSE_DONE_MASK SEP_CPU_CTRL__SMC_FUSE_SENSE_STATUS__SMC_FUSE_SENSE_DONE_bm

// Every fuse shadow read in the boot flow is downstream of this wait. A shadow
// read taken before sensing completes returns zero, and zero is a legal encoding
// for the fields that gate security: LC_STATE zero decodes as TEST_DEV, where
// secure boot is optional, so an early lifecycle read fails open. Polled without
// timeout -- the hang is the accepted failure mode ([SEP-ROM-CPU-080]).
static inline void smc_wait_fuse_sense(void) {
    while ((mmio_read32(SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR) &
            SMC_FUSE_SENSE_DONE_MASK) == 0u) {
        // spin
    }
}

static inline uint32_t sep_get_smc_sram_base(void) {
    return sep_get_smc_base() + SMC_SRAM_OFFSET;
}
