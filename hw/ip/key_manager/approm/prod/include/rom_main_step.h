/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef ROM_MAIN_STEP_H
#define ROM_MAIN_STEP_H

/**
 * @file rom_main_step.h
 * @brief Key Manager firmware main-loop step interface.
 */

/**
 * @brief Run one Key Manager firmware main-loop iteration.
 *
 * Processes pending RX work, then sleeps atomically with respect to IRQ
 * dispatch when no complete frame is buffered.
 */
void rom_main_step(void);

#endif /* ROM_MAIN_STEP_H */
