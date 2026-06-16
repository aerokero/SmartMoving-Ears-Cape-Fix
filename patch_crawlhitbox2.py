#!/usr/bin/env python3
"""
Fixes crawl hitbox (v2, corrected): replaces the wrong-offset injection with the
correct one.

JVM BRANCH OFFSET FORMULA:
  target = opcode_address + branchoffset
  NOT: target = (opcode_address + instruction_length) + branchoffset

The first attempt used the "PC-after" formula, so both ifeq and ifne targeted
abs offset 184 (middle of a putfield sequence) instead of 187 (return).
The JVM VerifyError said "Expecting a stackmap frame at branch target 184".

CORRECTION:
  ifeq at inj pos 4 (abs 146): offset = return_pos - opcode_pos = 45 - 4 = 41 = 0x29
  ifne at inj pos 13 (abs 155): offset = 45 - 13 = 32 = 0x20

The replacement is the same size (45 bytes), so code_length stays at 188.

Operates on the CURRENT zip state (wrong v2 injection, code_len=188).
"""

import struct, zipfile, io, shutil, os

SM_ZIP = (r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)"
          r"\.minecraft\mods\SmartMoving for ModLoader.zip")
BACKUP = SM_ZIP + ".backup_crawlhitbox2b"
ENTRY  = "net/minecraft/move/SmartMoving.class"

METHOD_NAME = b"beforeMoveEntity"
METHOD_DESC = b"(DDD)V"

# Current state: wrong v2 injection is already in place, code_len=188.
EXPECTED_CODE_LEN = 188

# Wrong injection currently in the zip (45 bytes, branch offsets off by 3):
#   ifeq at inj pos 4 has offset 0x26=38 -> target abs 146+38=184 (wrong!)
#   ifne at inj pos 13 has offset 0x1D=29 -> target abs 155+29=184 (wrong!)
OLD_INJECTION = bytes([
    0x2A, 0xB4, 0x00, 0x1C,         # aload_0, getfield #28 (isCrawling:Z)
    0x99, 0x00, 0x26,               # ifeq +38  (WRONG: targets 184 not 187)
    0x2A, 0xB4, 0x00, 0x35,         # aload_0, getfield #53 (heightOffset:F)
    0x0B, 0x95,                     # fconst_0, fcmpl
    0x9A, 0x00, 0x1D,               # ifne +29  (WRONG: targets 184 not 187)
    # sp.bh = (float) 0.8d
    0x2A, 0xB4, 0x00, 0x07,         # aload_0, getfield #7 (sp:Lgs)
    0x14, 0x00, 0xA5,               # ldc2_w #165 (double 0.8d)
    0x90, 0xB5, 0x00, 0x36,         # d2f, putfield #54 (gs.bh:F)
    # sp.aW.e = sp.aW.b + 0.8d
    0x2A, 0xB4, 0x00, 0x07,         # aload_0, getfield #7 (sp:Lgs)
    0xB4, 0x00, 0x3B,               # getfield #59 (gs.aW:Leq)
    0x59,                           # dup
    0xB4, 0x00, 0x3F,               # getfield #63 (eq.b:D = minY)
    0x14, 0x00, 0xA5,               # ldc2_w #165 (double 0.8d)
    0x63, 0xB5, 0x00, 0x3E,         # dadd, putfield #62 (eq.e:D = maxY)
])
assert len(OLD_INJECTION) == 45

