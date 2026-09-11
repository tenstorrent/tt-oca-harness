# Entropy Compressor Reference Model

## Overview

This directory contains the reference model for the Entropy Compressor (BIW Extractor) used in testbench verification.

## Files

| File | Description |
|------|-------------|
| `gf256_functions.svh` | GF(2^8) arithmetic functions (multiply, multiply-add) |
| `compressor_cfg_if.sv` | Configuration interface for runtime control |
| `Entropy_Compressor_RefModel.sv` | Main reference model (BIW extractor) |
| `README.md` | This file |

## GF(2^8) Functions

### Primitive Polynomial

Uses the **AES primitive polynomial**: x^8 + x^4 + x^3 + x + 1 (0x1B)

This is the same polynomial used in AES MixColumns operations.

### Functions

#### `gf256_mult(a, b)`

Multiplies two GF(2^8) elements using the shift-and-XOR algorithm.

**Example:**

```systemverilog
logic [7:0] result;
result = gf256_mult(8'h02, 8'h03);  // Returns 8'h06
result = gf256_mult(8'h53, 8'hCA);  // Returns 8'h01 (AES test vector)
```

#### `gf256_muladd(a, b, c)`

Computes `(a * b) + c` in GF(2^8). This is the core BIW extractor operation.

**Example:**

```systemverilog
logic [7:0] result;
result = gf256_muladd(8'h02, 8'h03, 8'h01);  // Returns 8'h07
result = gf256_muladd(8'h53, 8'hCA, 8'h00);  // Returns 8'h01
```

### Usage in Your Code

```systemverilog
// Include the functions
`include "gf256_functions.svh"

// Use in your module
module my_module;
    logic [7:0] a, b, c, y;

    // Compute BIW extractor
    assign y = gf256_muladd(a, b, c);
endmodule
```

## Configuration Interface

### Overview

The `compressor_cfg_if` interface provides runtime control over the compressor reference model.

### Key Features

| Signal | Type | Default | Description |
|--------|------|---------|-------------|
| `enable` | Input | 1 | Enable/disable compressor |
| `bypass` | Input | 0 | Bypass mode (0=BIW, 1=concatenate) |
| `lane_mask[11:0]` | Input | 0xFFF | Per-lane enable mask |
| `group_sel[1:0]` | Input | 0 | Debug group selection (0-3) |
| `group_a_debug[7:0]` | Output | - | Selected group's 'a' input |
| `group_b_debug[7:0]` | Output | - | Selected group's 'b' input |
| `group_c_debug[7:0]` | Output | - | Selected group's 'c' input |
| `group_y_debug[7:0]` | Output | - | Selected group's 'y' output |
| `sample_count[31:0]` | Output | - | Number of samples processed |

### Usage Example

**In SystemVerilog:**

```systemverilog
// Create configuration interface
compressor_cfg_if cfg();

// Instantiate compressor model
Entropy_Compressor_RefModel #(.N_LANES(12)) model (
    .clk_i  (clk),
    .rstn_i (rstn),
    .bytes_i(input_bytes),
    .vld_i  (input_valid),
    .cfg    (cfg.slave),
    .word_o (output_word),
    .vld_o  (output_valid)
);

// Configure from testbench
initial begin
    cfg.enable    = 1'b1;      // Enable compression
    cfg.bypass    = 1'b0;      // Use BIW extraction
    cfg.lane_mask = 12'hFFF;   // All lanes active
    cfg.group_sel = 2'b00;     // Debug group 0
end
```

**From Python (cocotb):**

```python
# Enable compressor
dut.compressor_cfg.enable.value = 1
dut.compressor_cfg.bypass.value = 0

# Enable all lanes
dut.compressor_cfg.lane_mask.value = 0xFFF

# Select debug group 2 for inspection
dut.compressor_cfg.group_sel.value = 2
await RisingEdge(dut.clk)

