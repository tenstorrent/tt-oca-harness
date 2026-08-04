#include <stdint.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "sep_smc_bringup.h"       /* common: sep_smc_open_window / _bringup_from_sram / _scratch_* */
#include "sep_interop_protocol.h"

/*
 * SEP_SMU_002  sep_interop  --  SEP (consumer) firmware.
 *
 * The real SEP CPU boots from reset, programs its SMU aperture + inbound/outbound filters so
 * the SMC-facing mailbox port and the SEP->SMC alias are reachable, then brings the SMC up
 * over the (unfiltered) SEP->SMC port using the common sep_smc_bringup helpers exactly like
 * SEP_SMU_004 (open outbound window -> wait exact SRAM cookie -> re-vector + release the SMC
 * cores). It then runs the mailbox handshake on the SEP-local port (OUTBOUND_MAILBOX_0 @
 * 0x10A00000): publish READY -> receive TOKEN -> reply RESPONSE -> receive ACK -> publish
 * SEP_PASS, write-1-to-clearing the mailbox read IRQ after each pop. No ext_in, no force.
 *
 * PASS/FAIL is signalled by parking in a named loop (a cocotb PC watch classifies the run);
 * there is NO STDOUT / test_pass magic here.
 */

__attribute__((noinline, used)) void sep_smc_interop_pass_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

__attribute__((noinline, used)) void sep_smc_interop_fail_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

/* SEP SMU aperture: size 0x20000000 so [0, 0x20000000) covers the mailbox (0x10A00000) and
 * the SEP system-peripheral region without overlapping the SMC aperture at [0x40000000, ...). */
#define SEP_REGION_SIZE_VALUE 0x20000000u

/* SEP inbound filters over the mailbox window (must cover BOTH ports so the SMC pushes at
 * the SMC-facing port 0x10A00800 reach the mailbox). filter0 secure, filter1 non-secure. */
#define SEP_INBOUND_FILTER0_BASE  INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR  /* 0x10A21000 */
#define SEP_INBOUND_FILTER_STRIDE 0x20u
#define SEP_FILTER_CONFIG_OFFSET  0x00u
#define SEP_FILTER_START_OFFSET   0x08u
#define SEP_FILTER_END_OFFSET     0x10u
#define SEP_MBOX_INBOUND_START    0x0000000010A00000ULL
#define SEP_MBOX_INBOUND_END      0x0000000010A0084FULL
/* allow_burst=0 on these sub-4KB inbound filters so the byte-granular END (0x10A0084F) stores
 * EXACTLY -- allow_burst=1 rounds a same-page window up to 0x..FFF (the SEP_SMU_003 lesson). */
#define SEP_MBOX_INBOUND_CFG      0x0000000100030013ULL   /* read/write/enable/src_id=3          */
#define SEP_MBOX_INBOUND_CFG_NS   0x0000000100030113ULL   /* + allow_ns (non-secure)             */

/* SEP-local mailbox port (OUTBOUND_MAILBOX_0) absolute register addresses. */
#define SEP_LOCAL_MBOX_WDATA  (SEP_LOCAL_MBOX_BASE + MBOX_WRITE_DATA_OFFSET)  /* 0x10A00000 */
#define SEP_LOCAL_MBOX_RDATA  (SEP_LOCAL_MBOX_BASE + MBOX_READ_DATA_OFFSET)   /* 0x10A00008 */
#define SEP_LOCAL_MBOX_STATUS (SEP_LOCAL_MBOX_BASE + MBOX_STATUS_OFFSET)      /* 0x10A00010 */
#define SEP_LOCAL_MBOX_RIRQT  (SEP_LOCAL_MBOX_BASE + MBOX_RIRQT_OFFSET)       /* 0x10A00028 */
#define SEP_LOCAL_MBOX_IRQS   (SEP_LOCAL_MBOX_BASE + MBOX_IRQS_OFFSET)        /* 0x10A00030 */
#define SEP_LOCAL_MBOX_IRQEN  (SEP_LOCAL_MBOX_BASE + MBOX_IRQEN_OFFSET)       /* 0x10A00038 */
#define SEP_LOCAL_MBOX_IRQP   (SEP_LOCAL_MBOX_BASE + MBOX_IRQP_OFFSET)        /* 0x10A00040 */

/*
 * Write a 64-bit filter field as two 32-bit stores. The SEP CPU is RV32; a WRITE_REG64 to a
 * CSR whose upper half lands off-map faults (that is what wedged the previous 002 firmware),
 * so program every 64-bit filter/aperture field with explicit 32-bit CSR writes.
 */
static inline void wr_filter_field32(uint32_t addr, uint64_t val)
{
    WRITE_REG(addr + 0x0u, (uint32_t)(val & 0xFFFFFFFFu));
    WRITE_REG(addr + 0x4u, (uint32_t)(val >> 32));
}

static void program_sep_setup(void)
{
    /* Aperture first (32-bit write only) so any SMC push arriving mid-setup is routable.
     * (No mailbox clock-gate write is needed: sep_system_csr's mailbox_cg_en is a functional
     * no-op -- assigned but unused in RTL -- so the mailbox runs on the raw clk_i regardless.) */
    WRITE_REG(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR, SEP_REGION_SIZE_VALUE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    /* Inbound filter 0 (secure) and 1 (non-secure) over the mailbox window. START/END before
     * CONFIG so each filter enables atomically over its final range. */
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_FILTER_START_OFFSET,  SEP_MBOX_INBOUND_START);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_FILTER_END_OFFSET,    SEP_MBOX_INBOUND_END);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_FILTER_CONFIG_OFFSET, SEP_MBOX_INBOUND_CFG);

    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_INBOUND_FILTER_STRIDE + SEP_FILTER_START_OFFSET,
                      SEP_MBOX_INBOUND_START);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_INBOUND_FILTER_STRIDE + SEP_FILTER_END_OFFSET,
                      SEP_MBOX_INBOUND_END);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_INBOUND_FILTER_STRIDE + SEP_FILTER_CONFIG_OFFSET,
                      SEP_MBOX_INBOUND_CFG_NS);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* Bounded wait for the SEP-local mailbox RX FIFO to become non-empty. 0 = data, -1 = timeout. */
