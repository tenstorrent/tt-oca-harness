/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Defines - Register access and utility functions
 */

#ifndef SMC_DEFINES_H
#define SMC_DEFINES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "smc_top_regs.h"
#include "smc_rom_defs.h"
#include "smc_strap.h"

#define NUM_EXTERNAL_INTERRUPTS (256)  /* 4-core: NUM_EXT_INTERRUPTS=256 */
#define MAILBOX_INTERUPT_ID_BASE (289) /* cpu_interrupts_o[288] -> PLIC ID 289 (4-core) */

#define SMC_ROM_STACK_END \
    0xC0066400 /* ROM stack end + safety margin (high watermark 23.7KB based on tests, allocating \
                  25KB) */

/* OCCP-accessible SRAM region (starts after ROM-owned regions) */
#define SMC_SRAM_OCCP_BASE_ADDR \
    SMC_ROM_STACK_END /* OCCP accessible SRAM base - starts after ROM sections */

/* PLL/CGM Configuration Constants */
#define SMC_CGM_COUNT (7)                   // SMC has CGM0-6 (7 total CGMs)
#define SMC_CGM_STATUS_REG_INTERVAL (0x100) // CGM status registers at 0x100 byte intervals

static inline void write_reg(uint64_t addr, uint32_t value) {
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)addr;
    *p_addr = value;
}

static inline uint32_t read_reg(uint64_t addr) {
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)addr;
    return *p_addr;
}

static inline uint64_t read_reg_64(uint64_t addr) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
    return *p_addr;
}

static inline void write64_reg(uint64_t addr, uint64_t value) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
    *p_addr = value;
}

static inline uint64_t read64_reg(uint64_t addr) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)addr;
    return *p_addr;
}

static inline void write16_reg(uint64_t addr, uint16_t value) {
    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)addr;
    *p_addr = value;
}

static inline uint16_t read16_reg(uint64_t addr) {
    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)addr;
    return *p_addr;
}

static inline void write_periph_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_periph_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_dma_ctrl_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(DMA_CTRL_REG_MAP_BASE_ADDR + // replace
                                         offset);
    *p_addr = value;
}

static inline uint64_t read_dma_ctrl_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(DMA_CTRL_REG_MAP_BASE_ADDR + // replace
                                         offset);
    return *p_addr;
}

static inline void write_zeroer_ctrl_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(ZEROER_CTRL_REG_MAP_BASE_ADDR + // replace
                                         offset);
    *p_addr = value;
}

static inline uint64_t read_zeroer_ctrl_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(ZEROER_CTRL_REG_MAP_BASE_ADDR + // replace
                                         offset);
    return *p_addr;
}

static inline void write_spm(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
    *p_addr = value;
}

static inline void write_spm64(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_spm(uint64_t offset) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
    return *p_addr;
}

static inline uint64_t read_spm64(uint64_t offset) {
    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(SPM_MEMORY_MEM_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_smc_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *addr_ptr =
        (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
    *addr_ptr = value;
}

static inline uint64_t read_smc_reg(uint64_t offset) {
    volatile uint64_t *addr_ptr =
        (volatile uint64_t *)(uintptr_t)(SMC_CPU_CTRL_REG_MAP_BASE_ADDR + offset);
    return *addr_ptr;
}

static inline void write_scratch(uint8_t scratch_num, uint32_t value) {
    volatile uint32_t *addr = (volatile uint32_t *)(uintptr_t)(SMC_CPU_CTRL_SCRATCH_0__REG_ADDR +
                                                               (scratch_num * sizeof(uint64_t)));
    *addr = value;
}

static inline uint32_t read_scratch(uint8_t scratch_num) {
    volatile uint32_t *addr = (volatile uint32_t *)(uintptr_t)(SMC_CPU_CTRL_SCRATCH_0__REG_ADDR +
                                                               (scratch_num * sizeof(uint64_t)));
    return *addr;
}

/* Legacy POST code function - writes to scratch register 0 (pass/fail)
 * For structured POST code management, use smc_post_code.h API instead */
static inline void write_postcode(uint32_t value) {
    write_scratch(0, value);
}

static inline void write_mailbox(uint8_t mailbox_num, uint8_t is_inbound, uint32_t offset,
                                 uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR +
                                         (mailbox_num * 0x1000 + is_inbound * 0x800) + offset);
    *p_addr = value;
}

static inline uint64_t read_mailbox(uint8_t mailbox_num, uint8_t is_inbound, uint32_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR +
                                         (mailbox_num * 0x1000 + is_inbound * 0x800) + offset);
    return *p_addr;
}

