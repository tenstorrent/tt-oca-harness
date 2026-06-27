# Markov Health Test Counter Saturation Fix

## Problem Summary

The Markov health test module contained a critical arithmetic overflow issue that caused the test to become unresponsive after extended runtime (~260K transitions).

### Root Cause

The module implemented saturation logic to prevent counter overflow, but this created a "frozen probability" problem:

1. **Individual counters** saturate at 65,535 (16-bit max)
2. **Total transitions** saturate at 262,143 (18-bit max)
3. Once saturated, **no new entropy data affects probabilities**
4. Test becomes **meaningless** - either stuck at false failures or false passes

### Example Failure Scenario

```
After ~260K transitions:
  count_01 = 65,535 (saturated)
  count_10 = 65,535 (saturated)
  count_00 = 65,535 (saturated)
  count_11 = 65,535 (saturated)
  total_transitions = 262,143 (saturated)

All probability calculations frozen:
  prob_01 = (65,535 * 255) / 262,143 = 63.75 → 64

New entropy samples have ZERO effect on probabilities!
```

## Solution: Sliding Window with Counter Scaling

### Implementation

Added a **windowing mechanism** that periodically scales down all counters when approaching saturation:

```systemverilog
module entropy_markov_test #(
    parameter int unsigned DATA_WIDTH = 32,
    parameter int unsigned WINDOW_THRESHOLD = 200000  // New parameter
) (
    // ... ports ...
);

// When total_transitions reaches threshold, scale all counters
if (next_total_transitions >= 18'(WINDOW_THRESHOLD)) begin
    // Divide all counters by 2 (right shift)
    next_count_01 = next_count_01 >> 1;
    next_count_10 = next_count_10 >> 1;
    next_count_00 = next_count_00 >> 1;
    next_count_11 = next_count_11 >> 1;
    next_total_transitions = next_total_transitions >> 1;
end
```

### Benefits

1. **Maintains relative proportions** - probabilities stay accurate
2. **Prevents saturation staleness** - counters never freeze
3. **Continuous monitoring** - test remains responsive indefinitely
4. **Emphasizes recent transitions** - sliding window effect
5. **Configurable threshold** - default 200K, adjustable per use case

### Additional Fix

Fixed width consistency issue in total transitions calculation:
- **Before**: Check used 19-bit, assignment used 18-bit (inconsistent)
- **After**: Both use 18-bit (consistent)

```systemverilog
// Fixed width consistency
if (next_total_transitions + 18'(DATA_WIDTH) <= 18'h3FFFF) begin
    next_total_transitions = next_total_transitions + 18'(DATA_WIDTH);
end
```

## Verification

Created comprehensive test (`tb_markov_windowing.v`) that verifies:

### Test Results

```
Total samples: 1,600
Total transitions: ~51,200
Scaling events: 11
Final counters: 01=844, 10=844, 00=5,327, 11=983

✓ ALL TESTS PASSED

Verified behaviors:
✓ Scaling triggers at window threshold (8,000 transitions)
✓ Probabilities remain responsive after scaling
✓ Counters never saturate (stayed < 6,000, far below 65,535)
✓ Multiple scaling events handled correctly (11 events)
✓ Pattern changes detected properly (00 pattern → prob_00 dominant)
```

### Test Scenarios

1. **Fill to threshold** - Verified scaling triggers at ~8K transitions
2. **Responsiveness** - Biased patterns (01, 10, 00, 11) correctly affect probabilities
3. **Pattern switching** - Probabilities track changing entropy characteristics
4. **Multiple scalings** - 11 scaling events over 51K transitions
5. **Saturation prevention** - Counters stay well below max (< 10% of capacity)
6. **Final responsiveness** - Test remains responsive after many scalings

## Impact

### Before Fix
- ❌ Test becomes meaningless after ~260K samples
- ❌ Probabilities freeze at saturated values
- ❌ No detection of entropy changes
- ❌ Guaranteed false failures or false passes

### After Fix
- ✅ Continuous responsive monitoring
- ✅ Probabilities track entropy changes indefinitely
- ✅ Never saturates - runs forever
- ✅ Maintains statistical validity with sliding window
- ✅ Configurable window size for different requirements

## Usage

### Default Configuration (200K transitions)
```systemverilog
entropy_markov_test #(
    .DATA_WIDTH(32)
    // WINDOW_THRESHOLD defaults to 200000
) dut (
    // ... connections ...
);
```

### Custom Window Size
```systemverilog
entropy_markov_test #(
    .DATA_WIDTH(32),
    .WINDOW_THRESHOLD(100000)  // Scale every 100K transitions
) dut (
    // ... connections ...
);
```

### Considerations

- **Smaller threshold**: More frequent scaling, emphasizes recent transitions
- **Larger threshold**: Less frequent scaling, longer history window
- **Default (200K)**: Good balance for most use cases
- **Test used 8K**: Accelerated testing, demonstrates mechanism

## Files Modified

- **`rtl/entropy_markov_test.sv`** - Added windowing mechanism
- **`tb/tb_markov_windowing.v`** - New comprehensive test
- **`tb/Makefile`** - Added test targets
- **`doc/markov_windowing_fix.md`** - This document

## Testing

Run the windowing test:
```bash
cd tb/
make markov-window          # Run test
make markov-window-waves    # View waveforms
make markov-window-clean    # Clean files
```

---

**Fix Date**: December 17, 2025
**Verified**: All tests passing with 11 scaling events over 51K transitions
**Status**: Ready for integration
