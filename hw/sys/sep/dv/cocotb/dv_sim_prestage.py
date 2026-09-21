# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Pre-sim image staging hook for the SEP OSS DV flow.

The `sep_wrapper` DUT's generic efuse model self-preloads its OTP bank from
``<cwd>/out/sep_efuse.hex`` in an RTL ``initial $readmemh`` at simulation time 0 —
BEFORE any cocotb Python runs. The efuse tests, however, build their golden OTP
image inside the cocotb coroutine (``sep_base_test.write_efuse_image``), which is
too late for that t=0 read. This module regenerates the SAME image a real-fuse-sense
test would use, keyed on the per-leaf seed + the test's image parameters, and writes
it to ``<cwd>/out/sep_efuse.hex`` BEFORE the simulator process launches.

The runlib (``tools/dv/runlib/stages.py``) calls ``stage(item, seed, cwd, sim_args=,
root=)`` from the per-test sim setup if this module exists on the DUT's
``python_root``. It is a no-op for any test not in the registry AND without a
``+sep_efuse_preload`` plusarg (so ``+skip_fuse_sense`` tests are unaffected — the
model still reads the file but the sensed data is bypassed).

``+sep_efuse_preload`` on a test's args is honored here exactly as
``sep_base_test.select_efuse_image`` honors it at runtime, so the t=0 staged image
matches the test's golden: ``+sep_efuse_preload=<path>`` loads that file,
``+sep_efuse_preload`` with no path loads the committed default, and its absence
falls back to the per-test registry entry (random or registry preload).

Determinism: ``SepEfuseImage().randomize(seed, ...)`` is seeded by ``RANDOM_SEED``
(the value the sim gets and ``sep_base_test.random_seed()`` reads), so the staged
image is bit-identical to the test's own golden — the base post-sense backdoor
shadow compare is the drift detector if this registry ever diverges from a test's
``select_efuse_image(...)`` call.

REGISTRY MAINTENANCE: each entry must mirror the test's ``select_efuse_image`` /
``SepEfuseImage().randomize(...)`` kwargs EXACTLY. Do not import the test modules
here (they import cocotb); duplicate the params and rely on the post-sense compare
to catch drift.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# dv root = .../dv (this file is at .../dv/cocotb/dv_sim_prestage.py).
_DV_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EFUSE_PRELOAD = _DV_ROOT / "tb" / "efuse_preloads" / "sep_efuse_default.hex"


def _load_env_module(modname: str, filename: str):
    """Import a cocotb/env module by file path.

    The ``env`` package ``__init__`` pulls in cocotb/pyuvm (sim-only), so a
    plain package import would fail in the pre-sim runlib process. The env
    directory has to go on ``sys.path`` first: the sim gets it from
    ``[cocotb] python_paths`` in ``sep_sim_cfg.toml``, but this hook runs in
    ``run_dv.py``'s interpreter, where a bare sibling import would raise
    ``ModuleNotFoundError``.
    """
    env_dir = _DV_ROOT / "cocotb" / "env"
    if str(env_dir) not in sys.path:
        sys.path.insert(0, str(env_dir))
    path = env_dir / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {modname} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_sep_efuse_image():
    """Import SepEfuseImage without going through env/__init__.py."""
    return _load_env_module("sep_efuse_image", "sep_efuse_image.py").SepEfuseImage


def _rma_token_fixed(seed: int) -> dict[str, int]:
    """Same pins as ``sep_efuse_rma_token_rand_test``'s ``cfg.image_fixed()``."""
    mod = _load_env_module("sep_rma_token", "sep_rma_token.py")
    return mod.SepRmaTokenCfg(seed).image_fixed()


def _locked_field_irq_fixed(seed: int) -> dict[str, int]:
    """Same pins as ``sep_locked_field_access_irq_path_test``'s ``cfg.image_fixed()``."""
    mod = _load_env_module("sep_locked_field_irq", "sep_locked_field_irq.py")
    return mod.SepLockedFieldIrqCfg(seed).image_fixed()