static inline void write_gpio_shim(uint8_t gpio_num, uint32_t offset, uint32_t value) {
    uint32_t gpio_spacing = 0x20;
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)((GPIO_CTRL_0__REG_MAP_BASE_ADDR +
                                                                  gpio_num * gpio_spacing) +
                                                                 offset);
    *p_addr = value;
}

static inline uint32_t read_gpio_shim(uint8_t gpio_num, uint32_t offset) {
    uint32_t gpio_spacing = 0x20;
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)((GPIO_CTRL_0__REG_MAP_BASE_ADDR +
                                                                  gpio_num * gpio_spacing) +
                                                                 offset);
    return *p_addr;
}

static inline void write_gpio(uint8_t gpio_num, uint32_t offset, uint32_t value) {
    uint32_t gpio_spacing = 0x10;
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)((GPIO_INTF_0__REG_MAP_BASE_ADDR +
                                                                  gpio_num * gpio_spacing) +
                                                                 offset);
    *p_addr = value;
}

static inline uint32_t read_gpio(uint8_t gpio_num, uint32_t offset) {
    uint32_t gpio_spacing = 0x10;
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)((GPIO_INTF_0__REG_MAP_BASE_ADDR +
                                                                  gpio_num * gpio_spacing) +
                                                                 offset);
    return *p_addr;
}

// static inline void write_ptp_timer(uint32_t offset, uint32_t value)
// {
//   volatile uint32_t *p_addr =
//       (volatile uint32_t *)(uintptr_t)(PTP_TIMER_REG_MAP_BASE_ADDR + offset);
//   *p_addr = value;
// }

// static inline uint32_t read_ptp_timer(uint32_t offset)
// {
//   volatile uint32_t *p_addr =
//       (volatile uint32_t *)(uintptr_t)(PTP_TIMER_REG_MAP_BASE_ADDR + offset);
//   return *p_addr;
// }

// static inline void write_zeros(const uint32_t addr, const uint32_t size,
//                                const bool int_en)
// {
//   write_zeroer_ctrl_reg(AXI_DATA_ACCEL_AXI_ZEROER_CTRL_DEST_ADDR_REG_OFFSET,
//                         addr);
//   write_zeroer_ctrl_reg(AXI_DATA_ACCEL_AXI_ZEROER_CTRL_SIZE_REG_OFFSET, size);
//   write_zeroer_ctrl_reg(AXI_DATA_ACCEL_AXI_ZEROER_CTRL_CTRL_STATUS_REG_OFFSET,
//                         int_en);

//   while (read_zeroer_ctrl_reg(
//       AXI_DATA_ACCEL_AXI_ZEROER_CTRL_CTRL_STATUS_REG_OFFSET))
//     ;
// }

static inline void write_pll_ctrl_reg(uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_REG_MAP_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint32_t read_pll_ctrl_reg(uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_REG_MAP_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_apb2avsbus_ctrl_reg(uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_AVSBUS_CONTROLLER_REG_MAP_BASE_ADDR +
                                         offset); // replace
    *p_addr = value;
}

static inline uint32_t read_abp2avsbus_ctrl_reg(uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_AVSBUS_CONTROLLER_REG_MAP_BASE_ADDR +
                                         offset); // replace
    return *p_addr;
}

static inline void write_cgm_pll_reg(uint32_t id, uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_REG_ADDR + id * 0x100 +
                                         offset);
    *p_addr = value;
}

static inline uint32_t read_cgm_pll_reg(uint32_t id, uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_REG_ADDR + id * 0x100 +
                                         offset);
    return *p_addr;
}

static inline void write_uart_reg(int uart_id, uint32_t offset, uint32_t value) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_REG_MAP_BASE_ADDR;
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__UART_REG_MAP_BASE_ADDR;
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__UART_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__UART_REG_MAP_BASE_ADDR;
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    *p_addr = value;
}

static inline uint32_t read_uart_reg(int uart_id, uint32_t offset) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__UART_REG_MAP_BASE_ADDR;
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__UART_REG_MAP_BASE_ADDR;
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__UART_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__UART_REG_MAP_BASE_ADDR;
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    return *p_addr;
}

