# Decorrelator Disable Bug Fix

## Problem Summary

The entropy decorrelator module contained a critical control logic bug where the `entropy_byte_valid_o` output signal would remain stuck HIGH after the module was disabled, leading to continuous FIFO overflow errors in downstream logic.

### Root Cause

The bug was in the downsampler sequential logic block (`rtl/entropy_decorrelator.sv`, lines 59-73). The `entropy_byte_valid_o` signal was only updated when `enable_i` was HIGH:

```systemverilog
always @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
        entropy_byte_valid_o <= 1'b0;
        clk_divider          <= sample_clk_div_i;
    end else if (enable_i) begin
        // Valid signal gets set/cleared here
        if (clk_divider == CLKDIV_WIDTH'(0)) begin
            entropy_byte_valid_o <= 1'b1;  // Set HIGH
        end else begin
            entropy_byte_valid_o <= 1'b0;  // Cleared when counting
        end
    end
    // BUG: No else clause to handle enable_i = 0
    // If valid was HIGH when disabled, it stays HIGH forever!
end
```

**The Problem Chain:**
1. Module disabled while `entropy_byte_valid_o = HIGH`
2. No `else` clause → valid signal retains its value
3. `entropy_byte_valid_o` stays stuck HIGH
4. Downstream `entropy_stream_valid_o = |entropy_byte_valid` stays HIGH
5. FIFO push logic continuously attempts to push
6. With FIFO full: `overflow = push_i & fifo_full` → **continuous overflow errors**

### Example Failure Scenario

```
Cycle N:   enable_i = 1, entropy_byte_valid_o = 1 (valid pulse)
Cycle N+1: enable_i = 0 (disabled)
Cycle N+2: enable_i = 0, entropy_byte_valid_o = 1 (STUCK!)
Cycle N+3: enable_i = 0, entropy_byte_valid_o = 1 (STUCK!)
...
Forever:   entropy_byte_valid_o = 1 (STUCK!)

Result: Continuous FIFO overflow errors
```

## Solution: Add Disable Path

### Implementation

Added an explicit `else` clause to clear the valid signal when the module is disabled:

```systemverilog
always @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
        entropy_byte_valid_o <= 1'b0;
        clk_divider          <= sample_clk_div_i;
    end else if (enable_i) begin
        if (clk_divider == CLKDIV_WIDTH'(0)) begin
            clk_divider           <= sample_clk_div_i;
            entropy_byte_sample_o <= ff_stage[LENGTH-1:LENGTH-8] & byte_mask_i;
            entropy_byte_valid_o  <= 1'b1;
        end else begin
            clk_divider          <= clk_divider - CLKDIV_WIDTH'(1);
            entropy_byte_valid_o <= 1'b0;
        end
    end else begin
        // When disabled, clear the valid signal to prevent it from staying stuck HIGH
        entropy_byte_valid_o <= 1'b0;
    end
end
```

### Benefits

1. **Proper disable behavior** - Valid signal clears immediately when disabled
2. **Prevents stuck-HIGH condition** - No signal retention across disable/enable cycles
3. **Eliminates spurious FIFO overflows** - Downstream logic sees correct valid state
4. **Clean state transitions** - Module state properly resets on disable

## Verification

Created comprehensive test (`tb/tb_decorrelator_disable.v`) that verifies all disable scenarios:

### Test Results

```
✓✓✓ ALL TESTS PASSED ✓✓✓

Bug Fix Verified:
  - entropy_byte_valid_o clears when enable_i goes LOW
  - Valid signal doesn't get stuck HIGH
  - Normal operation resumes correctly after re-enable
  - Rapid enable/disable transitions handled correctly
```

### Test Scenarios

**TEST 1: Normal Operation**
- Verify decorrelator generates valid pulses correctly when enabled
- Confirms baseline functionality

**TEST 2: Disable While Valid is HIGH**
- Wait for `entropy_byte_valid_o` to go HIGH
- Disable immediately while valid is HIGH
- Verify valid clears on next clock cycle
- **This is the key test that would fail with the bug**

**TEST 3: Valid Stays LOW While Disabled**
- Monitor for 50 cycles while disabled
- Verify valid never goes HIGH during disable period
- Confirms no spurious valid pulses

**TEST 4: Re-enable and Verify Normal Operation**
- Re-enable the decorrelator
- Verify valid pulses resume normally
- Confirms clean recovery from disable

**TEST 5: Rapid Enable/Disable Stress Test**
- Toggle enable rapidly for 20 cycles with varying periods
- Verify valid never stays HIGH while disabled
- Tests race conditions and edge cases

**TEST 6: Disable-Enable Boundary Timing**
- Test 1-cycle disable period
- Verify immediate re-enable works correctly
- Tests minimum disable duration

## Impact

### Before Fix
- ❌ Valid signal stuck HIGH after disable
- ❌ Continuous FIFO overflow errors
- ❌ System malfunction due to stuck state
- ❌ No way to recover without hard reset

### After Fix
- ✅ Valid signal properly clears on disable
- ✅ No spurious FIFO operations
- ✅ Clean enable/disable state transitions
- ✅ Normal operation resumes after re-enable
- ✅ Robust against rapid enable/disable toggling

## Usage

The fix is transparent to users - no API or interface changes. The decorrelator now properly handles the `enable_i` control signal:

```systemverilog
entropy_decorrelator #(
    .LENGTH(29),
    .CLKDIV_WIDTH(24)
) dcor (
    .clk_i,
    .rst_ni,
    .enable_i,  // Now properly controls entropy_byte_valid_o
    .noise_i,
    .bypass_i,
    .byte_mask_i,
    .sample_clk_div_i,
    .entropy_byte_sample_o,
    .entropy_byte_valid_o  // Clears when enable_i = 0
);
```

### Expected Behavior

```
enable_i = 1 → entropy_byte_valid_o pulses normally (1 cycle every N cycles)
enable_i = 0 → entropy_byte_valid_o = 0 (forced LOW)
```

## Files Modified

- **`rtl/entropy_decorrelator.sv`** - Added else clause to clear valid on disable
- **`tb/tb_decorrelator_disable.v`** - New comprehensive test (6 test scenarios)
- **`tb/Makefile`** - Added test targets (decorr-disable, decorr-disable-waves, decorr-disable-clean)
- **`doc/decorrelator_disable_fix.md`** - This document

## Testing

Run the disable test:
```bash
cd tb/
make decorr-disable          # Run test
make decorr-disable-waves    # View waveforms
make decorr-disable-clean    # Clean files
```

---

**Fix Date**: December 18, 2025
**Verified**: All 6 tests passing
**Status**: Ready for integration
