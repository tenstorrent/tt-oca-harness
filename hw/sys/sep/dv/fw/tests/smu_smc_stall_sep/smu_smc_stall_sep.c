#include <stdint.h>
#include <stddef.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "test_completion.h"
#include "sep_smc_bringup.h"   /* common: sep_smc_open_window / _bringup_from_sram / _scratch_* */
#include "smu_smc_stall_protocol.h"

/*
 * SEP_SMU_004  smu_smc_stall_sep  --  SEP (consumer) firmware.
 *
 * The real SEP CPU boots from reset, brings the SMC up over the (unfiltered) SEP->SMC port
 * using the common sep_smc_bringup helpers (open outbound window -> wait exact SRAM cookie
 * -> re-vector + release the SMC cores), then proves it is live (READY) and actively reading
 * the SMC command channel (POLL_ARMED via the PROBE handshake). It is frozen by CLA halt
 * driven from the SMC; while frozen it cannot consume GO. On CLA release it resumes, consumes
 * GO (GO_SEEN) and runs the acknowledged completion protocol (COMPLETION -> ACK -> PASS). All
 * SEP<->SMC traffic goes through the SEP->SMC alias (no ext_in, no force). 004 verifies the
 * CLA halt/run crossing, NOT the production SMC secure-boot / manifest / BL1 flow.
 */

__attribute__((noinline, used)) void smu_smc_stall_sep_pass_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

__attribute__((noinline, used)) void smu_smc_stall_sep_fail_loop(void)
{
    while (1) { __asm__ volatile("wfi"); }
}

static int run_stall_sequence(void)
{
    /* Open the SEP outbound egress window over the SEP->SMC region (common helper). */
    sep_smc_open_window();

    /* Frontdoor boot (common helper): wait for the EXACT SRAM preload cookie, then re-vector
     * + release the four SMC cores. On preload timeout, publish S0_FAIL and stop -- never
     * proceed on an absent/bad preload. */
    if (sep_smc_bringup_from_sram((uint32_t)SMU_STALL_SMC_ENTRY,
                                  SMU_STALL_SMC_IMAGE_FIRST_WORD,
                                  SMU_STALL_FW_POLL_LIMIT) != 0) {
        sep_smc_scratch_write(SMU_STALL_RSP_ALIAS_ADDR, SMU_STALL_S0_FAIL);
        return -11;
    }

    /* Gate on the SMC initial-release marker so READY can never race the SMC scratch clear. */
    if (sep_smc_scratch_wait(SMU_STALL_STATUS_ALIAS_ADDR, SMU_STALL_INIT_RELEASE_OK,
                             SMU_STALL_FW_POLL_LIMIT) != 0) {
        return -1;
    }

    /* Publish READY, then enter the GO-poll loop. */
    sep_smc_scratch_write(SMU_STALL_RSP_ALIAS_ADDR, SMU_STALL_READY);

    /* PROBE -> POLL_ARMED handshake: prove we are actively reading the command channel
     * before the SMC halts us. */
    if (sep_smc_scratch_wait(SMU_STALL_CMD_ALIAS_ADDR, SMU_STALL_PROBE,
                             SMU_STALL_FW_POLL_LIMIT) != 0) {
        return -2;
    }
    sep_smc_scratch_write(SMU_STALL_RSP_ALIAS_ADDR, SMU_STALL_POLL_ARMED);

    /* Poll for GO. The SMC halts us here (after HALT_OK); while frozen we cannot observe GO.
     * On CLA release we resume and consume it. */
    if (sep_smc_scratch_wait(SMU_STALL_CMD_ALIAS_ADDR, SMU_STALL_GO,
                             SMU_STALL_FW_POLL_LIMIT) != 0) {
        return -3;
    }
    sep_smc_scratch_write(SMU_STALL_RSP_ALIAS_ADDR, SMU_STALL_GO_SEEN);

    /* Acknowledged completion protocol. */
    if (sep_smc_scratch_wait(SMU_STALL_CMD_ALIAS_ADDR, SMU_STALL_RELEASE_GATE,
                             SMU_STALL_FW_POLL_LIMIT) != 0) {
        return -4;
    }
    sep_smc_scratch_write(SMU_STALL_RSP_ALIAS_ADDR, SMU_STALL_COMPLETION);

    if (sep_smc_scratch_wait(SMU_STALL_CMD_ALIAS_ADDR, SMU_STALL_ACK,
                             SMU_STALL_FW_POLL_LIMIT) != 0) {
        return -5;
    }
    sep_smc_scratch_write(SMU_STALL_RSP_ALIAS_ADDR, SMU_STALL_PASS);

    return 0;
}

int main(void)
{
    int rc = run_stall_sequence();
    if (rc == 0) {
        smu_smc_stall_sep_pass_loop();
    } else {
        smu_smc_stall_sep_fail_loop();
    }
    return rc;
}
