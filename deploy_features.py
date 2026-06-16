#!/usr/bin/env python3
import zipfile, io, os

ARCHIVES = [
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\Armorstand Player fix forge patch.zip",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\6bd56c3c-7688-4947-be61-3b186829a112.jar",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\97bbe32f-8e2e-4e99-bd9f-32286239e4c0.jar",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\8f6f632d-bfad-4f91-8bda-3de6d74ef1e8.jar",
]
CLASS_PATH = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\smartmoving\SmartMovingFeatures.class"
ENTRY = "SmartMovingFeatures.class"

def main():
    print(f"Reading compiled class from: {CLASS_PATH}")
    with open(CLASS_PATH, 'rb') as f:
        class_data = f.read()

    print(f"Class size: {len(class_data)} bytes")

    for archive in ARCHIVES:
        if not os.path.exists(archive):
            print(f"Archive not found, skipping: {archive}")
            continue

        print(f"Updating archive: {archive}")
        buf = io.BytesIO()
        with zipfile.ZipFile(archive, 'r') as zin:
            with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                replaced = False
                for item in zin.infolist():
                    if item.filename == ENTRY:
                        zout.writestr(item, class_data)
                        print(f"  Replaced entry: {ENTRY}")
                        replaced = True
                    else:
                        zout.writestr(item, zin.read(item.filename))

                if not replaced:
                    zout.writestr(ENTRY, class_data)
                    print(f"  Added new entry: {ENTRY}")

        with open(archive, 'wb') as f:
            f.write(buf.getvalue())

        print(f"Successfully updated {archive}")

if __name__ == '__main__':
    main()