# Read debug values
group_a = int(dut.compressor_cfg.group_a_debug.value)
group_b = int(dut.compressor_cfg.group_b_debug.value)
group_c = int(dut.compressor_cfg.group_c_debug.value)
group_y = int(dut.compressor_cfg.group_y_debug.value)

print(f"Group 2: ({group_a:02X} * {group_b:02X}) + {group_c:02X} = {group_y:02X}")
```

### Operating Modes

#### Normal Mode (bypass=0)

```
12 input bytes → 4 BIW extractors → 32-bit word
Each group: y[i] = (a[i] * b[i]) + c[i] in GF(2^8)
```

#### Bypass Mode (bypass=1)

```
12 input bytes → Simple concatenation → 32-bit word
Output = {bytes[0], bytes[1], bytes[2], bytes[3]}
```

**Use case**: Debug, verify data flow without GF(2^8) complexity

#### Lane Masking

```
lane_mask = 0xFFF → All 12 lanes active
lane_mask = 0x001 → Only lane 0 active (others forced to 0x00)
lane_mask = 0xAAA → Even lanes only: 0,2,4,6,8,10
```

**Use case**: Test single lane, debug specific RO issues

### Debug Features

**Group Selection** (group_sel):

- `2'b00`: Debug group 0 → lanes [0, 4, 8]
- `2'b01`: Debug group 1 → lanes [1, 5, 9]
- `2'b10`: Debug group 2 → lanes [2, 6, 10]
- `2'b11`: Debug group 3 → lanes [3, 7, 11]

**Debug Outputs**: Expose intermediate values for verification

- `group_a_debug`: First input to multiply (lane i)
- `group_b_debug`: Second input to multiply (lane i+4)
- `group_c_debug`: Add input (lane i+8)
- `group_y_debug`: Final output byte
- `group_product_debug`: a*b before adding c

**Example**: Verify GF(2^8) arithmetic

```python
# Select group 0
dut.compressor_cfg.group_sel.value = 0
await RisingEdge(dut.clk)

a = int(dut.compressor_cfg.group_a_debug.value)
b = int(dut.compressor_cfg.group_b_debug.value)
c = int(dut.compressor_cfg.group_c_debug.value)
y = int(dut.compressor_cfg.group_y_debug.value)

# Verify: y should equal (a*b)+c in GF(2^8)
expected = gf256_muladd(a, b, c)
assert y == expected, f"Mismatch: got {y:02X}, expected {expected:02X}"
```

### Helper Functions

The interface includes built-in helper functions:

```systemverilog
// Check if lane is enabled
logic enabled = cfg.is_lane_enabled(lane_num);

// Count active lanes
int active = cfg.count_active_lanes();

// Get lane indices for group
int la, lb, lc;
cfg.get_group_lanes(group_num, la, lb, lc);
```

## Testing

The GF(2^8) functions include built-in assertions that verify correctness against known test vectors from AES.

**To enable assertions**, define `GF256_ENABLE_ASSERTIONS` when compiling:

```systemverilog
`define GF256_ENABLE_ASSERTIONS
`include "gf256_functions.svh"
```

The assertions will automatically run at simulation start and verify:

- Basic multiplication operations
- Polynomial reduction
- AES test vectors
- Algebraic properties (commutativity, distributive law, etc.)

**Note**: Testing is integrated into the main testbench when the compressor reference model is instantiated.

## Test Vectors

### From AES Specification (FIPS 197)

| Operation | Result | Notes |
|-----------|--------|-------|
| 0x02 * 0x03 | 0x06 | Basic multiplication |
| 0x02 * 0x87 | 0x0E | With polynomial reduction |
| 0x53 * 0xCA | 0x01 | AES MixColumns |
| 0x03 * 0xCA | 0x8D | AES MixColumns |
| 0xFF * 0xFF | 0x72 | Maximum values |

### Properties Verified

