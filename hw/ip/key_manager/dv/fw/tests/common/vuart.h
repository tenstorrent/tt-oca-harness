/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file vuart.h
 * @brief Virtual UART for firmware-testbench communication during simulation.
 *
 * Provides a simple UART-like interface so firmware tests can use printf(),
 * putc(), getc(), etc., with output captured by the cocotb testbench.
 * In synthesis the VUART registers exist but are unused (no side effects).
 *
 * Usage:
 * @code
 *   #include "vuart.h"
 *
 *   void main() {
 *       vuart_init();  // Optional: VUART is always ready
 *       printf("Hello from firmware!\n");
 *       vuart_puts("Test passed\n");
 *   }
 * @endcode
 */

#ifndef VUART_H
#define VUART_H

#include <stdint.h>
#include <stdarg.h>
#include "key_manager_fw.h"

/* Register access macros using struct types */
#define VUART_TX_REG (*(volatile km_csr__vuart_tx_reg_t *)KEY_MANAGER_KMCSR_VUART_TX_BASE_ADDR)
#define VUART_RX_REG (*(volatile km_csr__vuart_rx_reg_t *)KEY_MANAGER_KMCSR_VUART_RX_BASE_ADDR)
#define VUART_STATUS_REG \
    (*(volatile km_csr__vuart_status_reg_t *)KEY_MANAGER_KMCSR_VUART_STATUS_BASE_ADDR)

/*---------------------------------------------------------------------------
 * Basic VUART Functions
 *---------------------------------------------------------------------------*/

/**
 * Initialize the virtual UART (optional, VUART is always ready)
 */
static inline void vuart_init(void) {
    /* No initialization needed - VUART is always ready */
}

/**
 * Check if TX is ready to accept data
 * @return 1 if ready, 0 otherwise
 */
static inline int vuart_tx_ready(void) {
    return VUART_STATUS_REG.f.tx_ready != 0;
}

/**
 * Check if RX has data available
 * @return 1 if data available, 0 otherwise
 */
static inline int vuart_rx_valid(void) {
    return VUART_STATUS_REG.f.rx_valid != 0;
}

/**
 * Check if VUART printing is enabled
 * @return 1 if printing enabled, 0 otherwise
 */
static inline int vuart_print_enabled(void) {
    return VUART_STATUS_REG.f.print_enable != 0;
}

/**
 * Transmit a single character (blocking)
 * @param c Character to transmit
 */
static inline void vuart_putc(char c) {
    /* TX is always ready: the testbench captures each byte the cycle it is
     * written, so there is no ready wait. */
    VUART_TX_REG.f.tx_byte = (uint32_t)c;
    VUART_TX_REG.f.data_valid = 1;
}

/**
 * Receive a single character (blocking)
 * @return Received character
 */
static inline char vuart_getc(void) {
    while (!vuart_rx_valid()) {
    }

    return (char)VUART_RX_REG.f.rx_byte;
}

/**
 * Transmit a string (blocking)
 * @param s Null-terminated string to transmit
 */
static inline void vuart_puts(const char *s) {
    while (*s) {
        vuart_putc(*s++);
    }
}

/*---------------------------------------------------------------------------
 * Printf Support
 *---------------------------------------------------------------------------
 * These functions enable printf() to work with the VUART.
 * The implementation uses a simple custom printf that doesn't require
 * full C library support.
 */

/**
 * Print unsigned integer in decimal
 */
static inline void vuart_print_uint(uint32_t val) {
    char buf[12]; /* Max 10 digits + sign + null */
    int i = 0;

    if (val == 0) {
        vuart_putc('0');
        return;
    }

    while (val > 0) {
        buf[i++] = (char)('0' + (val % 10));
        val /= 10;
    }

    /* Print in reverse order */
    while (i > 0) {
        vuart_putc(buf[--i]);
    }
}

/**
 * Print signed integer in decimal
 */
static inline void vuart_print_int(int32_t val) {
    if (val < 0) {
        vuart_putc('-');
        val = -val;
    }
    vuart_print_uint((uint32_t)val);
}

/**
 * Print unsigned integer in hexadecimal
 */
static inline void vuart_print_hex(uint32_t val, int width) {
    static const char hex_digits[] = "0123456789ABCDEF";
    int started = 0;

    for (int i = 7; i >= 0; i--) {
        int digit = (val >> (i * 4)) & 0xF;
        if (digit != 0 || started || i < width) {
            vuart_putc(hex_digits[digit]);
            started = 1;
        }
    }

    if (!started) {
        vuart_putc('0');
    }
}

/**
 * Simple printf implementation for firmware
 * Supports: %d, %u, %x, %X, %s, %c, %%
 *
 * @param fmt Format string
 * @param ... Variable arguments
 * @return Number of characters printed
 */
static inline int vuart_printf(const char *fmt, ...) {
    /* Check if printing is enabled - if not, skip all formatting work to save simulation time */
    if (!vuart_print_enabled()) {
        return 0;
    }

    va_list args;
    int count = 0;

    va_start(args, fmt);

    while (*fmt) {
        if (*fmt == '%') {
            fmt++;
            int width = 0;

            /* Parse width (simple: just digits) */
            while (*fmt >= '0' && *fmt <= '9') {
                width = width * 10 + (*fmt - '0');
                fmt++;
            }

            switch (*fmt) {
            case 'd':
            case 'i':
                vuart_print_int(va_arg(args, int32_t));
                break;

            case 'u':
                vuart_print_uint(va_arg(args, uint32_t));
                break;

            case 'x':
            case 'X':
                if (width == 0) width = 1;
                vuart_print_hex(va_arg(args, uint32_t), width);
                break;

            case 's': {
                const char *s = va_arg(args, const char *);
                if (s == 0) s = "(null)";
                vuart_puts(s);
                break;
            }

            case 'c':
                vuart_putc((char)va_arg(args, int));
                count++;
                break;

            case '%':
                vuart_putc('%');
                count++;
                break;

            case '\0':
                /* End of string after % */
                goto done;

            default:
                /* Unknown format, print as-is */
                vuart_putc('%');
                vuart_putc(*fmt);
                count += 2;
                break;
            }
            fmt++;
        } else {
            vuart_putc(*fmt++);
            count++;
        }
    }

done:
    va_end(args);
    return count;
}

/*---------------------------------------------------------------------------
 * Standard I/O Redirects
 *---------------------------------------------------------------------------
 * Define these macros to redirect standard I/O to VUART.
 * Include this header and these will automatically work.
 */

/* Redirect putchar to VUART */
#define putchar(c) vuart_putc(c)

/* Redirect puts to VUART (note: standard puts adds newline) */
#define puts(s) \
    do { \
        vuart_puts(s); \
        vuart_putc('\n'); \
    } while (0)

/* Redirect printf to VUART (simple, works for basic cases) */
#define printf vuart_printf

/* Redirect getchar to VUART */
#define getchar() vuart_getc()

#endif /* VUART_H */
