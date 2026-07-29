# SPDX-License-Identifier: Apache-2.0
"""Hierarchical AXI-Lite single-beat helpers (Force/Release on packed req).

Verilator notes:
  - Prefer packed-word Force (forceable net); keep an RMW shadow.
  - Force with an explicit 111-bit LogicArray so VforceEn covers all bits
    (narrow int Forces can leak continuous-driver bits into upper words).
  - CTN NO_LATENCY demux: idle aw_ready often 0; idle ar_ready often 1.
  - Hold valids until the response beat (r_valid / b_valid); do not drop
    AR on the first ar_ready sample (false idle ready before DUT sees valid).
"""

from __future__ import annotations

from typing import Any

from cocotb.handle import Force, Release
from cocotb.triggers import FallingEdge, RisingEdge
from cocotb.types import LogicArray, Range

_AXIL_REQ_BITS = {
    "aw_addr": (110, 79),
    "aw_prot": (78, 76),
    "aw_valid": (75, 75),
    "w_data": (74, 43),
    "w_strb": (42, 39),
    "w_valid": (38, 38),
    "b_ready": (37, 37),
    "ar_addr": (36, 5),
    "ar_prot": (4, 2),
    "ar_valid": (1, 1),
    "r_ready": (0, 0),
}
_AXIL_REQ_WIDTH = 111

_AXIL_RESP_BITS = {
    "aw_ready": (40, 40),
    "w_ready": (39, 39),
    "b_resp": (38, 37),
    "b_valid": (36, 36),
    "ar_ready": (35, 35),
    "r_data": (34, 3),
    "r_resp": (2, 1),
    "r_valid": (0, 0),
}

_AXIL_REQ_FORCE_SHADOW: dict[int, int] = {}


def _packed_width(handle: Any) -> int | None:
    try:
        return len(handle.value)
    except Exception:
        return None


def _is_hier_req(req: Any) -> bool:
    width = _packed_width(req)
    if width is not None and width >= 100:
        return False
    return hasattr(req, "aw_valid")


def _is_hier_resp(resp: Any) -> bool:
    width = _packed_width(resp)
    if width is not None and width >= 32:
        return False
    return hasattr(resp, "aw_ready")


def _bit_get(word: int, hi: int, lo: int) -> int:
    return (int(word) >> lo) & ((1 << (hi - lo + 1)) - 1)


def _bit_set(word: int, hi: int, lo: int, val: int) -> int:
    width = hi - lo + 1
    mask = ((1 << width) - 1) << lo
    return (int(word) & ~mask) | ((int(val) & ((1 << width) - 1)) << lo)


def axil_req_get(req: Any, field: str) -> int:
    if _is_hier_req(req):
        if field == "aw_addr":
            return int(req.aw.addr.value) & 0xFFFFFFFF
        if field == "aw_prot":
            return int(req.aw.prot.value)
        if field == "w_data":
            return int(req.w.data.value) & 0xFFFFFFFF
        if field == "w_strb":
            return int(req.w.strb.value) & 0xF
        if field == "ar_addr":
            return int(req.ar.addr.value) & 0xFFFFFFFF
        if field == "ar_prot":
            return int(req.ar.prot.value)
        return int(getattr(req, field).value)
    hi, lo = _AXIL_REQ_BITS[field]
    key = id(req)
    if key in _AXIL_REQ_FORCE_SHADOW:
        return _bit_get(_AXIL_REQ_FORCE_SHADOW[key], hi, lo)
    return _bit_get(int(req.value), hi, lo)


def axil_resp_get(resp: Any, field: str) -> int:
    if _is_hier_resp(resp):
        if field == "b_resp":
            return int(resp.b.resp.value)
        if field == "r_data":
            return int(resp.r.data.value) & 0xFFFFFFFF
        if field == "r_resp":
            return int(resp.r.resp.value)
        return int(getattr(resp, field).value)
    hi, lo = _AXIL_RESP_BITS[field]
    return _bit_get(int(resp.value), hi, lo)


def _force_req_fields(req: Any, updates: dict[str, int]) -> None:
    if _is_hier_req(req):
        for field, val in updates.items():
            if field == "aw_addr":
                req.aw.addr.value = Force(val & 0xFFFFFFFF)
            elif field == "aw_prot":
                req.aw.prot.value = Force(val)
            elif field == "w_data":
                req.w.data.value = Force(val & 0xFFFFFFFF)
            elif field == "w_strb":
                req.w.strb.value = Force(val & 0xF)
            elif field == "ar_addr":
                req.ar.addr.value = Force(val & 0xFFFFFFFF)
            elif field == "ar_prot":
                req.ar.prot.value = Force(val)
            else:
                getattr(req, field).value = Force(val)
        return

    key = id(req)
    word = int(_AXIL_REQ_FORCE_SHADOW.get(key, 0))
    for field, val in updates.items():
        hi, lo = _AXIL_REQ_BITS[field]
        word = _bit_set(word, hi, lo, val)
    # Full-width Force so Verilator VforceEn covers bits [110:0].
    req.value = Force(
        LogicArray.from_unsigned(word & ((1 << _AXIL_REQ_WIDTH) - 1), Range(110, 0))
    )
    _AXIL_REQ_FORCE_SHADOW[key] = word


