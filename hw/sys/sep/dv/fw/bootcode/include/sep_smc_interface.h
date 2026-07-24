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
#include "och_sep_top_reg.h"

// ---------------------------------------------------------------------------
// SMC base address (fixed in crossbar configuration)
// ---------------------------------------------------------------------------

// SMC global base address as seen by SEP CPU.
// The xbar routes [0x40000000, 0xC0000000) to sep_system_peripherals
// (external_smu port), which forwards to SMC via the output fabric.
#define SEP_SMC_GLOBAL_BASE  0x40000000u

static inline uint32_t sep_get_smc_base(void) {
    return SEP_SMC_GLOBAL_BASE;
}

// ---------------------------------------------------------------------------
// SMC register offsets (relative to SMC base)
// ---------------------------------------------------------------------------

// Reset unit — latched strap values (32-bit LO + 32-bit HI).
#define SMC_STRAPS_LO_OFFSET        0x2090u
#define SMC_STRAPS_HI_OFFSET        0x2094u

// CPU_CTRL scratch registers (64-bit stride: index * 8).
#define SMC_SCRATCH_BASE_OFFSET     0x10100u

// Chip config block (VERSION_LO/HI, CHIP_ID, LC_STATE, RAS_BANK_INFO).
#define SMC_CHIP_ID_OFFSET          0x2908u

// SMC fuse map — chiplet/package ID for usage constraints (C13.7).
// 8 × 32-bit words each. SEP reads via AXI: smc_base + offset.
// These are the shared offsets for the SMC fuse-map register window.
#define SMC_FUSE_MAP_CHIPLET_ID_OFFSET  0xB008u
#define SMC_FUSE_MAP_PACKAGE_ID_OFFSET  0xB028u
#define SMC_LC_STATE_OFFSET         0x290Cu

// SMC SRAM (SPM memory).
#define SMC_SRAM_OFFSET             0x60000u
#define SMC_SRAM_SIZE_BYTES         0x100000u   // 1 MiB

// DFX_CTRL_STATUS_SMU register — memory repair + MBIST status (merged into single register).
#define SMC_DFX_CTRL_STATUS_SMU_OFFSET  0xF800u

// DFX_CTRL_STATUS bitfield (same for SOC and SEP_SMC views).
#define DFT_STATUS_MEM_REPAIR_DONE_BIT      0
#define DFT_STATUS_MEM_REPAIR_SUCCESS_BIT   1
#define DFT_STATUS_MEM_REPAIR_ABORT_BIT     2
#define DFT_STATUS_MEM_REPAIR_DONE_MASK     (1u << 0)
#define DFT_STATUS_MEM_REPAIR_SUCCESS_MASK  (1u << 1)
#define DFT_STATUS_MEM_REPAIR_ABORT_MASK    (1u << 2)

// ---------------------------------------------------------------------------
// Strap bit definitions (SEP↔SMC interface contract)
// ---------------------------------------------------------------------------

// STRAPS_LO (32-bit):
#define SMC_STRAP_MEM_REPAIR_BYPASS_BIT     13
#define SMC_STRAP_STATUS_RPT_DISABLE_BIT    21
#define SMC_STRAP_PRIMARY_CHIPLET_BIT       25

// STRAPS_HI (32-bit, representing bits [63:32] of the 64-bit strap word):
#define SMC_STRAP_BOOT_RECOVERY_BIT_HI      23  // absolute bit 55
#define SMC_STRAP_BL0_PLLCLK_BIT_HI         24  // absolute bit 56
#define SMC_STRAP_ROTATE_UPDATE_BIT_HI       29  // absolute bit 61

// Masks (applied to the corresponding 32-bit register read).
#define SMC_STRAP_MEM_REPAIR_BYPASS_MASK    (1u << SMC_STRAP_MEM_REPAIR_BYPASS_BIT)
#define SMC_STRAP_STATUS_RPT_DISABLE_MASK   (1u << SMC_STRAP_STATUS_RPT_DISABLE_BIT)
#define SMC_STRAP_PRIMARY_CHIPLET_MASK      (1u << SMC_STRAP_PRIMARY_CHIPLET_BIT)
#define SMC_STRAP_BOOT_RECOVERY_MASK        (1u << SMC_STRAP_BOOT_RECOVERY_BIT_HI)
#define SMC_STRAP_BL0_PLLCLK_MASK           (1u << SMC_STRAP_BL0_PLLCLK_BIT_HI)
#define SMC_STRAP_ROTATE_UPDATE_MASK        (1u << SMC_STRAP_ROTATE_UPDATE_BIT_HI)

// ---------------------------------------------------------------------------
// Scratch register indices (SEP↔SMC coordination protocol)
// ---------------------------------------------------------------------------

#define SMC_SCRATCH_POST_CODE_IDX               1
#define SMC_SCRATCH_VIRT_CONSOLE_IDX            2
#define SMC_SCRATCH_MANIFEST_ADDR_IDX           8
#define SMC_SCRATCH_STATUS_TO_SEP_IDX           9
#define SMC_SCRATCH_MBIST_FAILURE_IDX           10
#define SMC_SCRATCH_STATUS_BUFFER_ADDR_IDX      11
#define SMC_SCRATCH_SEP_SAFE_SRAM_START_IDX     13
#define SMC_SCRATCH_SEP_SAFE_SRAM_SIZE_IDX      14
#define SMC_SCRATCH_MEM_REPAIR_STATUS_IDX       15

// ---------------------------------------------------------------------------
// SMC→SEP status flags (scratch[9] bitfield)
// ---------------------------------------------------------------------------

#define SMC_SEP_STATUS_SRAM_INIT            (1u << 0)
#define SMC_SEP_STATUS_MANIFEST_READY       (1u << 1)
#define SMC_SEP_STATUS_BUFFER_READY         (1u << 2)
#define SMC_SEP_STATUS_SRAM_PROTECTED       (1u << 3)

// ---------------------------------------------------------------------------
// MEM_REPAIR status values (scratch[15])
// ---------------------------------------------------------------------------

#define SMC_MEM_REPAIR_STATUS_PASSED        0x600DCAFEu
#define SMC_MEM_REPAIR_STATUS_FAILED        0xBADC0FFEu
#define SMC_MEM_REPAIR_STATUS_BYPASSED      0x12340001u

// ---------------------------------------------------------------------------
// Lifecycle state
// ---------------------------------------------------------------------------

#define SMC_LC_STATE_MASK                   0xFu

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

static inline uint32_t sep_get_smc_sram_base(void) {
    return sep_get_smc_base() + SMC_SRAM_OFFSET;
}
