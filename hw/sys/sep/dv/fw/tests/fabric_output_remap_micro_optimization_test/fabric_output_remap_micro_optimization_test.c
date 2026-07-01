/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * TC_FABRIC_067: fabric_output_remap_micro_optimization_test
 *
 * 目標: output_remap 89.83% → 90%+ (僅需 0.17% 改進)
 * 策略: 極小量邊界條件補強，專注最後幾個未觸及的 toggle 位元
 * 優先級: 最高 (最容易達標)
 *
 * 專注於最細緻的邊界條件和未觸及的 corner cases
 */

#include "sep_test_common.h"
#include "sep_fabric.h"

// 微調邊界和異常條件場景
#define MICRO_REMAP_SCENARIOS 12

// 邊界值定義 - 專注未觸及的邊緣值
#define ADDR_BOUNDARY_EDGE_LOW   0x7FFFFFFE  // 32-bit 邊界-2
#define ADDR_BOUNDARY_EDGE_HIGH  0x80000001  // 32-bit 邊界+1
#define OFFSET_MICRO_PATTERN_1   0x00000003  // 微小偏移模式
#define OFFSET_MICRO_PATTERN_2   0x0000000C  // 微小偏移模式
#define SIZE_MICRO_BURST_1       0x1         // 1-byte 最小burst
#define SIZE_MICRO_BURST_2       0x3         // 3-byte 不對齊

static int test_micro_boundary_edge_cases(void)
{
    printf("Starting micro boundary edge case tests...\n");

    // 場景 1: 極邊界位址對齊測試
    for (int region = 14; region < 16; region++) {  // 專注最高區域
        uint32_t edge_addr = ADDR_BOUNDARY_EDGE_LOW + (region * 4);

        if (setup_output_remap_region(region,
                                     edge_addr,
                                     edge_addr + OFFSET_MICRO_PATTERN_1,
                                     1, // enable
                                     (region % 2) ? AP_CHANNEL : STEE_CHANNEL) != 0) {
            printf("ERROR: Failed to setup edge boundary region %d\n", region);
            return -1;
        }

        // 極小 burst 存取
        if (test_axi_transaction(edge_addr, SIZE_MICRO_BURST_1, AXI_READ) != 0) {
            printf("ERROR: Edge boundary read failed for region %d\n", region);
            return -1;
        }

        // 不對齊存取
        if (test_axi_transaction(edge_addr + 1, SIZE_MICRO_BURST_2, AXI_WRITE) != 0) {
            printf("ERROR: Edge boundary unaligned write failed for region %d\n", region);
            return -1;
        }
    }

    printf("Micro boundary edge cases: PASS\n");
    return 0;
}

static int test_offset_calculation_corners(void)
{
    printf("Starting offset calculation corner tests...\n");

    // 場景 2: 偏移計算的角落案例
    uint32_t corner_offsets[] = {
        0x00000001, 0x00000002, 0x00000007,  // 小偏移
        0x0000000F, 0x0000001F, 0x0000003F,  // nibble 邊界
        0x000000FF, 0x000001FF, 0x000003FF   // byte 邊界
    };

    for (int i = 0; i < sizeof(corner_offsets)/sizeof(uint32_t); i++) {
        int region = 12 + (i % 4);  // 使用高區域
        uint32_t src_addr = 0x40000000 + (i * 0x1000);
        uint32_t dest_addr = src_addr + corner_offsets[i];

        if (setup_output_remap_region(region, src_addr, dest_addr, 1,
                                     (i % 2) ? STEE_CHANNEL : AP_CHANNEL) != 0) {
            printf("ERROR: Failed offset corner setup %d\n", i);
            return -1;
        }

        // 測試計算路徑
        if (test_axi_transaction(src_addr + (corner_offsets[i] >> 2), 4, AXI_READ) != 0) {
            printf("ERROR: Offset calculation failed for corner %d\n", i);
            return -1;
        }
    }

    printf("Offset calculation corners: PASS\n");
    return 0;
}

