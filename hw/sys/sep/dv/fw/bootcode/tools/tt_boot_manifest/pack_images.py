#!/usr/bin/env python3

import struct
import time
import argparse
import sys
import os
import logging
import hmac
import hashlib

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding, utils
from .utils import convert_to_int, generate_sha256_hash, load_config, enable_checking, disable_checking, check, checking_disabled
from .pack_images_constants import *
from .aes128cbc import aes128cbc_encrypt
from .get_app_entry import get_start_address
from .manifest_signing import prepare_signing_key

logger = logging.getLogger(__name__.strip('_'))

def setup_logging(verbose):
    """ Setup logger, at INFO level by default, or DEBUG if verbose is true."""
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    logging.basicConfig(level=level, format='pack_images: %(levelname)s: %(message)s')

def validate_value(value, valid_values, var_name):
    if value not in valid_values:
        raise ValueError(f"Invalid value for {var_name}: {value}. \
                         Allowed values are {', '.join(map(str, valid_values))}.")

def validate_enum_value(value, enum_type, var_name):
    check(value in [member.value for member in enum_type],
          f"Invalid value for {var_name}: {value}. Allowed values are {[member.value for member in enum_type]}.")

def pack_boot_arguments(manifest, packed_manifest, payload_length):
    BL2_demotion = convert_to_int(manifest['boot_arguments']['BL2_demotion'])
    validate_value(BL2_demotion, {0, 1}, "BL2_demotion")
    payload_offset = convert_to_int(manifest['boot_arguments']['payload_offset'])
    secure_boot = convert_to_int(manifest['boot_arguments']['secure_boot'])
    validate_value(secure_boot, {0, 1}, "secure_boot")
    use_ext_sram = convert_to_int(manifest['boot_arguments']['use_ext_sram'])
    validate_value(use_ext_sram, {0, 1}, "use_ext_sram")
    check(payload_offset <= -payload_length or payload_offset >= MANIFEST_SIZE_BYTES, \
        f"Payload offset {payload_offset} is out of range, needs to be <= {-payload_length} or >= {MANIFEST_SIZE_BYTES}")

    # Use raw flag_args value if present (only intended for testing)
    flag_args = convert_to_int(manifest['boot_arguments'].get('flag_args', 0))
    flag_args |= (secure_boot << FLAG_ARGS_BIT_SECURE_BOOT)
    flag_args |= (BL2_demotion << FLAG_ARGS_BIT_BL2_DEMOTION)
    flag_args |= (use_ext_sram << FLAG_ARGS_BIT_USE_EXT_SRAM)

    check((flag_args & FLAG_ARGS_VALID_MASK) == flag_args, f"Invalid flag_args value {flag_args}, some reserved bits are set")

    packed_manifest += struct.pack('<q', payload_offset)  # int64_t is packed with '<q'
    packed_manifest += struct.pack('<I', flag_args)
    packed_manifest += struct.pack('<I', 0) # _reserved_0
    packed_manifest += struct.pack('<Q', 0) # _reserved_1
    return packed_manifest

def pack_manifest_signature(manifest, packed_manifest, signing_key, TBS_data):

    validate_enum_value(signing_key.signature_type, ManifestSignatureType, "signature_type")

    logger.debug(f"TBS data: {TBS_data.hex()}")
    logger.debug(f"TBS data length: {len(TBS_data)}")
    digest = generate_sha256_hash(TBS_data)
    logger.debug(f"TBS data sha256 digest: {digest.hex()}")

    # Sign the data with private key
    signature_bytes = signing_key.generate_verified_signature(TBS_data)
    signing_key.validate_signature_size()
    signature_size = len(signature_bytes)
    fill_bytes = bytes.fromhex(UNUSED_BYTE * (MAX_SIG_SZ_BYTES - signature_size))
    signature_bytes = signature_bytes + fill_bytes
    logger.debug(f"Signature: {signature_bytes.hex()}")
    check(MAX_SIG_SZ_BYTES == len(signature_bytes), \
        f"Invalid packed signature length {len(signature_bytes)} should be equal to {MAX_SIG_SZ_BYTES}")

    packed_manifest += signature_bytes
    packed_manifest += digest
    return packed_manifest

def pack_manifest_public_key(packed_manifest, signing_key):
    signing_key.validate_public_key_size()
    public_key_bytes = signing_key.public_key_bytes
    public_key_size = len(public_key_bytes)
    fill_bytes = bytes.fromhex(UNUSED_BYTE * (MAX_SIGNING_KEY_SZ_BYTES - public_key_size))
    public_key_bytes = public_key_bytes + fill_bytes
    check(MAX_SIGNING_KEY_SZ_BYTES == len(public_key_bytes), \
        f"Invalid packed public key length {len(public_key_bytes)} should be equal to {MAX_SIGNING_KEY_SZ_BYTES}")

    packed_manifest += public_key_bytes
    return packed_manifest

