/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC ROM Common Definitions
 * Centralized definitions for register addresses, bit positions, and constants
 * used throughout the SMC production ROM firmware.
 *
 * This header provides essential constants that can be used in both C and assembly code.
 * For higher-level utility functions and register access helpers, see smc_defines.h.
 *
 * Usage:
 *   - Assembly code: Use *_VAL variants (e.g., SMC_STRAPS_LO_REG_ADDR_VAL)
 *   - C code: Use regular definitions (e.g., SMC_STRAPS_LO_REG_ADDR)
 *   - Both files are designed to work together - smc_defines.h includes this file
 */

#ifndef SMC_ROM_DEFS_H
#define SMC_ROM_DEFS_H

/*
 * Register Address Definitions
 * These are extracted from registers/smc_top_regs.h to avoid complex includes in assembly
 */
/* SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR in regs/gen/c/smc_addr.h */
#define SMC_STRAPS_LO_REG_ADDR 0xC0403000
/* SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_HI_BASE_ADDR in regs/gen/c/smc_addr.h */
#define SMC_STRAPS_HI_REG_ADDR 0xC0403004

/*
 * eFuse map addresses that registers/smc_top_regs.h gets wrong. That header still describes the
 * previous fuse map and its generator is missing from the tree, so every eFuse register the ROM
 * reads is defined here instead. Only LOCKS is still correct there.
 *
 * Do not reach for the header's SMC_EFUSE_MAP_CHIPLET_ID_* or SMC_EFUSE_MAP_PACKAGE_ID_*: those
 * registers no longer exist, and PACKAGE_ID's stale address now lands inside I2C_I3C_ID.
 *
 * Mirror of the generated regs/gen/c/smc_addr.h symbols SMC_TOP_SMC_EFUSE_MAP_<REG>_BASE_ADDR.
 */
#define SMC_EFUSE_MAP_I2C_I3C_ID_REG_ADDR(idx) (0xC0007028 + ((idx)*8))
#define SMC_EFUSE_MAP_SMC_CONFIG_REG_ADDR 0xC0007070
#define SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_REG_ADDR 0xC0007078

/*
 * Strap Bit Definitions
 * From tt_smc_master_chiplet_config_pkg.sv
 */
#define SMC_STRAP_MEM_REPAIR_BYPASS_BIT 13
#define SMC_STRAP_TEST_EN_BIT 14
#define SMC_STRAP_BOOT_I2C_BIT 18
#define SMC_STRAP_PRIMARY_CHIPLET_BIT 25
#define SMC_STRAP_SRAM_AUTO_ZERO_DISABLE_BIT 26
#define SMC_STRAP_CHIP_ID_3 11
#define SMC_STRAP_CHIP_ID_2 12
#define SMC_STRAP_SPI_USE_FUSED_CONFIG_BIT 22

/* Chiplet ID constants for clock configuration */
#define SMC_AUX_CHIPLET_ID 3

// CHIP_ID_1/0 relocated off pads 55/57 to Harness input pads 15 (UART1 rx) and 23 (UART3 rx), which
// live in STRAPS_LO.
#define SMC_STRAP_CHIP_ID_1 15
#define SMC_STRAP_CHIP_ID_0 23

#define SMC_STRAP_MEM_BIST_BYPASS_BIT 54    /* In HI register */
#define SMC_STRAP_BOOT_RECOVERY_BIT 19      /* In LO register */
#define SMC_STRAP_BL0_PLLCLK_BIT 20         /* In LO register - enables PLL configuration */
#define SMC_STRAP_STATUS_RPT_DISABLE_BIT 21 /* In LO register - Disable status reporting */
#define SMC_STRAP_ROTATE_UPDATE_BIT \
    58 /* In HI register (STRAPS_HI[26]); pad 61 -> 58 after 68->65 shrink */

