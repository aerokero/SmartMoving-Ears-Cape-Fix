#!/usr/bin/env python3
"""Build a distributable SmartMoving archive with the EarSkinCompat fix included."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = SCRIPT_DIR / "SmartMoving for ModLoader"
COMPILED_CLASS = SCRIPT_DIR / "farn" / "ears_compat" / "EarSkinCompat.class"
OUTPUT_DIR = SCRIPT_DIR / "dist"
OUTPUT_ZIP = OUTPUT_DIR / "SmartMoving for ModLoader.zip"


def build_compat_class() -> None:
    if os.environ.get("SKIP_COMPILATION") == "1":
        if not COMPILED_CLASS.exists():
            raise SystemExit(f"Expected prebuilt class was not found: {COMPILED_CLASS}")
        return

    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "compile_and_rename_new.py")],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(result.stdout + result.stderr)

    if not COMPILED_CLASS.exists():
        raise SystemExit(f"Expected compiled class was not created: {COMPILED_CLASS}")


def copy_tree(src: Path, dst: Path) -> None:
    for root, _, files in os.walk(src):
        root_path = Path(root)
        relative = root_path.relative_to(src)
        target_dir = dst / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        for filename in files:
            shutil.copy2(root_path / filename, target_dir / filename)


def add_file_to_stage(stage_root: Path, source_file: Path, relative_path: Path) -> None:
    destination = stage_root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_file, destination)


def build_release_zip() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit(f"Missing unpacked mod directory: {SOURCE_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="smartmoving-release-", dir=OUTPUT_DIR) as temp_dir:
        stage_root = Path(temp_dir) / "SmartMoving for ModLoader"
        stage_root.mkdir(parents=True, exist_ok=True)

        copy_tree(SOURCE_DIR, stage_root)
        add_file_to_stage(
            stage_root,
            COMPILED_CLASS,
            Path("farn") / "ears_compat" / "EarSkinCompat.class",
        )

        if OUTPUT_ZIP.exists():
            OUTPUT_ZIP.unlink()

        with zipfile.ZipFile(OUTPUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in stage_root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(stage_root))


def verify_release_zip() -> None:
    with zipfile.ZipFile(OUTPUT_ZIP, "r") as archive:
        names = set(archive.namelist())

    required = {
        "farn/ears_compat/EarSkinCompat.class",
        "net/minecraft/move/SmartMovingRender.class",
    }
    missing = sorted(required - names)
    if missing:
        raise SystemExit("Release zip is missing required entries:\n" + "\n".join(missing))


def main() -> None:
    build_compat_class()
    build_release_zip()
    verify_release_zip()
    print(f"Built release archive: {OUTPUT_ZIP}")


if __name__ == "__main__":
    main()