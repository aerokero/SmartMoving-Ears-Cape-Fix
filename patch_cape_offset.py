#!/usr/bin/env python3
"""
Change cape Z offset from 0.125 to 0.25 (2 pixels further out from player).
Modifies the float constant in ds.class constant pool.
"""
import zipfile, io, os, shutil, struct

JAR = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\8f6f632d-bfad-4f91-8bda-3de6d74ef1e8.jar"
BACKUP = JAR + ".backup_cape_offset"
ENTRY = "ds.class"

def main():
    # 0.125f = 0x3E000000, 0.25f = 0x3E800000
    OLD = struct.pack('>f', 0.125)
    NEW = struct.pack('>f', 0.25)

    with zipfile.ZipFile(JAR, 'r') as z:
        data = bytearray(z.read(ENTRY))

    count = data.count(OLD)
    print(f"Found {count} occurrence(s) of 0.125f in ds.class")

    if count == 0:
        print("ERROR: 0.125f not found"); return

    # Find the one in the cape section (should be around bytecode offset 305-308)
    # We'll replace the first occurrence that appears in the code section
    pos = data.find(OLD)
    print(f"Replacing at offset {pos}")

    if not os.path.exists(BACKUP):
        shutil.copy2(JAR, BACKUP)
        print(f"Backup: {BACKUP}")

    data[pos:pos+4] = NEW

    buf = io.BytesIO()
    with zipfile.ZipFile(JAR, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, bytes(data))
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(JAR, 'wb') as f:
        f.write(buf.getvalue())

    print("Done. Cape offset changed from 0.125 to 0.25")

if __name__ == '__main__':
    main()
