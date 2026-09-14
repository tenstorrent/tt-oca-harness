# Entropy Source Synthesis Directory

This directory contains files for logic synthesis of the entropy_source component.

## Files

### RTL File List

- **`entropy_source_rtl.f`** - Complete list of RTL files for synthesis in dependency order
  - Format: Standard Verilog file list (.f format)
  - Contains relative paths from syn/ directory
  - Includes comprehensive synthesis notes and warnings

### Timing Constraints

- **`entropy_source.sdc`** - Synopsys Design Constraints file
  - Clock definitions and timing requirements
  - False path constraints for ring oscillators
  - False path constraints for ripple dividers
  - Multi-cycle path definitions
  - Special handling for metastable sampling

### Verification

- **`check_rtl_files.sh`** - Script to verify all RTL files exist before synthesis
  - Checks every file in entropy_source_rtl.f
  - Provides clear error messages if files are missing
  - Detects if register files need to be generated

## Usage

### Prerequisites

Before running synthesis, ensure all RTL files are present:

```bash
# 1. Generate register files from SystemRDL (if not already done)
cd ../rtl
make build

# 2. Verify all files are present
cd ../syn
./check_rtl_files.sh
```

### Synthesis Flow

#### Synopsys Design Compiler

```tcl
# Read RTL files
read -f entropy_source_rtl.f

# Read timing constraints
read_sdc entropy_source.sdc

# Compile design
compile_ultra
```

#### Cadence Genus

```tcl
# Read RTL files
read -f entropy_source_rtl.f

# Read timing constraints
read_sdc entropy_source.sdc

# Synthesize
synthesize
```

## Important Notes

### Register Files

The register files (`entropy_source_reg.sv`, `entropy_source_reg_pkg.sv`) are **auto-generated** from SystemRDL and are NOT tracked in git.

**Generate them before synthesis:**

```bash
cd ../rtl
make build
```

This will:

1. Generate register files from `../regs/entropy_source.rdl`
2. Copy them to `../rtl/` directory

### Ring Oscillator Constraints

The entropy source contains **asynchronous ring oscillators** that require special synthesis handling:

1. **Do not optimize ring oscillator cells**
   - Use `set_dont_touch` on instances in `entropy_ring_oscillator`
   - Preserve the NAND/inverter chain structure

2. **Timing analysis**
   - Ring oscillator paths are marked as false paths in SDC
   - See `entropy_source.sdc` for complete constraints

3. **Metastability**
   - Sampler flip-flops operate in the metastable region; those events are the entropy source
   - Dual-rank synchronizers handle metastability

### Ripple Divider Constraints

The entropy source contains **asynchronous ripple dividers** for programmable sample clock division:

1. **Do not optimize ripple divider cells**
   - Use `set_dont_touch` on instances in `entropy_ripple_divider`
   - Preserve toggle flip-flop structure (D→QB feedback)
   - Total: 13 instances (1 debug + 12 generators)

2. **Timing analysis**
   - Ripple divider feedback paths are marked as false paths
   - Ripple chain connections (Q→CLK) are marked as false paths
   - Divided outputs are not part of clock tree
   - See the RIPPLE DIVIDER CONSTRAINTS section of `entropy_source.sdc`

3. **Asynchronous structure**
   - Each stage clocks the next stage (ripple chain)
   - Each toggle flip-flop feeds D from QB, a combinational feedback loop
   - Synthesis and lint report these loops; the false-path constraints above cover them

### Security Considerations

This is a security-critical component for true random number generation:

- **Avoid aggressive optimization** that may reduce entropy quality
- **Preserve module boundaries** for health test modules
- Consider using `set_dont_touch` selectively on entropy paths
- Verify that optimization doesn't inadvertently correlate noise sources

## Troubleshooting

### Error: Missing register files

```
✗ MISSING: ../rtl/entropy_source_reg_pkg.sv
✗ MISSING: ../rtl/entropy_source_reg.sv
```

**Solution:** Generate register files:

```bash
cd ../rtl && make build
```

### Error: SystemRDL generation fails

**Check:**

1. Virtual environment is activated: `source ../venv/bin/activate`
2. Required packages installed: `pip install -r ../requirements.txt`
3. OCH_ROOT environment variable is set

### Synthesis Issues

If synthesis reports timing violations or unexpected behavior:

1. **Check ring oscillator constraints** in `entropy_source.sdc`
2. **Verify false paths** are properly applied
3. **Review optimization settings** - may need to disable for ring oscillators
4. **Check for metastability warnings** - warnings on the sampler flip-flops are expected

## References

- SystemRDL source: `../regs/entropy_source.rdl`
- RTL directory: `../rtl/`
- Documentation: `../doc/`
- Specification: `../doc/Entropy_Noise_Source_for_TRNG.pdf`
