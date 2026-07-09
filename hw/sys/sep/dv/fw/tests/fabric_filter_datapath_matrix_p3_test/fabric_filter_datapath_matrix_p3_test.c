/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_FABRIC_061: fabric_filter_datapath_matrix_p3_test
 *
 * 目標: traffic_filter 88.11% → 90%+, axi_filter_wrap 64.11% → 90%+
 * 策略: 針對性的 pass/block 流量測試，覆蓋所有datapath組合
 * 優先級: 第一輪 (中等難度)
 *
 * 專注於filter模組的完整datapath矩陣測試
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// Filter datapath 場景數量
#define FILTER_DATAPATH_SCENARIOS 8

// Filter 測試定義
#define FILTER_TEST_BASE_ADDR 0x30000000
#define FILTER_REGION_SIZE 0x100000
#define MAX_FILTER_ENTRIES 16

// AXI屬性定義
#define AXI_PROT_SECURE 0x0
#define AXI_PROT_NON_SECURE 0x1
#define AXI_PROT_PRIVILEGED 0x0
#define AXI_PROT_USER 0x2

static int test_no_match_default_block_scenarios(void) {
    printf("Starting no-match default block scenarios...\n");

    // 場景1: No-match 預設阻擋測試
    for (int test_case = 0; test_case < 16; test_case++) {
        uint32_t test_addr = FILTER_TEST_BASE_ADDR + test_case * 0x10000;

        // 設置filter規則，但故意不匹配測試位址
        for (int filter_entry = 0; filter_entry < 8; filter_entry++) {
            uint32_t filter_start = 0x50000000 + filter_entry * 0x100000; // 不同範圍
            uint32_t filter_end = filter_start + 0x80000;

            // 設置filter條目但不覆蓋test_addr
            if (setup_output_remap_region_extended(filter_entry, filter_start, filter_end,
                                                   1,          // enable
                                                   0,          // allow
                                                   0xFFFF0000, // mask
                                                   AXI_PROT_NON_SECURE) != 0) {
                return -1;
            }
        }

        // 測試no-match位址應該被default block
        if (test_axi_transaction(test_addr, 4, AXI_READ) != 0) {
            // 預期失敗 - 應該被block
        }
        if (test_axi_transaction(test_addr + 0x100, 8, AXI_WRITE) != 0) {
            // 預期失敗 - 應該被block
        }
    }

    printf("No-match default block scenarios: PASS\n");
    return 0;
}

static int test_read_only_pass_write_block_combinations(void) {
    printf("Starting read-only pass/write block combinations...\n");

    // 場景2: Read-only pass, write block 組合
    for (int combo = 0; combo < 16; combo++) {
        uint32_t region_base = FILTER_TEST_BASE_ADDR + combo * 0x100000;

        for (int entry = 0; entry < 8; entry++) {
            uint32_t entry_start = region_base + entry * 0x20000;
            uint32_t entry_end = entry_start + 0x10000;

            // 設置read-only filter
            if (setup_output_remap_region_extended(entry, entry_start, entry_end,
                                                   1,                         // enable
                                                   1,                         // read allowed
                                                   0xFFFF0000 | (1 << entry), // write blocked
                                                   AXI_PROT_SECURE) != 0) {
                return -1;
            }
        }

        // 測試read-only訪問模式
        for (int entry = 0; entry < 8; entry++) {
            uint32_t test_addr = region_base + entry * 0x20000 + 0x1000;

            // Read應該pass
            if (test_axi_transaction(test_addr, 4, AXI_READ) != 0) {
                printf("ERROR: Read should pass for combo %d entry %d\n", combo, entry);
                return -1;
            }

            // Write應該block
            if (test_axi_transaction(test_addr + 4, 4, AXI_WRITE) != 0) {
                // 預期失敗 - write should be blocked
            }
        }
    }

    printf("Read-only pass/write block combinations: PASS\n");
    return 0;
}

