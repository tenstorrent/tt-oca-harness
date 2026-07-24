from enum import Enum

class ManifestSignatureType(Enum):
    NO_SIGNATURE = 0
    RSA_3072 = 1
    ECC_P_256 = 2

class ManifestPublicKeySelection(Enum):
    ROM_KEY = 0
    FUSE_KEY_0 = 1
    FUSE_KEY_1 = 2
    FUSE_SOP_KEY = 4
    FUSE_SYS_KEY = 5

class ManifestIdentifier(Enum):
    TBL1 = 0x314c4254 # "TBL1"
    TBL2 = 0x324c4254 # "TBL2"

class ImageType(Enum):
    SEP_BL1 = 0x00000_31_4c_42_50_45_53
    SEP_BL2 = 0x00000_32_4c_42_50_45_53
    SMC_BL1 = 0x00000_31_4c_42_43_4d_53
    SMC_BL2 = 0x00000_32_4c_42_43_4d_53


# Constants for sizes - these can be updated via set_sep_iram_config()
_config = {
    'SEP_IRAM_BASE': 0x01000000,
    'SEP_IRAM_SIZE': 0x00020000,
}

# Expose as module-level attributes for backward compatibility
SEP_IRAM_BASE = _config['SEP_IRAM_BASE']
SEP_IRAM_SIZE = _config['SEP_IRAM_SIZE']

def set_sep_iram_config(base=None, size=None):
    """
    Update SEP IRAM configuration values.

    Args:
        base: New SEP_IRAM_BASE value (hex or int), or None to keep current
        size: New SEP_IRAM_SIZE value (hex or int), or None to keep current

    Example:
        set_sep_iram_config(base=0x70020000, size=0x00040000)
    """
    global SEP_IRAM_BASE, SEP_IRAM_SIZE

    if base is not None:
        _config['SEP_IRAM_BASE'] = base
        SEP_IRAM_BASE = base

    if size is not None:
        _config['SEP_IRAM_SIZE'] = size
        SEP_IRAM_SIZE = size

def get_sep_iram_config():
    """
    Get current SEP IRAM configuration values.

    Returns:
        dict: Dictionary with 'base' and 'size' keys
    """
    return {
        'base': SEP_IRAM_BASE,
        'size': SEP_IRAM_SIZE,
    }

def reset_sep_iram_config():
    """Reset SEP IRAM configuration to default values."""
    set_sep_iram_config(base=0x70010000, size=0x00020000)

# SPI config offsets - these can be updated via set_spi_config_offsets()
# Manifest offsets are automatically calculated as SPI offset + 0x1000
MANIFEST_OFFSET_DELTA = 0x1000

_spi_config = {
    'PRIMARY_SPI_CONFIG_OFFSET': 0x0,
    'BACKUP_SPI_CONFIG_OFFSET': 0x40000,
    'PRIMARY_MANIFEST_OFFSET': 0x0 + MANIFEST_OFFSET_DELTA,
    'BACKUP_MANIFEST_OFFSET': 0x80000 + MANIFEST_OFFSET_DELTA,
}

# Expose as module-level attributes for backward compatibility
PRIMARY_SPI_CONFIG_OFFSET = _spi_config['PRIMARY_SPI_CONFIG_OFFSET']
BACKUP_SPI_CONFIG_OFFSET = _spi_config['BACKUP_SPI_CONFIG_OFFSET']
PRIMARY_MANIFEST_OFFSET = _spi_config['PRIMARY_MANIFEST_OFFSET']
BACKUP_MANIFEST_OFFSET = _spi_config['BACKUP_MANIFEST_OFFSET']

def set_spi_config_offsets(primary=None, backup=None):
    """
    Update SPI configuration offset values.

    Manifest offsets are automatically calculated as SPI config offset + 0x1000.

    Args:
        primary: New PRIMARY_SPI_CONFIG_OFFSET value (hex or int), or None to keep current
        backup: New BACKUP_SPI_CONFIG_OFFSET value (hex or int), or None to keep current

    Example:
        set_spi_config_offsets(primary=0x0, backup=0x80000)
        # This will set PRIMARY_MANIFEST_OFFSET to 0x1000 and BACKUP_MANIFEST_OFFSET to 0x81000
    """
    global PRIMARY_SPI_CONFIG_OFFSET, BACKUP_SPI_CONFIG_OFFSET
    global PRIMARY_MANIFEST_OFFSET, BACKUP_MANIFEST_OFFSET

    if primary is not None:
        _spi_config['PRIMARY_SPI_CONFIG_OFFSET'] = primary
        PRIMARY_SPI_CONFIG_OFFSET = primary

        _spi_config['PRIMARY_MANIFEST_OFFSET'] = primary + MANIFEST_OFFSET_DELTA
        PRIMARY_MANIFEST_OFFSET = primary + MANIFEST_OFFSET_DELTA

    if backup is not None:
        _spi_config['BACKUP_SPI_CONFIG_OFFSET'] = backup
        BACKUP_SPI_CONFIG_OFFSET = backup

        _spi_config['BACKUP_MANIFEST_OFFSET'] = backup + MANIFEST_OFFSET_DELTA
        BACKUP_MANIFEST_OFFSET = backup + MANIFEST_OFFSET_DELTA

