from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml
from pydantic import ValidationError

from detective_bot.engine.model import GameDefinition, GameManifest, GamePackage
from detective_bot.engine.validation import (
    IssueSeverity,
    ValidationIssue,
    has_errors,
    validate_package,
)


class DuplicateYamlKeyError(ValueError):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from error
        if duplicate:
            raise DuplicateYamlKeyError(
                f"duplicate YAML key {key!r} at "
                f"line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class LoadedGamePackage:
    package: GamePackage
    package_root: Path
    asset_paths: Mapping[str, Path]
    asset_variant_paths: Mapping[str, Mapping[str, Path]]
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class PackageFailure:
    package_root: Path
    issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class CatalogScan:
    packages: tuple[LoadedGamePackage, ...]
    failures: tuple[PackageFailure, ...]


class PackageLoadError(ValueError):
    def __init__(
        self,
        package_root: Path,
        issues: tuple[ValidationIssue, ...],
    ) -> None:
        self.package_root = package_root
        self.issues = issues
        super().__init__(
            f"invalid game package {package_root}: "
            f"{sum(issue.severity is IssueSeverity.ERROR for issue in issues)} errors"
        )


def load_game_package(package_root: str | Path) -> LoadedGamePackage:
    root = Path(package_root).resolve()
    issues: list[ValidationIssue] = []

    manifest_data = _load_yaml(root / "manifest.yaml", "manifest", issues)
    if manifest_data is None:
        raise PackageLoadError(root, tuple(issues))

    manifest = _validate_model(
        GameManifest,
        manifest_data,
        "manifest",
        issues,
    )
    if manifest is None:
        raise PackageLoadError(root, tuple(issues))

    _validate_semver(manifest.version, "manifest.version", issues)
    if root.parent.name != manifest.game_id:
        _error(
            issues,
            "game_id_path_mismatch",
            "manifest.game_id",
            f"manifest game_id {manifest.game_id!r} does not match directory "
            f"{root.parent.name!r}",
        )
    if root.name != manifest.version:
        _error(
            issues,
            "version_path_mismatch",
            "manifest.version",
            f"manifest version {manifest.version!r} does not match directory "
            f"{root.name!r}",
        )

    game_path = _resolve_package_path(
        root,
        manifest.game_file,
        "manifest.game_file",
        issues,
    )
    game_data = (
        _load_yaml(game_path, "definition", issues)
        if game_path is not None
        else None
    )
    definition = (
        _validate_model(
            GameDefinition,
            game_data,
            "definition",
            issues,
        )
        if game_data is not None
        else None
    )
    if definition is None:
        raise PackageLoadError(root, tuple(issues))

    package = GamePackage(manifest=manifest, definition=definition)
    issues.extend(validate_package(package))

    asset_paths: dict[str, Path] = {}
    asset_variant_paths: dict[str, Mapping[str, Path]] = {}
    for asset_id, asset in manifest.assets.items():
        asset_path = _resolve_package_path(
            root,
            asset.path,
            f"manifest.assets.{asset_id}.path",
            issues,
        )
        if asset_path is None:
            continue
        if not asset_path.is_file():
            _error(
                issues,
                "missing_asset",
                f"manifest.assets.{asset_id}.path",
                f"asset file does not exist: {asset.path}",
            )
            continue
        asset_paths[asset_id] = asset_path
        variants: dict[str, Path] = {}
        for platform, variant in asset.variants.items():
            variant_path = _resolve_package_path(
                root,
                variant,
                f"manifest.assets.{asset_id}.variants.{platform}",
                issues,
            )
            if variant_path is None:
                continue
            if not variant_path.is_file():
                _error(
                    issues,
                    "missing_asset",
                    f"manifest.assets.{asset_id}.variants.{platform}",
                    f"asset file does not exist: {variant}",
                )
                continue
            variants[platform] = variant_path
        asset_variant_paths[asset_id] = MappingProxyType(variants)

    collected = tuple(issues)
    if has_errors(collected):
        raise PackageLoadError(root, collected)
    return LoadedGamePackage(
        package=package,
        package_root=root,
        asset_paths=MappingProxyType(asset_paths),
        asset_variant_paths=MappingProxyType(asset_variant_paths),
        issues=collected,
    )


class FileSystemGameCatalog:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._scan_cache: CatalogScan | None = None

    def scan(self) -> CatalogScan:
        if self._scan_cache is not None:
            return self._scan_cache
        packages: list[LoadedGamePackage] = []
        failures: list[PackageFailure] = []
        if not self.root.is_dir():
            issue = ValidationIssue(
                severity=IssueSeverity.ERROR,
                code="catalog_root_missing",
                path=str(self.root),
                message="catalog root does not exist",
            )
            self._scan_cache = CatalogScan(
                packages=(),
                failures=(PackageFailure(self.root, (issue,)),),
            )
            return self._scan_cache

        for game_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
            for version_dir in sorted(
                (path for path in game_dir.iterdir() if path.is_dir()),
                key=lambda path: path.name,
            ):
                resolved_version = version_dir.resolve()
                if not resolved_version.is_relative_to(self.root):
                    issue = ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        code="path_traversal",
                        path=str(version_dir),
                        message="catalog package must remain inside catalog root",
                    )
                    failures.append(PackageFailure(version_dir, (issue,)))
                    continue
                try:
                    packages.append(load_game_package(resolved_version))
                except PackageLoadError as error:
                    failures.append(
                        PackageFailure(error.package_root, error.issues)
                    )
        self._scan_cache = CatalogScan(tuple(packages), tuple(failures))
        return self._scan_cache

    def list_games(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    loaded.package.manifest.game_id
                    for loaded in self.scan().packages
                }
            )
        )

    def list_versions(self, game_id: str) -> tuple[str, ...]:
        versions = [
            loaded.package.manifest.version
            for loaded in self.scan().packages
            if loaded.package.manifest.game_id == game_id
        ]
        return tuple(sorted(versions, key=SemVer.parse))

    def get(self, game_id: str, version: str) -> LoadedGamePackage:
        if re.fullmatch(r"[a-z][a-z0-9_]*", game_id) is None:
            raise ValueError(f"invalid game id: {game_id}")
        SemVer.parse(version)
        package_root = (self.root / game_id / version).resolve()
        if not package_root.is_relative_to(self.root):
            raise ValueError("package path must remain inside catalog root")
        scan = self.scan()
        for loaded in scan.packages:
            if (
                loaded.package.manifest.game_id == game_id
                and loaded.package.manifest.version == version
            ):
                return loaded
        for failure in scan.failures:
            if failure.package_root.resolve() == package_root:
                raise PackageLoadError(package_root, failure.issues)
        raise KeyError(f"game package is not installed: {game_id}/{version}")

    def get_latest(self, game_id: str) -> LoadedGamePackage:
        versions = self.list_versions(game_id)
        if not versions:
            raise KeyError(f"no installed valid versions for game: {game_id}")
        highest = SemVer.parse(versions[-1])
        equivalent = [
            version
            for version in versions
            if SemVer.parse(version) == highest
        ]
        if len(equivalent) > 1:
            raise ValueError(
                "ambiguous latest semantic version precedence: "
                + ", ".join(equivalent)
            )
        return self.get(game_id, versions[-1])


