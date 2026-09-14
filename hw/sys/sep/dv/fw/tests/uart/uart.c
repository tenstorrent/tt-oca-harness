/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "test_completion.h"
#include "uart_16550_dl_reg.h"
#include "uart_16550_main_reg.h"
#include "uart_16550_main_wo_reg.h"
#include "sep_outbound_filter.h"

int main(void) {
    // Initialize outbound filter to allow testpass mailbox access
    sep_outbound_filter_init();

    // Variable declarations
    uint32_t wr_data, rd_data;
    int rc = 0;

    // RNG Seeding
    srand(1234); // TODO: Replace with dynamic seeding

    // Register sanity test
    printf("Checking register interface connectivity...\n");
    wr_data = rand() & 0xff;
    *((volatile uint32_t *)(0x44000000 + SCR_REG_OFFSET)) = wr_data;
    printf("Wrote data 0x%x to SCR.\n", wr_data);
    rd_data = *((volatile uint32_t *)(0x44000000 + SCR_REG_OFFSET));
    if (rd_data != wr_data) {
        printf("Register interface test failed: Read value 0x%x does not match write value 0x%x!\n",
               rd_data, wr_data);
        rc = -1;
        goto done;
    }
    printf("Successfully read back write value 0x%x from SCR register!\n", rd_data);

    // UART loopback test
    printf("Configuring UART...\n");
    uint32_t baud_rate = 921600;
    uint32_t uart_clk_hz = 100000000; // 100 MHz
    // The baud generator divides by (divisor + 1); round to nearest before
    // subtracting so truncation does not cost a whole count.
    uint32_t divisor = (uart_clk_hz + 8 * baud_rate) / (16 * baud_rate) - 1;
    printf("Setting baud rate to %d, divisor = %d...\n", baud_rate, divisor);
    *((volatile uint32_t *)(0x44000000 + LCR_REG_OFFSET)) =
        0x83; // Mux to DL address map. 8 data bits, no parity, 1 stop bit.
    *((volatile uint32_t *)(0x44000000 + DLL_REG_OFFSET)) =
        divisor & 0xff; // divisor low byte
    *((volatile uint32_t *)(0x44000000 + DLM_REG_OFFSET)) = divisor >> 8 & 0xff; // divisor high byte
    *((volatile uint32_t *)(0x44000000 + LCR_REG_OFFSET)) = 0x03; // Return to main address map
    *((volatile uint32_t *)(0x44000000 + MCR_REG_OFFSET)) = 0x10; // Enable system loopback
    printf("Configuration complete!\n");

    printf("Performing UART loopback test...\n");
    wr_data = rand() & 0xff;
    *((volatile uint32_t *)(0x44000000 + THR_REG_OFFSET)) = wr_data;
    printf("Wrote data 0x%x to THR.\n", wr_data);

    uint32_t lsr = *((volatile uint32_t *)(0x44000000 + LSR_REG_OFFSET));
    for (int i = 0; i < 1000; i++) { // Should in theory take 1085 clock cycles to fully send data
                                     // given clk frequency = 100 MHz and baud rate = 921600
        *((volatile uint32_t *)(0x44000000 + SCR_REG_OFFSET)) = 0x0;
    }
    while (!(lsr & UART_16550_MAIN_LSR_DR_MASK)) {
        printf("Waiting for data to be ready in RBR...\n");
        for (int i = 0; i < 1000; i++) {
            *((volatile uint32_t *)(0x44000000 + SCR_REG_OFFSET)) = 0x0;
        }
        lsr = *((volatile uint32_t *)(0x44000000 + LSR_REG_OFFSET));
    }
    rd_data = *((volatile uint32_t *)(0x44000000 + RBR_REG_OFFSET));
    printf("Data 0x%x read from RBR.\n", rd_data);
    if (rd_data != wr_data) {
        printf("UART test failed: Data does not match expected value! Expected 0x%x.\n", wr_data);
        rc = -1;
        goto done;
    }
    printf("UART loopback test passed: Data matches expected value!\n");
    rc = 0;

done:
    if (rc == 0) {
        test_pass(0);
    } else {
        test_fail(1);
    }

    // Keep CPU alive after signaling completion.
    while (1) {
        __asm__("wfi");
    }
}