def pack_usage_constraints(manifest, packed_manifest):
    # Support raw selector_bits, used by DV scripts.
    selector_bits = manifest['usage_constraints'].get('selector_bits', None)
    if selector_bits is not None:
        selector_bits = convert_to_int(selector_bits)
    else:
        chiplet_selector = convert_to_int(manifest['usage_constraints']['selectors']['chiplet_id'])
        check(chiplet_selector <= 0xff, f"Invalid chiplet_id selector {chiplet_selector}")
        package_selector = convert_to_int(manifest['usage_constraints']['selectors']['package_id'])
        check(package_selector <= 0xff, f"Invalid package_id selector {package_selector}")
        life_cycle_states_selector = convert_to_int(manifest['usage_constraints']['selectors']['life_cycle_states'])
        check(life_cycle_states_selector <= 0x1, f"Invalid life_cycle_states selector {life_cycle_states_selector}")
        BL1_demotion_selector = convert_to_int(manifest['usage_constraints']['selectors']['BL1_demotion'])
        check(BL1_demotion_selector <= 0x1, f"Invalid BL1_demotion selector {BL1_demotion_selector}")
        selector_bits = 0
        selector_bits |= (chiplet_selector << SELECTOR_SHIFT_CHIPLET_ID)
        selector_bits |= (package_selector << SELECTOR_SHIFT_PACKAGE_ID)
        selector_bits |= (life_cycle_states_selector << SELECTOR_SHIFT_LIFE_CYCLE_STATES)
        selector_bits |= (BL1_demotion_selector << SELECTOR_SHIFT_BL1_DEMOTION)

    check((selector_bits & SELECTOR_BITS_VALID_MASK) == selector_bits, f"Invalid selector_bits value {selector_bits}, some reserved bits are set")
    packed_manifest += struct.pack('<Q', selector_bits)

    for key, selector_offset in [('chiplet_id', 0), ('package_id', 8)]:
        for i in range(DEVICE_ID_NUM_WORDS):
            val = convert_to_int(manifest['usage_constraints'][key][i])
            bit = i + selector_offset
            check((selector_bits & (1 << bit) != 0) or (val == UNUSED_UINT32), \
                f"{key} #{i} {val:#x} is not unused i.e. not {UNUSED_UINT32:#x}, but selector bit {bit} is not set in {selector_bits:#x}")
            packed_manifest += struct.pack('<I', val)

    # Pack life_cycle_states with conditional check of selector_bits
    if checking_disabled() or (selector_bits & (1 << SELECTOR_SHIFT_LIFE_CYCLE_STATES)):
        life_cycle_states = convert_to_int(manifest['usage_constraints']['life_cycle_states'])
        check(life_cycle_states & LIFE_CYCLE_STATES_VALID_MASK == life_cycle_states, f"Invalid life_cycle_states {life_cycle_states}, reserved bits are set")
        check(life_cycle_states != 0, f"Invalid life_cycle_states {life_cycle_states}, must be non-zero")
        packed_manifest += struct.pack('<I', life_cycle_states)

        # Check that life_cycle_states is valid for the secure boot mode
        secure_boot = convert_to_int(manifest['boot_arguments']['secure_boot'])
        if secure_boot == 0:
            # PROD & PROD_END are not allowed for non-secure boot
            check(life_cycle_states & (LIFE_CYCLE_STATES_PROD | LIFE_CYCLE_STATES_PROD_END) == 0, f"Invalid life_cycle_states {life_cycle_states} for non-secure boot")
    else:
        packed_manifest += struct.pack('<I', UNUSED_UINT32)

    # Use raw flags value if present (only intended for testing)
    flags = convert_to_int(manifest['usage_constraints'].get('flags', 0))

    # Pack BL1_demotion into flags with conditional check of selector_bits
    if checking_disabled() or (selector_bits & (1 << SELECTOR_SHIFT_BL1_DEMOTION)):
        BL1_demotion = convert_to_int(manifest['usage_constraints']['BL1_demotion'])
        validate_value(BL1_demotion, {0, 1}, "BL1_demotion")
        flags |= (BL1_demotion << USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION)

    encrypted_payload = convert_to_int(manifest['encrypted_payload'])
    validate_value(encrypted_payload, {0, 1}, "encrypted_payload")
    flags |= (encrypted_payload << USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD)

    security_version_update = convert_to_int(manifest['security_version_update'])
    validate_value(security_version_update, {0, 1}, "security_version_update")
    flags |= (security_version_update << USAGE_CONSTRAINTS_FLAGS_BIT_SECURITY_VERSION_UPDATE)

    check((flags & USAGE_CONSTRAINTS_FLAGS_VALID_MASK) == flags, f"Invalid flags value {flags}, some reserved bits are set")

    # Pack the flags value
    packed_manifest += struct.pack('<I', flags)

    return packed_manifest

