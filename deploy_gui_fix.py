#!/usr/bin/env python
import zipfile, io, os

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
ARCHIVES = [
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\Armorstand Player fix forge patch.zip",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\6bd56c3c-7688-4947-be61-3b186829a112.jar",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\97bbe32f-8e2e-4e99-bd9f-32286239e4c0.jar",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\8f6f632d-bfad-4f91-8bda-3de6d74ef1e8.jar",
]

with zipfile.ZipFile(SM_ZIP, 'r') as z:
    patched_gui = z.read("net/minecraft/move/GuiIngame.class")

for archive in ARCHIVES:
    if not os.path.exists(archive):
        print(f"Skipping: {archive}")
        continue
    
    buf = io.BytesIO()
    with zipfile.ZipFile(archive, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "net/minecraft/move/GuiIngame.class":
                    zout.writestr(item, patched_gui)
                else:
                    zout.writestr(item, zin.read(item.filename))
    
    with open(archive, 'wb') as f:
        f.write(buf.getvalue())
    print(f"Updated {archive}")

print("Done")
