<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->
# Test signing keys

Every key in this directory is a **test key**. The private halves are committed so
that debug ROM images, packed test manifests and firmware tests can be built and signed
without a key store. Treat them as public: anyone with a clone can sign with them.

None of them may anchor a release ROM. A `BUILD_TYPE=release` ROM build reads public keys
only, from `release_signing_keys/`, and refuses a directory holding any private key.

| File | Algorithm | Used by |
|---|---|---|
| `rsa_private_key.rom_key0.pem` … `rom_key5.pem` | RSA-3072 | Debug ROM trust anchors (`key_digests.c` is generated from these) and the packed OCA test manifests under `configs/` |
| `ec_private_key.pem` | ECDSA P-256 | The ECDSA boot test manifest (`configs/oca_ecdsa_boot_test.yaml`) |
| `mldsa87_test_private_key.pem` | ML-DSA-87 (seed-only PKCS#8) | The SEP Adams Bridge ML-DSA-87 firmware test (`hw/sys/sep/dv/fw/tests/abr_mldsa87_verify_test/`), which signs a dummy blob with it at build time. No ROM image reads it. |

The ML-DSA-87 firmware test's vector generator pins the SHA-256 of this key's raw public
key and refuses any other key, so replacing the file means updating that pin too.
