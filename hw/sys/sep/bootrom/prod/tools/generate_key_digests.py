#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Generate key_digests.c from RSA-3072 key files.

Usage:
    python3 generate_key_digests.py --keys rom_key0.pem,rom_key1.pem,...
    python3 generate_key_digests.py --keys-dir path/to/signing_keys/
    python3 generate_key_digests.py --keys-dir path/to/release_keys/ --key-form public

Extracts the RSA-3072 public modulus, computes SHA-256(modulus_big_endian_384bytes),
and outputs key_digests.c.

The ROM only ever needs the digest of a public modulus, so a release build reads
public key files and refuses to run against a directory holding private key
material. See --key-form.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

# RSA-3072. The digest is over the raw big-endian modulus at this exact width, so a
# key of any other size would silently produce a digest the ROM can never match.
MODULUS_BYTES = 384
MODULUS_BITS = MODULUS_BYTES * 8

KEY_FORM_PRIVATE = "private"
KEY_FORM_PUBLIC = "public"

# Matches the PEM banner of every private key encoding openssl emits: "RSA PRIVATE
# KEY" (PKCS#1), "EC PRIVATE KEY" (SEC1), "PRIVATE KEY" (PKCS#8) and "ENCRYPTED
# PRIVATE KEY". Matching the banner also catches keys this script cannot load --
# wrong algorithm, or passphrase-protected.
PEM_PRIVATE_BANNER = re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")

PEM_BANNER = re.compile(rb"-----BEGIN ([A-Z0-9 ]+)-----")


def pem_label(blob):
    """The label of the first PEM block in ``blob``, or None."""
    match = PEM_BANNER.search(blob)
    return match.group(1) if match else None


def die(*lines):
    """Exit with a multi-line diagnostic, in the style of the Makefile's own guards."""
    for line in lines:
        print(line, file=sys.stderr)
    raise SystemExit(1)


