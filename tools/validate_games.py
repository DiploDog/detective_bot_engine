#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from detective_bot.engine.validation import ValidationIssue
from detective_bot.infrastructure.game_catalog import (
    FileSystemGameCatalog,
    PackageLoadError,
    SemVer,
    load_game_package,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Detective Bot game packages."
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Catalog root or a single games/<game_id>/<version> package",
    )
    arguments = parser.parse_args()
    target = arguments.path.resolve()

    if (target / "manifest.yaml").is_file() or _looks_like_version_directory(
        target
    ):
        return _validate_one(target)
    return _validate_catalog(target)


def _validate_one(package_root: Path) -> int:
    print(f"PACKAGE {package_root}")
    try:
        loaded = load_game_package(package_root)
    except PackageLoadError as error:
        _print_issues(error.issues)
        return 1
    _print_issues(loaded.issues)
    print("OK")
    return 0


def _validate_catalog(catalog_root: Path) -> int:
    scan = FileSystemGameCatalog(catalog_root).scan()
    for loaded in scan.packages:
        manifest = loaded.package.manifest
        print(
            f"PACKAGE {manifest.game_id}/{manifest.version} "
            f"({loaded.package_root})"
        )
        _print_issues(loaded.issues)
        print("OK")
    for failure in scan.failures:
        print(f"PACKAGE {failure.package_root}")
        _print_issues(failure.issues)
    if not scan.packages and not scan.failures:
        print(f"No game packages found under {catalog_root}")
    return 1 if scan.failures else 0


def _print_issues(issues: tuple[ValidationIssue, ...]) -> None:
    for issue in issues:
        print(
            f"{issue.severity.value} {issue.code} "
            f"{issue.path}: {issue.message}"
        )


def _looks_like_version_directory(path: Path) -> bool:
    try:
        SemVer.parse(path.name)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
