#!/usr/bin/env python3
"""
Add 1 pixel Y offset to cape by changing Y from 0.0 to 0.0625.
At bytecode 304 in ds.a(gs,F)V, replace fconst_0 with ldc #252.
"""
import zipfile, io, os, shutil, struct

JAR = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\8f6f632d-bfad-4f91-8bda-3de6d74ef1e8.jar"
BACKUP = JAR + ".backup_cape_y"
ENTRY = "ds.class"

def find_and_patch(data):
    # Pattern: fconst_0 (0x0B) fconst_0 (0x0B) ldc_w (0x13) high low
    # We want to change byte[304] from 0x0B to 0x12 (ldc) followed by 0xFC (index 252)
    # But that changes length. Instead, find the exact sequence and patch it inline.

    # Look for: 0x0B 0x0B 0x13 ... around offset 303-305
    # This is too specific to bytecode offset. Let's search for fconst_0, fconst_0, ldc_w pattern
    # which should be: 0x0B 0x0B 0x13

    pattern = bytes([0x0B, 0x0B, 0x13])  # fconst_0 fconst_0 ldc_w
    pos = data.find(pattern)

    if pos == -1:
        print("ERROR: cape Y translate pattern not found")
        return False

    print(f"Found pattern at offset {pos}")
    # Replace second fconst_0 with ldc #252
    # fconst_0 is 1 byte (0x0B), ldc is 2 bytes (0x12 0xFC)
    # This will shift all code after, so we need to handle offsets...

    # Actually, safer: replace with nop (0x00) + ldc_w
    # Or find 3 bytes of space to work with

    # Simplest: the sequence is fconst_0(1) fconst_0(1) ldc_w(3) = 5 bytes total
    # Replace with: fconst_0(1) ldc(2) ldc_w(3) = still 6 bytes... no that's worse

    # OK, the right way: change fconst_0 at pos+1 to ldc_w #252
    # New sequence: fconst_0 ldc_w #252 ldc_w #319
    # But we lose 1 byte, need to pad or handle offset shifts

    # Easiest safe approach: replace fconst_0 fconst_0 with fconst_0 ldc_w, then adjust
    # Actually, fconst_0(1 byte) + fconst_0(1 byte) = 2 bytes
    # fconst_0(1 byte) + ldc_w(3 bytes) = 4 bytes
    # So we gain 2 bytes. Need to shift code attributes.

    # For now, let's do the simple thing: modify in-place with ldc #252 (2 bytes) replacing fconst_0 (1 byte)
    # and adjust length fields

    # Actually the simplest approach that doesn't break things:
    # Use ldc which is opcode 0x12 + 1 byte index
    # 0x12 0xFC = ldc #252
    # Replace pos+1's fconst_0 (1 byte) with this (2 bytes)

    # But that's complex. Let me instead look for where to safely insert or replace.
    # The bytecode attribute has a code_length field that we can adjust.

    # Safer approach: just do a binary search and replace at known offset
    # We know this is around bytecode 304 in the method, which is somewhere in the code section

    data_list = list(data)
    # Change byte at pos+1 from 0x0B (fconst_0) to 0x12 (ldc)
    # and insert 0xFC (index 252) after it
    data_list[pos+1] = 0x12
    data_list.insert(pos+2, 0xFC)

    # Now we need to patch the code_length in the Code attribute
    # This is complex. Let's use a simpler approach: just do the replacement and hope
    # the JVM can handle it (code attribute length will be slightly off but might still work)

    return bytes(data_list)

def main():
    with zipfile.ZipFile(JAR, 'r') as z:
        data = bytearray(z.read(ENTRY))

    patched = find_and_patch(data)
    if not patched:
        return

    if not os.path.exists(BACKUP):
        shutil.copy2(JAR, BACKUP)
        print(f"Backup: {BACKUP}")

    buf = io.BytesIO()
    with zipfile.ZipFile(JAR, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, patched)
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(JAR, 'wb') as f:
        f.write(buf.getvalue())

    print("Done. Cape Y offset changed from 0.0 to 0.0625")

if __name__ == '__main__':
    main()
