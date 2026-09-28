# tt-oca-harness-model: issues blocking the SEP VP

Independent defects in the SystemC model, found while integrating the virtual platform into
`tt-oca-harness` (PR #2065). Issue 1 is fixed; **issue 2 is the live blocker** -- it stops
every VP boot test -- and issue 3 is queued, arriving only when `origin/main` is next merged
into the VP branch. Further regressions are being found separately, so this is the VP-facing
subset rather than a complete inventory.

| # | issue | effect |
|---|---|---|
| 1 | eFuse 0x174 is `SYSCLK_FREQ_MHZ`, not `SEP_SPI_CTRL_FIELD_EN` | **FIXED** by model `a9d9da50`; `test_efuse_map_drift` green |
| 2 | Cold scratch is cleared only at construction, not on reset | every ROM boot hangs at the warm-reset check; 58 of 86 VP tests fail |
| 3 | SPI controller models the deleted forked spi_host | not yet hit; breaks the SPI boot path on the next main merge |

---

# Issue 1 -- eFuse 0x174 is SYSCLK_FREQ_MHZ, not SEP_SPI_CTRL_FIELD_EN

**Target repo:** `tenstorrent/tt-oca-harness-model` — the SystemC functional model.
**Not** `tt-oca-harness`, which only consumes it as a submodule.

**Pinned at:** `4580db79` (`Merge pull request #226 from tenstorrent/feat/align-vp-maps-to-rtl`,
2026-09-18), the current tip of the model's `main`.

**Found by:** `virtual_platform/tests/test_efuse_map_drift.py` in `tt-oca-harness`, on
branch `inmcm/integrate_virtual_platform` (PR #2065), after merging `origin/main`.

```
FAILED tests/test_efuse_map_drift.py::test_every_rdl_register_exists_in_the_model
  registers in the RDL with no counterpart in the VP eFuse model:
      SYSCLK_FREQ_MHZ (0x174)
```

PR #226 realigned the whole eFuse map and fixed a wholesale offset drift. This one
register did not come with it.

---

## 1. The disagreement

Both trees put something at eFuse offset **0x174**, and they disagree on what.

| | name at 0x174 | fields |
|---|---|---|
| **RDL** (authority) | `SYSCLK_FREQ_MHZ` | `sysclk_freq_mhz[10:0]`, `rsvd[31:11]` |
| **model** | `SEP_SPI_CTRL_FIELD_EN` | `spi_control_field_en[7:0]`, `smu_pll_sysclk[18:8]`, `spi_control_field_en_rsvd[31:19]` |

The RDL is `hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl` in `tt-oca-harness`:

```systemrdl
reg SYSCLK_FREQ_MHZ {                              // line 817
    regwidth = 32; accesswidth = 32;
    field { sw = r; hw = rw;
        desc = "Configured sysclk PLL frequency in MHz; ignored if 0. Consumed by boot ROM clock math.";
    } sysclk_freq_mhz[10:0] = 0x0;
    field { sw = r; hw = rw; desc = "Reserved"; } rsvd[31:11] = 0x0;
};
...
ROM_CTL          ROM_CTL          @0x170;          // line 962
SYSCLK_FREQ_MHZ  SYSCLK_FREQ_MHZ  @0x174;          // line 963
CHIPLET_PUBK_HASH CHIPLET_PUBK_HASH0 @0x178;       // line 964
```

Lock bits are `SYSCLK_FREQ_MHZ_WRITE_LOCK[36]` and `SYSCLK_FREQ_MHZ_READ_LOCK[37]`
(RDL lines 284, 291).

The model's version is `sep/peripherals/efuse/include/efuse_register.h`, whose own comment
records the rename and declines it:

```c
// RTL SYSCLK_FREQ_MHZ @0x174. Kept under the existing software name.
static constexpr unsigned int SEP_SPI_CTRL_FIELD_EN_OFFSET  = 0x174;   // line 52
```

**The RDL is authoritative.** The boot ROM is compiled against the header generated from it
(`hw/sys/sep/regs/gen/c/sep_addr.h`), so silicon and ROM both use the RDL's layout.

## 2. Why it matters — it is a bit-position bug, not a naming one

`hw/sys/sep/bootrom/prod/src/pll_init.c:35` reads the register and takes **bits [10:0]** as
the PLL frequency in MHz:

```c
uint32_t sysclk_fuse = mmio_read32(OCH_SEP_TOP_SEP_EFUSE_MAP_SYSCLK_FREQ_MHZ_BASE_ADDR);
uint16_t pll_freq_mhz =
    (uint16_t)((sysclk_fuse & SEP_EFUSE_MAP__SYSCLK_FREQ_MHZ__SYSCLK_FREQ_MHZ_bm) >>
               SEP_EFUSE_MAP__SYSCLK_FREQ_MHZ__SYSCLK_FREQ_MHZ_bp);
if (pll_freq_mhz == 0u) {
    report_status(STATUS_TYPE_WARN, SEP_MSG_PLL_FUSES_BLANK);   /* -> REF_CLK fallback */
}
```

The model's sysclk field sits at **[18:8]**. Under the VP the ROM therefore reads
`spi_control_field_en[7:0]` concatenated with the low 3 bits of `smu_pll_sysclk`, and treats
the result as a frequency. Depending on the fuse map that is either a wrong clock or an
accidental zero, which silently routes boot down the `PLL_FUSES_BLANK` / REF_CLK path — a
passing boot for the wrong reason.

## 3. The part that makes this more than a rename

**The RDL has no SPI register in the SEP eFuse map at all.** Searching the whole file for
`spi` returns nothing; 0x174's neighbours are `ROM_CTL` at 0x170 and `CHIPLET_PUBK_HASH0` at
0x178. The offset was **repurposed**, not renamed — `spi_control_field_en` no longer exists
in the fuse map.

That collides with a live consumer inside the model. Its own SPI firmware tests read the
same field, for the same purpose, at the model's bit positions:

`sw/sep-vp-tests/fw-tests-from-tt-oca-hw/fw/sep/tests/common/spi_clk.h`

```c
/* Real core clock (MHz) from the sensed eFuse smu_pll_sysclk field; 0 -> 100
 * (reference-clock fallback, matching ROM pll_init). */
static inline uint32_t spi_core_mhz(void)
{
    SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_reg_u ef;
    ef.val = READ_REG(SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_REG_ADDR);
    uint32_t f = (uint32_t)ef.f.smu_pll_sysclk;
    return f ? f : 100u;
}
```

So both trees already agree this register holds the core clock frequency and that 0 means
"fall back". They disagree only on **where the field sits** and **whether the SPI
field-enable bits share the word**. Aligning to the RDL means `spi_clk.h` reads
`sysclk_freq_mhz[10:0]`, and any eFuse/shadow preload those SPI tests use must be restated
in the new layout — a preload written for [18:8] encodes a different number once the field
moves.

Whether the SPI field-enable bits need a home elsewhere is a question for whoever owns the
fuse map; this document does not assume an answer. If they are genuinely gone, the model
should drop them rather than keep them at an address the RDL has reassigned.

## 4. Sites to change in the model

Line numbers are at `4580db79`.

| file | lines | what |
|---|---|---|
| `sep/peripherals/efuse/include/efuse_register.h` | 52 | offset constant `SEP_SPI_CTRL_FIELD_EN_OFFSET` and the comment above it |
| | 1227–1268 | the `SEP_SPI_CTRL_FIELD_EN_type` class: name, bitfields, masks |
| | 304–305 | lock-bit doc comments naming `SEP_SPI_CTRL_FIELD_EN` |
| `sep/peripherals/efuse/include/efuse_base.h` | 61, 139 | member construction and declaration |
| `sep/peripherals/efuse/src/efuse.cpp` | 34 | CCI parameter `sep_spi_ctrl_field_en` |
| | 377 | lock-bit map entry |
| | 758 | `set(...)` wiring from the CCI parameter |
| `sep/peripherals/efuse/src/efuse_base.cpp` | 52 | reset |
| `sep/peripherals/efuse/test/inc/efuse_basetest.h` | 65, 138, 211 | READ / WRITE / RESET mask expectations |
| `sep/peripherals/efuse/test/src/efuse_basetest.cpp` | 32 | the register's row in the table test |
| `sw/sep-vp-tests/.../fw/sep/tests/common/spi_clk.h` | 35–41 | the consumer above |
| `sw/sep-vp-tests/.../dependencies/meta/registers/c/och_sep_top_reg.h` | — | generated register header carrying the old name/layout |

## 5. Knock-on changes in tt-oca-harness

Only if the **CCI parameter name** changes. The harness drives fuses by parameter name:

- `virtual_platform/sepvp/fuses.py:152` — `_SPI_CTRL_FIELD_MAP` maps the TOML field
  `spi_control_field_en` to the sep-vp parameter `sep_spi_ctrl_field_en`.
- `virtual_platform/sepvp/fuses.py:133` — `"SEP_SPI_CTRL": ("spi_ctrl", None)`.

Rename the parameter and these must follow, or fuse preloads silently stop landing. Say so
in the model PR so the harness side can be updated in the same window.

## 6. Verifying the fix

From a `tt-oca-harness` checkout with the submodule pointed at the fixed model:

```bash
make -C virtual_platform vp-py-deps
cd virtual_platform && ../.venv/bin/python -m pytest tests/test_efuse_map_drift.py -q
```

All three checks must pass. `test_model_offsets_match_the_rdl` and
`test_every_rdl_register_exists_in_the_model` parse the model's `efuse_register.h` against
the RDL-generated `sep_addr.h`, so they verify the real header rather than a restatement.

Then confirm the ROM actually reads a sane clock — a full-boot test that does not report
`SEP_MSG_PLL_FUSES_BLANK` when the fuse map provisions a frequency.

Also re-run the model's own SPI tests, since `spi_clk.h` changes with this.

## 7. Do not paper over it downstream

`test_efuse_map_drift.py` carries an `_ALIASES` map for registers the model merely spells
differently, and the failure text offers it as an option. **This is not that case.** An
alias makes the guard pass while leaving the ROM reading the wrong bits — precisely the
failure the test exists to catch. The map's own comment applies: entries are names the model
has not caught up on, and a new one should be justified rather than added for convenience.

Until the model is fixed, `test_every_rdl_register_exists_in_the_model` stays red, and that
is the correct state. It is the only test failing on PR #2065 for a real reason.


---

# Issue 2 -- cold scratch is cleared only at construction, so every boot hangs

**Severity: blocks all VP boot testing.** 58 of the 86 tests in
`virtual_platform/tests/` fail on this alone, every one of them identically.

## Symptom

Every boot ends the same way, a few lines into reset:

```
[sep_scratch_cold::reset_process] - [CRNG] Reset complete

BL0 ERROR    0x0069 SEP_MSG_WARM_RESET_HANG
```

The ROM never reaches `SEP_MSG_PLL_CLK_INIT`, so every test that boots anything fails at its
first expectation. There is one root cause here, not 58.

## What the ROM is doing

`hw/sys/sep/bootrom/prod/src/vector.S` decides cold versus warm boot before it touches DCCM,
by reading the warm-handler slot `SEP_COLD_SCRATCH_7` (lines ~211-240):

```asm
    li      t0, SEP_COLD_SCRATCH_7
    lw      t1, 0(t0)              /* t1 = warm handler address */
    beqz    t1, cold_boot          /* zero -> cold boot */
    ...                            /* non-zero -> range check against ICCM/SRAM */
    j       warm_reset_hang        /* out of range -> hang, status 0x69 */
```

So a cold start requires `SEP_COLD_SCRATCH_7` to read **zero**. Anything else is treated as
an armed warm-reset handler, range-checked, and -- if it does not point into ICCM or SRAM --
deliberately hung. The ROM comments are explicit that hanging is the intended response,
because an unexpected handler value "may indicate corruption or attack".

The VP is reaching that hang on a cold start, so its `SEP_COLD_SCRATCH_7` is reading
non-zero.

This check is recent: `9317673f1` ("sep: Harden ROM boot and expand firmware DV coverage",
#1581). Before it the ROM did not read the slot at reset, which is why the VP has not needed
this until now. RTL satisfies it -- `hw/sys/sep/dv/cocotb/tests/rom_fw/sep_warm_reset_*.py`
covers all four arms on main and passes.

## This is not a regression

The VP did boot fine before, and nothing in the model broke. The ROM gained a requirement
the model has never had to meet.

`9317673f1` ("sep: Harden ROM boot and expand firmware DV coverage", #1581, 2026-09-07) added
the warm-reset dispatch. Before it the ROM did not read the slot at reset at all:

```bash
git show origin/feature/sep_virtual_platform:hw/sys/sep/bootrom/prod/src/vector.S \
  | grep -c SEP_COLD_SCRATCH_7     # 0
git show <VP branch before the main merge>:.../vector.S | grep -c SEP_COLD_SCRATCH_7   # 0
grep -c SEP_COLD_SCRATCH_7 hw/sys/sep/bootrom/prod/src/vector.S                        # 5
```

The VP was booting a ROM with no warm-reset check. Merging `origin/main` into the VP branch
brought the hardened ROM in, and the model met a new hardware-state dependency for the first
time. RTL already satisfies it -- `hw/sys/sep/dv/cocotb/tests/rom_fw/sep_warm_reset_*.py`
covers all four arms on main and passes.

## Where to look

Two explanations are ruled out; do not spend time on them.

**Addressing matches.** The generated header gives stride 8 and eight registers
(`OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(idx) = 0x10802000 + idx * 0x8`, `SIZE
0x40`), and the model declares `RegVector<SCRATCH_type<64>, 8>` at the same base. The ROM's
32-bit `lw` reads the low half of a 64-bit slot, which is correct.

**The reset value is right.** `sep_scratch_cold_register.h:23` constructs each register with
reset `0x0`.

**What differs is WHEN the reset runs.** `sep_scratch_cold` calls `reset_all_registers()`
once, from its constructor:

```cpp
// sep/peripherals/sep_scratch_cold/src/sep_scratch_cold.cpp:21
    reset_all_registers();
```

It registers no reset process. Every other peripheral resets on the reset signal instead --
`csrng` is the clearest comparison:

```cpp
// sep/peripherals/csrng/src/csrng.cpp:116, 164, 213
    SC_METHOD(reset_process);
    ...
    void csrng_model::reset_process() { ... reset_all_registers(); ... }
```

So the scratch block is zeroed at elaboration and never again, while the rest of the
subsystem re-resets whenever reset is asserted. That is consistent with the observed failure:
the ROM cold-boots once and, per `vector.S`, the cold path deliberately poisons the slot --

```asm
cold_boot:
    li      t0, SEP_COLD_SCRATCH_7
    li      t1, -1                 /* out of range on purpose */
    sw      t1, 0(t0)
```

-- so on any later reset of the core the ROM reads `-1`, fails the range check and hangs,
which is exactly the behaviour the ROM intends for a warm reset with no handler armed. The
model never clears the slot on that second reset because nothing is wired to do so.

**State this as the leading explanation, not a proven one.** It has not been confirmed by
instrumenting a run; what is confirmed is the structural difference above and that the two
simpler explanations do not hold. Whoever picks this up should verify the reset sequence
before changing behaviour.

The design question behind it: a *cold* scratch block should be cleared by a cold reset and
**preserved** across a warm one -- that persistence is the entire point of the warm-handler
slot, and `vector.S` says so ("the warm path writes NOTHING ... persistence is what a
watchdog handler slot is for"). So the fix is not simply to re-zero on every reset; the model
needs to distinguish cold from warm, matching the RTL the DV tests above describe.

## Verifying the fix

From a `tt-oca-harness` checkout with the submodule pointed at the fixed model:

```bash
make -C virtual_platform vp
cd virtual_platform && ../.venv/bin/python -m pytest tests/bootcode/test_bootcode.py -q
```

`test_common_early_boot` is the cheapest proof: it asserts the ROM reaches
`SEP_MSG_PLL_CLK_INIT` with no ERROR-type status line, which is exactly what the hang
prevents today. Once that passes, run the full suite -- the other 57 failures should clear
with it.

A cold start must reach `cold_boot`, and a warm start with an unarmed slot must still hang
deliberately: the ROM poisons the slot with -1 on the cold path precisely so an unarmed warm
reset hangs rather than silently cold-booting. Do not "fix" this by forcing the slot to zero
unconditionally -- that would disable the warm-reset dispatch the ROM relies on, and the RTL
DV tests above describe the behaviour the model should match.

---

# Issue 3 -- the SPI controller model is the forked spi_host, which no longer exists

**Not yet hit.** The VP branch is 50 commits behind `origin/main` and predates this change,
so nothing fails on it today. It lands the moment `origin/main` is merged into the VP branch,
which is deliberately being deferred until issue 2 is fixed. Queue it; do not chase it yet.

**Cause:** `b0fc4698b` -- "hw/sys/sep: Replace the forked SPI host with the upstream OpenTitan
spi_host" (#2064, merged 2026-09-19). It deletes the vendored `spi_controller` overlay --
`spi_controller.sv`, `_pkg`, `_reg`, `_reg_pkg`, about 2500 lines of forked RTL -- and adopts
upstream `hw/ip/spi_host` with two local patches.

`virtual_platform/tt-oca-harness-model/sep/peripherals/spi_controller/` models the fork. Its
own comments say so: "The RTL drives INTR_STATUS combinationally, so this both sets and
clears" describes the fork's equations. That RTL is gone.

## The register map is the easy half

Most addresses did not move. Four registers are renamed in place and one is new:

| offset | fork | upstream |
|---|---|---|
| 0x00 | `INTR_STATUS` | `INTR_STATE` |
| 0x0C | -- | `ALERT_TEST` **(new)** |
| 0x10 | `CTRL` | `CONTROL` |
| 0x18 | `CFG` | `CONFIGOPTS` |
| 0x20 | `CMD` | `COMMAND` |

`INTR_ENABLE` 0x04, `INTR_TEST` 0x08, `STATUS` 0x14, `CSID` 0x1C, `RXDATA` 0x24, `TXDATA`
0x28, `ERROR_ENABLE` 0x2C, `ERROR_STATUS` 0x30 and `EVENT_ENABLE` 0x34 keep both name and
address.

The model declares thirteen register classes -- `CFG_type`, `CMD_type`, `CTRL_type`,
`INTR_STATUS_type` and nine that already match. So the map work is four renames plus
`ALERT_TEST`, which the model does not implement at all.

```bash
git show origin/main:hw/sys/sep/regs/gen/c/sep_addr.h \
  | grep 'OCH_SEP_TOP_SPI_CONTROLLER.*BASE_ADDR'
```

## The behaviour is the hard half

Renaming registers will make it compile and still not work. `b0fc4698b` also changed the ROM
driver (`hw/sys/sep/bootrom/prod/src/sep_ot_spi.c`, +33/-16), and the reason is a semantic
change in `CONTROL.SW_RST`.

**Fork:** a self-clearing pulse. The old driver comment: "Flush the TX and RX FIFOs (and reset
the datapath) via a single SW_RST pulse ... SW_RST self-clears."

**Upstream:** a level. The new comment states the contract the model must now honour:

> `CONTROL.SW_RST` is a level: the core, both data FIFOs and the command queue stay held in
> reset until software clears it, so the release below is what makes the controller usable
> again. The CDC FIFOs drain rather than reset, so both must read empty before that release.

So the ROM now does set -> poll -> release, where it used to do one write:

```c
    ctrl.f.SW_RST = 1u;                 /* held, not a pulse */
    mmio_write32(..._CONTROL_BASE_ADDR, ctrl.w);

    for (uint32_t i = 0u; i < OT_SPI_POLL_MAX; i++) {
        status.w = mmio_read32(..._STATUS_BASE_ADDR);
        if (status.f.TXEMPTY && status.f.RXEMPTY && !status.f.ACTIVE) break;
    }

    ctrl.f.SW_RST = 0u;                 /* release */
    mmio_write32(..._CONTROL_BASE_ADDR, ctrl.w);
```

A model that self-clears `SW_RST`, or that does not drive `STATUS.TXEMPTY`/`RXEMPTY`/`ACTIVE`
to match a draining FIFO, will send the ROM round that bounded poll and then into a timeout
in the transfer that follows -- which reads as a flash or manifest failure, nowhere near the
actual cause. The drain poll is bounded deliberately, so the symptom is a late timeout rather
than a hang.

Assume other behaviour moved with it. The fork and upstream differ in FSM, FIFO and
event/error semantics, not only in `SW_RST`; that is why the change deleted 2500 lines rather
than renaming them.

## Reference for what correct looks like

Upstream RTL is vendored in this repo and is the authority:

```
vendor/lowRISC/opentitan/upstream/hw/ip/spi_host/rtl/spi_host.sv
                                              .../spi_controller_core.sv
                                              .../spi_controller_fsm.sv
                                              .../spi_controller_command_queue.sv
                                              .../spi_controller_shift_register.sv
vendor/lowRISC/opentitan/patches/0041-spi_host_renamed_submodules.patch
                                 0042-spi_host_window_no_racl.patch
```

Read the two patches: they are the only places this tree deviates from upstream.

## Verifying the fix

RTL DV already covers this and passes on main, so those tests describe the target behaviour:

```
hw/sys/sep/dv/cocotb/tests/spi/sep_spi_ot_host_csr_irq_rand_test.py   CSR / IRQ / error breadth
hw/sys/sep/dv/cocotb/tests/spi/sep_spi_ot_flash_cmd_rand_test.py      flash command breadth
hw/sys/sep/dv/cocotb/tests/spi/sep_spi_ot_dma_rx_test.py              DMA RX datapath
hw/sys/sep/dv/cocotb/tests/spi/sep_spi_ot_dma_tx_test.py              DMA TX datapath
hw/sys/sep/dv/cocotb/tests/spi/sep_spi_flash_jedec_smoke_test.py      cheapest smoke
```

On the VP side, once the model is updated and `origin/main` is merged into the VP branch, the
OCA boot tests are the proof: they fetch manifests and payloads over SPI flash
(`flash_image`, `boot="primary"`), so essentially all of
`virtual_platform/tests/bootcode/` depends on this peripheral.

```bash
cd virtual_platform && ../.venv/bin/python -m pytest tests/bootcode -q
```

Both RX drains need exercising. The ROM picks between SECURE_DMA and CPU PIO at **build**
time via `boot_flash.h` (`BOOT_OT_SPI_USE_PIO`), so they are separate binaries over separate
datapaths -- a green DMA path proves nothing about PIO.

## This list is not exhaustive

Issues 1 to 3 are what the VP integration surfaced. Further regressions are being found
independently while the model is worked on; treat this document as the VP-facing subset
rather than a complete inventory, and expect it to grow.