/* Strap bit masks */
#define SMC_STRAP_MEM_REPAIR_BYPASS_MASK (1U << SMC_STRAP_MEM_REPAIR_BYPASS_BIT)
#define SMC_STRAP_TEST_EN_MASK (1U << SMC_STRAP_TEST_EN_BIT)
#define SMC_STRAP_SRAM_AUTO_ZERO_DISABLE_MASK (1U << SMC_STRAP_SRAM_AUTO_ZERO_DISABLE_BIT)
#define SMC_STRAP_PRIMARY_CHIPLET_MASK (1U << SMC_STRAP_PRIMARY_CHIPLET_BIT)
#define SMC_STRAP_CHIP_ID_3_MASK (1U << SMC_STRAP_CHIP_ID_3)
#define SMC_STRAP_CHIP_ID_2_MASK (1U << SMC_STRAP_CHIP_ID_2)
#define SMC_STRAP_CHIP_ID_1_MASK (1U << SMC_STRAP_CHIP_ID_1) /* STRAPS_LO bit 15 */
#define SMC_STRAP_CHIP_ID_0_MASK (1U << SMC_STRAP_CHIP_ID_0) /* STRAPS_LO bit 23 */
#define SMC_STRAP_BOOT_I2C_MASK (1U << SMC_STRAP_BOOT_I2C_BIT)
#define SMC_STRAP_MEM_BIST_BYPASS_MASK (1U << (SMC_STRAP_MEM_BIST_BYPASS_BIT - 32))
#define SMC_STRAP_BL0_PLLCLK_MASK (1U << SMC_STRAP_BL0_PLLCLK_BIT)
#define SMC_STRAP_BOOT_RECOVERY_MASK (1U << SMC_STRAP_BOOT_RECOVERY_BIT)
#define SMC_STRAP_STATUS_RPT_DISABLE_MASK (1U << SMC_STRAP_STATUS_RPT_DISABLE_BIT)
#define SMC_STRAP_SPI_USE_FUSED_CONFIG_MASK (1U << SMC_STRAP_SPI_USE_FUSED_CONFIG_BIT)
#define SMC_STRAP_ROTATE_UPDATE_MASK (1U << (SMC_STRAP_ROTATE_UPDATE_BIT - 32))

/*
 * I3C/I2C Peripheral Controller to GPIO Assignments
 * These define which GPIOs are used for each I3C/I2C controller's SCL and SDA lines.
 * Updated to match contiguous GPIO layout reorganization.
 */
#define SMC_I3C_0_SCL_GPIO 27
#define SMC_I3C_0_SDA_GPIO 28
#define SMC_I3C_1_SCL_GPIO 63 /* unbonded */
#define SMC_I3C_1_SDA_GPIO 64 /* unbonded */
#define SMC_I3C_2_SCL_GPIO 29
#define SMC_I3C_2_SDA_GPIO 30
#define SMC_I3C_3_SCL_GPIO 31
#define SMC_I3C_3_SDA_GPIO 32
#define SMC_I3C_4_SCL_GPIO 33
#define SMC_I3C_4_SDA_GPIO 34
#define SMC_I3C_5_SCL_GPIO 35
#define SMC_I3C_5_SDA_GPIO 36

#define SMC_I2C_0_SCL_GPIO 37
#define SMC_I2C_0_SDA_GPIO 38
#define SMC_I2C_1_SCL_GPIO 41
#define SMC_I2C_1_SDA_GPIO 42

/* Observation GPIOs routed via the GPIO 2nd HW function override in
 * smc_ip_integration (hw2_ovrd must be set for the function to reach the pad). */
#define SMC_CAT_THERM_GPIO 52 /* thermal trip output (active low) */

#define SMC_STATUS_GPIO \
    58 /* GPIO used for reset status reporting (pad 61 -> 58 after 68->65 shrink) */
#define MAX_GPIO_COUNT 71 /* Maximum number of GPIOs supported */

/*
 * SRAM Definitions
 */
