# DTP Functional Coverage

This document describes the DTP functional coverage model (`dtp_fcov.py`) and how to integrate it into CocoTB tests.

## Overview

The DTP functional coverage model provides a Python-based functional coverage collection system for CocoTB verification. Since CocoTB doesn't have built-in functional coverage like SystemVerilog, this module implements:

- **Coverage Points**: Track individual features (instructions, states, modes)
- **Coverage Bins**: Track specific values or ranges within coverage points
- **Cross Coverage**: Track combinations of features (e.g., instruction × state)
- **Coverage Reports**: Generate text, JSON, and HTML coverage reports
- **Coverage Metrics**: Calculate coverage percentages and identify holes

## What is Covered?

The DTP functional coverage model tracks:

### 1. JTAG Instructions (`jtag_instruction`)
Tracks which JTAG instructions have been executed:
- BYPASS (0x0000, 0x003F)
- IDCODE (0x0001)
- RUNBIST (0x0002)
- SAMPLE_PRELOAD (0x0003)
- EXTEST (0x0004)
- CLAMP (0x0007)
- HIGHZ (0x0008)
- INTEST (0x0009)
- CLAMP_HOLD (0x000A)
- CLAMP_RELEASE (0x000B)
- And all other instructions defined in `DTPJTAGInstr_e`

### 2. TAP States (`tap_state`)
Tracks which TAP controller states have been visited:
- TEST_LOGIC_RESET
- RUN_TEST_IDLE
- SELECT_DR_SCAN
- CAPTURE_DR
- SHIFT_DR
- EXIT1_DR
- PAUSE_DR
- EXIT2_DR
- UPDATE_DR
- SELECT_IR_SCAN
- CAPTURE_IR
- SHIFT_IR
- EXIT1_IR
- PAUSE_IR
- EXIT2_IR
- UPDATE_IR

### 3. CTP Modes (`ctp_mode`)
Tracks CTP operation modes:
- WIRE_OR (mode=0)
- POINT_TO_POINT (mode=1)

### 4. IDCODE Fields (`idcode_*`)
Tracks IDCODE register fields:
- **idcode_value**: Unique IDCODE values seen
- **idcode_version**: VERSION field values (4-bit, 0-15)
- **idcode_lsb**: LSB validity (should be 1 per IEEE 1149.1)

### 5. Scan Lengths (`*_scan_length`)
Tracks scan chain widths:
- **ir_scan_length**: IR scan widths (4, 5, 6, 7, 8, 10, 16 bits)
- **dr_scan_length**: DR scan widths (1, 8, 16, 32, 64, 128 bits)

### 6. Cross Coverage
Tracks feature combinations:
- **instruction_x_state**: JTAG instruction and TAP state combinations
- **ctp_mode_transition**: CTP mode transitions (WIRE_OR ↔ POINT_TO_POINT)

## Quick Start

### Basic Integration

```python
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from env.dtp_fcov import create_dtp_coverage
from env.dtp_enum import DTPJTAGInstr_e

@cocotb.test()
async def my_test_with_coverage(dut):
    # 1. Create coverage model
    cov = create_dtp_coverage(name="My_Test_Coverage")

    # 2. Setup test (clock, BFM, etc.)
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())
    # ... more setup ...

    # 3. Sample coverage during test execution
    cov.sample_jtag_instruction(DTPJTAGInstr_e.IDCODE)
    cov.sample_tap_state("SHIFT_IR")
    cov.sample_ir_scan(DTPJTAGInstr_e.IDCODE, 6)
    cov.sample_dr_scan(32)
    cov.sample_idcode(0x12345679)

    # 4. Generate coverage reports at test end
    cov.print_coverage_report(detailed=True)
    cov.save_coverage_report("coverage.json")
    cov.generate_html_report("coverage.html")

    # 5. (Optional) Check coverage goals
    overall = cov.get_overall_coverage()
    assert overall >= 80.0, f"Coverage goal not met: {overall:.2f}%"
```

### Example Integration

You can integrate functional coverage into any existing test. Here's how to add coverage to a test like `dtp_jtag_idcode_test`:

```bash
cd $OCH_ROOT/dv/dtp
# Run any test - coverage can be added to the test code
make MODULE=dtp_jtag_idcode_test TESTCASE=dtp_jtag_idcode_test
```

The coverage model can be integrated into existing tests by:
1. Creating a coverage instance at test start
2. Sampling coverage during test execution
3. Generating reports at test end

## API Reference

### Creating Coverage Model

```python
from env.dtp_fcov import create_dtp_coverage

# Create coverage instance
cov = create_dtp_coverage(name="My_Coverage")

# Or use class directly
from env.dtp_fcov import DTPFunctionalCoverage
cov = DTPFunctionalCoverage(name="My_Coverage")
```

### Sampling Coverage

#### JTAG Instruction Coverage
```python
# Sample single instruction
cov.sample_jtag_instruction(DTPJTAGInstr_e.IDCODE)

# Sample IR scan (instruction + width)
cov.sample_ir_scan(DTPJTAGInstr_e.BYPASS_00, ir_width=6)
```