static inline void write_uart_engine_reg(int uart_id, uint32_t offset, uint32_t value) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_REG_MAP_BASE_ADDR;
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__LOG_ENGINE_REG_MAP_BASE_ADDR;
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__LOG_ENGINE_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__LOG_ENGINE_REG_MAP_BASE_ADDR;
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    *p_addr = value;
}

static inline uint32_t read_uart_engine_reg(int uart_id, uint32_t offset) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_0__LOG_ENGINE_REG_MAP_BASE_ADDR;
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_1__LOG_ENGINE_REG_MAP_BASE_ADDR;
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_2__LOG_ENGINE_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_UART = SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_3__LOG_ENGINE_REG_MAP_BASE_ADDR;
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    return *p_addr;
}

static inline void write_beu_reg(int hartid, uint64_t offset, uint64_t value) {
    uint64_t BASE_ADDRESS_BEU;
    if (hartid == 0) {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE0_BEU_REG_MAP_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE1_BEU_REG_MAP_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE2_BEU_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE3_BEU_REG_MAP_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_BEU + offset);
    *p_addr = value;
}

static inline uint64_t read_beu_reg(int hartid, uint64_t offset) {
    uint64_t BASE_ADDRESS_BEU;
    if (hartid == 0) {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE0_BEU_REG_MAP_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE1_BEU_REG_MAP_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE2_BEU_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_BEU = SMC_CLUSTER_CORE3_BEU_REG_MAP_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_BEU + offset);
    return *p_addr;
}

static inline void write_wdt_reg(int hartid, uint64_t offset, uint64_t value) {
    uint64_t BASE_ADDRESS_WDT;
    if (hartid == 0) {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE0_WDT_REG_MAP_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE1_WDT_REG_MAP_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE2_WDT_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE3_WDT_REG_MAP_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_WDT + offset);
    *p_addr = value;
}

static inline uint64_t read_wdt_reg(int hartid, uint64_t offset) {
    uint64_t BASE_ADDRESS_WDT;
    if (hartid == 0) {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE0_WDT_REG_MAP_BASE_ADDR;
    } else if (hartid == 1) {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE1_WDT_REG_MAP_BASE_ADDR;
    } else if (hartid == 2) {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE2_WDT_REG_MAP_BASE_ADDR;
    } else {
        BASE_ADDRESS_WDT = SMC_CLUSTER_CORE3_WDT_REG_MAP_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(BASE_ADDRESS_WDT + offset);
    return *p_addr;
}

// static inline void peripherals_out_of_reset(void)
// {
//   // Take all peripherals out of reset
//   SMC_WRAP_RESET_UNIT_MASTER_PERIPHERAL_RESETS_reg_u peripheral_reset_ctrl;
//   peripheral_reset_ctrl.val = read_reg(RESET_UNIT_PERIPHERAL_RESETS_REG_ADDR);
//   peripheral_reset_ctrl.f.avs_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.i2c_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.i3c_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.ptp_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.pvt_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.uart_reset_n_n0_scan = 1;
//   peripheral_reset_ctrl.f.telemetry_reset_n_n0_scan = 1;
//   write_reg(RESET_UNIT_PERIPHERAL_RESETS_REG_ADDR, peripheral_reset_ctrl.val);
// }

/* Auxiliary chiplet PLL configuration functions */

// static inline void wait_for_cgm_locks_smc(void)
// {
//   // Wait for all CGMs to lock (CGM0 to CGM_COUNT-1)
//   // CGM configuration values come from efuse shadow registers via i_cgm_init_code
//   // Hardware automatically programs: fcw_int, fcw_frac, prediv, postdiv0-3,
//   // cgm_enable, freq_acq_enable, freq_lock_threshold
//   for (int cgm = 0; cgm < SMC_CGM_COUNT; cgm++) {
//     wait_for_cgm_lock_smc(cgm);
//   }
// }

// static inline void configure_cgm2_peripheral_200mhz(void)
// {
//   // Configure CGM2 to generate 200MHz peripheral clock from 100MHz reference clock
//   // This is only needed for auxiliary chiplets when using refclk mode
//   // Formula: Fout = Fref × FCW_INT / 2^POSTDIV
//   // Calculate: FCW_INT = Fout / Fref = 200MHz / 100MHz = 2, POSTDIV = 0
//   uint16_t fcw_int = PERIPHERAL_REFCLK_OUTPUT_FREQ_MHZ / REFCLK_FREQ_MHZ;

//   // Enable CGM2
//   CGM_ENABLES_reg_u cgm_2_enables;
//   cgm_2_enables.val = read_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_ENABLES_REG_OFFSET);
//   cgm_2_enables.f.cgm_enable = 1;
//   cgm_2_enables.f.freq_acq_enable = 1;
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_ENABLES_REG_OFFSET, cgm_2_enables.val);

