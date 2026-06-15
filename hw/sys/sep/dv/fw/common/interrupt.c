/*
 * VeeR EL2 PIC interrupt utilities
 *
 * Uses RDL-generated constants from och_sep_top_reg.h
 */

#include "interrupt.h"
#include "och_sep_top_reg.h"

extern char INTVEC_BASE[];

// Helper to write a PIC register with fence
static inline void pic_write_reg(uint32_t addr, uint32_t value) {
    volatile uint32_t *reg = (volatile uint32_t *)addr;
    *reg = value;
    __asm__ volatile("fence" ::: "memory");
}

void pic_register_handler(uint32_t source_id, pic_handler_t handler) {
    uint32_t *vectbl = (uint32_t *)INTVEC_BASE;
    vectbl[source_id] = (uint32_t)handler;
    __asm__ volatile("fence" ::: "memory");
}

void pic_set_priority(uint32_t source_id, uint32_t priority) {
    // meipl array: source_id 1 -> meipl[0], source_id 2 -> meipl[1], etc.
    // PIC_MEIPL_0__REG_ADDR is address of meipl[0] (for source_id 1)
    uint32_t addr = PIC_MEIPL_0__REG_ADDR + (source_id - 1) * 4;
    pic_write_reg(addr, priority & EL2_PIC_MEIPL_INTPRIORITY_MASK);
}

void pic_set_gateway(uint32_t source_id, uint32_t type, uint32_t polarity) {
    // meigwctrl array: source_id 1 -> meigwctrl[0], etc.
    uint32_t addr = PIC_MEIGWCTRL_0__REG_ADDR + (source_id - 1) * 4;
    EL2_PIC_MEIGWCTRL_reg_u val = {
        .f = {
            .polarity = polarity & 0x1,
            .irq_type = type & 0x1
        }
    };
    pic_write_reg(addr, val.val);
}

void pic_enable_source(uint32_t source_id) {
    // meie array: source_id 1 -> meie[0], etc.
    uint32_t addr = PIC_MEIE_0__REG_ADDR + (source_id - 1) * 4;
    pic_write_reg(addr, 1);
}

void pic_disable_source(uint32_t source_id) {
    // meie array: source_id 1 -> meie[0], etc.
    uint32_t addr = PIC_MEIE_0__REG_ADDR + (source_id - 1) * 4;
    pic_write_reg(addr, 0);
}

void pic_enable_interrupts(void) {
    __asm__ volatile("csrwi 0xBC9, 0");                      // meipt = 0
    __asm__ volatile("csrwi 0xBCC, 0");                      // meicurpl = 0
    __asm__ volatile("csrs mie, %0" :: "r"(1 << 11));        // mie.meie
    __asm__ volatile("csrs mstatus, %0" :: "r"(1 << 3));     // mstatus.mie
}

void pic_disable_interrupts(void) {
    __asm__ volatile("csrc mstatus, %0" :: "r"(1 << 3));     // mstatus.mie
}