async def axil_hier_write32(
    clk,
    req: Any,
    resp: Any,
    addr: int,
    data: int,
    *,
    wstrb: int = 0xF,
    timeout_cycles: int = 64,
) -> int:
    """Issue one AXI-Lite write; return bresp (0=OKAY).

    Hold AW+W until b_valid. CTM PeakRDL needs both channels; CTN demux
    accepts AW into its W-select FIFO then W.
    """
    _force_req_fields(
        req,
        {
            "aw_valid": 0,
            "w_valid": 0,
            "ar_valid": 0,
            "b_ready": 1,
            "r_ready": 1,
        },
    )
    await RisingEdge(clk)
    _force_req_fields(
        req,
        {
            "aw_addr": addr & 0xFFFFFFFF,
            "aw_prot": 0,
            "aw_valid": 1,
            "w_data": data & 0xFFFFFFFF,
            "w_strb": wstrb & 0xF,
            "w_valid": 1,
            "ar_valid": 0,
            "b_ready": 1,
            "r_ready": 1,
        },
    )

    aw_done = w_done = False
    for _ in range(timeout_cycles):
        await FallingEdge(clk)
        if (not aw_done) and axil_req_get(req, "aw_valid") and axil_resp_get(
            resp, "aw_ready"
        ):
            aw_done = True
        if (not w_done) and axil_req_get(req, "w_valid") and axil_resp_get(
            resp, "w_ready"
        ):
            w_done = True
        if axil_resp_get(resp, "b_valid"):
            bresp = axil_resp_get(resp, "b_resp")
            await RisingEdge(clk)
            _force_req_fields(req, {"aw_valid": 0, "w_valid": 0, "b_ready": 1})
            await RisingEdge(clk)
            _release_req(req)
            return bresp
        if aw_done and w_done:
            # Drop valids after both channels accepted; keep b_ready for B.
            await RisingEdge(clk)
            _force_req_fields(req, {"aw_valid": 0, "w_valid": 0, "b_ready": 1})
            for _ in range(timeout_cycles):
                await FallingEdge(clk)
                if axil_resp_get(resp, "b_valid"):
                    bresp = axil_resp_get(resp, "b_resp")
                    await RisingEdge(clk)
                    _release_req(req)
                    return bresp
            break

    _release_req(req)
    raise TimeoutError("AXI-Lite write handshake/response timeout")


async def axil_hier_read32(
    clk,
    req: Any,
    resp: Any,
    addr: int,
    *,
    timeout_cycles: int = 64,
) -> tuple[int, int]:
    """Issue one AXI-Lite read; return (rresp, rdata).

    Hold ar_valid until r_valid — do not retire AR on the first idle ar_ready.
    """
    _force_req_fields(
        req,
        {
            "aw_valid": 0,
            "w_valid": 0,
            "ar_valid": 0,
            "b_ready": 1,
            "r_ready": 1,
        },
    )
    await RisingEdge(clk)
    _force_req_fields(
        req,
        {
            "ar_addr": addr & 0xFFFFFFFF,
            "ar_prot": 0,
            "ar_valid": 1,
            "aw_valid": 0,
            "w_valid": 0,
            "b_ready": 1,
            "r_ready": 1,
        },
    )

    for _ in range(timeout_cycles):
        await FallingEdge(clk)
        if axil_resp_get(resp, "r_valid"):
            rresp = axil_resp_get(resp, "r_resp")
            rdata = axil_resp_get(resp, "r_data") & 0xFFFFFFFF
            await RisingEdge(clk)
            _force_req_fields(req, {"ar_valid": 0, "r_ready": 1})
            await RisingEdge(clk)
            _release_req(req)
            return rresp, rdata

    _release_req(req)
    raise TimeoutError("AXI-Lite read response timeout")


def _release_req(req: Any) -> None:
    if not _is_hier_req(req):
        _AXIL_REQ_FORCE_SHADOW.pop(id(req), None)
        try:
            req.value = Release()
        except Exception:
            pass
        return

    for field in (
        "aw_valid",
        "w_valid",
        "ar_valid",
        "b_ready",
        "r_ready",
        "aw.addr",
        "aw.prot",
        "w.data",
        "w.strb",
        "ar.addr",
        "ar.prot",
    ):
        h = req
        try:
            for part in field.split("."):
                h = getattr(h, part)
            h.value = Release()
        except Exception:
            pass
