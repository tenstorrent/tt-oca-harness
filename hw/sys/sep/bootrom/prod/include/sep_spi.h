/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// OCAH SEP ROM SPI init API.

#pragma once

#include <stdbool.h>
#include <stdint.h>

// Set the flash address rotation (swap primary/backup offsets).
// Must be called before spi_init() if rotate is needed.
void spi_set_rotate(bool rotate);

// Initialise the memory-mapped (XIP) flash controller. To be called once before
// using the SPI flash memory space.
//
// Returns 0 on success, non-zero on failure.
uint32_t spi_init(void);

// Re-initialise SPI, typically after primary manifest validation fails to
// restart the SPI init sequence using the backup TLV.
//
// Returns 0 on success, non-zero on failure.
uint32_t spi_reinit(void);

// Report if primary TLV failed.
bool spi_primary_tlv_failed(void);

// Inform the SPI init code of the sysclk frequency (MHz).
void spi_set_sysclk(uint16_t freq_mhz);
