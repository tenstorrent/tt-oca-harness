/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef __SMC_TEST_H_DEFINED__
#define __SMC_TEST_H_DEFINED__

#include <stdbool.h>

#include "smc_cla_boot.h"
#include "smc_io.h"
#include "virt_console.h"

#define TEST_PASS 0xacafaca1
#define TEST_FAIL 0xffffffff
#define TEST_ROM_PASS 0x77777777
#define TEST_STATUS_SCRATCH 0

#define SMU_SEP_DV_CLA_ARM_TOKEN 0x02200100u

/* Scratch register allocation. These indices ALIAS; recorded because the
 * aliasing is not obvious from the names and the TB relies on it.
 *
 *   0  TEST_STATUS_SCRATCH -- the pass/fail verdict. monitor_test() polls it
 *      against TEST_PASS / TEST_FAIL / TEST_ROM_PASS, so anything else written
 *      here can decide the run's outcome. Never use it for data.
 *   1  FW status. The TB logs every change as "FW Status:" and, with
 *      +PRINT_POST_CODES, runs it through decode_post_code().
 *   2  ERROR_STATUS_REG *and* the virtual-console byte stream. virt_console()
 *      in smc_utils.py decodes every write here as up to three ASCII
 *      characters, so raising an error corrupts the console transcript and
 *      writing console text overwrites the error status.
 *   3  ERROR_COUNT_REG *and* SEED_REG -- the same index, below.
 *
 * ERROR_COUNT_REG and SEED_REG are both 3, so raise_error()'s count write at
 * the bottom of this file lands on the register the seed was delivered in, and
 * get_seed() reads whatever was written last. The TB owns that register too:
 * smc_api.py programs SCRATCH[3] with the ROM seed and reads it back, and
 * smc_ecc_api.py and st_octs_p2_sync_recovery.py both sample it.
 *
 * A test that both raises errors and reads the seed cannot trust either
 * value: every index 0..15 is written by some firmware test, and the seed's
 * index is fixed by the TB contract.
 */
#define ERROR_STATUS_REG 2
#define ERROR_COUNT_REG 3
#define SEED_REG 3

static uint32_t _ERROR_CNT;
extern uint32_t _RANDOM_LFSR;
static uint32_t _TEST_CONTROL;

/* SMU-SEP DV test bring-up **************************************************/
/* Arms the real CLA boot path, then publishes the token that the SV real-CLA
 * liveness monitor waits on before it will let the SEP core run. */