# Corrected injection (45 bytes, branch offsets use opcode-relative formula):
#   ifeq at inj pos 4: target = inj pos 45 -> offset = 45-4 = 41 = 0x29
#   ifne at inj pos 13: target = inj pos 45 -> offset = 45-13 = 32 = 0x20
NEW_INJECTION = bytes([
    0x2A, 0xB4, 0x00, 0x1C,         # aload_0, getfield #28 (isCrawling:Z)
    0x99, 0x00, 0x29,               # ifeq +41  (CORRECT: 4+41=45=return)
    0x2A, 0xB4, 0x00, 0x35,         # aload_0, getfield #53 (heightOffset:F)
    0x0B, 0x95,                     # fconst_0, fcmpl
    0x9A, 0x00, 0x20,               # ifne +32  (CORRECT: 13+32=45=return)
    # sp.bh = (float) 0.8d
    0x2A, 0xB4, 0x00, 0x07,         # aload_0, getfield #7 (sp:Lgs)
    0x14, 0x00, 0xA5,               # ldc2_w #165 (double 0.8d)
    0x90, 0xB5, 0x00, 0x36,         # d2f, putfield #54 (gs.bh:F)
    # sp.aW.e = sp.aW.b + 0.8d
    0x2A, 0xB4, 0x00, 0x07,         # aload_0, getfield #7 (sp:Lgs)
    0xB4, 0x00, 0x3B,               # getfield #59 (gs.aW:Leq)
    0x59,                           # dup
    0xB4, 0x00, 0x3F,               # getfield #63 (eq.b:D = minY)
    0x14, 0x00, 0xA5,               # ldc2_w #165 (double 0.8d)
    0x63, 0xB5, 0x00, 0x3E,         # dadd, putfield #62 (eq.e:D = maxY)
])
assert len(NEW_INJECTION) == 45
assert len(NEW_INJECTION) == len(OLD_INJECTION), "Same-size replacement required"


# ---------------------------------------------------------------------------
# Class-file helpers (unchanged from previous version)
# ---------------------------------------------------------------------------

def skip_cp_entry(data, pos):
    tag = data[pos]; pos += 1
    if tag == 1:
        length = struct.unpack_from(">H", data, pos)[0]; pos += 2 + length
    elif tag in (7, 8):
        pos += 2
    elif tag in (9, 10, 11, 12):
        pos += 4
    elif tag in (3, 4):
        pos += 4
    elif tag in (5, 6):
        pos += 8; return pos, True
    else:
        raise ValueError(f"Unknown CP tag {tag} at offset {pos-1}")
    return pos, False


def read_cp(data, pos, cp_count):
    entries = [None]
    i = 1
    while i < cp_count:
        start = pos
        tag = data[pos]
        pos, double_slot = skip_cp_entry(data, pos)
        entries.append((tag, bytes(data[start:pos])))
        i += 1
        if double_slot:
            entries.append(None)
            i += 1
    return entries, pos


def find_utf8(entries, text_bytes):
    for i, e in enumerate(entries):
        if e is None: continue
        tag, raw = e
        if tag == 1:
            length = struct.unpack_from(">H", raw, 1)[0]
            if raw[3:3+length] == text_bytes:
                return i
    return None


