<!-- SPDX-License-Identifier: Apache-2.0 -->
# TEST-ONLY signing keys — NOT FOR PRODUCTION

These RSA-3072 private keys exist so DV can exercise ROM key slots 1-5. They
are committed in the clear, which is by itself proof that they are not
production key material.

A production ROM must replace every slot with a real key digest and must not be
built with `TEST_BUILD`. The slots these keys populate are compiled in only
under `TEST_BUILD`; see `../generate_key_digests.py` and
`../../src/key_digests.c`.

Slot 0 (`dev0`) is not here. It lives in the `tt-boot-manifest` submodule at
`tools/tt-boot-manifest/tests/signing_keys/rsa_private_key.dev0.pem` and is the
key the shipped `secure_boot.bin` is signed with.

| slot | name | file |
|---|---|---|
| 1 | `dev1` | `rsa_private_key.dev1.pem` |
| 2 | `prod0` | `rsa_private_key.prod0.pem` |
| 3 | `prod1` | `rsa_private_key.prod1.pem` |
| 4 | `prod2` | `rsa_private_key.prod2.pem` |
| 5 | `prod3` | `rsa_private_key.prod3.pem` |

The slot names match `SLOT_NAMES` in `../generate_key_digests.py`; a test that
signs a manifest for slot N must use that slot's key here, because the ROM
compares `SHA-256(modulus)` against the compiled-in digest.

Every slot must have a key. A slot with no PEM is emitted as `(void *)0`, which
the ROM refuses at boot with `ROM_KEY_EMPTY` — a state no correctly generated
ROM reaches, so it must not be created on purpose either.

Regenerate the digest table from `bootrom/prod/`, so the paths recorded in the
generated comments stay relative to it:

    python3 tools/generate_key_digests.py \
        --keys-dir tools/test_signing_keys \
        --keys-dir tools/tt-boot-manifest/tests/signing_keys \
        --test-slots dev1,prod0,prod1,prod2,prod3 \
        -o src/key_digests.c
