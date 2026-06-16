#!/usr/bin/env python3
"""
In ModelCapeRenderer.preTransform, remove the early return that happens when
entityplayer == null. Instead, always apply sway and rotation for animation.
Remove ONLY the final 180-degree Y flip (which duplicates vanilla ds.a's flip).
"""
import zipfile, io, os, struct, shutil

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_mcr_pretransform"
ENTRY = "net/minecraft/move/ModelCapeRenderer.class"

def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    # In preTransform: ifnull 486 (jump to return)
    # Pattern: aload_0, getfield entityplayer, ifnull OFFSET
    # Replace ifnull with goto (unconditional jump) to skip the null check
    # Or replace with nop+nop+nop to remove the check entirely

    # Search for: aload_0 getfield ifnull pattern
    # aload_0 = 0x2A
    # getfield = 0xB4 (3 bytes total: 0xB4 + 2-byte index)
    # ifnull = 0xC0 (3 bytes total: 0xC0 + 2-byte offset)

    pattern1 = bytes([0x2A, 0xB4])  # aload_0, getfield
    pos = data.find(pattern1)

    if pos == -1:
        print("ERROR: aload_0 getfield pattern not found in preTransform")
        return

    print(f"Found potential pattern at {pos}")

    # Check what comes after (should be getfield data + ifnull)
    after_getfield = pos + 3  # Skip aload_0 (1) + getfield (3)
    if data[after_getfield] != 0xC0:
        print(f"Expected ifnull at {after_getfield}, found 0x{data[after_getfield]:02X}")
        print("Searching further...")
        # Try to find the ifnull in the preTransform method
        for i in range(pos, min(pos + 100, len(data))):
            if data[i] == 0xC0:
                print(f"Found ifnull at {i}")
                after_getfield = i
                break

    if data[after_getfield] == 0xC0:
        # Replace ifnull with goto to unconditionally skip the null block
        # ifnull OFFSET jumps if null; we want to always jump
        # So change 0xC0 to 0xA7 (goto)
        data[after_getfield] = 0xA7
        print(f"Changed ifnull to goto at {after_getfield}")
    else:
        print("Could not find ifnull instruction")

    # Now also remove the final 180-degree flip at end
    # Search for the pattern: ldc_w fconst_0 fconst_1 fconst_0 invokestatic glRotatef return
    pattern2 = bytes([0x0B, 0x0C, 0x0B])  # fconst_0, fconst_1, fconst_0

    pos2 = data.rfind(pattern2)  # From end
    if pos2 != -1 and pos2 > pos:  # Make sure it's after our first change
        print(f"Found final flip pattern at {pos2}")
        # Verify invokestatic comes next
        if data[pos2 + 3] == 0xB8:
            # Replace invokestatic with return, pad with nops
            data[pos2 + 3] = 0xB1  # return
            data[pos2 + 4] = 0x00  # nop
            data[pos2 + 5] = 0x00  # nop
            print("Replaced final glRotatef with return+nops")

    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup: {BACKUP}")

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

    print("Done. MCR.preTransform now always executes (no early null return).")

if __name__ == '__main__':
    main()
