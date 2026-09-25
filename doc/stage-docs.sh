#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#
# Stage Antora module sources for one OCAH documentation product from the hw
# tree. Product makefrags pass OCAH_DOC_PRODUCT_* paths. All staged output is
# gitignored throwaway build input: the single source of truth stays in each
# product's src/meta tree, hw/**/doc and hw/**/regs/gen, plus explicitly staged
# vendored documentation.
#
# Modules: ROOT, smc, sep, dtp, aou, ip; SMU is enabled by the TRM product.
#   - ROOT: product src/*.adoc + meta tables + subsystem port_table partials.
#   - subsystem modules: hw/sys/<sys>/doc pages and regs/gen partials.
#   - aou: selected content from the vendored AXI-over-UCIe specification.
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
AOU_DOC="$ROOT/vendor/tenstorrent/aou/upstream/DOC/MAS"
AOU_INTEGRATION_GUIDE="$ROOT/vendor/tenstorrent/aou/upstream/DOC/integration_guide"

SUBSYSTEMS="smc sep dtp smc/bootrom/prod sep/bootrom/prod"
# The SMU chapter links into the TRM's ROOT module. Other products retain
# their existing subsystem pages and the independent ROOT SMU port partial.
if [ "${OCAH_DOC_PRODUCT_INCLUDE_SMU:-0}" = "1" ]; then
  SUBSYSTEMS="$SUBSYSTEMS smu"
else
  # Remove stale SMU pages/assets from builds predating product scoping.
  rm -rf "${MOD:?}/smu"
fi
PORT_TABLE_SYS="smc sep dtp smu"
MODULES="ROOT $SUBSYSTEMS aou ip"

clean() {
  rm -rf "$MOD/ROOT/pages" "$MOD/ROOT/partials/hw" "$MOD/ROOT/assets"
  for m in smc sep dtp smu aou ip; do
    rm -rf "${MOD:?}/$m"
  done
  rm -f "$ASSETS"/aou-*
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
  python3 "$ROOT/tools/doc/scope_register_ids.py" "$src" "$dst"
}

# draw.io-exported SVGs append a trailing <switch> fallback block ("Text is
# not SVG - cannot display" + FAQ link) for renderers without SVG
# Extensibility support. Browsers report support correctly and never show
# it; asciidoctor-pdf's SVG renderer (prawn-svg) doesn't recognize the
# feature and renders the fallback text visibly in PDF output.
#
# Run as a postprocess step over every staged assets location (below), not
# as a preprocess step on the aggregation source, so it also catches SVGs
# checked in directly to a product's own assets/ that never pass through
# the hw/*/doc aggregation loop at all.

strip_drawio_switch_fallback() {
  local dir="$1"
  [ -d "$dir" ] || return 0
  find "$dir" -name '*.svg' -type f -print0 | while IFS= read -r -d '' svg; do
    local tmp
    tmp="$(mktemp)"
    tr '\n' ' ' <"$svg" |
      sed 's#<switch><g requiredFeatures="[^"]*\#Extensibility"[^/]*/> *<a[^>]*xlink:href="https://www\.drawio\.com/doc/faq/svg-export-text-problems"[^>]*> *<text[^>]*>.*</text></a></switch>##' \
        >"$tmp" 2>/dev/null && mv -f "$tmp" "$svg" || rm -f "$tmp"
  done
}

# --- module skeleton ---
for m in $MODULES; do
  mt=$(echo $m | tr / -)
  mkdir -p "$MOD/$mt/pages" "$MOD/$mt/partials" "$MOD/$mt/assets/images"
done

