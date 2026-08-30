from pathlib import Path

import pytest

from detective_bot.infrastructure.game_catalog import (
    FileSystemGameCatalog,
    PackageLoadError,
    SemVer,
)


FIXTURES = Path(__file__).parents[2] / "fixtures"


def write_minimal_package(root: Path, game_id: str, version: str) -> Path:
    package = root / game_id / version
    package.mkdir(parents=True)
    (package / "manifest.yaml").write_text(
        f"""
schema_version: 1
game_id: {game_id}
version: {version}
display_title: Test
game_file: game.yaml
assets: {{}}
""".strip(),
        encoding="utf-8",
    )
    (package / "game.yaml").write_text(
        """
schema_version: 1
entry_scene: start
variables: {}
scheduled_actions: {}
scenes:
  start:
    interactions:
      - id: finish
        input:
          type: text
        outcomes:
          - id: done
            when: otherwise
            transition: complete
""".strip(),
        encoding="utf-8",
    )
    return package


def test_catalog_lists_installed_valid_games_and_versions() -> None:
    catalog = FileSystemGameCatalog(FIXTURES / "games")
    assert catalog.list_games() == ("synthetic_detective",)
    assert catalog.list_versions("synthetic_detective") == (
        "1.9.0",
        "1.10.0",
    )


def test_catalog_get_latest_uses_semver_not_lexicographic_order() -> None:
    catalog = FileSystemGameCatalog(FIXTURES / "games")
    latest = catalog.get_latest("synthetic_detective")
    assert latest.package.manifest.version == "1.10.0"


def test_semver_orders_prerelease_before_release() -> None:
    assert SemVer.parse("1.10.0-alpha.2") < SemVer.parse("1.10.0")
    assert SemVer.parse("1.10.0-alpha.2") < SemVer.parse("1.10.0-alpha.10")


def test_catalog_reports_invalid_packages_without_installing_them() -> None:
    catalog = FileSystemGameCatalog(FIXTURES / "invalid_games")
    scan = catalog.scan()
    assert scan.packages == ()
    assert len(scan.failures) == 1
    assert catalog.list_games() == ()
    with pytest.raises(PackageLoadError):
        catalog.get("bad_package", "1.0.0")


def test_catalog_missing_game_has_no_latest_version() -> None:
    catalog = FileSystemGameCatalog(FIXTURES / "games")
    with pytest.raises(KeyError):
        catalog.get_latest("missing")


def test_catalog_caches_loaded_immutable_packages() -> None:
    catalog = FileSystemGameCatalog(FIXTURES / "games")
    first = catalog.get("synthetic_detective", "1.10.0")
    second = catalog.get("synthetic_detective", "1.10.0")
    assert first is second
    with pytest.raises(TypeError):
        first.package.definition.scenes["new_scene"] = first.package.definition.scenes[
            "finish"
        ]


def test_catalog_rejects_caller_path_traversal() -> None:
    catalog = FileSystemGameCatalog(FIXTURES / "games")
    with pytest.raises(ValueError):
        catalog.get("../synthetic_detective", "1.10.0")
    with pytest.raises(ValueError):
        catalog.get("synthetic_detective", "../1.10.0")


def test_catalog_rejects_symlink_escape(tmp_path: Path) -> None:
    catalog_root = tmp_path / "catalog"
    outside_root = tmp_path / "outside"
    outside_package = write_minimal_package(
        outside_root,
        "linked_game",
        "1.0.0",
    )
    game_directory = catalog_root / "linked_game"
    game_directory.mkdir(parents=True)
    (game_directory / "1.0.0").symlink_to(
        outside_package,
        target_is_directory=True,
    )
    scan = FileSystemGameCatalog(catalog_root).scan()
    assert scan.packages == ()
    assert scan.failures[0].issues[0].code == "path_traversal"


def test_catalog_rejects_ambiguous_latest_build_metadata(
    tmp_path: Path,
) -> None:
    write_minimal_package(tmp_path, "build_game", "1.0.0+a")
    write_minimal_package(tmp_path, "build_game", "1.0.0+b")
    catalog = FileSystemGameCatalog(tmp_path)
    assert catalog.list_versions("build_game") == ("1.0.0+a", "1.0.0+b")
    with pytest.raises(ValueError, match="ambiguous latest"):
        catalog.get_latest("build_game")
