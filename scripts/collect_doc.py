#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
collect_doc.py -- gather every .adoc/image file that makes up one OCAH
document (as built for the PDF backend) into a single mirror tree,
preserving each file's original repo-relative path.

Follows the PDF-backend include chain only (ifdef::backend-pdf[] blocks),
since those are always real, directly-resolvable filesystem paths -- the
ifdef::backend-html5[] branch is skipped entirely, including any
partial$.../component:module-style resource-ID includes inside it, which
aren't real filesystem paths at all outside an Antora build.

Usage:
    python3 collect_doc.py --start doc/trm/src/index.adoc --target /tmp/trm-mirror
    python3 collect_doc.py --start doc/trm/src/index.adoc --target /tmp/trm-mirror --images
    python3 collect_doc.py --start /doc/trm/src/index.adoc --target /tmp/trm-mirror --repo-root /mnt/c/git/tt-oca-harness

By default, only .adoc files are collected. Pass --images to also copy
images referenced via image::/image: macros.

--start accepts either:
  - a real filesystem path (absolute or relative to cwd), or
  - a repo-root-relative path, with or without a leading slash
    (e.g. "/doc/trm/src/index.adoc" or "doc/trm/src/index.adoc")

If --repo-root is not given, it's auto-detected by walking upward from the
resolved start file looking for a ".git" directory.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# Matches include:: directives. Captures the path before the first '['.
# Attributes inside the brackets ([leveloffset=+1] etc.) are intentionally
# not captured -- only the bare path is needed.
INCLUDE_RE = re.compile(r"include::([^\[\]]+)\[")

# Matches image:: (block) and image: (inline) macros. Same bracket handling
# as above.
IMAGE_RE = re.compile(r"image::?([^\[\]]+)\[")

IMAGESDIR_RE = re.compile(r"^:imagesdir:\s*(.+?)\s*$")

IFDEF_RE = re.compile(r"^(ifdef|ifndef)::([\w,-]+)\[\]\s*$")
ENDIF_RE = re.compile(r"^endif::.*\[\]\s*$")

IMAGE_EXTS = {".png", ".svg", ".jpg", ".jpeg", ".gif"}


def looks_like_resource_id(path: str) -> bool:
    """Antora resource-ID includes (partial$foo, smc:index.adoc,
    ip:foo/doc/index.adoc) aren't real filesystem paths. These should
    already be excluded since they only ever appear inside
    ifdef::backend-html5[] blocks, but this is a defensive second check
    in case one is ever found unconditionally or outside such a block."""
    if path.startswith("partial$"):
        return True
    # component:module-qualified resource id, e.g. "smc:index.adoc" or
    # "ip:foo/doc/index.adoc" -- a bare word then a colon then no
    # backslash/drive-letter pattern and not a URL scheme.
    if re.match(r"^[A-Za-z_][\w-]*:(?!//)", path):
        return True
    if path.startswith("http://") or path.startswith("https://"):
        return True
    return False