#define SMC_SRAM_BASE 0xC0060000    /* SPM_MEMORY_MEM_BASE_ADDR - physical SRAM start */
#define SMC_SRAM_SIZE (1024 * 1024) /* 1 MB total SRAM size */

/* ROM-owned memory regions (protected from OCCP access) */
#define SMC_ROM_DATA_BASE 0xC0060000 /* ROM .data section start */
#define SMC_ROM_STACK_END \
    0xC0066400 /* ROM stack end + safety margin (high watermark 23.7KB based on tests, allocating \
                  25KB) */

/* OCCP-accessible SRAM region (starts after ROM-owned regions) */
#define SMC_SRAM_BASE_ADDR \
    SMC_ROM_STACK_END /* OCCP accessible SRAM base - starts after ROM sections */
#define SMC_SRAM_STACK_LIMIT_ADDR (SMC_SRAM_BASE + SMC_SRAM_SIZE) /* End of physical SRAM */

/* SEP Safe SRAM Region (for SEP scratchpad operations)
 * This is the region SEP can safely use without interfering with SMC ROM operations */
#define SEP_SAFE_SRAM_START SMC_SRAM_BASE_ADDR /* Start: 0xC0066400 */
#define SEP_SAFE_SRAM_END 0xC015B000           /* End: just before status buffers*/
#define SEP_SAFE_SRAM_SIZE (SEP_SAFE_SRAM_END - SEP_SAFE_SRAM_START) /* ~987 KB */

/*
 * Scratchpad Register Definitions. Moved here since they are used in both C and assembly.
 * For SMC/SEP coordination per SMC ROM Boot Architecture Specification
 */
#define SMC_SCRATCH_BASE_ADDR 0xC0039080 /* SMC_CPU_CTRL_SCRATCH_0__REG_ADDR */
#define SMC_SCRATCH_MANIFEST_ADDR \
    8 /* Manifest address handoff to SEP (stored as offset from SMC_SRAM_BASE) */
#define SMC_SCRATCH_SMC_STATUS_TO_SEP 9 /* SMC Status to SEP coordination */
#define SMC_SCRATCH_STATUS_BUFFER_ADDR \
    11 /* Status reporting structure address (stored as offset from SMC_SRAM_BASE) */
#define SMC_SCRATCH_SEP_SAFE_SRAM_START \
    13 /* SEP safe SRAM start address (stored as offset from SMC_SRAM_BASE) */
#define SMC_SCRATCH_SEP_SAFE_SRAM_SIZE 14 /* SEP safe SRAM size in bytes */
#define SMC_SCRATCH_MBIST_FAILURE 10      /* MBIST failure register value */
#define SMC_SCRATCH_MBIST_STATUS 15 /* MBIST/memory repair status for early boot diagnostics */

/* DFX_CTRL_STATUS bit masks */
#define DFT_STATUS_MEM_REPAIR_DONE_MASK 0x1
#define DFT_STATUS_MEM_REPAIR_SUCCESS_MASK 0x2
#define DFT_STATUS_MBIST_DONE_MASK 0x10
#define DFT_STATUS_MBIST_PASS_MASK 0x100
#define DFT_STATUS_MBIST_ABORT_MASK 0x1000

/* Early boot MBIST/memory repair status codes */
#define MBIST_STATUS_RUNNING 0x12345678
#define MBIST_STATUS_PASSED 0x600DCAFE
#define MBIST_STATUS_FAILED 0xDEADBEEF
#define MBIST_STATUS_TIMEOUT 0xDEADC0DE
#define MBIST_STATUS_MEM_REPAIR_FAILED 0xBADC0FFE
#define MBIST_STATUS_MEM_REPAIR_BYPASSED 0x12340001
#define MBIST_STATUS_MEM_BIST_BYPASSED 0x12340002

/* OTP SMC_CONFIG bit 15 allows boot to continue despite reported DFT errors. */

