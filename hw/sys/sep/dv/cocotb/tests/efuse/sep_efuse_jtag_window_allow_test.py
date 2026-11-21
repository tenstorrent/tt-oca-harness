# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""At TEST_DEV, JTAG reaches the three eFuse windows and the shim window, and nothing else.

``sep_efuse_jtag_axil_el2_cpu_mux_test`` senses PROD, where the JTAG port
may reach the MMR token block and must be refused (SLVERR) on
the shadow map and on ``EFUSE_PROGRAM_CTRL``. This leaf senses TEST_DEV,
which is not a restricted lifecycle state, and reads a register of each of the
three windows: OKAY here and a refusal there is the per-window gate
(CHK-JTAG-WINDOW-ALLOW).

A JTAG read and a JTAG write of the first word and the first 8-byte-aligned word past
the registers of each window, and of the last two words of the page, answer as the SEP map states for that word
(CHK-JTAG-PAGE-UNBACKED; ``hw/sys/sep/regs/gen/adoc/memory_map.adoc``, row SEP eFuse
Wrapper Address Map; ``hw/sys/sep/doc/otp_fuse_controller.adoc:122-124``: JTAG and AXI
reach the same internal space).

A JTAG read and a JTAG write of ``EFUSE_BANK_INIT_TIME``, the shim window, answer OKAY
(CHK-JTAG-SHIM-ALLOW), the positive control of the PROD and RMA_SIP deny in
``sep_efuse_jtag_access_rand_test``, and the JTAG read-back after the write returns the
written value (CTRL-JTAG-SHIM-WRITE), so a JTAG write that reaches the shim register
shows at the read-back. The leaf writes the RDL reset value back.