static inline void smu_sep_dv_test_bringup(void) {
    smu_sep_program_real_cla_boot();
    write_scratch(1, SMU_SEP_DV_CLA_ARM_TOKEN);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* Core test control *********************************************************/
static inline __attribute__((noreturn)) void test_pass(int mhart_id) {
    write_scratch(mhart_id, TEST_PASS);
    for (;;) asm volatile("wfi");
}

static inline __attribute__((noreturn)) void test_fail(int mhart_id) {
    write_scratch(mhart_id, TEST_FAIL);
    for (;;) asm volatile("wfi");
}

static inline __attribute__((noreturn)) void test_rom_pass(int mhart_id) {
    write_scratch(mhart_id, TEST_ROM_PASS);
    for (;;) asm volatile("wfi");
}

/* Diagnostic messaging ******************************************************/
static inline void info_msg(int hartid, uint32_t info_code) {
    write_scratch(ERROR_STATUS_REG, ((hartid & 0xff) << 24U) | (info_code & 0x00ffffff));
}

static inline void info_msg_s(int hartid, const char *msg) {
    simputs("[INFO] Core[");
    simputhex16(hartid);
    simputs("]: ");
    simputs(msg);
    simputs("\n");
}

static inline void info_msg_hex32_s(int hartid, const char *msg, uint32_t val) {
    simputs("[INFO] Core[");
    simputhex16(hartid);
    simputs("]: ");
    simputs(msg);
    simputhex32(val);
    simputs("\n");
}

/* Error handling ************************************************************/
static inline void raise_error(int hartid, uint32_t code) {
    _ERROR_CNT++;
    write_scratch(ERROR_STATUS_REG, ((hartid & 0xff) << 24U) | (code & 0x000fffff) | 0x00E00000);
    write_scratch(ERROR_COUNT_REG, _ERROR_CNT);
}

static inline void raise_error_s(int hartid, const char *msg) {
    _ERROR_CNT++;
    simputs("[ERROR] Core[");
    simputhex16(hartid);
    simputs("]: ");
    simputs(msg);
    simputs("\n");
}

static inline void raise_error_hex32_s(int hartid, const char *msg, uint32_t val) {
    _ERROR_CNT++;
    simputs("[ERROR] Core[");
    simputhex16(hartid);
    simputs("]: ");
    simputs(msg);
    simputhex32(val);
    simputs("\n");
}

/* Fatal error wrappers ******************************************************/
static inline __attribute__((noreturn)) void raise_fatal(int hartid, uint32_t code) {
    raise_error(hartid, code);
    test_fail(hartid);
}

static inline __attribute__((noreturn)) void raise_fatal_s(int hartid, const char *msg) {
    raise_error_s(hartid, msg);
    test_fail(hartid);
}

static inline __attribute__((noreturn)) void raise_fatal_hex32_s(int hartid, const char *msg,
                                                                 uint32_t val) {
    raise_error_hex32_s(hartid, msg, val);
    test_fail(hartid);
}

/* Test lifecycle ************************************************************/
static inline void init_test(int hartid) {
    (void)hartid;
    const uint32_t seed = read_scratch(SEED_REG);
    simputshex32("Seeding test: ", seed);
    _RANDOM_LFSR = seed;

    _TEST_CONTROL = (uint32_t)read64_reg(SMC_TOP_SMC_CPU_CTRL_TEST_CTRL_BASE_ADDR);
    simputshex32("Reading test_ctrl: ", _TEST_CONTROL);
}

static inline uint32_t get_test_control(void) {
    return _TEST_CONTROL;
}

static inline void end_test(int hartid) {
    (_ERROR_CNT > 0) ? test_fail(hartid) : test_pass(hartid);
}

/* Random number utilities ***************************************************/
static inline uint32_t get_random_int(void) {
    const uint32_t bit =
        ((_RANDOM_LFSR >> 0) ^ (_RANDOM_LFSR >> 1) ^ (_RANDOM_LFSR >> 21) ^ (_RANDOM_LFSR >> 31)) &
        1U;
    return _RANDOM_LFSR = (_RANDOM_LFSR >> 1) | (bit << 31);
}

static inline bool error_on_bad_cab1e(int hartid, uint32_t val) {
    if (val == 0x0badcab1e) {
        raise_error_s(hartid, "Bad Cable detected!");
        return true;
    }
    return false;
}

static inline bool gpio_bad_cab1e_check(int hartid, int gpio_num, uint32_t val) {
    // RDL and physical GPIO numbering differ because of how the padring demux selects targets:
    // physical GPIOs 68-77 are JTAG and not APB-accessible, and three more APB targets (two
    // adopter pad-control blocks and the dummy ERR slave) sit contiguous with GPIOs 0-67 in the
    // demux, so the JTAG GPIOs map to indices 71-80 here and index 74 is the ERR slave, which
    // returns 0x0badcab1e.
    if (val == 0x0badcab1e) {
        if (gpio_num == 74) { // ERR slave
            return false;
        } else {
            raise_error_s(hartid, "Bad Cable detected!");
            return true;
        }
    } else {
        if (gpio_num == 74) { // ERR slave
            raise_error_s(hartid, "Should be Bad Cable!");
            info_msg_hex32_s(hartid, "Instead received: ", val);
            return true;
        } else {
            return false;
        }
    }

    return false;
}

#endif
