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

# SVG is not a valid Android drawable-nodpi resource; only raster formats here.
IMAGE_EXTENSIONS = (".png", ".webp")


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
    """Determine the repository root directory, validating it contains app resources."""
    if specified_root:
        root = Path(specified_root).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Specified repo root directory not found: {root}")
    else:
        script_dir = Path(__file__).resolve().parent
        candidates = [
            script_dir.parent,
            Path.cwd().resolve(),
            Path.cwd().resolve().parent,
        ]
        root = None
        for candidate in candidates:
            if (candidate / "app" / "src" / "main" / "res").is_dir():
                root = candidate
                break
        if root is None:
            raise FileNotFoundError(
                "Could not locate the Cuscon repo root. "
                "Ensure you run this from the repo, or use --repo-root."
            )

    # Final validation
    res_dir = root / "app" / "src" / "main" / "res"
    if not res_dir.is_dir():
        raise FileNotFoundError(
            f"Path '{root}' does not look like the Cuscon repo root "
            f"(missing {res_dir}). Use --repo-root to specify the correct path."
        )
    return root


def find_request_dir(request_dir_arg: Optional[str], repo_root: Path) -> Path:
    """Locate the request folder."""
    if request_dir_arg:
        request_dir = Path(request_dir_arg).expanduser().resolve()
        if not request_dir.is_dir():
            raise FileNotFoundError(f"Request directory not found: {request_dir}")
        return request_dir

    # Default: repo_root/requests/icon_request
    default = repo_root / "requests" / "icon_request"
    if default.is_dir():
        return default

    raise FileNotFoundError(
        "Could not locate an icon_request folder. "
        "Use --request-dir to specify the request directory."
    )


def load_text_lines(path: Path) -> Tuple[List[str], str]:
    """Load text lines and detected line ending.

    Returns:
        Tuple of (lines, line_ending). Lines have no trailing newline characters.
    """
    if not path.exists():
        return [], "\n"
    data = path.read_bytes()
    if b"\r\n" in data:
        ending = "\r\n"
    else:
        ending = "\n"
    text = data.decode("utf-8")
    # Split keeping the ending for accurate round-trip
    lines = text.splitlines()
    return lines, ending


def write_text_lines(path: Path, lines: List[str], ending: str) -> None:
    """Write lines to a file using the specified line ending."""
    content = ending.join(lines) + ending
    path.write_bytes(content.encode("utf-8"))


def ensure_safe_name(name: str) -> str:
    """Sanitize a candidate name into a valid drawable identifier."""
    cleaned = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
    if not cleaned:
        raise ValueError("Invalid icon name after sanitization.")
    if not cleaned[0].isalpha():
        raise ValueError(
            f"Invalid icon name '{cleaned}': must start with a letter."
        )
    return cleaned


def append_lines_to_xml(
    target_file: Path,
    new_lines: List[str],
    closing_tag: str,
    insert_after: Optional[str] = None,
) -> None:
    """Append new lines before the closing XML tag, avoiding duplicates.

    Args:
        target_file: Path to the XML file to update.
        new_lines: Lines to append.
        closing_tag: The closing tag to find (e.g. '</resources>').
        insert_after: Optional marker line; insert right after this line instead
            of before closing_tag. Useful for drawable.xml category insertion.
    """
    if not target_file.exists():
        raise FileNotFoundError(
            f"Target XML not found: {target_file}. "
            "Check --repo-root points to the correct Cuscon repo."
        )

    lines, ending = load_text_lines(target_file)
    existing_set = {l.strip() for l in lines if l.strip()}
    filtered = [l for l in new_lines if l.strip() not in existing_set]

    if not filtered:
        return

    insert_idx = len(lines)
    if insert_after:
        for i, l in enumerate(lines):
            if insert_after in l:
                insert_idx = i + 1
                break
        if insert_idx == len(lines):
            # Fallback: insert before closing_tag, skipping trailing blank lines
            for i, l in enumerate(lines):
                if closing_tag in l.strip():
                    insert_idx = i
                    while insert_idx > 0 and not lines[insert_idx - 1].strip():
                        insert_idx -= 1
                    break
    else:
        for i, l in enumerate(lines):
            if closing_tag in l.strip():
                # Insert before the closing tag, but also skip any trailing blank lines
                insert_idx = i
                while insert_idx > 0 and not lines[insert_idx - 1].strip():
                    insert_idx -= 1
                break

    # Normalize indentation to tab to match repo style, but preserve blank lines
    normalized = []
    for l in filtered:
        stripped = l.strip()
        # Keep blank lines as-is, normalize only actual XML elements
        if not stripped:
            normalized.append(l)
        elif stripped.startswith("<item") or stripped.startswith("<AppIcon"):
            # Normalize to tab + content
            normalized.append("\t" + stripped)
        else:
            normalized.append(l)

    output = lines[:insert_idx] + normalized + lines[insert_idx:]
    write_text_lines(target_file, output, ending)


