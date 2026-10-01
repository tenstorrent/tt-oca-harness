# Running the SMC boot ROM on `smc-vp`

How to load the SMC production boot ROM
(`hw/sys/smc/bootrom/prod`) into the modeled boot ROM and run it on the
virtual platform — and, just as importantly, what you will and will not be
able to see once it runs.

Everything below was verified against `tt-oca-harness-model` at `416200e9`
on 2026-09-04.

---

## TL;DR

```bash
# 1. Build the ROM. It compiles against picolibc, which most host RISC-V
#    toolchains lack, so build it in the container.
./scripts/docker-run.sh run-here make -C hw/sys/smc/bootrom/prod

# 2. Copy the SMC ini and point it at the ROM image + reset vector.
cp virtual_platform/tt-oca-harness-model/vp/platform/smc/config/smc_platform_vp.ini my_rom.ini
#    ... then set, in the [string] and [uint] sections respectively:
#      dut.bootrom.init_file : <abs path>/hw/sys/smc/bootrom/prod/build/release/bin/prod_rom.bin
#      dut.cluster.reset_pc  : 0xC0040000

# 3. Run. argv[2] is mandatory but the ROM does not need it — see "The ELF
#    argument" below. Any ELF whose loadable segments stay inside fast mem
#    (0x80000000–0x90000000) will do.
smc-vp my_rom.ini some-fastmem.elf 20 --uart-live
```

`smc-vp` comes from `make -C virtual_platform smc-vp`; `make env` puts it on
`PATH`.

---

## Why this works: the pieces line up by design

| | Linker script (`linker/smc/smc_rom.ld`) | VP (`vp/platform/smc/src/smc_platform.cpp`) |
|---|---|---|
| ROM | `rom @ 0xc0040000`, 128 K | `A_BOOTROM = 0xC0040000`, window `0x20000` |
| RAM | `testram @ 0xc0060000`, 1 M | `A_SCRATCH = 0xC0060000`, window `0x100000` |

Exact matches, both base and size.

The 128 K ROM image is also **self-sufficient**: `.data` is placed
`>testram AT>rom`, i.e. its load address is in ROM and its run address is in
testram, with `metal_segment_data_source_start = LOADADDR(.data)`. The ROM's
own startup copies it across, and `.bss` is `NOLOAD`. So preloading the ROM
image is all the memory setup that is needed — you do **not** need the ELF
loaded anywhere.

---

## The two knobs that matter

### `dut.bootrom.init_file` — the ROM contents

The modeled boot ROM is a **read-only** memory preloaded at elaboration; writes
to it are ignored by design. It takes its contents from a CCI parameter:

```ini
[string]
dut.bootrom.init_file        : /abs/path/to/prod_rom.bin
dut.bootrom.init_file_format : auto
```

`auto` picks `bin` for `.img`/`.bin` filenames and `hex` otherwise, so the
`prod_rom.bin` the ROM build already emits works as-is. (`make -C
hw/sys/smc/bootrom/prod` also produces `.hex`, `.preload.hex`, `.ecc.hex` and
`.bin64` if you need a different format.)

Confirm it took effect — the model logs what it loaded:

```
Info: dut.bootrom: bootrom instantiated: size_bytes=131072,
      init_file="/.../prod_rom.bin", init_file_format=bin, access_delay_ns=1
```

If you see `init_file=""` and `init_file_format=hex`, your ini was not read at
all. `smc-vp` warns and continues in that case:
`WARNING: cannot open ini '...' (skipping)`.

### `dut.cluster.reset_pc` — where the harts start

```ini
[uint]
dut.cluster.reset_pc : 0xC0040000
```

`main.cpp` presets `reset_pc` from the ELF's `e_entry` and *then* applies the
ini — the comment in the source is literally "Defaults first, then ini
overrides" — so the ini wins. That is what lets you point the reset vector at
the ROM while passing an unrelated ELF.

---

## The ELF argument, and why you must not pass `prod_rom.elf`

`smc-vp <ini> <elf> [sim_time_ms] [--uart-live] [--uart-interactive]` requires
the ELF, and loads it unconditionally:

```cpp
// Load the firmware into the cluster's Whisper ISS (fast-mem backed).
if (!dut.cluster.load_elf({elf_path})) { ... }
```

**Fast-mem backed** is the operative phrase. Addresses inside
`[fast_mem_lo, fast_mem_hi)` = `[0x80000000, 0x90000000)` are written straight
into the ISS's own memory. Anything outside that goes out over TLM — and the
load happens *before* `sc_start()`, when the platform's routers are not yet
able to accept transactions. A ROM ELF's segments live at `0xC004xxxx` /
`0xC006xxxx`, so passing it aborts elaboration:

