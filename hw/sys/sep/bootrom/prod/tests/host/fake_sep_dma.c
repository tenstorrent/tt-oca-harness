/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include "fake_sep_dma.h"

#include <string.h>

#include "rom_mmio.h"
#include "sep.h"
#include "status_ring.h"

#define MAX_REGS 512u
#define MAX_WRITES 4096u
#define MAX_CONSOLE 4096u
#define MAX_STATUS 64u

#define STATUS_ADDR SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR
#define CONTROL_ADDR SEP_TOP_SECURE_DMA_CONTROL_BASE_ADDR
#define ERROR_CODE_ADDR SEP_TOP_SECURE_DMA_ERROR_CODE_BASE_ADDR
#define CONSOLE_ADDR SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2)

#define W1C_BITS \
    (SECURE_DMA__STATUS__DONE_bm | SECURE_DMA__STATUS__ABORTED_bm | SECURE_DMA__STATUS__ERROR_bm | \
     SECURE_DMA__STATUS__CHUNK_DONE_bm)

static struct {
    fake_write_t regs[MAX_REGS];
    size_t nregs;
    fake_write_t log[MAX_WRITES];
    size_t nlog;
    char console[MAX_CONSOLE];
    size_t nconsole;
    uint16_t status_words[MAX_STATUS];
    size_t nstatus;

    uint32_t status;
    fake_dma_outcome_e outcome;
    uint32_t busy_polls;
    uint32_t error_code;
    uint32_t polls_left;
    int running;
    int drop_go;
    int ignore_w1c;
    int ignore_abort;
    unsigned ec_reads_left;
    uint32_t ec_late_value;
    int ec_late;
    uint32_t corrupt_addr;
    uint32_t corrupt_mask;
    unsigned go_count;
    unsigned bad_width;
} s;

static fake_write_t *find_reg(uint32_t addr) {
    for (size_t i = 0; i < s.nregs; ++i) {
        if (s.regs[i].addr == addr) return &s.regs[i];
    }
    return NULL;
}

static void store(uint32_t addr, uint32_t value) {
    fake_write_t *r = find_reg(addr);
    if (r == NULL && s.nregs < MAX_REGS) {
        r = &s.regs[s.nregs++];
        r->addr = addr;
    }
    if (r != NULL) r->value = value;
}

void fake_dma_reset(void) {
    memset(&s, 0, sizeof(s));
    s.outcome = FAKE_DMA_DONE;
    s.busy_polls = 2u;
}

void fake_dma_script(fake_dma_outcome_e outcome, uint32_t busy_polls, uint32_t error_code) {
    s.outcome = outcome;
    s.busy_polls = busy_polls;
    s.error_code = error_code;
}

void fake_dma_set_status(uint32_t status) {
    s.status = status;
}

void fake_dma_drop_go(int on) {
    s.drop_go = on;
}

void fake_dma_ignore_w1c(int on) {
    s.ignore_w1c = on;
}

void fake_dma_ignore_abort(int on) {
    s.ignore_abort = on;
}

void fake_dma_error_code_after_reads(unsigned reads, uint32_t value) {
    s.ec_late = 1;
    s.ec_reads_left = reads;
    s.ec_late_value = value;
}

void fake_dma_corrupt_on_write(uint32_t addr, uint32_t xor_mask) {
    s.corrupt_addr = addr;
    s.corrupt_mask = xor_mask;
}

void fake_mem_set(uint32_t addr, uint32_t value) {
    store(addr, value);
}

uint32_t fake_reg(uint32_t addr) {
    const fake_write_t *r = find_reg(addr);
    return r ? r->value : 0u;
}

const fake_write_t *fake_writes(size_t *count) {
    *count = s.nlog;
    return s.log;
}

size_t fake_writes_to(uint32_t addr) {
    size_t n = 0;
    for (size_t i = 0; i < s.nlog; ++i) n += (s.log[i].addr == addr);
    return n;
}

