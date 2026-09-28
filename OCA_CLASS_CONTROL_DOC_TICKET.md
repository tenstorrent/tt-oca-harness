# tt-oca-manifest: the OCA_FAIL_SIGNATURE_CLASS_CONTROL enum doc names only the
# manifest-initiated route

Doc-only. No behaviour change, no consumer code depends on the prose. Raised
from SEP ROM DV triage (PR #1590), where a PROD part returning this code did not
match what the enum documentation led a reader to expect.

**Repo:** `tt-oca-manifest`
**File:** `validators/oca/lib/oca_validator.h`, the `OCA_FAIL_SIGNATURE_CLASS_CONTROL = 36`
doc block (around lines 284-302 at submodule pin `1681ad91c`)

## What it says

The first of the three bullets:

>   - secure boot is in force but neither class bit is set, so nothing
>     names a signature to verify (a manifest that demands verification
>     while describing none);

The bullet itself is right. The parenthetical is not: it attributes the
enforcement to the manifest, when the check tests the *resolved* determination.

## Why that is wrong

`secure_boot.c:226` gates on `secure`, which is whatever
`secure_boot_decide(body, cb, &device_disabled)` returned — not on the
manifest's bit:

```c
if (secure == OCA_SECURE_TRUE
    && ctx->secure_boot_enforce_classic != OCA_SECURE_TRUE
    && ctx->secure_boot_enforce_pqc != OCA_SECURE_TRUE) {
    return OCA_FAIL_SIGNATURE_CLASS_CONTROL;
}
```

Its own comment already states the general rule, and contradicts the enum's
parenthetical:

> the format requires at least one class whenever secure boot is in force —
> **whichever input put it in force**

`secure_boot_decide()` has three inputs in precedence order. (1) is the
manifest's `secure_boot_control` enforced bit, which short-circuits. (3) is the
device's own `is_secure_boot_active()`. So a manifest with the enforced bit
CLEAR, on a device whose lifecycle enforces secure boot, reaches line 226 with
`secure == TRUE` and no class bit — and is refused with 36. No manifest demanded
anything.

The `@retval` text for the same code, further down the same header (~line 1616),
is already route-neutral and correct:

> Secure boot is in force and neither class bit is set, or secure_boot_pqc is
> set on a variant with no PQC crypto region

So the two doc sites for one code disagree, and the narrower one is the enum —
which is where a reader looks first.

## Why it matters

The device-forced route is likely the most common way a real part returns 36: a
production part handed a validly unsigned manifest. That is a normal,
fail-closed production rejection, and the enum doc does not mention it.

Worse, the one case the parenthetical does name — a manifest that sets the
enforced bit but names no class — is one the packer refuses to emit on the
producer side, so it is the *less* reachable of the two. An integrator reading
the enum would conclude 36 implies a malformed manifest, when on a PROD part it
usually means "this image is unsigned and this part requires signing".

This is exactly the wrong conclusion to lead a Consumer integrator to, because
the two have different responses: one is a bad build, the other is a correctly
rejected unsigned image.

## Suggested wording

Replace the parenthetical, and name the device route explicitly:

```
 *    - secure boot is in force but neither class bit is set, so nothing names
 *      a signature to verify. The enforcement may come from any input the
 *      precedence consults (see secure_boot_decide): most often a device whose
 *      lifecycle enforces secure boot, handed a manifest that declares none —
 *      an unsigned image on a part that requires signing. A manifest that sets
 *      the enforced bit while naming no class reaches the same code, though the
 *      packer refuses to emit one;
```

## Not affected

- The `@retval` text at ~1616 is already correct; leave it.
- The other two bullets are accurate (`parser.c:178` for the PQC-on-classic
  arm, and the `crypto_dispatch.c` / `authorization.c` gated-check backstops).
- SEP ROM side needs nothing: `status_for_result()` maps 36 to
  `SEP_MSG_MANIFEST_SECURE_BOOT`, which is route-neutral and right.

## How it surfaced

`sep_firmware_cntl_secure_boot_flow_test` puts a PROD part in front of a
manifest whose `secure_boot` is cleared. Because clearing the enforced bit
obliges the whole crypto set to be zeroed (`OCA_FAIL_SECURE_BOOT_INVARIANT`,
`parser.c:190-208`), the manifest is legally unsigned, the device forces
enforcement, and the slot is refused with `MANIFEST_ERR=0x00030024` on both
slots. Correct behaviour; the enum doc is what made it look wrong at first read.
