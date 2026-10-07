/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef CLA_SANITY_SEQUENCE_H
#define CLA_SANITY_SEQUENCE_H

/* CLA sanity sequence for the cpu_traffic super-loop: three CLA
 * functional-register reads. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

int cla_sanity_sequence(int hartid) {
    info_msg_s(hartid, "cla_sanity_sequence: Starting");

    uint32_t read_cla_cdgnode0ap0;
    read_cla_cdgnode0ap0 = read_reg(SMC_TOP_SMC_CLA_CLA_CDBGNODE0EAP0_BASE_ADDR(0));
    write_scratch(2, read_cla_cdgnode0ap0);

    uint32_t read_cla_ctrl_status;
    read_cla_ctrl_status = read_reg(SMC_TOP_SMC_CLA_CLA_CDBGCLACTRLSTATUS_BASE_ADDR(0));
    write_scratch(2, read_cla_ctrl_status);

    uint32_t read_cla_scratch;
    read_cla_scratch = read_reg(SMC_TOP_SMC_CLA_CLA_SCRATCH_BASE_ADDR(0));
    write_scratch(2, read_cla_scratch);

    info_msg_s(hartid, "cla_sanity_sequence: Ending");

    return 0;
}

#endif
