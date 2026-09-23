<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Release ROM key material

This directory holds the **public** halves of the ROM root keys a release build
anchors on. It ships empty on purpose: no key in this repository is fit for a
tape-out, and a committed placeholder would be one merge away from becoming one.

`make BUILD_TYPE=release` reads this directory, hashes each modulus, and generates
the ROM's `key_digests.c`. With the directory empty the build stops and says so.

## What to put here

One PEM per ROM key slot, named for its slot:

```
rsa_public_key.rom_key0.pem
rsa_public_key.rom_key1.pem
...
rsa_public_key.rom_key5.pem
```

Each must be an RSA-3072 public key. The ROM pins
`SHA-256(modulus_big_endian_384_bytes)` for each slot and compares a manifest's
key against it at boot, so the file must be the exact key whose private half will
sign production images.

Fewer than six is allowed. An unprovisioned slot is compiled in as a NULL digest,
which the ROM refuses (`src/oca_platform.c`), so the part fails closed on slots it
does not hold rather than accepting anything for them.

Use a directory outside the repository entirely by setting
`SEP_ROM_RELEASE_SIGNING_KEYS_DIR`:

```bash
make BUILD_TYPE=release SEP_ROM_RELEASE_SIGNING_KEYS_DIR=/path/to/keys
```

When the build runs in the toolchain container, that path has to be visible inside
it. `scripts/docker-run.sh run-here` mounts the repository, so a directory outside
the tree needs its own mount or a host build with `RISCV_TOOLCHAIN` set.

## Private keys are rejected

The build scans every file here and fails if any of them is a private key, whatever
it is called. The ROM only ever needs a public modulus; a private key in this
directory means the wrong directory was passed or test keys were staged into it, and
both produce a mask nobody can trust.

Production private keys belong in a hardware key store and must never enter source
control. The private test keys under `../tests/signing_keys/` are DV assets for
`BUILD_TYPE=debug` only.

## Signing release images

Generating the ROM's anchors is separate from signing the flash images those anchors
verify. `make BUILD_TYPE=release oca-images` is not implemented: signing a release
image means reaching a key store rather than reading a file, and that work is still
open. A release build produces the ROM only.