def find_repo_root(start_file: Path) -> Path | None:
    cur = start_file.resolve().parent
    for _ in range(50):
        if (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def resolve_start_path(start_arg: str, repo_root: Path | None) -> Path:
    p = Path(start_arg)
    if p.exists():
        return p.resolve()
    if repo_root is not None:
        candidate = repo_root / start_arg.lstrip("/")
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(
        f"could not resolve start path '{start_arg}' as a real filesystem "
        f"path or as repo-root-relative under {repo_root}"
    )


class Collector:
    def __init__(
        self,
        repo_root: Path,
        target_root: Path,
        include_images: bool = False,
        exclude_tables: bool = False,
    ):
        self.repo_root = repo_root
        self.target_root = target_root
        self.include_images = include_images
        self.exclude_tables = exclude_tables
        self.visited: set[Path] = set()
        self.copied: list[Path] = []
        self.excluded_table_count: int = 0
        self.warnings: list[str] = []
        # :imagesdir: is a document-wide AsciiDoc attribute: once set
        # anywhere in the include chain, it stays in effect for every file
        # processed afterward (including siblings/children that never set
        # it themselves), not just the file that declared it. This is
        # tracked as shared state across the whole recursive walk, updated
        # in the same top-to-bottom, depth-first order the real include
        # chain is processed in, rather than being reset per file.
        self.imagesdir: str | None = None

    def copy_preserving_structure(self, abs_path: Path) -> None:
        try:
            rel = abs_path.relative_to(self.repo_root)
        except ValueError:
            self.warnings.append(f"skipped (outside repo root {self.repo_root}): {abs_path}")
            return
        dest = self.target_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(abs_path, dest)
        self.copied.append(rel)

    def process_file(self, abs_path: Path) -> None:
        abs_path = abs_path.resolve()
        if abs_path in self.visited:
            return
        self.visited.add(abs_path)

        if not abs_path.exists():
            self.warnings.append(f"missing file, could not process: {abs_path}")
            return

        self.copy_preserving_structure(abs_path)

        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.warnings.append(f"could not read {abs_path}: {e}")
            return

        current_dir = abs_path.parent
        # Each frame is (skip: bool, kind: 'html5' | 'pdf' | 'other').
        # 'kind' is tracked (beyond a bare skip/no-skip boolean) purely to
        # support register-table detection below: a register-table pair is
        # an ifdef::backend-html5[] block whose passthrough-wrapped include
        # targets an .html file, paired with an immediately-following
        # ifdef::backend-pdf[] block whose include targets an .adoc file
        # with the *same basename*. Normal content includes (chapters,
        # whole-book cross-references like "smc:index.adoc") never have an
        # .html counterpart at all, so this is a reliable, path-independent
        # signal -- unlike matching on directory substrings like
        # "regs/gen/adoc", which isn't consistent (some generators use
        # "rdl/gen/adoc" instead).
        skip_stack: list[tuple[bool, str]] = []
        # Basenames (no extension) seen as .html passthrough targets while
        # inside a backend-html5 frame, pending a match against a following
        # backend-pdf frame's .adoc includes. Cleared whenever a pdf frame
        # ends, so pairing scope is "one html5 block, then one pdf block"
        # (which may itself batch several register blocks together, as in
        # cpu_registers.adoc), not a stricter per-include adjacency.
        pending_table_basenames: set[str] = set()

        for raw_line in text.splitlines():
            stripped = raw_line.strip()

            # AsciiDoc line comments suppress any directive on that line too.
            if stripped.startswith("//"):
                continue

            m = IFDEF_RE.match(stripped)
            if m:
                kind_word, cond = m.group(1), m.group(2)
                is_html5 = "backend-html5" in cond
                is_pdf = "backend-pdf" in cond
                if kind_word == "ifdef" and is_html5:
                    skip_stack.append((True, "html5"))
                elif kind_word == "ifdef" and is_pdf:
                    skip_stack.append((False, "pdf"))
                elif kind_word == "ifndef" and is_pdf:
                    # "if PDF backend is NOT active" == html5-only branch
                    skip_stack.append((True, "html5"))
                elif kind_word == "ifndef" and is_html5:
                    skip_stack.append((False, "pdf"))
                else:
                    # Some other, non-backend condition -- process normally,
                    # just keep the stack balanced for its endif.
                    skip_stack.append((False, "other"))
                continue

            if ENDIF_RE.match(stripped):
                if skip_stack:
                    _, popped_kind = skip_stack.pop()
                    if popped_kind == "pdf":
                        pending_table_basenames.clear()
                continue

            currently_skipping = any(skip for skip, _ in skip_stack)
            in_pdf_frame = any(kind == "pdf" for _, kind in skip_stack)
            in_html5_frame = any(kind == "html5" for _, kind in skip_stack)

            m = IMAGESDIR_RE.match(stripped)
            if not currently_skipping and m:
                # Resolved to an absolute path immediately, relative to
                # *this* file's own directory at the point of declaration --
                # baking that in now means every later image:: reference
                # (in this file or any file processed afterward) uses the
                # correct base regardless of which file it's physically
                # written in, matching AsciiDoc's document-wide attribute
                # semantics without needing to track "declared in which
                # file" separately.
                self.imagesdir = str((current_dir / m.group(1)).resolve())
                continue

            m = INCLUDE_RE.search(raw_line)
            if m:
                inc_path = m.group(1).strip()

                # Inside a skipped html5 frame: don't follow anything, but
                # do note .html passthrough targets for table-pair matching.
                if currently_skipping:
                    if in_html5_frame and inc_path.lower().endswith(".html"):
                        pending_table_basenames.add(Path(inc_path).stem)
                    continue

                if looks_like_resource_id(inc_path):
                    continue

                if (
                    self.exclude_tables
                    and in_pdf_frame
                    and inc_path.lower().endswith(".adoc")
                    and Path(inc_path).stem in pending_table_basenames
                ):
                    self.excluded_table_count += 1
                    continue

                resolved = (current_dir / inc_path).resolve()
                if not resolved.exists():
                    self.warnings.append(
                        f"include not found: '{inc_path}' referenced from {abs_path}"
                    )
                    continue
                if resolved.suffix.lower() == ".html":
                    continue
                self.process_file(resolved)
                continue

            if currently_skipping:
                continue

            m = IMAGE_RE.search(raw_line)
            if m:
                if not self.include_images:
                    continue
                img_path = m.group(1).strip()
                if img_path.startswith("http://") or img_path.startswith("https://"):
                    continue
                base_dir = Path(self.imagesdir) if self.imagesdir else current_dir
                resolved = (base_dir / img_path).resolve()
                if resolved.suffix.lower() not in IMAGE_EXTS:
                    continue
                if not resolved.exists():
                    self.warnings.append(
                        f"image not found: '{img_path}' (imagesdir={self.imagesdir!r}) "
                        f"referenced from {abs_path}"
                    )
                    continue
                if resolved in self.visited:
                    continue
                self.visited.add(resolved)
                self.copy_preserving_structure(resolved)
                continue


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--start",
        required=True,
        help="Path to the top-level index.adoc (see --help for accepted forms)",
    )
    ap.add_argument("--target", required=True, help="Directory to copy the collected tree into")
    ap.add_argument(
        "--repo-root",
        default=None,
        help="Repo root, for resolving repo-relative --start paths and ../-style includes. Auto-detected via .git if omitted.",
    )
    ap.add_argument(
        "--images",
        dest="images",
        action="store_true",
        default=False,
        help="Also copy image files referenced via image::/image: macros (default: adoc files only)",
    )
    ap.add_argument(
        "--no-images",
        dest="images",
        action="store_false",
        help="Explicitly skip images (this is already the default; provided for clarity in scripts)",
    )
    ap.add_argument(
        "--no-tables",
        dest="no_tables",
        action="store_true",
        default=False,
        help="Exclude auto-generated register-table includes (detected as an ifdef::backend-html5[] "
        "block whose .html include is paired with a same-named .adoc include in the following "
        "ifdef::backend-pdf[] block). Default: tables included.",
    )
    args = ap.parse_args()

    repo_root = Path(args.repo_root).resolve() if args.repo_root else None

    # Try resolving --start as a real path first, using the given repo_root
    # (if any) for the repo-relative fallback.
    try:
        start_path = resolve_start_path(args.start, repo_root)
    except FileNotFoundError:
        # Maybe --start IS a real path but --repo-root wasn't given yet and
        # is needed for auto-detection; try resolving --start literally
        # first so we have something to walk upward from.
        literal = Path(args.start)
        if literal.exists():
            start_path = literal.resolve()
        else:
            print(f"error: could not resolve --start '{args.start}'", file=sys.stderr)
            return 1

    if repo_root is None:
        repo_root = find_repo_root(start_path)
        if repo_root is None:
            print(
                "error: could not auto-detect repo root (no .git found above "
                f"{start_path}); pass --repo-root explicitly",
                file=sys.stderr,
            )
            return 1
        # Re-resolve --start now that we have a repo root, in case the
        # original --start argument was repo-relative and only resolves
        # correctly against this root (rather than the literal fallback
        # path used just to find the root).
        try:
            start_path = resolve_start_path(args.start, repo_root)
        except FileNotFoundError:
            pass  # keep the literal resolution from above

    target_root = Path(args.target).resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    print(f"repo root:  {repo_root}")
    print(f"start file: {start_path}")
    print(f"target:     {target_root}")
    print(
        f"images:     {'included' if args.images else 'excluded (adoc only) -- pass --images to include'}"
    )
    print(
        f"tables:     {'excluded' if args.no_tables else 'included -- pass --no-tables to exclude'}"
    )
    print()

    collector = Collector(
        repo_root,
        target_root,
        include_images=args.images,
        exclude_tables=args.no_tables,
    )
    collector.process_file(start_path)

    print(f"Copied {len(collector.copied)} file(s):")
    for rel in sorted(collector.copied):
        print(f"  {rel}")

    if collector.excluded_table_count:
        print()
        print(f"Excluded {collector.excluded_table_count} register-table include(s)")

    if collector.warnings:
        print()
        print(f"{len(collector.warnings)} warning(s):")
        for w in collector.warnings:
            print(f"  ! {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
