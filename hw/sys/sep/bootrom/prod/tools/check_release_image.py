#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fail if a release ROM image carries the ML-DSA-87 test public key.

The test key in tests/signing_keys/ signs firmware-test vectors and must never be a
trust anchor. This scans each image for the key's raw 2592-byte public key and for
its SHA-2 and SHA-3 digests, each raw, with every 32-bit word byte-swapped, and as
hex text: the forms a stored key or anchor digest would take.

Usage: check_release_image.py --key PEM IMAGE [IMAGE ...]
"""

import argparse
import hashlib
import sys

from cryptography.hazmat.primitives import serialization


def word_swapped(data):
    """data with the bytes of every 32-bit word reversed."""
    return b"".join(data[i : i + 4][::-1] for i in range(0, len(data), 4))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--key", required=True, help="ML-DSA-87 test private key (PKCS#8 PEM)")
    ap.add_argument("images", nargs="+", help="release images to scan")
    args = ap.parse_args()

    with open(args.key, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    pk = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    needles = {"public key": pk, "public key (word-swapped)": word_swapped(pk)}
    for alg in ("sha256", "sha384", "sha512", "sha3_256", "sha3_384", "sha3_512"):
        digest = hashlib.new(alg, pk).digest()
        name = f"public key {alg.upper()}"
        needles[name] = digest
        needles[f"{name} (word-swapped)"] = word_swapped(digest)
        needles[f"{name} (hex)"] = digest.hex().encode()
        needles[f"{name} (HEX)"] = digest.hex().upper().encode()

    found = []
    for image in args.images:
        with open(image, "rb") as f:
            data = f.read()
        found += [f"{image}: {name}" for name, needle in needles.items() if needle in data]
    if found:
        print("check_release_image: the ML-DSA-87 test key is in a release image:", file=sys.stderr)
        for line in found:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"check_release_image: no ML-DSA-87 test key material in {len(args.images)} image(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