def get_spi_config_offsets():
    """
    Get current SPI configuration offset values.

    Returns:
        dict: Dictionary with 'primary', 'backup', 'primary_manifest', and 'backup_manifest' keys
    """
    return {
        'primary': PRIMARY_SPI_CONFIG_OFFSET,
        'backup': BACKUP_SPI_CONFIG_OFFSET,
        'primary_manifest': PRIMARY_MANIFEST_OFFSET,
        'backup_manifest': BACKUP_MANIFEST_OFFSET,
    }

def reset_spi_config_offsets():
    """Reset SPI configuration offsets to default values."""
    set_spi_config_offsets(primary=0x0, backup=0x40000)




RSA_3072_KEY_SZ_BITS = 3072
RSA_3072_KEY_SZ_BYTES = RSA_3072_KEY_SZ_BITS // 8
EC_256_KEY_SZ_BYTES = 32
MAX_SIGNING_KEY_SZ_BYTES = max(RSA_3072_KEY_SZ_BYTES, EC_256_KEY_SZ_BYTES)
MAX_SIG_SZ_BYTES = max(RSA_3072_KEY_SZ_BYTES, EC_256_KEY_SZ_BYTES * 2)
SHA256_DIGEST_SIZE_BYTES = 32
ENC_IV_SIZE_BYTES = 32
ENC_SALT_SIZE_BYTES = 32
AES_ENC_IV_SIZE_BYTES = 16
AES_ENC_SALT_SIZE_BYTES = 32
AES_ENC_KEY_SIZE_BYTES = 16
MANIFEST_SIZE_BYTES = 1184
TOC_HEADER_SIZE_BYTES = 32
TOC_HEADER_MAGIC_WORD = 0x434f5450 # "PTOC"
TOC_MAJOR_VERSION = 1
TOC_ENTRY_SIZE_BYTES = 216
IMAGE_HEADER_SIZE_BYTES = 216
SIGNATURE_FIELD_SIZE = 384
PUBLIC_KEY_FIELD_SIZE = 384

ALIGNMENT_SIZE_BYTES = 8

PUBLIC_EXPONENT = 65537 # Fixed exponent value 0x010001

# bitmask to ensure the reserved selector_bits field bits 9-31 and 33-63 are set to 0
DEVICE_ID_NUM_WORDS = 8
SELECTOR_SHIFT_CHIPLET_ID = 0
SELECTOR_SHIFT_PACKAGE_ID = (SELECTOR_SHIFT_CHIPLET_ID + DEVICE_ID_NUM_WORDS)
SELECTOR_SHIFT_LIFE_CYCLE_STATES = (SELECTOR_SHIFT_PACKAGE_ID + DEVICE_ID_NUM_WORDS)
SELECTOR_SHIFT_BL1_DEMOTION = (SELECTOR_SHIFT_LIFE_CYCLE_STATES + 1)
SELECTOR_BITS_VALID_MASK = ((1 << (SELECTOR_SHIFT_BL1_DEMOTION + 1)) - 1)

USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION = 0
USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD = 1
USAGE_CONSTRAINTS_FLAGS_BIT_SECURITY_VERSION_UPDATE = 2
USAGE_CONSTRAINTS_FLAGS_VALID_MASK = ((1 << (USAGE_CONSTRAINTS_FLAGS_BIT_SECURITY_VERSION_UPDATE + 1)) - 1)

LIFE_CYCLE_STATES_TEST_DEV = 1 << 0
LIFE_CYCLE_STATES_PROD = 1 << 1
LIFE_CYCLE_STATES_PROD_END = 1 << 2
LIFE_CYCLE_STATES_RMA_SOP = 1 << 3
LIFE_CYCLE_STATES_RMA_CHIPLET = 1 << 4
LIFE_CYCLE_STATES_VALID_MASK = ((1 << 5) - 1)

FLAG_ARGS_BIT_SKIP_SHA256 = 31
FLAG_ARGS_BIT_SECURE_BOOT = 30
FLAG_ARGS_BIT_USE_EXT_SRAM = 29
FLAG_ARGS_BIT_BL2_DEMOTION = 0
FLAG_ARGS_VALID_MASK = ((3 << FLAG_ARGS_BIT_USE_EXT_SRAM) | 1)

# U64 mask
U64_MASK = 0xffffffffffffffff
# U32 mask
U32_MASK = 0xffffffff

# Byte value to use for unused padding data
UNUSED_BYTE = "A5"
UNUSED_UINT32 = int(UNUSED_BYTE * 4, 16)

# SPI constants
SPI_PARAM_TLV_TYPE = 0x464C # "FL"
SPI_PARAM_KEEP_DEFAULT_INIT = 1
SPI_PARAM_TLV_LENGTH = 9 * 4 + 32 # Excluding type and length field, plus hash
