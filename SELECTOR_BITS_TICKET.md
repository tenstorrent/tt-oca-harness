# Make the OCA selector bits enforce something on SEP

**Status:** proposed
**Area:** SEP boot ROM (`hw/sys/sep/bootrom/prod`), OCA image configs, SEP ROM spec, ROM DV
**Raised:** 2026-09-09, during the OCA manifest DV port

## Summary

A manifest states which usage constraints it wants enforced in `selector_bits`, and the ROM
supplies each selected constraint's value through a callback. On SEP today **no constraint is
ever evaluated**: every packed image selects nothing, and the one callback that would matter
for versions reports `UNAVAILABLE` unconditionally. The mechanism is wired but inert.

This ticket asks for two ROM-resident values — a baseline chiplet **version** and a structured
chiplet **identity** — so that version-range and identity selector bits can be exercised and
enforced, plus the build-time switches to control where each comes from.

## What is true today

### The selector-bit layout

From `validators/oca/lib/selector.h` and `oca_layout.h` (the C authority the ROM links):

| bits | meaning |
|---|---|
| 0–31 | chiplet-ID byte mask — which of the 32 chiplet-ID bytes must match |
| 32–63 | package-ID byte mask |
| 64–95 | system-ID byte mask |
| 96, 97, 98 | chiplet / package / system lifecycle constrained |
| 99, 100 | chiplet version floor / ceiling |
| 101, 102 | package version floor / ceiling |
| 103, 104 | system version floor / ceiling |
| 105–127 | reserved — any bit set is a **rejection**, not something to ignore |

Identity comparison is per byte and mask-driven: `oca_identity_compare(body, off, kind, mask,
cb)` — *"Only the bytes `mask` selects participate, so a manifest can pin part of an identity
and leave the rest free."*

### Nothing is selected

Measured across all 16 classic images in `bootrom/prod/build/oca_*_boot.bin`:

```
selector_bits    = 0x0
lifecycle_states = 0x0   (all three scopes)
demotion_control = 0x0000
```

So identity, lifecycle and version constraints are all unexercised. `secure_boot_control` is
the only populated control field (`0x03` on every signed image).

### The three callbacks, and which one is the gap

| callback | today | verdict |
|---|---|---|
| `plat_get_identity_bytes` (`oca_platform.c:472`) | reads fuses `SEP_CHIPLET_ID` @`0x109302A0`, `SEP_SIP_ID` @`0x109302C0`, `SEP_SYS_ID` @`0x109302E0`, 32 B each | **works** — but a blank or DV OTP reads zero, so a manifest can only usefully pin bytes to zero |
| `plat_get_lifecycle_state` (`:495`) | chiplet only; package and system return `OCA_HW_UNAVAILABLE` | **correct as-is** — a manifest constraining a level the device cannot report must not boot |
| `plat_get_version` (`:546`) | returns `OCA_HW_UNAVAILABLE` unconditionally, `*out_major = *out_minor = 0` | **the gap** — comment says *"No version-range fuses are provisioned on SEP"*, so any manifest selecting bits 99–104 fails closed |

Per `SEP-ROM-MAN-040`, a selected constraint whose input is unavailable fails the slot. That is
the right default and should stay; the point of this ticket is to make the chiplet version
*available* so the constraint becomes usable rather than fatal.

## Requested work

### 1. ROM-resident baseline chiplet version

Embed a chiplet version in the ROM and return it from `plat_get_version` for
`OCA_VERSION_LEVEL_CHIPLET`, so version floor/ceiling constraints (selector bits 99, 100) are
enforceable.

* Package and system levels keep returning `OCA_HW_UNAVAILABLE` — SEP has no such identity, and
  failing closed there is correct.
* Targeting the **0.5.0** release, the requested starting value is **major `0x0000`, minor
  `0x00FF`**.
* Overridable at build time.

Proposed knobs, following the existing `BL1_SRAM_EXEC_ENABLE` / `ROM_ICCM_CLEAR_*` style:

```make
SEP_CHIPLET_VERSION_MAJOR ?= 0x0000
SEP_CHIPLET_VERSION_MINOR ?= 0x00FF
```

Both must reach `CFLAGS` **and** `BUILD_FLAGS`, so a change rebuilds the objects — the stamp at
`Makefile:325` (`$(OBJS): $(FLAGS_STAMP)`) already covers every object including `vector.o`
once the variable is listed there.

**Design question to settle before implementing.** `minor = 0xFF` behaves asymmetrically: it
satisfies any floor a 0.x manifest sets, and **violates any ceiling** below `0.255`. If the
images are expected to pin a maximum (bit 100), an embedded `0.255` rejects them. Pick
deliberately:

