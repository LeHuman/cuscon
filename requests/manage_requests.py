#!/usr/bin/env python3
"""Manage Cuscon icon request folders and apply them to the app.

This script scans icon request directories, classifies requested icons,
resolves filename conflicts interactively, and applies approved icons
and XML metadata into the app resources.
"""

import argparse
import re
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

IMAGE_EXTENSIONS = (".png", ".webp", ".svg")


class RequestStatus(Enum):
    """Status values for request icon classification."""

    NEW = "new"
    ALREADY_ADDED = "already_added"
    CONFLICT = "conflict"
    MISSING_METADATA = "missing_metadata"


@dataclass
class RequestItem:
    """Represents one requested icon file and its metadata."""

    name: str
    file_path: Path
    appfilter_lines: List[str] = field(default_factory=list)
    theme_lines: List[str] = field(default_factory=list)
    components: Set[str] = field(default_factory=set)
    request_dir: Optional[Path] = None
    duplicate_files: List[Path] = field(default_factory=list)

    def has_metadata(self) -> bool:
        """Return True when the request contains appfilter or theme metadata."""
        return bool(self.appfilter_lines or self.theme_lines)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Manage Cuscon icon requests.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("status", "resolve", "apply"),
        default="status",
        help="Operation to run (status, resolve, apply). Defaults to status.",
    )
    parser.add_argument(
        "--request-dir",
        help="Path to the icon_request folder to process.",
    )
    parser.add_argument(
        "--repo-root",
        help="Path to the repository root directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing to disk.",
    )
    return parser.parse_args()


def find_repo_root(specified_root: Optional[str]) -> Path:
    """Determine the repository root directory."""
    if specified_root:
        root = Path(specified_root).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Specified repo root directory not found: {root}")
        return root

    script_dir = Path(__file__).resolve().parent
    if (script_dir.parent / "app").is_dir():
        return script_dir.parent

    cwd = Path.cwd().resolve()
    if (cwd / "app").is_dir():
        return cwd
    if (cwd.parent / "app").is_dir():
        return cwd.parent

    return script_dir.parent


def find_request_dir(request_dir_arg: Optional[str], repo_root: Path) -> Path:
    """Locate the request folder using fallback search order."""
    if request_dir_arg:
        request_dir = Path(request_dir_arg).expanduser().resolve()
        if not request_dir.is_dir():
            raise FileNotFoundError(f"Request directory not found: {request_dir}")
        return request_dir

    candidates = [
        repo_root / "requests" / "icon_request",
        repo_root / "requests" / "icon_request_",
        repo_root / "icon_request",
        repo_root / "icon_request_",
    ]

    cwd = Path.cwd().resolve()
    if cwd.name in ("icon_request", "icon_request_") and cwd.is_dir():
        return cwd

    candidates.extend([cwd / "icon_request", cwd / "icon_request_"])

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    raise FileNotFoundError(
        "Could not locate an icon_request folder. Use --request-dir to specify the request directory."
    )


def load_text_lines(path: Path) -> List[str]:
    """Load text lines from a file, returning empty list if missing."""
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1").splitlines()


def ensure_safe_name(name: str) -> str:
    """Sanitize a candidate name into a valid drawable identifier."""
    cleaned = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if not cleaned:
        raise ValueError("Invalid icon name after sanitization.")
    return cleaned


def append_unique_lines_to_xml(target_file: Path, new_lines: List[str], closing_tag: str) -> None:
    """Append new lines right before the closing XML tag, avoiding duplicates."""
    lines = load_text_lines(target_file)
    existing_set = {l.strip() for l in lines if l.strip()}
    filtered_additions = [l for l in new_lines if l.strip() not in existing_set]

    if not filtered_additions:
        return

    insert_idx = len(lines)
    for i, l in enumerate(lines):
        if l.strip() == closing_tag:
            insert_idx = i
            break

    output_lines = lines[:insert_idx] + filtered_additions + lines[insert_idx:]
    target_file.write_text("\n".join(output_lines) + "\n", encoding="utf-8")



