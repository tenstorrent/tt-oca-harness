/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_drbg.c
 * @brief DRBG sampler driver implementation
 *
 * All register access goes through volatile pointers and
 * PeakRDL-generated types from key_manager.h / key_manager_addr.h.
 */

#include "rom_drbg.h"
#include "key_manager_fw.h"

/**
 * @brief Read the DRBG status register.
 *
 * @return Raw 32-bit value of DRBG_SAMPLER_STATUS_REG.
 */
uint32_t rom_drbg_status_read(void) {
    return ROM_DRBG_STATUS_REG.w;
}

/**
 * @brief Read a single random word from the DRBG.
 *
 * @return 32-bit random value from DRBG_SAMPLER_DATA_REG.
 */
uint32_t rom_drbg_get_word(void) {
    return ROM_DRBG_DATA_REG.w;
}

/** @brief DRBG status register (volatile). */
#define DRBG_STATUS \
    (*(volatile km_drbg_sampler__status_reg_t *)KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR)
/** @brief DRBG configuration register (volatile). */
#define DRBG_CFG (*(volatile km_drbg_sampler__cfg_reg_t *)KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR)

/**
 * @brief Block until the DRBG hardware is ready.
 */
void rom_drbg_init(void) {
    while (!DRBG_STATUS.f.drbg_ready)
        ;
}

/**
 * @brief Fill a buffer with DRBG output using prefetch for throughput.
 *
 * Each word is taken from DATA, not from PREFETCH_DATA: only a DATA read
 * consumes the prefetched word and starts the next fetch. PREFETCH_DATA is a
 * read-only debug mirror of the same holding register, so reading it in a loop
 * would return one value repeatedly.
 *
 * @param[out] buf   Output buffer (must hold at least count words).
 * @param[in] count  Number of 32-bit words to fill.
 */
void rom_drbg_get_block(uint32_t *buf, uint8_t count) {
    km_drbg_sampler__cfg_reg_t cfg;

    cfg.w = DRBG_CFG.w;
    cfg.f.prefetch = 1;
    DRBG_CFG.w = cfg.w;

    for (uint8_t i = 0; i < count; i++) buf[i] = ROM_DRBG_DATA_REG.w;

    cfg.w = DRBG_CFG.w;
    cfg.f.prefetch = 0;
    DRBG_CFG.w = cfg.w;
}