@total_ordering
@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[int | str, ...] | None = None

    _PATTERN = re.compile(
        r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
        r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
    )

    @classmethod
    def parse(cls, value: str) -> SemVer:
        match = cls._PATTERN.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid semantic version: {value}")
        prerelease: tuple[int | str, ...] | None = None
        if match.group(4) is not None:
            parts: list[int | str] = []
            for part in match.group(4).split("."):
                if part.isdigit():
                    if len(part) > 1 and part.startswith("0"):
                        raise ValueError(
                            f"invalid numeric prerelease identifier: {part}"
                        )
                    parts.append(int(part))
                else:
                    parts.append(part)
            prerelease = tuple(parts)
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=prerelease,
        )

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        release = (self.major, self.minor, self.patch)
        other_release = (other.major, other.minor, other.patch)
        if release != other_release:
            return release < other_release
        if self.prerelease is None:
            return False
        if other.prerelease is None:
            return True
        return _prerelease_less(self.prerelease, other.prerelease)


def _prerelease_less(
    left: tuple[int | str, ...],
    right: tuple[int | str, ...],
) -> bool:
    for left_part, right_part in zip(left, right, strict=False):
        if left_part == right_part:
            continue
        if isinstance(left_part, int) and isinstance(right_part, str):
            return True
        if isinstance(left_part, str) and isinstance(right_part, int):
            return False
        return left_part < right_part  # type: ignore[operator]
    return len(left) < len(right)


def _load_yaml(
    path: Path | None,
    document_name: str,
    issues: list[ValidationIssue],
) -> Any | None:
    if path is None or not path.is_file():
        _error(
            issues,
            "missing_file",
            document_name,
            f"required file does not exist: {path}",
        )
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.load(file, Loader=UniqueKeyLoader)
    except DuplicateYamlKeyError as error:
        _error(
            issues,
            "duplicate_yaml_key",
            document_name,
            str(error),
        )
        return None
    except yaml.YAMLError as error:
        _error(
            issues,
            "invalid_yaml",
            document_name,
            str(error),
        )
        return None
    except (OSError, UnicodeError) as error:
        _error(
            issues,
            "file_read_error",
            document_name,
            str(error),
        )
        return None
    if not isinstance(data, dict):
        _error(
            issues,
            "invalid_document",
            document_name,
            "YAML document root must be a mapping",
        )
        return None
    return data


def _validate_model(
    model_type: type,
    data: Any,
    path: str,
    issues: list[ValidationIssue],
) -> Any | None:
    try:
        return model_type.model_validate(data)
    except ValidationError as error:
        for item in error.errors(include_url=False):
            location = ".".join(str(part) for part in item["loc"])
            code = (
                "invalid_transition"
                if "transition" in item["loc"]
                else "model_validation"
            )
            _error(
                issues,
                code,
                f"{path}.{location}" if location else path,
                item["msg"],
            )
        return None


def _resolve_package_path(
    root: Path,
    relative_path: str,
    path: str,
    issues: list[ValidationIssue],
) -> Path | None:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        _error(
            issues,
            "invalid_asset_path",
            path,
            "package path must be relative",
        )
        return None
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        _error(
            issues,
            "path_traversal",
            path,
            "package path must remain inside package root",
        )
        return None
    return resolved


def _validate_semver(
    version: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    try:
        SemVer.parse(version)
    except ValueError as error:
        _error(issues, "invalid_semver", path, str(error))


def _error(
    issues: list[ValidationIssue],
    code: str,
    path: str,
    message: str,
) -> None:
    issues.append(
        ValidationIssue(
            severity=IssueSeverity.ERROR,
            code=code,
            path=path,
            message=message,
        )
    )
