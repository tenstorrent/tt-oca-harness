# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for dtp_jtag_zero_length_bypass_test.

The single-TAP leg checks ZERO_LENGTH_BYPASS pass-through against a plain
BYPASS reference. The chain leg selects a seeded STAP with a downstream TAP
behind it and scans the same chain under ZERO_LENGTH_BYPASS and then under
BYPASS: the marker leaves TDO right after the STAP chain alone, then one TCK
later, behind the bypass register's captured 0. The SV-UVM twin is
``uvm/seq_lib/dtp_jtag_zero_length_bypass_test_seq.svh``.
"""

from __future__ import annotations

from env.dtp_scan_ref_model import SCAN_MARKER_WIDTH
from env.dtp_stap_ds_agent import STAP_DS_TDR_NAME
from env.dtp_types import DtpJtagInstr

from .dtp_scan_base_test_seq import dtp_scan_base_test_seq


class dtp_jtag_zero_length_bypass_test_seq(dtp_scan_base_test_seq):
    """Run ZERO_LENGTH_BYPASS pass-through checks, alone and in a STAP chain."""

    # STAP host ports the chain leg splices. Under ZERO_LENGTH_BYPASS the I/O
    # STAP's host TDO lockup samples TDI itself on the falling TCK edge, so
    # the length of its splice depends on when the master changes TDI.
    CHAIN_STAPS = ("smc", "sep", "extra0")

    async def body(self) -> None:
        await self.attach_family_checker(
            {
                "CHK-TAP-RESET-TLR",
                "CHK-ZLB-PASSTHROUGH",
                "CHK-BYPASS-DELAY",
                "CHK-ZLB-CHAIN-ALIGN",
                "CHK-SCAN-CHAIN",
                "CHK-SCAN-COUNT",
                "CHK-SCAN-IR-LEN",
                "CHK-SCAN-DR-LEN",
                "CHK-NONVAC",
            },
        )
        self.attach_downstream_taps()
        await self.reset_to_tlr()
        await self.check_zero_length_bypass_patterns(width=64)
        await self.check_bypass_delay(0x3F, 0xA5A5_5A5A_C3C3_3C3C)
        await self.check_zero_length_bypass_chain()
        await self.finalize_family_checker()

    async def check_zero_length_bypass_chain(self) -> None:
        """Scan one STAP chain under ZERO_LENGTH_BYPASS and under BYPASS.

        With the PTAP 3DCR select set, a seeded STAP selected, and its
        downstream TAP on ``DS_TDR``, a ZERO_LENGTH_BYPASS scan writes a
        seeded ``DS_TDR`` value and a maintain scan reads the chain back
        (``CHK-SCAN-CHAIN``); under BYPASS the same chain reads back with
        the bypass register ahead of it. Every scan carries a marker whose
        position proves how many bits the PTAP adds (``CHK-ZLB-CHAIN-ALIGN``).
        """
        rng = self.rng("zlb_chain")
        stap = rng.choice(self.CHAIN_STAPS)
        assert self.ds_attached(stap), f"no downstream TAP behind STAP {stap}"
        ds = self.stap_model.downstream[stap]
        value = rng.getrandbits(ds.reg(STAP_DS_TDR_NAME).width)
        marker = rng.getrandbits(SCAN_MARKER_WIDTH) | (1 << (SCAN_MARKER_WIDTH - 1))
        payload = {"config_hold": rng.randrange(2), "stap_sel": 1, "tms_hold": rng.randrange(2)}
        ctx = f"zlb_chain.{stap}"
        self.log_banner(f"ZERO_LENGTH_BYPASS in the STAP chain: {stap}")
        self.log.info(
            "%s %s=0x%x marker=0x%04x 3DCR payload=%s",
            ctx,
            STAP_DS_TDR_NAME,
            value,
            marker,
            payload,
        )

        self.log_step(1, "Select STAP %s with composed TAP_3DCR scans", stap)
        await self.stap_chain_flush(context=f"{ctx}.flush")
        await self.stap_chain_write(
            ptap_select=1, ptap_config_hold=1, sib_en={stap: 1}, context=f"{ctx}.open_sib"
        )
        await self.stap_chain_write(payloads={stap: payload}, context=f"{ctx}.select")

        self.log_step(2, "One network-wide IR scan: ZERO_LENGTH_BYPASS and downstream DS_TDR")
        await self.stap_chain_ir_write(
            ptap_instr=DtpJtagInstr.ZERO_LENGTH_BYPASS,
            ds_ir={stap: ds.opcode_of(STAP_DS_TDR_NAME)},
            context=f"{ctx}.load_zlb",
        )

        self.log_step(3, "ZERO_LENGTH_BYPASS: write DS_TDR through the chain, then read it back")
        captured = await self.stap_chain_write(
            ds_values={stap: value}, marker=marker, context=f"{ctx}.zlb_write", scan_kind="zlb"
        )
        self.check_zlb_chain_align(captured, marker, scan_kind="zlb", context=f"{ctx}.zlb_write")
        captured = await self.stap_chain_maintain(
            marker=marker, context=f"{ctx}.zlb_read", scan_kind="zlb"
        )
        self.check_stap_chain_readback(captured, context=f"{ctx}.zlb_read", scan_kind="zlb")
        self.check_zlb_chain_align(captured, marker, scan_kind="zlb", context=f"{ctx}.zlb_read")

        self.log_step(4, "BYPASS: the same chain reads back behind the bypass register")
        await self.stap_chain_ir_write(
            ptap_instr=DtpJtagInstr.BYPASS_3F, context=f"{ctx}.load_bypass"
        )
        captured = await self.stap_chain_maintain(
            marker=marker, context=f"{ctx}.bypass_read", scan_kind="bypass"
        )
        self.check_stap_chain_readback(captured, context=f"{ctx}.bypass_read", scan_kind="bypass")
        self.check_zlb_chain_align(
            captured, marker, scan_kind="bypass", context=f"{ctx}.bypass_read"
        )

        chain_len = len(self.stap_model.chain_layout(None, "zlb"))
        await self.stap_chain_flush(context=f"{ctx}.cleanup")
        self.log_summary(
            "ZERO_LENGTH_BYPASS chain",
            stap=stap,
            ds_tdr=f"0x{value:x}",
            marker=f"0x{marker:04x}",
            chain_len=chain_len,
        )

    def check_zlb_chain_align(
        self, captured: int, marker: int, *, scan_kind: str, context: str
    ) -> None:
        """``CHK-ZLB-CHAIN-ALIGN``: under ZERO_LENGTH_BYPASS the marker leaves
        TDO right after the STAP chain; under BYPASS the bit after the chain
        is the bypass register's captured 0 and the marker follows it.

        Valid after a scan that leaves the chain layout as it found it, such
        as a maintain scan or a downstream register write.
        """
        assert scan_kind in ("zlb", "bypass"), f"no alignment rule for a {scan_kind} scan"
        chain_len = len(self.stap_model.chain_layout(None, "zlb"))
        ptap_bits = 1 if scan_kind == "bypass" else 0
        name = (
            "BYPASS: captured 0, then the marker"
            if ptap_bits
            else "ZERO_LENGTH_BYPASS: marker right after the STAP chain"
        )
        self.family_check(
            "CHK-ZLB-CHAIN-ALIGN",
            name,
            (captured >> chain_len) & self.bit_mask(SCAN_MARKER_WIDTH + ptap_bits),
            marker << ptap_bits,
            context=(
                f"{context} chain_len={chain_len} "
                f"latency={captured.bit_length() - SCAN_MARKER_WIDTH} captured=0x{captured:x}"
            ),
        )
