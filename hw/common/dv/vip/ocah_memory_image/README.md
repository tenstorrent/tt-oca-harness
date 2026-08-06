# ocah_memory_image — SEP Memory Image Loader

> **This is a behavioral VIP.  It has no silicon-accuracy claims.**

`ocah_memory_image` is a cocotb VIP package that provides a single Python API
for loading firmware, ROM, SRAM, and OTBN images into SEP-style memory banks.
Tests do not need per-bank backdoor knowledge — they call one loader and the
loader routes ELF sections (or explicit hex/binary files) into the correct
banks, then emits `+<bank>_preload=<file>` plusargs for the active testbench.

## Supported Image Formats

| Format | Method | ELF routing? | Notes |
|---|---|---|---|
| ELF (RISC-V 32/64-bit, LE) | `load_elf(path)` | Yes, by PT_LOAD paddr | Requires `pyelftools` |
| OCAH hex (Task #9 format) | `load_hex(bank, path)` | No (explicit bank) | Pure stdlib |
| Intel HEX (objcopy `-O ihex`) | `load_ihex(bank, path)` | No (resolved by address) | Pure stdlib |
| Raw binary | `load_bin(bank, path, base_offset=0)` | No (explicit bank) | Pure stdlib |

Mach-O, PE, and COFF are out of scope.  ECC / parity encoding is out of
scope — ECC bits are emitted as zero unless the caller pre-encodes them.

## SEP Memory Banks

| Bank name | Plusarg | Base addr | Size | Word width |
|---|---|---|---|---|
| `sep_sram` | `+sep_sram_preload` | `0x2000_0000` | 256 KB | 64-bit |
| `sep_boot_rom` | `+sep_boot_rom_preload` | `0x0000_0000` | 128 KB | 64-bit |
| `sep_tcm` | `+sep_tcm_preload` | `0x4000_0000` | 256 KB | 39-bit |
| `km_rom` | `+km_rom_preload` | (not CPU-mapped) | 16 KB data | 36-bit |
| `km_sram` | `+km_sram_preload` | (not CPU-mapped) | 16 KB data | 36-bit |
| `otbn_imem` | `+otbn_imem_preload` | (not CPU-mapped) | 16 KB data | 39-bit |
| `otbn_dmem` | `+otbn_dmem_preload` | (not CPU-mapped) | 32 KB data | 312-bit |

Bases shown are defaults from `SepMemoryLayout.default()`.  Override with a
custom YAML layout if your chip's address decoder differs.

## Hex File Format

All emitted hex files follow the Task #9 INTERFACE.md format:

- One word per line, most-significant nibble first.
- Line N loads word address N (0-indexed).
- Comment lines begin with `#`; blank lines are skipped.
- If the file is shorter than the bank depth, remaining entries default to zero
  (handled by the RTL shim, not this Python code).

Digit counts per word:

| Bank | Word width | Hex digits/line |
|---|---|---|
| SEP SRAM, SEP Boot ROM | 64-bit | 16 |
| SEP TCM, OTBN IMEM | 39-bit | 10 |
| KM ROM, KM SRAM | 36-bit | 9 |
| OTBN DMEM | 312-bit | 78 |

## ELF Section Routing

`load_elf()` iterates PT_LOAD segments and uses each segment's *physical
address* (p_paddr; falls back to p_vaddr if p_paddr is zero) to find the
matching bank by address window.

Typical SEP firmware layout:

```
PT_LOAD paddr=0x0000_0000  → sep_boot_rom  (.text / boot ROM image)
PT_LOAD paddr=0x2000_0000  → sep_sram      (.data / .rodata / .bss)
```

Segments whose physical address falls outside all bank windows are logged at
WARNING level and skipped.

## Plusargs

In addition to the per-bank `+<bank>_preload=<file>` plusargs emitted by
`write_plusargs()`, two optional plusargs are documented here for tests that
want higher-level control:

| Plusarg | Effect |
|---|---|
| `+sep_image=<elf>` | Shorthand: equivalent to calling `OcahMemoryImage().load_elf(<elf>)` followed by `write_plusargs()`.  Not emitted by this class — provided as a convention for TB-level wrappers that parse plusargs themselves. |
| `+sep_image_map=<yaml>` | Path to a custom `SepMemoryLayout` YAML file.  Not parsed by this class directly; pass to `SepMemoryLayout.from_yaml()` before constructing `OcahMemoryImage`. |

## Public API

### `OcahMemoryImage(layout=None, run_dir=None)`

Construct a loader.

- `layout` — `SepMemoryLayout` instance; defaults to `SepMemoryLayout.default()`.
- `run_dir` — directory where hex files are written by `write_plusargs()`;
  defaults to the current working directory.

### `load_elf(path)`

Parse an ELF file and route PT_LOAD segments to banks by physical address.
Requires `pyelftools`.

### `load_hex(bank: str, path: str)`

Load a bank from an OCAH hex file (Task #9 format).

### `load_ihex(bank: str, path: str)`

Load a bank from an Intel HEX file.  Resolves each record's absolute address
against the bank's `base_addr`.  Banks without a CPU base address
(KM ROM/SRAM, OTBN IMEM/DMEM) cannot be loaded via this method; use
`load_hex()` or `load_bin()` instead.

### `load_bin(bank: str, path: str, base_offset: int = 0)`

Load a bank from a raw binary file, starting at `base_offset` bytes within
the bank.

### `backdoor_write(bank: str, addr: int, data: int)`

Patch a single word in the Python-side image store *before* `write_plusargs()`
is called.  Use this to inject test-specific values without rebuilding
firmware.

### `write_plusargs(run_dir=None) -> list[str]`

Write per-bank hex files to `run_dir` (or the directory passed at
construction) and return the corresponding `+<bank>_preload=<path>` argument
strings.  Banks with no data loaded are skipped.

### `get_bank_content(bank: str) -> list[int]`

Return a copy of the word array for a bank (None entries become 0).

### `is_bank_loaded(bank: str) -> bool`

Return True if at least one word has been loaded into the bank.

### `backdoor_sim_write(dut_handle, bank, word_addr, word_data, layout=None)` (async)

Poke a word into a live simulation memory array via a cocotb hierarchical
handle.  This is a coroutine defined at the module level (import it from
`ocah_memory_image`).

The testbench must expose each bank's backing array as a hierarchical handle.
The expected paths are:

| Bank | TB handle path |
|---|---|
| `sep_sram` | `u_sep_ip_integration.u_sep_sram.mem` |
| `sep_boot_rom` | `u_sep_ip_integration.u_sep_boot_rom.mem` |
| `sep_tcm` | `u_sep_ip_integration.u_sep_tcm_wrapper.iccm_bank0.mem` |
| `km_rom` | `u_sep_ip_integration.u_km_rom.mem` |
| `km_sram` | `u_sep_ip_integration.u_km_sram.mem` |
| `otbn_imem` | `u_sep_ip_integration.u_otbn_imem_sram.mem` |
| `otbn_dmem` | `u_sep_ip_integration.u_otbn_dmem_sram.mem` |

Adjust the `_BACKDOOR_HANDLE_MAP` dict in `ocah_memory_image.py` if your TB
uses different paths.  Verilator requires `--public-flat-rw` for
hierarchical array access.

### `SepMemoryLayout.default() -> SepMemoryLayout`

Return the canonical seven-bank SEP layout from Task #9 INTERFACE.md.

### `SepMemoryLayout.from_yaml(path: str) -> SepMemoryLayout`

Load a custom layout from a YAML file.  See `examples/example_layout.yaml`
for the schema.  Requires `pyyaml`.

## Quick-Start Examples

### Load an ELF and run

```python
from ocah_memory_image import OcahMemoryImage

img = OcahMemoryImage(run_dir=sim_run_dir)
img.load_elf("fw/sep/tests/hello_world/hello_world.elf")
plusargs = img.write_plusargs()
# Pass plusargs to cocotb runner or simulator command line.
```

### Load banks from hex files

```python
img = OcahMemoryImage(run_dir=sim_run_dir)
img.load_hex("sep_boot_rom", "fw/sep/build/sep_boot_rom.hex")
img.load_hex("sep_sram",     "fw/sep/tests/hello_world/hello_world.hex")
img.load_hex("km_rom",       "hw/ip/key_manager/dv/fw/build/tests/rom_main/rom_main.rom.hex")
plusargs = img.write_plusargs()
```

### Patch a word before simulation

```python
img = OcahMemoryImage(run_dir=sim_run_dir)
img.load_elf("fw/sep/tests/crypto_test/crypto_test.elf")
img.backdoor_write("sep_sram", addr=0x100, data=0xDEAD_BEEF_CAFE_BABE)
plusargs = img.write_plusargs()
```

### Use a custom layout

```python
from ocah_memory_image import OcahMemoryImage, SepMemoryLayout

layout   = SepMemoryLayout.from_yaml("my_chip_layout.yaml")
img      = OcahMemoryImage(layout=layout, run_dir=sim_run_dir)
img.load_elf("fw/sep/tests/hello_world/hello_world.elf")
plusargs = img.write_plusargs()
```

See `examples/example_load_elf.py` for a complete set of usage patterns.

## Dependencies

| Package | Required for | Install |
|---|---|---|
| Python stdlib only | hex / binary loading, Intel HEX, plusarg emission | (built-in) |
| `pyelftools` | `load_elf()` | `pip install pyelftools` |
| `pyyaml` | `SepMemoryLayout.from_yaml()` | `pip install pyyaml` (optional) |
| `cocotb` | `backdoor_sim_write()` | project cocotb environment |

## Design Notes and Assumptions

1. **ELF physical address routing.** The loader uses p_paddr for placement
   because embedded RISC-V firmware typically places .text at the ROM physical
   address.  If your linker script maps p_paddr differently from p_vaddr,
   adjust the `load_elf()` logic or pre-split the ELF sections manually.

2. **Wide-word ECC / parity.** For 36-bit (KM ROM/SRAM) and 39-bit
   (TCM/OTBN IMEM) words, the data portion is 32 bits.  The upper ECC/parity
   bits are zero-filled.  Pre-encode ECC before loading if the DUT checks it.
   OTBN DMEM 312-bit words are packed as 8 × 32-bit data sub-words; ECC
   sub-fields are zero.

3. **Endianness.** Raw bytes are packed into words little-endian (matches
   RISC-V ABI).  The hex output is big-endian (MSN first) as required by
   INTERFACE.md.

4. **Determinism.** All outputs are deterministic; there is no random padding.
   Unwritten words are emitted as zero.  Trailing all-zero lines are omitted
   from hex files for compactness; the RTL shim zero-initialises missing lines.

5. **Address map defaults.** The `SepMemoryLayout.default()` base addresses
   are illustrative values derived from the OSS documentation.  The
   authoritative map is in the SEP top-level RTL address decoder.  Use a
   custom YAML layout if your chip differs.

6. **`backdoor_sim_write` handle paths.** The hierarchical handle paths in
   `_BACKDOOR_HANDLE_MAP` are placeholders that match the naming conventions
   in the Task #9 RTL shims.  They will need adjustment if the actual TB
   instantiation depth or naming differs.

## TODOs

- ECC pre-encoding hooks (for DUTs that check ECC syndromes).
- DCCM and multi-bank TCM preload (currently only ICCM bank 0 is loaded via
  `+sep_tcm_preload`; see Task #9 INTERFACE.md open issues).
- Verify and update `_BACKDOOR_HANDLE_MAP` paths once the SEP TB hierarchy
  is finalised.
- Add a `dump_hex(bank, path)` method for post-simulation memory dumps.

## Related Documents

- This package's `SepMemoryLayout.default()` values document the default bank
  windows used by the loader.
- `examples/example_load_elf.py` — usage patterns.
- `examples/example_layout.yaml` — custom layout YAML template.
