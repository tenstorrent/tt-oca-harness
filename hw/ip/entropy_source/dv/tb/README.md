# Entropy Component Testbenches

This directory contains comprehensive testbenches for verifying the entropy component modules including entropy noise sources and debug monitoring functionality.

## Quick Start

### Entropy Noise Source Test

```bash
# Run the simulation
make

# Check that enabling the ring advances simulated time
make ring-smoke

# View help
make help

# Clean and run
make clean && make

# View waveforms with Surfer (after simulation)
make waves
```

### Debug Monitor Test

```bash
# Run the simulation
make debug

# View help
make help

# Clean and run
make debug-clean && make debug

# View waveforms with Surfer (after simulation)
make debug-waves
```

## Entropy Noise Source Testbench

### Overview

Verifies the `entropy_noise_source` module with comprehensive frequency measurement, metastability detection, and entropy generation analysis. The noise source internally instantiates a ring oscillator and performs metastable sampling with D flip-flops.

### Test Features

- **Ring Oscillator Startup**: Verifies proper oscillation begins after enable (internal to noise source)
- **Metastable Sampling**: Tests the sampling D flip-flop that captures ring oscillator transitions
- **Frequency Measurement**: Accurate measurement of ring oscillator and synchronized output frequencies
- **Metastability Analysis**: Estimates metastable events and rates from sampling process
- **Extended Runtime**: 2ms simulation for at least 500 synchronized output edges

### Clock Configuration

- **Ring Oscillator**: ~35.7 MHz asynchronous oscillation (internal to noise source)
- **Sample Clock**: 6.0 MHz (1/6 of ring frequency, used for metastable sampling)
- **System Clock**: 10.0 MHz (used for final synchronization)

### DUT Configuration

```verilog
entropy_noise_source #(
    .TOTAL_LENGTH(17),    // 17-stage ring oscillator (internal)
    .TAPPED_LENGTH(13)    // 13-stage tap for detuning
) u_entropy_noise_src (
    .clk_i(clk_i),           // 10 MHz system clock for synchronization
    .rstn_i(rstn_i),         // Active-low reset
    .sample_clk_i(sample_clk_i), // 6 MHz sample clock for metastable sampling
    .enable_i(enable_i),     // Enable ring oscillation
    .detune_i(detune_i),     // Select tap length for frequency tuning
    .noise_o(noise_o)        // Synchronized entropy output after sampling
);
```

### Files Generated

- `tb_ring_oscillator` - Compiled simulation executable
- `ring_oscillator.vcd` - Waveform file with full signal traces

## Debug Monitor Testbench

### Overview

Comprehensively verifies the `entropy_debug_monitor` module which provides configurable signal selection and frequency division for debugging entropy sources.

### Test Description

#### Phase 1: Signal Selection Test (16 Signals with ÷4)

- **Purpose**: Verify that each of the 16 input signals can be individually selected
- **Configuration**: `select_freq_div_i = 2` (divide by 4)
- **Input Signals**: 16 coprime oscillators with periods from 31ns to 101ns
- **Expected Results**: Each signal should appear at output divided by 4

#### Phase 2: Frequency Division Test (Signal[7] with All Divisions)

- **Purpose**: Verify all frequency division ratios work correctly
- **Test Signal**: Signal[7] (61ns period, ~16.39 MHz)
- **Division Ratios**: 1, 2, 4, 8, 16, 32, 64 (powers of 2)
- **Expected Results**: Output frequency should match input frequency divided by selected ratio

### Input Oscillators

16 coprime period oscillators to minimize correlation:

```verilog
PERIODS[0:15] = {31.0, 37.0, 41.0, 43.0, 47.0, 53.0, 59.0, 61.0,
                 67.0, 71.0, 73.0, 79.0, 83.0, 89.0, 97.0, 101.0}
```

### DUT Configuration

```verilog
entropy_debug_monitor #(
    .NSIGNALS(16),        // 16 input signals
    .FREQ_DIV_WIDTH(7)    // 7 frequency division ratios
) u_debug_monitor (
    .rstn_i(rstn_i),
    .select_signal_i(select_signal_i),    // 4-bit: selects 1 of 16 signals
    .signal_i(signal_i),                  // 16-bit: input signals
    .select_freq_div_i(select_freq_div_i), // 4-bit: selects division ratio
    .sig_monitor_o(sig_monitor_o)         // 1-bit: monitored output
);
```

### Features Exercised

- **Signal multiplexer**: Selects 1 of 16 inputs using 4-bit select
- **Asynchronous frequency divider**: 6-stage ripple counter for division
- **Output multiplexer**: Selects divided signal using 4-bit select
- **Reset behavior**: Proper initialization of all divider stages
- **One-hot verification**: Continuous monitoring of decode logic integrity

### Files Generated

- `tb_debug_monitor` - Compiled simulation executable
- `debug_monitor.vcd` - Waveform file (~40MB with all signals and decode traces)

## Verification Features

### One-Hot Verification

Both testbenches include continuous verification that binary decode signals are always one-hot:

- **Signal selection decode**: Ensures exactly one of 16 signal selects is active
- **Frequency selection decode**: Ensures exactly one of 7 frequency dividers is active
- **Error reporting**: Detailed messages if violations occur with timing and decode patterns

### Frequency Measurement

Accurate frequency measurement using edge counting:

- **Configurable measurement windows**: Optimized for different frequency ranges
- **Realistic tolerances**: 10% pass, 20% info, >20% fail criteria
- **Error percentage reporting**: Actual vs expected frequency differences

### Comprehensive Coverage

- **Startup behavior**: Proper reset and initialization sequences
- **Steady-state operation**: Long-duration measurements for accuracy
- **Corner cases**: Boundary conditions and edge cases
- **Debug capabilities**: Extensive VCD signal dumps for analysis

## Common Files

### RTL Sources

- `../../../../common/och_prim_generic/rtl/` - Shared OCAH primitive behavioral models
- `../rtl/entropy_ring_oscillator.sv` - Simple ring oscillator module (used internally)
- `../rtl/entropy_noise_source.sv` - Main noise source with ring oscillator and sampling
- `../rtl/entropy_debug_monitor.sv` - Debug monitoring and signal selection

### Simulation Tools

- **iverilog**: Verilog compiler and simulator
- **Surfer**: Waveform viewer
- **VCD format**: Standard waveform dump format

## Usage for Entropy System

### Entropy Noise Source

- **Entropy generation**: Primary source of random bits from ring oscillator and metastable sampling
- **Integrated sampling**: Contains internal ring oscillator with metastable D flip-flop sampling
- **Characterization**: Measure oscillation frequencies, sampling behavior, and stability
- **Validation**: Verify proper startup, sampling process, and continuous operation

### Debug Monitor

- **Signal isolation**: Select specific oscillator for analysis
- **Frequency scaling**: Scale down high frequencies for measurement equipment
- **Off-chip monitoring**: Provide clean output signals for external analysis
- **System debug**: Troubleshoot entropy source performance issues
