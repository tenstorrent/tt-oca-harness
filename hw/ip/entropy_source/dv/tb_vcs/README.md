# Entropy Source Testbench (VCS + Cocotb)

APB-based cocotb testbench for the entropy_source RTL with behavioral ring oscillator models.

## Prerequisites

```bash
cd $OCH_ROOT   # repository root
source bin/setup_env.sh
```

## Quick Start

```bash
cd sim
./run.sh --list              # List all tests
./run.sh -t test_reg_walk    # Run a single test
./run.sh --regre             # Run the regression suite
cat latest_regr.log          # View latest regression report
```

## Directory Structure

```
tb_vcs/
├── sim/                     # Simulation scripts
│   ├── run.sh              # Main test runner
│   ├── regression.list     # Regression test selection
│   ├── parse_log.sh        # Generate regression reports
│   └── latest_regr.log     # Symlink to latest regression.log
├── test/                    # Test suite (Python/Cocotb)
│   ├── test_base.py        # Common infrastructure & helpers
│   ├── test_config.py      # Test configuration
│   ├── test_decorrelator_modes.py  # Decorrelator tests
│   ├── test_entropy_fifo.py        # FIFO tests
│   ├── test_health_tests.py        # Health monitor tests
│   ├── test_debug_monitor.py       # Debug monitor tests
│   ├── test_reg_walk.py            # Register walking test
│   └── test_entropy_sanity.py      # End-to-end sanity
├── apb_vip/                 # APB4 Verification IP
├── models/                  # Reference models (decorrelator, compressor)
├── doc/                     # Documentation
│   ├── TEST_PLAN.txt       # Test plan with pass criteria
│   └── REGISTER_MAP.md     # Register documentation
└── regs/          # SystemRDL sources & generated files
    ├── rdl/                # SystemRDL source files
    └── reg_update.sh       # RDL regeneration script
```

## Regression Testing

### Running Regression

```bash
cd sim
./run.sh --regre
```

Results saved to timestamped directory: `logs/regr_YYYY-MM-DD_HH-MM-SS/regression.log`

### Quick Access to Latest Results

```bash
cat latest_regr.log          # View latest regression report (symlink)
```

The `latest_regr.log` symlink automatically points to the most recent regression run.

### Test Selection

Edit `sim/regression.list` to control which test suites run:

```bash
test_entropy_sanity          # Sanity test
test_reg_walk                # Register walk
test_decorrelator_modes      # Decorrelator suite
test_entropy_fifo            # FIFO suite
test_health_tests            # Health test suite
test_debug_monitor           # Debug monitor suite
#test_misc                   # Comment out to skip
```

### Regression Report Format

`regression.log` includes pass/fail status and **checker coverage**:

```
Test Name                          Status   DECOR COMP  FIFO  IRQ   Time
--------------------------------------------------------------------------------
test_1_1_1_full_decorrelation_mode PASS     V     V     V     -     1.39s
test_2_3_1_overflow_detection      PASS     -     -     -     V     0.59s
test_3_3_1_repetition_test_failure PASS     -     -     -     V     1.01s
```

**Checker Status:**

