#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Turn a declarative TOML fuse configuration into a SEP eFuse preload image.

The SEP OTP is a 256-word array the RTL reads with ``$readmemh`` at simulation
time 0. The DUT knows nothing about register names, so something has to turn
"LC_STATE is PROD" into "word 3 holds 0x000000e1". That is this module.

Placement is NOT described here. Register offsets and widths come from
``SepEfuseImage``'s field table (derived from the generated register header, in
turn generated from ``sep_efuse_map.rdl``), and bit ranges within a register come
from that header's ctypes bitfield structs. Nothing here restates the fuse map:
a hand-maintained copy placed by TOML iteration order would let a reordered
config file silently move every field after the edit.

``apply_toml()`` is called TWICE per simulation, from two processes:
``dv_sim_prestage.stage()`` before the simulator launches, to write the array the
RTL reads at t=0, and ``sep_base_test.select_efuse_image()`` inside the test, to
build the golden its post-sense check compares that array against. Both reach it
through ``SepEfuseImage.load()``, so the two cannot disagree.

Config format (every key optional; anything unstated stays 0)::

    [LC_STATE]
      [LC_STATE.fields.lc_state]
      value = 0xE1

    [CLASS_KEY]                   # whole-register form, for wide registers
    value = 0x54e01f1d...

An unknown register name, an unknown field name, or a value too wide for its
field is a hard error. That is the property an opaque committed ``.hex`` cannot
have: when the RDL moves a field, a stale config fails loudly here instead of
staging a plausible-looking image that no longer means what its filename says.

Run directly for the two human-facing jobs, neither needed for a normal test run:

    ./sep_generate_efuse_preload.py --selftest
    ./sep_generate_efuse_preload.py --emit <cfg.toml> [--output-dir DIR]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ENV_DIR = Path(__file__).resolve().parent
_DV_ROOT = _ENV_DIR.parents[1]
_REPO_ROOT = _DV_ROOT.parents[3]
_CONFIG_DIR = _DV_ROOT / "tb" / "efuse_preloads" / "efuse_configurations"


