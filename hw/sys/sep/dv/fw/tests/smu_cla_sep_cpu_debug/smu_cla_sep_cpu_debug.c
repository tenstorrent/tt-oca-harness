#include <stdint.h>
#include <stddef.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "test_completion.h"
#include "sep_smc_bringup.h"   /* common: sep_smc_open_window / _bringup_from_sram / _scratch_* */
#include "smu_cla_sep_cpu_debug_protocol.h"

/*
 * SEP_SMU_022  smu_cla_sep_cpu_debug_control_test  --  SEP (consumer) firmware.
 *
 * The real SEP CPU boots from reset, brings the SMC up over the SEP->SMC port (common
 * sep_smc_bringup helpers -- force-free, no ext_in, no pc_loop_common Force), then serves as
 * the CLA-controlled workload:
 *   BUSY workload  : a continuous outbound-poll loop (LSU-active, retiring) that the SMC's CLA
 *                    action[0] DEBUG-halt freezes and action[1] resumes, and against which
 *                    action[3] PMU-halt is characterized (LSU never idle -> quiescence-gated).
 *   IDLE workload  : on GO_IDLE the SEP acks then WFI (no-LSU, quiescent) so action[3] PMU-halt
 *                    can complete (core_empty=1). Two workloads are REQUIRED to establish the
 *                    PMU-halt semantics -- see CHK-PMU-HALT-DIAG. This fw only provides the
 *                    workloads; the cocotb scoreboard classifies the VeeR handshake.
 */

__attribute__((noinline, used)) void smu_cla_sep_cpu_debug_pass_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

__attribute__((noinline, used)) void smu_cla_sep_cpu_debug_fail_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

static int run_cla_debug_consumer(void)
{
    /* Force-free frontdoor boot of the SMC over the SEP->SMC port (common helper). */
    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)CLADBG_SMC_ENTRY,
                                  CLADBG_SMC_IMAGE_FIRST_WORD,
                                  CLADBG_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(CLADBG_RSP_ALIAS_ADDR, CLADBG_S0_FAIL);
        return -1;
    }

    /* Gate on the SMC initial-release marker, then publish READY. */
    if (sep_smc_scratch_wait(CLADBG_STATUS_ALIAS_ADDR, CLADBG_INIT_RELEASE_OK,
                             CLADBG_FW_POLL_LIMIT) != 0) {
        return -2;
    }
    sep_smc_scratch_write(CLADBG_RSP_ALIAS_ADDR, CLADBG_READY);

    /* BUSY workload: continuously read the SMC->SEP command channel (outbound reads keep the
     * LSU active and the core retiring) until GO_IDLE. The SMC drives action[0] DEBUG-halt
     * (freezes this loop), action[1] DEBUG-run (resumes it), and action[3] PMU-halt (busy)
     * across this window; the cocotb observes the effects. */
    uint32_t saw_go_idle = 0;
    for (uint32_t i = 0; i < CLADBG_FW_POLL_LIMIT; ++i) {
        if (READ_REG(CLADBG_CMD_ALIAS_ADDR) == CLADBG_GO_IDLE) {
            saw_go_idle = 1;
            break;
        }
    }
    if (!saw_go_idle) {
        return -3;
    }

    /* IDLE workload: ack, then WFI so the core quiesces (LSU idle, core_empty=1) and action[3]
     * PMU-halt can complete. Stay parked -- the cocotb observes o_cpu_halt_status. */
    sep_smc_scratch_write(CLADBG_RSP_ALIAS_ADDR, CLADBG_IDLE_ACK);
    for (;;) {
        __asm__ volatile("wfi");
    }
    return 0;
}

int main(void)
{
    int rc = run_cla_debug_consumer();
    if (rc == 0) {
        smu_cla_sep_cpu_debug_pass_loop();
    } else {
        smu_cla_sep_cpu_debug_fail_loop();
    }
    return rc;
}
