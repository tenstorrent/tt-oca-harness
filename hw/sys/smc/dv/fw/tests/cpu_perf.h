/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef CPU_PERF_H
#define CPU_PERF_H

#include "smc_io.h"

/****************************/
/* Performance Counters API */
/****************************/

static inline void write_mhpmevent3(uint64_t val) {
    asm volatile("csrw mhpmevent3, %0" ::"r"(val));
}

static inline void write_mhpmevent4(uint64_t val) {
    asm volatile("csrw mhpmevent4, %0" ::"r"(val));
}

static inline void write_mhpmevent5(uint64_t val) {
    asm volatile("csrw mhpmevent5, %0" ::"r"(val));
}

static inline void write_mhpmevent6(uint64_t val) {
    asm volatile("csrw mhpmevent6, %0" ::"r"(val));
}

static inline uint64_t read_mhpmcounter3(void) {
    uint64_t val;
    asm volatile("csrr %0, mhpmcounter3" : "=r"(val));
    return val;
}

static inline uint64_t read_mhpmcounter4(void) {
    uint64_t val;
    asm volatile("csrr %0, mhpmcounter4" : "=r"(val));
    return val;
}

static inline uint64_t read_mhpmcounter5(void) {
    uint64_t val;
    asm volatile("csrr %0, mhpmcounter5" : "=r"(val));
    return val;
}

static inline uint64_t read_mhpmcounter6(void) {
    uint64_t val;
    asm volatile("csrr %0, mhpmcounter6" : "=r"(val));
    return val;
}

/******************************************************/
/* Icache/Dcache Miss & Branch Misprediction Counters */
/******************************************************/

static uint32_t icache_miss_counter;
static uint32_t dcache_miss_counter;
static uint32_t bdm_miss_counter;
static uint32_t btm_miss_counter;

static inline void start_icache_miss_counter(void) {
    uint32_t icache_val = 0x2 | (1 << 8);
    icache_miss_counter = read_mhpmcounter3();
    write_mhpmevent3(icache_val);
}

static inline void start_dcache_miss_counter(void) {
    uint32_t dcache_val = 0x2 | (1 << 9);
    dcache_miss_counter = read_mhpmcounter4();
    write_mhpmevent4(dcache_val);
}

static inline void start_branch_direction_miss_counter(void) {
    uint32_t bdm_val = 0x1 | (1 << 13);
    bdm_miss_counter = read_mhpmcounter5();
    write_mhpmevent5(bdm_val);
}

static inline void start_branch_target_miss_counter(void) {
    uint32_t btm_val = 0x2 | (1 << 14);
    btm_miss_counter = read_mhpmcounter6();
    write_mhpmevent6(btm_val);
}

static inline uint32_t read_icache_miss_counter(void) {
    uint32_t icache_misses = read_mhpmcounter3();
    // Event selector 0 stops the counter without resetting it
    write_mhpmevent3(0);
    return icache_misses - icache_miss_counter;
}

static inline uint32_t read_dcache_miss_counter(void) {
    uint32_t dcache_misses = read_mhpmcounter4();
    // Event selector 0 stops the counter without resetting it
    write_mhpmevent4(0);
    return dcache_misses - dcache_miss_counter;
}

static inline uint32_t read_branch_direction_miss_counter(void) {
    uint32_t bdm_misses = read_mhpmcounter5();
    // Event selector 0 stops the counter without resetting it
    write_mhpmevent5(0);
    return bdm_misses - bdm_miss_counter;
}

static inline uint32_t read_branch_target_miss_counter(void) {
    uint32_t btm_misses = read_mhpmcounter6();
    // Event selector 0 stops the counter without resetting it
    write_mhpmevent6(0);
    return btm_misses - btm_miss_counter;
}

/**************/
/* COCOTB API */
/**************/

// Scratch-register handshake tokens consumed by the cocotb testbench.
static inline void start_counter(void) {
    icache_miss_counter = 0;
    dcache_miss_counter = 0;
    bdm_miss_counter = 0;
    btm_miss_counter = 0;
    write_scratch(7, 0xDEADBEEF);
}

static inline void end_counter(void) {
    write_scratch(7, 0xCAFEBABE);
}

static inline void start_subsequence(void) {
    write_scratch(7, 0xBEEFDEAD);
    start_dcache_miss_counter();
    start_icache_miss_counter();
    start_branch_direction_miss_counter();
    start_branch_target_miss_counter();
}

static inline void end_subsequence(void) {
    write_scratch(7, 0xFEEDBEEF);
    uint32_t icache_misses = read_icache_miss_counter();
    uint32_t dcache_misses = read_dcache_miss_counter();
    uint32_t bdm_misses = read_branch_direction_miss_counter();
    uint32_t btm_misses = read_branch_target_miss_counter();
    write_scratch(10, icache_misses);
    write_scratch(11, dcache_misses);
    write_scratch(12, bdm_misses);
    write_scratch(13, btm_misses);
}

/***************************/
/* Coremark Timer Function */
/***************************/

static inline int tb_get_time(void) {
    write_scratch(7, 0x12345678);
    return read_scratch(8);
}

/*******************/
/* General Helpers */
/*******************/

static inline int int_pow(int base, int exp) {
    int result = 1;

    while (exp > 0) {
        if (exp % 2 == 1) {
            result *= base;
        }
        base *= base;
        exp /= 2;
    }
    return result;
}

#endif // CPU_PERF_H
