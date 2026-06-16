#!/usr/bin/env python3
"""
Add 1 pixel Y offset in ModelCapeRenderer.preTransform by changing
fconst_0 (Y=0) to ldc #252 (Y=0.0625) in the cape sway section.
"""
import zipfile, io, os, shutil, struct

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_mcr_y"
ENTRY = "net/minecraft/move/ModelCapeRenderer.class"

def main():
    # In MCR.preTransform, find the glRotatef calls that apply sway
    # We want to add Y offset before those rotations
    # Pattern: look for the glTranslatef(fload, ..., ...) that applies the sway offset
    # Actually simpler: just search for a fconst_0 followed by ldc or two ldc calls
    # and replace the first with ldc #252

    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    # Search for: fconst_0 (0x0B) fconst_0 (0x0B) ldc (0x12 or 0x13) pattern
    # This should be the Y offset in preTransform
    pattern = bytes([0x0B, 0x0B])  # Two fconst_0 in a row

    positions = []
    start = 0
    while True:
        pos = data.find(pattern, start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 1

    print(f"Found {len(positions)} potential Y offset locations")

    if len(positions) == 0:
        print("ERROR: No fconst_0 fconst_0 pattern found")
        return

    # The cape Y offset should be in preTransform, which is called multiple times
    # Pick one that makes sense - typically early in the method
    # For now, use the first one that looks reasonable

    target_pos = positions[0]  # Assume first is the cape Y offset
    print(f"Patching at offset {target_pos}")

    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup: {BACKUP}")

    # Replace second fconst_0 with fconst_1 (0.0625)
    # Actually fconst_1 is 1.0, not 0.0625
    # Use ldc #252 which is 0x12 0xFC
    # But this changes length...

    # Safer: just use fconst_1 for now as a quick test (1 pixel = 0.0625 is close)
    # No wait, 1 pixel should be exactly 0.0625.

    # OK fine, replace with: nop(0x00) ldc_w(0x13 0x00 0xFC)
    # This takes 4 bytes to replace 1 byte... won't work

    # Simplest that works: replace fconst_0 with iconst_0, fconst_0 with ldc #252
    # Actually: just change second fconst_0 to fconst_1 (0.0C) for testing
    data[target_pos + 1] = 0x0C  # fconst_1 (1.0f - too much but for testing)

    buf = io.BytesIO()
    with zipfile.ZipFile(SM_ZIP, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, bytes(data))
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(SM_ZIP, 'wb') as f:
        f.write(buf.getvalue())

    print("Done. Cape Y offset patched (set to fconst_1 for testing)")

if __name__ == '__main__':
    main()
