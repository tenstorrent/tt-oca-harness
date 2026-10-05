# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""OCA manifest field offsets, loaded from the producer's own constants.

The offsets are not restated here. `src/oca/constants.py` in the tt-oca-manifest
submodule is what the packer writes with and what the C validator's layout-sync
test pins, so a copy in this repo would be a third place to drift. A test that
pokes byte 3748 because a comment said so is a test that silently stops poking
`payload_offset` the day the format moves.

Loaded by file path rather than imported as `tt_boot_manifest.oca.constants`:
the package's `__init__` pulls in the signing and encryption modules, so a plain
import needs `cryptography` installed. The pytest venv has no reason to carry the
producer's crypto dependencies just to read integer offsets.
"""

import importlib.util

from sepvp import paths

_CONSTANTS = paths.BOOTCODE_DIR / "tools" / "tt-oca-manifest" / "src" / "oca" / "constants.py"


def _load():
    if not _CONSTANTS.is_file():
        raise FileNotFoundError(
            f"OCA producer constants not found at {_CONSTANTS}; is the "
            "tt-oca-manifest submodule checked out?"
        )
    spec = importlib.util.spec_from_file_location("oca_producer_constants", _CONSTANTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


C = _load()

# Flash slot offsets. These are the SPI image's layout, not the manifest format's,
# so they come from the ROM header (include/boot_flash.h) rather than the producer.
PRIMARY_OFFSET = 0x1000
BACKUP_OFFSET = 0x41000

# Re-exported for readability at the tamper sites.
OCAC_MAGIC = C.OCAC_MAGIC
OCAP_MAGIC = C.OCAP_MAGIC
BODY_SIZE = C.OCA_CLASSIC_BODY_SIZE
SIGNED_REGION_END = C.OCA_CLASSIC_SIGNED_REGION_END
OFF_MAGIC = C.OFF_BOOT_MANIFEST_MAGIC
OFF_MANIFEST_LENGTH = C.OFF_MANIFEST_LENGTH
OFF_TRAILER = C.OFF_CLASSIC_MANIFEST_TRAILER
OFF_PAYLOAD_OFFSET = C.OFF_PAYLOAD_OFFSET
OFF_PAYLOAD_LENGTH = C.OFF_PAYLOAD_LENGTH
OFF_REVOKE = C.OFF_PUBLIC_KEY_CLASSIC_REVOKE
OFF_SECURITY_VERSION = C.OFF_MANIFEST_SECURITY_VERSION
TOC_HEADER_SIZE = C.TOC_HEADER_SIZE
TOC_ENTRY_SIZE = C.TOC_ENTRY_SIZE

# A byte inside the signed region, clear of any field a case wants to set on
# purpose, for breaking manifest_hash.
SIGNED_REGION_BYTE = 24

assert SIGNED_REGION_BYTE < SIGNED_REGION_END
assert OFF_PAYLOAD_OFFSET >= SIGNED_REGION_END, (
    "payload_offset must lie in the unsigned tail for the no-re-signing tamper "
    "cases to work; the format moved it"
)
