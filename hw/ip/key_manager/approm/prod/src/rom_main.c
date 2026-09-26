/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_main.c
 * @brief Key Manager ROM firmware entry point.
 */

#include "rom_boot.h"
#include "rom_main_step.h"

/**
 * @brief Entry point: run boot init then message loop (never returns).
 *
 * @return 0 (unreachable; rom_main loops forever).
 */
int main(void) {
    rom_boot_init();
    while (1) rom_main_step();
    return 0;
}