def find_method(data, cp_entries, cp_end, name_idx, desc_idx):
    pos = cp_end
    pos += 2  # access_flags
    pos += 2  # this_class
    pos += 2  # super_class
    icount = struct.unpack_from(">H", data, pos)[0]; pos += 2
    pos += icount * 2
    fcount = struct.unpack_from(">H", data, pos)[0]; pos += 2
    for _ in range(fcount):
        pos += 6
        ac = struct.unpack_from(">H", data, pos)[0]; pos += 2
        for _ in range(ac):
            pos += 2
            alen = struct.unpack_from(">I", data, pos)[0]; pos += 4 + alen
    mcount = struct.unpack_from(">H", data, pos)[0]; pos += 2
    for _ in range(mcount):
        m_start = pos
        acc, m_name, m_desc = struct.unpack_from(">HHH", data, pos); pos += 6
        ac = struct.unpack_from(">H", data, pos)[0]; pos += 2
        attrs_start = pos
        for _ in range(ac):
            pos += 2
            alen = struct.unpack_from(">I", data, pos)[0]; pos += 4 + alen
        if m_name == name_idx and m_desc == desc_idx:
            apos = attrs_start
            for _ in range(ac):
                attr_name_idx = struct.unpack_from(">H", data, apos)[0]; apos += 2
                alen = struct.unpack_from(">I", data, apos)[0]; apos += 4
                e = cp_entries[attr_name_idx]
                if e and e[0] == 1:
                    raw = e[1]
                    utf8_len = struct.unpack_from(">H", raw, 1)[0]
                    if raw[3:3+utf8_len] == b"Code":
                        code_len_pos = apos + 4
                        code_len = struct.unpack_from(">I", data, code_len_pos)[0]
                        code_start = code_len_pos + 4
                        return m_start, apos - 6, code_len_pos, code_start, code_len, alen
                apos += alen
            raise ValueError("Method found but has no Code attribute")
    raise ValueError(f"Method not found")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))
    print(f"SmartMoving.class: {len(data)} bytes")

    assert struct.unpack_from(">I", data, 0)[0] == 0xCAFEBABE
    cp_count = struct.unpack_from(">H", data, 8)[0]
    cp_entries, cp_end = read_cp(data, 10, cp_count)

    name_idx = find_utf8(cp_entries, METHOD_NAME)
    desc_idx = find_utf8(cp_entries, METHOD_DESC)
    if name_idx is None or desc_idx is None:
        raise RuntimeError("CP entries not found")

    m_start, attr_hdr, code_len_pos, code_start, code_len, attr_body_len = \
        find_method(data, cp_entries, cp_end, name_idx, desc_idx)
    print(f"  beforeMoveEntity: code_len={code_len}, code_start={code_start}")

    if code_len != EXPECTED_CODE_LEN:
        print(f"ERROR: Expected code_length={EXPECTED_CODE_LEN}, got {code_len}")
        return

    inject_pos = code_start + 142

    actual = bytes(data[inject_pos:inject_pos + len(OLD_INJECTION)])
    if actual != OLD_INJECTION:
        print("ERROR: Old injection bytes not found at code offset 142.")
        print(f"  Expected: {OLD_INJECTION.hex()}")
        print(f"  Actual:   {actual.hex()}")
        return
    print("  Wrong 45-byte injection found at code offset 142.")

    # Same-size replacement: just overwrite the 45 bytes
    data[inject_pos:inject_pos + len(NEW_INJECTION)] = NEW_INJECTION
    # code_length unchanged (same size)

    # Verify the return is still at code_start + 187
    return_byte = data[code_start + 187]
    if return_byte != 0xB1:
        print(f"ERROR: return not at expected position (got 0x{return_byte:02X})")
        return

    # Verify branch offsets by re-reading
    # ifeq opcode at injection pos 4, branch offset at pos 6 (high=5, low=6)
    ifeq_opcode_abs = 142 + 4  # = 146
    ifeq_offset = struct.unpack_from(">h", data, code_start + 142 + 5)[0]
    ifeq_target  = ifeq_opcode_abs + ifeq_offset
    print(f"  ifeq at code offset {ifeq_opcode_abs}: offset={ifeq_offset} "
          f"-> target={ifeq_target} (expected 187)")

    ifne_opcode_abs = 142 + 13  # = 155
    ifne_offset = struct.unpack_from(">h", data, code_start + 142 + 14)[0]
    ifne_target  = ifne_opcode_abs + ifne_offset
    print(f"  ifne at code offset {ifne_opcode_abs}: offset={ifne_offset} "
          f"-> target={ifne_target} (expected 187)")

    if ifeq_target != 187 or ifne_target != 187:
        print("ERROR: Branch targets not correct!")
        return
    print("  Branch targets verified OK (both -> 187 = return).")

    # Backup and write
    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup: {BACKUP}")
    else:
        print(f"Backup already exists: {BACKUP}")

    buf = io.BytesIO()
    with zipfile.ZipFile(SM_ZIP, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, bytes(data))
                    print(f"  Replaced {ENTRY}")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(SM_ZIP, 'wb') as f:
        f.write(buf.getvalue())

    print("\nDone! Branch offsets corrected.")
    print("  ifeq +41: if !isCrawling -> return")
    print("  ifne +32: if heightOffset != 0 -> return")
    print("Both branches now target offset 187 (return), matching the fall-through path.")
    print("sp.bh=0.8f and sp.aW.e=sp.aW.b+0.8 are set for isCrawling+heightOffset==0.")


if __name__ == "__main__":
    main()