```
Error: /OSCI_TLM-2/multi_socket: dut.front_port_router.tgt:
  Call to b_transport without a registered callback for b_transport.
```

So pass something harmless. A three-instruction stub is enough:

```bash
printf '.section .text\n.globl _start\n_start:\n  nop\n' > stub.S
riscv64-unknown-elf-gcc -march=rv64imac_zicsr -mabi=lp64 \
  -nostdlib -nostartfiles -Wl,-z,max-page-size=0x1000 \
  -Wl,-Ttext=0x80010000 stub.S -o fastmem-stub.elf
```

Check it lands inside fast mem — `readelf -lW` should show a `LOAD` at
`0x8000f000` or similar, **not** below `0x80000000`:

```
readelf -lW fastmem-stub.elf | grep LOAD
```

(A default `-Ttext=0x80000000` puts the ELF headers in a page *below* the
segment, which falls outside fast mem.)

---

## Seeing what the ROM is doing

### The ROM has no UART console

`simputs()` / `simputshex*()` (`lib/src/virt_console.c`) do not touch a UART.
They pack ASCII or hex into a 32-bit word and write it to **cpu_ctrl
`SCRATCH[2]`** (`0xC0039090` = `SMC_SCRATCH_BASE_ADDR 0xC0039080` + `2 * 8`),
leaving a testbench to decode it. POST codes go the same way to `SCRATCH[1]`
(`0xC0039088`).

The wire format, for reference:

```
[31:8] payload   [7:4] reserved   [3:1] opcode   [0] duplicate-detect toggle

opcode 0 = ASCII : up to 3 bytes at [15:8],[23:16],[31:24], NUL-terminated
opcode 1 = HEX16 : 16-bit value at [23:8], as 4 lowercase hex digits
opcode 2 = DEC24 : 24-bit value at [31:8], as decimal
```

Bit 0 is flipped by the firmware when it re-sends an otherwise identical word;
it is not part of the opcode or payload.

The VP now decodes this and prints whole lines:

```
[SMC_VCONSOLE] <text>
```

It is on by default and can be turned off with `dut.cluster.vconsole_enable :
false` in the `[bool]` section. See "Model changes this needed" below.

A line with no trailing newline still appears — it is flushed when the cluster
is destroyed. (Not from `end_of_simulation()`: SystemC only calls that from
`sc_stop()`, which the ordinary time-limited run never reaches.)

### Prints are compiled out by default

`simputs` is a no-op unless `DEBUG` is defined. For a release ROM build, ask
for it explicitly:

```bash
./scripts/docker-run.sh run-here \
  make -C hw/sys/smc/bootrom/prod ENABLE_RELEASE_PRINTS=1 clean all
```

(`ENABLE_RELEASE_PRINTS=1` adds `-DDEBUG=1`. Plain `BUILD_TYPE=debug` defines
it too, but produces a much larger image.)

### Current status: the production ROM stays silent

With all of the above in place — image preloaded, reset vector at
`0xC0040000`, prints enabled, decoder working — the production ROM **runs to
completion with exit 0, no trap and no output**, out to a 200 ms window.

The decoder itself is known-good. Driven from ROM-resident code over the real
bus, each path behaves: ASCII-with-newline, HEX16, an unterminated line
appearing at flush, a *read* of `SCRATCH[2]` correctly not re-emitting, and
`vconsole_enable : false` emitting nothing. Separately, a ROM-resident program
that initialises UART0 and writes to it prints normally.

So the silence means the ROM is not reaching its first `simputs()`, rather than
that its output is being missed. Somewhere in early ROM init it stops making
progress. That is the open question; the console decoder is the tool for
chasing it.

If you want to reproduce the decoder check, the shape is: assemble a few `sw`
instructions to `0xC0039090` with the word encodings above, `objcopy -O binary`
it, and point `dut.bootrom.init_file` at the result.

---

## Gotchas worth knowing

**Use 32-bit MMIO accesses.** A byte store to a modeled peripheral does not
fault gracefully — it kills the process inside the ISS:

```
Hart.hpp:3268: void WdRiscv::Hart<URV>::memWrite(...):
  Assertion `0 && "Error: Assertion failed"' failed.
