#!/usr/bin/env python3
"""
Neutralize ModelCapeRenderer.setCurrent(gs,float) so entityplayer stays null.

Why: ModelCapeRenderer.preTransform exits early when entityplayer == null,
skipping its OWN sway + 180-degree Y flip. The vanilla ds.a cape path already
applies translate(0,0,0.125)+sway+180. With setCurrent active, BOTH fire =>
double 180 = no flip => cape renders on the FRONT.

Fix: overwrite setCurrent's first bytecode (aload_0, 0x2A) with return (0xB1).
The method returns immediately, entityplayer never gets stored, preTransform
always exits early, and only the vanilla ds.a transform remains => cape on BACK.

Single-byte, fully reversible (backup created). Code attribute length unchanged.
"""
import zipfile, shutil, io, os, struct, sys

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_mcr_setcurrent"
ENTRY  = "net/minecraft/move/ModelCapeRenderer.class"

def find_method_code_offset(data, target_name, target_desc):
    pos = 0
    magic, minor, major = struct.unpack_from('>IHH', data, pos); pos += 8
    assert magic == 0xCAFEBABE
    cp_count, = struct.unpack_from('>H', data, pos); pos += 2
    cp = [None]
    i = 1
    while i < cp_count:
        tag = data[pos]; pos += 1
        if tag == 1:
            n, = struct.unpack_from('>H', data, pos); pos += 2
            cp.append((1, data[pos:pos+n])); pos += n; i += 1
        elif tag in (7, 8):
            v, = struct.unpack_from('>H', data, pos); pos += 2
            cp.append((tag, v)); i += 1
        elif tag in (9, 10, 11, 12):
            a, b = struct.unpack_from('>HH', data, pos); pos += 4
            cp.append((tag, a, b)); i += 1
        elif tag in (3, 4):
            pos += 4; cp.append((tag, 0)); i += 1
        elif tag in (5, 6):
            pos += 8; cp.append((tag, 0)); cp.append(None); i += 2
        else:
            raise ValueError(f"Unknown CP tag {tag} at {pos}")
    def utf(idx):
        e = cp[idx]
        return e[1] if e and e[0] == 1 else None
    pos += 6  # access, this, super
    icount, = struct.unpack_from('>H', data, pos); pos += 2 + icount*2
    fcount, = struct.unpack_from('>H', data, pos); pos += 2
    for _ in range(fcount):
        pos += 6
        ac, = struct.unpack_from('>H', data, pos); pos += 2
        for _ in range(ac):
            pos += 2
            alen, = struct.unpack_from('>I', data, pos); pos += 4 + alen
    mcount, = struct.unpack_from('>H', data, pos); pos += 2
    code_utf = None
    for idx, e in enumerate(cp):
        if e and e[0] == 1 and e[1] == b"Code":
            code_utf = idx; break
    for _ in range(mcount):
        m_access, m_name, m_desc, m_ac = struct.unpack_from('>HHHH', data, pos); pos += 8
        name = utf(m_name); desc = utf(m_desc)
        is_target = (name == target_name and desc == target_desc)
        for _ in range(m_ac):
            attr_name_idx, attr_len = struct.unpack_from('>HI', data, pos); pos += 6
            if is_target and attr_name_idx == code_utf:
                # Code attr body: max_stack(2) max_locals(2) code_length(4) code...
                code_off = pos + 8
                return code_off
            pos += attr_len
    return None

def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    off = find_method_code_offset(data, b"setCurrent", b"(Lgs;F)V")
    if off is None:
        print("ERROR: setCurrent(Lgs;F)V not found"); sys.exit(1)

    cur = data[off]
    if cur == 0xB1:
        print("Already patched (first opcode is return). Nothing to do.")
        return
    if cur != 0x2A:
        print(f"ERROR: expected aload_0 (0x2A) at code start, found 0x{cur:02X}. Aborting.")
        sys.exit(1)

    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup: {BACKUP}")

    data[off] = 0xB1  # return
    print(f"Patched setCurrent first opcode: 0x2A (aload_0) -> 0xB1 (return) at offset {off}")

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
    print("Done. ModelCapeRenderer.setCurrent neutralized.")

if __name__ == '__main__':
    main()