size_t fake_write_index(uint32_t addr, size_t from) {
    for (size_t i = from; i < s.nlog; ++i) {
        if (s.log[i].addr == addr) return i;
    }
    return s.nlog;
}

unsigned fake_go_count(void) {
    return s.go_count;
}

unsigned fake_bad_width_count(void) {
    return s.bad_width;
}

int fake_console_has(const char *text) {
    return strstr(s.console, text) != NULL;
}

int fake_status_has(uint16_t value) {
    for (size_t i = 0; i < s.nstatus; ++i) {
        if (s.status_words[i] == value) return 1;
    }
    return 0;
}

// Only the ASCII op of the virtual console is decoded; hex and decimal values
// are marked with '#'.
static void console_write(uint32_t v) {
    if ((v & 0xFFu) == 0u || (v & 0xFFu) == 1u) {
        for (int i = 1; i < 4; ++i) {
            const char c = (char)((v >> (8 * i)) & 0xFFu);
            if (c != 0 && s.nconsole + 1 < MAX_CONSOLE) s.console[s.nconsole++] = c;
        }
    } else if (s.nconsole + 1 < MAX_CONSOLE) {
        s.console[s.nconsole++] = '#';
    }
}

static void finish_run(void) {
    s.running = 0;
    s.status &= ~SECURE_DMA__STATUS__BUSY_bm;
    if (s.outcome == FAKE_DMA_ERROR) {
        s.status |= SECURE_DMA__STATUS__ERROR_bm;
        store(ERROR_CODE_ADDR, s.error_code);
    } else {
        s.status |= SECURE_DMA__STATUS__DONE_bm;
    }
}

uint32_t fake_mmio_read32(uint32_t addr) {
    if (addr == STATUS_ADDR) {
        if (s.running && s.outcome != FAKE_DMA_NEVER) {
            if (s.polls_left == 0u) {
                finish_run();
            } else {
                --s.polls_left;
            }
        }
        return s.status;
    }
    if (addr == ERROR_CODE_ADDR && s.ec_late) {
        if (s.ec_reads_left == 0u) return s.ec_late_value;
        --s.ec_reads_left;
    }
    return fake_reg(addr);
}

void fake_mmio_write32(uint32_t addr, uint32_t value) {
    if (s.nlog < MAX_WRITES) {
        s.log[s.nlog].addr = addr;
        s.log[s.nlog].value = value;
        ++s.nlog;
    }
    if (addr == CONSOLE_ADDR) {
        console_write(value);
        return;
    }
    if (addr == STATUS_ADDR) {
        if (!s.ignore_w1c) s.status &= ~(value & W1C_BITS);
        return;
    }
    if (addr == CONTROL_ADDR) {
        store(addr, value);
        if (value & SECURE_DMA__CONTROL__ABORT_bm) {
            if (s.ignore_abort) return;
            s.running = 0;
            s.status = (s.status & ~SECURE_DMA__STATUS__BUSY_bm) | SECURE_DMA__STATUS__ABORTED_bm;
            return;
        }
        if ((value & SECURE_DMA__CONTROL__GO_bm) && !s.drop_go &&
            !(s.status & SECURE_DMA__STATUS__BUSY_bm)) {
            ++s.go_count;
            s.running = 1;
            s.polls_left = s.busy_polls;
            s.status |= SECURE_DMA__STATUS__BUSY_bm;
        }
        return;
    }
    store(addr, addr == s.corrupt_addr ? value ^ s.corrupt_mask : value);
}

void fake_mmio_bad_width(uint32_t addr) {
    (void)addr;
    ++s.bad_width;
}

void fake_mmio_fence(void) {
}

void status_ring_buffer_insert(uint32_t value) {
    if (s.nstatus < MAX_STATUS) s.status_words[s.nstatus++] = (uint16_t)(value & 0xFFFFu);
}