//   // Set frequency control word for calculated multiplication
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_FCW_INT_REG_OFFSET, fcw_int);

//   // Set fractional part to 0 (not used)
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_FCW_FRAC_REG_OFFSET, 0);

//   // Set predivider to 0 (no pre-division)
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_PREDIV_REG_OFFSET, 0);

//   // Set post-dividers (POSTDIV0 = 0 for divide by 1)
//   CGM_POSTDIV_ARRAY_0_reg_u postdivs;
//   postdivs.val = CGM_POSTDIV_ARRAY_0_REG_DEFAULT;
//   postdivs.f.postdiv0 = 0;  // 2^0 = 1 (no division)
//   postdivs.f.postdiv1 = 0;
//   postdivs.f.postdiv2 = 0;
//   postdivs.f.postdiv3 = 0;
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_ARRAY_0_REG_OFFSET, postdivs.val);

//   // Set post-divider configuration (bypass refclk until locked)
//   CGM_POSTDIV_CONFIG_reg_u postdiv_config;
//   postdiv_config.val = CGM_POSTDIV_CONFIG_REG_DEFAULT;
//   postdiv_config.f.postdiv0_config = 0; // Bypass clkref until cgm is locked
//   postdiv_config.f.postdiv1_config = 1; // Force clock gate
//   postdiv_config.f.postdiv2_config = 1; // Force clock gate
//   postdiv_config.f.postdiv3_config = 1; // Force clock gate
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_CONFIG_REG_OFFSET, postdiv_config.val);

//   // Set frequency lock threshold
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_LOCK_CONFIG_REG_OFFSET, 0x0B); // 1% jitter

//   // Trigger register update
//   write_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_REG_UPDATE_REG_OFFSET, 0x1);

//   // Wait for CGM2 lock
//   wait_for_cgm_lock_smc(2);
// }

// static inline uint32_t get_peripheral_clock_frequency_mhz(void)
// {
//   // Determine the current peripheral clock frequency based on actual CGM mux configuration
//   // All chiplets must configure peripherals with correct frequency regardless of chiplet type
//   //
//   // IMPORTANT: Don't rely solely on BL0_PLLCLK strap - individual CGM muxes can override!
//   // Even when BL0_PLLCLK is deasserted, specific CGMs may still use PLL via mux configuration.

//   // Check CGM2 mux configuration to determine actual clock source
//   // CGM2 is used for peripheral clock on all chiplets
//   // AG_MUX_SELECT register: "0 for refclk and 1 for pll"
//   // CGM2 uses bits 8-11 (4 bits per CGM, CGM2 is index 2: bits 8-11)
//   uint32_t ag_mux_select = read_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR);
//   uint32_t cgm2_mux_bits = (ag_mux_select >> 8) & 0xF; // Extract CGM2 mux bits [11:8]

//   if (cgm2_mux_bits != 0) {
//     // CGM2 mux is configured to use PLL - calculate frequency from CGM2 registers
//     // Hardware automatically configures CGM registers from efuse via i_cgm_init_code
//     //
//     // RTL Reference: CGM instances have i_init_code input interface
//     // - tt_cgm_pll_wrapper.sv:211 shows i_init_code[i] input (80 bits per CGM)
//     // - Movellus vendor IP automatically loads configuration from efuse shadow registers

//     // Read CGM2 frequency control word and dividers from registers
//     uint16_t fcw_int = read_cgm_pll_reg(2, SMC_WRAP_PLL_CNTL_CGM_0_FCW_INT_REG_OFFSET);
//     uint16_t postdiv_array = read_cgm_pll_reg(2,
//     SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_ARRAY_0_REG_OFFSET); uint16_t postdiv0 = postdiv_array & 0x7;
//     // Extract postdiv0 (bits 2:0)

