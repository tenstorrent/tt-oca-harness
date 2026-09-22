# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary manifest carries a KDF input that derives a different AES key.

``decrypt_payload`` splits ``m->encryption_kdf_input`` into the KBKDF's info and
salt halves and derives the payload key from them and the ``CLASS_KEY`` fuse
(``bootrom/prod/src/manifest_crypto.c``). So the manifest, not the fuse alone,
decides the key -- and a manifest whose KDF input is not the one the packer keyed
from selects a key the payload was never encrypted under.

``invalid_kdf_input.bin`` is the golden encrypted image with
``primary.manifest.encryption_kdf_input`` overridden (``Makefile``,
``decrypt_negative_images``). That one override is enough because the packer's two
uses of the field are independent: ``process_manifest`` encrypts with
``encryption_derived_key``, while ``pack_encryption`` packs
``encryption_kdf_input`` verbatim. The packer notices the pair no longer agree and
says so -- ``WARNING: KDF derived key does not match manifest test key`` -- which
is the packer reporting the injected fault, not a build problem.

The KBKDF still SUCCEEDS -- it derives a valid 16-byte key, just not the right one
-- so this is not a decryption error; ``sep_decrypt_input_defect`` states what that
costs and how the ordering is graded.

Unlike the IV row, this corrupts EVERY block rather than block 0. The backup slot
carries the golden KDF input, so it decrypts and boots in the same run.

Needs ``+sep_crypto_edn_force``: two RSA-3072 modexps on OTBN plus two AES
decryptions, and AES is EDN client 0.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_decrypt_input_defect import sep_decrypt_input_defect_base


@pyuvm.test()
class sep_firmware_invalid_decryption_kdf_input_test(sep_decrypt_input_defect_base):
    """Primary manifest KDF input derives the wrong key -> TOC refused -> backup boots."""

    defect = "kdf_input"