def pack_encryption(manifest, packed_manifest):
    encrypted_payload = convert_to_int(manifest['encrypted_payload'])
    if encrypted_payload == 1:
        # Allow overriding the IV that is packed into the manifest, for testing purposes.
        # encryption_iv is always used for the actual encryption step.
        val = manifest.get('packed_encryption_iv', manifest['encryption_iv'])
        iv = bytes.fromhex(val)
        kdf_input = bytes.fromhex(manifest['encryption_kdf_input'])
        check(len(iv) == AES_ENC_IV_SIZE_BYTES, \
            f'IV length is {len(iv)}, must be {AES_ENC_IV_SIZE_BYTES} bytes long')
        check(len(kdf_input) == AES_ENC_SALT_SIZE_BYTES, \
            f'kdf input length is {len(kdf_input)}, must be {AES_ENC_SALT_SIZE_BYTES} bytes long')
        iv += bytes(16)
        derived_key = bytes.fromhex(manifest['encryption_derived_key'])
    else:
        iv = bytes.fromhex(UNUSED_BYTE * ENC_IV_SIZE_BYTES)
        kdf_input = bytes.fromhex(UNUSED_BYTE * ENC_SALT_SIZE_BYTES)
        derived_key = bytes.fromhex(UNUSED_BYTE * 16)

    check(len(derived_key) == AES_ENC_KEY_SIZE_BYTES, \
        f'Key password length is {len(derived_key)}, must be {AES_ENC_KEY_SIZE_BYTES} bytes long')
    check(len(iv) == ENC_IV_SIZE_BYTES, \
        f'IV length is {len(iv)}, must be == {ENC_IV_SIZE_BYTES} bytes long')
    check(len(kdf_input) == ENC_SALT_SIZE_BYTES, \
        f'kdf input length is {len(kdf_input)}, must be == {ENC_SALT_SIZE_BYTES} bytes long')

    # encrypted_payload is packed into the flags field of usage_constraints
    packed_manifest += iv
    packed_manifest += kdf_input

    logger.debug(f"encrypted_payload: {encrypted_payload}")
    logger.debug(f"IV: {iv.hex()}")
    logger.debug(f"KDF input: {kdf_input.hex()}")

    return packed_manifest

