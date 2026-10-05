/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_GPIO_H
#define SMC_GPIO_H

#include "gpio_intf_addr.h"
#include "smc_reg_access.h"

static inline void write_gpio(uint8_t gpio_num, uint32_t offset, uint32_t value) {
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_GPIO_INTF_BASE_ADDR((gpio_num)) + offset);
    *p_addr = value;
}

static inline void write_gpio_shim(uint8_t gpio_num, uint32_t offset, uint32_t value) {
    uint32_t gpio_spacing = 0x20;
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)(SMC_TOP_GPIO_CTRL_BASE_ADDR(0) +
                                                                 gpio_num * gpio_spacing + offset);
    *p_addr = value;
}

static inline uint32_t read_gpio(uint8_t gpio_num, uint32_t offset) {
    volatile uint32_t *p_addr =
        (volatile uint32_t *)(uintptr_t)(SMC_TOP_GPIO_INTF_BASE_ADDR((gpio_num)) + offset);
    return *p_addr;
}

static inline uint32_t read_gpio_shim(uint8_t gpio_num, uint32_t offset) {
    uint32_t gpio_spacing = 0x20;
    volatile uint32_t *p_addr = (volatile uint32_t *)(uintptr_t)(SMC_TOP_GPIO_CTRL_BASE_ADDR(0) +
                                                                 gpio_num * gpio_spacing + offset);
    return *p_addr;
}

#endif /* SMC_GPIO_H */
