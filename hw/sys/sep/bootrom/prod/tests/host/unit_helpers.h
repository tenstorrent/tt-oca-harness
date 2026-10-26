/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Minimal host test harness. RUN_TEST resets the fixture before each case, so no
// case can depend on state another left behind.

#ifndef ROM_HOST_UNIT_HELPERS_H
#define ROM_HOST_UNIT_HELPERS_H

#include <stdio.h>
#include <string.h>

extern int g_unit_total;
extern int g_unit_failed;
extern int g_unit_case_failed;

void test_fixture_reset(void);

#define TEST(name) static void name(void)

#define RUN_TEST(name) \
    do { \
        test_fixture_reset(); \
        g_unit_case_failed = 0; \
        name(); \
        ++g_unit_total; \
        if (g_unit_case_failed) { \
            ++g_unit_failed; \
            printf("FAIL %s\n", #name); \
        } else { \
            printf("ok   %s\n", #name); \
        } \
    } while (0)

#define UNIT_FAIL(fmt, ...) \
    do { \
        printf("  %s:%d: " fmt "\n", __FILE__, __LINE__, __VA_ARGS__); \
        g_unit_case_failed = 1; \
    } while (0)

#define ASSERT_EQ_INT(got, want) \
    do { \
        long long g_ = (long long)(got), w_ = (long long)(want); \
        if (g_ != w_) UNIT_FAIL("%s == %lld, want %lld", #got, g_, w_); \
    } while (0)

#define ASSERT_TRUE(cond) \
    do { \
        if (!(cond)) UNIT_FAIL("%s is false", #cond); \
    } while (0)

#define ASSERT_MEM_EQ(a, b, n) \
    do { \
        if (memcmp((a), (b), (n)) != 0) UNIT_FAIL("%s != %s", #a, #b); \
    } while (0)

static inline int unit_report(void) {
    printf("%d/%d passed\n", g_unit_total - g_unit_failed, g_unit_total);
    return g_unit_failed == 0 ? 0 : 1;
}

#endif // ROM_HOST_UNIT_HELPERS_H
