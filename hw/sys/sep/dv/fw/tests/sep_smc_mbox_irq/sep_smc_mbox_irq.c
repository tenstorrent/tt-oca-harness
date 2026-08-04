#include <stdint.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "sep_smc_bringup.h"        /* common: sep_smc_open_window / _bringup_from_sram / _scratch_* */
#include "sep_mbox_irq_protocol.h"

/*
 * SEP_SMU_015  sep_smc_mbox_irq  --  SEP (PRODUCER) firmware.
 *
 * The real SEP CPU boots from reset, programs its SMU aperture + inbound filters (so the SMC can
 * reach every mailbox inbound port) + outbound egress window, then brings the SMC up over the
 * (unfiltered) SEP->SMC port exactly like SEP_SMU_002/004. It then walks all eight mailbox
 * channels ONE AT A TIME: for ch=0..7 it pushes token (0x15000000|ch) into the SEP-local OUTBOUND
 * port, which asserts that channel's source interrupt (packed onto SMC cpu_interrupts[256+ch]),
 * and waits for the SMC to signal "channel ch fully consumed + cleared + held quiet" via the
 * scratch3 progress channel before advancing. After channel 7 it waits for the SMC verdict
 * (SMU015_SMC_PASS on scratch10, read through the real SEP->SMC alias) and then publishes its own
 * completion (SMU015_SEP_PASS) to SEP cold scratch6. No ext_in, no force, no probe.
 *
 * PASS/FAIL is signalled by parking in a named loop (a cocotb PC watch classifies the run) AND by
 * the cold-scratch6 verdict; there is NO STDOUT / test_pass magic here.
 */

__attribute__((noinline, used)) void smu_sep_mailbox_irq_sep_pass_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

__attribute__((noinline, used)) void smu_sep_mailbox_irq_sep_fail_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

/* SEP inbound filters over the whole mailbox channel region (must cover every inbound port so the
 * SMC's pops/W1C/readbacks reach the mailbox). filter0 secure, filter1 non-secure. */
#define SEP_INBOUND_FILTER0_BASE  INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR  /* 0x10A21000 */
#define SEP_INBOUND_FILTER_STRIDE 0x20u
#define SEP_FILTER_CONFIG_OFFSET  0x00u
#define SEP_FILTER_START_OFFSET   0x08u
#define SEP_FILTER_END_OFFSET     0x10u

/* SEP-local OUTBOUND mailbox WRITE_DATA for channel ch. */
static inline uint32_t sep_mbox_wdata(uint32_t ch)
{
    return (uint32_t)(SMU015_MBOX_OUTBOUND_BASE + SMU015_MBOX_CH_STRIDE * ch + MBOX_WRITE_DATA_OFFSET);
}

/*
 * Write a 64-bit filter field as two 32-bit stores. The SEP CPU is RV32; a WRITE_REG64 to a CSR
 * whose upper half lands off-map faults, so program every 64-bit filter field with explicit
 * 32-bit CSR writes (mirrors SEP_SMU_002).
 */
static inline void wr_filter_field32(uint32_t addr, uint64_t val)
{
    WRITE_REG(addr + 0x0u, (uint32_t)(val & 0xFFFFFFFFu));
    WRITE_REG(addr + 0x4u, (uint32_t)(val >> 32));
}

