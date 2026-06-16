#!/usr/bin/env python3
import zipfile, io, os

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
CLASS_PATH = r"d:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\smartmoving\farn\ears_compat\EarSkinCompat.class"
ENTRY = "farn/ears_compat/EarSkinCompat.class"

def main():
    print(f"Reading compiled class from: {CLASS_PATH}")
    with open(CLASS_PATH, 'rb') as f:
        class_data = f.read()
    
    print(f"Class size: {len(class_data)} bytes")
    
    # Read existing zip and rewrite with the new entry
    buf = io.BytesIO()
    with zipfile.ZipFile(SM_ZIP, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            replaced = False
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, class_data)
                    print(f"Replaced existing entry: {ENTRY}")
                    replaced = True
                else:
                    zout.writestr(item, zin.read(item.filename))
            
            if not replaced:
                zout.writestr(ENTRY, class_data)
                print(f"Added new entry: {ENTRY}")
                
    with open(SM_ZIP, 'wb') as f:
        f.write(buf.getvalue())
        
    print("Packing complete. Verifying presence of entry in zip...")
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        names = z.namelist()
        if ENTRY in names:
            print(f"Verification Success: {ENTRY} is in the zip.")
        else:
            print(f"Verification Failed: {ENTRY} NOT found in the zip.")

if __name__ == '__main__':
    main()