/* SMC Status to SEP (Scratch Register 9) Bitfield Definitions */
#define SMC_SEP_STATUS_SRAM_INIT_BIT 0      /* SMC SRAM initialized */
#define SMC_SEP_STATUS_MANIFEST_READY_BIT 1 /* Manifest ready */
#define SMC_SEP_STATUS_BUFFER_READY_BIT 2   /* Status buffer ready */
#define SMC_SEP_STATUS_SRAM_PROTECTED_BIT 3 /* SRAM protected */

#define SMC_SEP_STATUS_SRAM_INIT (1U << SMC_SEP_STATUS_SRAM_INIT_BIT)
#define SMC_SEP_STATUS_MANIFEST_READY (1U << SMC_SEP_STATUS_MANIFEST_READY_BIT)
#define SMC_SEP_STATUS_BUFFER_READY (1U << SMC_SEP_STATUS_BUFFER_READY_BIT)
#define SMC_SEP_STATUS_SRAM_PROTECTED (1U << SMC_SEP_STATUS_SRAM_PROTECTED_BIT)

/*
 * AXI Zeroer Control FSM Register Definitions
 * From AXI_DATA_ACCEL_AXI_ZEROER_CTRL_*_REG_ADDR
 */
#define SMC_ZEROER_DEST_ADDR_REG 0xC0038200
#define SMC_ZEROER_SIZE_REG 0xC0038208
#define SMC_ZEROER_CTRL_STATUS_REG 0xC0038210

/* AXI Zeroer Control Status Register Bits */
#define SMC_ZEROER_CTRL_START_BIT 0
#define SMC_ZEROER_STATUS_BUSY_BIT 32

/* AXI Zeroer Control Values */
#define SMC_ZEROER_START_VALUE 1
#define SMC_ZEROER_BUSY_MASK (1ULL << SMC_ZEROER_STATUS_BUSY_BIT)

/*
 * Boot Flow Constants
 */

/* Boot completion status codes */
#define SMC_BOOT_SUCCESS 0xacafaca1 /* Boot completed successfully */
#define SMC_BOOT_FAILURE 0xdeadbeef /* Boot failed */

/* Written to scratch register 15 when execution enters EBREAK-filled ROM padding. */
#define ROM_PADDING_TRAP_STATUS 0xBADF00D0

/* Boot status indication codes */
#define SMC_BOOT_I2C_INDICATION 0xBEEF0002      /* I2C boot mode selected */
#define SMC_BOOT_RECOVERY_INDICATION 0xBEEF0003 /* Recovery boot mode */

/* Boot phase tracking */
#define SMC_BOOT_PHASE_BASE 0x1000 /* Base for phase tracking */

/*
 * Interface Map Constants
 */
#define SMC_INTERFACE_I2C0_BIT 0 /* I2C0 interface bit position */
#define SMC_INTERFACE_I2C1_BIT 1 /* I2C1 interface bit position */
#define SMC_INTERFACE_I3C0_BIT 2 /* I3C0 interface bit position */
#define SMC_INTERFACE_I3C1_BIT 3 /* I3C1 interface bit position */
#define SMC_INTERFACE_I3C2_BIT 4 /* I3C2 interface bit position */
#define SMC_INTERFACE_I3C3_BIT 5 /* I3C3 interface bit position */

#define SMC_INTERFACE_I2C0_MASK (1U << SMC_INTERFACE_I2C0_BIT)
#define SMC_INTERFACE_I2C1_MASK (1U << SMC_INTERFACE_I2C1_BIT)
#define SMC_INTERFACE_I3C0_MASK (1U << SMC_INTERFACE_I3C0_BIT)
#define SMC_INTERFACE_I3C1_MASK (1U << SMC_INTERFACE_I3C1_BIT)
#define SMC_INTERFACE_I3C2_MASK (1U << SMC_INTERFACE_I3C2_BIT)
#define SMC_INTERFACE_I3C3_MASK (1U << SMC_INTERFACE_I3C3_BIT)

/*
 * Lifecycle State (LC) Register Definitions
 * Register address and mask - detailed LC definitions are in smc_security.h
 */