def extract_request_xml_blocks(lines: List[str], attr_name: str) -> Tuple[Dict[str, List[str]], Dict[str, Set[str]]]:
    """Extract XML lines (with preceding comments) grouped by drawable stem name."""
    lines_map: Dict[str, List[str]] = {}
    components_map: Dict[str, Set[str]] = {}
    pending_comments: List[str] = []

    pattern = re.compile(rf'{attr_name}="([^"]+)"')
    comp_pattern = re.compile(r'component="([^"]+)"')

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            pending_comments.append(line)
            continue

        match = pattern.search(line)
        if match:
            drawable = match.group(1)
            block = pending_comments + [line]
            lines_map.setdefault(drawable, []).extend(block)
            pending_comments = []

            comp_match = comp_pattern.search(line)
            if comp_match:
                components_map.setdefault(drawable, set()).add(comp_match.group(1))
            continue

        if stripped and not (stripped.startswith("<resources") or stripped.startswith("</resources") or stripped.startswith("<Theme") or stripped.startswith("</Theme")):
            pending_comments = []

    return lines_map, components_map


def scan_request_items(request_dir: Path) -> Dict[str, RequestItem]:
    """Scan the request directory for icon files and associated metadata."""
    request_files: Dict[str, List[Path]] = {}
    for child in sorted(request_dir.iterdir()):
        if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS:
            request_files.setdefault(child.stem, []).append(child)

    appfilter_lines = load_text_lines(request_dir / "appfilter.xml")
    theme_lines = load_text_lines(request_dir / "theme_resources.xml")

    appfilter_map, components_map = extract_request_xml_blocks(appfilter_lines, "drawable")
    theme_map, _ = extract_request_xml_blocks(theme_lines, "image")

    all_drawables = set(request_files.keys()) | set(appfilter_map.keys()) | set(theme_map.keys())

    items: Dict[str, RequestItem] = {}
    for name in sorted(all_drawables):
        files = request_files.get(name, [])
        primary_file = files[0] if files else (request_dir / f"{name}.png")
        duplicates = files[1:] if len(files) > 1 else []

        item = RequestItem(
            name=name,
            file_path=primary_file,
            appfilter_lines=appfilter_map.get(name, []),
            theme_lines=theme_map.get(name, []),
            components=components_map.get(name, set()),
            request_dir=request_dir,
            duplicate_files=duplicates,
        )
        items[name] = item

    return items


def load_existing_app_data(repo_root: Path) -> Tuple[Set[str], Set[str]]:
    """Extract existing drawable names and component signatures from the app."""
    drawable_dir = repo_root / "app" / "src" / "main" / "res" / "drawable-nodpi"
    existing_drawables: Set[str] = set()
    if drawable_dir.is_dir():
        for item in drawable_dir.iterdir():
            if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
                existing_drawables.add(item.stem)

    appfilter_path = repo_root / "app" / "src" / "main" / "res" / "xml" / "appfilter.xml"
    existing_components: Set[str] = set()
    if appfilter_path.exists():
        lines = load_text_lines(appfilter_path)
        comp_pattern = re.compile(r'component="([^"]+)"')
        for line in lines:
            m = comp_pattern.search(line)
            if m:
                existing_components.add(m.group(1))

    return existing_drawables, existing_components


def classify_items(
    items: Dict[str, RequestItem],
    existing_drawables: Set[str],
    existing_components: Set[str],
) -> Dict[RequestStatus, List[RequestItem]]:
    """Classify request items into NEW, ALREADY_ADDED, CONFLICT, or MISSING_METADATA."""
    summary: Dict[RequestStatus, List[RequestItem]] = {
        RequestStatus.NEW: [],
        RequestStatus.ALREADY_ADDED: [],
        RequestStatus.CONFLICT: [],
        RequestStatus.MISSING_METADATA: [],
    }

    for item in items.values():
        is_already_added = bool(item.components and item.components.issubset(existing_components))
        is_conflict = item.name in existing_drawables and not is_already_added

        if is_already_added:
            summary[RequestStatus.ALREADY_ADDED].append(item)
        elif is_conflict:
            summary[RequestStatus.CONFLICT].append(item)
        elif not item.has_metadata():
            summary[RequestStatus.MISSING_METADATA].append(item)
        else:
            summary[RequestStatus.NEW].append(item)

    return summary


