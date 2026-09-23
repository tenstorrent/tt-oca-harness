/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Checks the SMC status ring buffer: published location, geometry, drain, one ROM-reported
 * error entry, and overwrite-oldest on a write to a full buffer. Needs status reporting
 * enabled (+FORCE_STATUS_REPORTING); every entry graded is written by the ROM itself.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include "smc_status.h"
#include "smc_ring_buffer.h"
#include <stddef.h>
#include <string.h>

_Static_assert((int)OCCP_STATUS_MSG_STATUS == SMC_STATUS_TYPE_STATUS,
               "status message type disagrees with smc_status.h");
_Static_assert((int)OCCP_STATUS_MSG_WARNING == SMC_STATUS_TYPE_WARNING,
               "warning message type disagrees with smc_status.h");
_Static_assert((int)OCCP_STATUS_MSG_ERROR == SMC_STATUS_TYPE_ERROR,
               "error message type disagrees with smc_status.h");
_Static_assert((int)OCCP_FW_ID_SMC_BL0 == SMC_STATUS_FW_ID_SMC_BL0,
               "SMC BL0 firmware ID disagrees with smc_status.h");

#define RB_SRAM_OFFSET_BASE SMC_SRAM_BASE_ADDR

#define RB_SCRATCH9_STATUS_BUFFER_READY (1U << 2)

/* End of the SRAM window published to SEP; both ring buffers must sit above it. */
#define RB_SAFE_SRAM_END_ADDR 0xC015B000ULL

/* Denied in both secure and non-secure mode: the ROM owns this SRAM region. */
#define RB_DENIED_READ_ADDR SMC_SRAM_BASE_ADDR

#define RB_SENTINEL_OLDEST 0xA5A50001U
#define RB_SENTINEL_NEXT 0xA5A50002U

#define RB_HEAD_ADDR(base) ((base) + (uint64_t)offsetof(smc_ring_buffer_t, head))
#define RB_TAIL_ADDR(base) ((base) + (uint64_t)offsetof(smc_ring_buffer_t, tail))
#define RB_NUM_ENTRIES_ADDR(base) ((base) + (uint64_t)offsetof(smc_ring_buffer_t, num_entries))
#define RB_ENTRY_ADDR(base, idx) \
    ((base) + (uint64_t)offsetof(smc_ring_buffer_t, entries) + ((uint64_t)(idx) * sizeof(uint32_t)))

typedef struct {
    test_context_t *occp;
    uint64_t rb_addr;
    int checks_total;
    int checks_passed;
    bool overall_result;
} rb_test_context_t;

static void init_rb_test_context(rb_test_context_t *t, test_context_t *occp_ctx) {
    memset(t, 0, sizeof(*t));
    t->occp = occp_ctx;
    t->overall_result = true;
}

static void record_check(rb_test_context_t *t, bool passed, const char *name) {
    t->checks_total++;
    if (passed) {
        t->checks_passed++;
        simputs("PASS: ");
    } else {
        t->overall_result = false;
        simputs("FAIL: ");
    }
    simputs(name);
    simputs("\n");
}

static bool expect_eq32(const char *what, uint32_t actual, uint32_t expected) {
    if (actual != expected) {
        simputs("  MISMATCH: ");
        simputs(what);
        simputs("\n");
        simputshex32("    expected: 0x", expected);
        simputshex32("    actual:   0x", actual);
        return false;
    }
    simputs("  ok: ");
    simputs(what);
    simputshex32(" = 0x", actual);
    return true;
}

static bool rb_read_word(rb_test_context_t *t, uint64_t addr, uint32_t *out) {
    uint8_t buf[sizeof(uint32_t)];

    memset(buf, 0, sizeof(buf));
    int result = occp_send_read_command(t->occp, t->occp->slave_addr, addr, buf, sizeof(buf));
    increment_cmd_count(t->occp);
    if (result != OCCP_SUCCESS) {
        simputshex64("  ERROR: OCCP READ failed at address 0x", addr);
        return false;
    }
    memcpy(out, buf, sizeof(*out));
    return true;
}

static bool rb_write_word(rb_test_context_t *t, uint64_t addr, uint32_t value) {
    uint8_t buf[sizeof(uint32_t)];

    memcpy(buf, &value, sizeof(value));
    int result = occp_send_write_command(t->occp, t->occp->slave_addr, addr, buf, sizeof(buf));
    increment_cmd_count(t->occp);
    if (result != OCCP_SUCCESS) {
        simputshex64("  ERROR: OCCP WRITE failed at address 0x", addr);
        return false;
    }
    return true;
}

