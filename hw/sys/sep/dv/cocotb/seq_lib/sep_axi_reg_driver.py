# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base for direct-AXI register drivers on the SEP CPU-LSU bus.

The OpenTitan crypto run-control drivers (AES/HMAC/KMAC/OTBN) and the CSRNG/EDN
interrupt driver all issue the same single-beat 32-bit register read/write through
the SEP AXI agent and fail on a non-OKAY response. This mixin holds that one
``_wr`` / ``_rd`` pair so the response handling lives in one place.

A subclass sets ``_DRIVER_TAG`` (used in the assert message and the
``SepAxiAccessSeq`` name) and inherits ``__init__`` / ``_wr`` / ``_rd``. The test
owns one instance: ``self.aes = SepAes(self)``. All accesses are 32-bit beats
(``size=2``) via the wrapper's 64->32 dw-converter; a subclass that needs the
full bus width can override ``_AXI_SIZE``.

``SepAxiDriver(uvm_driver)`` in ``env.sep_axi_agent`` is the cocotb AXI driver
component, a different class from this mixin.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq


class SepAxiRegDriver:
    """Shared direct-AXI register access for SEP run-control drivers."""

    # Subclasses override this; it labels the access in error messages and the
    # sequence name (e.g. "AES" -> seq names "aes_wr"/"aes_rd").
    _DRIVER_TAG = "AXI"
    # AXI AxSIZE encoding (2 => 4-byte beat). None => the agent's bus width.
    _AXI_SIZE: int | None = 2

    def __init__(self, test, *, logger=None) -> None:
        self.test = test
        self.log = logger if logger is not None else test.logger

    async def _wr(self, addr: int, data: int) -> None:
        seq = SepAxiAccessSeq(
            f"{self._DRIVER_TAG.lower()}_wr",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            size=self._AXI_SIZE,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"{self._DRIVER_TAG} write @0x{addr:08x} not OKAY")

    async def _rd(self, addr: int) -> int:
        seq = SepAxiAccessSeq(
            f"{self._DRIVER_TAG.lower()}_rd",
            op=SepAxiOp.READ,
            addr=addr,
            size=self._AXI_SIZE,
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"{self._DRIVER_TAG} read @0x{addr:08x} not OKAY")
        return seq.rdata
