# Entropy Ring Oscillator Tune FSM Bug Analysis

## Bug Summary

The `entropy_rosc_tune_fsm` module has a critical bug where the `tune_state_o` output toggles **every clock cycle** when `health_error_i` remains asserted HIGH, instead of toggling only once on signal transitions.

## Test Results

### Test 1: Health Error Held HIGH for 10 Cycles
- **Expected**: 1 toggle on the 0→1 edge
- **Actual**: 9-10 toggles (one per clock cycle)
- **Result**: ❌ BUG CONFIRMED

### Test 2: Multiple Pulses (2 pulses with 5 cycles each)
- **Expected**: 4 toggles total (one per edge: 0→1, 1→0, 0→1, 1→0)
- **Actual**: 10 toggles
- **Result**: ❌ BUG CONFIRMED

### Test 3: Extended Assertion (20 cycles HIGH)
- **Expected**: 1 toggle on the 0→1 edge
- **Actual**: 19-20 toggles (one per clock cycle)
- **Result**: ❌ BUG CONFIRMED

## Root Cause Analysis

### Current Implementation (BUGGY)

```systemverilog
always_comb begin
    next_state = state;

    case (state)
        STATE_0: begin
            if (health_error_i) begin  // LEVEL check, not EDGE check
                next_state = STATE_1;
            end
        end
        STATE_1: begin
            if (health_error_i) begin  // LEVEL check, not EDGE check
                next_state = STATE_0;
            end
        end
    endcase
end
```

### The Problem

1. **STATE_0**: When `health_error_i` is HIGH, transitions to STATE_1
2. **STATE_1**: When `health_error_i` is HIGH, transitions to STATE_0
3. **Result**: On every clock cycle where `health_error_i` is HIGH, the FSM toggles between states

This is a **level-sensitive** check, not an **edge-sensitive** check.

### What Should Happen

- **0→1 transition**: `tune_state_o` should toggle once
- **1→0 transition**: `tune_state_o` should toggle once
- **Stable HIGH**: `tune_state_o` should remain stable (no toggling)
- **Stable LOW**: `tune_state_o` should remain stable (no toggling)

## Impact Assessment

### Severity: **HIGH**

The bug causes the ring oscillator detuning mechanism to continuously oscillate when health tests fail, rather than making a single adjustment. This results in:

1. **Unstable entropy generation**: Ring oscillators constantly switching between tuned/detuned states
2. **Ineffective countermeasures**: Cannot properly respond to health test failures
3. **Unpredictable behavior**: Detune state becomes unpredictable during error conditions
4. **Potential oscillation at clock frequency**: Could introduce unwanted high-frequency noise

### Affected Modules

- **Primary**: `entropy_rosc_tune_fsm.sv`
- **Secondary**: `entropy_generator.sv` (uses the tune FSM)
- **Tertiary**: Any module instantiating `entropy_generator` with auto-tuning enabled

## Fix Strategy

### Option 1: Edge Detection with Registered Signal (RECOMMENDED)

Add a registered copy of `health_error_i` to detect edges:

```systemverilog
logic health_error_d;  // Previous cycle value

always @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
        health_error_d <= 1'b0;
    end else begin
        health_error_d <= health_error_i;
    end
end

// Detect rising and falling edges
wire health_error_rising  = health_error_i & ~health_error_d;
wire health_error_falling = ~health_error_i & health_error_d;
wire health_error_edge    = health_error_rising | health_error_falling;
```

Then modify FSM to use edge detection:

```systemverilog
always_comb begin
    next_state = state;

    case (state)
        STATE_0: begin
            if (health_error_edge) begin  // Respond to ANY edge
                next_state = STATE_1;
            end
        end
        STATE_1: begin
            if (health_error_edge) begin  // Respond to ANY edge
                next_state = STATE_0;
            end
        end
    endcase
end
```

### Option 2: Single-Bit History FSM

Use additional FSM states to track whether we've already responded to the current level:

- STATE_0_IDLE: In tune state 0, waiting for health_error to go HIGH
- STATE_0_WAIT: In tune state 0, health_error is HIGH, waiting for it to go LOW
- STATE_1_IDLE: In tune state 1, waiting for health_error to go HIGH
- STATE_1_WAIT: In tune state 1, health_error is HIGH, waiting for it to go LOW

This is more complex and uses more states.

### Option 3: Rising Edge Only Detection

Only respond to rising edges (0→1 transitions):

```systemverilog
always_comb begin
    next_state = state;

    case (state)
        STATE_0: begin
            if (health_error_rising) begin  // Only rising edge
                next_state = STATE_1;
            end
        end
        STATE_1: begin
            if (health_error_rising) begin  // Only rising edge
                next_state = STATE_0;
            end
        end
    endcase
end
```

This is simpler but only responds when errors are detected (0→1), not when they clear.

## Recommendation

**Option 1 (Edge Detection with Registered Signal)** is recommended because:

1. ✅ Responds to both rising and falling edges (symmetric behavior)
2. ✅ Simple and clear implementation
3. ✅ Minimal logic overhead (1 flip-flop + combinational edge detection)
4. ✅ Follows standard edge detection pattern
5. ✅ Easy to verify and test

## Next Steps

1. ✅ **COMPLETE**: Create testbench to demonstrate bug
2. ⏳ **PLANNED**: Implement fix using Option 1
3. ⏳ **PLANNED**: Verify fix with modified testbench
4. ⏳ **PLANNED**: Regression test with existing health test modules
5. ⏳ **PLANNED**: Update documentation

## Test Execution

To reproduce the bug:

```bash
cd tb/
make tune-fsm-bug        # Run the bug demonstration test
make tune-fsm-bug-waves  # View waveforms in Surfer
```

## Files

- **Bug test**: `tb/tb_rosc_tune_fsm_bug.v`
- **Buggy module**: `rtl/entropy_rosc_tune_fsm.sv`
- **Waveforms**: `tb/rosc_tune_fsm_bug.vcd`
- **This document**: `doc/tune_fsm_bug_analysis.md`

---

**Report generated**: December 17, 2025
**Tested with**: iverilog (Icarus Verilog)
**Status**: Bug confirmed, fix pending