def extract_request_xml_blocks(
    lines: List[str], attr_name: str
) -> Tuple[Dict[str, List[str]], Dict[str, Set[str]]]:
    """Extract XML lines grouped by drawable/name, without comments."""
    lines_map: Dict[str, List[str]] = {}
    components_map: Dict[str, Set[str]] = {}

    drawable_pattern = re.compile(rf'{attr_name}="([^"]+)"')
    comp_pattern = re.compile(r'component="([^"]+)"')
    # Also capture name="pkg/activity" from theme AppIcon entries
    name_pattern = re.compile(r'name="([^"]+)"')

    for line in lines:
        stripped = line.strip()
        # Skip comment lines — they are not copied into the app XMLs
        if stripped.startswith("<!--") and stripped.endswith("-->"):
            continue

        match = drawable_pattern.search(line)
        if match:
            key = match.group(1)
            lines_map.setdefault(key, []).append(line)

            # Extract component= for appfilter, name= for theme
            comp_match = comp_pattern.search(line)
            if comp_match:
                components_map.setdefault(key, set()).add(comp_match.group(1))
            else:
                name_match = name_pattern.search(line)
                if name_match:
                    components_map.setdefault(key, set()).add(name_match.group(1))

    return lines_map, components_map


def scan_request_items(request_dir: Path) -> Dict[str, RequestItem]:
    """Scan the request directory for icon files and associated metadata."""
    request_files: Dict[str, List[Path]] = {}
    for child in sorted(request_dir.iterdir()):
        if child.is_file() and child.suffix.lower() in IMAGE_EXTENSIONS:
            try:
                name = ensure_safe_name(child.stem)
                request_files.setdefault(name, []).append(child)
            except ValueError as exc:
                print(f"Warning: Skipping {child.name}: {exc}")
                continue

    appfilter_lines, _ = load_text_lines(request_dir / "appfilter.xml")
    theme_lines, _ = load_text_lines(request_dir / "theme_resources.xml")

    appfilter_map, components_map = extract_request_xml_blocks(appfilter_lines, "drawable")
    theme_map, theme_components = extract_request_xml_blocks(theme_lines, "image")

    # Merge theme components into the main components map
    for name, comps in theme_components.items():
        components_map.setdefault(name, set()).update(comps)

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


def load_existing_app_data(
    repo_root: Path,
) -> Tuple[Set[str], Set[str]]:
    """Extract existing drawable names and component signatures from the app."""
    drawable_dir = repo_root / "app" / "src" / "main" / "res" / "drawable-nodpi"
    existing_drawables: Set[str] = set()
    if drawable_dir.is_dir():
        for item in drawable_dir.iterdir():
            if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS:
                existing_drawables.add(item.stem)

    existing_components: Set[str] = set()
    appfilter_path = repo_root / "app" / "src" / "main" / "res" / "xml" / "appfilter.xml"
    if appfilter_path.exists():
        lines, _ = load_text_lines(appfilter_path)
        comp_pattern = re.compile(r'component="([^"]+)"')
        for line in lines:
            m = comp_pattern.search(line)
            if m:
                existing_components.add(m.group(1))

    # Also extract components from theme_resources.xml AppIcon name= attributes
    theme_path = repo_root / "app" / "src" / "main" / "res" / "xml" / "theme_resources.xml"
    if theme_path.exists():
        lines, _ = load_text_lines(theme_path)
        name_pattern = re.compile(r'name="([^"]+)"')
        for line in lines:
            # Only extract name= from AppIcon elements, not from other elements like Label, ThemePreview, etc.
            if "<AppIcon" in line:
                m = name_pattern.search(line)
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

        if is_already_added:
            summary[RequestStatus.ALREADY_ADDED].append(item)
        elif not item.has_metadata():
            # No XML metadata — either missing metadata or just a stray image
            summary[RequestStatus.MISSING_METADATA].append(item)
        elif item.name in existing_drawables:
            # Has metadata but drawable already exists → conflict
            summary[RequestStatus.CONFLICT].append(item)
        else:
            summary[RequestStatus.NEW].append(item)

    return summary


