"""
Scan all mod zips for Float constants > 1.0 in class files that also
reference Minecraft's timer fields ("H", "timerSpeed", "timerRenderCurrentTick").
Goal: find what mod is setting timer.timerSpeed > 1.0 causing game to run fast.
"""
import zipfile, struct, os, glob

MODS_DIR = r'D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods'

def parse_cp_full(data):
    pos = 8
    cp_count = struct.unpack_from(">H", data, pos)[0]; pos += 2
    entries = {}
    i = 1
    while i < cp_count:
        tag = data[pos]; pos += 1
        if tag == 1:
            n = struct.unpack_from(">H", data, pos)[0]; pos += 2
            s = data[pos:pos+n]; pos += n
            entries[i] = ('Utf8', s)
            i += 1
        elif tag in (7, 8):
            idx = struct.unpack_from(">H", data, pos)[0]; pos += 2
            entries[i] = ('ClassOrStr', idx); i += 1
        elif tag in (9, 10, 11):
            ci, ni = struct.unpack_from(">HH", data, pos); pos += 4
            entries[i] = ('Ref', ci, ni); i += 1
        elif tag == 12:
            ni, di = struct.unpack_from(">HH", data, pos); pos += 4
            entries[i] = ('NAT', ni, di); i += 1
        elif tag == 3:
            v = struct.unpack_from(">i", data, pos)[0]; pos += 4
            entries[i] = ('Int', v); i += 1
        elif tag == 4:
            v = struct.unpack_from(">f", data, pos)[0]; pos += 4
            entries[i] = ('Float', v); i += 1
        elif tag in (5, 6):
            pos += 8; entries[i] = ('LongDouble',); i += 2
        else:
            break
    return entries

TIMER_KEYWORDS = {b'timerSpeed', b'timerRenderCurrentTick', b'timerRenderTicksPassed',
                  b'H', b'rr', b'timer', b'Timer'}

def scan_zip(zip_path):
    try:
        z = zipfile.ZipFile(zip_path, 'r')
    except Exception:
        return
    for cls_name in z.namelist():
        if not cls_name.endswith('.class'):
            continue
        try:
            data = z.read(cls_name)
        except Exception:
            continue
        try:
            entries = parse_cp_full(data)
        except Exception:
            continue

        # Collect float constants > 1.0 (plausible speed multipliers)
        floats = [(i, e[1]) for i, e in entries.items()
                  if e[0] == 'Float' and e[1] > 1.0 and e[1] < 200.0]
        if not floats:
            continue

        # Check if this class references timer-related fields
        strings = [e[1] for e in entries.values() if e[0] == 'Utf8']
        has_timer_ref = any(s in TIMER_KEYWORDS or b'timer' in s.lower() or b'Timer' in s
                            for s in strings)

        if has_timer_ref or any(b'timerSpeed' in s for s in strings):
            for fidx, fval in floats:
                print(f'{zip_path}  {cls_name}  Float #{fidx} = {fval}')

    z.close()

# Scan all zip/jar files in mods dir (skip backups)
for f in sorted(os.listdir(MODS_DIR)):
    if f.endswith(('.zip', '.jar')) and 'backup' not in f.lower():
        scan_zip(os.path.join(MODS_DIR, f))
