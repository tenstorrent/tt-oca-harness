#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#
# Stage Antora module sources for one OCAH documentation product from the hw
# tree. Product makefrags pass OCAH_DOC_PRODUCT_* paths. All staged output is
# gitignored throwaway build input: the single source of truth stays in each
# product's src/meta tree plus hw/**/doc and hw/**/regs/gen.
#
# Module topology (5 modules): ROOT, smc, sep, dtp, ip.
#   - ROOT: product src/*.adoc + meta tables + subsystem port_table partials.
#   - smc/sep/dtp: pages from hw/sys/<sys>/doc, reg partials from its regs/gen.
#   - ip: every hw/ip/<ip>/doc collapsed under <ip>/doc, reg partials per IP.
# Register docs use generated .html partials for Antora HTML and generated .adoc
# partials for PDF.

set -euo pipefail

ROOT="${OCAH_ROOT:?OCAH_ROOT must be set}"
DOC="$ROOT/doc"
PRODUCT="${OCAH_DOC_PRODUCT_DIR:?OCAH_DOC_PRODUCT_DIR must be set}"
SRC="${OCAH_DOC_PRODUCT_SRC:-$PRODUCT/src}"
META="${OCAH_DOC_PRODUCT_META:-$PRODUCT/meta}"
MOD="${OCAH_DOC_PRODUCT_MODULES:-$PRODUCT/modules}"
ASSETS="${OCAH_DOC_PRODUCT_ASSETS:-$PRODUCT/assets}"
COMMON_ASSETS="$DOC/trm/assets"

SUBSYSTEMS="smc sep dtp"
PORT_TABLE_SYS="smc sep dtp smu"
MODULES="ROOT smc sep dtp ip"