static void program_sep_setup(void)
{
    /* Aperture first (32-bit write only) so any SMC access arriving mid-setup is routable.
     * (No mailbox clock-gate write is needed: sep_system_csr's mailbox_cg_en is a functional
     * no-op -- assigned but unused in RTL -- so the mailbox runs on the raw clk_i regardless.) */
    WRITE_REG(SEP_CPU_CTRL_SEP_REGION_SIZE_REG_ADDR, SMU015_SEP_REGION_SIZE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    /* Inbound filter 0 (secure) and 1 (non-secure) over the mailbox region. START/END before
     * CONFIG so each filter enables atomically over its final range. */
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_FILTER_START_OFFSET,  SMU015_MBOX_FILTER_START);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_FILTER_END_OFFSET,    SMU015_MBOX_FILTER_END);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_FILTER_CONFIG_OFFSET, SMU015_MBOX_FILTER_CFG);

    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_INBOUND_FILTER_STRIDE + SEP_FILTER_START_OFFSET,
                      SMU015_MBOX_FILTER_START);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_INBOUND_FILTER_STRIDE + SEP_FILTER_END_OFFSET,
                      SMU015_MBOX_FILTER_END);
    wr_filter_field32(SEP_INBOUND_FILTER0_BASE + SEP_INBOUND_FILTER_STRIDE + SEP_FILTER_CONFIG_OFFSET,
                      SMU015_MBOX_FILTER_CFG_NS);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static int run_mbox_irq_sequence(void)
{
    /* a. Aperture + inbound mailbox filters (32-bit CSR writes). */
    program_sep_setup();

    /* b. Open the SEP outbound egress filter over the SEP->SMC region, then frontdoor-boot the
     *    SMC exactly like SEP_SMU_002/004: wait the EXACT SRAM cookie, then re-vector + release
     *    the four SMC cores. On preload timeout, publish a fail marker and stop. */
    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)SMU015_SMC_ENTRY,
                                  SMU015_SMC_IMAGE_FIRST_WORD,
                                  SMU015_POLL_LIMIT) != 0) {
        return -1;
    }

    /* c. Gate on the SMC "up" marker before the first SMC-scratch write (mirrors the 002/004
     *    INIT_RELEASE_OK gate): POLL scratch2 for SMC_UP so READY can never race the SMC clearing
     *    its own scratch. */
    if (sep_smc_scratch_wait(SMU015_SMC_SCRATCH2_ALIAS, SMU015_SMC_UP, SMU015_POLL_LIMIT) != 0) {
        return -2;
    }

    /* d. Publish READY: the SEP aperture/inbound filters are up, so the SMC may now arm and access
     *    every mailbox inbound port. The SMC waits on this before arming. */
    sep_smc_scratch_write(SMU015_SMC_SCRATCH12_ALIAS, SMU015_READY);

    /* e. Wait for the SMC to arm all eight inbound IRQs (scratch3 == ARMED). Only then can a push
     *    assert the packed IRQ (the inbound output is IRQEN-gated). */
    if (sep_smc_scratch_wait(SMU015_SMC_SCRATCH3_ALIAS, SMU015_PROGRESS_ARMED, SMU015_POLL_LIMIT) != 0) {
        return -3;
    }

    /* f. Walk all eight channels strictly one at a time. Push token[ch] -> that channel's source
     *    IRQ asserts (packed one-hot) -> the SMC pops/verifies/W1C/reads-back-0/holds-quiet and
     *    publishes (ARMED | (ch+1)). The SEP waits that exact value before pushing ch+1, so at
     *    most one channel's IRQ is ever asserted (one-hot) and the no-refire window is honoured. */
    for (uint32_t ch = 0; ch < SMU015_NUM_CHANNELS; ++ch) {
        WRITE_REG(sep_mbox_wdata(ch), (uint32_t)(SMU015_TOKEN_BASE | ch));
        __asm__ volatile("fence iorw, iorw" ::: "memory");
        if (sep_smc_scratch_wait(SMU015_SMC_SCRATCH3_ALIAS, SMU015_PROGRESS_ARMED | (ch + 1u),
                                 SMU015_POLL_LIMIT) != 0) {
            return -4;
        }
    }

    /* g. After channel 7, wait for the SMC final verdict (SMU015_SMC_PASS) read through the real
     *    SEP->SMC alias 0x400390D0 (the cocotb captures RDATA/RRESP/RID/RLAST on this read). */
    if (sep_smc_scratch_wait(SMU015_SMC_SCRATCH10_ALIAS, SMU015_SMC_PASS, SMU015_POLL_LIMIT) != 0) {
        return -5;
    }

    return 0;
}

int main(void)
{
    int rc = run_mbox_irq_sequence();
    if (rc == 0) {
        /* SEP completion AFTER the SMC verdict: write SEP_PASS to cold scratch6 and park. */
        WRITE_REG(SMU015_SEP_COLD_SCRATCH6, SMU015_SEP_PASS);
        __asm__ volatile("fence iorw, iorw" ::: "memory");
        smu_sep_mailbox_irq_sep_pass_loop();
    } else {
        WRITE_REG(SMU015_SEP_COLD_SCRATCH6, SMU015_SEP_FAIL);
        __asm__ volatile("fence iorw, iorw" ::: "memory");
        smu_sep_mailbox_irq_sep_fail_loop();
    }
    return rc;
}
