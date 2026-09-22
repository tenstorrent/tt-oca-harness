/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>
#include <stddef.h>

#include "och_sep_common.h"
#include "sep.h"
#include "sep_outbound_filter.h" /* common: sep_outbound_filter_init() (0x80000000 egress) */
#include "sep_smc_bringup.h"     /* common: sep_smc_open_window / _bringup_from_sram */
#include "smu_sep_ext_axi_protocol.h"

/*
 * smu_sep_ext_axi_combined_probe_test  --  SEP external-egress firmware.
 *
 * The SEP is BOTH the primary that releases the SMC and the outbound producer for the
 * SEP->ext_out leg.  It:
 *   S1  (SEP is the PRIMARY, runs FIRST) releases the four SMC cores over the SEP->SMC alias
 *       -- identical to the smc_sep_xbar SEP fw: sep_smc_open_window() opens the outbound egress
 *       window over the SEP->SMC region, then sep_smc_bringup_from_sram() waits (bounded, same
 *       poll-limit idiom) for the SMC image cookie in SRAM and, once present, re-vectors +
 *       pulses reset on all four SMC cores.  Without this the SMC never boots, SMC_READY never
 *       appears, and the whole SMC side of the dual-firmware test fails.  The ENTRY/cookie are
 *       derived from THIS test's SMC image (hw/sys/smc/dv/fw/tests/smu_sep_ext_axi;
 *       EXTAXI_SMC_ENTRY / EXTAXI_SMC_IMAGE_FIRST_WORD in smu_sep_ext_axi_protocol.h).
 *   S2  programs + READS BACK its own aperture (sep_global_base/sep_region_size),
 *       opens its inbound windows (so tb.ext_in can reach SEP cold scratch for the
 *       GO/ROUTE_DONE barrier + the ext_in->SEP route leg), and opens its outbound
 *       egress filter covering 0x80000000.  Any mismatch/bus fault -> the SEP fail loop
 *       (writes 0x160AFFEE).
 *   S3  publishes SEP_READY=0x16050002 at cold scratch4 and polls SEP_GO=0x16060002
 *       at cold scratch5 (tb.ext_in writes GO only after both firmware setups proven).
 *   S6  after GO, emits 0xA5A55A5A then 0xCAFEBABE to 0x80000000 so the SEP
 *       {00,sep_id} default-master fall-through route reaches ext_out (CHK-SEP-OUT).
 *   S10 waits (bounded) for ROUTE_DONE_SEP=0x160D0002 at cold scratch7, then writes
 *       SMU016_SEP_PASS=0x160A0001 to LOCAL cold scratch6 and parks in
 *       smu_sep_ext_axi_sep_pass_loop.
 *
 * The egress store to 0x80000000 is the CHK-SEP-OUT stimulus.  Every wait
 * after it is bounded so the firmware never hangs -- if ROUTE_DONE/PASS cannot be reached
 * the SEP parks at a defined, named PC (the fail loop); if the store itself does not
 * complete, the SEP sits at the (also defined) store PC.  DV reports the observed PC and
 * phase and adjudicates the egress behaviour from the run rather than preassigning a cause.
 *
 * The outbound/inbound filter blocks are write-only programming interfaces (a CPU read
 * of one stalls), so only the aperture CSRs are read back in firmware; the filter
 * values are verified DV-side by passive DUT reads (same policy as smc_sep_xbar).
 *
 * allow_ns is an exact AxPROT[1] match (traffic_filter.sv), so each inbound window is
 * programmed with a SECURE rule (rule0) AND an NS rule (rule1) covering the same range
 * -> the ext_in->SEP leg passes regardless of the initiator's security level.
 */

/* SEP aperture CSRs (readable). GLOBAL_BASE is 64-bit; REGION_SIZE is 32-bit. */
#define SEP_GLOBAL_BASE_REG \
    SEP_TOP_SEP_CPU_CTRL_SEP_GLOBAL_BASE_ADDR_BASE_ADDR                    /* 0x10A300C0 \
                                                                            */