clean() {
  rm -rf "$MOD/ROOT/pages" "$MOD/ROOT/partials/hw" "$MOD/ROOT/assets"
  for m in smc sep dtp ip; do
    rm -rf "${MOD:?}/$m"
  done
  # Remove only the gitignored image copies staged into product assets.
  git -C "$ROOT" clean -fdX "$ASSETS" >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--clean" ]; then
  clean
  exit 0
fi

# Copy the .adoc tree under $1 into $2, preserving subdirs (skips non-adoc).
stage_adoc_tree() {
  local src="$1" dst="$2" rel
  [ -d "$src" ] || return 0
  while IFS= read -r rel; do
    mkdir -p "$dst/$(dirname "$rel")"
    cp -f "$src/$rel" "$dst/$rel"
  done < <(cd "$src" && find . -name '*.adoc' -type f | sed 's|^\./||')
}

# Copy a generated adoc dir verbatim (register partials) if present.
stage_gen_adoc() {
  local src="$1" dst="$2"
  [ -d "$src" ] || return 0
  mkdir -p "$dst"
  cp -R "$src/." "$dst/"
}

# Copy generated single-file HTML register docs if present. These are intended
# for Antora backend-html5 includes and are not the native PeakRDL mini-site.
stage_gen_html() {
  local src="$1" dst="$2"
  [ -d "$src" ] || return 0
  mkdir -p "$dst"
  cp -R "$src/." "$dst/"
}

# --- module skeleton ---
for m in $MODULES; do
  mkdir -p "$MOD/$m/pages" "$MOD/$m/partials" "$MOD/$m/assets/images"
done

# --- ROOT: product pages + meta tables ---
for f in "$SRC"/*.adoc; do
  [ -f "$f" ] && cp -f "$f" "$MOD/ROOT/pages/"
done
mkdir -p "$MOD/ROOT/pages/meta"
for f in "$META"/*.adoc; do
  [ -f "$f" ] && cp -f "$f" "$MOD/ROOT/pages/meta/"
done

# --- ROOT: subsystem port_table partials (referenced from integration_guide) ---
for s in $PORT_TABLE_SYS; do
  pt="$ROOT/hw/sys/$s/doc/port_table.adoc"
  if [ -f "$pt" ]; then
    mkdir -p "$MOD/ROOT/partials/hw/$s/doc"
    cp -f "$pt" "$MOD/ROOT/partials/hw/$s/doc/port_table.adoc"
  fi
done

# --- subsystems: pages + register partials ---
for s in $SUBSYSTEMS; do
  stage_adoc_tree "$ROOT/hw/sys/$s/doc" "$MOD/$s/pages"
  stage_gen_adoc "$ROOT/hw/sys/$s/regs/gen/adoc" "$MOD/$s/partials/$s/regs/gen/adoc"
  stage_gen_html "$ROOT/hw/sys/$s/regs/gen/html" "$MOD/$s/partials/$s/regs/gen/html"
  stage_gen_adoc "$ROOT/hw/sys/$s/dv/shims/regs/gen/adoc" "$MOD/$s/partials/$s/dv/shims/regs/gen/adoc"
  stage_gen_html "$ROOT/hw/sys/$s/dv/shims/regs/gen/html" "$MOD/$s/partials/$s/dv/shims/regs/gen/html"
done

# --- ip: collapse every hw/ip/<ip>/doc under <ip>/doc, partials per IP. Register
#     partials are staged for every IP (even register-only IPs with no doc/ dir,
#     e.g. zeroer referenced by SMC). AXI network/monitor elements live under
#     hw/common/axi/<name> but are register-only from the doc perspective, so they
#     are staged into the same ip module namespace (e.g. axi_alias_remap,
#     axi_filter, output_remap referenced by SMC fabric). Family-grouped IPs live
#     one level deeper (hw/ip/<family>/<ip>, e.g. jtag/uart/cross_trigger); the
#     hw/ip/*/*/ glob picks them up by basename (=<ip>), and the flat-IP subdirs it
#     also enumerates (rtl/regs/dv/doc) have no doc/ or regs/gen so they stage nothing. ---
for ipdir in "$ROOT"/hw/ip/*/ "$ROOT"/hw/ip/*/*/ "$ROOT"/hw/common/axi/*/; do
  ip="$(basename "$ipdir")"
  [ -d "$ipdir/doc" ] && stage_adoc_tree "$ipdir/doc" "$MOD/ip/pages/$ip/doc"
  stage_gen_adoc "$ipdir/regs/gen/adoc" "$MOD/ip/partials/$ip/regs/gen/adoc"
  stage_gen_html "$ipdir/regs/gen/html" "$MOD/ip/partials/$ip/regs/gen/html"
  stage_gen_adoc "$ipdir/dv/shims/regs/gen/adoc" "$MOD/ip/partials/$ip/dv/shims/regs/gen/adoc"
  stage_gen_html "$ipdir/dv/shims/regs/gen/html" "$MOD/ip/partials/$ip/dv/shims/regs/gen/html"
done

# --- images: aggregate hw doc images into doc/assets (PDF) and module images
#     (HTML). Flattened by basename so references resolve regardless of source. ---
while IFS= read -r img; do
  mkdir -p "$ASSETS"
  cp -f "$img" "$ASSETS/" 2>/dev/null || true
done < <(find "$ROOT"/hw/ip/*/doc "$ROOT"/hw/ip/*/*/doc "$ROOT"/hw/sys/*/doc -type f \
  \( -name '*.png' -o -name '*.svg' -o -name '*.jpg' -o -name '*.jpeg' \) 2>/dev/null)

stage_module_assets() {
  local src="$1"
  [ -d "$src" ] || return 0
  for m in $MODULES; do
    for ext in png svg jpg jpeg; do
      cp -f "$src"/*.$ext "$MOD/$m/assets/images/" 2>/dev/null || true
    done
  done
}

stage_module_assets "$COMMON_ASSETS"
stage_module_assets "$ASSETS"

echo "Staged Antora modules under $MOD"
