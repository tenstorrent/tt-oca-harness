// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC counterpart for the SEP bidirectional handshake
// (hw/sys/sep/dv/fw/tests/sep_smu_bidirect). That image drives the SEP half
// and stalls at its first wait without this one.
//
// Protocol, as defined by the SEP-side firmware; the patterns and addresses
// below must match it:
//
//   SEP   opens the route from the SMC into SEP cold scratch, opens its
//         filter windows and checks access to SMC scratch, then
//   SEP   -> SMC scratch = SEP_READY
//   SMC   -> SEP cold scratch = SMC_TO_SEP
//   SEP   -> SMC scratch = SEP_ACK
//   SMC   -> SEP cold scratch = SMC_DONE
//   SEP   parks in its pass loop.
//
// The SEP writes SEP_READY only after it opens the route, so this side never
// writes into the SEP before the route exists. The SMC output fabric passes
// traffic by default, so this side programs no filters of its own.

#include <stdint.h>

#define SMC_SCRATCH_BASE ((uintptr_t)0xC0039080u)
#define SMC_SCRATCH_STRIDE 8u
#define SMC_SCRATCH(n) (SMC_SCRATCH_BASE + ((n)*SMC_SCRATCH_STRIDE))

#define SMC_SCRATCH12 SMC_SCRATCH(12)
#define SEP_COLD_SCRATCH0 ((uintptr_t)0x10802000u)

#define SEP_READY_PATTERN 0x51EAD001u
#define SEP_TO_SMC_ACK_PATTERN 0x5E9ACCE5u
#define SMC_TO_SEP_PATTERN 0xC001CAFEu
#define SMC_TO_SEP_DONE_PATTERN 0xD0E0F00Du

// Longer than the SEP side's poll bound, so a stall is attributed to the side
// that stopped, not to this one giving up first.
#define SMC_WAIT_ITERS 4000000u

// Progress markers for the testbench: a stalled run shows which step of the
// handshake it reached.
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