#define SEP_REGION_SIZE_REG SEP_TOP_SEP_CPU_CTRL_SEP_REGION_SIZE_BASE_ADDR /* 0x10A300D0 */

/* SEP-local cold scratch barrier registers (8-byte stride). */
#define COLD4 \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(4) /* 0x10802020 SEP_READY (SEP -> ext_in) */
#define COLD5 \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(5) /* 0x10802028 SEP_GO    (ext_in -> SEP) */
#define COLD6 \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6) /* 0x10802030 SMU016_SEP_PASS (LOCAL) \
                                                   */
#define COLD7 \
    SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7) /* 0x10802038 ROUTE_DONE_SEP (ext_in -> SEP) */

/* SEP inbound filter: cover the cold scratch region (cold0..cold7) so ext_in can reach
 * the barrier + route-data registers. Secure (rule0) + NS (rule1).
 * The SEP inbound traffic filter (BlockByDefault=1) sits BEFORE the global->local remap
 * (axi_window_remap, target_base=0), so it evaluates the GLOBAL address the external master
 * presents. That global must equal sep_global_base + local so the remap subtracts back to
 * the real SEP-local cold-scratch register: 0x04000000 + 0x108020xx = 0x148020xx (the
 * EXTAXI_SEP_COLD*_GLOBAL values). Programming 0x048020xx would both miss the intended local
 * (remaps to 0x008020xx) and, once region_size covers it, still target the wrong register --
 * so the window is programmed at the 0x148020xx globals. */
#define SEP_INB_BASE SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0)  /* 0x10A21000 */
#define SEP_INB_START ((uint64_t)EXTAXI_SEP_COLD0_GLOBAL)      /* 0x14802000 GLOBAL */
#define SEP_INB_END ((uint64_t)EXTAXI_SEP_COLD7_GLOBAL + 7ULL) /* 0x1480203F GLOBAL */

static volatile int g_status;

/* Program the SEP aperture and read it back. Returns 0 on match, -1 on mismatch. */
static int program_sep_aperture(void) {
    WRITE_REG64(SEP_GLOBAL_BASE_REG, (uint64_t)EXTAXI_SEP_GLOBAL_BASE);
    WRITE_REG(SEP_REGION_SIZE_REG, (uint32_t)EXTAXI_SEP_REGION_SIZE);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (READ_REG64(SEP_GLOBAL_BASE_REG) != (uint64_t)EXTAXI_SEP_GLOBAL_BASE) {
        return -1;
    }
    if (READ_REG(SEP_REGION_SIZE_REG) != (uint32_t)EXTAXI_SEP_REGION_SIZE) {
        return -1;
    }
    return 0;
}

