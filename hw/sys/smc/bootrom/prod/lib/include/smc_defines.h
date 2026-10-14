/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* SMC Defines - Register access and utility functions
 */

#ifndef SMC_DEFINES_H
#define SMC_DEFINES_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "smc_addr.h"
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
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_periph_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_dma_ctrl_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_DMA_CTRL_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_dma_ctrl_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_DMA_CTRL_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_zeroer_ctrl_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_ZEROER_CTRL_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_zeroer_ctrl_reg(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_ZEROER_CTRL_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_spm(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    *p_addr = value;
}

static inline void write_spm64(uint64_t offset, uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint64_t read_spm(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    return *p_addr;
}

static inline uint64_t read_spm64(uint64_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SPM_MEMORY_BASE_ADDR + offset);
    return *p_addr;
}

static inline void write_smc_reg(uint64_t offset, uint64_t value) {
    volatile uint64_t *addr_ptr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    *addr_ptr = value;
}

static inline uint64_t read_smc_reg(uint64_t offset) {
    volatile uint64_t *addr_ptr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR + offset);
    return *addr_ptr;
}

static inline void write_scratch(uint8_t scratch_num, uint32_t value) {
    volatile uint64_t *addr =
        (volatile uint64_t *)(uintptr_t)SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(scratch_num);
    *addr = value;
}

static inline uint32_t read_scratch(uint8_t scratch_num) {
    volatile uint64_t *addr =
        (volatile uint64_t *)(uintptr_t)SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(scratch_num);
    return (uint32_t)*addr;
}

/* Legacy POST code function - writes to scratch register 0 (pass/fail)
 * For structured POST code management, use smc_post_code.h API instead */
static inline void write_postcode(uint32_t value) {
    write_scratch(0, value);
}

/* Mailbox pair spacing and inbound-half offset, both taken from the generated map. */
#define SMC_MAILBOX_STRIDE \
    (SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_1_BASE_ADDR - \
     SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define SMC_MAILBOX_INBOUND_OFFSET \
    (SMC_TOP_SMC_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR - \
     SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)

static inline void write_mailbox(uint8_t mailbox_num, uint8_t is_inbound, uint32_t offset,
                                 uint64_t value) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR +
                                         mailbox_num * SMC_MAILBOX_STRIDE +
                                         is_inbound * SMC_MAILBOX_INBOUND_OFFSET + offset);
    *p_addr = value;
}

static inline uint64_t read_mailbox(uint8_t mailbox_num, uint8_t is_inbound, uint32_t offset) {
    volatile uint64_t *p_addr =
        (volatile uint64_t *)(uintptr_t)(SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR +
                                         mailbox_num * SMC_MAILBOX_STRIDE +
                                         is_inbound * SMC_MAILBOX_INBOUND_OFFSET + offset);
    return *p_addr;
}

static inline void write_gpio_shim(uint8_t gpio_num, uint32_t offset, uint32_t value) {
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR(
                                             gpio_num) +
                                         offset);
    *p_addr = value;
}

static inline uint32_t read_gpio_shim(uint8_t gpio_num, uint32_t offset) {
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR(
                                             gpio_num) +
                                         offset);
    return *p_addr;
}

static inline void write_gpio(uint8_t gpio_num, uint32_t offset, uint32_t value) {
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_GPIO_INTF_BASE_ADDR(gpio_num) + offset);
    *p_addr = value;
}

static inline uint32_t read_gpio(uint8_t gpio_num, uint32_t offset) {
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_GPIO_INTF_BASE_ADDR(gpio_num) + offset);
    return *p_addr;
}

static inline void write_apb2avsbus_ctrl_reg(uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR + offset);
    *p_addr = value;
}

static inline uint32_t read_abp2avsbus_ctrl_reg(uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR + offset);
    return *p_addr;
}

/* An out-of-range UART ID selects the last instance. */
static inline uint32_t smc_uart_instance(int uart_id) {
    return (uint32_t)uart_id < SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_NUM
               ? (uint32_t)uart_id
               : SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_NUM - 1;
}

static inline void write_uart_reg(int uart_id, uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(
                                             smc_uart_instance(uart_id)) +
                                         offset);
    *p_addr = value;
}

static inline uint32_t read_uart_reg(int uart_id, uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t *)(uintptr_t)(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(
                                             smc_uart_instance(uart_id)) +
                                         offset);
    return *p_addr;
}

static inline void write_uart_engine_reg(int uart_id, uint32_t offset, uint32_t value) {
    volatile uint16_t *p_addr =
        (volatile uint16_t
             *)(uintptr_t)(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(
                               smc_uart_instance(uart_id)) +
                           offset);
    *p_addr = value;
}

static inline uint32_t read_uart_engine_reg(int uart_id, uint32_t offset) {
    volatile uint16_t *p_addr =
        (volatile uint16_t
             *)(uintptr_t)(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(
                               smc_uart_instance(uart_id)) +
                           offset);
    return *p_addr;
}

static inline void write_beu_reg(int hartid, uint64_t offset, uint64_t value) {
    uint64_t base_addr;
    if (hartid == 0) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR;
    } else if (hartid == 1) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR;
    } else if (hartid == 2) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR;
    } else {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(base_addr + offset);
    *p_addr = value;
}

static inline uint64_t read_beu_reg(int hartid, uint64_t offset) {
    uint64_t base_addr;
    if (hartid == 0) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR;
    } else if (hartid == 1) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR;
    } else if (hartid == 2) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR;
    } else {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(base_addr + offset);
    return *p_addr;
}

static inline void write_wdt_reg(int hartid, uint64_t offset, uint64_t value) {
    uint64_t base_addr;
    if (hartid == 0) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR;
    } else if (hartid == 1) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR;
    } else if (hartid == 2) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR;
    } else {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(base_addr + offset);
    *p_addr = value;
}

static inline uint64_t read_wdt_reg(int hartid, uint64_t offset) {
    uint64_t base_addr;
    if (hartid == 0) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR;
    } else if (hartid == 1) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR;
    } else if (hartid == 2) {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR;
    } else {
        base_addr = SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR;
    }

    volatile uint64_t *p_addr = (volatile uint64_t *)(uintptr_t)(base_addr + offset);
    return *p_addr;
}

#endif /* SMC_DEFINES_H */