def _lc_transition_fixed(seed: int) -> dict[str, int]:
    """Same pins as ``sep_lcc_lc_state_transition_matrix_test``'s ``cfg.image_fixed()``.

    The annotated local is load-bearing, not style: ``_load_env_module`` returns
    ``Any``, so returning its result directly is a mypy ``no-any-return``. The
    three sibling helpers above still carry that finding, and the mypy reporter
    has no output cap -- its GitHub payload is within a few characters of the
    65535-character annotation limit, so one more finding fails the check run.
    """
    mod = _load_env_module("sep_lc_transition", "sep_lc_transition.py")
    fixed: dict[str, int] = mod.SepLcTransitionCfg(seed).image_fixed()
    return fixed


def _set_only_fixed(seed: int) -> dict[str, int]:
    """Same pins as ``sep_efuse_set_only_monotonicity_test``'s ``cfg.image_fixed()``."""
    mod = _load_env_module("sep_efuse_set_only", "sep_efuse_set_only.py")
    return mod.SepEfuseSetOnlyCfg(seed).image_fixed()


def _key_revocation_fixed(seed: int) -> dict[str, int]:
    """Pins for ``sep_key_revocation_bitmap_random_test``, from the SHARED draw.

    The exception to this file's duplicate-and-compare convention, and
    deliberately so: the revocation bitmap is the stimulus under test, and a
    hand-copied constraint that drifted would stage a different bitmap than the
    testcase predicts an outcome for. The draw therefore lives in
    ``env/sep_key_revocation_draw.py`` and both readers call it.
    """
    mod = _load_env_module("sep_key_revocation_draw", "sep_key_revocation_draw.py")
    fixed: dict[str, int] = mod.efuse_fixed(mod.draw(seed).bitmap)
    return fixed


# Common LC-gated field pins shared by several PROD-lifecycle tests.
_SIP_SYS_DIS_PINS = {
    "SIP_DIS": 0x0F0F_0F0F_0F0F_0F0F,
    "SYS_DIS": 0x00FF_00FF_00FF_00FF,
}

# sep_lcc_uvm_inbound_filter_gating_test needs DBG_1 bits 0/1 left enabled, because a
# PROD demotion only relaxes its group to these vectors rather than forcing it open.
# Kept separate rather than changing the shared dict: the other two entries want the
# fully-disabled vectors, and this file must mirror each test's own
# select_efuse_image(fixed=...) or the staged image and the golden disagree.
_SIP_SYS_DIS_PINS_DBG_OPEN = {
    "SIP_DIS": 0x0F0F_0F0F_0F0F_0F0C,
    "SYS_DIS": 0x00FF_00FF_00FF_00FC,
}

