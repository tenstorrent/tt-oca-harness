# Entropy Source Simulation Guide

## Prerequisites

### Python Version Requirements

**Required:** Python 3.7 - 3.12

The test environment uses cocotb which currently supports Python 3.7 through 3.12. Python 3.13+ is **not yet supported**.

If you encounter pip installation errors when running `./run.sh`, check your Python version:

```bash
python3 --version
```

#### Workaround for Python 3.13+

If your system default `python3` is version 3.13 or newer, manually create the venv with a compatible Python version:

```bash
# Remove any existing incompatible venv
rm -rf ./venv

# Create venv with Python 3.12 (or 3.11, 3.10, 3.9)
python3.12 -m venv ./venv

# Now run.sh will use this existing venv
./run.sh -t test_entropy_sanity
```
## Quick Start

```bash
# List all available tests
./run.sh --list

# Run a test
./run.sh -t test_entropy_sanity

# Run with waveforms
./run.sh -t test_reg_walk --waves

# Run with code coverage
./run.sh -t test_health_tests --cov
```

## Available Tests

Total: 48 tests across 5 test suites

| Test Module | Tests | Description |
|-------------|-------|-------------|
| `test_reg_walk` | 1 | Register access verification |
| `test_decorrelator_modes` | 16 | Decorrelator modes and configurations |
| `test_entropy_fifo` | 16 | FIFO functionality and boundary conditions |
| `test_health_tests` | 13 | Health monitors (Repetition, APT, Markov) |
| `test_debug_monitor` | 3 | Debug monitor CSR interface |
| `test_apb_random` | 1 | Random APB transactions |
| `test_entropy_sanity` | 1 | End-to-end sanity check |
| `test_misc` | 1 | Downsample rate configuration |

## Running Simulations

### Basic Usage

```bash
./run.sh -t <test_name> [options]
```

### Common Options

| Option | Description |
|--------|-------------|
| `-t, --test` | Test module to run (required) |
| `--testcase` | Run specific test function |
| `-l, --list` | List all available tests |
| `--waves` | Enable FSDB waveform generation |
| `--cov` | Enable code coverage |
| `--force` | Force recompilation |
| `-c, --cleanup` | Clean build artifacts |

### Examples

```bash
# Run all decorrelator tests (16 subtests)
./run.sh -t test_decorrelator_modes

# Run specific subtest with waves
./run.sh -t test_decorrelator_modes --testcase test_1_1_1_full_decorrelation_mode --waves

# Run health tests with coverage
./run.sh -t test_health_tests --cov

# Force rebuild
./run.sh -t test_reg_walk --force
```

## Simulation Scripts

### run.sh
Main simulation script. Automatically detects source changes and only recompiles when needed.

```bash
./run.sh -t test_entropy_sanity          # Basic run
./run.sh -t test_reg_walk --waves        # With waveforms
./run.sh -t test_health_tests --cov      # With coverage
```

### clean.sh
Remove all build artifacts, logs, and waveforms.

```bash
./clean.sh
```

### kill_simv.sh
Kill hung simulation processes.

```bash
./kill_simv.sh
```

## Code Coverage

```bash
# Run test with coverage
./run.sh -t test_reg_walk --cov

# View coverage report (auto-generated)
firefox sim/logs/test_reg_walk/coverage/reports/hierarchy.html
```

Coverage reports are saved in: `sim/logs/<test>/coverage/reports/`

## Waveform Debugging

```bash
# Generate waveforms
./run.sh -t test_entropy_sanity --waves

# View in Verdi
verdi -ssf sim/logs/test_entropy_sanity/tb_entropy_top.fsdb &
```

Waveforms are saved in: `sim/logs/<test>/tb_entropy_top.fsdb`

## Directory Structure

```
tb_vcs/
├── sim/                       # Run simulations from here
│   ├── run.sh                # Main simulation script
│   ├── clean.sh              # Cleanup script
│   ├── kill_simv.sh          # Kill hung processes
│   ├── logs/                 # Test logs and results (auto-generated)
│   └── build/                # Build artifacts (auto-generated)
├── test/                     # Test suite (Python/Cocotb)
├── Makefile                  # Build configuration
├── rtl.f                     # RTL file list
└── tb.f                      # Testbench file list
```

## Troubleshooting

### Python version error during venv creation

**Error:** `subprocess-exited-with-error` when installing cocotb

**Cause:** Your system's default `python3` is version 3.13 or newer (cocotb requires 3.7-3.12)

**Solution:**
```bash
# Check Python version
python3 --version

# If 3.13+, manually create venv with compatible Python
rm -rf ./venv
python3.12 -m venv ./venv
./run.sh -t <test>
```

See [Prerequisites](#prerequisites) section for details.

### Simulation hangs
```bash
./kill_simv.sh
```

### Compilation errors
```bash
./clean.sh
./run.sh -t <test> --force
```

### View logs
```bash
cat sim/logs/<test>/cocotb_<test>.log     # Test log
cat sim/logs/<test>/vcs.log               # Compilation log
```

---

For more details, see project documentation in `../doc/` and `../README.md`