```

The test firmware's `REG_WRITE` is `uint32_t` for this reason, and the ROM's
`write_scratch()` is a `volatile uint32_t *` store.

**UART0 needs initialising before TX.** `sw/smc-vp-tests/common/start.S` does
it in `uart_init` (8N1, divisor 1) before `main`. Skipping it gives you a
silent UART, or a hang if you poll `LSR.THRE`:

```asm
li t0, 0xC0006100
li t1, 0x80    ; sw t1, 0x0C(t0)   # LCR: DLAB=1
li t1, 0x01    ; sw t1, 0x00(t0)   # DLL = 1
sw zero, 0x04(t0)                  # DLM = 0  -> divisor 1
li t1, 0x03    ; sw t1, 0x0C(t0)   # LCR: 8N1, DLAB=0
```

**Park the other harts.** The cluster runs four harts, all from the same reset
vector. Test firmware gates on `mhartid` and spins the rest in `wfi`; without
that, four copies of your output interleave.

**Keep the ini inside the repo if you use the container.**
`docker-run.sh run-here` bind-mounts only the repository, so an ini under
`/tmp` or a scratch directory is invisible inside the container and you get
`WARNING: cannot open ini`. Either keep it in the tree or use a natively built
`smc-vp`.

**`smu-vp` takes two inis and its own ELFs** — it is a different invocation
(`smu-vp <smc-ini> <smc-elf> <sep-ini> <sep-elf> [ms]`); none of the above has
been tried through it.

---

## Model changes this needed

Both are in the `tt-oca-harness-model` submodule, on branch
`smc/scratch-console-and-offset`, and need their own PR there — they are not
part of the harness repo.

1. **The virtual-console decoder**, added to the SMC CPU cluster's ctrl block
   (`smc/cpu_cluster`), gated on the new `vconsole_enable` CCI parameter. It
   reuses the decoder the SEP already had for the identical protocol, which
   moved from `sep/peripherals/sep_scratch_cold/include/` to the shared
   `common/include/` so the two cannot drift.

   It went into the *cluster*, not the `cpu_ctrl` peripheral model, because
   `vp/platform/smc` routes the `0xC0039000` control window to
   `cluster.ctrl` and binds the `cpu_ctrl` module's socket to an idle
   initiator — that model is not on the bus in `smc-vp` at all, and keeps
   only its WDT sideband.

2. **`cpu_ctrl`'s whole offset table**, aligned to `cpu_ctrl.rdl`. Nine
   registers were in the wrong place — `SCRATCH` at `0x100` (where the rdl
   puts `WB_PC_CORE0`), `TEST_CTRL` at `0x200` (`SMC_ATTRIBUTES`), the entire
   generic space at `0x1000` — and `RESET_TIMEOUT` was missing. None of it
   affects the ROM path, since that model is not on the bus, but the rdl, the
   production ROM and the cluster's own ctrl block all agree against it.

   Six registers have no rdl counterpart at all (`GLOBAL_BASE`, `LOCAL_BASE`,
   `REGION_SIZE`, `DEBUG_CTRL`, `DEBUG_BUS_MUX`, `CLOCK_GATE_CONTROL`); they
   were interleaved with the real ones, which is what displaced the map. They
   are preserved but moved into one block above the rdl's highest register, so
   the list says plainly which half is RTL-backed. Whether they belong there
   at all is for the block owner to decide.

   The reason this drifted unnoticed is worth knowing if you touch that model:
   every case in its testbench addresses registers through the `OFF_*` symbols,
   so the suite passes for *any* self-consistent map. It now also has an "rdl
   offset conformance" case that restates every offset as a literal.

There is also one harness-side fix (`virtual_platform/Makefile`): the SMC/SMU
build recipes now export `WHISPER_HOME`/`BOOST_DIR`, not just the configure
step. CMake re-runs its own configure during a build whenever any
`CMakeLists.txt` in the tree changes — a model uprev, or an edit to any of the
~20 peripherals it pulls in — and that re-configure inherits the build step's
environment. Without those variables the smc/smu platforms are silently
skipped and the next build fails with `No rule to make target 'smc-vp'`.
`make smc-clean` recovers a tree already in that state.

---

## Reference

| Thing | Where |
|---|---|
| ROM sources / build | `hw/sys/smc/bootrom/prod` (`README.adoc`, `Makefile`) |
| ROM memory layout | `hw/sys/smc/bootrom/prod/linker/smc/smc_rom.ld` |
| ROM scratch/console addresses | `hw/sys/smc/bootrom/prod/include/smc_rom_defs.h`, `lib/src/virt_console.c` |
| Authoritative cpu_ctrl map | `hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl` |
| VP address map | `…/vp/platform/smc/src/smc_platform.cpp` (`A_*` constants, `add_route` calls) |
| VP CLI + ini handling | `…/vp/platform/smc/main.cpp` |
| Default SMC ini | `…/vp/platform/smc/config/smc_platform_vp.ini` |
| Boot ROM model | `…/smc/peripherals/bootrom/include/bootrom.h` |
| Console decoder | `…/common/include/virt_console_decoder.h` |
| Building the VPs | `virtual_platform/README.md`, `make -C virtual_platform help` |