def _reexec_under_venv() -> None:
    """Re-exec under the repo virtualenv if this interpreter cannot parse TOML.

    Only reachable when run as a script. The DV flow runs Python 3.11 under
    ``.venv``, but a bare ``./sep_generate_efuse_preload.py`` may pick up an older
    system Python without ``tomllib`` -- there is nothing to fall back to, so hand
    the invocation to the interpreter the flow itself uses.
    """
    if sys.version_info >= (3, 11):
        return
    venv_python = _REPO_ROOT / ".venv" / "bin" / "python3"
    if not venv_python.is_file():
        sys.exit(
            f"{Path(__file__).name}: needs Python 3.11+ for tomllib, running "
            f"{'.'.join(str(v) for v in sys.version_info[:3])}, and "
            f"{venv_python} does not exist. Invoke it with the DV virtualenv."
        )
    if Path(sys.executable).resolve() == venv_python.resolve():
        return  # already there -- never exec ourselves in a loop
    os.execv(
        str(venv_python),
        [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


if __name__ == "__main__":
    _reexec_under_venv()

# Import order matters: sep_reg_meta puts regs/gen/py on sys.path as an import
# side effect, so it has to precede sep_reg. Same idiom as sep_efuse_image.
import tomllib  # noqa: E402
from typing import Dict, Optional, Tuple  # noqa: E402

import sep_reg_meta  # noqa: F401,E402
import sep_reg  # noqa: E402

WORD_BITS = 32

# Per-register keys this loader understands. Anything else is rejected rather
# than ignored: a key that silently does nothing is worse than a typo, because
# the config still loads and the author's intent is quietly dropped.
#   value    -- whole register, little-endian
#   fields   -- named bitfields
#   regwidth -- present in reference-suite configs; the RDL fixes the width, so the
#               key is accepted and never affects placement
_ALLOWED_KEYS = frozenset(("value", "fields", "regwidth"))

# Lock keys are rejected, not modelled. The reference config format carries
# per-register read_locked/write_locked; rejecting them loudly means a config copied
# from the reference cannot appear to set a lock that never lands.
_LOCK_KEYS = frozenset(("read_locked", "write_locked"))


def _bitfields(reg_name: str) -> Optional[Dict[str, Tuple[int, int]]]:
    """``{field_name: (lsb, width)}`` for ``reg_name``, or None if the generated
    header declares no bitfields for it.

    ctypes lays bitfields out LSB-first in declaration order, which is how the
    generator emits them, so the running total IS the field's lsb.

    None means "wider than the generator emits a struct for" (the 256-bit keys,
    digests, UIDs and SPARE regions, plus 64-bit SIP_DIS/SYS_DIS). Those declare
    exactly one full-width field in the RDL, so ``_apply_register`` accepts a
    single field entry for them and treats it as the whole register.
    """
    struct = getattr(sep_reg, f"SEP_EFUSE_MAP_{reg_name}_reg_t", None)
    if struct is None:
        return None
    out: Dict[str, Tuple[int, int]] = {}
    lsb = 0
    for fname, _ctype, width in struct._fields_:
        out[fname] = (lsb, width)
        lsb += width
    return out


def _check_width(value: int, width: int, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{where}: value must be an integer, got {value!r}")
    if value < 0:
        raise ValueError(f"{where}: value must not be negative ({value})")
    if value >= (1 << width):
        raise ValueError(f"{where}: value {value:#x} does not fit in {width} bits")
    return value


def _apply_register(image, reg_name: str, body: dict) -> None:
    """Apply one ``[REG]`` table onto ``image``.

    LC_STATE is written as a plain word, bypassing
    ``SepEfuseImage.set_lc_state()``, which rejects any code outside the 7 legal
    ones. Preloads that sense the DUT straight into a corrupt (non-complementary)
    or INVALID lifecycle encoding exist precisely to inject a state the write
    path cannot reach, so this loader must be able to express them.
    """
    for key in body:
        if key in _LOCK_KEYS:
            raise ValueError(
                f"[{reg_name}].{key}: lock bits are not implemented by this "
                "loader, so this key would silently do nothing. Remove it, or "
                "add lock support together with a test that checks enforcement"
            )
        if key not in _ALLOWED_KEYS:
            raise ValueError(
                f"[{reg_name}].{key}: unknown key. Expected one of "
                f"{', '.join(sorted(_ALLOWED_KEYS))}"
            )

    try:
        fld = image.field(reg_name)
    except KeyError:
        raise KeyError(
            f"unknown eFuse register {reg_name!r}: absent from the generated map. "
            "Check the name against sep_efuse_map.rdl"
        ) from None

    reg_bits = fld.n_words * WORD_BITS
    fields = _bitfields(reg_name)
    value = 0
    saw_whole = "value" in body
    if saw_whole:
        value = _check_width(body["value"], reg_bits, f"[{reg_name}].value")

    entries = body.get("fields") or {}
    for fname, fbody in entries.items():
        where = f"[{reg_name}.fields.{fname}]"
        if not isinstance(fbody, dict) or "value" not in fbody:
            raise ValueError(f"{where}: expected a table with a 'value' key")
        if saw_whole:
            raise ValueError(
                f"{where}: register also sets a whole-register 'value'; use one form or the other"
            )
        if fields is None:
            # No bitfield struct is generated for registers wider than 64 bits.
            # Those declare a single full-width field in the RDL, so the name is
            # documentation and the value covers the register.
            if len(entries) != 1:
                raise ValueError(
                    f"{where}: {reg_name} is {reg_bits} bits and has no generated "
                    "bitfields, so it accepts exactly one whole-register field entry"
                )
            value = _check_width(fbody["value"], reg_bits, where)
            continue
        if fname not in fields:
            raise KeyError(
                f"{where}: {reg_name} has no field {fname!r}. "
                f"Declared fields: {', '.join(sorted(fields))}"
            )
        lsb, width = fields[fname]
        value |= _check_width(fbody["value"], width, where) << lsb

    image.set_int(reg_name, value)


def apply_toml(image, path: str | Path):
    """Apply a TOML fuse configuration onto ``image`` in place; returns ``image``.

    Duck-typed on ``SepEfuseImage`` (``field()``, ``set_int()``) rather than
    importing it, so ``SepEfuseImage.load()`` can dispatch here without a
    circular import.
    """
    path = Path(path)
    with path.open("rb") as handle:
        doc = tomllib.load(handle)
    for reg_name, body in doc.items():
        if not isinstance(body, dict):
            raise ValueError(f"{path}: top-level key {reg_name!r} is not a register table")
        _apply_register(image, reg_name, body)
    return image


# ── script entry points ──────────────────────────────────────────────────────
# Everything below runs only when this file is executed directly. Neither job is
# needed for a normal test run: the prestage hook and the tests call apply_toml()
# through SepEfuseImage.load().


def _load_sep_efuse_image():
    """Import SepEfuseImage by file path.

    The ``env`` package ``__init__`` pulls in cocotb/pyuvm, which do not exist
    outside a simulation, so a plain package import would fail here.
    """
    import importlib.util

    if str(_ENV_DIR) not in sys.path:
        sys.path.insert(0, str(_ENV_DIR))
    spec = importlib.util.spec_from_file_location(
        "sep_efuse_image", _ENV_DIR / "sep_efuse_image.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["sep_efuse_image"] = module
    spec.loader.exec_module(module)
    return module.SepEfuseImage


def _emit(configs, output_dir: Path) -> int:
    SepEfuseImage = _load_sep_efuse_image()
    for config in configs:
        image = apply_toml(SepEfuseImage(), config)
        target = output_dir / f"{Path(config).stem}.hex"
        image.write_hex(target)
        print(f"wrote {target}")
    return 0


_failures: list = []


def _selftest() -> int:
    """Cover what the committed configs cannot.

    The committed configs touch few registers and none of them can fail, so the
    wide registers and every error path would otherwise be untested code on the
    path that decides what the DUT senses at t=0.
    """
    import tempfile

    SepEfuseImage = _load_sep_efuse_image()

    def build(text: str):
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(text)
            tmp = handle.name
        try:
            return apply_toml(SepEfuseImage(), tmp)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def ok(label: str, text: str, want, get) -> None:
        try:
            got = get(build(text))
        except Exception as exc:  # noqa: BLE001 - report, do not mask
            print(f"FAIL  {label} -- raised {type(exc).__name__}: {exc}")
            _failures.append(label)
            return
        if got == want:
            print(f"PASS  {label}")
        else:
            print(f"FAIL  {label} -- got {got:#x}, want {want:#x}")
            _failures.append(label)

    def err(label: str, text: str, substring: str) -> None:
        """Assert the config is REJECTED with a message naming the problem."""
        try:
            build(text)
        except Exception as exc:  # noqa: BLE001
            if substring in str(exc):
                print(f"PASS  {label}")
            else:
                print(f"FAIL  {label} -- rejected for the wrong reason: {exc}")
                _failures.append(label)
            return
        print(f"FAIL  {label} -- accepted an invalid config")
        _failures.append(label)

    print("-- values land where the generated map says --")
    ok(
        "ROM_CTL packs its bitfields LSB-first",
        "[ROM_CTL]\n"
        "  [ROM_CTL.fields.rom_endianness_ctrl]\n  value = 0x1\n"
        "  [ROM_CTL.fields.rom_swap_ctrl]\n  value = 0x6\n",
        0x1 | (0x6 << 1),
        lambda i: i.field_int("ROM_CTL"),
    )
    ok(
        "whole-register form fills a 256-bit field",
        "[CLASS_KEY]\nvalue = 0x" + "a5" * 32 + "\n",
        int("a5" * 32, 16),
        lambda i: i.field_int("CLASS_KEY"),
    )
    # A corrupt (non-complementary) encoding must survive: preloads exist to
    # sense the DUT into states the write path cannot reach.
    ok(
        "corrupt LC_STATE encoding is preserved verbatim",
        "[LC_STATE]\n  [LC_STATE.fields.lc_state]\n  value = 0x11\n",
        0x11,
        lambda i: i.words[i.field("LC_STATE").word],
    )
    ok(
        "anything unstated stays zero",
        "[LC_STATE]\n  [LC_STATE.fields.lc_state]\n  value = 0xE1\n",
        0xE1,
        lambda i: sum(i.words),
    )
    ok(
        "the reference suite's stray regwidth key is ignored",
        "[SYSCLK_FREQ_MHZ]\n  [SYSCLK_FREQ_MHZ.fields.sysclk_freq_mhz]\n  value = 0x320\n",
        0x320,
        lambda i: i.field_int("SYSCLK_FREQ_MHZ"),
    )

    # Registers no live config sets. A name here that the RDL no longer has makes
    # _apply_register raise, so this is the drift check for the wide and secret
    # registers as well as a placement one.
    print("\n-- registers not exercised by any live config --")
    wide = (
        "[TRANSIENT_RMA_EN]\n  [TRANSIENT_RMA_EN.fields.transient_rma_en]\n  value = 0x1\n"
        "[SIP_DIS]\n  [SIP_DIS.fields.sip_dis]\n  value = 0xdeadbeafdeadbeaf\n"
        "[SYS_DIS]\n  [SYS_DIS.fields.sys_dis]\n  value = 0xbadcab1ebadcab1e\n"
        "[RMA_SIP_TOKEN_DIGEST]\n  [RMA_SIP_TOKEN_DIGEST.fields.token]\n"
        "  value = 0x123456789abcdef\n"
        "[RMA_CHIPLET_TOKEN_DIGEST]\n  [RMA_CHIPLET_TOKEN_DIGEST.fields.token]\n"
        "  value = 0x66687aadf862bd776c8fc18b8e9f8e20089714856ee233b3902a591d0d5f2925\n"
        "[CHIPLET_UID]\n  [CHIPLET_UID.fields.uid]\n  value = 0xdeadbeef\n"
        "[SYSCLK_FREQ_MHZ]\n"
        "  [SYSCLK_FREQ_MHZ.fields.sysclk_freq_mhz]\n  value = 0x320\n"
    )
    for reg, want in (
        ("TRANSIENT_RMA_EN", 0x1),
        ("SIP_DIS", 0xDEADBEAFDEADBEAF),
        ("SYS_DIS", 0xBADCAB1EBADCAB1E),
        ("RMA_SIP_TOKEN_DIGEST", 0x123456789ABCDEF),
        (
            "RMA_CHIPLET_TOKEN_DIGEST",
            0x66687AADF862BD776C8FC18B8E9F8E20089714856EE233B3902A591D0D5F2925,
        ),
        ("CHIPLET_UID", 0xDEADBEEF),
        ("SYSCLK_FREQ_MHZ", 0x320),
    ):
        ok(f"{reg} round-trips", wide, want, lambda i, r=reg: i.field_int(r))

    print("\n-- a stale or wrong config fails loud --")
    err("unknown register", "[NOT_A_REG]\nvalue = 1\n", "unknown eFuse register")
    err("unknown field", "[ROM_CTL]\n  [ROM_CTL.fields.nope]\n  value = 1\n", "has no field")
    err("unknown per-register key", "[LC_STATE]\nnope = 1\n", "unknown key")
    err(
        "lock key rejected rather than ignored",
        '[LC_STATE]\nwrite_locked = "False"\n',
        "lock bits are not implemented",
    )
    err(
        "value wider than its field",
        "[ROM_CTL]\n  [ROM_CTL.fields.rom_swap_ctrl]\n  value = 0x20\n",
        "does not fit in 5 bits",
    )
    err(
        "value wider than its register",
        "[LC_STATE]\nvalue = 0x1_0000_0000\n",
        "does not fit in 32 bits",
    )
    err("negative value", "[LC_STATE]\nvalue = -1\n", "must not be negative")
    err(
        "whole-register and per-field forms mixed",
        "[LC_STATE]\nvalue = 1\n  [LC_STATE.fields.lc_state]\n  value = 2\n",
        "use one form or the other",
    )
    err(
        "two field entries on a register with no generated bitfields",
        "[CLASS_KEY]\n  [CLASS_KEY.fields.key]\n  value = 1\n"
        "  [CLASS_KEY.fields.other]\n  value = 2\n",
        "exactly one whole-register field",
    )

    # Loading each live config is the floor: these are what the DUT senses at
    # t=0, so one that no longer parses -- because the RDL renamed a field, say
    # -- must fail here and not in a long simulation. The byte-compare applies only
    # to configs with a committed .hex image (the plusargs name the .toml and the
    # array is generated, so a committed image is the exception). Count them and
    # say so, since a loop that compares nothing looks like one that verified all.
    print("\n-- every live config loads, and matches its .hex if one exists --")
    configs = sorted(_CONFIG_DIR.glob("*.toml"))
    if not configs:
        print(f"FAIL  no configs found in {_CONFIG_DIR}")
        _failures.append("no configs")
    compared = 0
    for config in configs:
        try:
            image = apply_toml(SepEfuseImage(), config)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {config.name} does not load: {type(exc).__name__}: {exc}")
            _failures.append(config.name)
            continue
        committed = config.parent.parent / f"{config.stem}.hex"
        if not committed.is_file():
            print(f"PASS  {config.name} (loads; no committed image to compare)")
            continue
        compared += 1
        want = "".join(f"{w:08x}\n" for w in image.words)
        if committed.read_text() == want:
            print(f"PASS  {config.name} -> {committed.name} byte-exact")
        else:
            print(f"FAIL  {config.name} does not reproduce {committed.name}")
            _failures.append(config.name)
    print(f"      {len(configs)} config(s) loaded, {compared} byte-compared")

    print()
    if _failures:
        print(f"{len(_failures)} FAILURE(S): {', '.join(_failures)}")
        return 1
    print("ALL PASS")
    return 0


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--selftest", action="store_true", help="run the loader selftest")
    parser.add_argument(
        "--emit", nargs="+", type=Path, metavar="CFG", help="write <CFG>.hex for each config given"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_CONFIG_DIR.parent,
        help="where --emit writes (default: tb/efuse_preloads/)",
    )
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.emit:
        return _emit(args.emit, args.output_dir)
    parser.error("nothing to do: pass --selftest or --emit")


if __name__ == "__main__":
    sys.exit(_main())
