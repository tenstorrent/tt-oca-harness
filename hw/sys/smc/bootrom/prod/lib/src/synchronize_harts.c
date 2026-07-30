/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * Minimal hart synchronization for SMC Production ROM
 *
 * @file synchronize_harts.c
 */

// Function prototype to satisfy -Wmissing-prototypes
void __metal_synchronize_harts(void);

/* Minimal hart synchronization function required by crt0.S */
__attribute__((section(".init"))) void __metal_synchronize_harts(void) {
    /* For single-hart production ROM, no synchronization needed */
}