def print_status(summary: Dict[RequestStatus, List[RequestItem]]) -> None:
    """Display summary of request items."""
    descriptions = {
        RequestStatus.NEW: "Brand-new icons ready to be added to Cuscon (image file + XML metadata).",
        RequestStatus.ALREADY_ADDED: "App components that are ALREADY registered in Cuscon (nothing to do).",
        RequestStatus.CONFLICT: "Icons that ALREADY exist in Cuscon, but a new activity/package was requested.",
        RequestStatus.MISSING_METADATA: "Image files with no XML configuration lines.",
    }

    def print_section(status: RequestStatus, title: str) -> None:
        group = summary[status]
        print(f"\n{'=' * 70}")
        print(f" {title.upper()} ({len(group)} items)")
        print(f" Description: {descriptions[status]}")
        print(f"{'=' * 70}")
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
    existing_drawables: Set[str],
    dry_run: bool,
) -> None:
    """Interactively resolve filename conflicts."""
    if not conflicts:
        print("\nNo conflicts found.")
        return

    appfilter_path = request_dir / "appfilter.xml"
    theme_path = request_dir / "theme_resources.xml"

    appfilter_lines, appfilter_ending = load_text_lines(appfilter_path)
    theme_lines, theme_ending = load_text_lines(theme_path)

    target_appfilter = repo_root / "app" / "src" / "main" / "res" / "xml" / "appfilter.xml"
    target_theme = repo_root / "app" / "src" / "main" / "res" / "xml" / "theme_resources.xml"

    if not target_appfilter.exists():
        raise FileNotFoundError(f"Target appfilter.xml not found: {target_appfilter}")
    if not target_theme.exists():
        raise FileNotFoundError(f"Target theme_resources.xml not found: {target_theme}")

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
        while action not in ("l", "d", "r", "s"):
            try:
                action = input("\nChoose action ([l]ink / [d]elete / [r]ename / [s]kip): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting resolution.")
                return

        if action == "s":
            print("Skipped.")
            continue

        if action == "l":
            print(f"Linking component(s) to existing '{item.name}' icon...")
            if not dry_run:
                if item.appfilter_lines:
                    append_lines_to_xml(target_appfilter, item.appfilter_lines, "</resources>")
                if item.theme_lines:
                    append_lines_to_xml(target_theme, item.theme_lines, "</Theme>")

                # Delete request image files
                for f in [item.file_path] + item.duplicate_files:
                    if f.exists():
                        f.unlink()
                        print(f"  Deleted: {f.name}")

            # Remove matching lines from request XMLs
            appfilter_lines = [
                l for l in appfilter_lines
                if f'drawable="{item.name}"' not in l
            ]
            theme_lines = [
                l for l in theme_lines
                if f'image="{item.name}"' not in l
            ]
            modified = True
            if dry_run:
                print(f"  [dry-run] Would link '{item.name}' and remove request image.")
            else:
                print(f"Linked '{item.name}' component to existing icon and removed request image.")
            continue

        if action == "d":
            if not dry_run:
                for f in [item.file_path] + item.duplicate_files:
                    if f.exists():
                        print(f"  Deleting: {f.name}")
                        f.unlink()
            else:
                for f in [item.file_path] + item.duplicate_files:
                    print(f"  [dry-run] Would delete: {f.name}")

            appfilter_lines = [
                l for l in appfilter_lines
                if f'drawable="{item.name}"' not in l
            ]
            theme_lines = [
                l for l in theme_lines
                if f'image="{item.name}"' not in l
            ]
            modified = True
            continue

        if action == "r":
            new_name = ""
            while not new_name:
                try:
                    candidate = input("New drawable name: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting resolution.")
                    return
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
                # Check no intra-request collision
                if any(candidate == other.name for other in conflicts if other is not item):
                    print(f"Name '{candidate}' collides with another conflict item. Pick another.")
                    continue
                new_name = candidate

            ext = item.file_path.suffix
            new_file_path = item.file_path.with_name(new_name + ext)

            if dry_run:
                print(f"  [dry-run] Would rename {item.file_path.name} -> {new_file_path.name}")
            else:
                if item.file_path.exists():
                    if new_file_path.exists():
                        print(f"  Warning: {new_file_path.name} already exists, skipping rename.")
                    else:
                        item.file_path.rename(new_file_path)
                        print(f"  Renamed {item.file_path.name} -> {new_file_path.name}")
                # Also rename duplicate files
                new_duplicates = []
                for dup in item.duplicate_files:
                    new_dup = dup.with_name(new_name + dup.suffix)
                    if dup.exists():
                        if new_dup.exists():
                            print(f"  Warning: {new_dup.name} already exists, skipping duplicate rename.")
                        else:
                            dup.rename(new_dup)
                            new_duplicates.append(new_dup)
                item.duplicate_files = new_duplicates

            # Rewrite XML references
            appfilter_lines = [
                l.replace(f'drawable="{item.name}"', f'drawable="{new_name}"')
                for l in appfilter_lines
            ]
            theme_lines = [
                l.replace(f'image="{item.name}"', f'image="{new_name}"')
                for l in theme_lines
            ]
            modified = True

    if modified:
        if dry_run:
            print("\n[dry-run] Request XML files would be updated.")
        else:
            if appfilter_path.exists():
                write_text_lines(appfilter_path, appfilter_lines, appfilter_ending)
            if theme_path.exists():
                write_text_lines(theme_path, theme_lines, theme_ending)
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

    # Validate all target files exist before making any changes
    for name, path in [("appfilter.xml", target_appfilter), ("drawable.xml", target_drawable_xml), ("theme_resources.xml", target_theme)]:
        if not path.exists():
            raise FileNotFoundError(
                f"Target XML not found: {path}. "
                "Check --repo-root points to the correct Cuscon repo."
            )

    file_copies: List[Tuple[Path, Path]] = []
    appfilter_additions: List[str] = []
    drawable_additions: List[str] = []
    theme_additions: List[str] = []

    for item in new_items:
        if not item.file_path.exists():
            print(f"Warning: Skipping {item.name}, file not found: {item.file_path}")
            continue

        dest_file = target_drawable_dir / item.file_path.name
        file_copies.append((item.file_path, dest_file))

        appfilter_additions.extend(item.appfilter_lines)
        drawable_additions.append(f'\t<item drawable="{item.name}" />')
        theme_additions.extend(item.theme_lines)

    if dry_run:
        print("Dry-run mode: Planned actions:")
        print(f"  Drawables to copy ({len(file_copies)}):")
        for src, dst in file_copies:
            print(f"    {src.name} -> {dst}")
        print(f"  Appfilter lines to append: {len(appfilter_additions)}")
        print(f"  Drawable.xml lines to append: {len(drawable_additions)}")
        print(f"  Theme_resources.xml lines to append: {len(theme_additions)}")
        return

    # Perform all copies first
    target_drawable_dir.mkdir(parents=True, exist_ok=True)
    copied_count = 0
    for src, dst in file_copies:
        if not dst.exists():
            shutil.copy2(src, dst)
            copied_count += 1
    print(f"Copied {copied_count} icon files into {target_drawable_dir}.")

    # Append to XMLs using the consolidated helper
    if appfilter_additions:
        append_lines_to_xml(target_appfilter, appfilter_additions, "</resources>")
        print(f"Appended {len(appfilter_additions)} lines to appfilter.xml.")

    if drawable_additions:
        append_lines_to_xml(
            target_drawable_xml,
            drawable_additions,
            "</resources>",
            insert_after='<category title="New Icons"',
        )
        print(f"Appended {len(drawable_additions)} lines to drawable.xml.")

    if theme_additions:
        append_lines_to_xml(target_theme, theme_additions, "</Theme>")
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
        interactive_resolve(
            summary[RequestStatus.CONFLICT],
            repo_root,
            request_dir,
            existing_drawables,
            args.dry_run,
        )
    elif args.command == "apply":
        apply_requests(summary[RequestStatus.NEW], repo_root, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