static int wait_mbox_not_empty(void)
{
    for (uint32_t i = 0; i < SEP_INTEROP_POLL_LIMIT; ++i) {
        if ((READ_REG(SEP_LOCAL_MBOX_STATUS) & MBOX_STATUS_EMPTY_MASK) == 0u) {
            return 0;
        }
    }
    return -1;
}

static int run_interop_sequence(void)
{
    /* a. Aperture + inbound mailbox filters (32-bit CSR writes). */
    program_sep_setup();

    /* b. Open the SEP outbound egress filter over the whole SEP->SMC region + mailbox
     *    ([0x40000000, 0x800000FF], cfg 0x0000000101000013) via the common helper, then
     *    frontdoor-boot the SMC exactly like SEP_SMU_004: wait for the EXACT SRAM preload
     *    cookie, then re-vector + release the four SMC cores. On preload timeout, publish a
     *    fail marker and stop -- never proceed on an absent/bad preload. */
    sep_smc_open_window();

    if (sep_smc_bringup_from_sram((uint32_t)SEP_INTEROP_SMC_ENTRY,
                                  SEP_INTEROP_SMC_IMAGE_FIRST_WORD,
                                  SEP_INTEROP_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_INTEROP_SMC_SCRATCH12_ALIAS, SEP_INTEROP_TEST_FAIL);
        return -1;
    }

    /* Gate on the SMC "up" marker BEFORE the first SMC-scratch write: POLL (read) scratch2 for
     * SMC_UP, exactly like SEP_SMU_004 polls INIT_RELEASE_OK. This is what keeps the READY
     * publish below from racing the just-released SMC clearing/initing its own scratch (the race
     * that wedged the sep_axi_in write). On timeout, publish a fail marker and stop. */
    if (sep_smc_scratch_wait(SEP_INTEROP_SMC_SCRATCH2_ALIAS, SEP_INTEROP_SMC_UP,
                             SEP_INTEROP_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SEP_INTEROP_SMC_SCRATCH12_ALIAS, SEP_INTEROP_TEST_FAIL);
        return -6;
    }

    /* c. Arm the SEP-local mailbox read-data IRQ (threshold 0 -> fire on any word; enable
     *    bit1); read back, and confirm the port starts idle -- RX FIFO empty, no IRQ. */
    WRITE_REG(SEP_LOCAL_MBOX_RIRQT, 0u);
    WRITE_REG(SEP_LOCAL_MBOX_IRQEN, MBOX_IRQ_READ_MASK);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(SEP_LOCAL_MBOX_RIRQT) != 0u)                             return -2;
    if (READ_REG(SEP_LOCAL_MBOX_IRQEN) != MBOX_IRQ_READ_MASK)             return -2;
    if ((READ_REG(SEP_LOCAL_MBOX_STATUS) & MBOX_STATUS_EMPTY_MASK) == 0u) return -2; /* RX empty */
    if (READ_REG(SEP_LOCAL_MBOX_IRQS) != 0u)                             return -2;
    if (READ_REG(SEP_LOCAL_MBOX_IRQP) != 0u)                             return -2;

    /* Publish READY into SMC scratch12; the SMC waits on this before sending the token. */
    sep_smc_scratch_write(SEP_INTEROP_SMC_SCRATCH12_ALIAS, SEP_INTEROP_READY);

    /* d. Wait for the SMC token, pop it, verify, W1C the read IRQ, confirm status/pending clear. */
    if (wait_mbox_not_empty() != 0)                          return -3;
    if (READ_REG(SEP_LOCAL_MBOX_RDATA) != SEP_INTEROP_TOKEN) return -3;
    WRITE_REG(SEP_LOCAL_MBOX_IRQS, MBOX_IRQ_ALL);   /* W1C ALL: read + sticky write-threshold bit */
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(SEP_LOCAL_MBOX_IRQS) != 0u) return -3;
    if (READ_REG(SEP_LOCAL_MBOX_IRQP) != 0u) return -3;

    /* e. Reply with RESPONSE. */
    WRITE_REG(SEP_LOCAL_MBOX_WDATA, SEP_INTEROP_RESPONSE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    /* f. Wait for ACK, pop it, verify, W1C, confirm clear. */
    if (wait_mbox_not_empty() != 0)                        return -4;
    if (READ_REG(SEP_LOCAL_MBOX_RDATA) != SEP_INTEROP_ACK) return -4;
    WRITE_REG(SEP_LOCAL_MBOX_IRQS, MBOX_IRQ_ALL);   /* W1C ALL: read + sticky write-threshold bit */
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG(SEP_LOCAL_MBOX_IRQS) != 0u) return -4;
    if (READ_REG(SEP_LOCAL_MBOX_IRQP) != 0u) return -4;

    /* g. Publish SEP-side completion. */
    WRITE_REG(SEP_LOCAL_MBOX_WDATA, SEP_INTEROP_SEP_PASS);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    return 0;
}

int main(void)
{
    int rc = run_interop_sequence();
    if (rc == 0) {
        sep_smc_interop_pass_loop();
    } else {
        sep_smc_interop_fail_loop();
    }
    return rc;
}
