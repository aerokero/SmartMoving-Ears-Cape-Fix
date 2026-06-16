#!/usr/bin/env python3
"""
In ModelCapeRenderer.preTransform, skip the final glRotatef(180, 0, 1, 0)
by replacing those bytecodes with just return.

This keeps sway/rotation working (fixes crouch) but removes the double-flip
that puts cape on front. The vanilla ds.a(gs,F)V provides the single 180° flip.
"""
import zipfile, io, os, shutil

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_mcr_final_flip"
ENTRY = "net/minecraft/move/ModelCapeRenderer.class"

def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    # Final glRotatef(180, 0, 1, 0) sequence at end of preTransform
    # ldc_w #20 (180.0f) = 0x13 followed by 2-byte index
    # fconst_0 = 0x0B
    # fconst_1 = 0x0C
    # fconst_0 = 0x0B
    # invokestatic glRotatef = 0xB8 followed by 2-byte index

    # Search for pattern: 13 ?? ?? 0B 0C 0B B8 ?? ??
    # Where ?? are the method indices

    pattern = bytes([0x13, 0x0B, 0x0C, 0x0B, 0xB8])  # Partial pattern (skip indices)

    # Actually, let's search for the simpler pattern: ldc_w fconst_0 fconst_1 fconst_0
    simple_pattern = bytes([0x0B, 0x0C, 0x0B])  # fconst_0, fconst_1, fconst_0

    pos = data.rfind(simple_pattern)  # Find from end (final flip is at end)
    if pos == -1:
        print("ERROR: final flip pattern not found")
        return

    print(f"Found pattern at offset {pos}")

    # Check what comes before and after
    before = data[pos-3:pos]
    after = data[pos+3:pos+10]
    print(f"  Before: {before.hex()}")
    print(f"  After: {after.hex()}")

    # The sequence should be: ldc_w(3) + fconst_0(1) + fconst_1(1) + fconst_0(1) + invokestatic(3)
    # We replace all of that (9 bytes) with just return (1 byte)
    # But that changes lengths... Instead, replace with NOPs padding

    # Safer: just overwrite the glRotatef invokestatic part
    # The invokestatic is 3 bytes (0xB8 + 2-byte index), change it to return (0xB1)
    invokestatic_pos = pos + 3
    if data[invokestatic_pos] != 0xB8:
        print(f"ERROR: expected invokestatic at {invokestatic_pos}, found 0x{data[invokestatic_pos]:02X}")
        return

    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup: {BACKUP}")

    # Replace 0xB8 with 0xB1 (return), pad next 2 bytes with NOPs
    data[invokestatic_pos] = 0xB1  # return
    data[invokestatic_pos + 1] = 0x00  # nop
    data[invokestatic_pos + 2] = 0x00  # nop

    print(f"Patched: replaced glRotatef with return + nops")

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

    print("Done. MCR.preTransform final 180° flip removed.")

if __name__ == '__main__':
    main()