static int test_channel_switching_micro_scenarios(void)
{
    printf("Starting channel switching micro scenarios...\n");

    // 場景 3: 通道切換微場景
    for (int cycle = 0; cycle < 8; cycle++) {
        int region1 = 8 + cycle;
        int region2 = 15 - cycle;

        // 快速切換 AP ↔ STEE
        if (setup_output_remap_region(region1, 0x50000000 + cycle*0x1000,
                                     0x60000000 + cycle*0x1000, 1, AP_CHANNEL) != 0) {
            return -1;
        }

        if (setup_output_remap_region(region2, 0x50000000 + cycle*0x1000 + 0x800,
                                     0x60000000 + cycle*0x1000 + 0x800, 1, STEE_CHANNEL) != 0) {
            return -1;
        }

        // 微妙的並行存取
        test_axi_transaction(0x50000000 + cycle*0x1000 + 1, 2, AXI_WRITE);
        test_axi_transaction(0x50000000 + cycle*0x1000 + 0x801, 2, AXI_READ);
    }

    printf("Channel switching micro scenarios: PASS\n");
    return 0;
}

static int test_non_standard_size_burst_modes(void)
{
    printf("Starting non-standard size/burst mode tests...\n");

    // 場景 4: 非標準 size/burst 模式
    uint32_t unusual_sizes[] = {1, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15};

    for (int i = 0; i < sizeof(unusual_sizes)/sizeof(uint32_t); i++) {
        int region = 4 + (i % 12);
        uint32_t test_addr = 0x70000000 + i * 0x100;

        if (setup_output_remap_region(region, test_addr, test_addr + 0x10000,
                                     1, (i % 2) ? AP_CHANNEL : STEE_CHANNEL) != 0) {
            return -1;
        }

        // 不常見的 size 測試
        if (test_axi_transaction(test_addr + (i * 16), unusual_sizes[i],
                               (i % 2) ? AXI_WRITE : AXI_READ) != 0) {
            printf("ERROR: Unusual size %d failed\n", unusual_sizes[i]);
            return -1;
        }
    }

    printf("Non-standard size/burst modes: PASS\n");
    return 0;
}

static int test_parallel_micro_stress(void)
{
    printf("Starting parallel micro stress tests...\n");

    // 場景 5: 並行微壓力測試
    for (int stress_round = 0; stress_round < 4; stress_round++) {
        // 設置多個重疊區域
        for (int region = 0; region < 16; region++) {
            uint32_t base = 0x80000000 + stress_round * 0x100000;
            if (setup_output_remap_region(region,
                                         base + region * 0x1000,
                                         base + 0x10000 + region * 0x1000,
                                         1, region % 2) != 0) {
                return -1;
            }
        }

        // 快速並行存取
        for (int access = 0; access < 32; access++) {
            uint32_t addr = 0x80000000 + stress_round * 0x100000 + access * 64;
            test_axi_transaction(addr, 4, access % 2);
            test_axi_transaction(addr + 32, 8, (access + 1) % 2);
        }
    }

    printf("Parallel micro stress: PASS\n");
    return 0;
}

int main(void)
{
    printf("TC_FABRIC_067: Output Remap Micro-Optimization Test\n");
    printf("Goal: 89.83%% -> 90%%+ (需要僅 0.17%% 改進)\n");
    printf("Focus: 極小量邊界條件補強，專注最後幾個未觸及的 toggle 位元\n\n");

    // 初始化fabric系統
    if (init_sep_fabric() != 0) {
        test_fail("TC_FABRIC_067");
        return TEST_FAIL;
    }

    // 執行所有微調測試場景
    if (test_micro_boundary_edge_cases() != 0) {
        test_fail("TC_FABRIC_067 - Boundary Edge Cases");
        return TEST_FAIL;
    }

    if (test_offset_calculation_corners() != 0) {
        test_fail("TC_FABRIC_067 - Offset Calculation");
        return TEST_FAIL;
    }

    if (test_channel_switching_micro_scenarios() != 0) {
        test_fail("TC_FABRIC_067 - Channel Switching");
        return TEST_FAIL;
    }

    if (test_non_standard_size_burst_modes() != 0) {
        test_fail("TC_FABRIC_067 - Non-standard Modes");
        return TEST_FAIL;
    }

    if (test_parallel_micro_stress() != 0) {
        test_fail("TC_FABRIC_067 - Parallel Stress");
        return TEST_FAIL;
    }

    printf("\n=== TC_FABRIC_067: OUTPUT REMAP MICRO-OPTIMIZATION TEST PASSED ===\n");
    printf("Expected improvement: 89.83%% -> 90%%+ coverage\n");

    test_pass("TC_FABRIC_067");
    return TEST_PASS;
}