static uint32_t rb_occupancy(uint32_t head, uint32_t tail) {
    return (head + SMC_RING_BUFFER_SIZE - tail) % SMC_RING_BUFFER_SIZE;
}

static bool rb_pop_entry(rb_test_context_t *t, uint32_t *entry) {
    int result = occp_send_get_smc_status_command(t->occp, t->occp->slave_addr, entry);
    increment_cmd_count(t->occp);
    if (result != OCCP_SUCCESS) {
        simputs("  ERROR: GET_SMC_STATUS command failed\n");
        return false;
    }
    return true;
}

static bool rb_trigger_one_rom_entry(rb_test_context_t *t) {
    uint8_t discard[sizeof(uint32_t)];

    memset(discard, 0xAA, sizeof(discard));
    /* With exp_response_code set, OCCP_SUCCESS means the ROM returned exactly that error. */
    t->occp->exp_response_code = OCCP_INVALID_ADDRESS;
    int result = occp_send_read_command(t->occp, t->occp->slave_addr, RB_DENIED_READ_ADDR, discard,
                                        sizeof(discard));
    increment_cmd_count(t->occp);
    t->occp->exp_response_code = OCCP_ERROR_NONE;
    if (result != OCCP_SUCCESS) {
        simputs("  ERROR: denied READ did not return the expected OCCP_INVALID_ADDRESS error\n");
        return false;
    }

    uint32_t version = 0;
    /* A valid command clears the ROM's consecutive-error count; five errors unlatch it. */
    result = occp_send_get_version_command(t->occp, t->occp->slave_addr, &version);
    increment_cmd_count(t->occp);
    if (result != OCCP_SUCCESS) {
        simputs("  ERROR: GET_VERSION re-latch after the denied READ failed\n");
        return false;
    }
    return true;
}

static bool rb_entry_is_read_access_denied(uint32_t entry) {
    simputshex32("  entry message type: 0x", OCCP_STATUS_EXTRACT_MSG_TYPE(entry));
    simputshex32("  entry firmware ID:  0x", OCCP_STATUS_EXTRACT_FW_ID(entry));
    simputshex32("  entry value:        0x", OCCP_STATUS_EXTRACT_VALUE(entry));
    return occp_status_matches_expected(entry, OCCP_FW_ID_SMC_BL0, OCCP_STATUS_MSG_ERROR,
                                        (uint16_t)OCCP_SPEC_ERROR_READ_ACCESS_DENIED, false);
}

static bool check_buffer_published(rb_test_context_t *t) {
    simputs("\n=== C1: ROM publishes the SMC ring-buffer location ===\n");
    bool ok = true;
    uint32_t scratch9 = 0;
    uint32_t offset = 0;

    if (!rb_read_word(t, SMC_CPU_CTRL_SCRATCH_9__REG_ADDR, &scratch9) ||
        !rb_read_word(t, SMC_CPU_CTRL_SCRATCH_11__REG_ADDR, &offset)) {
        record_check(t, false, "C1 ring-buffer location published");
        return false;
    }

    simputshex32("  scratch 9:  0x", scratch9);
    simputshex32("  scratch 11: 0x", offset);

    if ((scratch9 & RB_SCRATCH9_STATUS_BUFFER_READY) == 0) {
        simputs("  MISMATCH: scratch 9 bit 2 (status buffer ready) is not set\n");
        ok = false;
    }

    uint64_t sep_buffer_addr = RB_SRAM_OFFSET_BASE + (uint64_t)offset;
    uint64_t smc_buffer_addr = sep_buffer_addr - sizeof(smc_ring_buffer_t);

    simputshex64("  SEP buffer address: 0x", sep_buffer_addr);
    simputshex64("  SMC buffer address: 0x", smc_buffer_addr);

    if ((offset % sizeof(uint32_t)) != 0) {
        simputs("  MISMATCH: published offset is not 32-bit aligned\n");
        ok = false;
    }
    if (smc_buffer_addr < RB_SAFE_SRAM_END_ADDR) {
        simputs("  MISMATCH: SMC buffer overlaps the SEP-safe SRAM window\n");
        ok = false;
    }
    if (sep_buffer_addr + sizeof(smc_ring_buffer_t) > OCCP_TEST_UPPER_ADDR) {
        simputs("  MISMATCH: SEP buffer extends past the end of SRAM\n");
        ok = false;
    }

    if (ok) {
        t->rb_addr = smc_buffer_addr;
    }
    record_check(t, ok, "C1 ring-buffer location published");
    return ok;
}