//     // Calculate frequency using Movellus CGM vendor formula: Fout = Fref * FCW / 2^POSTDIV
//     // Source: cgm.rdl:52 - "Integer part of FCW... Fout=Fref*FCW/2**postdiv"
//     // Where Fref = 100MHz (reference clock)
//     uint32_t frequency_mhz = (REFCLK_FREQ_MHZ * fcw_int) >> postdiv0;
//     return frequency_mhz;
//   } else {
//     // CGM2 mux is configured to use reference clock
//     // Peripheral clock should run at 200MHz in refclk mode
//     // Configured by configure_cgm2_peripheral_200mhz()
//     return PERIPHERAL_REFCLK_OUTPUT_FREQ_MHZ;
//   }
// }

// static inline uint32_t get_core_clock_frequency_mhz(void)
// {
//   // Determine the current core clock frequency based on actual CGM mux configuration
//   // All chiplets must configure core with correct frequency regardless of chiplet type
//   //
//   // Check CGM0 mux configuration to determine actual clock source
//   // CGM0 is used for core clock (SMC System Clock) on all chiplets
//   // AG_MUX_SELECT register: "0 for refclk and 1 for pll"
//   // CGM0 uses bits 0-3 (4 bits per CGM, CGM0 is index 0: bits 3:0)
//   uint32_t ag_mux_select = read_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR);
//   uint32_t cgm0_mux_bits = ag_mux_select & 0xF; // Extract CGM0 mux bits [3:0]

//   if (cgm0_mux_bits != 0) {
//     // CGM0 mux is configured to use PLL - calculate frequency from CGM0 registers
//     // Hardware automatically configures CGM registers from efuse via i_cgm_init_code
//     //
//     // RTL Reference: CGM instances have i_init_code input interface
//     // - tt_cgm_pll_wrapper.sv:211 shows i_init_code[i] input (80 bits per CGM)
//     // - Movellus vendor IP automatically loads configuration from efuse shadow registers

//     // Read CGM0 frequency control word and dividers from registers
//     uint16_t fcw_int = read_cgm_pll_reg(0, SMC_WRAP_PLL_CNTL_CGM_0_FCW_INT_REG_OFFSET);
//     uint16_t postdiv_array = read_cgm_pll_reg(0,
//     SMC_WRAP_PLL_CNTL_CGM_0_POSTDIV_ARRAY_0_REG_OFFSET); uint16_t postdiv0 = postdiv_array & 0x7;
//     // Extract postdiv0 (bits 2:0)

//     // Calculate frequency using Movellus CGM vendor formula: Fout = Fref * FCW / 2^POSTDIV
//     // Source: cgm.rdl:52 - "Integer part of FCW... Fout=Fref*FCW/2**postdiv"
//     // Where Fref = 100MHz (reference clock)
//     uint32_t frequency_mhz = (REFCLK_FREQ_MHZ * fcw_int) >> postdiv0;
//     return frequency_mhz;
//   } else {
//     // CGM0 mux is configured to use reference clock
//     // In refclk mode, core runs directly from the reference clock at 100MHz
//     return REFCLK_FREQ_MHZ;
//   }
// }

// static inline void switch_pll_mux_functional(void)
// {
//   // Switch all CGM muxes to PLL sources
//   write_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR, 0x01111111); // Main PLL
//   clock mux select write_reg(LOCAL_SMC_WRAP_PLL_CNTL_SMC_PLL_CNTL_AG_MUX_SELECT_REG_ADDR + 0x8,
//   0x01111111); // Peripheral PLL clock mux select
// }

// static inline void program_clocks(void)
// {
//   // Hardware automatically configures CGM registers from efuse values
//   // via i_cgm_init_code inputs. SMC ROM only needs to configure mux selection.

//   if (smc_strap_is_bl0_pllclk_enabled()) {
//     // PLL mode: Wait for PLL lock completion (CGMs configured automatically from efuse)
//     wait_for_cgm_locks_smc();

//     // Switch all clock muxes to use PLL sources
//     switch_pll_mux_functional();
//   } else {
//     // RefClk mode: Core runs directly from 100MHz refclk, only configure peripheral clock
//     configure_cgm2_peripheral_200mhz();   // CGM2: Peripheral clock at 200MHz
//   }
// }

#endif /* SMC_DEFINES_H */
