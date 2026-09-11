# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup enables chiplet_id constraints it does not satisfy; the ROM halts.

The mirror of ``sep_firmware_manifest_primary_invalid_chiplet_id_test``. There the
primary carries the defect and the valid backup completes the boot; here the
primary is refused by the failover trigger, the backup carries the chiplet_id
defect, and with both slots refused ``rom_manifest_boot`` runs out of retries and
``rom_err_fail`` halts the ROM (``bootrom/prod/src/manifest_load.c``,
``bootrom/prod/src/rom_main.c``). The expected outcome is terminal -- ``ERROR: INVALID_CHIPLET_ID`` rather than a warning.

THE FAILOVER TRIGGER. Reaching the backup by breaking the primary's payload TOC
version does not work here: this ROM validates the TOC INSIDE the slot attempt and
prints ``MANIFEST_OK`` only after the whole slot has passed (``manifest_load.c``),
so a TOC-defective primary never reports itself validated. Disabling the
manifest's secure-boot flag does not work either -- it is ignored in PROD
(``secure_boot_enabled``), the lifecycle this environment must run for the crypto
chain to be enforced at all. The trigger is therefore the shared
``corrupt_primary`` identifier corruption, a BAD_MAGIC refused before any hash or
crypto work, as for the other members of this family. The trigger is not the feature under test, and its error code is deliberately
different from the backup's so the two slots' rejections stay individually
countable.

The stimulus and the fixed selector mask are identical to the primary-side
sibling's; see that module for why the mask is 0x28 and why the fuse side's value
is not this testbench's to assert.
"""

from __future__ import annotations

import pyuvm

from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_usage_constraint_base import sep_backup_usage_constraint_base

_SELECTOR_MASK = 0x28
_REJECT_INDEX = 3


@pyuvm.test()
class sep_firmware_manifest_backup_invalid_chiplet_id_test(
        sep_backup_usage_constraint_base):
    """Backup enables chiplet_id words 3 and 5 -> both slots refused -> halt."""

    defect_marker = fd.CHIPLET_MARKER
    defect_evidence = fd.device_id_required_markers("chiplet_id", _REJECT_INDEX)

    def plant(self, buf: bytearray, slot: str) -> None:
        index = fd.plant_device_id_defect(buf, slot, "chiplet_id", _SELECTOR_MASK)
        assert index == _REJECT_INDEX, (
            f"selector mask 0x{_SELECTOR_MASK:02x} makes word {index} the lowest "
            f"enabled one, but this testcase asserts {_REJECT_INDEX}"
        )
        self.logger.info(
            "CHK-STIMULUS-CHIPLET-ID: %s selector_bits[0..7] = 0x%02x, so the ROM "
            "must read chiplet_id words %s and refuse on word %d",
            slot, _SELECTOR_MASK,
            [i for i in range(8) if _SELECTOR_MASK & (1 << i)], index,
        )

    def check_constraint_evidence(self, console: list[str]) -> None:
        fd.assert_device_id_mismatch(self.logger, console, "chiplet_id",
                                     _REJECT_INDEX)
