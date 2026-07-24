// SPDX-License-Identifier: Apache-2.0
// SMC firmware that arms the real SEP CPU through the CLA custom actions.

#include <stdint.h>

#define SMC_SCRATCH0_ADDR ((uintptr_t)0xC0039080u)
#define SMC_CLA_CDFDCSR_ADDR ((uintptr_t)0xC01601A0u)
#define SMC_CLA_EAP0_ADDR ((uintptr_t)0xC0163120u)
#define SMC_CLA_EAP1_ADDR ((uintptr_t)0xC0163128u)
#define SMC_CLA_CTRL_ADDR ((uintptr_t)0xC0163190u)

#define SMC_TEST_PASS 0xACAFACA1u
#define CLA_ENABLE_EAP 0x20u
#define CLA_ENABLE 0x40u

static uint64_t cla_eap_value(uint32_t action0, uint32_t action1, int enable1)
{
    uint64_t value = 0;
    value |= (uint64_t)3u << 14;   // NOR
    value |= (uint64_t)63u << 16;  // event-none 0
    value |= (uint64_t)62u << 22;  // event-none 1
    value |= (uint64_t)action0 << 28;
    value |= (uint64_t)action1 << 32;
    value |= (uint64_t)1u << 36;
    if (enable1) {
        value |= (uint64_t)1u << 37;
    }
    return value;
}

static void write64(uintptr_t address, uint64_t value)
{
    *((volatile uint64_t *)address) = value;
}

int main(void)
{
    // #3582 inverted custom action 2. Normal boot fires only run actions 1 and 4.
    write64(SMC_CLA_CDFDCSR_ADDR, (uint64_t)1u << 63);
    write64(SMC_CLA_CTRL_ADDR, CLA_ENABLE | CLA_ENABLE_EAP);
    write64(SMC_CLA_EAP0_ADDR, cla_eap_value(1u, 4u, 1));
    write64(SMC_CLA_EAP1_ADDR, cla_eap_value(4u, 4u, 0));
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    *((volatile uint32_t *)SMC_SCRATCH0_ADDR) = SMC_TEST_PASS;
    for (;;) {
        __asm__ volatile("wfi");
    }
}