# test name -> OTP image spec. mode "random" => randomize(seed+seed_offset, **kw);
# mode "preload" => load(preload). Mirrors each test's select_efuse_image(...).
EFUSE_IMAGE_REGISTRY: dict[str, dict] = {
    # Full-shadow proof + W1S persistence: seed-random with CHIPLET_UID pinned to 0
    # (the test programs one bit of it after the first sense). Must match the test's
    # select_efuse_image(fixed={"CHIPLET_UID": 0}).
    "sep_efuse_image_test": {"mode": "random", "fixed": {"CHIPLET_UID": 0}},
    # Committed preload image (test passes +sep_efuse_preload, seed-independent).
    "sep_efuse_sense_test": {"mode": "preload", "preload": str(_DEFAULT_EFUSE_PRELOAD)},
    # LC stitch: starts at TEST_DEV (lc_raw=0x0) with SIP/SYS pins.
    "sep_efuse_lcc_lc_state_stitch_test": {
        "mode": "random",
        "lc_raw": 0x0,
        "fixed": dict(_SIP_SYS_DIS_PINS),
    },
    # PROD-lifecycle real-sense tests (lc_raw=0x1 = LC_PROD).
    "sep_efuse_jtag_axil_el2_cpu_mux_test": {"mode": "random", "lc_raw": 0x1},
    "sep_fabric_inbound_filter_rule_matrix_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed": dict(_SIP_SYS_DIS_PINS),
    },
    "sep_sec_dis_override_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed": dict(_SIP_SYS_DIS_PINS),
    },
    "sep_lcc_uvm_inbound_filter_gating_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed": dict(_SIP_SYS_DIS_PINS_DBG_OPEN),
    },
    "sep_efuse_km_axil_cpu_mux_coexist_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed": {"CHIPLET_UID": 0xDEAD_BEEF},
    },
    "sep_km_kmac_sideload_kat_test": {"mode": "random", "lc_raw": 0x1},
    "sep_km_aes_sideload_kat_test": {"mode": "random", "lc_raw": 0x1},
    "sep_km_hmac_sideload_kat_test": {"mode": "random", "lc_raw": 0x1},
    "sep_km_otbn_sideload_kat_test": {"mode": "random", "lc_raw": 0x1},
    "sep_drbg_real_sink_multi_km_aes_test": {"mode": "random", "lc_raw": 0x1},
    # Spare-field lock x program. SPARE0..7 pinned 0 so the unlocked-then-lock
    # walk starts from a known-zero field (lock_prob stays 0).
    "sep_efuse_program_lock_matrix_test": {
        "mode": "random",
        "lc_raw": 0x0,
        "fixed": {f"SPARE{i}": 0 for i in range(8)},
    },
    # Demote product starts at TEST_DEV with DIS=0; the pinned DIS pair is
    # W1S-programmed after the first LC walk.
    "sep_lcc_demote_feat_ctrl_matrix_test": {
        "mode": "random",
        "lc_raw": 0x0,
        "fixed": {"SIP_DIS": 0, "SYS_DIS": 0},
    },
    # RMA token RANDCFG. Digests come from SepRmaTokenCfg(seed); see
    # _rma_token_fixed() so the t=0 hex matches the test golden.
    "sep_efuse_rma_token_rand_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed_from": "rma_token",
    },
    # Set-only shadow OR-merge. Sensed ones come from SepEfuseSetOnlyCfg(seed);
    # see _set_only_fixed() so the t=0 hex matches the test golden.
    "sep_efuse_set_only_monotonicity_test": {
        "mode": "random",
        "lc_raw": 0x0,
        "fixed_from": "set_only",
    },
    # LC_STATE shadow-write next-state walk. The OTP image is a t=0 deposit that
    # survives reset, so each sensed starting state is its own leaf and the
    # +lc_start on the leaf's args must agree with lc_raw here -- the test reads
    # the sensed nibble off the DUT and fails loudly if they disagree. Token
    # digests and SIP/SYS pins come from SepLcTransitionCfg(seed); see
    # _lc_transition_fixed().
    "sep_lcc_lc_state_w1s_prod_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed_from": "lc_transition",
    },
    "sep_lcc_lc_state_w1s_prod_demote_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed_from": "lc_transition",
    },
    "sep_lcc_lc_state_w1s_rma_sip_test": {
        "mode": "random",
        "lc_raw": 0x2,
        "fixed_from": "lc_transition",
    },
    "sep_lcc_lc_state_w1s_rma_chiplet_test": {
        "mode": "random",
        "lc_raw": 0x6,
        "fixed_from": "lc_transition",
    },
    "sep_lcc_lc_state_w1s_prod_end_test": {
        "mode": "random",
        "lc_raw": 0x8,
        "fixed_from": "lc_transition",
    },
    # The transient-RMA leaf senses TRANSIENT_RMA_EN=1, which the test re-pins in
    # its own select_efuse_image call.
    "sep_lcc_lc_state_w1s_transient_test": {
        "mode": "random",
        "lc_raw": 0x8,
        "fixed_from": "lc_transition",
        "fixed_extra": {"TRANSIENT_RMA_EN": 1},
    },
    # Locked-field shadow IRQ. SPARE lock bits and patterns come from
    # SepLockedFieldIrqCfg(seed); see _locked_field_irq_fixed().
    "sep_locked_field_access_irq_path_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed_from": "locked_field_irq",
    },
    # TP074 constrained-random key revocation. The entry carries NO
    # +sep_efuse_preload, so the drawn CHIPLET_PUBK_REVOKE bitmap comes from the
    # same pure function the testcase predicts its outcome with; see
    # _key_revocation_fixed(). The image this entry stages is NOT the one the DUT
    # senses -- the model's $readmemh waits for reset and the testcase's golden
    # replaces this file at 0 ns -- it is the copy the testcase compares its
    # golden against, which is what proves both processes ran the same draw.
    "sep_key_revocation_bitmap_random_test": {
        "mode": "random",
        "lc_raw": 0x1,
        "fixed_from": "key_revocation_draw",
    },
}


