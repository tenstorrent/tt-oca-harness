/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_drbg.c
 * @brief DRBG sampler driver implementation
 *
 * All register access goes through volatile pointers and
 * PeakRDL-generated types from key_manager_regs.h.
 */

#include "rom_drbg.h"
#include "key_manager_regs.h"

/**
 * @brief Read the DRBG status register.
 *
 * @return Raw 32-bit value of DRBG_SAMPLER_STATUS_REG.
 */
uint32_t rom_drbg_status_read(void)
{
    return ROM_DRBG_STATUS_REG.val;
}

/**
 * @brief Read a single random word from the DRBG.
 *
 * @return 32-bit random value from DRBG_SAMPLER_DATA_REG.
 */
uint32_t rom_drbg_get_word(void)
{
    return ROM_DRBG_DATA_REG.val;
}

/** @brief DRBG status register (volatile). */
#define DRBG_STATUS   (*(volatile KM_DRBG_SAMPLER_STATUS_REG_reg_u *)DRBG_SAMPLER_STATUS_REG_ADDR)
/** @brief DRBG configuration register (volatile). */
#define DRBG_CFG      (*(volatile KM_DRBG_SAMPLER_CFG_REG_reg_u *)DRBG_SAMPLER_CFG_REG_ADDR)
/** @brief DRBG prefetch data register (volatile). */
#define DRBG_PREFETCH (*(volatile KM_DRBG_SAMPLER_PREFETCH_DATA_REG_reg_u *)DRBG_SAMPLER_PREFETCH_DATA_REG_ADDR)

/**
 * @brief Block until the DRBG hardware is ready.
 */
void rom_drbg_init(void)
{
    while (!DRBG_STATUS.f.drbg_ready)
        ;
}

/**
 * @brief Fill a buffer with DRBG output using prefetch for throughput.
 *
 * @param[out] buf   Output buffer (must hold at least count words).
 * @param[in] count  Number of 32-bit words to fill.
 */
void rom_drbg_get_block(uint32_t *buf, uint8_t count)
{
    KM_DRBG_SAMPLER_CFG_REG_reg_u cfg;

    cfg.val = DRBG_CFG.val;
    cfg.f.prefetch = 1;
    DRBG_CFG.val = cfg.val;

    for (uint8_t i = 0; i < count; i++)
        buf[i] = DRBG_PREFETCH.val;

    cfg.val = DRBG_CFG.val;
    cfg.f.prefetch = 0;
    DRBG_CFG.val = cfg.val;
}
