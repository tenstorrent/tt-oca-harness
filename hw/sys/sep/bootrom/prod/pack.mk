# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# OCA image packing shared by the boot ROM and the BL1 builds. The including
# Makefile defines OCAH_ROOT and BUILD_DIR first.

PACK_MK_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
TT_OCA_MANIFEST_DIR ?= $(PACK_MK_DIR)/tools/tt-oca-manifest

UV ?= uv
# Cap the wheel platform on older glibc hosts; an existing environment may
# otherwise retain an ABI-incompatible cryptography wheel.
MANIFEST_UV_PLATFORM := $(shell python3 -c 'import platform; libc, ver = platform.libc_ver(); parts = tuple(int(x) for x in ver.split(".")[:2]) if ver else (0, 0); machine = platform.machine(); print("" if libc != "glibc" or parts >= (2, 34) else f"{machine}-manylinux_2_28" if parts >= (2, 28) else f"{machine}-manylinux_2_17")' 2>/dev/null)
MANIFEST_UV_FLAGS := $(if $(MANIFEST_UV_PLATFORM),--python-platform $(MANIFEST_UV_PLATFORM) --reinstall-package cryptography,)
MANIFEST_PYTHON ?= $(UV) --project "$(OCAH_ROOT)" run --locked --group manifest $(MANIFEST_UV_FLAGS) python

# Keep packing isolated from the root project. The distribution is
# tt-oca-manifest, but its import package remains tt_boot_manifest. Resolve
# native wheels per invocation to avoid reusing another host's ABI artifacts.
ifneq ($(shell command -v uv 2>/dev/null),)
PACK_RUN := $(MANIFEST_PYTHON) -m tt_boot_manifest.pack_images
else
# PYTHONPATH cannot express package-dir remapping, so provide a symlink shim.
# Keep setup and execution in one shell so caller environment prefixes reach the packer.
PACK_SHIM := $(BUILD_DIR)/.pack-shim
PACK_RUN = sh -c 'mkdir -p "$(PACK_SHIM)" && \
	ln -sfn "$(abspath $(TT_OCA_MANIFEST_DIR))/src" "$(PACK_SHIM)/tt_boot_manifest" && \
	PYTHONPATH="$(PACK_SHIM)" exec python3 -m tt_boot_manifest.pack_images "$$@"' tt-pack
endif

.PHONY: ensure-pack-deps
ensure-pack-deps:
	@test -f "$(TT_OCA_MANIFEST_DIR)/pyproject.toml" || { \
	  echo "ERROR: the tt-oca-manifest submodule is not checked out."; \
	  echo "       Expected: $(TT_OCA_MANIFEST_DIR)"; \
	  echo "       Run: git -C $(OCAH_ROOT) submodule update --init \\"; \
	  echo "              hw/sys/sep/bootrom/prod/tools/tt-oca-manifest"; \
	  exit 1; }
	@command -v uv >/dev/null || $(MANIFEST_PYTHON) -c 'import cryptography, ruamel.yaml, tomlkit, bitarray' 2>/dev/null || { \
	  echo "ERROR: uv not found and the packer's Python deps are not importable."; \
	  echo "       Either install uv (https://docs.astral.sh/uv/getting-started/installation/,"; \
	  echo "       tools/dv/run_dv.py requires the same tool, so this is a one-off), or"; \
	  echo "       provide python3 with cryptography, ruamel.yaml, tomlkit and bitarray."; \
	  exit 1; }

# Recipe for an image target that a release build must refuse: every in-tree
# config signs with a private test key.
define pack_refuse_release
@echo "ERROR: $@ is not implemented for BUILD_TYPE=release."; \
echo "       The configs sign with the private test keys in tests/signing_keys/,"; \
echo "       which must never produce a flashable release image."; \
echo "       Production signing needs a key store (signing_authority=hsm/aws)"; \
echo "       and is not wired up yet."; \
echo "       For test images: make BUILD_TYPE=debug $@"; \
exit 1
endef
