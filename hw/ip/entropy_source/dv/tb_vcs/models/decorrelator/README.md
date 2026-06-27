# Decorrelator Reference Model

## ⚠️ IMPORTANT: This is NOT Production RTL

**These are simulation-only reference models used for generating golden data.**

- **Purpose**: Generate expected entropy outputs for verification and comparison
- **Status**: Testbench infrastructure (behavioral models)
- **NOT**: The actual synthesizable RTL design

The actual entropy decorrelator implementation will be in:
```
hw/ip/entropy/rtl/    (when integrated with real design)
```

---

## Files in This Directory

### `Serial_Decorrelator_RefModel.sv`
- **Type**: SystemVerilog reference model
- **Purpose**: Generate golden decorrelated entropy data
- **Modes**:
  - Mode 0: DECOR_29 - 29-deep XOR decorrelator (spec default)
  - Mode 1: DECOR_7 - 7-deep XOR decorrelator (shallow)
  - Mode 2: BYPASS - No decorrelation, raw bits (debug)
  - Mode 3: LFSR_29 - 29-bit Fibonacci LFSR
  - Mode 4: LFSR_7 - 7-bit Fibonacci LFSR

### `decor_cfg_if.sv`
- **Type**: SystemVerilog interface
- **Purpose**: Configuration interface for decorrelator mode selection
- **Usage**: Controlled from Python test scripts via cocotb

### `DECORRELATOR_ANALYSIS.md`
- **Type**: Documentation
- **Purpose**: Detailed analysis comparing implementation against specification
- **Contents**: Verification that reference model matches spec requirements

---

## Why SystemVerilog for Reference Model?

**Sequential Logic**: The decorrelator is inherently sequential with:
- 29-deep shift registers
- Cycle-by-cycle bit shifting
- Counter-based sampling

**Waveform Debugging**: SystemVerilog allows:
- Viewing shift register contents in Verdi
- Verifying timing (sample at cycle 64?)
- Correlating with RO inputs cycle-by-cycle

**Timing Accuracy**:
- Runs at same clock speed as DUT
- Can validate CDC between RO clock and APB clock
- Enables side-by-side comparison with real RTL (when available)

---

## Usage from Python Tests

The reference model is configured from Python via the `decor_cfg_if` interface:

```python
from test.test_base import decor_configure, DECOR_MODE_29

# Configure decorrelator mode
decor_configure(dut, DECOR_MODE_29, log=True)

# Now reference model generates golden data
# Compare with DUT output when available
```

**Available helpers**:
- `decor_set_mode(dut, mode)` - Set mode 0-4
- `decor_configure(dut, mode)` - Set mode with logging
- `decor_get_recommended_sample_period(mode)` - Get recommended period
- `decor_print_mode_info(mode)` - Display mode details

See: `test/test_base.py` for full API

---

## Configuration

### Current Hardcoded Parameters:
- **SAMPLE_PERIOD**: 64 cycles (in `tb_entropy_top.sv`)
- **DEPTH**: 29 (for DECOR_29 mode)
- **N**: 16 lanes

### Runtime Configurable:
- **mode**: 0-4 via `decor_cfg.mode` from Python

### Recommended Sample Periods:
- Mode 0 (DECOR_29): 64 cycles ← **default**
- Mode 1 (DECOR_7): 16 cycles
- Mode 2 (BYPASS): 8 cycles
- Mode 3 (LFSR_29): 64 cycles
- Mode 4 (LFSR_7): 16 cycles

*Note: All periods are coprime with their respective depths*

---

## Future: When Real RTL is Available

When the actual entropy decorrelator RTL is implemented:

1. **Side-by-Side Comparison**:
   ```systemverilog
   // In testbench
   Serial_Decorrelator_RefModel u_golden_model (...);
   entropy_decorrelator u_real_rtl (...);  // Actual design

   // Compare outputs
   always @(posedge clk) begin
       if (golden_vld && rtl_vld) begin
           assert (golden_bytes == rtl_bytes);
       end
   end
   ```

2. **Waveform Analysis**:
   - View both models in Verdi side-by-side
   - Identify differences cycle-by-cycle
   - Debug mismatches visually

3. **Regression Testing**:
   - Keep reference model for continuous validation
   - Ensure RTL changes don't break functionality

---

## Related Documentation

- **Spec**: `../../doc/Entropy_Noise_Source_for_TRNG.pdf` (Pages 6-7)
- **Analysis**: `DECORRELATOR_ANALYSIS.md` (this directory)
- **Config**: `../../test/test_config.py` (DecorrelatorConfig)
- **Helpers**: `../../test/test_base.py` (decor_* functions)

---

## Questions?

If you have questions about:
- **Reference model implementation**: See `DECORRELATOR_ANALYSIS.md`
- **Configuration options**: See `decor_cfg_if.sv` comments
- **Python API**: See `test/test_base.py`
- **Specification**: See Entropy_Noise_Source_for_TRNG.pdf
