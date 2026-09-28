# Unauthenticated demotion flags, gated by signed allow bits

**Status:** proposed
**Area:** SEP boot ROM `[C15]`, OCA manifest usage, `tt-oca-manifest` packer, SEP ROM spec, ROM DV
**Raised:** 2026-09-09, ahead of porting the demotion DV family

## Summary

Keep the ability for an *unauthenticated* manifest field to request BL1/BL2 demotion, but make
it usable only when the *signed* part of the manifest explicitly delegates that authority, per
level. A signed demotion value always wins over the unauthenticated one.

This is a **custom OCAH usage** of the OCA format: the unauthenticated flags are left to the
implementor, and the allow bits occupy reserved space the format sets aside for exactly this.

## Why it fits the format without a validator change

Two properties of the format make this an extension rather than a deviation.

**`demotion_control[15:4]` is reserved and tolerated.** `oca_check_reserved_bits` (parser.c)
is explicit:

> boot-manifest v2 requires the Consumer to "not process, depend on, infer, or act upon any
> reserved field" and does not oblige it to verify reserved regions hold 0x00 … reserved
> regions are explicitly "available for backward-compatible minor-version extension"

and `oca_demotion_check` (demotion.c) is a documented no-op for the same reason. So the
library will neither reject nor interpret bits 4/5, and the *device* is the intended consumer
of the operative bits: *"the operative demotion bits [3:0] are consumed device-side, not by
this host validator."*

**`unauthenticated_flags` is unread.** 8 bytes at offset 3756, in the unsigned tail. The spec
records bit 0 (secure-boot escalation) as a **gap** — *"read by neither the ROM nor the
validation library"* — so bits 1 and up are free, and bit 0 stays reserved for its declared
purpose.

## Proposed encoding

### `unauthenticated_flags` — offset 3756, unsigned tail

| bit | name | note |
|---|---|---|
| 0 | secure-boot escalation | already declared, still unimplemented — leave reserved |
| 1 | `UNAUTH_BL1_DEMOTE` | new |
| 2 | `UNAUTH_BL2_DEMOTE` | new |
| 63:3 | reserved | zero |

### `demotion_control` — offset 172, u16, inside the signed region

| bit | name | status |
|---|---|---|
| 0 | `BL1_DEMOTION_VALID` | existing |
| 1 | `BL1_DEMOTION_ENABLE` | existing |
| 2 | `BL2_DEMOTION_VALID` | existing |
| 3 | `BL2_DEMOTION_ENABLE` | existing |
| 4 | `BL1_UNAUTH_ALLOW` | **new**, from the reserved range |
| 5 | `BL2_UNAUTH_ALLOW` | **new**, from the reserved range |
| 15:6 | reserved | zero |

## Precedence

Per level, independently, and evaluated after the lifecycle gate:

```
if lc_state == PROD_END:
    never demote                                  # SEP-ROM-DEM-020, unchanged
elif <LEVEL>_DEMOTION_VALID:
    demote = <LEVEL>_DEMOTION_ENABLE              # signed value wins when set
elif <LEVEL>_UNAUTH_ALLOW:
    demote = unauthenticated_flags[<LEVEL>]       # authority delegated by signature
else:
    no request                                    # fail closed
```

Three properties follow, and they are the point of the design:

* **Default closed.** An all-zero `demotion_control` — which is what every image this tree
  packs carries today, and what any unaware producer emits — blocks the unauthenticated bits
  completely. Flipping them achieves nothing.
* **Delegation is itself signed.** The only way an unsigned bit can influence device state is
  if a signed, verified manifest said it may, for that level.
* **Signed values are not overridable.** `VALID` set means the unauthenticated bit is not
  consulted at all, so an attacker cannot flip a producer's explicit decision.

## One addition worth making beyond the ask

**The measurement must record that demotion was delegated, not just what it resolved to.**

`SEP-ROM-DEM-050` makes the applied demotion state an input to the boot measurement, and the
boot-state record already carries `MEAS_DEMOTION_BL1_DEMOTE` / `_BL1_LOCKED` /
`_BL2_DECISION`. If a delegated demotion measures identically to a signed one, a verifier
cannot tell that an *unauthenticated* input influenced the boot — which is exactly the fact an
attestation consumer would want to weigh. Suggest adding one bit per level, e.g.
`MEAS_DEMOTION_BL1_DELEGATED` / `_BL2_DELEGATED`, set when the value came from the
unauthenticated field.

