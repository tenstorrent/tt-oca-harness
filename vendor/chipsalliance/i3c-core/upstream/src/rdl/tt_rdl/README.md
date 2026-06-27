# tt_rdl — Tenstorrent-Modified I3C Register Definitions

This directory contains a modified copy of the upstream i3c-core RDL files
(`src/rdl/`), with changes tailored for the Tenstorrent OCAH integration.
Three new files are also added here that do not exist upstream.

---

## Changes from Upstream (`src/rdl/`)

### `registers.rdl` — Address map and memory restructuring

| Parameter / Field | Upstream | tt_rdl | Reason |
|---|---|---|---|
| `DAT_offset` | `0x400` | `0x300` | Tighter address packing |
| `DCT_offset` | `0x800` | `0x400` | Follows DAT shrink |
| `ADDR_WIDTH` | `12` | `11` | Matches reduced address space |
| `DAT_MEMORY` entries | `128` | `16` | Reflects actual DAT depth |
| `dct_depth` comment | (none) | expanded | Clarifies 16 logical entries × 128-bit = 32 × 64-bit accesses |
| `dat_depth` comment | (none) | expanded | Clarifies 16 logical entries × 64-bit each |

The DCT memory definition was also restructured to use 64-bit accesses
(32 entries) instead of a single 128-bit-wide 16-entry memory.  Each
logical DCT entry N maps to addresses N×2 (low half) and N×2+1 (high
half).  This is required for compatibility with the PeakRDL Python
toolchain, which does not support 128-bit `memwidth`.

```
// Before (upstream)
mem {
    mementries = 16;
    memwidth = 128;
    sw = rw;
    DCT_structure DCT_MEMORY [128];
} external DCT @ DCT_offset;

// After (tt_rdl)
mem {
    desc = "DCT split into 64-bit halves for Python tool compatibility.
            Each logical entry N uses addresses N*2 (low) and N*2+1 (high).";
    mementries = 32;   // 16 entries × 2 (low + high halves)
    memwidth = 64;     // 64-bit accesses
    sw = rw;
} external DCT @ DCT_offset;
```

---

### `base_registers.rdl` — Parameterised DAT offset reset value

In the `DAT_SECTION_OFFSET` register, the `TABLE_OFFSET` field reset value
was changed from a hard-coded literal to the `DAT_offset` address-map
parameter so it stays consistent when `DAT_offset` is overridden.

```
// Before (upstream)
reset = 12'h400;

// After (tt_rdl)
reset = DAT_offset;
```

---

### `soc_management_interface.rdl` — Timing register field width reduction

All I3C timing parameter registers had their field widths reduced from
20 bits (`[19:0]`) to 8 bits (`[7:0]`).  This matches the actual
hardware counter widths used in the Tenstorrent integration and avoids
synthesising unused register bits.

Affected registers (T_R, T_F, T_SU_DAT, T_HD_DAT, T_HIGH, T_LOW,
T_HD_STA, T_SU_STA, T_SU_STO, T_R_PP, T_F_PP, T_HIGH_PP, T_LOW_PP,
T_SU_PP, T_HD_PP, T_CASR, T_CBSR):

```
// Before (upstream)
} T_R[19:0];

// After (tt_rdl)
} T_R[7:0];
```

---

## Files Not Present Upstream

| File | Description |
|---|---|
| `generate_register_files.sh` | Shell script that regenerates RTL from this RDL set (see below) |
| `scripts/rdl_post_process.py` | Python post-processor: converts unpacked arrays/structs to packed form and inserts `i3c_sva.svh` assertion includes |
| `README.md` | This file |

The upstream file `oca_i3c_wrap.rdl` is intentionally omitted from this
directory; the Tenstorrent wrapper uses `registers.rdl` as the top-level
address map instead.

---

## Regenerating RTL from RDL

After editing any `.rdl` file in this directory, run the generation
script to produce updated SystemVerilog:

```bash
# From this directory (src/rdl/tt_rdl/)
OCH_ROOT=/path/to/tt-oca-hw source generate_register_files.sh
```

The script:

1. Validates that `OCH_ROOT` points to the `tt-oca-hw` repository root
   (needed to locate `tools/reg_flow/regblock_udps.rdl`).
2. Invokes `peakrdl regblock` on `registers.rdl` with:
   - `--cpuif passthrough` — generates `s_cpuif_*` ports that match the
     `i3c.sv` module interface.
   - `--default-reset rst` — aligns the port name with the original
     I3CCSR interface (actual reset logic uses `hwif_in.rst_ni`).
   - `--type-style hier` — preserves the original i3c-core type naming.
3. Post-processes the generated files with
   `scripts/rdl_post_process.py` to convert any unpacked struct/array
   syntax to packed form (required for synthesis) and to add the
   `i3c_sva.svh` assertion include.

**Output files** are written to `src/csr/` (two levels up from this directory):

- `src/csr/I3CCSR.sv` — generated register block RTL
- `src/csr/I3CCSR_pkg.sv` — generated package with type definitions
