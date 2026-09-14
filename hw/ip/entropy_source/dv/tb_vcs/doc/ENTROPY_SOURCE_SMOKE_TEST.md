# Entropy Source - Smoke Test

**Purpose**: Verify basic connectivity and entropy generation
**Time**: < 10 µs (< 1000 clock cycles @ 100 MHz)
**Models**: None (uses real RTL ring oscillators)

---

## Requirements

**Clocks**:

- `clk_i` (APB clock): 100 MHz (10 ns period)
- `rosc_sample_clk_i` (Sample clock): 100-450 MHz (present but not used; test uses internal RO clocks)

**Interface**: APB4 slave interface

**Outputs**:

- `entropy_stream_data_o[31:0]` - Entropy data
- `entropy_stream_vld_o` - Valid pulse (data ready)

---

## Test Procedure

### Step 1: Read Component ID

**Operation**: APB Read from address `0x000`
**Expected**: `0x01000001`
**Purpose**: Verify APB interface functionality

### Step 2: Configure Decorrelator Bypass Mode

**Operation**: APB Write to address `0x0A0` with data `0x0003FFFF`
**Details**:

- `BYPASS[11:0] = 0xFFF` (bypass all 12 decorrelators)
- `SAMPLE_CLK_DIV[31:12] = 63` (divide-by-64 sampling)

### Step 3: Initialize Ring Oscillators

**3.1** APB Write to address `0x090` with data `0x00000000` (disable all ROs)
**3.2** Wait 1000 ns (100 cycles)
**3.3** APB Write to address `0x090` with data `0x00FFFFFF` (enable all 24 ROs)

**Purpose**: Break X-propagation in RO feedback loops (simulation only)
**Note**: Uses default clock configuration (internal sample clock ROs)
See Appendix A for detailed explanation.

### Step 4: Monitor FIFO Status and Read Data

**4.1 Monitor FIFO Status**:

- **Operation**: Periodically read address `0x024` (FIFO_STATUS)
- **Wait**: 1000 ns (100 cycles) between reads
- **Samples**: 5 reads

**Expected Progression**:

```
Sample 0: LEVEL=0,  WPTR=0,  RPTR=0
Sample 1: LEVEL>0,  WPTR>0,  RPTR=0
Sample 2: LEVEL>prev, WPTR>prev, RPTR=0
Sample 3: LEVEL>prev, WPTR>prev, RPTR=0
Sample 4: LEVEL>prev, WPTR>prev, RPTR=0
```

**Pass Criteria**:

- ✓ LEVEL[6:0] increasing (entropy generated)
- ✓ WPTR[12:8] advancing (FIFO written)
- ✓ RPTR[20:16] = 0 (no unexpected reads)

**4.2 Read FIFO Data**:

- **Operation**: Read address `0x028` (FIFO_RDATA) multiple times
- **Count**: Up to 10 words or available FIFO level
- **Purpose**: Verify entropy data is not all zeros

**Pass Criteria**:

- ✓ At least some non-zero values (not all 0x00000000)
- ✓ RPTR advances by number of reads

### Step 5: Monitor Entropy Stream

**Operation**: Observe `entropy_stream_vld_o` and `entropy_stream_data_o`
**Duration**: 10 µs (1000 cycles)

**Pass Criteria**:

- ✓ `entropy_stream_vld_o` pulses HIGH at least once
- ✓ Multiple unique `entropy_stream_data_o` values
- ✓ Data not stuck at `0x00000000` or `0xFFFFFFFF`

---

## Pass Criteria Summary

| Check | Criteria |
|-------|----------|
| APB Interface | Read 0x000 = 0x01000001 |
| FIFO Level | Increases over time |
| Write Pointer | Advances (wraps allowed) |
| Read Pointer (before reads) | Stays at 0 |
| FIFO Data | Non-zero values |
| Read Pointer (after reads) | Advances correctly |
| Valid Signal | Toggles HIGH |
| Entropy Data | Varying values |
| End-to-End | ROs → Decorrelator → Compressor → FIFO → APB |

---

## Quick Reference

**Timing Assumptions** (APB clock = 100 MHz, period = 10 ns):

- Reset: 20 ns (2 cycles)
- RO settle time: 1000 ns (100 cycles)
- FIFO monitoring: 1000 ns between samples
- Stream monitoring: 10 µs total (1000 cycles)

**Critical Addresses**:

- `0x000`: COMPONENT_ID (expect 0x01000001)
- `0x024`: FIFO_STATUS (LEVEL, WPTR, RPTR)
- `0x028`: FIFO_RDATA (read entropy data, auto-pop)
- `0x090`: RING_OSC_ENABLE (24-bit enable mask)
- `0x0A0`: DECORRELATOR_CTRL (bypass + sample divider)