Cheap to add now, awkward later: the record layout is a verifier-facing contract, and
`bl0_state` already had to grow once for the measurement fields.

## Work items

### ROM (`rom_main.c` `[C15]`, `oca_boot.c`, `include/oca_boot.h`)

1. `OCA_DEMOTE_BL1_UNAUTH_ALLOW` / `_BL2_UNAUTH_ALLOW` bit definitions.
2. An accessor for the unsigned field — `rom_oca_unauth_flags()` beside
   `rom_oca_demotion_control()`. It reads the staged body like its neighbour, but its
   docstring must say plainly that the value is **not authenticated**, so no future reader
   mistakes it for signed content.
3. Rework the `[C15]` decision to the precedence above. The existing shape already helps: the
   decision is taken first and the register write deferred past the fuse locks, so only the
   predicate changes.
4. `bl2_demote` becomes the *resolved* BL2 value, and both the `DEMOTE_1` unlock decision and
   `bl0_state.bl2_demotion_decision` must use that same resolved value —
   `SEP-ROM-DEM-040` requires the recorded decision and the register state to come from one
   predicate, and delegation adds a second way for them to diverge.
5. Console markers for the delegated paths, so DV can attribute them:
   e.g. `BL1_DEMOTE_UNAUTH=`, `BL2_DEMOTE_UNAUTH=`. Absence of these on a signed-decision boot
   is as informative as their presence on a delegated one.
6. Measurement bits per the section above.

### Spec (`hw/sys/sep/bootrom/prod/doc/rom.adoc`)

* `SEP-ROM-DEM-030` gains the precedence, including that `ALLOW` is consulted only when
  `VALID` is clear.
* A new requirement for the allow semantics and the fail-closed default.
* `SEP-ROM-DEM-040`: state that the recorded BL2 decision is the resolved value.
* `SEP-ROM-DEM-050` / attestation: the delegation bits.
* The field table at line 1455 gains `unauthenticated_flags` bits 1–2; the demotion-control
  table gains bits 4–5; the "secure-boot escalation flag — *gap*" row needs a note that bit 0
  stays reserved for it.
* Re-run `doc/checks/`.

### Packer (`tt-oca-manifest`, cross-repo)

The reserved bits are **Producer-zeroed**, so the packer cannot emit them today. Production
images need a config knob for `demotion_control[5:4]` and `unauthenticated_flags[2:1]`. This
is the one item outside this repo, and it is **not** on the critical path: DV can set both
fields by mutation, since `sep_oca_payload.reseal()` re-signs, and the unauthenticated field
needs no reseal at all — being outside the signed region is the whole point.

### DV

* `sep_oca_mutate`: `set_demotion(...)` taking all six bits in one call (the bits are decided
  together, and six `set_demotion_bit` calls would rehash six times), plus
  `set_unauth_flags()` / `unauth_flags()` which must **not** rehash.
* The demotion family then covers a wider matrix than before: per level,
  {signed VALID+ENABLE} × {ALLOW} × {unauth bit} × {PROD, PROD_END}. The rows that matter
  most are the ones this design exists for:
  * `ALLOW=0`, unauth bit set → **no demotion**, and the unauth bit is provably ignored;
  * `ALLOW=1`, unauth bit set, `VALID=0` → demotion applied, `*_UNAUTH=` marker present;
  * `ALLOW=1`, unauth bit set, `VALID=1`, `ENABLE=0` → **not demoted**, signed value wins;
  * unauth bit flipped *after* signing with `ALLOW=1` → still honoured, and this is the case
    that proves the field is genuinely unauthenticated rather than incidentally unsigned.
* The last row is the one to write first: it is cheap (no reseal) and it is the only test that
  distinguishes this feature from a signed-only design.

## Open questions

1. Bit assignment: are `unauthenticated_flags` bits 1/2 and `demotion_control` bits 4/5
   acceptable, or should they be placed to match another OCAH consumer's expectations?
2. Should `ALLOW` also gate a *downgrade* — i.e. can a delegated unauth bit turn demotion
   **off** where the signed side asked for it on? Under the precedence above it cannot, because
   `VALID` set stops the unauth bit being read. Confirm that is intended.
3. Is delegation wanted in `PROD` only, or also in the RMA states? `PROD_END` is already
   excluded by `DEM-020`.
4. Does the measurement delegation bit need to distinguish "delegated and the bit was set"
   from "delegated and the bit was clear"? The former changed the boot; the latter only shows
   the producer was willing.
