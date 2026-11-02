# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bit map of the SEP RAS struct on the bench tap ``sep_ras_probe_o``.

The tap carries the packed ``sep_pkg::sep_ras_t`` (``hw/sys/sep/rtl/sep_pkg.sv``,
"RAS" section). ``periph_bus_err`` bit ``k`` belongs to the block at index ``k``
of ``periph_bus_err_e`` in the same package.

Usage::

    watch = SepBitWatch(dut.sep_ras_probe_o, bits={"wdt_bark": ras_bit("wdt_bark")})
    aes = ras_field(int(dut.sep_ras_probe_o.value), "periph_bus_err", 0)
"""

from __future__ import annotations

from typing import Any

from env.sep_chk_log import _fmt

PERIPH_BUS_ERR_BLOCKS: tuple[str, ...] = ("aes", "hmac", "kmac", "otbn", "csrng", "edn", "wdt")

RAS_FIELDS: tuple[tuple[str, int], ...] = (
    ("lc_sigint_err", 1),
    ("lockstep_err", 1),
    ("wdt_bark", 1),
    ("wdt_bite", 1),
    ("iccm_ecc_ce", 1),
    ("iccm_ecc_ue", 1),
    ("dccm_ecc_ce", 1),
    ("dccm_ecc_ue", 1),
    ("km_uncorrectable", 1),
    ("km_correctable", 1),
    ("dma_alert", 1),
    ("dma_reg_bus_err", 1),
    ("dma_host_intg_err", 1),
    ("periph_bus_err", len(PERIPH_BUS_ERR_BLOCKS)),
    ("csrng_fatal", 1),
    ("edn_fatal", 1),
    ("crypto_alert", 1),
    ("entropy_fill_stall", 1),
    ("entropy_pool_err", 1),
    ("token_match_fault", 1),
)

# A packed struct puts its first declared field at the MSB, so each field's LSB
# is the sum of the widths declared after it, and the total is $bits(sep_ras_t).
RAS_WIDTH = 26
RAS_LSB: dict[str, int] = {}
RAS_FIELD_WIDTH: dict[str, int] = dict(RAS_FIELDS)
_lsb = sum(w for _, w in RAS_FIELDS)
for _name, _w in RAS_FIELDS:
    _lsb -= _w
    RAS_LSB[_name] = _lsb
if sum(RAS_FIELD_WIDTH.values()) != RAS_WIDTH:
    raise RuntimeError(
        f"sep_ras_t field widths sum to {sum(RAS_FIELD_WIDTH.values())}, expected {RAS_WIDTH}"
    )


def ras_bit(name: str, k: int = 0) -> int:
    """Return the tap bit index of field ``name`` (bit ``k`` of a vector field)."""
    if not 0 <= k < RAS_FIELD_WIDTH[name]:
        raise IndexError(f"{name}[{k}] is outside the field width {RAS_FIELD_WIDTH[name]}")
    return RAS_LSB[name] + k


def ras_field(value: int, name: str, k: int | None = None) -> int:
    """Return field ``name`` of a tap value; with ``k``, only its bit ``k``."""
    if k is not None:
        return (value >> ras_bit(name, k)) & 1
    return (value >> RAS_LSB[name]) & ((1 << RAS_FIELD_WIDTH[name]) - 1)


def check_tap_width(probe) -> None:
    """Raise if the bench tap ``probe`` is not ``RAS_WIDTH`` bits wide."""
    if len(probe) != RAS_WIDTH:
        raise RuntimeError(f"{probe._name} is {len(probe)} bits, sep_ras_t is {RAS_WIDTH}")


class RasChkLines:
    """Graded RAS lines of a leaf that has no ``SepChkLog``, in the form it prints.

    ``ok(name, cond, **fields)`` logs ``CHK-<name> PASS: seed=<n> <fields>`` or
    ``CHK-<name> FAIL: seed=<n> <fields>`` and keeps each FAIL line in ``fails``,
    so the leaf can report every half and raise once at its end.
    ``obs(name, **fields)`` logs ``OBS-<name> seed=<n> <fields>`` and grades nothing.
    """

    def __init__(self, logger: Any, seed: int) -> None:
        self._log = logger
        self._seed = seed
        self.fails: list[str] = []

    def _line(self, head: str, fields: dict[str, Any]) -> str:
        parts = [head, f"seed={self._seed}"]
        parts += [f"{k}={_fmt(v)}" for k, v in fields.items()]
        return " ".join(parts)

    def ok(self, name: str, cond: bool, **fields: Any) -> bool:
        cond = bool(cond)
        line = self._line(f"CHK-{name} {'PASS' if cond else 'FAIL'}:", fields)
        if cond:
            self._log.info(line)
        else:
            self._log.error(line)
            self.fails.append(line)
        return cond

    def obs(self, name: str, **fields: Any) -> None:
        self._log.info(self._line(f"OBS-{name}", fields))