def reject_private_key_material(keys_dir):
    """Refuse to proceed if the directory holds any private key.

    A release ROM is anchored on public moduli alone, so a private key here means
    the wrong directory or staged test keys. Check every regular file, not just the
    six the slots name: the dangerous case is a key under an unexpected name.
    """
    offenders = []
    for path in sorted(keys_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        if PEM_PRIVATE_BANNER.search(blob):
            offenders.append(path)

    if offenders:
        die(
            "ERROR: private key material found in a release key directory.",
            f"       Directory: {keys_dir}",
            *(f"         {p.name}" for p in offenders),
            "",
            "       A release ROM is anchored on public moduli only. Remove the private",
            "       keys, or point SEP_ROM_RELEASE_SIGNING_KEYS_DIR at the right directory.",
        )


def slot_filename(key_form, name):
    return f"rsa_{key_form}_key.{name}.pem"


def load_modulus(pem_path, key_form):
    """Return the RSA modulus from a PEM file, as an integer.

    Needs python3-cryptography, which the RISC-V toolchain sandbox does not carry,
    so this runs on the host. The Makefile's key-digests target owns that ordering.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    blob = pem_path.read_bytes()

    # The label carries which of the two forms this file is; the loaders below
    # report only that they could not decode it.
    label = pem_label(blob)
    if label is None:
        die(f"ERROR: {pem_path} does not contain a PEM block.")
    wanted_private = key_form == KEY_FORM_PRIVATE
    if (b"PRIVATE" in label) != wanted_private:
        die(
            f"ERROR: {pem_path} holds a '{label.decode()}' block,"
            f" but a {key_form} key was expected."
        )

    try:
        if wanted_private:
            key = serialization.load_pem_private_key(blob, password=None).public_key()
        else:
            key = serialization.load_pem_public_key(blob)
    except Exception as e:
        die(f"ERROR: cannot read {key_form} key {pem_path}: {e}")

    if not isinstance(key, rsa.RSAPublicKey):
        die(
            f"ERROR: {pem_path} is not an RSA key.",
            "       ROM key slots anchor RSA-3072 moduli; this ROM verifies nothing else.",
        )

    n = key.public_numbers().n
    if n.bit_length() != MODULUS_BITS:
        die(
            f"ERROR: {pem_path} is RSA-{n.bit_length()}, expected RSA-{MODULUS_BITS}.",
            f"       The digest is taken over a {MODULUS_BYTES}-byte big-endian modulus,",
            "       so a key of any other width could never match at boot.",
        )
    return n


def extract_modulus_digest(pem_path, key_form):
    """Extract the RSA-3072 modulus from PEM and return its SHA-256 digest."""
    n = load_modulus(pem_path, key_form)
    return hashlib.sha256(n.to_bytes(MODULUS_BYTES, byteorder="big")).digest()


def format_digest(name, digest):
    """Format a digest as a C static const array."""
    lines = [f"static const uint8_t {name}[SHA256_DIGEST_SIZE_BYTES] = {{"]
    # 16 bytes per line: 4 indent + 16 * "0xXX, " lands on 99 columns, just inside the
    # tree's clang-format ColumnLimit of 100. At 8 per line clang-format repacks the array
    # and `make ocah-format-c-check` reports the generated file as unformatted.
    for i in range(0, 32, 16):
        chunk = ", ".join(f"0x{digest[i + j]:02x}" for j in range(16))
        lines.append(f"    {chunk},")
    lines.append("};")
    return "\n".join(lines)


# Slot names are positional only, because the ROM draws no trust distinction between
# them: all six are ROM-embedded root keys, resolved the same way by the same bitmap
# (public_key_select_classic bits [7:0], which also index CHIPLET_PUBK_REVOKE).
SLOT_NAMES = [f"rom_key{n}" for n in range(6)]


def collect_pem_files(args):
    """Resolve the slot -> PEM mapping from --keys-dir or --keys."""
    if not args.keys_dir:
        pem_files = {}
        for i, path in enumerate(args.keys.split(",")):
            path = path.strip()
            if path and path != "-":
                pem_files[SLOT_NAMES[i]] = Path(path)
        return pem_files

    keys_dir = Path(args.keys_dir)
    if not keys_dir.is_dir():
        die(
            f"ERROR: key directory not found: {keys_dir}",
            "       A release build needs the production ROM key public moduli, which are",
            "       deliberately not shipped in this repository. Provision them there, or",
            "       set SEP_ROM_RELEASE_SIGNING_KEYS_DIR to the directory holding them.",
        )

    # Reject private material before reading anything, so a directory that should
    # never have been used is refused whole.
    if args.key_form == KEY_FORM_PUBLIC:
        reject_private_key_material(keys_dir)

    pem_files = {}
    for name in SLOT_NAMES:
        path = keys_dir / slot_filename(args.key_form, name)
        if path.exists():
            pem_files[name] = path

    if not pem_files:
        die(
            f"ERROR: no {args.key_form} ROM keys found in {keys_dir}",
            f"       Expected files named {slot_filename(args.key_form, 'rom_key<N>')}"
            " for N in 0..5.",
        )
    return pem_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keys", help="Comma-separated PEM files (slot0,slot1,...)")
    group.add_argument("--keys-dir", help="Directory with per-slot ROM key PEM files")
    parser.add_argument(
        "--key-form",
        choices=[KEY_FORM_PRIVATE, KEY_FORM_PUBLIC],
        default=KEY_FORM_PRIVATE,
        help="Key file form to read. 'public' additionally refuses a directory "
        "containing any private key (default: private)",
    )
    parser.add_argument("-o", "--output", default="key_digests.c")
    args = parser.parse_args()

    pem_files = collect_pem_files(args)

    digest_defs = []
    entries = []
    for slot, name in enumerate(SLOT_NAMES):
        if name in pem_files:
            digest = extract_modulus_digest(pem_files[name], args.key_form)
            var = f"digest_{name}"
            digest_defs.append(format_digest(var, digest))
            entries.append(f"    {{.digest = {var}}}, // slot {slot}: {name}")
            print(f"  slot {slot} ({name}): {pem_files[name]}", file=sys.stderr)
        else:
            # NULL marks the slot unprovisioned. The ROM refuses it
            # (oca_platform.c), so a part built with fewer than six keys fails
            # closed on the ones it does not hold.
            entries.append(f"    {{.digest = (void *)0}}, // slot {slot}: {name}")

    with open(args.output, "w") as f:
        # Emit the licence header the tree-wide OSPO sweep expects. Without it every
        # regeneration silently strips the header off key_digests.c again.
        f.write("/* SPDX-License-Identifier: Apache-2.0 */\n")
        f.write("/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */\n\n")
        f.write("// Auto-generated by generate_key_digests.py — DO NOT EDIT.\n")
        f.write("//\n")
        f.write("// SHA-256 digests of RSA-3072 public key moduli.\n\n")
        f.write('#include "key_digests.h"\n\n')
        for d in digest_defs:
            f.write(d + "\n\n")
        f.write("public_key_info_t public_key_digests[NUM_PUBLIC_KEY_DIGESTS] = {\n")
        f.write("\n".join(entries) + "\n")
        f.write("};\n")

    print(f"Generated {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
