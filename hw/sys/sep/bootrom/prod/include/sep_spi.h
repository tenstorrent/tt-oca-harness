/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// External flash controller hooks for the memory-mapped (XIP window) transport
// (BOOT_SPI_CONTROLLER_OT=0). The default stubs in src/sep_spi.c report the
// controller as absent; an integrator overrides them with
// NONFREE_BOOTCODE_SOURCES.

#pragma once

#include <stdbool.h>
#include <stdint.h>

// Swap the primary and backup slots. Must be called before spi_init().
void spi_set_rotate(bool rotate);

// Bring up the controller so flash reads through the XIP window succeed.
// Returns 0 on success, non-zero on failure.
uint32_t spi_init(void);

// Bring the controller up again against the backup slot's configuration record
// after the primary slot fails validation.
// Returns 0 on success, non-zero on failure.
uint32_t spi_reinit(void);

// True iff the primary slot's flash controller configuration record was unusable.
bool spi_primary_tlv_failed(void);

// Pass the system clock frequency (MHz) to the controller bring-up.
void spi_set_sysclk(uint16_t freq_mhz);