def print_status(summary: Dict[RequestStatus, List[RequestItem]]) -> None:
    """Display summary of request items with clear, beginner-friendly descriptions."""
    descriptions = {
        RequestStatus.NEW: "Brand-new icons ready to be added to Cuscon (image file + XML metadata).",
        RequestStatus.ALREADY_ADDED: "App components that are ALREADY registered in Cuscon (nothing to do).",
        RequestStatus.CONFLICT: "Icons that ALREADY exist in Cuscon, but a user requested a new activity/package for them.",
        RequestStatus.MISSING_METADATA: "Image files in the request folder that have no XML configuration lines.",
    }

    def print_section(status: RequestStatus, title: str) -> None:
        group = summary[status]
        print(f"\n{'='*70}")
        print(f" {title.upper()} ({len(group)} items)")
        print(f" Description: {descriptions[status]}")
        print(f"{'='*70}")
        if not group:
            print("  (none)")
            return
        for item in group:
            dups = [f.name for f in item.duplicate_files]
            suffix = f"  [duplicate files: {', '.join(dups)}]" if dups else ""
            file_str = f" ({item.file_path.name})" if item.file_path.exists() else " (no image file)"
            print(f"  - {item.name}{file_str}{suffix}")

    print_section(RequestStatus.NEW, "New icons")
    print_section(RequestStatus.ALREADY_ADDED, "Already added")
    print_section(RequestStatus.CONFLICT, "Conflicts")
    print_section(RequestStatus.MISSING_METADATA, "Missing metadata")


