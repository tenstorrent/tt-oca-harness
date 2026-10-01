// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC counterpart for the SEP bidirectional handshake
// (hw/sys/sep/dv/fw/tests/sep_smu_bidirect). That image drives the SEP half;
// without this one it stalls at its first wait and reports -100.
//
// Protocol, as defined by the SEP-side firmware; the patterns and addresses
// below must match it:
//
//   SEP   programs its SMU xbar aperture to [0, 0x2000_0000) so SMC->SEP writes
//         reach SEP cold scratch, opens its outbound/inbound filter windows,
//         read/write-checks SMC scratch8..11, then
//   SEP   -> SMC scratch12 = SEP_READY
//   SMC   -> SEP cold scratch0 = SMC_TO_SEP
//   SEP   -> SMC scratch12 = SEP_ACK
//   SMC   -> SEP cold scratch0 = SMC_DONE
//   SEP   parks in its pass loop.
//
// The SEP writes SEP_READY only after programming the aperture, so this side
// never writes into the SEP before the route exists -- the ordering is carried
// by the handshake itself rather than by a delay.
//
// Addresses: SMC scratch is at 0xC003_9080 locally (stride 8) and appears to the
// SEP at 0x4003_9080 through the SMC aperture; SEP cold scratch0 is 0x1080_2020,
// inside the aperture the SEP programs for itself. The SMC output fabric is
// BlockByDefault=0, so this side needs no filter programming of its own.

#include <stdint.h>

#define SMC_SCRATCH_BASE ((uintptr_t)0xC0039080u)
#define SMC_SCRATCH_STRIDE 8u
#define SMC_SCRATCH(n) (SMC_SCRATCH_BASE + ((n)*SMC_SCRATCH_STRIDE))

#define SMC_SCRATCH12 SMC_SCRATCH(12)
// SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(n) = 0x10802000 + n*8.
#define SEP_COLD_SCRATCH0 ((uintptr_t)0x10802000u)

#define SEP_READY_PATTERN 0x51EAD001u
#define SEP_TO_SMC_ACK_PATTERN 0x5E9ACCE5u
#define SMC_TO_SEP_PATTERN 0xC001CAFEu
#define SMC_TO_SEP_DONE_PATTERN 0xD0E0F00Du

// The SEP side polls with a 1e6-iteration bound; stay well above it so a real
// stall is attributed to whichever side actually stopped, not to this one
// giving up first.
#define SMC_WAIT_ITERS 4000000u

// Progress markers for the testbench, in scratch0. A run that stalls says which
// half of the handshake it reached instead of only timing out.
#define SMC_PHASE_ADDR SMC_SCRATCH(0)
#define SMC_PHASE_ENTERED 0x5C000001u
#define SMC_PHASE_SAW_READY 0x5C000002u
#define SMC_PHASE_SAW_ACK 0x5C000003u
#define SMC_PHASE_DONE 0x5C000004u
#define SMC_PHASE_TIMEOUT_READY 0x5CBAD001u
#define SMC_PHASE_TIMEOUT_ACK 0x5CBAD002u

static inline void wr32(uintptr_t addr, uint32_t value) {
    *((volatile uint32_t *)addr) = value;
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static inline uint32_t rd32(uintptr_t addr) {
    return *((volatile uint32_t *)addr);
}

static int wait_for(uintptr_t addr, uint32_t expected) {
    for (uint32_t i = 0; i < SMC_WAIT_ITERS; i++) {
        if (rd32(addr) == expected) {
            return 0;
        }
    }
    return -1;
}

int main(void) {
    wr32(SMC_PHASE_ADDR, SMC_PHASE_ENTERED);

    if (wait_for(SMC_SCRATCH12, SEP_READY_PATTERN) != 0) {
        wr32(SMC_PHASE_ADDR, SMC_PHASE_TIMEOUT_READY);
        for (;;) {
            __asm__ volatile("wfi");
        }
    }
    wr32(SMC_PHASE_ADDR, SMC_PHASE_SAW_READY);
    wr32(SEP_COLD_SCRATCH0, SMC_TO_SEP_PATTERN);

    if (wait_for(SMC_SCRATCH12, SEP_TO_SMC_ACK_PATTERN) != 0) {
        wr32(SMC_PHASE_ADDR, SMC_PHASE_TIMEOUT_ACK);
        for (;;) {
            __asm__ volatile("wfi");
        }
    }
    wr32(SMC_PHASE_ADDR, SMC_PHASE_SAW_ACK);
    wr32(SEP_COLD_SCRATCH0, SMC_TO_SEP_DONE_PATTERN);

    wr32(SMC_PHASE_ADDR, SMC_PHASE_DONE);
    for (;;) {
        __asm__ volatile("wfi");
    }
}
