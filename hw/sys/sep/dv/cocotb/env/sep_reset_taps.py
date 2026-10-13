# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Isolate-vector and reset-tap sampler with the VPLAN bench index.

``tb_top`` brings out the 14-bit isolate request and isolate-complete vectors
of the crypto AXI interconnect (``crypto_isolate_req_probe_o``,
``crypto_isolated_probe_o``) with bit ``x`` the VPLAN bench isolate stage
``x`` (``docs/SEP_TB_ARCH.adoc``, crypto reset-sequencer probes), and one port
per sequenced engine reset (``*_gated_rst_n_probe_o``). The index is a table
that resolves a path name; it is never an expected value.

Isolate stage ``x`` (VPLAN bench index, bit ``x`` of each vector):

==  ====================  ==  ====================
x   path                  x   path
==  ====================  ==  ====================
0   host_otbn             7   trng_edn
1   host_aes              8   km_otbn
2   host_hmac             9   km_aes
3   host_kmac             10  km_hmac
4   host_abr              11  km_kmac
5   trng_entropy_source   12  km_abr
6   trng_csrng            13  km_efuse
==  ====================  ==  ====================

Engine reset ``ip_rst_n[i]``: 0 Key Manager, 1 OTBN, 2 AES, 3 HMAC, 4 KMAC,
5 TRNG, 6 Adams Bridge (the ``SW_RESET_N`` bit number).

The sampler reads every tap on each rising edge of ``clk_i`` in the read-only
phase through ``SepBitWatch`` and drives nothing.

Usage::

    taps = SepResetTaps().start()
    taps.log_map(log)
    m = taps.mark()
    ...write SW_RESET_N...
    await taps.iso_req.wait_rise(m["iso_req"], bound=200, bit=iso_name(0))
    taps.ip_rst[1].fall_clks_since(m["ip_rst_1"])
"""

from __future__ import annotations

from typing import Any

import cocotb
from sep_bit_watch import BitMark, SepBitWatch

# VPLAN bench index x -> path name.
ISO_BENCH: tuple[str, ...] = (
    "host_otbn",
    "host_aes",
    "host_hmac",
    "host_kmac",
    "host_abr",
    "trng_entropy_source",
    "trng_csrng",
    "trng_edn",
    "km_otbn",
    "km_aes",
    "km_hmac",
    "km_kmac",
    "km_abr",
    "km_efuse",
)
ISO_WIDTH = len(ISO_BENCH)

# ip_rst_n[i] -> tb_top port.
IP_RST_PORTS: tuple[str, ...] = (
    "km_gated_rst_n_probe_o",
    "otbn_gated_rst_n_probe_o",
    "aes_gated_rst_n_probe_o",
    "hmac_gated_rst_n_probe_o",
    "kmac_gated_rst_n_probe_o",
    "trng_gated_rst_n_probe_o",
    "abr_gated_rst_n_probe_o",
)
IP_RST_NAMES: tuple[str, ...] = ("km", "otbn", "aes", "hmac", "kmac", "trng", "abr")

# Reset taps that are single ports of tb_top.
RESET_TAP_PORTS: dict[str, str] = {
    "sep_reset_n": "dbg_sep_reset_n_o",
    "sep_cpu_reset_n": "sep_cpu_reset_n_o",
    "aon_rst_n": "aon_rst_n_probe_o",
}


def iso_name(x: int) -> str:
    """Watcher bit name of bench isolate stage ``x``."""
    return f"x{x}_{ISO_BENCH[x]}"


class SepResetTaps:
    """Per-clock sampler of the isolate vectors and the reset taps."""

    def __init__(self, dut: Any = None, *, xz_fail: bool = True) -> None:
        self.dut = dut if dut is not None else cocotb.top
        bits = {iso_name(x): x for x in range(ISO_WIDTH)}
        self.iso_req = SepBitWatch(
            self.dut.crypto_isolate_req_probe_o,
            bits,
            name="iso_req",
            dut=self.dut,
            xz_fail=xz_fail,
        )
        self.iso_ack = SepBitWatch(
            self.dut.crypto_isolated_probe_o,
            dict(bits),
            name="iso_ack",
            dut=self.dut,
            xz_fail=xz_fail,
        )
        self.ip_rst: dict[int, SepBitWatch] = {
            i: SepBitWatch(
                getattr(self.dut, port), name=f"ip_rst_n[{i}]", dut=self.dut, xz_fail=xz_fail
            )
            for i, port in enumerate(IP_RST_PORTS)
        }
        self.resets: dict[str, SepBitWatch] = {
            name: SepBitWatch(getattr(self.dut, port), name=name, dut=self.dut, xz_fail=xz_fail)
            for name, port in RESET_TAP_PORTS.items()
        }
        self.km_cond = SepBitWatch(
            self.dut.km_cond_rst_probe_o,
            {"rst_warm_sync_n": 0, "rst_cold_aasd_n": 1},
            name="km_cond_rst",
            dut=self.dut,
            xz_fail=xz_fail,
        )

    def _watchers(self) -> dict[str, SepBitWatch]:
        w: dict[str, SepBitWatch] = {"iso_req": self.iso_req, "iso_ack": self.iso_ack}
        w.update({f"ip_rst_{i}": s for i, s in self.ip_rst.items()})
        w.update(self.resets)
        w["km_cond_rst"] = self.km_cond
        return w

    def start(self) -> "SepResetTaps":
        for w in self._watchers().values():
            w.start()
        return self

    async def stop(self) -> None:
        for w in self._watchers().values():
            await w.stop()

    def mark(self) -> dict[str, BitMark]:
        """One mark per watcher, keyed ``iso_req``, ``iso_ack``, ``ip_rst_<i>``,
        the ``RESET_TAP_PORTS`` names and ``km_cond_rst``."""
        return {k: w.mark() for k, w in self._watchers().items()}

    def iso_req_now(self) -> int | None:
        """Current isolate request vector in bench order (None on X or Z)."""
        return _bench_now(self.dut.crypto_isolate_req_probe_o)

    def iso_ack_now(self) -> int | None:
        """Current isolate-complete vector in bench order (None on X or Z)."""
        return _bench_now(self.dut.crypto_isolated_probe_o)

    def ip_rst_n_now(self) -> int | None:
        """Current ``ip_rst_n[6:0]`` in bench order (None on X or Z)."""
        val = 0
        for i, port in enumerate(IP_RST_PORTS):
            v = getattr(self.dut, port).value
            if not v.is_resolvable:
                return None
            val |= (int(v) & 1) << i
        return val

    @staticmethod
    def log_map(log) -> None:
        """Log the bench index tables the leaf uses."""
        for x in range(ISO_WIDTH):
            log.info("OBS-ISO-MAP: x=%d path=%s", x, ISO_BENCH[x])
        for i, port in enumerate(IP_RST_PORTS):
            log.info("OBS-IPRST-MAP: i=%d engine=%s port=%s", i, IP_RST_NAMES[i], port)


def _bench_now(sig) -> int | None:
    v = sig.value
    if not v.is_resolvable:
        return None
    return int(v)