#### TAP State Coverage
```python
# Sample TAP state
cov.sample_tap_state("SHIFT_DR")
cov.sample_tap_state(jtag_bfm.current_state.name)
```

#### CTP Mode Coverage
```python
# Sample CTP mode
cov.sample_ctp_mode(DTPCTPMode_e.WIRE_OR)      # 0
cov.sample_ctp_mode(DTPCTPMode_e.POINT_TO_POINT)  # 1
```

#### IDCODE Coverage
```python
# Sample IDCODE (automatically extracts fields)
idcode = 0x12345679
cov.sample_idcode(idcode)
```

#### Scan Length Coverage
```python
# Sample IR scan length
cov.sample_ir_scan(instruction, width=6)

# Sample DR scan length
cov.sample_dr_scan(width=32)
```

### Querying Coverage

```python
# Get overall coverage percentage
overall = cov.get_overall_coverage()  # Returns 0.0 - 100.0

# Get coverage point summary
summary = cov.get_coverpoint_summary()
for name, info in summary.items():
    print(f"{name}: {info['coverage_percent']:.2f}%")

# Get cross coverage summary
cross_summary = cov.get_cross_coverage_summary()

# Get uncovered bins for a coverage point
uncovered = cov.get_uncovered_bins("jtag_instruction")
print(f"Uncovered instructions: {uncovered}")
```

### Generating Reports

#### Console Report
```python
# Print coverage report to console
cov.print_coverage_report(detailed=False)  # Summary only
cov.print_coverage_report(detailed=True)   # With uncovered bins
```

#### JSON Report
```python
# Save coverage data to JSON
cov.save_coverage_report("coverage.json")

# JSON format:
# {
#   "name": "Coverage_Name",
#   "timestamp": "2025-10-30T12:00:00",
#   "overall_coverage": 85.5,
#   "total_samples": 42,
#   "coverpoints": { ... },
#   "cross_coverage": { ... }
# }
```

#### HTML Report
```python
# Generate HTML coverage report
cov.generate_html_report("coverage.html")

# Opens in browser with:
# - Visual progress bars
# - Color-coded coverage status
# - Detailed bin tables
# - Interactive navigation
```

## Integration Patterns

### Pattern 1: Test-Level Coverage

Collect coverage for a single test:

```python
@cocotb.test()
async def my_test(dut):
    cov = create_dtp_coverage(name="Test_Coverage")

    # Test body with coverage sampling
    # ...

    # Report at end
    cov.print_coverage_report()
```

### Pattern 2: Test Suite Coverage

Accumulate coverage across multiple tests:

```python
# Global coverage instance
_global_coverage = None

def get_global_coverage():
    global _global_coverage
    if _global_coverage is None:
        _global_coverage = create_dtp_coverage(name="Suite_Coverage")
    return _global_coverage

@cocotb.test()
async def test1(dut):
    cov = get_global_coverage()
    # Test body...

@cocotb.test()
async def test2(dut):
    cov = get_global_coverage()
    # Test body...

# Final report after all tests
# (requires custom test runner)
```

### Pattern 3: Coverage-Driven Test Generation

Use coverage to guide test creation:

```python
@cocotb.test()
async def coverage_driven_test(dut):
    cov = create_dtp_coverage()

    # Run initial tests
    # ...

    # Check coverage holes
    uncovered_instr = cov.get_uncovered_bins("jtag_instruction")

    # Generate tests for uncovered items
    for instr in uncovered_instr:
        log.info(f"Testing uncovered instruction: {instr}")
        await test_instruction(dut, instr)
        cov.sample_jtag_instruction(instr)

    # Verify coverage goal
    assert cov.get_overall_coverage() >= 90.0
```

### Pattern 4: Coverage as Pass/Fail Criteria

Use coverage thresholds for test success:

```python
@cocotb.test()
async def test_with_coverage_goal(dut):
    cov = create_dtp_coverage()

    # Test body...

    # Check coverage goals
    overall = cov.get_overall_coverage()
    instruction_cov = cov.coverpoints["jtag_instruction"].coverage_percent

    # Assertions
    assert overall >= 80.0, f"Overall coverage too low: {overall:.2f}%"
    assert instruction_cov >= 90.0, f"Instruction coverage too low: {instruction_cov:.2f}%"

    cov.print_coverage_report()
```

## Advanced Usage

### Adding Custom Coverage Points

You can extend the coverage model with custom coverage points:

```python
cov = create_dtp_coverage()

# Add custom coverage point
from env.dtp_fcov import CoveragePoint

custom_cp = CoveragePoint(
    name="my_custom_feature",
    description="Custom feature coverage"
)

# Add bins
custom_cp.add_bin("feature_A", goal=1)
custom_cp.add_bin("feature_B", goal=5)  # Require 5 hits

# Add to model
cov.coverpoints["my_custom_feature"] = custom_cp

# Sample
custom_cp.hit("feature_A")
custom_cp.hit("feature_B", count=2)
```

### Adding Custom Cross Coverage