static bool check_buffer_geometry(rb_test_context_t *t) {
    simputs("\n=== C2: SMC ring-buffer geometry ===\n");
    bool ok = true;
    uint32_t num_entries = 0;
    uint32_t head = 0;
    uint32_t tail = 0;

    if (!rb_read_word(t, RB_NUM_ENTRIES_ADDR(t->rb_addr), &num_entries) ||
        !rb_read_word(t, RB_HEAD_ADDR(t->rb_addr), &head) ||
        !rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail)) {
        record_check(t, false, "C2 buffer geometry");
        return false;
    }

    ok &= expect_eq32("num_entries", num_entries, SMC_RING_BUFFER_SIZE);
    if (head >= SMC_RING_BUFFER_SIZE) {
        simputshex32("  MISMATCH: head outside [0, size): 0x", head);
        ok = false;
    }
    if (tail >= SMC_RING_BUFFER_SIZE) {
        simputshex32("  MISMATCH: tail outside [0, size): 0x", tail);
        ok = false;
    }

    record_check(t, ok, "C2 buffer geometry");
    return ok;
}

static bool check_drain_semantics(rb_test_context_t *t) {
    simputs("\n=== C3: read advances the tail, drained buffer reports empty ===\n");
    bool ok = true;
    uint32_t head_before = 0;
    uint32_t tail_before = 0;

    if (!rb_read_word(t, RB_HEAD_ADDR(t->rb_addr), &head_before) ||
        !rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail_before)) {
        record_check(t, false, "C3 read semantics and drain to empty");
        return false;
    }

    uint32_t popped = 0;
    uint32_t entry = 0;
    bool drained = false;

    for (uint32_t i = 0; i < SMC_RING_BUFFER_SIZE; i++) {
        if (!rb_pop_entry(t, &entry)) {
            record_check(t, false, "C3 read semantics and drain to empty");
            return false;
        }
        if (entry == 0) {
            drained = true;
            break;
        }
        simputshex32("  drained entry: 0x", entry);
        popped++;
    }

    if (!drained) {
        simputs("  MISMATCH: buffer never reported empty within SMC_RING_BUFFER_SIZE reads\n");
        ok = false;
    }
    if (popped == 0) {
        simputs("  MISMATCH: no boot status entries present; ROM reported nothing\n");
        ok = false;
    }
    simputshex32("  entries drained: ", popped);

    uint32_t head_after = 0;
    uint32_t tail_after = 0;
    if (!rb_read_word(t, RB_HEAD_ADDR(t->rb_addr), &head_after) ||
        !rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail_after)) {
        record_check(t, false, "C3 read semantics and drain to empty");
        return false;
    }

    ok &=
        expect_eq32("tail after drain", tail_after, (tail_before + popped) % SMC_RING_BUFFER_SIZE);
    ok &= expect_eq32("head unchanged by reads", head_after, head_before);
    ok &= expect_eq32("empty buffer has head == tail", tail_after, head_after);
    ok &= expect_eq32("occupancy after drain", rb_occupancy(head_after, tail_after), 0);

    record_check(t, ok, "C3 read semantics and drain to empty");
    return ok;
}

static bool check_single_report(rb_test_context_t *t) {
    simputs("\n=== C4: one denied READ produces exactly one ERROR entry ===\n");
    bool ok = true;
    uint32_t head_before = 0;
    uint32_t tail_before = 0;

    if (!rb_read_word(t, RB_HEAD_ADDR(t->rb_addr), &head_before) ||
        !rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail_before)) {
        record_check(t, false, "C4 single ROM error entry");
        return false;
    }

    if (!rb_trigger_one_rom_entry(t)) {
        record_check(t, false, "C4 single ROM error entry");
        return false;
    }

    uint32_t head_after = 0;
    uint32_t tail_after = 0;
    uint32_t entry = 0;
    if (!rb_read_word(t, RB_HEAD_ADDR(t->rb_addr), &head_after) ||
        !rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail_after) ||
        !rb_read_word(t, RB_ENTRY_ADDR(t->rb_addr, head_before), &entry)) {
        record_check(t, false, "C4 single ROM error entry");
        return false;
    }

    ok &= expect_eq32("head advanced by one", head_after, (head_before + 1) % SMC_RING_BUFFER_SIZE);
    ok &= expect_eq32("tail untouched (buffer not full)", tail_after, tail_before);
    ok &= expect_eq32("occupancy after one report", rb_occupancy(head_after, tail_after), 1);

    simputshex32("  entry written at the old head: 0x", entry);
    if (!rb_entry_is_read_access_denied(entry)) {
        simputs("  MISMATCH: entry is not ERROR / SMC BL0 / READ_ACCESS_DENIED\n");
        ok = false;
    }

    uint32_t drained = 0;
    if (!rb_pop_entry(t, &drained)) {
        record_check(t, false, "C4 single ROM error entry");
        return false;
    }
    ok &= expect_eq32("popped entry equals the entry in memory", drained, entry);

    record_check(t, ok, "C4 single ROM error entry");
    return ok;
}