**Note**: RING_OSC_CTRL (0x098) uses default value 0xFFF (internal sample clocks)

**Test File**: `test/test_cl_integration.py::test_cl_integration_minimal`

---

## Appendix A: Ring Oscillator Initialization (Simulation Only)

### Problem: X-Propagation in Feedback Loops

Ring oscillators contain combinational feedback loops:

```
feedback -> NAND -> delay_stages[N] -> MUX -> feedback
```

In simulation, without an initial value, the `feedback` signal starts at X (unknown). Since the loop is purely combinational, X propagates through all stages and never resolves. The RO remains stuck at X forever.

In real silicon, physical noise and charge injection break the loop within nanoseconds. No special initialization is needed.

### Solution: Toggle RING_OSC_ENABLE Register

The RING_OSC_ENABLE register (address 0x090) provides a clean way to initialize ROs:

**Step 1**: Write `0x00000000` to disable all ring oscillators

- This forces the enable signal LOW
- All RO internal logic is gated off
- Feedback loops are broken

**Step 2**: Wait 1000 ns (100 cycles)

- Allow all internal states to settle to known values
- All flops and latches reach stable state
- Any residual X values propagate out

**Step 3**: Write `0x00FFFFFF` to enable all ring oscillators

- Bit [11:0]: Enable 12 noise ring oscillators
- Bit [23:12]: Enable 12 sample clock ring oscillators
- ROs start from clean state and begin oscillating

Properties of this method:

- Uses the documented register interface (no testbench backdoor)
- Works the same way in real silicon
- No hierarchy-dependent paths

### Register Bit Allocation (RING_OSC_ENABLE @ 0x090)

| Bits | Field | Description |
|------|-------|-------------|
| [11:0] | ENABLE | Enable for 12 noise ring oscillators |
| [23:12] | SAMPLE_CLK_ENABLE | Enable for 12 sample clock ring oscillators |

Default value: `0x00FFFFFF` (all enabled after reset)

### Timing Requirements

**Minimum settle time**: 100 APB clock cycles = 1000 ns @ 100 MHz

- Conservative estimate to ensure all internal logic settles
- Can be reduced if APB clock is slower
- Can be increased if issues observed in fast corners

**Why 100 cycles?**

- Decorrelator shift registers are up to 64 stages deep
- +36 cycles margin for safety
- In bypass mode, this is not critical (no decorrelator delay)

---

## Appendix B: Configuration Details

### DECORRELATOR_CTRL Register (0x0A0)

| Field | Bits | Value | Description |
|-------|------|-------|-------------|
| BYPASS | [11:0] | 0xFFF | Bypass all 12 decorrelators (no feedback loop) |
| SAMPLE_CLK_DIV | [31:12] | 63 | Sample clock divider (actual division = value + 1 = 64) |

**Bypass Mode**:

- BYPASS=0xFFF: Break decorrelator feedback loops, shift raw bits
- Faster sampling possible (can reduce SAMPLE_CLK_DIV from 63 to 7)
- Captures all raw entropy bits without decorrelation processing

**Normal Mode** (not used in this smoke test):

- BYPASS=0x000: Enable decorrelator feedback for all 12 generators
- Use default SAMPLE_CLK_DIV=63 (div-64)

### RING_OSC_CTRL Register (0x098)

| Field | Bits | Value | Description |
|-------|------|-------|-------------|
| SAMPLE_CLK_SELECT | [11:0] | 0xFFF (default) | Select clock source for each sampler |

**Per-bit encoding**:

- Bit = 0: Use external clock `rosc_sample_clk_i`
- Bit = 1: Use internal ring oscillator clock

**Default 0xFFF**: All 12 samplers use internal RO clocks (no configuration needed)

- Internal sample clock ROs are initialized by RING_OSC_ENABLE toggle in Step 3
- Simplifies test setup (one less register write)

---

## Appendix C: Simulation vs Real Silicon

| Aspect | Simulation | Real Silicon |
|--------|-----------|--------------|
| RO Feedback | Starts at X, never resolves | Physical noise breaks loop in <1 ns |
| Initialization | Requires RING_OSC_ENABLE toggle | No action needed (auto-start) |
| Setup Time | 1000 ns settle delay | Immediate operation |
| Models | None (real RTL) | Native hardware |

**Key Takeaway**: The RING_OSC_ENABLE toggle workaround is purely for simulation. Real silicon will work immediately after reset without any special initialization sequence.

---

**Test**: `test/test_cl_integration.py::test_cl_integration_minimal`