#define SMC_LC_STATE_REG_ADDR 0xC000290C
#define SMC_LC_STATE_MASK 0xF

/* Clock Frequency Constants */
#define REFCLK_FREQ_MHZ (100)                   // Reference clock input frequency (always 100MHz)
#define PERIPHERAL_REFCLK_OUTPUT_FREQ_MHZ (200) // Peripheral clock output frequency in refclk mode

/*
 * Assembly-specific definitions
 *
 * The regular definitions above are included when assembling and work fine
 * with RISC-V %hi()/%lo() operators. This section only contains values that
 * need special handling for assembly compatibility - specifically, expressions
 * that need to be pre-calculated to literal values.
 */
#ifdef __ASSEMBLER__
/* Pre-calculated values for expressions that can't be evaluated by assembler */
#define SMC_STRAPS_LO_REG_ADDR_VAL 0xC0403000
#define SMC_STRAPS_HI_REG_ADDR_VAL 0xC0403004
/* Literal addresses for assembly, which cannot include the generated headers because their C
 * typedefs do not assemble. Nothing cross-checks these against the register map, so keep them in
 * step with regs/gen/c/smc_addr.h by hand:
 *   SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR
 *   SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR
 *   SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(15), whose stride is 8 bytes, not 4
 */
#define SMC_EFUSE_MAP_SMC_CONFIG_REG_ADDR_VAL 0xC0007070
#define DFX_CTRL_STATUS_SMU_REG_ADDR_VAL 0xC000B800
#define SMC_SCRATCH_MBIST_STATUS_ADDR_VAL 0xC00390F8
#define ROM_PADDING_TRAP_STATUS_VAL 0xBADF00D0
#define SMC_STRAP_MEM_REPAIR_BYPASS_MASK_VAL 0x00002000
#define SMC_STRAP_MEM_BIST_BYPASS_MASK_VAL 0x00400000 /* (1U << (54 - 32)) */
#define SMC_EFUSE_SMC_CONFIG_SRAM_AUTO_ZERO_DISABLE_MASK_VAL 0x80
#define SMC_ZEROER_DEST_ADDR_REG_VAL 0xC0038200
#define SMC_ZEROER_SIZE_REG_VAL 0xC0038208
#define SMC_ZEROER_CTRL_STATUS_REG_VAL 0xC0038210
#define SMC_ZEROER_BUSY_MASK_VAL 0x100000000
#define SMC_SRAM_SIZE_VAL 0x100000                           /* (1024 * 1024) = 1 MB */
#define SMC_STRAP_SRAM_AUTO_ZERO_DISABLE_MASK_VAL 0x04000000 /* (1U << 26) */
#define DFT_STATUS_MEM_REPAIR_DONE_MASK_VAL 0x1
#define DFT_STATUS_MEM_REPAIR_SUCCESS_MASK_VAL 0x2
#define DFT_STATUS_MBIST_DONE_MASK_VAL 0x10
#define DFT_STATUS_MBIST_PASS_MASK_VAL 0x100
#define DFT_STATUS_MBIST_ABORT_MASK_VAL 0x1000
#define MBIST_STATUS_RUNNING_VAL 0x12345678
#define MBIST_STATUS_PASSED_VAL 0x600DCAFE
#define MBIST_STATUS_FAILED_VAL 0xDEADBEEF
#define MBIST_STATUS_TIMEOUT_VAL 0xDEADC0DE
#define MBIST_STATUS_MEM_REPAIR_FAILED_VAL 0xBADC0FFE
#define MBIST_STATUS_MEM_REPAIR_BYPASSED_VAL 0x12340001
#define MBIST_STATUS_MEM_BIST_BYPASSED_VAL 0x12340002
#define SMC_EFUSE_SMC_CONFIG_DFT_IGNORE_ERROR_MASK_VAL 0x8000
#endif

#endif /* SMC_ROM_DEFS_H */
