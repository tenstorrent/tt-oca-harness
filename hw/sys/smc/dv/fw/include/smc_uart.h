/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SMC_UART_H
#define SMC_UART_H

#include "smc_reg_access.h"

static inline void write_uart_reg(int uart_id, uint32_t offset, uint32_t value) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
    } else {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    *p_addr = value;
}

static inline uint32_t read_uart_reg(int uart_id, uint32_t offset) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
    } else {
        BASE_ADDRESS_UART = SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    return *p_addr;
}

static inline void write_uart_engine_reg(int uart_id, uint32_t offset, uint32_t value) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(0);
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(1);
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(2);
    } else {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(3);
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    *p_addr = value;
}

static inline uint32_t read_uart_engine_reg(int uart_id, uint32_t offset) {
    uint32_t BASE_ADDRESS_UART;
    if (uart_id == 0) {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(0);
    } else if (uart_id == 1) {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(1);
    } else if (uart_id == 2) {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(2);
    } else {
        BASE_ADDRESS_UART =
            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_BASE_ADDR(3);
    }

    volatile uint16_t *p_addr = (volatile uint16_t *)(uintptr_t)(BASE_ADDRESS_UART + offset);
    return *p_addr;
}

#endif /* SMC_UART_H */