def interactive_resolve(
    conflicts: List[RequestItem],
    repo_root: Path,
    request_dir: Path,
    dry_run: bool,
) -> None:
    """Interactively resolve filename conflicts with clear prompts."""
    if not conflicts:
        print("\nNo conflicts found.")
        return

    appfilter_path = request_dir / "appfilter.xml"
    theme_path = request_dir / "theme_resources.xml"

    appfilter_lines = load_text_lines(appfilter_path)
    theme_lines = load_text_lines(theme_path)

    target_appfilter = repo_root / "app" / "src" / "main" / "res" / "xml" / "appfilter.xml"
    target_theme = repo_root / "app" / "src" / "main" / "res" / "xml" / "theme_resources.xml"

    existing_drawables, _ = load_existing_app_data(repo_root)
    modified = False

    print("\n" + "=" * 70)
    print(" CONFLICT RESOLUTION HELPER")
    print(" Cuscon uses 1 icon per app. A conflict happens when an icon with this")
    print(" name already exists in the app, but a new app component was requested.")
    print("=" * 70)

    for item in conflicts:
        print(f"\nConflict Item: '{item.name}'")
        print(f"  Request Image File : {item.file_path.name}")
        print(f"  Request Components : {', '.join(item.components) if item.components else '(none)'}")
        print(f"  Appfilter Lines    : {len(item.appfilter_lines)}")
        print(f"  Theme Lines        : {len(item.theme_lines)}")

        print("\nOptions:")
        print("  [l]ink   : Use existing icon in Cuscon. Link the new app component to the existing icon")
        print("             and delete the redundant request image file.")
        print("  [d]elete : Ignore/discard this request item completely (deletes request image & metadata).")
        print("  [r]ename : Rename this drawable (only if this is a completely different app).")
        print("  [s]kip   : Leave untouched and skip to next item.")

        action = ""
        while action not in ("l", "d", "r", "s", "k"):
            try:
                action = input("\nChoose action ([l]ink / [d]elete / [r]ename / [s]kip): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting resolution.")
                return

        if action in ("s", "k"):
            print("Skipped.")
            continue

        if action == "l":
            print(f"Linking component(s) to existing '{item.name}' icon...")
            if not dry_run:
                # Append appfilter and theme lines to main app XMLs
                if item.appfilter_lines and target_appfilter.exists():
                    append_unique_lines_to_xml(target_appfilter, item.appfilter_lines, "</resources>")
                if item.theme_lines and target_theme.exists():
                    append_unique_lines_to_xml(target_theme, item.theme_lines, "</Theme>")

                # Delete duplicate request image files
                files_to_delete = [item.file_path] + item.duplicate_files
                for f in files_to_delete:
                    if f.exists():
                        f.unlink()

            pattern_app = re.compile(rf'drawable="{re.escape(item.name)}"')
            pattern_theme = re.compile(rf'image="{re.escape(item.name)}"')
            appfilter_lines = [line for line in appfilter_lines if not pattern_app.search(line)]
            theme_lines = [line for line in theme_lines if not pattern_theme.search(line)]
            modified = True
            print(f"Linked '{item.name}' component to existing icon and removed request image.")
            continue

        if action == "d":
            files_to_delete = [item.file_path] + item.duplicate_files
            for f in files_to_delete:
                if f.exists():
                    if dry_run:
                        print(f"Would delete: {f}")
                    else:
                        print(f"Deleting: {f}")
                        f.unlink()

            pattern_app = re.compile(rf'drawable="{re.escape(item.name)}"')
            pattern_theme = re.compile(rf'image="{re.escape(item.name)}"')
            appfilter_lines = [line for line in appfilter_lines if not pattern_app.search(line)]
            theme_lines = [line for line in theme_lines if not pattern_theme.search(line)]
            modified = True
            continue

        if action == "r":
            new_name = ""
            while not new_name:
                candidate = input("New drawable name: ").strip()
                try:
                    candidate = ensure_safe_name(candidate)
                except ValueError as exc:
                    print(f"Invalid name: {exc}")
                    continue

                if candidate == item.name:
                    print("New name must differ from original name.")
                    continue
                if candidate in existing_drawables:
                    print(f"Name '{candidate}' already exists in app drawables. Pick another.")
                    continue
                new_name = candidate

            ext = item.file_path.suffix
            new_file_path = item.file_path.with_name(new_name + ext)

            if dry_run:
                print(f"Would rename {item.file_path.name} -> {new_file_path.name}")
            else:
                print(f"Renaming {item.file_path.name} -> {new_file_path.name}")
                if item.file_path.exists():
                    item.file_path.rename(new_file_path)

            app_sub = re.compile(rf'(drawable="){re.escape(item.name)}(")')
            theme_sub = re.compile(rf'(image="){re.escape(item.name)}(")')

            appfilter_lines = [app_sub.sub(rf'\1{new_name}\2', l) for l in appfilter_lines]
            theme_lines = [theme_sub.sub(rf'\1{new_name}\2', l) for l in theme_lines]
            modified = True

    if modified:
        if dry_run:
            print("\nDry-run: Request XML files would be updated.")
        else:
            if appfilter_path.exists():
                appfilter_path.write_text("\n".join(appfilter_lines) + "\n", encoding="utf-8")
            if theme_path.exists():
                theme_path.write_text("\n".join(theme_lines) + "\n", encoding="utf-8")
            print("\nUpdated request metadata XML files.")


