# Scrambler

## Introduction

The `scrambler` module provides lightweight, combinational scrambling and
descrambling of SRAM data and addresses. Its primary purpose is to prevent
an attacker with physical access to the SRAM cells from reading meaningful
data by making each stored word appear to be random, unique to both its
contents and its storage address.

The data path implements a single round of the
[PRESENT](https://en.wikipedia.org/wiki/PRESENT) block cipher, adapted for
32-bit words. The address path applies an independent single-round substitution
and permutation so that logically adjacent addresses map to physically scattered
locations in the SRAM array.

The module is purely combinational — it has no clock or reset and introduces
zero pipeline stages. It is intended to be placed in the data and address paths
between the SRAM controller and the physical SRAM macro.

### Cipher Summary

| Path | Forward (write / scramble) | Inverse (read / descramble) |
|------|----------------------------|-----------------------------|
| Data | XOR round\_key → S-box → P-layer | Inverse P-layer → Inverse S-box → XOR round\_key |
| Address | XOR key → S-box → P-layer | — (one-way; stored directly) |

The round key is derived from `scrambler_key_i` XORed with a 32-bit expansion
of `addr_i`, binding each ciphertext uniquely to its address (address tweaking).

---

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ADDR_WIDTH` | `int unsigned` | 10 | Width of the SRAM address bus. Supported values: 6–13 (selects the corresponding `addr_scrambleN` function). Values outside this range pass the address through unchanged. |
| `DATA_WIDTH` | `int unsigned` | 32 | Width of the data bus. **Only 32-bit is supported.** |
| `BYTE_WISE` | `int unsigned` | 0 | Permutation layer mode. `0` = full 32-bit PRESENT permutation (`perm32`/`iperm32`). `1` = four independent 8-bit permutations (`perm8`/`iperm8`), preserving byte lane boundaries. |

### Supported SRAM Depths

The table below lists the convenience size-specific wrapper modules. Each
wraps `scrambler` with a fixed `ADDR_WIDTH`.

| Module | `ADDR_WIDTH` | SRAM depth |
|--------|-------------|------------|
| `scrambler_512x32` | 9 | 512 words |
| `scrambler_1024x32` | 10 | 1024 words |
| `scrambler_2048x32` | 11 | 2048 words |
| `scrambler_4096x32` | 12 | 4096 words |
| `scrambler_8192x32` | 13 | 8192 words |

For new designs, instantiate `scrambler` directly with the appropriate
`ADDR_WIDTH` rather than using a size-specific wrapper.

---

## Port List

| Port | Direction | Width | Description |
|------|-----------|-------|-------------|
| `addr_i` | input | `ADDR_WIDTH` | Logical SRAM read/write address. |
| `byte_mask_i` | input | `DATA_WIDTH/8` | Byte write enable mask. Reserved for future byte-masked write support; currently unused by the scrambler logic. |
| `scrambler_key_i` | input | 32 | Static secret key. The lower `ADDR_WIDTH` bits are also used as the address scramble key. |
| `scrambled_addr_o` | output | `ADDR_WIDTH` | Scrambled address to present to the physical SRAM. |
| `write_data_i` | input | `DATA_WIDTH` | Plaintext data to be written. |
| `scrambled_write_data_o` | output | `DATA_WIDTH` | Scrambled data to store in the physical SRAM. |
| `scrambled_read_data_i` | input | `DATA_WIDTH` | Scrambled data read from the physical SRAM. |
| `read_data_o` | output | `DATA_WIDTH` | Descrambled plaintext data returned to the SRAM controller. |

---

## Detailed Microarchitecture

The scrambler is composed of three sub-modules and a package of pure
functions (`scrambler_pkg`).

```
                    scrambler_key_i
                          │
              ┌───────────┴────────────┐
              │                        │
              ▼                        ▼
    ┌──────────────────┐   scrambler_key_i[ADDR_WIDTH-1:0]
    │ scrambler_addr_  │               │
    │     tweak        │               ▼
    │  (expand addr,   │   ┌─────────────────────────┐
    │   XOR with key)  │   │  addr_scrambleN(addr,key)│
    └────────┬─────────┘   └──────────┬──────────────┘
             │ round_key              │
             │                        ▼ scrambled_addr_o
             │
    ─────────┼─────────── Data Scramble Path ─────────────────
             │
    write_data_i
             │
             ▼
        XOR round_key
             │
             ▼
    sbox4 × 8 nibbles
             │
      BYTE_WISE==0 ──► perm32 ──► scrambled_write_data_o
      BYTE_WISE==1 ──► perm8×4 ─► scrambled_write_data_o

    ─────────┼─────────── Data Descramble Path ──────────────
             │
    scrambled_read_data_i
             │
      BYTE_WISE==0 ──► iperm32 ─┐
      BYTE_WISE==1 ──► iperm8×4 ┘
             │
             ▼
    ibox4 × 8 nibbles
             │
             ▼
        XOR round_key
             │
             ▼
         read_data_o
```

### scrambler\_pkg

A SystemVerilog package containing all cipher primitives as synthesizable
`automatic` functions.

#### Substitution Layer

- **`sbox4(d)`** — PRESENT 4-bit S-box. Applied to all 8 nibbles of the 32-bit
  data word on the scramble path.
- **`ibox4(d)`** — Inverse of `sbox4`. Applied on the descramble path.
- **`sbox3(d)`** — Pyjamask 3-bit S-box. Used by address scramble functions
  when the address width is not a multiple of 4.

#### Permutation Layer (data)

- **`perm32(d)`** — Full 32-bit PRESENT bit permutation. Used when
  `BYTE_WISE == 0`. Scatters bits across all four bytes.
- **`iperm32(d)`** — Inverse of `perm32`.
- **`perm8(d)`** — 8-bit permutation. Used when `BYTE_WISE == 1`. Applied
  independently to each byte, preserving byte lane boundaries for use with
  byte-masked SRAMs.
- **`iperm8(d)`** — Inverse of `perm8`.

#### Address Scramble Functions

`addr_scrambleN(addr, key)` for N ∈ {6, 7, 8, 9, 10, 11, 12, 13}.

Each function applies one round of: XOR with key → nibble S-boxes (mix of
`sbox3`/`sbox4` depending on width) → width-specific permutation (`permN`).
The permutation functions `permN` / `ipermN` are defined for N = 6–16.

#### Barrel Rotator (`rol6`–`rol16`)

Left-rotation functions used internally by address scramble functions. Each
constructs a 2× or 3× extended word (`{d,d}` or `{d,d,d}`) and shifts it
left by up to 4 stages (×1, ×2, ×4, ×8), returning the top `WIDTH` bits.
Functions with WIDTH ≤ 8 or WIDTH = 16 use a 2× extension; all others use 3×.

### scrambler\_addr\_tweak

Expands the N-bit address into a 32-bit value by repeating it, then XORs
with `scrambler_key_i` to produce the 32-bit `round_key`.

The expansion strategy for each supported width:

| `ADDR_WIDTH` | Expansion |
|---|---|
| 32 | direct |
| 16 | `{addr, addr}` |
| 8 | `{addr×4}` |
| 9 | `{addr, addr, addr, addr[8:4]}` — 9+9+9+5 = 32 |
| 10 | `{addr, addr, addr, addr[9:8]}` — 10+10+10+2 = 32 |
| 11 | `{addr, addr, addr[10:1]}` — 11+11+10 = 32 |
| 12 | `{addr, addr, addr[11:4]}` — 12+12+8 = 32 |
| 13 | `{addr, addr, addr[12:7]}` — 13+13+6 = 32 |
| other | zero-padded to 32 bits |

### scrambler\_rotator

A generic parameterized right-rotator used as a utility primitive. Doubles the
input (`{d, d}`) and shifts right by the rotation amount. For widths 9, 10,
and 12, the rotation amount is taken modulo the data width to handle
out-of-range values.

---

## Usage Example

### RTL Integration

The following shows how `scrambler` is connected between an SRAM controller
and a physical SRAM macro for a 1024-word × 32-bit SRAM with byte-lane write
support.

```systemverilog
module sram_ctrl_example (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [9:0]  addr_i,
    input  logic        wen_i,
    input  logic [3:0]  byte_en_i,
    input  logic [31:0] wdata_i,
    output logic [31:0] rdata_o,
    input  logic [31:0] scrambler_key_i
);

    // Scrambler wires
    logic [9:0]  scr_addr;
    logic [31:0] scr_wdata;
    logic [31:0] scr_rdata;

    scrambler #(
        .ADDR_WIDTH(10),
        .DATA_WIDTH(32),
        .BYTE_WISE (1)       // per-byte permutation for byte-masked writes
    ) u_scrambler (
        .addr_i                 (addr_i),
        .byte_mask_i            (byte_en_i),
        .scrambler_key_i        (scrambler_key_i),
        .scrambled_addr_o       (scr_addr),
        .write_data_i           (wdata_i),
        .scrambled_write_data_o (scr_wdata),
        .scrambled_read_data_i  (scr_rdata),
        .read_data_o            (rdata_o)
    );

    // Physical SRAM macro (synchronous, byte-write-enable)
    sram_1024x32 u_sram (
        .clk_i    (clk_i),
        .addr_i   (scr_addr),
        .wen_i    (wen_i),
        .wmask_i  (byte_en_i),
        .wdata_i  (scr_wdata),
        .rdata_o  (scr_rdata)
    );

