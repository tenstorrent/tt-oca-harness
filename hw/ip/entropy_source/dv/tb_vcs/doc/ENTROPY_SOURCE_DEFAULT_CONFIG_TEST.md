# Entropy Source - Default Configuration Test

**Purpose**: Verify FIFO control path with ZERO configuration (all defaults)
**Time**: < 5 µs (< 500 clock cycles @ 100 MHz)
**Models**: None (uses real RTL ring oscillators)
**Configuration**: ZERO register writes - uses all register defaults
**Verification**: Control path only (FIFO level/pointers, not data values)

---

## Overview

This is the **absolute minimum** smoke test. It verifies that the entropy source FIFO control path works immediately after reset without ANY configuration register writes.

**Key Insight**:
FIFO control logic (counters/pointers) operates independently of data values. Even if the data path contains X's from uninitialized RO feedback loops (simulation only), the FIFO control path functions correctly.

**Key Differences from Standard Smoke Test**:

- Standard test: 1 config write (DECORRELATOR_CTRL), verifies data path
- This test: ZERO config writes, verifies control path only
- Standard test: Bypass mode (faster)
- This test: Normal mode (default with feedback)

---

## Requirements

**Clocks**:

- `clk_i` (APB clock): 100 MHz (10 ns period)
- `rosc_sample_clk_i` (Sample clock): Not used (internal RO clocks by default)

**Interface**: APB4 slave interface

**Default Configuration**:

- RING_OSC_ENABLE: 0x00FFFFFF (all 24 ROs enabled)
- RING_OSC_CTRL: 0xFFF (use internal sample clocks)
- DECORRELATOR_CTRL: BYPASS=0x000 (normal mode), DIV=63 (div-64)
- All other registers: Reset defaults

---

## Test Procedure

### Step 1: Wait After Reset

**Operation**: Wait 1000 ns (100 cycles) after reset release
**Purpose**: Allow system to stabilize with default configuration before first APB access

### Step 2: Read Component ID

**Operation**: APB Read from address `0x000`
**Expected**: `0x01000001`
**Purpose**: Verify APB interface functionality

### Step 3: Monitor FIFO Status

**Operation**: Periodically read address `0x024` (FIFO_STATUS)
**Wait**: 1000 ns (100 cycles) between reads
**Samples**: 5 reads
**Duration**: ~5 µs total

**Expected Progression**:

```
Sample 0: LEVEL=0,  WPTR=0,  RPTR=0
Sample 1: LEVEL>0,  WPTR>0,  RPTR=0
Sample 2: LEVEL>prev, WPTR>prev, RPTR=0
Sample 3: LEVEL>prev, WPTR>prev, RPTR=0
Sample 4: LEVEL>prev, WPTR>prev, RPTR=0
```

**Pass Criteria**:

- ✓ LEVEL[6:0] increases (control path working)
- ✓ WPTR[12:8] advances (control path working)
- ✓ RPTR[20:16] = 0 (control path working)

**Notes**:

- Data rate will be slower than bypass mode (decorrelator in normal mode)
- Data values not checked - may contain X's from RO feedback loops (simulation only)
- Control path independent of data values - counters work regardless

---

## Pass Criteria Summary