def apply_requests(new_items: List[RequestItem], repo_root: Path, dry_run: bool) -> None:
    """Apply new request icons and XML entries to the repository."""
    if not new_items:
        print("No new icons to apply.")
        return

    target_appfilter = repo_root / "app" / "src" / "main" / "res" / "xml" / "appfilter.xml"
    target_drawable_xml = repo_root / "app" / "src" / "main" / "res" / "xml" / "drawable.xml"
    target_theme = repo_root / "app" / "src" / "main" / "res" / "xml" / "theme_resources.xml"
    target_drawable_dir = repo_root / "app" / "src" / "main" / "res" / "drawable-nodpi"

    existing_appfilter_lines = load_text_lines(target_appfilter)
    existing_drawable_lines = load_text_lines(target_drawable_xml)
    existing_theme_lines = load_text_lines(target_theme)

    existing_appfilter_set = {l.strip() for l in existing_appfilter_lines if l.strip()}
    existing_drawable_set = {l.strip() for l in existing_drawable_lines if l.strip()}
    existing_theme_set = {l.strip() for l in existing_theme_lines if l.strip()}

    appfilter_additions: List[str] = []
    drawable_additions: List[str] = []
    theme_additions: List[str] = []
    file_copies: List[Tuple[Path, Path]] = []

    for item in new_items:
        if not item.file_path.exists():
            print(f"Warning: Skipping {item.name}, file not found: {item.file_path}")
            continue

        dest_file = target_drawable_dir / item.file_path.name
        file_copies.append((item.file_path, dest_file))

        for line in item.appfilter_lines:
            if line.strip() not in existing_appfilter_set:
                appfilter_additions.append(line)
                existing_appfilter_set.add(line.strip())

        item_drawable_tag = f'    <item drawable="{item.name}" />'
        if item_drawable_tag.strip() not in existing_drawable_set:
            drawable_additions.append(item_drawable_tag)
            existing_drawable_set.add(item_drawable_tag.strip())

        for line in item.theme_lines:
            if line.strip() not in existing_theme_set:
                theme_additions.append(line)
                existing_theme_set.add(line.strip())

    if dry_run:
        print("Dry-run mode: Planned actions:")
        print(f"  Drawables to copy ({len(file_copies)}):")
        for src, dst in file_copies:
            print(f"    {src.name} -> {dst}")
        print(f"  Appfilter lines to append: {len(appfilter_additions)}")
        print(f"  Drawable.xml lines to append: {len(drawable_additions)}")
        print(f"  Theme_resources.xml lines to append: {len(theme_additions)}")
        return

    target_drawable_dir.mkdir(parents=True, exist_ok=True)
    copied_count = 0
    for src, dst in file_copies:
        if not dst.exists():
            shutil.copy2(src, dst)
            copied_count += 1
    print(f"Copied {copied_count} icon files into {target_drawable_dir}.")

    # Append to appfilter.xml
    if appfilter_additions and target_appfilter.exists():
        lines = load_text_lines(target_appfilter)
        insert_idx = len(lines)
        for i, l in enumerate(lines):
            if l.strip() == "</resources>":
                insert_idx = i
                break
        new_lines = lines[:insert_idx] + [""] + appfilter_additions + lines[insert_idx:]
        target_appfilter.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"Appended {len(appfilter_additions)} lines to appfilter.xml.")

    # Append to drawable.xml under <category title="New Icons" /> or before </resources>
    if drawable_additions and target_drawable_xml.exists():
        lines = load_text_lines(target_drawable_xml)
        insert_idx = -1
        for i, l in enumerate(lines):
            if '<category title="New Icons"' in l:
                insert_idx = i + 1
                break
        if insert_idx == -1:
            for i, l in enumerate(lines):
                if l.strip() == "</resources>":
                    insert_idx = i
                    break
        if insert_idx == -1:
            insert_idx = len(lines)

        new_lines = lines[:insert_idx] + drawable_additions + lines[insert_idx:]
        target_drawable_xml.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"Appended {len(drawable_additions)} lines to drawable.xml.")

    # Append to theme_resources.xml
    if theme_additions and target_theme.exists():
        lines = load_text_lines(target_theme)
        insert_idx = len(lines)
        for i, l in enumerate(lines):
            if l.strip() == "</Theme>":
                insert_idx = i
                break
        new_lines = lines[:insert_idx] + [""] + theme_additions + lines[insert_idx:]
        target_theme.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"Appended {len(theme_additions)} lines to theme_resources.xml.")


def main() -> int:
    """Run the request manager CLI."""
    args = parse_args()

    try:
        repo_root = find_repo_root(args.repo_root)
        request_dir = find_request_dir(args.request_dir, repo_root)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(f"Using request folder: {request_dir}")

    request_items = scan_request_items(request_dir)
    if not request_items:
        print("No request icons or metadata found in the specified request directory.")
        return 0

    existing_drawables, existing_components = load_existing_app_data(repo_root)
    summary = classify_items(request_items, existing_drawables, existing_components)

    if args.command == "status":
        print_status(summary)
    elif args.command == "resolve":
        interactive_resolve(summary[RequestStatus.CONFLICT], repo_root, request_dir, args.dry_run)
    elif args.command == "apply":
        apply_requests(summary[RequestStatus.NEW], repo_root, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
