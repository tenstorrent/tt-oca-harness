# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Console model of the OCA Boot ROM: which tokens it can print, and one slot attempt."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

_SEP = Path(__file__).resolve().parents[3]
_ROM_SRC = _SEP / "bootrom" / "prod" / "src"
# The ROM and the BL1 test image share one console; BL1 prints the BL0S_* echoes.
_SOURCES = (
    (_ROM_SRC, re.compile(r"simputs(?:hex32|dec24)?\((.*?)\);", re.S)),
    (_SEP / "dv" / "fw" / "tests" / "bl1_pass_test", re.compile(r"bl1_puts\((.*?)\);", re.S)),
)
# A C-escape-aware string literal, so an embedded "\n" is not read as the closing quote.
_STR_LIT_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
# apply_lock(addr, bitmask, "WHAT") prints "WHAT" then "_LOCK_FAIL" from two separate calls.
_LOCK_CALL_RE = re.compile(r'apply_lock\(.*?,\s*"((?:[^"\\]|\\.)*)"\s*\)', re.S)


def _tokens(literal: str) -> list[str]:
    # Splits a literal on \n so a ternary arm or split print statement is not glued to \n.
    return [t.strip() for t in literal.replace("\\n", "\n").split("\n") if t.strip()]


def _scan() -> frozenset[str]:
    out = set()
    for root, call_re in _SOURCES:
        for c in sorted(root.glob("*.c")):
            text = c.read_text()
            for call in call_re.finditer(text):
                for lit in _STR_LIT_RE.finditer(call.group(1)):
                    out.update(_tokens(lit.group(1)))
    for c in sorted(_ROM_SRC.glob("*.c")):
        for m in _LOCK_CALL_RE.finditer(c.read_text()):
            out.add(_tokens(m.group(1))[0] + "_LOCK_FAIL")
    return frozenset(out)


ROM_MARKERS = _scan()


def _boundary_match(text: str, token: str) -> bool:
    # `text` carries `token` only at a real token boundary, not as a prefix of a longer identifier.
    if not text.startswith(token):
        return False
    if len(text) == len(token) or token[-1] in "=: ":
        return True
    tail = text[len(token)]
    return not (tail.isalnum() or tail == "_")


def count(lines: Iterable[str], marker: str) -> int:
    return sum(1 for line in lines if _boundary_match(line, marker))


def _printed(marker: str) -> bool:
    # A marker is known only as an exact token, or a value-carrying token plus its value.
    return any(marker == t or (t[-1] in "=: " and marker.startswith(t)) for t in ROM_MARKERS)


def assert_known(markers: Iterable[str], where: str) -> None:
    unknown = [m for m in markers if not _printed(m)]
    assert not unknown, (
        f"{where}: the OCA ROM never prints {unknown}; a required one can never "
        f"appear and a forbidden one checks nothing. Use a token from ROM_MARKERS."
    )


@dataclass
class Attempt:
    index: int
    src: int
    first: int
    last: int
    markers: list[tuple[int, str]] = field(default_factory=list)
    error: int | None = None
    # "incomplete" covers a trap, a timeout, or a terminal failure that prints no MANIFEST_ERR=.
    stage: str = "manifest"


_ERR_PREFIX = "MANIFEST_ERR="
_ERR_RE = re.compile(r"MANIFEST_ERR=0x([0-9a-fA-F]{8})")
_SRC_RE = re.compile(r"MANIFEST_SRC=0x([0-9a-fA-F]{8})")


def split_attempts(console: list[str]) -> list[Attempt]:
    starts = [i for i, line in enumerate(console) if _SRC_RE.search(line)]
    out = []
    for n, s in enumerate(starts):
        end = starts[n + 1] - 1 if n + 1 < len(starts) else len(console) - 1
        att = Attempt(
            n,
            int(_SRC_RE.search(console[s]).group(1), 16),
            s,
            end,
            [(i, console[i]) for i in range(s, end + 1)],
        )
        seen_ok = seen_payload = False
        for idx, line in att.markers:
            if _ERR_PREFIX in line:
                m = _ERR_RE.search(line)
                # MANIFEST_ERR= without 8 hex digits raises instead of parsing as no error.
                assert m, (
                    f"attempt {att.index} (src 0x{att.src:08x}): {line!r} carries "
                    f"{_ERR_PREFIX} but not the expected 8 hex digits after it"
                )
                att.error = int(m.group(1), 16)
                att.last = idx
                break
            seen_ok |= _boundary_match(line, "MANIFEST_OK")
            seen_payload |= _boundary_match(line, "PAYLOAD_OK")
        if att.error is not None:
            att.stage = "placement" if seen_payload else "payload" if seen_ok else "manifest"
        else:
            att.stage = "accepted" if seen_payload else "incomplete"
        att.markers = [(i, line) for i, line in att.markers if i <= att.last]
        out.append(att)
    return out


