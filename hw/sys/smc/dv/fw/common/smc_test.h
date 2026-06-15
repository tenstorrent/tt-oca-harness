#ifndef __SMC_TEST_H_DEFINED__
#define __SMC_TEST_H_DEFINED__

#include <stdbool.h>

#include "smc_defines.h"
#include "virt_console.h"

#define TEST_PASS 0xacafaca1
#define TEST_FAIL 0xffffffff
#define TEST_ROM_PASS 0x77777777
#define TEST_STATUS_SCRATCH 0

#define ERROR_STATUS_REG 2
#define ERROR_COUNT_REG 3
#define SEED_REG 3

static uint32_t _ERROR_CNT;
extern uint32_t _RANDOM_LFSR;
static uint32_t _TEST_CONTROL;

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
  write_scratch(ERROR_STATUS_REG,
                ((hartid & 0xff) << 24U) | (info_code & 0x00ffffff));
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
  write_scratch(ERROR_STATUS_REG,
                ((hartid & 0xff) << 24U) | (code & 0x000fffff) | 0x00E00000);
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

static inline void raise_error_hex32_s(int hartid, const char *msg,
                                       uint32_t val) {
  _ERROR_CNT++;
  simputs("[ERROR] Core[");
  simputhex16(hartid);
  simputs("]: ");
  simputs(msg);
  simputhex32(val);
  simputs("\n");
}

/* Fatal error wrappers ******************************************************/
static inline __attribute__((noreturn)) void raise_fatal(int hartid,
                                                         uint32_t code) {
  raise_error(hartid, code);
  test_fail(hartid);
}

static inline __attribute__((noreturn)) void raise_fatal_s(int hartid,
                                                           const char *msg) {
  raise_error_s(hartid, msg);
  test_fail(hartid);
}

static inline __attribute__((noreturn)) void raise_fatal_hex32_s(
    int hartid, const char *msg, uint32_t val) {
  raise_error_hex32_s(hartid, msg, val);
  test_fail(hartid);
}

/* Test lifecycle ************************************************************/
static inline void init_test(int hartid) {
  (void)hartid; // TODO this is unused
  const uint32_t seed = read_scratch(SEED_REG);
  simputshex32("Seeding test: ", seed);
  _RANDOM_LFSR = seed;

  _TEST_CONTROL = read_reg(SMC_CPU_CTRL_TEST_CTRL_REG_ADDR);
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
  const uint32_t bit = ((_RANDOM_LFSR >> 0) ^ (_RANDOM_LFSR >> 1) ^
                        (_RANDOM_LFSR >> 21) ^ (_RANDOM_LFSR >> 31)) &
                       1U;
  return _RANDOM_LFSR = (_RANDOM_LFSR >> 1) | (bit << 31);
}


static inline bool error_on_bad_cab1e(int hartid, uint32_t val) {
  if(val == 0x0badcab1e) {
    raise_error_s(hartid, "Bad Cable detected!");
    return true;
  }
  return false;
}

static inline bool gpio_bad_cab1e_check(int hartid, int gpio_num, uint32_t val) {
  // There is currently a mismatch between RDL and physical GPIO numbering to work around how demux select is done in padring
  // Physical GPIOs 68-77 are for JTAG and are NOT APB-accessible
  // There are 3 more APB targets -- refclk ctrl + POC & PBIAS Ctrl + Dummy 'ERR Slave'
  // In the demux, they are contiguous with GPIOs 0-67, so we should treat them like that here
  // GPIO [] is ERR slv and is expected to return 0x0badcab1e
  // Therefore treat JTAG GPIOs as GPIOs 71-80
  if(val == 0x0badcab1e) {
    if (gpio_num == 74) { // TODO update index once gpio_shim err_slv added
      return false;
    } else {
      raise_error_s(hartid, "Bad Cable detected!");
      return true;
    }
  } else {
    if (gpio_num == 74)
    { // TODO update index once gpio_shim err_slv added
      raise_error_s(hartid, "Should be Bad Cable!");
      info_msg_hex32_s(hartid, "Instead received: ", val);
      return true;
    }
    else
    {
      return false;
    }
  }


  return false;
}

#endif