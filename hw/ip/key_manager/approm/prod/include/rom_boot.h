/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_boot.h
 * @brief Key Manager one-time boot sequence.
 *
 * Declares rom_boot_init() so production firmware (rom_main.c) and
 * tests that exercise the boot path can link the same implementation.
 */

#ifndef ROM_BOOT_H
#define ROM_BOOT_H

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Enable SRAM scrambler and restart CPU from reset vector.
 *
 * Implemented in assembly; never returns. Use after writing the
 * scrambler key. Works when .text is in VROM (uses LUI+JALR to 0).
 */
void rom_boot_sram_restart(void) __attribute__((noreturn));

/**
 * @brief Query whether boot-time wipe/shred operations are enabled.
 *
 * Weak default returns the compile-time `ROM_KM_BOOT_WIPE_DEFAULT`
 * setting (enabled by default). Tests may still override this to skip
 * expensive boot wipe/shred operations.
 *
 * @return 1 when boot wipe/shred is enabled; 0 to disable.
 */
int rom_boot_wipe_enabled(void);

/**
 * @brief Query whether unrecoverable-fault wipe/shred is enabled.
 *
 * Weak default returns the compile-time `ROM_KM_UNREC_WIPE_DEFAULT`
 * setting (enabled by default). Tests may override this independently
 * from boot wipe behavior.
 *
 * @return 1 when unrecoverable wipe/shred is enabled; 0 to disable.
 */
int rom_unrec_wipe_enabled(void);

/**
 * @brief Execute the KM hardware initialisation sequence.
 *
 * Steps are performed in strict order; a step may restart the CPU
 * (SRAM scrambler first-time init) so the function must be
 * idempotent with respect to the hardware state that persists
 * across a warm restart (scrambler enabled + locked).
 */
void rom_boot_init(void);

#ifdef __cplusplus
}
#endif

#endif /* ROM_BOOT_H */