def pack_manifest_TBS(manifest, payload, payload_image_count, signing_key):
    packed_manifest = bytearray()
    identifier = convert_to_int(manifest['manifest_identifier'])
    validate_enum_value(identifier, ManifestIdentifier, "manifest_identifier")
    packed_manifest += struct.pack('<I', identifier)
    v = convert_to_int(manifest['manifest_version_major'])
    check(v == 1, "Manifest major version must be 1")
    packed_manifest += struct.pack('<H', convert_to_int(manifest['manifest_version_major']))
    packed_manifest += struct.pack('<H', convert_to_int(manifest['manifest_version_minor']))
    # Use the value from the manifest if it exists (intended for testing)
    manifest_length = convert_to_int(manifest.get('manifest_length', MANIFEST_SIZE_BYTES))
    check(manifest_length <= MANIFEST_SIZE_BYTES, f"Manifest length {manifest_length} is greater than {MANIFEST_SIZE_BYTES}")
    check(manifest_length % ALIGNMENT_SIZE_BYTES == 0, f"Manifest length {manifest_length} must be a multiple of {ALIGNMENT_SIZE_BYTES}")
    packed_manifest += struct.pack('<I', manifest_length)
    packed_manifest += struct.pack('<I', 0) # _reserved_0
    packed_manifest = pack_usage_constraints(manifest, packed_manifest)
    packed_manifest = pack_encryption(manifest, packed_manifest)
    packed_manifest += struct.pack('<H', 0) # _reserved_1
    packed_manifest += struct.pack('<H', convert_to_int(manifest['security_version']))
    packed_manifest += struct.pack('B', (manifest['encryption_type']))
    packed_manifest += struct.pack('B', signing_key.signature_type)

    public_key_sel = manifest['public_key_sel']
    if isinstance(public_key_sel, dict):
        selection = convert_to_int(public_key_sel['selection'])
        validate_enum_value(selection, ManifestPublicKeySelection, "selection")
        value = selection << 4
        if selection == ManifestPublicKeySelection.ROM_KEY.value:
            index = convert_to_int(public_key_sel['rom_key_index'])
            check(index <= 5, f"Invalid rom_key_index {index}, must be <= 5")
            value |= index
    else:
        value = convert_to_int(public_key_sel)
    packed_manifest += struct.pack('<H', value) # 16-bit value

    packed_manifest = pack_manifest_public_key(packed_manifest, signing_key)
    if manifest['encrypted_payload']:
        # Hash the entire (already encrypted) payload
        hashed_length = len(payload)
        hash_data = payload
    else:
        # Hash just the plaintext TOC
        toc_size = TOC_HEADER_SIZE_BYTES + (TOC_ENTRY_SIZE_BYTES * payload_image_count)
        hashed_length = toc_size
        hash_data = payload[:toc_size]
    hash_value = generate_sha256_hash(hash_data)
    logger.debug(f"Payload SHA-256 Hash: {hash_value.hex()}")
    packed_manifest += hash_value
    # Use the value from the manifest if it exists (intended for testing), otherwise use the calculated value
    payload_hashed_length = convert_to_int(manifest.get('payload_hashed_length', hashed_length))
    check(payload_hashed_length == hashed_length, f"Invalid payload_hashed_length {payload_hashed_length}, expected {hashed_length}")
    packed_manifest += struct.pack('<Q', payload_hashed_length)
    timestamp = manifest.get('timestamp', None)
    if timestamp is None:
        timestamp = time.time()
    timestamp = convert_to_int(timestamp)
    logger.debug(f"timestamp: {timestamp}")
    packed_manifest += struct.pack('<q', timestamp)
    logger.debug(f"Payload image count: {payload_image_count}")
    # Use the value from the manifest if it exists (intended for testing), otherwise use the calculated value
    payload_length = convert_to_int(manifest.get('payload_length', len(payload)))
    check(payload_length == len(payload), f"Invalid payload_length {payload_length}, expected {len(payload)}")
    packed_manifest += struct.pack('<Q', payload_length)
    major = manifest['content_version']['major']
    check(major < (1 << 16), "content_version.major too large")
    minor = manifest['content_version']['minor']
    check(minor < (1 << 24), "content_version.minor too large")
    patch = manifest['content_version']['patch']
    check(patch < (1 << 24), "content_version.patch too large")
    version = (major << 48) | (minor << 24) | patch
    packed_manifest += struct.pack('<Q', version)
    desc = manifest['description'].encode('ascii', errors='strict')
    check(len(desc) > 0, "Manifest description is empty")
    check(len(desc) <= 127, f"Manifest description too long '{desc[127:]}'")
    packed_manifest += struct.pack('<127s', desc)
    packed_manifest += struct.pack('B', 0) # ensure null-termination
    return packed_manifest, manifest_length, payload_length

def pack_manifest(manifest, payload, payload_image_count, signing_key):
    TBS_data, manifest_length, payload_length = pack_manifest_TBS(manifest, payload, payload_image_count, signing_key)
    packed_manifest = TBS_data.copy()
    packed_manifest = pack_manifest_signature(manifest, packed_manifest, signing_key, TBS_data)
    packed_manifest = pack_boot_arguments(manifest, packed_manifest, payload_length)
    if len(packed_manifest) != manifest_length:
        packed_manifest += bytes.fromhex(UNUSED_BYTE * (manifest_length - len(packed_manifest)))
    check(len(packed_manifest) == MANIFEST_SIZE_BYTES, \
        f"Manifest length is {len(packed_manifest)}, expected {MANIFEST_SIZE_BYTES}")
    return packed_manifest