def assert_attempt(
    att: Attempt,
    *,
    error: int | None,
    stage: str,
    ordered: Sequence[str] = (),
    absent: Sequence[str] = (),
) -> None:
    assert_known(list(ordered) + list(absent), f"attempt {att.index}")
    assert att.error == error, (
        f"attempt {att.index} (src 0x{att.src:08x}) ended with "
        f"{'no error' if att.error is None else f'0x{att.error:08x}'}, expected "
        f"{'no error' if error is None else f'0x{error:08x}'}"
    )
    assert att.stage == stage, f"attempt {att.index} stopped at {att.stage}, expected {stage}"
    lines = [line for _, line in att.markers]
    pos = -1
    for m in ordered:
        hit = next((k for k in range(pos + 1, len(lines)) if _boundary_match(lines[k], m)), None)
        assert hit is not None, f"attempt {att.index}: {m} missing or out of order in {lines}"
        pos = hit
    for m in absent:
        assert not any(_boundary_match(line, m) for line in lines), (
            f"attempt {att.index}: forbidden {m} in {lines}"
        )


def _selftest() -> int:
    assert "MANIFEST_OK" in ROM_MARKERS and "RSA_VERIFY_OK" in ROM_MARKERS
    # Tokens this ROM does not print: assert_known must refuse them.
    assert "PLD_HASH_OK" not in ROM_MARKERS and "SIG_VALID" not in ROM_MARKERS
    # Ternary print sites, apply_lock's split print, and a BL1 leading-"\n" literal all scan in.
    assert_known(
        [
            "MANIFEST_PRIMARY",
            "MANIFEST_BACKUP",
            "BL1_DST=ICCM",
            "BL1_DST=SRAM",
            "ESRC_FIPS_LOCK_FAIL",
            "ENTROPY_SRC_SEL_LOCK_FAIL",
            "BL0S_SIZE=" + "0" * 8,
        ],
        "selftest",
    )
    assert_known(["BL0S_BOOT_PCR=" + "0" * 64, "LC=PROD", "FUSE: SBOOT_DIS: 1"], "selftest")
    try:
        assert_known(["PLD_HASH_OK"], "selftest")
    except AssertionError:
        pass
    else:
        raise AssertionError("assert_known accepted PLD_HASH_OK, a token the ROM does not print")
    assert_known(["MANIFEST_ERR=0x00030015", "PUBK_REVOKE=0x00000000"], "selftest")
    for bad in ("MANIFEST_OK.junk", "LC=PROD-END"):
        try:
            assert_known([bad], "selftest")
        except AssertionError:
            pass
        else:
            raise AssertionError(f"assert_known accepted the typo'd marker {bad!r}")

    # A short token must not match as a prefix of a longer one that happens to share it.
    assert not _boundary_match("RSA_EXEC_FAIL", "RSA_EXEC")
    assert not _boundary_match("LC=PROD_END", "LC=PROD")
    assert not _boundary_match("COPY_LEN=0x00000010", "LEN=0x00000010")
    assert _boundary_match("RSA_EXEC", "RSA_EXEC")
    assert _boundary_match("LEN=0x00000010", "LEN=")
    assert count(["RSA_EXEC", "RSA_EXEC_FAIL", "RSA_EXEC"], "RSA_EXEC") == 2

    console = [
        "MANIFEST_PRIMARY",
        "MANIFEST_SRC=0x00001000",
        "OCA_BODY=0x00001000",
        "PUBK_AUTHORIZED",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        "MANIFEST_ERR=0x00030015",
        "MANIFEST_BACKUP",
        "MANIFEST_SRC=0x00041000",
        "PUBK_AUTHORIZED",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        "PAYLOAD_OK",
        "BL1_JUMP=0xc0000000",
    ]
    a = split_attempts(console)
    assert [x.src for x in a] == [0x1000, 0x41000]
    assert a[0].stage == "payload" and a[0].error == 0x00030015
    assert a[1].stage == "accepted" and a[1].error is None
    assert_attempt(
        a[0],
        error=0x00030015,
        stage="payload",
        ordered=("PUBK_AUTHORIZED", "RSA_EXEC", "RSA_VERIFY_OK", "MANIFEST_OK"),
        absent=("PAYLOAD_OK",),
    )
    try:
        assert_attempt(
            a[1],
            error=None,
            stage="accepted",
            ordered=("RSA_VERIFY_OK", "RSA_EXEC"),
        )
    except AssertionError:
        pass
    else:
        raise AssertionError("assert_attempt accepted a reversed ordered sequence")
    try:
        assert_attempt(a[1], error=None, stage="accepted", absent=("PAYLOAD_OK",))
    except AssertionError:
        pass
    else:
        raise AssertionError("assert_attempt accepted a present forbidden marker")

    # A substring collision (COPY_LEN= holding LEN=, RSA_EXEC_FAIL holding RSA_EXEC) must not match.
    fail_console = [
        "MANIFEST_PRIMARY",
        "MANIFEST_SRC=0x00002000",
        "PUBK_AUTHORIZED",
        "RSA_EXEC_FAIL",
        "COPY_LEN=0x00000010",
        "MANIFEST_ERR=0x00030102",
    ]
    b = split_attempts(fail_console)[0]
    assert b.stage == "manifest" and b.error == 0x00030102
    try:
        assert_attempt(b, error=0x00030102, stage="manifest", ordered=("RSA_EXEC",))
    except AssertionError:
        pass
    else:
        raise AssertionError("ordered accepted RSA_EXEC_FAIL as RSA_EXEC")
    assert_attempt(b, error=0x00030102, stage="manifest", absent=("LEN=0x00000010",))

    # An error before MANIFEST_OK stages "manifest"; one after PAYLOAD_OK stages "placement".
    manifest_console = [
        "MANIFEST_PRIMARY",
        "MANIFEST_SRC=0x00003000",
        "MANIFEST_ERR=0x0003000c",
    ]
    c = split_attempts(manifest_console)[0]
    assert c.stage == "manifest" and c.error == 0x0003000C
    assert_attempt(c, error=0x0003000C, stage="manifest", absent=("MANIFEST_OK", "PAYLOAD_OK"))
    try:
        assert_attempt(c, error=0x0003000C, stage="manifest", ordered=("MANIFEST_OK",))
    except AssertionError:
        pass
    else:
        raise AssertionError("ordered found MANIFEST_OK on an attempt that never reached it")

    placement_console = [
        "MANIFEST_PRIMARY",
        "MANIFEST_SRC=0x00004000",
        "PUBK_AUTHORIZED",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
        "PAYLOAD_OK",
        "NO_BL1_IMAGE",
        "MANIFEST_ERR=0x00030102",
    ]
    d = split_attempts(placement_console)[0]
    assert d.stage == "placement" and d.error == 0x00030102
    assert_attempt(
        d,
        error=0x00030102,
        stage="placement",
        ordered=("MANIFEST_OK", "PAYLOAD_OK", "NO_BL1_IMAGE"),
    )

    trap_console = [
        "MANIFEST_PRIMARY",
        "MANIFEST_SRC=0x00005000",
        "OCA_BODY=0x00001000",
        "PUBK_AUTHORIZED",
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "MANIFEST_OK",
    ]
    e = split_attempts(trap_console)[0]
    assert e.stage == "incomplete" and e.error is None
    try:
        assert_attempt(e, error=None, stage="accepted")
    except AssertionError:
        pass
    else:
        raise AssertionError("a trap/timeout attempt with no PAYLOAD_OK read as accepted")

    try:
        split_attempts(["MANIFEST_SRC=0x00006000", "MANIFEST_ERR=garbage"])
    except AssertionError:
        pass
    else:
        raise AssertionError("an unparsable MANIFEST_ERR= was silently treated as no error")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