/* Open the SEP inbound filter over the cold scratch region (secure + NS rules). */
static void open_sep_inbound_window(void) {
    uintptr_t base = (uintptr_t)SEP_INB_BASE;

    WRITE_REG64(base + EXTAXI_FILTER_START_OFF, SEP_INB_START);
    WRITE_REG64(base + EXTAXI_FILTER_END_OFF, SEP_INB_END);
    WRITE_REG64(base + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_SECURE);

    base += EXTAXI_FILTER_STRIDE;
    WRITE_REG64(base + EXTAXI_FILTER_START_OFF, SEP_INB_START);
    WRITE_REG64(base + EXTAXI_FILTER_END_OFF, SEP_INB_END);
    WRITE_REG64(base + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_NS);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

/* Bounded poll of a local register for an exact value. Returns 0 on match, -1 on timeout. */
static int wait_reg_eq(uintptr_t addr, uint32_t expected) {
    for (uint32_t i = 0; i < EXTAXI_FW_POLL_LIMIT; ++i) {
        if (READ_REG(addr) == expected) {
            return 0;
        }
    }
    return -1;
}

static int run_sep_ext_axi_sequence(void) {
    /* S1 (SEP is the PRIMARY, runs FIRST): release the four SMC cores over the SEP->SMC alias,
     * exactly as the smc_sep_xbar SEP fw. Open the outbound egress window over the SEP->SMC region
     * (0x40000000..0x800000FF), then sep_smc_bringup_from_sram() waits (bounded, same poll-limit
     * idiom) for the SMC image cookie in SRAM and only then re-vectors + pulses reset on all four
     * SMC cores. Without this the SMC never boots and SMC_READY never appears. The later
     * sep_outbound_filter_init() re-narrows this same outbound filter (entry 0) to the 0x80000000
     * egress range; the SMC bring-up completes before that, and 0x80000000 stays in range. */
    sep_smc_open_window();
    if (sep_smc_bringup_from_sram((uint32_t)EXTAXI_SMC_ENTRY, EXTAXI_SMC_IMAGE_FIRST_WORD,
                                  EXTAXI_FW_POLL_LIMIT) != 0) {
        return -4; /* SMC image cookie never landed within poll_limit -> SEP fail loop */
    }

    /* S2 (setup): aperture program + readback (real fault check). */
    if (program_sep_aperture() != 0) {
        return -1;
    }

    /* S2 (setup): inbound windows for ext_in -> SEP; outbound egress for 0x80000000.
     * sep_outbound_filter_init() opens the all-pass egress over 0x80000000..0x800000FF
     * (identical to sep_smc_notify). Filters are write-only -> no CPU readback. */
    open_sep_inbound_window();
    sep_outbound_filter_init();

    /* Clear the SEP-owned poll targets so the DV sees clean 0 -> token transitions.
     * Do NOT touch cold scratch0 (ext_in route data). */
    WRITE_REG(COLD5, 0u); /* SEP_GO poll target */
    WRITE_REG(COLD6, 0u); /* SMU016_SEP_PASS */
    WRITE_REG(COLD7, 0u); /* ROUTE_DONE_SEP poll target */
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    /* S3 (barrier): publish SEP_READY at cold scratch4, then poll SEP_GO at cold scratch5. */
    WRITE_REG(COLD4, EXTAXI_SEP_READY);
    __asm__ volatile("fence iorw, iorw" ::: "memory");
    if (wait_reg_eq(COLD5, EXTAXI_SEP_GO) != 0) {
        return -2;
    }

    /* S6 (egress): two-word SEP->ext_out payload to non-aperture 0x80000000. The xbar
     * default-master fall-through routes it to ext_out with ID {00,sep_id}
     * (CHK-SEP-OUT stimulus). Whether it reaches ext_out is adjudicated from the run. */
    WRITE_REG(EXTAXI_SEP_OUT_ADDR, EXTAXI_SEP_OUT_DATA0);
    WRITE_REG(EXTAXI_SEP_OUT_ADDR, EXTAXI_SEP_OUT_DATA1);
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    /* S10 (complete): bounded-wait for ROUTE_DONE_SEP (ext_in writes it only after all
     * four legal legs + DECERR + recovery). Timeout -> fail loop (defined named PC). */
    if (wait_reg_eq(COLD7, EXTAXI_ROUTE_DONE_SEP) != 0) {
        return -3;
    }
    return 0;
}

__attribute__((noinline, used)) void smu_sep_ext_axi_sep_pass_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((noinline, used)) void smu_sep_ext_axi_sep_fail_loop(void) {
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void) {
    g_status = run_sep_ext_axi_sequence();

    if (g_status == 0) {
        /* No final marker may precede its ROUTE_DONE readback: PASS is written only now. */
        WRITE_REG(COLD6, EXTAXI_SEP_PASS);
        __asm__ volatile("fence iorw, iorw" ::: "memory");
        smu_sep_ext_axi_sep_pass_loop();
    } else {
        WRITE_REG(COLD6, EXTAXI_SEP_FAIL);
        __asm__ volatile("fence iorw, iorw" ::: "memory");
        smu_sep_ext_axi_sep_fail_loop();
    }

    return g_status;
}