- Commutativity: `a * b = b * a`
- Identity: `a * 1 = a`
- Zero: `a * 0 = 0`
- Distributive: `a * (b + c) = (a * b) + (a * c)`
- Associative (addition): `(a + b) + c = a + (b + c)`

## Implementation Notes

### Algorithm: Shift-and-XOR (Peasant's Algorithm)

The multiplication algorithm is **fully unrolled** for synthesis efficiency:

```
For each bit i in b (0 to 7):
    1. If b[i] == 1: p = p XOR a_shifted
    2. Check if a_shifted[7] == 1 (overflow)
    3. Shift a_shifted left by 1
    4. If overflow: a_shifted = a_shifted XOR POLY
```

## References

1. **FIPS 197** - Advanced Encryption Standard (AES)
   - Section 4.2: Multiplication in GF(2^8)
   - <https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.197.pdf>

2. **Finite Field Arithmetic**
   - Introduction to Galois Fields for Cryptography
   - Primitive polynomials and irreducible polynomials

3. **BIW Extractor**
   - Barak-Impagliazzo-Wigderson randomness extractor
   - Uses GF(2^8) multiply-add as the extraction function

## Reference Model

### Overview

The `Entropy_Compressor_RefModel` implements the BIW (Barak-Impagliazzo-Wigderson) extractor for compressing 12 byte streams into a 32-bit word.

### Architecture

```
Input: 12 bytes [0..11] from decorrelator model
       ↓
Lane Masking (configurable per-lane enable)
       ↓
Grouping: 4 groups of 3 lanes each
  - Group 0: lanes [0, 4, 8]  → biw_byte[0] → word[31:24]
  - Group 1: lanes [1, 5, 9]  → biw_byte[1] → word[23:16]
  - Group 2: lanes [2, 6, 10] → biw_byte[2] → word[15:8]
  - Group 3: lanes [3, 7, 11] → biw_byte[3] → word[7:0]
       ↓
BIW Extraction: y[i] = (a[i] * b[i]) + c[i] in GF(2^8)
       ↓
Output: 32-bit compressed word
```

### Instantiation Example

```systemverilog
// Configuration interface
compressor_cfg_if cfg();

// Reference model
Entropy_Compressor_RefModel #(
    .N_LANES(12)
) u_compressor_refmodel (
    .clk_i  (apb.pclk),
    .rstn_i (apb.presetn),
    .bytes_i(entropy_bytes),     // [11:0][7:0] from decorrelator
    .vld_i  (entropy_bytes_vld),
    .cfg    (cfg.slave),
    .word_o (compressed_word),   // 32-bit output
    .vld_o  (compressed_vld)
);

// Configuration
initial begin
    cfg.enable    = 1'b1;
    cfg.bypass    = 1'b0;
    cfg.lane_mask = 12'hFFF;
    cfg.group_sel = 2'b00;
end
```

### Features

1. **Configurable Operation**
   - Enable/disable compression
   - Bypass mode for debug
   - Per-lane masking

2. **Debug Capabilities**
   - Group selection (0-3)
   - Expose intermediate values (a, b, c, y)
   - Show multiplication product before addition

3. **Quality Monitoring**
   - Sample counter
   - Zero output detection
   - Pattern repeat detection

4. **Pipeline**
   - One-cycle latency (registered output)
   - Valid signal follows input with enable check

### Timing

```
Cycle N:   bytes_i valid, vld_i asserted
           ↓ (combinational BIW extraction)
Cycle N+1: word_o updated, vld_o asserted
```

**Latency**: 1 cycle from input valid to output valid

### Verification Modes

Enable compile-time checking:

```systemverilog
// Define before including module
`define COMPRESSOR_ENABLE_CHECKS    // Enables assertions and warnings
`define COMPRESSOR_DEBUG            // Enables debug messages

`include "Entropy_Compressor_RefModel.sv"
```

**Checks include:**

- Zero output rate monitoring (warns if >1%)
- Pattern repeat monitoring (warns if >5%)
- Output activity checking
