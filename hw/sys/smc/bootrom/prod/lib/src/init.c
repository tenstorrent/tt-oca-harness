/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Minimal Metal initialization functions for SMC Production ROM */

#include <stddef.h>

/* Minimal metal init/fini functions required by crt0.S */
void metal_init(void) __attribute__((weak));
void metal_init(void) {
    /* Minimal initialization - nothing needed for simple production ROM */
}

void metal_fini(void) __attribute__((weak));
void metal_fini(void) {
    /* Minimal finalization - nothing needed for simple production ROM */
}

void metal_init_run(void) __attribute__((weak));
void metal_init_run(void) {
    metal_init();
}

void metal_fini_run(void) __attribute__((weak));
void metal_fini_run(void) {
    metal_fini();
}
