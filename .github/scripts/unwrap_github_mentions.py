#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unwrap code-span GitHub @mentions in safe-output comment bodies.

A login inside backticks is a code span, not a GitHub mention. This
rewrites `body` strings in agent JSON/JSONL before safe-outputs posts
them. gh-aw mention filtering still escapes people who are not
collaborators or issue/PR context.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# GitHub login: 1–39 ASCII alphanumerics or hyphens, not starting or ending
# with a hyphen. Teams (@org/team) are left wrapped.
MENTION_SPAN = re.compile(r"`(@[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)`")

DEFAULT_PATHS = (
    "/tmp/gh-aw/agent_output.json",
    "/tmp/gh-aw/safeoutputs.jsonl",
)


def unwrap_text(text: str) -> str:
    return MENTION_SPAN.sub(r"\1", text)


def unwrap_comment_bodies(value: object) -> object:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "body" and isinstance(item, str):
                out[key] = unwrap_text(item)
            else:
                out[key] = unwrap_comment_bodies(item)
        return out
    if isinstance(value, list):
        return [unwrap_comment_bodies(item) for item in value]
    return value


def rewrite_json_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    rewritten = unwrap_comment_bodies(data)
    if rewritten == data:
        return False
    path.write_text(json.dumps(rewritten, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def rewrite_jsonl_file(path: Path) -> bool:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = False
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        data = json.loads(stripped)
        rewritten = unwrap_comment_bodies(data)
        if rewritten != data:
            changed = True
            newline = "\n" if line.endswith("\n") else ""
            out.append(json.dumps(rewritten, ensure_ascii=False) + newline)
        else:
            out.append(line)
    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


def rewrite_path(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    text = path.read_text(encoding="utf-8", errors="replace").lstrip()
    if text.startswith("{"):
        return rewrite_json_file(path)
    return rewrite_jsonl_file(path)


def files_to_rewrite(argv: list[str]) -> list[Path]:
    env_out = os.environ.get("GH_AW_SAFE_OUTPUTS", "").strip()
    paths = [Path(p) for p in argv]
    if env_out:
        paths.append(Path(env_out))
    if not argv:
        paths.extend(Path(p) for p in DEFAULT_PATHS)
    # Preserve order, drop duplicates.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def main(argv: list[str]) -> int:
    changed_any = False
    for path in files_to_rewrite(argv):
        try:
            if rewrite_path(path):
                print(f"unwrapped mentions in {path}", file=sys.stderr)
                changed_any = True
        except (OSError, json.JSONDecodeError) as exc:
            print(f"skip {path}: {exc}", file=sys.stderr)
    if not changed_any:
        print("no backtick-wrapped mentions to unwrap", file=sys.stderr)
    return 0


def _self_test() -> None:
    import tempfile

    assert unwrap_text("`@minshaohoTT` — review") == "@minshaohoTT — review"
    assert unwrap_text("@already-plain") == "@already-plain"
    assert unwrap_text("`@org/team`") == "`@org/team`"
    item = {"type": "add_comment", "body": "`@aottavianoTT` please look"}
    assert unwrap_comment_bodies(item)["body"] == "@aottavianoTT please look"
    wrapped = {"items": [item], "noop": {"message": "leave `code` alone"}}
    out = unwrap_comment_bodies(wrapped)
    assert out["items"][0]["body"] == "@aottavianoTT please look"
    assert out["noop"]["message"] == "leave `code` alone"

    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "agent_output.json"
        json_path.write_text(
            json.dumps({"items": [{"type": "add_comment", "body": "`@minshaohoTT` hi"}]}),
            encoding="utf-8",
        )
        assert rewrite_path(json_path)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["items"][0]["body"] == "@minshaohoTT hi"

        jsonl_path = Path(tmp) / "safeoutputs.jsonl"
        jsonl_path.write_text(
            '{"type":"add_comment","body":"`@nbetikTT` review"}\n',
            encoding="utf-8",
        )
        assert rewrite_path(jsonl_path)
        line = json.loads(jsonl_path.read_text(encoding="utf-8"))
        assert line["body"] == "@nbetikTT review"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        _self_test()
    else:
        raise SystemExit(main(sys.argv[1:]))