static bool check_overflow_behaviour(rb_test_context_t *t) {
    simputs("\n=== C5: a write to a full buffer advances the tail and overwrites the oldest ===\n");
    bool ok = true;
    const uint32_t seed_tail = 0;
    const uint32_t seed_head = SMC_RING_BUFFER_SIZE - 1; /* (head + 1) % size == tail => full */

    /* Seed the full state over OCCP: 511 ROM-reported errors would exceed the sim budget. */
    if (!rb_write_word(t, RB_ENTRY_ADDR(t->rb_addr, 0), RB_SENTINEL_OLDEST) ||
        !rb_write_word(t, RB_ENTRY_ADDR(t->rb_addr, 1), RB_SENTINEL_NEXT) ||
        !rb_write_word(t, RB_ENTRY_ADDR(t->rb_addr, seed_head), 0) ||
        !rb_write_word(t, RB_TAIL_ADDR(t->rb_addr), seed_tail) ||
        !rb_write_word(t, RB_HEAD_ADDR(t->rb_addr), seed_head)) {
        record_check(t, false, "C5 overflow overwrites the oldest entry");
        return false;
    }

    uint32_t head_before = 0;
    uint32_t tail_before = 0;
    uint32_t slot_oldest = 0;
    uint32_t slot_next = 0;
    uint32_t slot_head = 0;
    if (!rb_read_word(t, RB_HEAD_ADDR(t->rb_addr), &head_before) ||
        !rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail_before) ||
        !rb_read_word(t, RB_ENTRY_ADDR(t->rb_addr, 0), &slot_oldest) ||
        !rb_read_word(t, RB_ENTRY_ADDR(t->rb_addr, 1), &slot_next) ||
        !rb_read_word(t, RB_ENTRY_ADDR(t->rb_addr, seed_head), &slot_head)) {
        record_check(t, false, "C5 overflow overwrites the oldest entry");
        return false;
    }

    ok &= expect_eq32("seeded head", head_before, seed_head);
    ok &= expect_eq32("seeded tail", tail_before, seed_tail);
    ok &= expect_eq32("seeded oldest slot", slot_oldest, RB_SENTINEL_OLDEST);
    ok &= expect_eq32("seeded next slot", slot_next, RB_SENTINEL_NEXT);
    ok &= expect_eq32("seeded head slot cleared", slot_head, 0);
    ok &= expect_eq32("buffer is full before the overflowing write",
                      rb_occupancy(head_before, tail_before), SMC_RING_BUFFER_SIZE - 1);
    if (!ok) {
        simputs("  Seeding did not take effect; the overflow result would not be meaningful\n");
        record_check(t, false, "C5 overflow overwrites the oldest entry");
        return false;
    }

    if (!rb_trigger_one_rom_entry(t)) {
        record_check(t, false, "C5 overflow overwrites the oldest entry");
        return false;
    }

    uint32_t head_after = 0;
    uint32_t tail_after = 0;
    uint32_t written = 0;
    if (!rb_read_word(t, RB_HEAD_ADDR(t->rb_addr), &head_after) ||
        !rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail_after) ||
        !rb_read_word(t, RB_ENTRY_ADDR(t->rb_addr, seed_head), &written)) {
        record_check(t, false, "C5 overflow overwrites the oldest entry");
        return false;
    }

    ok &= expect_eq32("head advanced by one", head_after, (head_before + 1) % SMC_RING_BUFFER_SIZE);
    ok &= expect_eq32("tail advanced by one (write to a full buffer)", tail_after,
                      (tail_before + 1) % SMC_RING_BUFFER_SIZE);
    ok &= expect_eq32("occupancy stays at capacity", rb_occupancy(head_after, tail_after),
                      SMC_RING_BUFFER_SIZE - 1);

    simputshex32("  entry written into the slot the head pointed at: 0x", written);
    if (!rb_entry_is_read_access_denied(written)) {
        simputs("  MISMATCH: overflowing entry is not ERROR / SMC BL0 / READ_ACCESS_DENIED\n");
        ok = false;
    }

    uint32_t popped = 0;
    if (!rb_pop_entry(t, &popped)) {
        record_check(t, false, "C5 overflow overwrites the oldest entry");
        return false;
    }
    ok &= expect_eq32("oldest entry dropped; read returns the next one", popped, RB_SENTINEL_NEXT);
    if (popped == RB_SENTINEL_OLDEST) {
        simputs("  MISMATCH: the entry the tail moved past is still readable\n");
        ok = false;
    }

    uint32_t tail_final = 0;
    if (!rb_read_word(t, RB_TAIL_ADDR(t->rb_addr), &tail_final)) {
        record_check(t, false, "C5 overflow overwrites the oldest entry");
        return false;
    }
    ok &= expect_eq32("read advanced the tail by one", tail_final,
                      (tail_after + 1) % SMC_RING_BUFFER_SIZE);

    record_check(t, ok, "C5 overflow overwrites the oldest entry");
    return ok;
}