# --- ROOT: product pages + meta tables ---
for f in "$SRC"/*.adoc; do
  [ -f "$f" ] && cp -f "$f" "$MOD/ROOT/pages/"
done
if [ "${OCAH_DOC_PRODUCT_INCLUDE_REVISION:-1}" != "1" ]; then
  rm -f "$MOD/ROOT/pages/revision.adoc" "$MOD/ROOT/pages/aou-records-of-changes.adoc"
fi
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
  m=$(echo $s | tr / -)
  stage_adoc_tree "$ROOT/hw/sys/$s/doc" "$MOD/$m/pages"
  stage_gen_adoc "$ROOT/hw/sys/$s/regs/gen/adoc" "$MOD/$m/partials/$m/regs/gen/adoc"
  stage_gen_html "$ROOT/hw/sys/$s/regs/gen/html" "$MOD/$m/partials/$m/regs/gen/html"
  stage_gen_adoc "$ROOT/hw/sys/$s/dv/models/regs/gen/adoc" "$MOD/$m/partials/$m/dv/models/regs/gen/adoc"
  stage_gen_html "$ROOT/hw/sys/$s/dv/models/regs/gen/html" "$MOD/$m/partials/$m/dv/models/regs/gen/html"
done
# DTP and SMU port tables are private ROOT partials included by their owning pages.
rm -f "$MOD/dtp/pages/port_table.adoc" "$MOD/smu/pages/port_table.adoc"

# --- aou: each product stages only the section it publishes ---
rm -rf "$MOD/aou"
mkdir -p "$MOD/aou/pages" "$MOD/aou/partials" "$MOD/aou/assets/images"
case "$(basename "$PRODUCT")" in
trm)
  mkdir -p "$MOD/aou/partials/pdf"
  for page in overview architecture interrupts-errors ppa-appendices software-operation; do
    sed -E 's/(xref:(figure|table)-[0-9]+)\[(Figure|Table) [0-9]+\]/\1[]/g' "$AOU_DOC/$page.adoc" \
      >"$MOD/aou/partials/$page.adoc"
    # The PDF inherits book numbering instead of the standalone specification's numbers.
    sed -E 's/^(={2,6}) [0-9]+(\.[0-9]+)*\. /\1 /; s/(xref:(figure|table)-[0-9]+)\[(Figure|Table) [0-9]+\]/\1[]/g' "$AOU_DOC/$page.adoc" \
      >"$MOD/aou/partials/pdf/$page.adoc"
  done
  # The web appendices have separate pages; the PDF keeps the complete section.
  sed '/^ifndef::release\[\]/,$d' "$AOU_DOC/ppa-appendices.adoc" \
    >"$MOD/aou/partials/ppa-appendices.adoc"
  sed -n '/^ifndef::release\[\]/,/^endif::release\[\]/p' "$AOU_DOC/ppa-appendices.adoc" \
    >"$MOD/aou/partials/records-of-changes.adoc"
  sed -n '/^\[\[appendix-b-referenced-documents\]\]/,$p' "$AOU_DOC/ppa-appendices.adoc" \
    >"$MOD/aou/partials/referenced-documents.adoc"
  aou_pages="overview architecture interrupts-errors ppa-appendices records-of-changes referenced-documents software-operation"
  for page in $aou_pages; do
    # Published fragments land beside the link to their owning topic page.
    {
      echo '++++'
      sed -nE 's/^\[\[([^],]+)\]\]$/<span id="\1"><\/span>/p' "$MOD/aou/partials/$page.adoc"
      echo '++++'
    } >"$MOD/aou/partials/$page-anchors.adoc"
  done
  # Antora topics need page-qualified links; PDF partials retain same-book links.
  sed -i -f <(
    for page in $aou_pages; do
      sed -nE "s/^\[\[([^],]+)\]\]$/s@xref:\1\\\\[@xref:ROOT:aou-$page.adoc#\1[@g/p" \
        "$MOD/aou/partials/$page.adoc"
    done
  ) "$MOD"/aou/partials/{overview,architecture,interrupts-errors,ppa-appendices,records-of-changes,referenced-documents}.adoc
  ;;
integrator)
  cp -f "$AOU_INTEGRATION_GUIDE/integrator.adoc" "$MOD/aou/partials/"
  ;;
programmer)
  cp -f "$AOU_DOC/software-operation.adoc" "$MOD/aou/partials/"
  ;;
esac

# DTP: exclude defines.adoc (DV content, not for publication).
rm -f "$MOD/dtp/pages/defines.adoc"

# --- ip: collapse every hw/ip/<ip>/doc under <ip>/doc, partials per IP. Register
#     partials are staged for every IP (even register-only IPs with no doc/ dir,
#     e.g. zeroer referenced by SMC). AXI network/monitor elements live under
#     hw/ip/<name> and are staged into the ip module namespace (e.g. axi_alias_remap,
#     axi_filter, output_remap referenced by SMC fabric). Family-grouped IPs live
#     one level deeper (hw/ip/<family>/<ip>, e.g. jtag/uart/cross_trigger); the
#     hw/ip/*/*/ glob picks them up by basename (=<ip>), and the flat-IP subdirs it
#     also enumerates (rtl/regs/dv/doc) have no doc/ or regs/gen so they stage nothing. ---
for ipdir in "$ROOT"/hw/ip/*/ "$ROOT"/hw/ip/*/*/; do
  ip="$(basename "$ipdir")"
  [ -d "$ipdir/doc" ] && stage_adoc_tree "$ipdir/doc" "$MOD/ip/pages/$ip/doc"
  stage_gen_adoc "$ipdir/regs/gen/adoc" "$MOD/ip/partials/$ip/regs/gen/adoc"
  stage_gen_html "$ipdir/regs/gen/html" "$MOD/ip/partials/$ip/regs/gen/html"
  stage_gen_adoc "$ipdir/dv/models/regs/gen/adoc" "$MOD/ip/partials/$ip/dv/models/regs/gen/adoc"
  stage_gen_html "$ipdir/dv/models/regs/gen/html" "$MOD/ip/partials/$ip/dv/models/regs/gen/html"
done