endmodule
```

**Integration notes:**

- **Address**: connect `scrambled_addr_o` directly to the SRAM address input.
  Never present the logical address to the SRAM macro.
- **Write path**: connect `scrambled_write_data_o` to the SRAM write data input.
- **Read path**: connect the SRAM read data output to `scrambled_read_data_i`;
  read `read_data_o` for the plaintext.
- **Key**: `scrambler_key_i` should be loaded from a hardware fuse or OTP at
  boot and held stable. Changing the key invalidates all data currently stored
  in the SRAM.
- **Combinational latency**: the scrambler adds a combinational delay of
  approximately 3–4 logic levels (XOR + S-box + permutation). Verify timing
  closure in the SRAM read/write timing paths.
- **BYTE_WISE mode**: set `BYTE_WISE = 1` when the SRAM supports byte write
  enables. In this mode the permutation operates within each byte, so a
  byte-masked write to scrambled data does not corrupt adjacent bytes.
  Set `BYTE_WISE = 0` for word-only SRAMs to get stronger inter-byte diffusion.

---

### Verilator Simulation Tests

The `dv/` directory contains Verilator-based round-trip tests for all five
supported SRAM depths in both word-mode (`BYTE_WISE=0`) and byte-wise mode
(`BYTE_WISE=1`). The tests are purely combinational — no clock is needed.

#### Directory layout

```
dv/
  Makefile                         # build and run targets
  tb_scrambler_common.h            # shared C++ test template
  tests/
    tb_scrambler_1024x32.cpp       # BYTE_WISE=0 driver for 1024x32
    tb_scrambler_1024x32_bw.cpp    # BYTE_WISE=1 driver for 1024x32
    tb_scrambler_512x32.cpp        # ... and so on for 512, 2048, 4096, 8192
    ...
