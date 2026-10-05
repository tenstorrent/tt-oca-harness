#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

rule_color="$(tput setaf 6 2>/dev/null || true)"
section_color="$(tput setaf 3 2>/dev/null || true)"
variable_color="$(tput setaf 2 2>/dev/null || true)"
value_color="$(tput setaf 1 2>/dev/null || true)"
clear_style="$(tput sgr0 2>/dev/null || true)"

echo "Usage: make [${rule_color}TARGET${clear_style} ...] [${variable_color}ARG${clear_style}=${value_color}VALUE${clear_style} ...]"
echo "${section_color}Targets:${clear_style}"
echo "    ${rule_color}help${clear_style}"
echo "        Show this help"
echo ""

target_regex="^[a-zA-Z0-9%_\/%-]+:"
section_regex="^##[[:space:]]*@section[[:space:]]*(.*)$"
docblock_regex="^##[[:space:]]+(.+)$"
param_regex="@param[[:space:]]+([a-zA-Z_]+)(=([^[:space:]]+))?[[:space:]]*(.*$)?"

comment=""
params=""
params_doc=""

for file in ${MAKEFILES}; do
  while IFS= read -r line; do
    if [[ -z "${line}" ]]; then
      continue
    fi

    if [[ "${line}" =~ ${section_regex} ]]; then
      section_name="$(echo "${line}" | sed -e "s/^##[[:space:]]*@section[[:space:]]*//g")"
      echo "${section_color}${section_name}${clear_style}:"
    elif [[ "${line}" =~ ${target_regex} ]]; then
      if [[ -n "${comment}" ]]; then
        target="$(echo "${line}" | sed -e "s/^\([a-zA-Z0-9%_\/%-]\+\):.*/\1/g")"
        display_target="${target#ocah-}"
        echo "    ${rule_color}${display_target}${clear_style} ${params}"
        echo -e "${comment}"
        if [[ -n "${params_doc}" ]]; then
          echo "        Params:"
          echo -e "${params_doc}"
        fi
      fi
      comment=""
      params=""
      params_doc=""
    elif [[ "${line}" =~ ${param_regex} ]]; then
      param="$(echo "${line}" | sed -e "s/##[[:space:]]*@param[[:space:]]\+\([a-zA-Z_]\+\)\(=\([^[:space:]]\+\)\)\?[[:space:]]*\(.*\)\?$/${variable_color}\1${clear_style}=${value_color}\3${clear_style}/g")"
      param_doc="$(echo "${line}" | sed -e "s/##[[:space:]]*@param[[:space:]]\+\([a-zA-Z_]\+\)\(=\([^[:space:]]\+\)\)\?[[:space:]]*\(.*\)\?$/- \1 (example: \3) \4/g")"
      params="${params}${param} "
      params_doc="${params_doc}         ${param_doc}\n"
    elif [[ "${line}" =~ ${docblock_regex} ]]; then
      line_cleaned="$(echo "${line}" | sed -e "s/^##\+[[:space:]]*\(.*\)$/\1/g")"
      comment="${comment}        ${line_cleaned}\n"
    fi
  done <"${file}"
done
