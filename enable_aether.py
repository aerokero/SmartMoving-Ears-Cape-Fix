import zipfile, io, os

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
ENTRY  = "net/minecraft/move/SmartMovingMod.class"

# Pattern with iconst_0 (0x03)
TARGET_PATCHED = bytes([
    0x12, 0x19,         # ldc "mod_Aether"
    0xB6, 0x00, 0x1A,   # invokevirtual equals
    0x99, 0x00, 0x14,   # ifeq +20
    0x03,               # iconst_0
    0x3D,               # istore_2
])

def main():
    if not os.path.exists(SM_ZIP):
        print("Error: SmartMoving zip not found.")
        return
        
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    if TARGET_PATCHED in data:
        pos = data.index(TARGET_PATCHED)
        data[pos + 8] = 0x04 # change to iconst_1
        print("Enabling Aether detection in SmartMovingMod...")
        
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
        print("Successfully enabled Aether detection!")
    else:
        print("Aether detection already enabled or pattern not found.")

if __name__ == '__main__':
    main()