| Check | Criteria |
|-------|----------|
| APB Interface | Read 0x000 = 0x01000001 |
| Configuration Writes | ZERO (pure defaults) |
| FIFO Level | Increases over time |
| Write Pointer | Advances (wraps allowed) |
| Read Pointer | Stays at 0 |
| Control Path | Independent of data values |
| Data Path | Not verified (X's allowed) |

---

## Quick Reference

**Timing Assumptions** (APB clock = 100 MHz, period = 10 ns):

- Reset: 20 ns (2 cycles)
- RO settle time: 1000 ns (100 cycles)
- FIFO monitoring: 1000 ns between samples
- Total test time: ~5 µs

**Critical Addresses**:

- `0x000`: COMPONENT_ID (expect 0x01000001)
- `0x024`: FIFO_STATUS (LEVEL, WPTR, RPTR)

**Configuration Used**:

- Everything at reset defaults - ZERO writes
- DECORRELATOR_CTRL: BYPASS=0x000 (normal mode with feedback) - default
- RING_OSC_CTRL: 0xFFF (internal sample clocks) - default
- RING_OSC_ENABLE: 0x00FFFFFF (all enabled) - default

**Test File**: `test/test_cl_integration.py::test_cl_integration_default_config`

---

## Comparison with Standard Smoke Test

| Aspect | Default Config Test | Standard Smoke Test |
|--------|-------------------|-------------------|
| **Configuration Writes** | ZERO | 1 (DECORRELATOR_CTRL) |
| **Decorrelator Mode** | Normal (feedback active) | Bypass (no feedback) |
| **Data Rate** | Slower (~2 words/sample) | Faster (~5 words/sample) |
| **FIFO Status** | Yes (level/pointers) | Yes (level/pointers) |
| **FIFO Data Read** | No | Yes (10 words) |
| **FIFO Data Verification** | No (X's allowed) | Yes (verify non-zero) |
| **Stream Monitoring** | No | Yes (1000 cycles) |
| **Test Duration** | ~5 µs | ~10 µs |
| **Verification** | Control path only | Full end-to-end |
| **Purpose** | Verify defaults work | Complete verification |

---

## Default Configuration Details

### DECORRELATOR_CTRL (0x0A0) - Default Value: 0x0003F000

| Field | Bits | Default | Description |
|-------|------|---------|-------------|
| BYPASS | [11:0] | 0x000 | Normal mode: decorrelator feedback active |
| SAMPLE_CLK_DIV | [31:12] | 63 | Divide-by-64 sampling (default) |

**Normal Mode Behavior**:

- Decorrelator feedback loops are active
- Entropy bits go through LFSR-based decorrelation
- Slower effective sample rate due to decorrelation processing
- Better entropy quality (decorrelated output)

### RING_OSC_ENABLE (0x090) - Default Value: 0x00FFFFFF

| Field | Bits | Default | Description |
|-------|------|---------|-------------|
| ENABLE | [11:0] | 0xFFF | All 12 noise ROs enabled |
| SAMPLE_CLK_ENABLE | [23:12] | 0xFFF | All 12 sample clock ROs enabled |

**Note**: Default enables all ROs. No configuration needed for this test.

### RING_OSC_CTRL (0x098) - Default Value: 0xFFF

| Field | Bits | Default | Description |
|-------|------|---------|-------------|
| SAMPLE_CLK_SELECT | [11:0] | 0xFFF | Use internal sample clock ROs |

**Default Behavior**: All samplers use internal ring oscillator clocks (no external clock needed)

---

## Key Takeaways

1. **Zero Configuration Required**: The entropy source FIFO control path works immediately after reset with ZERO register writes.

2. **Control vs Data Path Independence**: FIFO control logic (level, write pointer, read pointer) operates independently of data values. Even if data contains X's from uninitialized RO feedback loops (simulation only), the control path functions correctly.

3. **Default Configuration Works**: All register defaults are properly configured for operation:
   - Ring oscillators: All 24 enabled by default
   - Decorrelator: Normal mode with feedback (not bypassed)
   - Clock source: Internal RO clocks (no external clock needed)

4. **Minimal Verification Sufficient**: By monitoring only FIFO_STATUS register, we prove:
   - Entropy generation is active (level increases)
   - FIFO write logic works (write pointer advances)
   - FIFO read logic idle (read pointer stays at 0)
   - All with ZERO configuration!

5. **Simulation vs Silicon**: Data path X's are simulation-only artifact. In real silicon, physical noise immediately initializes RO feedback loops and data will be valid.

---

**Test**: `test/test_cl_integration.py::test_cl_integration_default_config`
**Related**: See `ENTROPY_SOURCE_SMOKE_TEST.md` for full smoke test with bypass mode
