<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
-->

# ocah_regwalk — register model and access classifier

One representation of a register space for the generic register walks (reset
compare, bit bash, field sweep, dead-space decode), read from the generated
Python header `hw/<sys|ip>/<block>/regs/gen/py/<top>_reg.py` that
`tools/regs/rdlpyhdr.py` emits. The header carries addresses, the register type
of every instance and the full field contract, so a walk joins an address to
its fields through `<INST>_REG_TYPE` and never rebuilds a symbol name or parses
IP-XACT.

**Maturity: Experimental.** No DUT walk consumes it yet. It is promoted when
the SEP bit-bash and dead-space walks and the SMC RDL sweeps source their
inventory from it and their regressions gate it.

## Public API

```python
from ocah_regwalk import ExclusionSet, load_model, reg_masks, reset_reason, word_view, write_reason

model = load_model("hw/sys/sep/regs/gen/py/sep_reg.py")   # or an imported module
reg = model.by_symbol("SEP_CPU_CTRL_SEP_NMI_VEC")
masks = reg_masks(reg)                                     # RegMasks over the full width
word = word_view(reg, 0)                                   # the 32-bit bus word
```

| Member | Contract |
|---|---|
| `load_model(module_or_path) -> RegModel` | Reads every window, type and instance; raises when an instance has no `_REG_TYPE` or a type has no `_REG_FIELDS` / `_REG_WIDTH` |
| `RegModel.blocks`, `.regfiles`, `.mems`, `.windows` | `Window(name, base, size, kind)` from the `_REG_MAP_`, `_REG_FILE_` and `_MEM_` symbols; `.top` is the addrmap holding everything |
| `RegModel.registers` | Every `RegInst`, by address then symbol |
| `.by_symbol(sym)`, `.by_addr(addr)`, `.at(addr)` | Lookup by the register's base word; `by_addr` raises when two instances share an address (an I3C write port and read port do), `at` returns them all. The upper words of a 64/128/256-bit register are not keys here: `word_view` gives their addresses |
| `.under(prefix)`, `.array_count(prefix)` | Instances whose symbol starts at `prefix`; the count of `<prefix>_<n>_` windows or instances, contiguous from 0 |
| `RegInst(block, name, symbol, type_name, addr, offset, width, index, fields)` | `block` is the innermost addrmap whose name prefixes the symbol and whose range holds the address; `name` is the rest; `index` is a trailing `_<n>_`; `.base_name`, `.reset`, `.words`, `.field(name)` |
| `FieldSpec` | The ten-field `_REG_FIELDS` record: name, lsb, msb, sw, hw, onwrite, onread, singlepulse, volatile, reset (`None` when not a constant) |
| `classify_field(f) -> frozenset[FieldClass]` | `RO`/`RW`/`WO`/`WRITE_ONCE` from `sw`; `W1C`, `W1S`, `W0C`, `W0S`, `WSET`, `WCLR`, `WOT`, `WZT`, `WUSER` from `onwrite`; `RC`, `RS`, `RUSER` from `onread`; `PULSE`, `HW_DRIVEN` (volatile), `UNRESET` |
| `reg_masks(reg) -> RegMasks` | `storage`, `sw_usable`, `plain_rw`, `static_reset`, `unreset`, `reserved`, `unimplemented`, `write_destructive`, `read_destructive` |
| `word_view(reg, word) -> WordView` | Address, reset and masks of one 32-bit word of a wider register |
| `reset_reason(reg)`, `write_reason(reg, mask=None, require_reset=True)` | RDL-derived reasons a reset compare or a write/readback proves nothing, or `None` |
| `ExclusionSet(named=, name_suffix=, name_prefix=, name_substring=, block_prefix=)` | Hand-named exclusions, each with a reason; `.reason(reg)`, `.account(inventory, *reason_fns, admitted=, strict=)`, `.tally()` |

`sw_usable` leaves out fields named `rsvd`, `rsvd0`, `rsvd_0`, `reserved`,
`RESERVED_7_3` and the like (`RESERVED_NAME`), case-insensitively, and fields
with `sw = na`. `reserved` is the storage those fields hold; `unimplemented` is
the bits no field occupies, which read as zero. `plain_rw` is `sw = rw` with no
`onwrite`, `onread`, `singlepulse` or `volatile`; `static_reset` is readable,
non-volatile and constant-reset.

`reset_reason` has three arms: no readable field; `sw = r` throughout with no
declared reset; no storage bit with a constant reset. A volatile field is not
an arm, because its reset value is still what a read returns before hardware
moves it; `static_reset` names the bits a walk may pin without that
reservation. `write_reason` adds: no software-usable bit; no writable field
under the mask; then the first field under the mask that is read-only,
write-modified, read-modified, `singlepulse` or volatile. A walk that writes
only `plain_rw` bits passes that mask. The reset arms apply to a write too,
so plain storage with no declared reset is refused by default; a walk that
proves write/readback on such storage passes `require_reset=False`, which
keeps only the no-readable-field arm.

`ExclusionSet.account` consults the reason functions first, then the named
entries. It raises when a register has no reason and is not admitted, when an
admitted register carries a reason, when an admitted symbol is not in the
inventory, and (with `strict`) when a named entry matches nothing.

## What the header states, and what it does not

Derived from the header alone:

- every address window (addrmap, regfile, memory) with base and size, where
  size is the RDL node size, which ends at the last register;
- every register instance, its type, width, fields and assembled reset;
- the element count and stride of an array of blocks or registers, from the
  `_<n>_` symbols (`array_count`, and the instances' addresses);
- every access class above, and the reset and write reasons.

Not in the header, so a walk takes it from elsewhere or names it by hand:

- the decode window of a block when it is wider than the RDL node size (the
  fabric's, not the RDL's);
- the `_NUM` / `_STRIDE` / `_TOTAL_SIZE` macros of the C address header; the
  same geometry follows from the indexed symbols, but a walk that cross-checks
  the two generated views still reads the C header;
- the base address a leaf-IP header (`entropy_source_reg.py`, the OpenTitan
  overlays) has inside a subsystem; its windows start at 0 and the subsystem
  header's `<IP>_REG_MAP_BASE_ADDR` places them;
- whether a `None` reset means no reset at all or a reset taken from a signal,
  field or property reference; both read as `UNRESET`;
- the `external` register property, field encodings (an enumerated field that
  sanitizes an unsupported value), and every side effect past the register's
  own storage: fabric remaps, filter windows, locks, FIFO ports, OTP triggers,
  shadowed registers, clock-gate ordering. These stay `ExclusionSet` entries
  with a reason;
- which registers share a type that the RDL instantiates several times; the
  header binds each instance to its type, but says nothing about the others;
- whether a walk may prove write/readback on plain storage that has no
  declared reset. `write_reason` refuses it unless `require_reset=False`,
  because a reset compare on the same bits is a placeholder compare; the SMC
  field sweep proves such registers today and keeps them by passing the flag.

## Tests

```bash
uv run --locked --group dv python -m unittest discover -s hw/common/dv/vip/ocah_regwalk/tests
```

`tests/fixture_reg.py` is a hand-written header covering every field class and
every reason arm. `tests/test_inventory.py` loads the committed SMC and SEP
headers, checks the model's register count against the header's `_REG_ADDR`
symbols and every `_REG_DEFAULT`, and reproduces the SEP partition
`hw/sys/sep/dv/cocotb/env/sep_reg_meta.py` prints (export, inventory,
nometa), stating why the model binds every instance where that walk binds
fewer.