# --- ip: index pages include their topic fragments. For IP_PAGE_OWNERS,
#     the topic fragments listed in IP_FRAGMENTS move out of pages/ and into
#     partials/ so they are private (no standalone URL). The owning index page
#     includes them via the partial$ prefix for HTML or a relative path for PDF.
#     CTN memmap.adoc also moves to partials/; it owns CTM and CTP register maps.
IP_PAGE_OWNERS="jtag_intf_unit jtag_ptap jtag_stap
cross_trigger_network cross_trigger_port cross_trigger_matrix
avsbus_controller axi_lite_mailbox_unit efuse gpio i2c system_timer_octs
telemetry_receiver uart_16550 log_engine i3ccore_wrap
drbg entropy_source key_manager scrambler"
IP_FRAGMENTS="architecture.adoc interface.adoc memmap.adoc programming.adoc firmware.adoc"
for ip in $IP_PAGE_OWNERS; do
  src="$MOD/ip/pages/$ip/doc"
  dst="$MOD/ip/partials/$ip/doc"
  for frag in $IP_FRAGMENTS; do
    if [ -f "$src/$frag" ]; then
      mkdir -p "$dst"
      mv "$src/$frag" "$dst/$frag"
    fi
  done
done

# The TRM's combined TRNG/DRBG page alias and a standalone DRBG page cannot
# own the same URL. The DRBG architecture remains a reusable partial.
if [ "$(basename "$PRODUCT")" = "trm" ]; then
  rm -f "$MOD/ip/pages/drbg/doc/index.adoc"
fi

# --- opentitan overlay: vendored OpenTitan IPs (e.g. csrng, edn) whose register
#     collateral is generated into the lowRISC overlay rather than hw/ip, because
#     they are instantiated through wrappers (e.g. the DRBG wraps CSRNG and EDN).
#     Stage each under the ip module namespace so its generated maps include like
#     any other IP. Overlay names do not collide with hw/ip. ---
for otdir in "$ROOT"/vendor/lowRISC/opentitan/overlay/regs/*/; do
  [ -d "$otdir" ] || continue
  ip="$(basename "$otdir")"
  stage_gen_adoc "$otdir/regs/gen/adoc" "$MOD/ip/partials/$ip/regs/gen/adoc"
  stage_gen_html "$otdir/regs/gen/html" "$MOD/ip/partials/$ip/regs/gen/html"
done

# --- pulp-platform overlay: the iDMA frontend register block (dma_ctrl) is
#     generated into the pulp overlay's flat rdl/gen tree rather than hw/ip,
#     because it is instantiated through the SMC DMA wrapper. The overlay vends a
#     single block, so stage its flat gen under the block-named ip partial
#     namespace (ip:partial$dma_ctrl) like the OpenTitan overlay above. ---
stage_gen_adoc "$ROOT/vendor/pulp-platform/idma/overlay/rdl/gen/adoc" "$MOD/ip/partials/dma_ctrl/regs/gen/adoc"
stage_gen_html "$ROOT/vendor/pulp-platform/idma/overlay/rdl/gen/html" "$MOD/ip/partials/dma_ctrl/regs/gen/html"

# --- images: aggregate hw doc images into doc/assets (PDF) and module images
#     (HTML). Flattened by basename so references resolve regardless of source. ---
while IFS= read -r img; do
  mkdir -p "$ASSETS"
  cp -f "$img" "$ASSETS/" 2>/dev/null || true
done < <(find -L "$ROOT"/hw/ip/*/doc "$ROOT"/hw/ip/*/*/doc "$ROOT"/hw/sys/*/doc -type f \
  \( -name '*.png' -o -name '*.svg' -o -name '*.jpg' -o -name '*.jpeg' \) 2>/dev/null)

stage_module_assets() {
  local src="$1"
  local modules="${2:-$MODULES}"
  [ -d "$src" ] || return 0
  for m in $modules; do
    for ext in png svg jpg jpeg; do
      cp -f "$src"/*.$ext "$MOD/$m/assets/images/" 2>/dev/null || true
    done
  done
}

stage_module_assets "$COMMON_ASSETS"
stage_module_assets "$ASSETS"
# Antora resolves an unqualified image target in an included partial
# against the *including* page's own module, not the partial's origin
# module, so the images must also land in ROOT (every product includes the
# AOU partial from a ROOT page).
stage_module_assets "$AOU_DOC/assets" "aou ROOT"
stage_module_assets "$AOU_INTEGRATION_GUIDE/assets" "aou ROOT"

# Postprocess every location that ends up holding a copy of these images --
# after all copying above is done.
strip_drawio_switch_fallback "$ASSETS"
strip_drawio_switch_fallback "$COMMON_ASSETS"
for m in $MODULES; do
  strip_drawio_switch_fallback "$MOD/$m/assets/images"
done

echo "Staged Antora modules under $MOD"
