/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_drbg.h
 * @brief DRBG sampler driver for Key Manager firmware
 *
 * Provides initialization, status query, single-word read, and bulk
 * (prefetch) read from the hardware DRBG sampler.
 */

#ifndef ROM_DRBG_H
#define ROM_DRBG_H

#include <stdint.h>

#include "key_manager_fw.h"

/** @brief DRBG sampler status register (volatile, read-only). */
#define ROM_DRBG_STATUS_REG \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)
/** @brief DRBG sampler data register (volatile, read-only). */
#define ROM_DRBG_DATA_REG \
    (*(volatile km_drbg_sampler__data_reg_t *)KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR)

/**
 * @brief Read the DRBG status register.
 *
 * @return Raw 32-bit value of DRBG_SAMPLER_STATUS_REG.
 */
uint32_t rom_drbg_status_read(void);

/**
 * @brief Read a single random word from the DRBG.
 * @return 32-bit random value from DRBG_SAMPLER_DATA_REG.
 */
uint32_t rom_drbg_get_word(void);

/**
 * @brief Initialize the DRBG sampler.
 *
 * Polls DRBG_SAMPLER_STATUS_REG.drbg_ready with no timeout.
 * If the DRBG never becomes ready the KM stays here until the SEP
 * performs a hard reset.
 */
void rom_drbg_init(void);

/**
 * @brief Read multiple random words using the DRBG prefetch path.
 *
 * Enables prefetch, reads @p count words from DATA, then disables prefetch.
 * Reads go to DATA rather than PREFETCH_DATA because only a DATA read consumes
 * the prefetched word and starts the next fetch.
 *
 * @param buf Destination buffer (must hold at least @p count words).
 * @param count Number of 32-bit words to read.
 */
void rom_drbg_get_block(uint32_t *buf, uint8_t count);

#endif /* ROM_DRBG_H */
