#!/usr/bin/env python3
"""
Patches SmartMovingMod.class inside SmartMoving zip to disable Aether detection.

Root cause of model rendering bugs:
  SmartMoving detects mod_Aether and uses RenderPlayerAether which calls back into
  Aether's doRenderMisc/doRenderEnergyShield, rendering SmartMoving's ModelPlayer
  instances as "accessories" on top of the main player — creating duplicate limbs
  ("third leg", head/cape artifacts).

Fix:
  In SmartMovingMod.ModsLoaded, when mod_Aether is detected:
    Original: iconst_1; istore_2  (hasAether = true)
    Patched:  iconst_0; istore_2  (hasAether = false)

  SmartMoving then uses RenderPlayer (its non-Aether renderer) for dc/xz entities.
  Aether continues to use its own RenderPlayerAether for gs-typed entities.
  SmartMoving animations (climb, sprint, crawl) still work correctly.

Run: python patch_aether.py
"""

import zipfile, shutil, io, sys, os, struct

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_aether"
ENTRY  = "net/minecraft/move/SmartMovingMod.class"

# Pattern to find in ModsLoaded:
#   The bytecode around the Aether detection:
#     ldc #25 "mod_Aether"          → 12 19     (ldc uses 1-byte index since #25 < 256)
#     invokevirtual #26 equals      → B6 00 1A
#     ifeq +20 (→ 84)               → 99 00 14
#     iconst_1                      → 04       ← change to iconst_0 (03)
#     istore_2                      → 3D
#
# CP index #25 = 0x19 = 25  (fits in 1 byte → ldc 0x12, not ldc_w 0x13)
# CP index #26 = 0x001A = 26

TARGET = bytes([
    0x12, 0x19,         # ldc #25 "mod_Aether"  (2 bytes: opcode + 1-byte index)
    0xB6, 0x00, 0x1A,   # invokevirtual #26 (String.equals)
    0x99, 0x00, 0x14,   # ifeq +20
    0x04,               # iconst_1  ← PATCH THIS BYTE
    0x3D,               # istore_2
])
PATCH_OFFSET = 8  # index of the iconst_1 byte within TARGET
NEW_BYTE = 0x04   # iconst_1


def main():
    print(f"Patching {SM_ZIP}")

    if not os.path.exists(SM_ZIP):
        print(f"ERROR: SmartMoving zip not found")
        sys.exit(1)

    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    print(f"SmartMovingMod.class: {len(data)} bytes")

    count = data.count(TARGET)
    if count == 0:
        # Maybe already patched?
        patched_target = TARGET[:PATCH_OFFSET] + bytes([NEW_BYTE]) + TARGET[PATCH_OFFSET+1:]
        if data.count(patched_target) == 1:
            print("Already patched — nothing to do!")
            return
        print(f"ERROR: target pattern not found in class file. Not patching.")
        print(f"  Searching for: {TARGET.hex()}")
        sys.exit(1)
    if count != 1:
        print(f"ERROR: Expected 1 match, found {count}. Aborting.")
        sys.exit(1)

    pos = data.index(TARGET)
    print(f"Found target at file offset {pos}")
    print(f"  Byte at patch_offset: 0x{data[pos + PATCH_OFFSET]:02X} "
          f"(expected 0x{TARGET[PATCH_OFFSET]:02X})")

    data[pos + PATCH_OFFSET] = NEW_BYTE
    print(f"  Patched: iconst_1 -> iconst_0 (hasAether always false)")

    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup: {BACKUP}")
    else:
        print(f"Backup already exists: {BACKUP}")

    buf = io.BytesIO()
    with zipfile.ZipFile(SM_ZIP, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, bytes(data))
                    print(f"  Replaced {ENTRY}")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(SM_ZIP, 'wb') as f:
        f.write(buf.getvalue())

    print("\nDone!")
    print("SmartMoving will now use RenderPlayer instead of RenderPlayerAether.")
    print("Model rendering bugs (third leg, head, cape) should be gone.")
    print()
    print("If something breaks, restore:")
    print(f'  copy "{BACKUP}" "{SM_ZIP}"')


if __name__ == "__main__":
    main()
