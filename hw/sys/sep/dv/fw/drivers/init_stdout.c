/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdio.h>  // This should be the picolibc stdio.h in newlib/libc/tinystdio/stdio.h
#include <stdlib.h>
#include <stdint.h>

#include "tb.h"

static int sep_putc(char c, FILE *file);
static int sep_getc(FILE *file);

static FILE __stdio = FDEV_SETUP_STREAM(sep_putc, sep_getc, NULL, _FDEV_SETUP_WRITE);
FILE *const stdout = &__stdio;
__strong_reference(stdout, stderr);
__strong_reference(stdout, stdin);  // Shouldnt work but here for completeness

static int sep_putc(char c, FILE *file) {

    // TB STDOUT mailbox expects byte writes (WSTRB=0x01) for character output.
    // Use an 8-bit store so the AXI write strobes match the TB data-channel filter.
    volatile uint8_t *stdout_ptr = (volatile uint8_t *)STDOUT;
    *stdout_ptr = (uint8_t)c;
	return c;

}

static int sep_getc(FILE *file) {

    printf("ERROR: Tried to read from stdin, this is not supported\n");
    // exit(1);

}
