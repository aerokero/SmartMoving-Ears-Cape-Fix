# SmartMoving Ears Cape Fix

Compatibility fix for the SmartMoving mod and the Ears cape renderer on Minecraft Beta 1.7.3.

## What it does

- Keeps SmartMoving movement behavior intact.
- Preserves Ears cape rendering alongside the SmartMoving player model.
- Packages the fix as a releasable mod archive.

## Installation

Download the latest release zip and place `SmartMoving for ModLoader.zip` into your `.minecraft/mods` folder.

## Build from source

Run:

```powershell
python build_release.py
```

The packaged archive is written to `dist/SmartMoving for ModLoader.zip`.

## Notes

- This repository is intentionally minimal and release-focused.
- The release workflow builds the archive from the tracked mod files and the prebuilt `EarSkinCompat.class` helper.