* `major 0, minor 0xFF` — "newest pre-1.0". Good for floors, unusable with ceilings.
* `major 0, minor 5` — the literal 0.5. Works with both, and a ceiling of `0.5` is meaningful.

Whichever is chosen, state it in the spec next to the requirement, because a manifest author
has to know what the device will report.

### 2. ROM-resident structured chiplet identity

Embed a chiplet ID in the ROM, laid out so the manufacturer and family are separable from the
device instance, and have the ROM confirm the manufacturer and family bytes match a mask it
holds.

* Layout: **mfg / family / device**, delineated so a fixed mask covers mfg+family. A concrete
  proposal, to be ratified: byte 0 `mfg`, byte 1 `family`, bytes 2–3 `device`, bytes 4–31
  reserved and zero. The mask constant then covers bytes 0–1.
* This value is **independent of the `SEP_CHIPLET_ID` fuse**.
* A build-time flag selects which the comparison uses: the ROM-embedded value or the OTP fuse.
* The ROM-embedded value is itself build-time overridable.

```make
SEP_CHIPLET_ID_SOURCE ?= rom    # rom | otp
SEP_CHIPLET_ID_MFG    ?= <tbd>
SEP_CHIPLET_ID_FAMILY ?= <tbd>
SEP_CHIPLET_ID_DEVICE ?= <tbd>
```

**Note this is two distinct checks, and the ticket wants both.**

1. The library's existing masked compare, driven by the *manifest's* mask — "do the bytes this
   manifest pins match the device?"
2. A **new ROM-side policy check** — "does this manifest pin the mfg and family bytes at all?"
   The library cannot ask that; it honours whatever mask the manifest supplies, including an
   empty one. Enforcing a minimum pinning is a ROM policy addition, in the same family as
   `BL1_SRAM_EXEC_ENABLE`: a build decision about what the ROM will accept. It needs its own
   requirement, its own console marker for the refusal, and its own DV case.

Whether that policy is on by default is a decision. Consistent with how the SRAM gate was
handled, suggest **off by default** initially (so existing images keep booting) with a knob to
enable it, then flip the default once the images pin their identity.

### 3. Make the packed images select real constraints

The ROM work is untestable while every image selects nothing. Update the OCA image configs
under `bootrom/prod/configs/` so that at least:

* one image pins chiplet mfg+family and a version floor, and boots;
* one pins a mismatching mfg/family and is refused;
* one selects a version floor above the baseline and is refused;
* one selects a reserved bit (105+) and is refused — this arm needs no device support at all
  and is worth having regardless.

## Consequences elsewhere

**Spec (`hw/sys/sep/bootrom/prod/doc/rom.adoc`).** New requirements for the baseline version, the identity
source flag, and the mfg/family pinning policy; the reported version value has to be stated
where a manifest author will find it. `SEP-ROM-MAN-040` needs no change — it already says an
unavailable selected constraint fails the slot — but the note that no version is available
becomes stale and must go. Re-run `doc/checks/` after: `check_tables.py` and `check_xrefs.py`
both gate the requirement index.

**DV.** The identity/version families do not exist yet; they are new tests, not ports. Two
existing things improve for free:

* `env/sep_oca_mutate.verify_usage_constraints_layout()` is a weak anchor today precisely
  because the constraint fields are all zero — masks pass trivially on zeros. Images that
  populate `selector_bits` and `lifecycle_states` make it a real check.
* `set_selector_bit()` and `set_lifecycle_states()` already exist in that module and are
  selftested, so the mutation side of the new tests is in place.

**Build matrix.** Five new knobs is a lot of surface. Whatever lands, the non-default value of
each needs a compile check, as was done for `BL1_SRAM_EXEC_ENABLE=0`,
`ROM_ICCM_CLEAR_FULL=1` and `ROM_ICCM_CLEAR_ENABLE=0` — a flag whose other branch is never
compiled is a latent break. Worth folding into whatever CI job builds the ROM variants.

## Open questions

1. Version value: `0.255` or `0.5`? See the trade-off above — it depends on whether images will
   pin ceilings.
2. mfg/family/device byte layout and the actual mfg/family values. The mask constant follows
   from the layout, and the packer and ROM must agree.
3. Is the mfg/family pinning policy on or off by default at introduction?
4. Should `SEP_CHIPLET_ID_SOURCE=otp` also apply to package and system IDs, or is the ROM-side
   value chiplet-only? The fuses for all three exist; only the chiplet one has a stated need.
5. Does anything outside the ROM consume the embedded identity — attestation, the boot-state
   measurement record, key derivation? If so the layout is a wider contract than the manifest
   check and should be ratified accordingly.
