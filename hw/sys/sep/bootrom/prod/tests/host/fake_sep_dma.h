/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Scriptable stand-in for the secure DMA and the SEP scratch registers, for host
// tests of the ROM's DMA users.
//
// Every MMIO write is logged. Registers and memory words read back what was last
// written (0 if never written), except STATUS, which the script drives: a write
// to CONTROL with GO set starts a run that stays BUSY for `busy_polls` STATUS
// reads and then ends as the script says. STATUS clears DONE, ABORTED, ERROR and
// CHUNK_DONE on write-1-to-clear; CONTROL with ABORT ends a run. Console text
// written through cold_scratch[2] is decoded, and status words reported through
// the status ring are recorded.

#ifndef FAKE_SEP_DMA_H
#define FAKE_SEP_DMA_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    FAKE_DMA_DONE,  // DONE after the busy polls
    FAKE_DMA_ERROR, // ERROR and the scripted ERROR_CODE after the busy polls
    FAKE_DMA_NEVER  // BUSY until ABORT
} fake_dma_outcome_e;

typedef struct {
    uint32_t addr;
    uint32_t value;
} fake_write_t;

// Restores the defaults: idle, every run ends DONE after 2 busy polls.
void fake_dma_reset(void);

void fake_dma_script(fake_dma_outcome_e outcome, uint32_t busy_polls, uint32_t error_code);

// STATUS as it reads before the first CONTROL write (e.g. BUSY, or a stale DONE).
void fake_dma_set_status(uint32_t status);

// CONTROL writes with GO are dropped, as if the engine never saw them.
void fake_dma_drop_go(int on);

// Write-1-to-clear on STATUS has no effect.
void fake_dma_ignore_w1c(int on);

// CONTROL with ABORT leaves the engine BUSY, as an abort that does not drain.
void fake_dma_ignore_abort(int on);

// After `reads` reads of ERROR_CODE that return its stored value, later reads
// return `value`.
void fake_dma_error_code_after_reads(unsigned reads, uint32_t value);

// A write to `addr` stores `value ^ xor_mask`, so it reads back different.
void fake_dma_corrupt_on_write(uint32_t addr, uint32_t xor_mask);

void fake_mem_set(uint32_t addr, uint32_t value);
uint32_t fake_reg(uint32_t addr);

const fake_write_t *fake_writes(size_t *count);
size_t fake_writes_to(uint32_t addr);
// Index of the first logged write to `addr` at or after `from`, or the log length.
size_t fake_write_index(uint32_t addr, size_t from);
unsigned fake_go_count(void);
unsigned fake_bad_width_count(void);

int fake_console_has(const char *text);
int fake_status_has(uint16_t value);

#endif // FAKE_SEP_DMA_H
