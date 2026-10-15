# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DRBG bring-up with an EDN mode that the leaf chooses.

``drbg_bring_up`` runs the first part of ``SepBaseTest.bring_up_entropy``: the
DRBG scoreboard noise, ``SepEsrcConfigSeq`` (TRNG reset, ESRC configuration with
the generators off, CSRNG enable, EDN commands staged), ``SepEsrcEnableGeneratorsSeq``
and the wait for the first seed. Then it writes EDN ``CTRL`` once with the value
that the leaf passes, or not at all with ``edn_ctrl=None``. It writes no
``FIPS_LOCK``.

The scoreboard runs with ``strict=False`` by default: a leaf that uses this
helper grades register state, not data. The leaf calls ``stop()`` on the
returned scoreboard before each TRNG reset that ends the bring-up.

Usage::

    sb = await drbg_bring_up(self, edn_ctrl=EDN.value("CTRL", EDN_ENABLE=6, CMD_FIFO_RST=9))
    ...
    sb.stop()
"""

from __future__ import annotations

import cocotb
from pyuvm import uvm_sequence
from sep_reg_meta import sym

from seq_lib.sep_esrc_bringup_seq import (
    SepEntropyCfg,
    SepEsrcConfigSeq,
    SepEsrcEnableGeneratorsSeq,
    _wr,
)

EDN_CTRL = sym("EDN_CTRL_REG_ADDR")


class SepEdnCtrlWriteSeq(uvm_sequence):
    """One write of EDN ``CTRL``."""

    def __init__(self, name: str = "edn_ctrl_write", *, value: int) -> None:
        super().__init__(name)
        self.value = value

    async def body(self) -> None:
        await _wr(self, EDN_CTRL, self.value)


async def drbg_bring_up(
    test,
    *,
    edn_ctrl: int | None = None,
    strict: bool = False,
    cfg: SepEntropyCfg | None = None,
):
    """Bring up ESRC, CSRNG and the first seed, then write EDN ``CTRL`` = ``edn_ctrl``.

    Returns the started ``SepDrbgScoreboard`` (also ``test.drbg_sb``). Raises if
    no seed reaches CSRNG within the ``wait_seed_ready`` bound.
    """
    from env.sep_drbg_scoreboard import SepDrbgScoreboard

    if cfg is None:
        cfg = SepEntropyCfg()
    test.entropy_cfg = cfg
    sb = SepDrbgScoreboard(
        cocotb.top,
        test.logger,
        strict=strict,
        golden_kwargs=cfg.golden_kwargs(),
        chk2_backdoor=cfg.chk2_backdoor,
        score_km=False,
    )
    test.drbg_sb = sb
    sb.start()
    await test.assert_noise_force_active()
    await test.start_seq(SepEsrcConfigSeq("esrc_config", cfg=cfg))
    await test.start_seq(SepEsrcEnableGeneratorsSeq("esrc_enable_gens"))
    if not await test.wait_seed_ready():
        await test.report_entropy_stall()
        sb.stop()
        raise AssertionError("DRBG-BRING-UP: ESRC never produced a seed (drbg_seed_valid_o)")
    if edn_ctrl is not None:
        await test.start_seq(SepEdnCtrlWriteSeq("edn_ctrl_write", value=edn_ctrl))
    test.logger.info(
        "DRBG-BRING-UP seed=1 edn_ctrl=%s strict=%s",
        "none" if edn_ctrl is None else f"0x{edn_ctrl:08x}",
        strict,
    )
    return sb