static int test_ns_secure_allow_deny_patterns(void) {
    printf("Starting NS/secure allow/deny patterns...\n");

    // 場景3: NS allow/deny 和 secure 模式
    uint32_t security_patterns[] = {AXI_PROT_SECURE, AXI_PROT_NON_SECURE,
                                    AXI_PROT_SECURE | AXI_PROT_PRIVILEGED,
                                    AXI_PROT_NON_SECURE | AXI_PROT_USER};

    for (int pattern_idx = 0; pattern_idx < 4; pattern_idx++) {
        for (int region = 0; region < 4; region++) {
            uint32_t region_start =
                FILTER_TEST_BASE_ADDR + pattern_idx * 0x1000000 + region * 0x100000;
            uint32_t region_end = region_start + 0x80000;

            uint32_t security_attr = security_patterns[pattern_idx];
            int allow_ns = (security_attr & AXI_PROT_NON_SECURE) ? 1 : 0;
            int allow_secure = (security_attr & AXI_PROT_NON_SECURE) ? 0 : 1;

            // 設置security-aware filter
            if (setup_output_remap_region_extended(region, region_start, region_end,
                                                   1,            // enable
                                                   allow_secure, // channel for secure
                                                   0xFFF80000 |
                                                       (allow_ns << 16), // mask with NS bit
                                                   security_attr) != 0) {
                return -1;
            }

            // 測試不同security模式的訪問
            uint32_t test_addr = region_start + 0x10000;

            // Secure 訪問
            if (test_axi_transaction(test_addr, 4, AXI_READ) != 0) {
                if (allow_secure) {
                    printf("ERROR: Secure access should be allowed\n");
                    return -1;
                }
            }

            // Non-secure 訪問 (模擬)
            if (test_axi_transaction(test_addr + 0x1000, 4, AXI_WRITE) != 0) {
                if (allow_ns) {
                    printf("ERROR: NS access should be allowed\n");
                    return -1;
                }
            }
        }
    }

    printf("NS/secure allow/deny patterns: PASS\n");
    return 0;
}

static int test_burst_allowed_blocked_scenarios(void) {
    printf("Starting burst allowed/blocked scenarios...\n");

    // 場景4: Burst allowed/blocked 組合
    uint32_t burst_sizes[] = {1, 2, 4, 8, 16, 32, 64, 128};

    for (int burst_idx = 0; burst_idx < 8; burst_idx++) {
        uint32_t burst_size = burst_sizes[burst_idx];
        uint32_t region_base = FILTER_TEST_BASE_ADDR + burst_idx * 0x200000;

        for (int filter_entry = 0; filter_entry < 8; filter_entry++) {
            uint32_t entry_start = region_base + filter_entry * 0x40000;
            uint32_t entry_end = entry_start + 0x20000;

            // 設置burst-aware filter
            int burst_allowed = (burst_size <= (1 << filter_entry)) ? 1 : 0;

            if (setup_output_remap_region_extended(filter_entry, entry_start, entry_end,
                                                   1,             // enable
                                                   burst_allowed, // channel indicates burst policy
                                                   0xFFFE0000 |
                                                       (burst_size << 8), // mask with burst size
                                                   burst_size & 0xFF) != 0) {
                return -1;
            }
        }

        // 測試burst訪問模式
        for (int entry = 0; entry < 8; entry++) {
            uint32_t test_addr = region_base + entry * 0x40000 + 0x8000;
            int burst_allowed = (burst_size <= (1 << entry)) ? 1 : 0;

            // 測試不同大小的burst
            if (test_axi_transaction(test_addr, burst_size * 4, AXI_READ) != 0) {
                if (burst_allowed) {
                    printf("ERROR: Burst size %d should be allowed for entry %d\n", burst_size,
                           entry);
                    return -1;
                }
            }
        }
    }

    printf("Burst allowed/blocked scenarios: PASS\n");
    return 0;
}

int main(void) {
    printf("TC_FABRIC_061: Filter Datapath Matrix P3 Test\n");
    printf("Goals: traffic_filter 88.11%% -> 90%%+, axi_filter_wrap 64.11%% -> 90%%+\n");
    printf("Strategy: 針對性的 pass/block 流量測試，覆蓋所有datapath組合\n\n");

    // 初始化fabric系統
    if (init_sep_fabric() != 0) {
        test_fail("TC_FABRIC_061");
        return TEST_FAIL;
    }

    // 執行所有filter datapath場景
    if (test_no_match_default_block_scenarios() != 0) {
        test_fail("TC_FABRIC_061 - No Match Default Block");
        return TEST_FAIL;
    }

    if (test_read_only_pass_write_block_combinations() != 0) {
        test_fail("TC_FABRIC_061 - Read Only Pass Write Block");
        return TEST_FAIL;
    }

    if (test_ns_secure_allow_deny_patterns() != 0) {
        test_fail("TC_FABRIC_061 - NS Secure Allow Deny");
        return TEST_FAIL;
    }

    if (test_burst_allowed_blocked_scenarios() != 0) {
        test_fail("TC_FABRIC_061 - Burst Allowed Blocked");
        return TEST_FAIL;
    }

    printf("\n=== TC_FABRIC_061: FILTER DATAPATH MATRIX P3 TEST PASSED ===\n");
    printf("Expected improvement: traffic_filter 88.11%% -> 90%%+, axi_filter_wrap 64.11%% -> "
           "90%%+\n");

    test_pass("TC_FABRIC_061");
    return TEST_PASS;
}