```

#### How the test works

Each driver instantiates the Verilator model of `scrambler_1024x32` and calls
`run_word_tests()` (or `run_bytewise_tests()` for byte-wise mode) from
`tb_scrambler_common.h`. That function models the physical SRAM as a C++
`std::vector<uint32_t>` and runs two phases:

**Phase 1 — ascending write then ascending read:**

```
for each address i = 0 .. 1023:
    drive addr_i = i,  write_data_i = lcg_rand()
    call eval()
    store scrambled_write_data_o into memory[scrambled_addr_o]

for each address i = 0 .. 1023:
    drive addr_i = i
    call eval()                          // compute scrambled_addr_o
    drive scrambled_read_data_i = memory[scrambled_addr_o]
    call eval()                          // compute read_data_o
    assert read_data_o == original write_data_i
```

**Phase 2 — descending write then descending read:**

Same structure but addresses traverse in reverse order and data is sequential
(`i`, `i-1`, …) to verify there is no order dependency in the scramble
functions.

The key is fixed at `0xDEADBEEF` for reproducibility. The LCG uses seed 42.
The first 10 write and read transactions are printed verbatim so the scrambled
address and data mappings are visible:

```
Write[  0]: addr=0x000->0x2C3  data=0x4099B181->0xA3F2E84D
Write[  1]: addr=0x001->0x1C4  data=0x168F5CEC->0x57B0A1F2
...
Read[  0]:  addr=0x000  out=0x4099B181  exp=0x4099B181  PASS
Read[  1]:  addr=0x001  out=0x168F5CEC  exp=0x168F5CEC  PASS
```

#### Running the tests

All commands are run from the `dv/` directory.

```bash
cd hw/ip/scrambler/dv
```

Build and run the 1024×32 word-mode test:

```bash
make run_1024
```

Build and run the 1024×32 byte-wise test:

```bash
make run_1024_bw
```

Run all five depths, both modes (10 tests total):

```bash
make run_all run_all_bw
```

Build all testbenches without running them:

```bash
make all
```

Expected output for a passing run:

```
========================================
Scrambler 1024x32  BYTE_WISE=0 Tests
Key: 0xDEADBEEF
========================================

--- Phase 1: Ascending ---
Write[  0]: addr=0x000->0x...  data=0x...->0x...
...
Phase 1 errors: 0/1024
*** PHASE 1 PASSED ***

--- Phase 2: Descending ---
Phase 2 errors: 0/1024
*** PHASE 2 PASSED ***

========================================
All Tests Complete - 1024x32  BYTE_WISE=0
Total Errors: 0/2048
*** ALL TESTS PASSED ***
========================================
```

A non-zero error count and `*** TESTS FAILED ***` indicates a scramble/
descramble mismatch. The first up to 10 failing addresses are printed with
their expected and actual values.
