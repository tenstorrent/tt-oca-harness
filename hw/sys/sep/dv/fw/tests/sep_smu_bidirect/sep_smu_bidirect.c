#include <stdint.h>
#include <stddef.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "test_completion.h"

#define XBAR_FILTER_START_ADDR       0x0000000040000000ULL
#define XBAR_FILTER_END_ADDR         0x00000000800000FFULL
#define SEP_INBOUND_SHARED_START_ADDR  ((uint64_t)SEP_SCRATCH_COLD_SCRATCH_0__REG_ADDR)
#define SEP_INBOUND_SHARED_END_ADDR \
    ((uint64_t)SEP_SCRATCH_COLD_SCRATCH_7__REG_ADDR + 7ULL)
#define XBAR_FILTER_CONFIG           0x0000000101000013ULL
#define SMC_TO_SEP_FILTER_CONFIG     0x0000000101030013ULL
#define SMC_TO_SEP_NS_FILTER_CONFIG  0x0000000101030113ULL

#define FILTER_CONFIG_OFFSET   0x0u
#define FILTER_START_OFFSET    0x8u
#define FILTER_END_OFFSET      0x10u
#define FILTER_STRIDE          0x20u

/*
 * SEP->SMC address translation for the sep_ext_to_smc dedicated port (see
 * fw/sep/tests/sep_smc_xbar/sep_smc_xbar.c for the derivation): SMC
 * CPU_CTRL scratch[0] is at SMC-local 0xC0039080, so SEP must target
 * 0x40039080 to reach scratch[0]. The previous 0x40010140 constant assumed
 * scratch lived at 0xC0010140 (wrong address entirely), which caused every
 * scratch_rw_check readback to mismatch and dropped SEP into
 * `smu_bidirect_fail_loop`.
 */
#define SMC_XBAR_CPU_CTRL_SCRATCH8_ADDR  0x400390C0u
#define SMC_XBAR_SCRATCH_STRIDE          0x8u
#define SMC_XBAR_CPU_CTRL_SCRATCH12_ADDR 0x400390E0u

#define SEP_SHARED_ADDR                  SEP_SCRATCH_COLD_SCRATCH_0__REG_ADDR
#define SMC_TO_SEP_PATTERN               0xC001CAFEu
#define SMC_TO_SEP_DONE_PATTERN          0xD0E0F00Du
#define SEP_READY_PATTERN                0x51EAD001u
#define SEP_TO_SMC_ACK_PATTERN           0x5E9ACCE5u
#define SMC_TO_SEP_TIMEOUT_ITERS         1000000u

/*
 * SMU xbar SEP aperture must cover 0x10802000 (cold scratch) for SMC->SEP
 * writes and readbacks. SEP_REGION_SIZE defaults to 0x01000000 which excludes
 * it; program 0x20000000 so [0, 0x20000000) covers the SEP local address
 * space without overlapping the default SMC aperture at [0x40000000,
 * 0x41000000).
 */
#define SEP_APERTURE_SIZE                0x20000000ULL

static volatile int g_xbar_status;

static inline void program_sep_smu_aperture(void)
{
    /* 32-bit write (matches global_alias_remap_sanity). See interop fw. */
    WRITE_REG(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR, (uint32_t)SEP_APERTURE_SIZE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static inline void open_sep_outbound_xbar_window(void)
{
    uintptr_t base = (uintptr_t)OUTBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;

    WRITE_REG64(base + FILTER_START_OFFSET, XBAR_FILTER_START_ADDR);
    WRITE_REG64(base + FILTER_END_OFFSET, XBAR_FILTER_END_ADDR);
    WRITE_REG64(base + FILTER_CONFIG_OFFSET, XBAR_FILTER_CONFIG);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static inline void open_sep_inbound_sram_window(void)
{
    uintptr_t base = (uintptr_t)INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR;

    WRITE_REG64(base + FILTER_START_OFFSET, SEP_INBOUND_SHARED_START_ADDR);
    WRITE_REG64(base + FILTER_END_OFFSET, SEP_INBOUND_SHARED_END_ADDR);
    WRITE_REG64(base + FILTER_CONFIG_OFFSET, SMC_TO_SEP_FILTER_CONFIG);

    base += FILTER_STRIDE;
    WRITE_REG64(base + FILTER_START_OFFSET, SEP_INBOUND_SHARED_START_ADDR);
    WRITE_REG64(base + FILTER_END_OFFSET, SEP_INBOUND_SHARED_END_ADDR);
    WRITE_REG64(base + FILTER_CONFIG_OFFSET, SMC_TO_SEP_NS_FILTER_CONFIG);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static int smc_scratch_rw_check(uint32_t index, uint32_t pattern)
{
    uintptr_t addr = (uintptr_t)(SMC_XBAR_CPU_CTRL_SCRATCH8_ADDR +
                                 (index * SMC_XBAR_SCRATCH_STRIDE));
    WRITE_REG(addr, pattern);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    uint32_t readback = READ_REG(addr);
    if (readback != pattern) {
        return -((int)index + 1);
    }

    return 0;
}

static int wait_for_smc_to_sep_pattern(uint32_t expected)
{
    volatile uint32_t *shared = (volatile uint32_t *)(uintptr_t)SEP_SHARED_ADDR;

    for (uint32_t i = 0; i < SMC_TO_SEP_TIMEOUT_ITERS; ++i) {
        uint32_t value = *shared;
        if (value == expected) {
            return 0;
        }
    }

    return -1;
}

static int run_smu_bidirect_sequence(void)
{
    static const uint32_t patterns[] = {
        0x13579BDFu,
        0x2468ACE0u,
        0xA5A55A5Au,
        0x5A5AA5A5u,
    };

    /*
     * Program the SMU xbar SEP aperture BEFORE opening filter windows so
     * that any early SMC-side write is already routable across the xbar.
     */
    program_sep_smu_aperture();

    open_sep_outbound_xbar_window();
    open_sep_inbound_sram_window();

    for (uint32_t i = 0; i < (sizeof(patterns) / sizeof(patterns[0])); ++i) {
        int rc = smc_scratch_rw_check(i, patterns[i]);
        if (rc != 0) {
            return rc;
        }
    }

    volatile uint32_t *shared = (volatile uint32_t *)(uintptr_t)SEP_SHARED_ADDR;
    *shared = 0u;
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    WRITE_REG(SMC_XBAR_CPU_CTRL_SCRATCH12_ADDR, SEP_READY_PATTERN);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    if (wait_for_smc_to_sep_pattern(SMC_TO_SEP_PATTERN) != 0) {
        return -100;
    }

    WRITE_REG(SMC_XBAR_CPU_CTRL_SCRATCH12_ADDR, SEP_TO_SMC_ACK_PATTERN);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    if (wait_for_smc_to_sep_pattern(SMC_TO_SEP_DONE_PATTERN) != 0) {
        return -101;
    }

    return 0;
}

__attribute__((noinline, used)) void smu_bidirect_pass_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((noinline, used)) void smu_bidirect_fail_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void)
{
    g_xbar_status = run_smu_bidirect_sequence();

    if (g_xbar_status == 0) {
        smu_bidirect_pass_loop();
    } else {
        smu_bidirect_fail_loop();
    }

    return g_xbar_status;
}
