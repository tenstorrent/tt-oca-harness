/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef CLA_SANITY_SEQUENCE_H
#define CLA_SANITY_SEQUENCE_H

/* CLA sanity sequence for the cpu_traffic super-loop.
 *
 * Ported from tt-oca-hw/fw/smc/test_sequences/cla_sanity_sequence.h. Only the
 * active upstream body (three CLA functional-register reads) is kept; the rest
 * was already commented out upstream because the registers were removed. The
 * legacy SMC_CLA_*_REG_ADDR macros are migrated to the native PeakRDL
 * SMC_TOP_SMC_CLA_*_BASE_ADDR names. CLA is open IP. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

int cla_sanity_sequence(int hartid) {
    info_msg_s(hartid, "cla_sanity_sequence: Starting");

    // Read from cla functional register
    uint32_t read_cla_cdgnode0ap0;
    read_cla_cdgnode0ap0 = read_reg(SMC_TOP_SMC_CLA_CDBGNODE0EAP0_BASE_ADDR);
    write_scratch(2, read_cla_cdgnode0ap0);

    // Read from ctrl status cla functional register
    uint32_t read_cla_ctrl_status;
    read_cla_ctrl_status = read_reg(SMC_TOP_SMC_CLA_CDBGCLACTRLSTATUS_BASE_ADDR);
    write_scratch(2, read_cla_ctrl_status);

    // Read from cla status functional register
    uint32_t read_cla_scratch;
    read_cla_scratch = read_reg(SMC_TOP_SMC_CLA_SCRATCH_BASE_ADDR);
    write_scratch(2, read_cla_scratch);

    info_msg_s(hartid, "cla_sanity_sequence: Ending");

    return 0;
}

#endif