def payload_toc_entry(image, image_data, entry_point, image_number, offset):
    packed_header = bytearray()
    load_addr = convert_to_int(image['load_addr'])
    check(load_addr % ALIGNMENT_SIZE_BYTES == 0, \
        f"Image load address {load_addr} is not aligned to {ALIGNMENT_SIZE_BYTES} bytes")
    image_type = image['type']
    if image_type == 'SEPBL1':
        image_type = ImageType.SEP_BL1
    elif image_type == 'SEPBL2':
        image_type = ImageType.SEP_BL2
    elif image_type == 'SMCBL1':
        image_type = ImageType.SMC_BL1
    elif image_type == 'SMCBL2':
        image_type = ImageType.SMC_BL2
    else:
        check(False, f"Unrecognised image type '{image_type}'")
    packed_header += struct.pack('<Q', image_type.value)
    packed_header += struct.pack('<Q', offset)
    actual_image_length = len(image_data)
    image_length = image.get('length', actual_image_length)
    check(image_length > 0, f"Invalid image length {image_length}")
    check(image_length == actual_image_length, f"Invalid image length {image_length}, expected {actual_image_length}")
    packed_header += struct.pack('<Q', image_length)
    packed_header += struct.pack('<Q', convert_to_int(image['version']))
    packed_header += struct.pack('<Q', load_addr)

    logger.debug(f"Entry point from elf file: {entry_point} {entry_point:#x}")
    if image_type == ImageType.SEP_BL1:
        check(entry_point >= SEP_IRAM_BASE and entry_point + image_length < SEP_IRAM_BASE + SEP_IRAM_SIZE, \
            f"Invalid entry point {entry_point} and image length {image_length} for SEP_BL1 image, \
                valid range [{SEP_IRAM_BASE}, {SEP_IRAM_BASE + SEP_IRAM_SIZE})")
        entry_point -= SEP_IRAM_BASE
        logger.debug(f"Adjusted entry point for SEP BL1: {entry_point} {entry_point:#x}")

    # For now ignore the start address / entry point provided in the manifest config.
    # entry_point = convert_to_int(header['entry_point'])
    # logger.debug(f"Entry point from the manifest config: {entry_point}")

    packed_header += struct.pack('<Q', entry_point)
    packed_header += struct.pack('<Q', 0) # _reserved_0

    digest = generate_sha256_hash(image_data)
    # Allow overriding the hash for testing purposes.
    if checking_disabled():
        hash_value = image.get('hash', None)
        if hash_value is not None:
            digest = bytes.fromhex(hash_value)
            check(len(digest) == SHA256_DIGEST_SIZE_BYTES, \
                f"Invalid hash value length {len(digest)}, expected {SHA256_DIGEST_SIZE_BYTES}")

    logger.debug(f"Image {image_number} sha256 digest: {digest.hex()}")
    packed_header += struct.pack('<32s', digest)
    desc = image['description'].encode('ascii', errors='strict')
    check(len(desc) <= 127, f"Image description too long '{desc[127:]}'")
    packed_header += struct.pack('<127s', desc)
    packed_header += struct.pack('B', 0) # ensure null-termination
    check(len(packed_header) == IMAGE_HEADER_SIZE_BYTES, \
        f"Image header length is {len(packed_header)}, expected {IMAGE_HEADER_SIZE_BYTES}")
    return packed_header



def process_payload_images(toc_config, payload_images):
    payload = bytearray()
    toc_entries = bytearray()
    toc_size = TOC_HEADER_SIZE_BYTES + (TOC_ENTRY_SIZE_BYTES * len(payload_images))
    payload_image_count = 0
    for image in payload_images:
        entry_point = image.get('entry_point', None)
        file_path = os.path.expandvars(image['file_path'])
        if entry_point is None:
            entry_point = get_start_address(file_path)
        with open(file_path, 'rb') as f:
            image_data = f.read()
        padding_length = (ALIGNMENT_SIZE_BYTES - (len(image_data) % ALIGNMENT_SIZE_BYTES)) % ALIGNMENT_SIZE_BYTES
        image_data += b'\x00' * padding_length
        offset = image.get('offset', toc_size + len(payload))
        offset += image.get('gap', 0)
        check(offset >= toc_size, f"Image {payload_image_count} at offset {offset:#x} overlaps with TOC header ({toc_size:#x})")
        cur_offset = len(payload) + toc_size
        check(offset >= cur_offset, f"Image {payload_image_count} at offset {offset:#x} overlaps with previous image ({cur_offset:#x})")
        toc_entries.extend(payload_toc_entry(image, image_data, entry_point, payload_image_count, offset))
        gap_to_image = offset - cur_offset
        logger.debug(f'Image {payload_image_count}, gap to image is {gap_to_image:#x}')
        payload.extend(bytearray(bytes.fromhex(UNUSED_BYTE) * gap_to_image))
        payload.extend(image_data)
        payload_image_count += 1

    toc = bytearray()
    toc += struct.pack('<I', TOC_HEADER_MAGIC_WORD)
    major_version = convert_to_int(toc_config['version_major'])
    check(major_version == TOC_MAJOR_VERSION, f"Invalid TOC major version {major_version}, expected {TOC_MAJOR_VERSION}")
    toc += struct.pack('<H', major_version)
    toc += struct.pack('<H', convert_to_int(toc_config['version_minor']))
    actual_payload_length = toc_size + len(payload)
    payload_length = convert_to_int(toc_config.get('payload_length', actual_payload_length))
    check(payload_length == actual_payload_length, f"Invalid payload_length {payload_length}, expected {actual_payload_length}")
    toc += struct.pack('<Q', payload_length)
    image_count = convert_to_int(toc_config.get('image_count', payload_image_count))
    check(image_count == payload_image_count, f"Invalid image_count {image_count}, expected {payload_image_count}")
    toc += struct.pack('<Q', image_count)
    toc += struct.pack('<Q', 0) # reserved
    toc.extend(toc_entries)

    check(len(toc) == toc_size, f"Actual TOC size ({len(toc)}) doesn't match calculated {toc_size}")

    toc.extend(payload)

    return toc, payload_image_count

