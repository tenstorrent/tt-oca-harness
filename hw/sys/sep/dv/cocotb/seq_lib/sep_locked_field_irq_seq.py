# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shadow-word AXI driver for sep_locked_field_access_irq_path_test.

Config lives in ``env/sep_locked_field_irq.py`` so the pre-sim staging hook
can import it without cocotb.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SepEfuseImage

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver


class SepLockedFieldIrq(SepAxiRegDriver):
    """32-bit shadow-word access that returns the live AXI sequence."""

    _DRIVER_TAG = "LOCKIRQ"

    def _addr(self, name: str, word_idx: int = 0) -> int:
        fld = SepEfuseImage.field(name)
        if not 0 <= word_idx < fld.n_words:
            raise ValueError(f"{name} word {word_idx} out of range 0..{fld.n_words - 1}")
        return fld.shadow_addr + 4 * word_idx

    async def access(
        self,
        name: str,
        *,
        write: bool = False,
        wdata: int = 0,
        word_idx: int = 0,
        locked: bool = False,
    ) -> SepAxiAccessSeq:
        """One 32-bit shadow access.

        ``locked`` marks an access the lock refuses. The specification says only
        that such a shadow is not writable / not readable, so the scoreboard does
        not grade a locked access's response code. The caller grades a locked
        write by readback and the locked-field interrupt, and a locked read by
        its returned data and the locked-field interrupt. A timed-out locked
        read still fails the scoreboard. Because a locked read may complete
        with an error response and its data is graded, the bus monitor also
        lane-checks that beat for X/Z, which the driver would otherwise pass
        on as 0.
        """
        check_error_data = locked and not write
        mon = self.test.env.axi_monitor if check_error_data else None
        seq = SepAxiAccessSeq(
            f"lockirq_{'wr' if write else 'rd'}_{name}_w{word_idx}",
            op=SepAxiOp.WRITE if write else SepAxiOp.READ,
            addr=self._addr(name, word_idx),
            wdata=wdata,
            size=2,
            allow_unverified_write_resp=locked and write,
            allow_ungraded_read_resp=locked and not write,
        )
        if mon is not None:
            mon.open_error_rdata_window()
        try:
            await self.test.start_seq(seq)
        finally:
            if mon is not None:
                mon.close_error_rdata_window()
        return seq
