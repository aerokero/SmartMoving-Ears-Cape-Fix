import zipfile, struct

z = zipfile.ZipFile(r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\[1.7.3] Somnia v11.zip")

for cls_name in z.namelist():
    if not cls_name.endswith(".class"):
        continue
    data = z.read(cls_name)
    pos = 8
    cp_count = struct.unpack_from(">H", data, pos)[0]
    pos += 2
    strings = []
    i = 1
    while i < cp_count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            n = struct.unpack_from(">H", data, pos)[0]; pos += 2
            s = data[pos:pos+n]; pos += n
            strings.append(s)
            i += 1
        elif tag in (7, 8):
            pos += 2; i += 1
        elif tag in (9, 10, 11, 12):
            pos += 4; i += 1
        elif tag in (3, 4):
            pos += 4; i += 1
        elif tag in (5, 6):
            pos += 8; i += 2
        else:
            break
    for s in strings:
        try:
            decoded = s.decode("utf-8")
            # Look for Minecraft field names and timer-related refs
            if decoded in ("H", "rr", "timerRenderCurrentTick") or "timer" in decoded.lower() or "Timer" in decoded:
                print(f"{cls_name}: \"{decoded}\"")
        except:
            pass
