/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef SEP_FABRIC_H
#define SEP_FABRIC_H

/* SEP fabric (alias/remap/filter) test helpers.
 *
 * Holds fabric inline stubs, cache-attribute encodings, and alias/remap setup
 * stubs. The non-inline setup_* helpers are no-op stubs defined in
 * drivers/sep_fabric.c and linked from libsep.a. They program no hardware, so
 * a test that calls them checks nothing. */

#include <stdint.h>

/* Fabric channels / access direction. */
#define AP_CHANNEL 0
#define STEE_CHANNEL 1
#define AXI_READ 0
#define AXI_WRITE 1

/* Cache-attribute encodings (AXI region attributes). */
#define CACHE_ATTR_DEVICE 0x00
#define CACHE_ATTR_NORMAL_NC 0x04
#define CACHE_ATTR_NORMAL_WT 0x08
#define CACHE_ATTR_NORMAL_WB 0x0C
#define CACHE_ATTR_WRITEBACK CACHE_ATTR_NORMAL_WB
#define CACHE_ATTR_INSTRUCTION 0x02

/* Cache-attribute encodings (memory-type / shareability bits). */
#define CACHE_ATTR_STRONGLY_ORDERED 0u
#define CACHE_ATTR_WRITE_COMBINING 1u
#define CACHE_ATTR_WRITE_ALLOCATE 2u
#define CACHE_ATTR_READ_ALLOCATE 3u
#define CACHE_ATTR_WRITETHROUGH 4u
#define CACHE_ATTR_SHAREABLE 0x10u
#define CACHE_ATTR_BUFFERABLE 0x20u
#define CACHE_ATTR_NON_SHAREABLE 0x40u
#define CACHE_ATTR_INNER_SHAREABLE 0x80u

/* Output-remap register offsets. */
#define OUTPUT_REMAP_SRC_ADDR_LOW_OFFSET 0x00
#define OUTPUT_REMAP_CTRL_OFFSET 0x10
#define OUTPUT_REMAP_STATUS_OFFSET 0x14

/* Inline helper stubs (header-only). */
static inline int init_sep_fabric(void) {
    return 0;
}

static inline void sep_delay_cycles(uint32_t cycles) {
    for (volatile uint32_t i = 0; i < cycles * 100; i++) {
        __asm__ __volatile__("nop");
    }
}

static inline int setup_output_remap_region(int region, uint32_t src_start, uint32_t dest_start,
                                            int enable, int channel) {
    return 0;
}

static inline int test_axi_transaction(uint32_t addr, uint32_t size, int type) {
    return 0;
}

static inline int setup_output_remap_region_extended(int region, uint32_t src, uint32_t dest,
                                                     int enable, int channel, uint32_t mask,
                                                     uint32_t attr) {
    return 0;
}
static inline int read_output_remap_reg(int region, uint32_t offset, uint32_t *value) {
    *value = 0xDEADBEEF;
    return 0;
}
static inline int toggle_output_remap_region_enable(int region) {
    return 0;
}
static inline int toggle_output_remap_channel(int region) {
    return 0;
}
static inline int lock_output_remap_region(int region) {
    return 0;
}
static inline int unlock_output_remap_region(int region) {
    return 0;
}
static inline int reset_output_remap_region(int region) {
    return 0;
}
static inline int write_output_remap_reg(int region, uint32_t offset, uint32_t value) {
    return 0;
}

static inline uint32_t get_cycle_count(void) {
    uint32_t cycles;
    __asm__ volatile("rdcycle %0" : "=r"(cycles));
    return cycles;
}

static inline uint32_t get_system_frequency(void) {
    return 100000000; // 100 MHz
}

/* Alias/remap setup placeholders (no-op; defined in drivers/sep_fabric.c). */
int write_alias_csr_register();
int read_alias_csr_register();
int perform_alias_csr_soft_reset();
int setup_alias_wrap_maximum_intensity();
int setup_axi_filter_wrap_entry();
int setup_local_alias_advanced_mapping();
int test_axi_transaction_with_attributes();
int setup_local_alias_deep_config();
int setup_local_alias_complex_routing();
int setup_local_alias_master_routing();
int setup_local_alias_timing_critical();
int setup_local_alias_remap_extended();
int setup_local_alias_remap_master_specific();
int setup_local_alias_remap_boundary();
int setup_output_remap_region_multi_level();
int setup_output_remap_region_priority();

#endif /* SEP_FABRIC_H */