- `V` = Checker ALIVE (verification ran successfully)
- `X` = Checker DEAD (enabled but didn't run - **needs investigation**)
- `-` = Checker disabled for this test
- `M` = Manual verification required

## Checker Verification System

Four independent checkers verify correctness:

| Checker | Purpose | Log Marker |
|---------|---------|------------|
| **DECOR** | Decorrelator RTL vs Python reference model | `[DECOR CHECK]` |
| **COMP** | Compressor RTL vs GF(2^8) reference model | `[COMP CHECK]` |
| **FIFO** | FIFO readout vs golden queue | `[FIFO CHECK]` |
| **IRQ** | Interrupt assertion/deassertion | `[IRQ CHECK]` |

**Usage in tests:**

```python
from test.test_base import (
    decorrelator_checker_verify, compressor_checker_verify,
    verify_fifo_readout, irq_checker_verify_async
)

# Verify checkers (logs activity regardless of test pass/fail)
decorrelator_checker_verify(dut, mon, expected_match=True)
await irq_checker_verify_async(dut, apb, expected_irq=True)
```

## Development Workflows

### Single Test Development

```bash
cd sim
./run.sh -t test_name               # Run test without waveforms
./run.sh -t test_name --waves       # Debug with waveforms
verdi -ssf logs/test_name/*/simv.fsdb  # View waveforms
```

### Regression Workflow

```bash
./run.sh --regre                    # Run full regression (no waveforms)
cat latest_regr.log                 # Quick results
```

### Register Modification

```bash
# 1. Edit RDL source
vim ../regs/entropy_source_reg.rdl

# 2. Regenerate all artifacts (RTL, docs, headers)
cd ../regs
./reg_update.sh

# 3. Verify changes
git diff
cd ../../sim
./run.sh -t test_reg_walk
```

## Test Infrastructure

### Configuration System

Centralized test configuration via `test_config.py`:

```python
from test.test_config import DEFAULT_CONFIG, get_custom_config

cfg = get_custom_config(
    decorrelator_samples=100,
    fifo_verification_enable=True,
    disable_clk_divider_check=True
)
```

### Helper Functions

Common test patterns in `test_base.py`:

```python
from test.test_base import (
    init, reg_wr, reg_rd,
    configure_testbench, program_dut_registers,
    collect_entropy_samples, verify_fifo_readout,
    irq_checker_verify_async
)
```

### Register Access

```python
# Write/read by register name (no address calculation needed)
await reg_wr(apb, 'DECORRELATOR_CTRL', 0x003F0000)
status = await reg_rd(apb, 'FIFO_STATUS')

# Helper functions for common register operations
health_status = await read_health_test_status(apb)
intr_status = await read_intr_status(apb)
```

## Behavioral Models

- **Ring Oscillator (RO)**: Configurable bias, correlation, stuck-at faults, 32-bit injection mode
- **Decorrelator**: Python reference (modes 0-4: DECOR_29, DECOR_7, BYPASS, LFSR_29, LFSR_7)
- **Compressor**: Python GF(2^8) reference for BIW extraction
- **Golden Queue**: End-to-end FIFO verification
- **Golden Counters**: Health test reference models (repetition, APT, Markov)

See `models/` directory and `test_base.py` for implementation details.

## Writing Tests

### Template

```python
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from test.test_base import init, reg_wr, reg_rd
from test.test_config import get_custom_config

@cocotb.test()
async def test_my_feature(dut):
    """Test description following TEST_PLAN.txt format"""
    cfg = get_custom_config(decorrelator_samples=50)
    apb, mon = await init(dut, config=cfg)

    # Configure DUT
    ctrl = await reg_rd(apb, 'CTRL')
    await reg_wr(apb, 'CTRL', ctrl & ~(1 << 1))

    # Verify behavior
    ctrl = await reg_rd(apb, 'CTRL')
    assert not (ctrl & (1 << 1)), f"MODULE_ENABLE did not clear: {ctrl:#x}"

    # Verify checkers
    decorrelator_checker_verify(dut, mon, expected_match=True)
```

### Best Practices

- Follow TEST_PLAN.txt structure for test documentation
- Use descriptive names: `test_<suite>_<id>_<feature>` (e.g., `test_3_3_1_repetition_test_failure`)
- Add test to `regression.list` when complete
- Use checkers to verify correctness independently
- Log clear pass/fail messages with dut._log.info()
- Include checker verification even for tests that may fail

## Quick Reference

### Key Scripts

| Script | Purpose |
|--------|---------|
| `run.sh` | Main test runner (supports --list, -t, --regre, --waves, --force) |
| `parse_log.sh` | Generate regression reports with checker status |
| `reg_update.sh` | Regenerate RTL/docs/headers from SystemRDL |
| `clean.sh` | Clean build artifacts |

### Important Files

| File | Description |
|------|-------------|
| `TEST_PLAN.txt` | Test plan with pass criteria |
| `REGISTER_MAP.md` | Complete register documentation |
| `regression.list` | Test suite selection for regression |
| `latest_regr.log` | Symlink to most recent regression.log |

### Useful Commands

```bash
# List all tests
./run.sh --list

# Run single test with waves
./run.sh -t test_name --waves

# Run specific test suite
./run.sh -t test_health_tests

# Run regression
./run.sh --regre

# View latest results
cat latest_regr.log

# Force rebuild
./run.sh -t test_name --force

# Regenerate registers from RDL
cd ../regs && ./reg_update.sh
```

## Test Suites

### Suite 0: Sanity & Basic Tests

- test_entropy_sanity: End-to-end sanity check
- test_reg_walk: Register default value and access verification

### Suite 1: Decorrelator Modes

- Pure modes: Full decorrelation, full bypass, fast/slow sampling
- Mixed modes: Partial bypass configurations, dynamic reconfiguration
- Compressor bypass: Raw decorrelator output (3 words per sample)
- Byte mask: Decorrelator output masking

### Suite 2: Entropy FIFO

- Basic: Reset, push/pop, fill/drain, simultaneous operations
- Pointer management: Wraparound testing
- Boundary conditions: Overflow/underflow detection with IRQ
- Data integrity: Pattern testing with golden reference
- Register interface: Enable/disable, auto-pop verification
- Interrupts: INTR_TEST injection for FIFO interrupts
- Security: Parity generation, error detection, pointer fault detection

### Suite 3: Health Tests

- CSR interface: Enable/disable, threshold configuration, counter monitoring
- Pipeline integration: Health tests with full decorrelation
- Failure detection: Repetition/APT/Markov test failures with IRQ and recovery
- Threshold boundary: >= comparison logic verification
- Long-duration: Extended operation, repeated failure/recovery cycles
- Interrupt verification: INTR_TEST injection
- Detune feature: Manual detune, autotune for each health test

### Suite 4: Debug Monitor

- CSR interface: DEBUG_CTRL register access
- Signal selection: Index boundary values
- Frequency selection: Divider boundary values

### Suite 5: Miscellaneous

- Downsample rate configuration
- Startup delay

---

**For detailed test specifications and pass criteria, see [doc/TEST_PLAN.txt](doc/TEST_PLAN.txt)**
