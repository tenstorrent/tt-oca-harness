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
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)((SMC_EXTERNAL_MANDATORY_GPIO_CTRL_0__REG_MAP_BASE_ADDR +
                                          gpio_num * gpio_spacing) +
                                         offset);
    *p_addr = value;
}

static inline uint32_t read_gpio_shim(uint8_t gpio_num, uint32_t offset) {
    uint32_t gpio_spacing = 0x20;
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)((SMC_EXTERNAL_MANDATORY_GPIO_CTRL_0__REG_MAP_BASE_ADDR +
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

static inline void write_pll_ctrl_reg(uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t
             *)(uintptr_t)(SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_PLL_CNTL_REG_MAP_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint32_t read_pll_ctrl_reg(uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t
             *)(uintptr_t)(SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_PLL_CNTL_REG_MAP_BASE_ADDR + offset);
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
        (volatile uint16_t
             *)(uintptr_t)(SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_REG_ADDR +
                           id * 0x100 + offset);
    *p_addr = value;
}

static inline uint32_t read_cgm_pll_reg(uint32_t id, uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t
             *)(uintptr_t)(SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_PLL_CNTL_CGM_0_STATUS_REG_ADDR +
                           id * 0x100 + offset);
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

/* Auxiliary chiplet PLL configuration functions */

#endif /* SMC_DEFINES_H */
