#!/usr/bin/env python3
"""
Patches SmartMovingRender.class inside SmartMoving zip to fix a GL state bug
that makes chat text invisible.

Root cause: SmartMovingRender.renderGuiIngame() ends with glDisable(GL_BLEND),
leaving blending disabled for all subsequent GUI rendering (chat, etc.).

Fix: change the final glDisable(GL_BLEND) call to glEnable(GL_BLEND) so the
GL state is correct after SmartMoving's HUD renders.

Run: python patch_gl.py
"""

import zipfile, shutil, io, os, sys

SM_ZIP  = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP  = SM_ZIP + ".backup_gl"
ENTRY   = "net/minecraft/move/SmartMovingRender.class"

# End of renderGuiIngame:
#   sipush 3042  (GL_BLEND)  = 11 0B E2
#   invokestatic #101 (glDisable) = B8 00 65   ← change 0x65 to 0x66 (glEnable)
#   return                   = B1
TARGET  = bytes([0x11, 0x0B, 0xE2, 0xB8, 0x00, 0x65, 0xB1])
PATCH_OFFSET = 5   # index within TARGET of the 0x65 byte to change
NEW_BYTE = 0x66    # #102 = GL11.glEnable

def main():
    print(f"Patching {SM_ZIP}")

    if not os.path.exists(SM_ZIP):
        print(f"ERROR: SmartMoving zip not found"); sys.exit(1)

    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    count = data.count(TARGET)
    if count != 1:
        print(f"ERROR: Expected 1 match for target pattern, found {count}. Aborting.")
        sys.exit(1)

    pos = data.index(TARGET)
    print(f"Found target sequence at file offset {pos}")
    print(f"  Before patch: ...{data[pos+3:pos+7].hex()}...")
    assert data[pos + PATCH_OFFSET] == 0x65, f"Expected 0x65, got {data[pos+PATCH_OFFSET]:02X}"
    data[pos + PATCH_OFFSET] = NEW_BYTE
    print(f"  After  patch: ...{data[pos+3:pos+7].hex()}...")

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

    print("Done! Chat text should now be visible.")
    print("If something breaks, restore:")
    print(f"  copy \"{BACKUP}\" \"{SM_ZIP}\"")


if __name__ == "__main__":
    main()