def process_manifest(config):
    payload, payload_image_count = process_payload_images(config['toc'], config['payload_images'])

    manifest = config['manifest']
    secure_boot = convert_to_int(manifest['boot_arguments']['secure_boot'])
    if secure_boot != 1:
        check(secure_boot == 0, f"Invalid secure boot value {secure_boot}")
    encrypted_payload = convert_to_int(manifest['encrypted_payload'])
    check(encrypted_payload == 0 or secure_boot == 1, \
        f"Invalid encrypted_payload {encrypted_payload} for secure_boot {secure_boot}")
    if encrypted_payload == 1:
        encryption_type = manifest['encryption_type']
        check(encryption_type == 1, f"Unsupported encryption_type {encryption_type}")
        iv = bytes.fromhex(manifest['encryption_iv'])
        kdf_key = bytes.fromhex(manifest['encryption_key_input'])
        kdf_input = bytes.fromhex(manifest['encryption_kdf_input'])
        encryption_key = bytes.fromhex(manifest['encryption_derived_key'])

        check(len(kdf_key) == AES_ENC_SALT_SIZE_BYTES, \
            f'KDF base key length is {len(kdf_key)}, must be {AES_ENC_SALT_SIZE_BYTES} bytes long')
        check(len(kdf_input) == AES_ENC_SALT_SIZE_BYTES, \
            f'KDF input length is {len(kdf_input)}, must be {AES_ENC_SALT_SIZE_BYTES} bytes long')
        check(len(encryption_key) == AES_ENC_KEY_SIZE_BYTES, \
            f'Key length is {len(encryption_key)}, must be {AES_ENC_KEY_SIZE_BYTES} bytes long')

        # Derive the encryption key to test the derivation process
        # Eventually this will be replaced with a call to an HSM for real releases
        kdf_calculated_key = kbkdf_hmac256(
            AES_ENC_KEY_SIZE_BYTES,
            kdf_key,
            kdf_input[0:AES_ENC_SALT_SIZE_BYTES // 2],
            kdf_input[AES_ENC_SALT_SIZE_BYTES // 2: AES_ENC_SALT_SIZE_BYTES],
        )
        check(kdf_calculated_key == encryption_key, \
            f'KDF derived key does not match manifest test key')

        logger.debug(f"Payload Encryption key: {encryption_key.hex()}")
        payload = aes128cbc_encrypt(encryption_key, iv, payload)

    # Setup a signing key object (contains key material for secure enabled and is empty otherwise)
    signing_key = prepare_signing_key(manifest, secure_boot)

    manifest_blob = pack_manifest(manifest, payload, payload_image_count, signing_key)
    return manifest_blob, payload

def write_manifest_and_payload(manifest_blob, payload, output_manifest_file, output_payload_file):
    with open(output_manifest_file, 'wb') as f:
        f.write(manifest_blob)
    logger.debug(f"Written output manifest file {output_manifest_file}.\n")
    with open(output_payload_file, 'wb') as f:
        f.write(payload)
    logger.debug(f"Written output payload file {output_payload_file}.\n")

def check_for_overlaps(offsets_lengths):
    print(offsets_lengths)
    for i, (offset1, length1, name1) in enumerate(offsets_lengths):
        for j, (offset2, length2, name2) in enumerate(offsets_lengths):
            if i != j:
                check(offset1 + length1 <= offset2 or offset2 + length2 <= offset1, \
                    f"Blobs overlap: blob #{i} {name1} ends at {offset1 + length1:#x}, blob #{j} {name2} starts at {offset2:#x}")


def pack_blobs(blobs):
    logger.debug('Blob,                Start,   End,     Length')
    for addr in sorted(blobs.keys()):
        blob_len = len(blobs[addr][0])
        name = blobs[addr][1] + ','
        end = addr + blob_len
        logger.debug(f'{name: <20} {addr:#07x}, {end-1:#07x}, {blob_len:#07x}')
        if addr < 0:
            raise ValueError(f"Blob {name} has negative offset {addr:#x}")

    bounds = []
    for addr in sorted(blobs.keys()):
        bounds.append((addr, len(blobs[addr][0]), blobs[addr][1]))

    check_for_overlaps(bounds)

    output = bytearray()
    current = 0
    for addr in sorted(blobs.keys()):
        gap = addr - current
        blob = blobs[addr][0]
        if gap < 0:
            if not checking_disabled():
                raise ValueError(f"Blob {blobs[addr][1]} has negative gap {gap:#x} at address {addr:#x}")
            # Cut off the start of the next blob to make things fit
            blob = blob[abs(gap):]
        else:
            fill = bytearray(gap)
            output += fill
        logger.debug(f'{addr=:#x} {current=:#x} {gap=:#x} {len(blob)=:#x}')
        output += blob
        current = len(output)

    return output


def kbkdf_hmac256(out_key_size:int, in_key:bytes, info:bytes, salt:bytes):
    """
    Generate derived key bytes using in_key, info, and salt based on
    a simplified version of NIST SP 800-108r1. Uses SHA-256 as the PRF
    with (4.1) KDF in Counter Mode where the round count is 1.
    """
    counter_value = 1
    counter_size = 4
    key_bits = out_key_size * 8
    key_bits_size = 4

    #  Constructed input to HMAC function is as follows:
    #  AAAABBBBBBBBBBBBBBBBCDDDDDDDDDDDDDDDDEEEE
    #  A = 4 byte counter of value (0x1) (BE)
    #  B = 16 byte info string padded with zeros
    #  C = 1 byte delimeter of value 0x0
    #  D = 16 byte salt string padded with zeros
    #  E = 4 byte number of bits (BE)

    kdf_hash_input = counter_value.to_bytes(counter_size, byteorder='big')
    kdf_hash_input += info
    kdf_hash_input += b'\x00'
    kdf_hash_input += salt
    kdf_hash_input += key_bits.to_bytes(key_bits_size, byteorder='big')

    hash_function = hashlib.sha256
    h = hmac.new(key=in_key, msg=kdf_hash_input, digestmod=hash_function)

    return h.digest()[:out_key_size]

def create_spi_tlv_blob(spi_config):
    spi = bytearray()

    flags = 0
    if spi_config['flags']['keep_default_init']:
        flags |= SPI_PARAM_KEEP_DEFAULT_INIT

    spi += struct.pack('<H', SPI_PARAM_TLV_TYPE)
    spi += struct.pack('<H', SPI_PARAM_TLV_LENGTH)
    spi += struct.pack('B', convert_to_int(flags))
    spi += struct.pack('B', convert_to_int(spi_config['spi_freq']))
    spi += struct.pack('B', convert_to_int(spi_config['spi_dll_margin_rom']))
    spi += struct.pack('B', convert_to_int(spi_config['spi_dll_margin_tlv']))
    spi += struct.pack('<L', convert_to_int(spi_config['discovery_ctrl']))
    spi += struct.pack('<L', convert_to_int(spi_config['dq_timing']))
    spi += struct.pack('<L', convert_to_int(spi_config['dqs_timing']))
    spi += struct.pack('<L', convert_to_int(spi_config['gate_lpbk']))
    spi += struct.pack('<L', convert_to_int(spi_config['dll_slave']))
    spi += struct.pack('<L', convert_to_int(spi_config['dll_master']))
    spi += struct.pack('<L', convert_to_int(spi_config['misc']))
    spi += struct.pack('<L', convert_to_int(spi_config['rb_valid_time']))
    # struct.pack('<32s', digest)
    hash = generate_sha256_hash(spi)
    spi += struct.pack('<32s', hash)
    logger.debug(f"SPI TLV hash: {hash.hex()}")
    check(len(spi) == SPI_PARAM_TLV_LENGTH + 4, f"SPI TLV size mismatch {len(spi)} != {SPI_PARAM_TLV_LENGTH + 4}")

    return spi

# A dict that doesn't allow duplicate keys, because having two blobs at the same
# address doesn't make sense.
class BlobDict(dict):
    def __setitem__(self, key, value):
        if key in self:
            raise KeyError(f"Duplicate blob at address: {key:#x}")
        super().__setitem__(key, value)


def generate_images(config_data) -> list:
    logger.debug(f"Input config data:\n{config_data}")

    enable_checking()
    if config_data.get('meta', {}).get('disable_checks', False):
        disable_checking()

    manifest = config_data['primary']['manifest']

    manifest_blob, payload = process_manifest(config_data['primary'])

    # Support setting a different offset for recovery generation
    primary_manifest_offset = config_data['primary']['manifest'].get('offset', PRIMARY_MANIFEST_OFFSET)

    primary_payload_offset = manifest['boot_arguments']['payload_offset'] + primary_manifest_offset
    check(primary_payload_offset % ALIGNMENT_SIZE_BYTES == 0, \
        f"Primary payload address {primary_payload_offset} is not aligned to {ALIGNMENT_SIZE_BYTES} bytes")
    check(len(manifest_blob) <= BACKUP_MANIFEST_OFFSET, \
        f"Primary manifest length {len(manifest_blob)} is too large, needs to be at most {BACKUP_MANIFEST_OFFSET}")

    blobs = BlobDict()
    blobs[primary_manifest_offset] = (manifest_blob, 'Primary manifest')
    blobs[primary_payload_offset]  = (payload,       'Primary payload')

    spi = config_data['primary'].get('spi', False)
    if spi:
        blobs[PRIMARY_SPI_CONFIG_OFFSET] = (create_spi_tlv_blob(spi), 'Primary SPI config')
    check(spi, 'Missing Primary SPI config')

    images = []
    images.append(manifest_blob)
    images.append(payload)

    backup_manifest_blob = bytearray()
    backup_payload = bytearray()

    backup_config = config_data.get('backup', None)
    if backup_config:
        backup_manifest_blob, backup_payload = process_manifest(backup_config)
        backup_payload_offset = backup_config['manifest']['boot_arguments']['payload_offset'] + BACKUP_MANIFEST_OFFSET
        check(backup_payload_offset % ALIGNMENT_SIZE_BYTES == 0, \
            f"Recovery payload address {backup_payload_offset} is not aligned to ALIGNMENT_SIZE_BYTES bytes")

        spi = backup_config.get('spi', None)
        if spi:
            blobs[BACKUP_SPI_CONFIG_OFFSET] = (create_spi_tlv_blob(spi), 'Backup SPI config')
        check(spi, 'Missing Backup SPI config')

        blobs[BACKUP_MANIFEST_OFFSET] = (backup_manifest_blob, 'Recovery manifest')
        blobs[backup_payload_offset]  = (backup_payload,       'Recovery payload')

        images.append(backup_manifest_blob)
        images.append(backup_payload)
    else:
        blobs[BACKUP_MANIFEST_OFFSET] = (bytearray(MANIFEST_SIZE_BYTES), 'Empty backup manifest')

    final_blob = pack_blobs(blobs)
    images.append(final_blob)

    return images


def write_images(output_path, config_data, images) -> bool:
    OUT_DIR = os.path.dirname(output_path)
    OUT_BASENAME = os.path.splitext(os.path.basename(output_path))[0]

    if OUT_DIR:  # If the directory is not the current directory
        logger.debug(f"Creating path for {OUT_DIR}")
        os.makedirs(OUT_DIR, exist_ok=True)

    primary_manifest = images.pop(0)
    primary_payload = images.pop(0)
    manifest_filename = os.path.join(OUT_DIR, f"{OUT_BASENAME}_manifest.bin")
    payload_filename = os.path.join(OUT_DIR, f"{OUT_BASENAME}_payload.bin")
    write_manifest_and_payload(primary_manifest, primary_payload, manifest_filename, payload_filename)

    backup_config = config_data.get('backup', None)
    if backup_config:
        backup_manifest = images.pop(0)
        backup_payload = images.pop(0)
        manifest_filename = os.path.join(OUT_DIR, f"{OUT_BASENAME}_manifest_backup.bin")
        payload_filename = os.path.join(OUT_DIR, f"{OUT_BASENAME}_payload_backup.bin")
        write_manifest_and_payload(backup_manifest, backup_payload, manifest_filename, payload_filename)

    final_blob = images.pop(0)
    with open(output_path, 'wb') as f:
        f.write(final_blob)
    logger.debug(f"Written output file {output_path}.\n\n")
    return True

def pack_images(config_path: str ,output_path: str, verbose: bool) -> bool:
    setup_logging(verbose)
    config_data = load_config(config_path)
    if config_data == None:
        return False
    images = generate_images(config_data)
    if images== []:
        return False
    return write_images(output_path, config_data, images)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="./out/default.yaml")
    parser.add_argument("--out", type=str, default='./out/output.bin')
    parser.add_argument("-v", "--verbose", action='store_true')

    args = parser.parse_args()

    if args.config is None or args.out is None:
        parser.print_help()
        sys.exit(1)

    pack_images(args.config, args.out, args.verbose)


if __name__ == "__main__":
    main()
