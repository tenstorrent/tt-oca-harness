/* SPDX-License-Identifier: Apache-2.0 */
/* Test-only OTP helper surface used by imported KM firmware tests. */
#ifndef ROM_OTP_H
#define ROM_OTP_H

#include <stdint.h>
#include "test_common.h"

#define ROM_KM_OTP_WORDS 8u
#define ROM_KM_OTP_CHANGE_LIFE_CYCLE_bm 0x01u
#define ROM_KM_OTP_CHANGE_DEMOTION_bm   0x02u
#define ROM_KM_OTP_CHANGE_CHIPLET_UID_bm 0x04u
#define ROM_KM_OTP_CHANGE_SIP_UID_bm    0x08u
#define ROM_KM_OTP_CHANGE_SYS_UID_bm    0x10u
#define ROM_KM_OTP_CHANGE_CLASS_KEY_bm  0x20u
#define ROM_KM_OTP_CHANGE_ALL_MASK      0x3fu

#define KM_CSR_OTP_READ_LOCK_REG_CHIPLET_UID_MASK 0x01u
#define KM_CSR_OTP_READ_LOCK_REG_SIP_UID_MASK     0x02u
#define KM_CSR_OTP_READ_LOCK_REG_SYS_UID_MASK     0x04u
#define KM_CSR_OTP_READ_LOCK_REG_CLASS_KEY_MASK   0x08u

#define ROM_KM_IRQ_STATUS_OTP_CHANGE_MASK 0x100u

#define ROM_OTP_LIFE_CYCLE      (*(volatile uint32_t *)KEY_MANAGER_KMCSR_OTP_LIFE_CYCLE_BASE_ADDR)
#define ROM_OTP_DEMOTION_STATE  (*(volatile uint32_t *)KEY_MANAGER_KMCSR_OTP_DEMOTION_STATE_BASE_ADDR)
#define ROM_OTP_READ_LOCK       (*(volatile km_csr__otp_read_lock_reg_t *)KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR)
#define ROM_OTP_READ_LOCK_REG   ROM_OTP_READ_LOCK

void rom_otp_on_change(uint32_t changed_mask);

static inline void rom_otp_fill_pattern(uint32_t out[ROM_KM_OTP_WORDS], uint32_t byte_base)
{
    for (uint32_t i = 0; i < ROM_KM_OTP_WORDS; i++) {
        uint32_t b = byte_base + (i * 4u);
        out[i] = b | ((b + 1u) << 8) | ((b + 2u) << 16) | ((b + 3u) << 24);
    }
}

static inline int rom_otp_read_life_cycle(uint8_t *life_cycle)
{
    *life_cycle = 0x5u;
    return 0;
}

static inline int rom_otp_read_demotion(uint8_t *demotion)
{
    *demotion = 0x1u;
    return 0;
}

static inline int rom_otp_read_chiplet_uid(uint32_t out[ROM_KM_OTP_WORDS])
{
    rom_otp_fill_pattern(out, 0u);
    return 0;
}

static inline int rom_otp_read_sip_uid(uint32_t out[ROM_KM_OTP_WORDS])
{
    rom_otp_fill_pattern(out, 0x20u);
    return 0;
}

static inline int rom_otp_read_sys_uid(uint32_t out[ROM_KM_OTP_WORDS])
{
    rom_otp_fill_pattern(out, 0x40u);
    return 0;
}

static inline int rom_otp_read_class_key(uint32_t out[ROM_KM_OTP_WORDS])
{
    rom_otp_fill_pattern(out, 0x60u);
    return 0;
}

static inline void rom_otp_set_read_lock(uint32_t mask)
{
    ROM_OTP_READ_LOCK.w |= mask;
}

static inline uint32_t rom_otp_get_change_status(void)
{
    return 0;
}

static inline void rom_otp_clear_change_status(uint32_t mask)
{
    (void)mask;
}

static inline uint32_t rom_otp_read32(uint32_t addr)
{
    return *(volatile uint32_t *)addr;
}

static inline void rom_otp_write32(uint32_t addr, uint32_t value)
{
    *(volatile uint32_t *)addr = value;
}

#endif /* ROM_OTP_H */