```python
from env.dtp_fcov import CrossCoveragePoint

# Create custom cross coverage
custom_cross = CrossCoveragePoint(
    name="custom_cross",
    description="Custom feature cross coverage",
    point1_name="feature1",
    point2_name="feature2"
)

# Add cross bins
custom_cross.add_cross_bin("A", "X", goal=1)
custom_cross.add_cross_bin("A", "Y", goal=1)
custom_cross.add_cross_bin("B", "X", goal=1)
custom_cross.add_cross_bin("B", "Y", goal=1)

# Add to model
cov.cross_coverpoints["custom_cross"] = custom_cross

# Sample
custom_cross.hit("A", "X")
custom_cross.hit("B", "Y")
```

### Disabling Coverage Points

For performance, disable unused coverage points:

```python
# Disable a coverage point
cov.coverpoints["idcode_version"].enabled = False

# Disable cross coverage
cov.cross_coverpoints["instruction_x_state"].enabled = False

# Sampling disabled points has no effect
cov.sample_idcode(0x12345679)  # idcode_version won't be sampled
```

### Coverage Merging

Merge coverage from multiple runs:

```python
# Run 1
cov1 = create_dtp_coverage(name="Run1")
# ... collect coverage ...
cov1.save_coverage_report("coverage_run1.json")

# Run 2
cov2 = create_dtp_coverage(name="Run2")
# ... collect coverage ...
cov2.save_coverage_report("coverage_run2.json")

# Merge (requires custom script)
# merge_coverage.py coverage_run1.json coverage_run2.json -o merged.json
```

## Best Practices

### 1. Sample at Meaningful Points
```python
# GOOD: Sample after state transition completes
await jtag_bfm.scan_ir(instruction, width)
cov.sample_ir_scan(instruction, width)

# BAD: Don't sample in tight loops (performance impact)
for i in range(10000):
    cov.sample_tap_state("SHIFT_DR")  # Too frequent!
```

### 2. Use Descriptive Names
```python
# GOOD: Clear coverage model names
cov = create_dtp_coverage(name="IDCODE_Test_Coverage")

# BAD: Generic names
cov = create_dtp_coverage(name="cov")
```

### 3. Generate Reports at Test End
```python
@cocotb.test()
async def my_test(dut):
    cov = create_dtp_coverage()

    # Test body...

    # Always generate reports at end
    cov.print_coverage_report(detailed=True)
    cov.save_coverage_report(f"{cocotb.SIM_NAME}_coverage.json")
    cov.generate_html_report(f"{cocotb.SIM_NAME}_coverage.html")
```

### 4. Review Coverage Regularly
```python
# Check coverage during development
uncovered_instrs = cov.get_uncovered_bins("jtag_instruction")
if uncovered_instrs:
    log.warning(f"Uncovered instructions: {uncovered_instrs}")

# Add targeted tests for uncovered bins
```

### 5. Set Realistic Goals
```python
# Define clear coverage goals per project phase
if project_phase == "early_development":
    coverage_goal = 50.0
elif project_phase == "integration":
    coverage_goal = 80.0
else:  # production
    coverage_goal = 95.0

assert cov.get_overall_coverage() >= coverage_goal
```

## Performance Considerations

Coverage collection adds overhead to simulation. To minimize impact:

1. **Sample Selectively**: Don't sample every clock cycle
2. **Disable Unused Points**: Turn off coverage you don't need
3. **Limit Cross Coverage**: Be selective with cross coverage combinations
4. **Batch Sampling**: Sample multiple features together when possible

```python
# GOOD: Batch sampling
cov.sample_ir_scan(instruction, width)  # Samples instruction + width + state

# LESS EFFICIENT: Individual samples
cov.sample_jtag_instruction(instruction)
cov.sample_ir_scan_length(width)
cov.sample_tap_state(state)
```

## Troubleshooting

### Coverage Not Updating
- **Check enabled flag**: `cov.coverpoints["name"].enabled`
- **Verify sampling calls**: Add debug logging
- **Check bin names**: Ensure exact match with defined bins

### Low Cross Coverage
- Cross coverage requires both features to be sampled together
- Check that you're sampling both dimensions
- Review cross bin definitions

### HTML Report Not Rendering
- Ensure HTML file is saved successfully
- Check browser console for JavaScript errors
- Try different browser if issues persist

## Integration Examples

You can add coverage to any existing test by following the patterns shown in the "Integration Patterns" section above:
- Basic coverage integration with minimal code changes
- Sampling different coverage types during test execution
- Generating multiple report formats at test completion
- Using coverage metrics as pass/fail criteria

## Future Enhancements

Potential additions (not yet implemented):
- Coverage merging utility
- Regression tracking across runs
- Coverage trending over time
- Integration with CI/CD systems
- Coverage exclusions/waivers
- Weight-based coverage metrics
- Automatic test generation from coverage holes

## References

- IEEE 1149.1 (JTAG Standard)
- CocoTB Documentation: https://docs.cocotb.org
- DTP Enum Definitions: `dtp_enum.py`
- DTP Test Directory: `tests/standalone/` (integration examples in existing tests)

## Author

Andrew Hsiao (ahsiao@tenstorrent.com)

## License

Copyright 2025 Tenstorrent Inc.