def _preload_from_args(sim_args) -> str | None:
    """Parse the ``+sep_efuse_preload`` selector out of a test's rendered plusargs.

    Mirrors ``sep_base_test.select_efuse_image``:
      * ``+sep_efuse_preload=<path>`` -> return ``<path>``
      * bare ``+sep_efuse_preload``   -> return ``""`` (=> committed default)
      * absent                        -> return ``None``
    Last occurrence wins, matching plusarg override semantics.
    """
    if not sim_args:
        return None
    selector: str | None = None
    for arg in sim_args:
        if arg == "+sep_efuse_preload":
            selector = ""
        elif arg.startswith("+sep_efuse_preload="):
            selector = arg.split("=", 1)[1]
    return selector


def _resolve_preload(path: str, cwd, root) -> Path:
    """Resolve a ``+sep_efuse_preload=<path>`` value. Absolute paths are used as-is;
    a relative path is tried against the sim cwd, the repo root, and the DV root (the
    conventions a committed image could be referenced by). Raises if none exist so a
    typo'd path fails loud at stage time instead of silently staging a stale image."""
    p = Path(path)
    if p.is_absolute():
        if not p.is_file():
            raise FileNotFoundError(f"+sep_efuse_preload={path} does not exist")
        return p
    candidates = [Path(cwd) / p]
    if root:
        candidates.append(Path(root) / p)
    candidates.append(_DV_ROOT / p)
    for cand in candidates:
        if cand.is_file():
            return cand
    tried = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"+sep_efuse_preload={path} not found (tried: {tried})")


def stage(item: str, seed: int, cwd, *, sim_args=None, root=None) -> bool:
    """Write ``<cwd>/out/sep_efuse.hex`` for a registered efuse test OR any test that
    passes ``+sep_efuse_preload`` (the plusarg overrides the registry, matching the
    runtime ``select_efuse_image`` contract). Returns True if an image was staged,
    False if the test is neither registered nor carrying a preload plusarg (no-op)."""
    preload_sel = _preload_from_args(sim_args)
    spec = EFUSE_IMAGE_REGISTRY.get(item)
    if preload_sel is None and spec is None:
        print(f"[dv_sim_prestage] no-op item={item!r} (not in registry)", flush=True)
        return False

    SepEfuseImage = _load_sep_efuse_image()
    image = SepEfuseImage()

    if preload_sel is not None:
        # +sep_efuse_preload[=path] on the test's args wins over the registry, exactly
        # as sep_base_test.select_efuse_image honors it at runtime, so the t=0 staged
        # image matches the test's golden.
        path = (
            str(_DEFAULT_EFUSE_PRELOAD)
            if preload_sel == ""
            else str(_resolve_preload(preload_sel, cwd, root))
        )
        image.load(path)
    elif spec.get("mode") == "preload":
        image.load(spec["preload"])
    else:
        fixed = spec.get("fixed")
        if spec.get("fixed_from") == "rma_token":
            fixed = _rma_token_fixed(seed + int(spec.get("seed_offset", 0)))
        elif spec.get("fixed_from") == "set_only":
            fixed = _set_only_fixed(seed + int(spec.get("seed_offset", 0)))
        elif spec.get("fixed_from") == "lc_transition":
            fixed = _lc_transition_fixed(seed + int(spec.get("seed_offset", 0)))
        elif spec.get("fixed_from") == "locked_field_irq":
            fixed = _locked_field_irq_fixed(seed + int(spec.get("seed_offset", 0)))
        elif spec.get("fixed_from") == "key_revocation_draw":
            fixed = _key_revocation_fixed(seed + int(spec.get("seed_offset", 0)))
        extra = spec.get("fixed_extra")
        if extra:
            fixed = {**(fixed or {}), **extra}
        image.randomize(
            seed + int(spec.get("seed_offset", 0)),
            lc_raw=spec.get("lc_raw"),
            lock_prob=float(spec.get("lock_prob", 0.0)),
            fixed=fixed,
        )

    out_dir = Path(cwd) / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    hex_path = out_dir / "sep_efuse.hex"
    image.write_hex(hex_path)
    print(
        f"[dv_sim_prestage] staged {item} seed={seed} -> {hex_path}",
        flush=True,
    )
    return True
