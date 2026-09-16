# Register Verification Guide - Entropy Source

**Purpose**: Comprehensive register verification methodology for system integration
**Component**: Entropy Source (entropy_source)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Default Value Verification](#2-default-value-verification)
3. [Read-Write Pattern Testing](#3-read-write-pattern-testing)
4. [Write Mask Validation](#4-write-mask-validation)
5. [Special Register Testing](#5-special-register-testing)
6. [Recommended Test Checklist](#6-recommended-test-checklist)

---

## 1. Overview

### 1.1 Verification Objectives

This guide provides a systematic approach to verify:

- ✓ All registers reset to correct default values
- ✓ All writable bits in RW registers function correctly
- ✓ All read-only bits remain unaffected by writes
- ✓ Special behaviors (W1C, WO, side effects) work as specified
- ✓ No spurious register updates or corruption

### 1.2 Register Categories

| Category | Count | Verification Focus |
|----------|-------|-------------------|
| **Read-Only (R/O)** | 26 | Default values, HW update behavior |
| **Read-Write (R/W)** | 15 | Default values, write masks, pattern tests |
| **Write-Only (W/O)** | 1 | Side effects (cannot verify readback) |
| **Write-1-Clear (W1/C)** | 1 | Set/clear behavior |

### 1.3 Test Prerequisites

Before starting verification:

1. Apply hardware reset (`presetn`)
2. Configure clocks (APB clock, RO sample clock)

---

## 2. Default Value Verification

### 2.1 Objective

Verify all readable registers return correct default values after reset.

### 2.2 Reset Procedure

```
Step 1: Apply and release presetn through the APB testbench reset helper

Step 2: Verify reset completed
   - Read COMPONENT_ID (0x00)
   - Verify = 0x01010001
```

### 2.3 Default Value Table

#### Core Control and Status Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **COMPONENT_ID** | 0x00 | 0x01010001 | Fixed value: NAME=0x0001, VERSION=0.1 |
| **CTRL** | 0x04 | 0x10000002 | Module and SHA-256 conditioning enabled |
| **DEBUG_CTRL** | 0x0C | 0x00000000 | Debug disabled by default |

#### Interrupt Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **INTR_STATUS** | 0x10 | 0x00000000 | No pending interrupts |
| **INTR_ENABLE** | 0x14 | 0x00000000 | All interrupts disabled |
| **INTR_TEST** | 0x18 | N/A | Write-only, skip default check |

#### FIFO Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **FIFO_CTRL** | 0x20 | 0x00000001 | FIFO enabled by default (bit [0] = 1) |
| **FIFO_STATUS** | 0x24 | 0x00000000 | FIFO empty: LEVEL=0, WPTR=0, RPTR=0 |
| **FIFO_RDATA** | 0x28 | 0x00000000 | Empty FIFO returns 0 |

#### Health Test Configuration Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **HEALTH_TEST_CTRL** | 0x30 | 0x00001907 | All tests enabled: ENABLE[2:0]=0x7, REPETITION_LIMIT=25 |
| **HEALTH_TEST_WINDOW_SIZE** | 0x34 | 0x00000800 | APT and Markov window size = 2048 |
| **MARKOV_TEST_PROB_THRESHOLDS** | 0x38 | 0x006404B0 | High count = 1200, low count = 100 |

#### Health Test Status Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **HEALTH_TEST_STATUS** | 0x40 | 0x00000000 | ⚠ Check after disabling tests |
| **REPETITION_TEST_COUNT** | 0x44 | 0x00000000 | ⚠ Check after disabling tests |
| **APT_PATTERN_COUNT_1BIT** | 0x50 | 0x00000000 | ⚠ Check after disabling tests |
| **APT_PATTERN_COUNT_2BIT** | 0x54 | 0x00000000 | ⚠ Check after disabling tests |

#### APT Configuration Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **APT_PROPORTION_1BIT** | 0x60 | 0x000004B0 | High one-count limit = 1200 |
| **APT_PROPORTION_LO** | 0x70 | 0x00000350 | Low one-count limit = 848 |

#### Markov Test Status Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **MARKOV_TEST_COUNTS_0** | 0x80 | 0x00000000 | ⚠ Check after disabling tests |

#### Ring Oscillator Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **RING_OSC_ENABLE** | 0x90 | 0x00FFFFFF | All 12 ROs enabled (bits [23:0]) |
| **RING_OSC_TUNE** | 0x94 | 0x00000000 | No detuning by default |
| **RING_OSC_CTRL** | 0x98 | 0x00000FFF | All ROs use internal sample clocks |

#### Decorrelator Registers

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **DECORRELATOR_CTRL** | 0xA0 | 0x0003F000 | DIV=63 (bits [31:12]), BYPASS=0 (bits [11:0]) |
| **DECORRELATOR_MASK** | 0xA4 | 0x000000FF | All entropy bits enabled |

#### Per-Generator Health Status (12 Registers)

| Register | Address | Default | Verification Notes |
|----------|---------|---------|-------------------|
| **GENERATOR_0_HEALTH_STATUS** | 0xC0 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_1_HEALTH_STATUS** | 0xC4 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_2_HEALTH_STATUS** | 0xC8 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_3_HEALTH_STATUS** | 0xCC | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_4_HEALTH_STATUS** | 0xD0 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_5_HEALTH_STATUS** | 0xD4 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_6_HEALTH_STATUS** | 0xD8 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_7_HEALTH_STATUS** | 0xDC | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_8_HEALTH_STATUS** | 0xE0 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_9_HEALTH_STATUS** | 0xE4 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_10_HEALTH_STATUS** | 0xE8 | 0x00000000 | ⚠ Check after disabling tests |
| **GENERATOR_11_HEALTH_STATUS** | 0xEC | 0x00000000 | ⚠ Check after disabling tests |

### 2.4 Special Case: Health Test Status Registers

**Problem**: Health tests are enabled by default, so status counters may increment during verification.

**Solution**: Disable health tests, then apply reset, then check defaults.

```
Step 1: Disable all health tests
   - Write HEALTH_TEST_CTRL (0x30) = 0x00000000

Step 2: Toggle the disabled tests on and off to clear their counters

Step 3: Verify health status defaults
   - Read REPETITION_TEST_COUNT (0x44)       → Expect 0x00000000
   - Read APT_PATTERN_COUNT_1BIT (0x50)      → Expect 0x00000000
   - Read APT_PATTERN_COUNT_2BIT (0x54)      → Expect 0x00000000
   - Read MARKOV_TEST_COUNTS_0 (0x80)        → Expect 0x00000000
   - Read HEALTH_TEST_STATUS (0x40)          → Expect 0x00000000
   - Read GENERATOR_0..11_HEALTH_STATUS      → Expect 0x00000000 each
```

### 2.5 Default Check Summary

**Total Registers**: 42

- **Check immediately**: 30 registers
- **Skip (W/O)**: 1 register (INTR_TEST)
- **Check after disabling health tests**: 11 registers (status/counters)

---

## 3. Read-Write Pattern Testing

### 3.1 Objective

Verify all writable bits in RW registers can be written and read back correctly.

### 3.2 Test Patterns

Use four standard patterns to exercise all bit combinations:

| Pattern | Value | Bit Pattern | Purpose |
|---------|-------|-------------|---------|
| **Pattern 0** | 0x00000000 | 32'b0000...0000 | All zeros |
| **Pattern 1** | 0xFFFFFFFF | 32'b1111...1111 | All ones |
| **Pattern 2** | 0x5555AAAA | 32'b0101...1010 | Checkerboard A |
| **Pattern 3** | 0xAAAA5555 | 32'b1010...0101 | Checkerboard B |

### 3.3 Test Procedure (Per RW Register)

```
For each test pattern:
   Step 1: Write pattern to register
   Step 2: Read back value
   Step 3: Apply write mask to BOTH pattern and readback
   Step 4: Compare masked values
   Step 5: Report PASS/FAIL

After all patterns tested:
   Step 6: Restore register to default value
   Step 7: Verify default restored
```

### 3.4 RW Registers Under Test

#### CTRL (0x04)

- **Write Mask**: 0x13FF0112
- **Writable Bits**: [28] SHA256_WHITENING_ENABLE, [25:16] DOWNSAMPLE_RATE, [8] BYPASS_COMPRESSOR, [4] AUTOTUNE_ENABLE, [1] MODULE_ENABLE
- **Default**: 0x10000002

**Example Test**:

```
Write: 0xFFFFFFFF
Read:  0x13FF0112  ← Only writable bits set
```

#### DEBUG_CTRL (0x0C)

- **Write Mask**: 0x000007FF
- **Writable Bits**: [10:8] SELECT_FREQ_DIV, [7:0] SELECT_SIGNAL
- **Default**: 0x00000000

#### INTR_ENABLE (0x14)

- **Write Mask**: 0x11111111
- **Writable Bits**: [28] NOISE_OBS_OVERFLOW, [24] BIW_OBS_OVERFLOW, [20] AUTOTUNE_FAIL, [16] PERSISTENT_FAILURE, [12] FIFO_UNDERFLOW, [8] FIFO_OVERFLOW, [4] FIFO_ERROR, [0] HEALTH_TEST_FAILED
- **Default**: 0x00000000

#### FIFO_CTRL (0x20)

- **Write Mask**: 0x00000011
- **Writable Bits**: [4] ENTROPY_CHURN_ENABLE, [0] ENABLE
- **Default**: 0x00000001

#### HEALTH_TEST_CTRL (0x30)

- **Write Mask**: 0x0000FF07
- **Writable Bits**: [15:8] REPETITION_LIMIT, [2:0] ENABLE
- **Default**: 0x00001907

#### HEALTH_TEST_WINDOW_SIZE (0x34)

- **Write Mask**: 0x0000FFFF
- **Writable Bits**: [15:0] SIZE
- **Default**: 0x00000800

#### MARKOV_TEST_PROB_THRESHOLDS (0x38)

- **Write Mask**: 0xFFFFFFFF
- **Writable Bits**: [31:16] PROB_10_THRESHOLD, [15:0] PROB_01_THRESHOLD
- **Default**: 0x006404B0

#### APT_PROPORTION_1BIT (0x60)

- **Write Mask**: 0x0000FFFF
- **Writable Bits**: [15:0] LIMIT
- **Default**: 0x000004B0 (1200)

#### APT_PROPORTION_LO (0x70)

- **Write Mask**: 0x0000FFFF
- **Writable Bits**: [15:0] LIMIT
- **Default**: 0x00000350 (848)

#### RING_OSC_ENABLE (0x90)

- **Write Mask**: 0x00FFFFFF
- **Writable Bits**: [23:12] SAMPLE_CLK_ENABLE, [11:0] ENABLE
- **Default**: 0x00FFFFFF

#### RING_OSC_TUNE (0x94)

- **Write Mask**: 0x00FFFFFF
- **Writable Bits**: [23:12] SAMPLE_CLK_DETUNE, [11:0] DETUNE
- **Default**: 0x00000000

#### RING_OSC_CTRL (0x98)

- **Write Mask**: 0x00000FFF
- **Writable Bits**: [11:0] SAMPLE_CLK_SELECT
- **Default**: 0x00000FFF

#### DECORRELATOR_CTRL (0xA0)

- **Write Mask**: 0xFFFFFFFF
- **Writable Bits**: [31:12] SAMPLE_CLK_DIV, [11:0] BYPASS
- **Default**: 0x0003F000

#### DECORRELATOR_MASK (0xA4)

- **Write Mask**: 0x000000FF
- **Writable Bits**: [7:0] ENTROPY_BYTE_MASK
- **Default**: 0x000000FF

### 3.5 Registers to Skip

**INTR_STATUS (0x10)**: Skip pattern test, use dedicated W1C test (Section 5.1)

**INTR_TEST (0x18)**: Skip pattern test, write-only register (Section 5.2)

### 3.6 Pattern Test Summary

**Total RW Registers**: 15

- **Pattern test**: 13 registers
- **Skip (special)**: 2 registers (INTR_STATUS, INTR_TEST)

---

## 4. Write Mask Validation

### 4.1 Objective

Verify read-only bits within RW registers cannot be modified by writes.

### 4.2 Test Method

```
For each RW register with write mask < 0xFFFFFFFF:
   Step 1: Write 0xFFFFFFFF (attempt to set all bits)
   Step 2: Read back value
   Step 3: Verify readback == write_mask
   Step 4: Write 0x00000000 (attempt to clear all bits)
   Step 5: Read back value
   Step 6: Verify readback == 0x00000000
```

### 4.3 Critical Write Mask Tests

#### CTRL (0x04): Write Mask = 0x13FF0112

```
Test 1: Set all bits
   Write: 0xFFFFFFFF
   Read:  0x13FF0112  ✓

Test 2: Clear all bits
   Write: 0x00000000
   Read:  0x00000000  ✓
```

#### DEBUG_CTRL (0x0C): Write Mask = 0x000007FF

```
Test 1: Set all bits
   Write: 0xFFFFFFFF
   Read:  0x000007FF  ✓ (bits [31:11] unaffected)

Test 2: Clear all bits
   Write: 0x00000000
   Read:  0x00000000  ✓
```

#### INTR_ENABLE (0x14): Write Mask = 0x11111111

```
Test 1: Set all bits
   Write: 0xFFFFFFFF
   Read:  0x11111111  ✓ (every fourth bit from [0] through [28] writable)

Test 2: Clear all bits
   Write: 0x00000000
   Read:  0x00000000  ✓
```

#### APT_PROPORTION Registers (0x60 and 0x70): Write Mask = 0x0000FFFF

```
Test 1: Set all bits
   Write: 0xFFFFFFFF
   Read:  0x0000FFFF  ✓ (only bits [15:0] writable)

Test 2: Clear all bits
   Write: 0x00000000
   Read:  0x00000000  ✓
```

### 4.4 Write Mask Quick Reference

| Register | Write Mask | Unwritable Bits |
|----------|-----------|-----------------|
| CTRL | 0x13FF0112 | [31:29], [27:26], [15:9], [7:5], [3:2], [0] |
| DEBUG_CTRL | 0x000007FF | [31:11] |
| INTR_ENABLE | 0x11111111 | [31:29], [27:25], [23:21], [19:17], [15:13], [11:9], [7:5], [3:1] |
| FIFO_CTRL | 0x00000011 | [31:5], [3:1] |
| HEALTH_TEST_CTRL | 0x0000FF07 | [31:16], [7:3] |
| MARKOV_TEST_PROB_THRESHOLDS | 0xFFFFFFFF | None (all writable) |
| APT_PROPORTION_1BIT / LO | 0x0000FFFF | [31:16] |
| RING_OSC_ENABLE | 0x00FFFFFF | [31:24] |
| RING_OSC_TUNE | 0x00FFFFFF | [31:24] |
| RING_OSC_CTRL | 0x00000FFF | [31:12] |
| DECORRELATOR_CTRL | 0xFFFFFFFF | None (all writable) |
| DECORRELATOR_MASK | 0x000000FF | [31:8] |

---

## 5. Special Register Testing

### 5.1 INTR_STATUS (0x10) - Write-1-to-Clear Test

**Objective**: Verify W1C behavior for interrupt status bits

#### Test Procedure

```
Test Bit [0]: HEALTH_TEST_FAILED

Step 1: Clear all interrupts
   Write INTR_STATUS = 0x11111111
   Read INTR_STATUS → Expect 0x00000000

Step 2: Inject interrupt
   Write INTR_TEST = 0x00000001
   Wait 5 clock cycles

Step 3: Verify interrupt asserted
   Read INTR_STATUS → Expect bit [0] = 1

Step 4: Attempt clear with 0 (should NOT clear)
   Write INTR_STATUS = 0x00000000
   Read INTR_STATUS → Expect bit [0] = 1 (unchanged)

Step 5: Clear with 1 (should clear)
   Write INTR_STATUS = 0x00000001
   Read INTR_STATUS → Expect bit [0] = 0 (cleared)

Repeat for bits [4], [8], [12], [16], [20], [24], and [28]
```

#### Complete W1C Test Matrix

| Bit | Name | Inject (INTR_TEST) | Clear (INTR_STATUS) | Verify |
|-----|------|-------------------|---------------------|--------|
| [0] | HEALTH_TEST_FAILED | 0x00000001 | 0x00000001 | Bit clears |
| [4] | FIFO_ERROR | 0x00000010 | 0x00000010 | Bit clears |
| [8] | FIFO_OVERFLOW | 0x00000100 | 0x00000100 | Bit clears |
| [12] | FIFO_UNDERFLOW | 0x00001000 | 0x00001000 | Bit clears |

#### W1C Behavior Summary

| Write Value | Bit State Before | Bit State After | Result |
|-------------|------------------|-----------------|--------|
| 0 | 0 | 0 | No change |
| 0 | 1 | 1 | **Not cleared** |
| 1 | 0 | 0 | No change |
| 1 | 1 | 0 | **Cleared** |

### 5.2 INTR_TEST (0x18) - Write-Only Test

**Objective**: Verify write-only behavior and side effects

#### Test Procedure

```
Step 1: Write interrupt injection value
   Write INTR_TEST = 0x00000001

Step 2: Attempt to read back (should return 0)
   Read INTR_TEST → Expect 0x00000000 (NOT 0x00000001)

Step 3: Verify side effect occurred
   Read INTR_STATUS → Expect bit [0] = 1

Step 4: Clear interrupt
   Write INTR_STATUS = 0x00000001
```

#### Key Point

❌ **Cannot verify**: What was written to INTR_TEST
✓ **Can verify**: Side effect on INTR_STATUS

### 5.3 FIFO_RDATA (0x28) - Side Effect Test

**Objective**: Verify each read pops one entry from FIFO

#### Test Procedure

```
Prerequisites:
- FIFO has at least 10 entries
- FIFO_STATUS.LEVEL >= 10

Step 1: Record initial FIFO level
   Read FIFO_STATUS (0x24)
   Extract LEVEL = bits [6:0]
   initial_level = LEVEL

Step 2: Read FIFO data (pops entry)
   Read FIFO_RDATA (0x28)
   data_1 = RDATA

Step 3: Verify level decremented
   Read FIFO_STATUS (0x24)
   Extract LEVEL = bits [6:0]
   Verify LEVEL == initial_level - 1

Step 4: Read again
   Read FIFO_RDATA (0x28)
   data_2 = RDATA

Step 5: Verify level decremented again
   Read FIFO_STATUS (0x24)
   Extract LEVEL = bits [6:0]
   Verify LEVEL == initial_level - 2

Step 6: Verify data values are different
   Verify data_1 != data_2 (different FIFO entries)

Repeat for 10 reads total
```

#### Expected Behavior

| Operation | FIFO Level | Notes |
|-----------|-----------|-------|
| Initial state | N | N entries in FIFO |
| Read #1 | N-1 | Entry popped |
| Read #2 | N-2 | Next entry popped |
| ... | ... | ... |
| Read #N | 0 | FIFO empty |
| Read #N+1 | 0 | ⚠ Underflow interrupt |

### 5.4 Health Test Status Register Dynamic Behavior

**Objective**: Verify status registers update as health tests run

#### Test Procedure

```
Step 1: Enable health tests
   Write HEALTH_TEST_CTRL = 0x00001907

Step 2: Wait for entropy generation (1000 cycles)

Step 3: Read status registers (expect non-zero)
   Read REPETITION_TEST_COUNT (0x44) → Expect > 0
   Read APT_PATTERN_COUNT_1BIT (0x50) → Expect > 0
   Read MARKOV_TEST_COUNTS_0 (0x80) → Expect > 0

Step 4: Disable health tests
   Write HEALTH_TEST_CTRL = 0x00000000

Step 5: Toggle the health-test enables to clear their counters

Step 6: Verify counters reset to 0
   Read REPETITION_TEST_COUNT (0x44) → Expect 0x00000000
   Read APT_PATTERN_COUNT_1BIT (0x50) → Expect 0x00000000
   Read MARKOV_TEST_COUNTS_0 (0x80) → Expect 0x00000000
```

---

## 6. Recommended Test Checklist

### 6.1 Phase 1: Basic Register Sanity

- Read COMPONENT_ID, verify fixed value 0x01010001
- Apply hardware reset, verify CTRL returns to 0x10000002
- Verify FIFO_STATUS shows empty FIFO (LEVEL=0)
- Verify FIFO_CTRL default enabled (0x00000001)

### 6.2 Phase 2: Complete Default Value Check

- Verify all 30 immediate-check registers
- Disable health tests, reset, verify 11 status registers
- Document any mismatches with expected defaults

### 6.3 Phase 3: RW Pattern Testing

- Test 13 RW registers with 4 patterns each (52 tests)
- Verify write mask applied correctly in all cases
- Restore defaults after each register tested

### 6.4 Phase 4: Write Mask Validation

- Test CTRL write mask (0x13FF0112)
- Test DEBUG_CTRL write mask (0x000007FF)
- Test INTR_ENABLE write mask (0x11111111)
- Test APT_PROPORTION_1BIT and APT_PROPORTION_LO write masks (0x0000FFFF)
- Test all other RW register write masks

### 6.5 Phase 5: Special Register Tests

- INTR_STATUS W1C: Test all 8 interrupt bits
- INTR_TEST WO: Verify read returns 0, side effects work
- FIFO_RDATA: Verify read-pop side effect (10 reads)
- Health status: Verify dynamic updates when tests enabled

### 6.6 Phase 6: Integration Tests

- Register persistence: Write all RW, wait 1000 cycles, verify unchanged
- Concurrent access: Back-to-back writes/reads, no corruption
- Full interrupt flow: Enable → Inject → Service → Clear
- FIFO boundary: Fill to 64, drain to 0, check underflow

---

## 7. Test Coverage Summary

### 7.1 Coverage Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| **Register Coverage** | 100% | All 42 registers verified |
| **Bit Coverage** | 100% | All writable bits exercised |
| **Pattern Coverage** | 100% | All 4 patterns tested per RW register |
| **Special Behavior Coverage** | 100% | W1C, WO, side effects verified |

### 7.2 Expected Results

After completing all tests:

- **Default checks**: 41 (42 registers minus 1 WO)
- **RW pattern tests**: 52 (13 registers × 4 patterns)
- **Write mask tests**: 15 (all RW registers)
- **Special tests**: 4 (W1C, WO, FIFO, dynamic status)

**Total Tests**: ~112 test cases

---

## 8. Quick Reference: Test Pseudo-Code

### Default Value Test

```
reset_device()
for each readable register:
    value = read_register(address)
    assert(value == expected_default)
```

### RW Pattern Test

```
patterns = [0x00000000, 0xFFFFFFFF, 0x5555AAAA, 0xAAAA5555]
for each RW register:
    for each pattern:
        write_register(address, pattern)
        value = read_register(address)
        assert((value & write_mask) == (pattern & write_mask))
    restore_default(address)
```

### Write Mask Test

```
for each RW register:
    write_register(address, 0xFFFFFFFF)
    value = read_register(address)
    assert(value == write_mask)
```

### W1C Test

```
for each interrupt bit:
    inject_interrupt(bit)
    assert(read_intr_status() & bit != 0)
    write_intr_status(0x00000000)  // Try to clear with 0
    assert(read_intr_status() & bit != 0)  // Should NOT clear
    write_intr_status(bit)  // Clear with 1
    assert(read_intr_status() & bit == 0)  // Should clear
```

---

**End of Document**
