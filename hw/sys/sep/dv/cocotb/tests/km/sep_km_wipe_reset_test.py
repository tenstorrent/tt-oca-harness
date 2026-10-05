# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The KM recovers from a warm reset, and a SEP wipe request makes it post the wipe_state fault.

no_cpu / real fuse-sense / +km_rom_hex=rom_main.rom.parhex.

Warm-reset first: park and release the KM ``SW_RESET_N`` bit, wait for
``RESP_KM_READY``, and prove a key load still succeeds. Wipe last: write
``KM_WIPE_CTRL.wipe_state``. The KM posts ``RESP_UNRECOVERABLE_FAULT`` with
the ``wipe_state`` fault code and aggregator bit 30 (PIC source 31) asserts.
KPV-zero is not claimed -- those arrays have no SEP frontdoor.

Checkers:
  CHK0       rom_main boots and announces RESP_KM_READY.
  CHK-PRE    CMD_KEY_LOAD returns a handle before the warm reset.
  CHK-RESET  after a SW_RESET_N park and release the KM announces RESP_KM_READY
             again and CMD_KEY_LOAD returns a non-null handle.
  CHK-WIPE   a KM_WIPE_CTRL write posts RESP_UNRECOVERABLE_FAULT with the
             wipe_state fault code, and the aggregator bit asserts.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_reg_meta import SEP_CPU_CTRL
from env.sep_spec_tables import agg_from_pic
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import (
    KM_DEST_AES,
    KM_RESP_UNRECOVERABLE_FAULT,
    SepKmMailbox,
)

_KM_UNREC = agg_from_pic("KM unrecoverable error")

# RESP_UNRECOVERABLE_FAULT payload for a wipe: the `wipe_state` code (-1) from
# the Fault Codes table in hw/ip/key_manager/doc/firmware.adoc
# (km-resp-unrecoverable-fault). The payload is one word, the signed 8-bit code
# sign-extended to 32 bits. Every other cause in that table has a different
# code, so a fault from another cause fails CHK-WIPE.
_UFAULT_WIPE_STATE = -1
_UFAULT_WIPE_STATE_WORD = _UFAULT_WIPE_STATE & 0xFFFF_FFFF

# 256-bit known key so CHK-RESET is a real load, not a generate that
# depends on leftover DRBG state after the warm pulse.
_RESET_KEY = (
    0x11111111,
    0x22222222,
    0x33333333,
    0x44444444,
    0x55555555,
    0x66666666,
    0x77777777,
    0x88888888,
)


@pyuvm.test()
class sep_km_wipe_reset_test(sep_base_test):
    """The KM serves a key load after a warm reset, then a wipe posts the unrecoverable fault."""

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=0x1)
        self.write_efuse_image(image)
        await self.bring_up_no_cpu(park=("otbn", "kmac", "hmac"))

        self.km = SepKmMailbox(self)
        await self.bring_up_entropy(strict=True, score_km="observe")
        assert await self.wait_genbits(), "CSRNG CTR_DRBG never produced genbits"
        self.start_fifo_drain()

        await self.swrst.release("km")
        await self.km.wait_km_ready()
        self.logger.info("CHK0 PASS: rom_main booted, RESP_KM_READY over the mailbox")

        handle0 = await self.km.key_load(key_words=list(_RESET_KEY), dest=KM_DEST_AES)
        self.logger.info("CHK-PRE PASS: CMD_KEY_LOAD handle=0x%02x before warm reset", handle0)

        # --- CHK-RESET: park, release, ready, load again ---------------------
        await self.swrst.park("km")
        await self.swrst.release("km")
        self.km.reset_host_seq()
        await self.km.wait_km_ready()
        handle1 = await self.km.key_load(key_words=list(_RESET_KEY), dest=KM_DEST_AES)
        assert handle1 != 0, "CHK-RESET FAIL: post-reset CMD_KEY_LOAD returned a null handle"
        self.logger.info(
            "CHK-RESET PASS: SW_RESET_N park/release, RESP_KM_READY, CMD_KEY_LOAD handle=0x%02x",
            handle1,
        )

        # --- CHK-WIPE: SEP KM_WIPE_CTRL raises unrecoverable fault ------------
        await self.poll_internal_irq(_KM_UNREC, 0)
        wipe_addr = SEP_CPU_CTRL.addr("KM_WIPE_CTRL")
        seq = SepAxiAccessSeq(
            "km_wipe",
            op=SepAxiOp.WRITE,
            addr=wipe_addr,
            wdata=SEP_CPU_CTRL.field_mask("KM_WIPE_CTRL", "wipe_state"),
            size=2,
        )
        await self.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"CHK-WIPE FAIL: KM_WIPE_CTRL write @0x{wipe_addr:08x} not OKAY")
        words = await self.km.recv_unsolicited(KM_RESP_UNRECOVERABLE_FAULT, timeout=400_000)
        payload_len = (words[0] >> 16) & 0xFF
        assert payload_len == 1 and len(words) >= 2, (
            f"CHK-WIPE FAIL: unrecoverable frame payload_len={payload_len}, expected one "
            f"fault-code word ({[hex(w) for w in words]})"
        )
        assert words[1] == _UFAULT_WIPE_STATE_WORD, (
            f"CHK-WIPE FAIL: fault code 0x{words[1]:08x}, expected wipe_state "
            f"0x{_UFAULT_WIPE_STATE_WORD:08x} ({_UFAULT_WIPE_STATE})"
        )
        await self.poll_internal_irq(_KM_UNREC, 1)
        self.logger.info(
            "CHK-WIPE PASS: KM_WIPE_CTRL posted RESP_UNRECOVERABLE_FAULT "
            "payload=0x%08x == wipe_state code; aggregator [%d]=1",
            words[1],
            _KM_UNREC,
        )

        await self.stop_fifo_drain()
        await self.check_entropy_alerts_zero()
        assert self.drbg_sb.report()
        self.logger.info("entropy alerts clear and DRBG scoreboard reports PASS")