Only the ``EFUSE_SHIM_SIZE`` bytes of the shim window reach the shim
(``hw/sys/sep/doc/memory_map.adoc:157-161``; ``hw/ip/efuse/doc/interface.adoc:54-57``:
the wrapper merges JTAG accesses to the shim window). JTAG writes of the complement of
the shim register value to the page words above and to 8-byte-aligned addresses outside
the page and the shim window leave the JTAG read-back of ``EFUSE_BANK_INIT_TIME``
unchanged (CHK-JTAG-OUTSIDE-NO-SHIM). The shim decodes address bits [2:0], so a write
that reached it at one of these addresses would land on that register. The response of
each access outside the page and the shim window is logged (OBS-JTAG-OUTSIDE-RESP): no
TT text states it.
"""

from __future__ import annotations

import pyuvm
from env.sep_decode_resp import expected_unbacked, sep_map_row
from env.sep_lcc_golden import LC_TEST_DEV
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym

_EFUSE_SHADOW_BASE = sym("SEP_EFUSE_WRAP_SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
_EFUSE_IFACE_PROGRAM = sym("SEP_EFUSE_WRAP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_REG_ADDR")
_EFUSE_MMR_MATCH = sym("SEP_EFUSE_WRAP_EFUSE_MMR_RMA_SIP_TOKEN_MATCH_REG_ADDR")
_WINDOW_ROWS = tuple(
    sep_map_row(sym(f"SEP_EFUSE_WRAP_{w}_REG_MAP_BASE_ADDR"))
    for w in ("EFUSE_INTERFACE_CTRL", "EFUSE_MMR", "SEP_EFUSE_MAP")
)
_PAGE_LO = _WINDOW_ROWS[0].base
_PAGE_HI = _WINDOW_ROWS[-1].end + 1
# The first word and the first 8-byte-aligned word past the registers of each window,
# and the last two words of the page. A JTAG write that reached the shim at an
# 8-byte-aligned word would land on the shim register.
_PAGE_UNBACKED = tuple(
    dict.fromkeys(
        (
            *(a for r in _WINDOW_ROWS for a in (r.past_from, (r.past_from + 7) & ~7)),
            _PAGE_HI - 8,
            _PAGE_HI - 4,
        )
    )
)
_SHIM = RegBlock("SEP_EXTERNAL_EFUSE_SHIM_CTRL")
_SHIM_REG = "EFUSE_BANK_INIT_TIME"
_SHIM_ADDR = _SHIM.addr(_SHIM_REG)
_SHIM_RESET = _SHIM.reset(_SHIM_REG)
# A value other than the reset value and 0, inside the field.
_SHIM_WDATA = (_SHIM_RESET << 1) & _SHIM.mask_all(_SHIM_REG)
_SHIM_HI = _SHIM_ADDR + sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_SIZE")
# 8-byte-aligned addresses outside the page and the shim window: below the page, the
# first above it, the first above the shim window, and the last of the 32-bit space.
_OUTSIDE = (_PAGE_LO - 8, _PAGE_HI, (_SHIM_HI + 7) & ~7, (1 << 32) - 8)
_M32 = 0xFFFF_FFFF
_MAX_SENSE_CYCLES = 20_000
_OKAY = 0


@pyuvm.test()
class sep_efuse_jtag_window_allow_test(sep_base_test):
    """TEST_DEV JTAG reads of the three eFuse windows and a JTAG read and write of the
    shim window return OKAY; the page words past the registers answer as the map states;
    JTAG writes outside the shim window leave the shim register unchanged.

    The LSU scoreboard counts CPU-master transactions. This leaf's
    transactions are on the JTAG AXI-Lite port, so that scoreboard is not
    built. The CHK lines are the verdict.
    """

    build_env = False
    # The TEST_DEV image must be sensed before the windows are read; the shared
    # backdoor compare of the sensed shadow is the proof of that step.
    required_evidence = (
        "CHK-SENSE-BACKDOOR",
        "CHK-JTAG-WINDOW-ALLOW",
        "CHK-JTAG-PAGE-UNBACKED",
        "CHK-JTAG-SHIM-ALLOW",
        "CHK-JTAG-OUTSIDE-NO-SHIM",
    )

    async def _allow(self, label: str, addr: int) -> None:
        code, rdata = await self.jtag_axil_op(write=False, addr=addr)
        assert code == _OKAY, (
            f"CHK-JTAG-WINDOW-ALLOW FAIL: JTAG {label} @0x{addr:08x} in "
            f"TEST_DEV must be OKAY; got resp={code} rdata=0x{rdata:08x}"
        )
        self.logger.info(
            "CHK-JTAG-WINDOW-ALLOW PASS: JTAG %s @0x%08x OKAY in TEST_DEV (rdata=0x%08x)",
            label,
            addr,
            rdata,
        )

    async def _shim_allow(self) -> None:
        """CHK-JTAG-SHIM-ALLOW: the JTAG read and the JTAG write of ``_SHIM_ADDR`` answer
        OKAY; CTRL-JTAG-SHIM-WRITE requires the JTAG read-back after the write to return
        the written value. OBS-JTAG-SHIM-ALLOW-DATA logs the read data, the read-back and
        the response codes of the read-back and of the restore write."""
        rd_code, rdata = await self.jtag_axil_op(write=False, addr=_SHIM_ADDR)
        wr_code, _ = await self.jtag_axil_op(write=True, addr=_SHIM_ADDR, wdata=_SHIM_WDATA)
        back_code, back = await self.jtag_axil_op(write=False, addr=_SHIM_ADDR)
        restore_code, _ = await self.jtag_axil_op(write=True, addr=_SHIM_ADDR, wdata=_SHIM_RESET)
        self.logger.info(
            "OBS-JTAG-SHIM-ALLOW-DATA addr=0x%08x rdata=0x%08x wdata=0x%08x readback=0x%08x "
            "readback_resp=%d restore=0x%08x restore_resp=%d",
            _SHIM_ADDR,
            rdata,
            _SHIM_WDATA,
            back,
            back_code,
            _SHIM_RESET,
            restore_code,
        )
        assert rd_code == _OKAY and wr_code == _OKAY, (
            f"CHK-JTAG-SHIM-ALLOW FAIL: JTAG read and write of the shim window "
            f"@0x{_SHIM_ADDR:08x} in TEST_DEV must be OKAY; got rd_resp={rd_code} "
            f"wr_resp={wr_code}"
        )
        self.logger.info(
            "CHK-JTAG-SHIM-ALLOW PASS: JTAG read and write @0x%08x OKAY in TEST_DEV "
            "(rd_resp=%d wr_resp=%d)",
            _SHIM_ADDR,
            rd_code,
            wr_code,
        )
        assert back_code == _OKAY and back == _SHIM_WDATA, (
            f"CTRL-JTAG-SHIM-WRITE FAIL: JTAG read-back @0x{_SHIM_ADDR:08x} must return the "
            f"written 0x{_SHIM_WDATA:08x}; got resp={back_code} data=0x{back:08x}"
        )
        self.logger.info(
            "CTRL-JTAG-SHIM-WRITE PASS: JTAG read-back @0x%08x returns the written 0x%08x",
            _SHIM_ADDR,
            back,
        )

    async def _page_unbacked(self, wdata: int) -> None:
        """CHK-JTAG-PAGE-UNBACKED: per word of ``_PAGE_UNBACKED``, the JTAG read response
        and data and the JTAG write response of the SEP map."""
        for addr in _PAGE_UNBACKED:
            rd, wr = expected_unbacked(addr, "r"), expected_unbacked(addr, "w")
            rd_code, rdata = await self.jtag_axil_op(write=False, addr=addr)
            wr_code, _ = await self.jtag_axil_op(write=True, addr=addr, wdata=wdata)
            line = (
                f"addr=0x{addr:08x} row={rd.row} rd_resp={rd_code} rdata=0x{rdata:08x} "
                f"wr_resp={wr_code} exp_rd_resp={rd.resp} exp_rdata=0x{rd.rdata:08x} "
                f"exp_wr_resp={wr.resp}"
            )
            assert (rd_code, rdata, wr_code) == (rd.resp, rd.rdata, wr.resp), (
                f"CHK-JTAG-PAGE-UNBACKED FAIL: {line}"
            )
            self.logger.info("CHK-JTAG-PAGE-UNBACKED PASS: %s", line)

    async def _outside_no_shim(self) -> None:
        """CHK-JTAG-OUTSIDE-NO-SHIM: JTAG writes of the complement of the shim register
        value to the unbacked page words and to ``_OUTSIDE`` leave the JTAG read-back of
        the shim register unchanged. OBS-JTAG-OUTSIDE-RESP logs each outside response."""
        before_code, before = await self.jtag_axil_op(write=False, addr=_SHIM_ADDR)
        wdata = ~before & _M32
        await self._page_unbacked(wdata)
        for addr in _OUTSIDE:
            rd_code, rdata = await self.jtag_axil_op(write=False, addr=addr)
            wr_code, _ = await self.jtag_axil_op(write=True, addr=addr, wdata=wdata)
            self.logger.info(
                "OBS-JTAG-OUTSIDE-RESP addr=0x%08x rd_resp=%d rdata=0x%08x wr_resp=%d",
                addr,
                rd_code,
                rdata,
                wr_code,
            )
        after_code, after = await self.jtag_axil_op(write=False, addr=_SHIM_ADDR)
        line = (
            f"reg=0x{_SHIM_ADDR:08x} before=0x{before:08x} before_resp={before_code} "
            f"after=0x{after:08x} after_resp={after_code} wdata=0x{wdata:08x} "
            f"writes={len(_PAGE_UNBACKED) + len(_OUTSIDE)}"
        )
        assert before_code == _OKAY and after_code == _OKAY and after == before, (
            f"CHK-JTAG-OUTSIDE-NO-SHIM FAIL: {line}"
        )
        self.logger.info("CHK-JTAG-OUTSIDE-NO-SHIM PASS: %s", line)

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(lc_raw=LC_TEST_DEV)
        assert image.lc_raw() == LC_TEST_DEV, (
            f"test bug: image LC_STATE is not TEST_DEV (0x{image.lc_raw():x}); "
            "a restricted image would refuse these windows"
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self._allow("shadow", _EFUSE_SHADOW_BASE)
        await self._allow("EFUSE_PROGRAM_CTRL", _EFUSE_IFACE_PROGRAM)
        await self._allow("RMA_SIP_TOKEN_MATCH", _EFUSE_MMR_MATCH)
        await self._shim_allow()
        await self._outside_no_shim()