static void restore_buffer_empty(rb_test_context_t *t) {
    if (t->rb_addr == 0) {
        return;
    }
    if (!rb_write_word(t, RB_TAIL_ADDR(t->rb_addr), 0) ||
        !rb_write_word(t, RB_HEAD_ADDR(t->rb_addr), 0)) {
        simputs("WARNING: could not restore the ring buffer to the empty state\n");
    }
}

static void run_overflow_test_suite(rb_test_context_t *t) {
    simputs("=== SMC Status Ring Buffer Overflow Test ===\n");

    if (t->occp->status_reporting_disabled) {
        simputs("FAIL: STATUS_RPT_DISABLE strap is active. This testcase needs SMC status\n");
        simputs("      reporting; the run must set +FORCE_STATUS_REPORTING.\n");
        t->overall_result = false;
        return;
    }

    if (!check_buffer_published(t)) {
        simputs("Cannot locate the SMC ring buffer; the remaining checks cannot be run\n");
        return;
    }
    if (!check_buffer_geometry(t)) {
        simputs("Buffer geometry does not match the specification; stopping\n");
        return;
    }
    if (!check_drain_semantics(t)) {
        simputs("Buffer could not be drained to a known empty state; stopping\n");
        return;
    }
    check_single_report(t);
    check_overflow_behaviour(t);
    restore_buffer_empty(t);
}

static void finalize_test_results(rb_test_context_t *t) {
    uint32_t result_code =
        t->overall_result ? SMC_SCRATCHPAD_SIM_PASS_CODE : SMC_SCRATCHPAD_SIM_FAIL_CODE;

    simputs("\n=== Results ===\n");
    simputshex32("Checks passed: ", (uint32_t)t->checks_passed);
    simputshex32("Checks failed: ", (uint32_t)(t->checks_total - t->checks_passed));
    if (t->overall_result) {
        simputs("ALL RING BUFFER OVERFLOW CHECKS PASSED\n");
    } else {
        simputs("RING BUFFER OVERFLOW CHECKS FAILED\n");
    }

    int result =
        occp_send_write_command(t->occp, t->occp->slave_addr, SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
                                (uint8_t *)&result_code, sizeof(result_code));
    increment_cmd_count(t->occp);
    if (result != OCCP_SUCCESS) {
        simputs("FAIL: could not publish the result code to the DUT scratch register\n");
        t->overall_result = false;
    }
}

int main(void) {
    static test_context_t occp_ctx = {0};
    static rb_test_context_t test_ctx = {0};

    init_test(0);

    if (!initialize_interface(&occp_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    occp_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    occp_ctx.test_upper_addr_bound = OCCP_TEST_UPPER_ADDR;
    occp_ctx.overall_result = true;
    occp_ctx.cmd_count = 0;
    occp_ctx.exp_occp_last_error = 0;

    init_rb_test_context(&test_ctx, &occp_ctx);

    run_overflow_test_suite(&test_ctx);

    if (!occp_ctx.overall_result) {
        simputs("FAIL: a shared OCCP helper reported a failure\n");
        test_ctx.overall_result = false;
    }

    finalize_test_results(&test_ctx);

    if (test_ctx.overall_result) {
        test_pass(0);
    } else {
        test_fail(0);
    }
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
