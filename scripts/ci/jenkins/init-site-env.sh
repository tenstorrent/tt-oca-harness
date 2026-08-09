#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Source this file inside each Jenkins shell step that needs licensed EDA
# tools. Jenkins starts non-login shells, so the Environment Modules function
# is not guaranteed to exist even though the node has the corporate module
# tree installed.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "ERROR: source scripts/ci/jenkins/init-site-env.sh; do not execute it" >&2
    exit 2
fi

if [[ "${OCAH_SITE_ENV_READY:-0}" == "1" ]]; then
    return 0
fi

set +u
if ! type module >/dev/null 2>&1; then
    for init_script in \
        /tools_soc/tt/bin/bashrc \
        /etc/profile \
        /etc/profile.d/modules.sh \
        /usr/share/Modules/init/bash \
        /usr/share/lmod/lmod/init/bash
    do
        if [[ -r "$init_script" ]]; then
            # shellcheck disable=SC1090
            source "$init_script" >/dev/null 2>&1 || true
        fi
        type module >/dev/null 2>&1 && break
    done
fi
set -u

if ! type module >/dev/null 2>&1; then
    echo "ERROR: unable to initialize the Environment Modules command" >&2
    return 2
fi

module purge >/dev/null 2>&1 || true
if [[ -r /tools_soc/tt/bin/bashrc ]]; then
    set +u
    # shellcheck disable=SC1091
    source /tools_soc/tt/bin/bashrc >/dev/null 2>&1 || true
    set -u
fi

site_module="${OCAH_SITE_MODULE:-tt_ocah_env}"
if module load "$site_module" >/dev/null 2>&1; then
    echo "Loaded site module: $site_module"
else
    echo "Site module '$site_module' is unavailable; loading required tools directly."
    module load gcc/11.2.1
    module load bender/0.28.1-tenstorrent8-mr_fixes
    module load synopsys/licenses/2.3
    module load synopsys/vcs/X-2025.06
    module load synopsys/verdi/X-2025.06
    module load perl/5.36.0
    module load soc_tools
fi

export PATH="$HOME/.local/bin:/tools_soc/opensrc/riscv-gnu-toolchain/2025.01.20-rhel-8.10/bin:$PATH"
export OCAH_SITE_ENV_READY=1

for required_tool in vcs bender; do
    if ! command -v "$required_tool" >/dev/null 2>&1; then
        echo "ERROR: $required_tool is unavailable after site environment setup" >&2
        return 2
    fi
done
