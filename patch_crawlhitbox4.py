#!/usr/bin/env python3
"""
Increases max_stack of SmartMoving.beforeMoveEntity(DDD)V from 4 to 5.

The v2 injection pushes 5 operand-stack slots at its peak:
  // sp.aW.e = sp.aW.b + 0.8
  aload_0, getfield sp, getfield aW,  --> [aW]                  1 slot
  dup,                                --> [aW, aW]               2 slots
  getfield eq.b (double),             --> [aW, double]           3 slots
  ldc2_w 0.8d,   <-- PEAK             --> [aW, double, double]   5 slots  ← OVERFLOW
  dadd,                               --> [aW, double]           3 slots
  putfield eq.e                       --> []                     0 slots

The Code attribute max_stack field is at code_len_pos - 4 (2 bytes big-endian).
Changing it from 4 to 5 is a same-size change; no length fields need updating.

Operates on current state (code_len=188, StackMapTable has @187).
"""

import struct, zipfile, io, shutil, os

SM_ZIP = (r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)"
          r"\.minecraft\mods\SmartMoving for ModLoader.zip")
BACKUP = SM_ZIP + ".backup_crawlhitbox4"
ENTRY  = "net/minecraft/move/SmartMoving.class"

METHOD_NAME = b"beforeMoveEntity"
METHOD_DESC = b"(DDD)V"

EXPECTED_CODE_LEN = 188
EXPECTED_MAX_STACK = 4
REQUIRED_MAX_STACK = 5


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
    pos += 2; pos += 2; pos += 2
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
                        # max_stack is 4 bytes before code_length
                        max_stack_pos = code_len_pos - 4
                        return code_len_pos, code_start, code_len, max_stack_pos
                apos += alen
            raise ValueError("No Code attribute")
    raise ValueError("Method not found")


def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))
    print(f"SmartMoving.class: {len(data)} bytes")

    assert struct.unpack_from(">I", data, 0)[0] == 0xCAFEBABE
    cp_count = struct.unpack_from(">H", data, 8)[0]
    cp_entries, cp_end = read_cp(data, 10, cp_count)

    name_idx = find_utf8(cp_entries, METHOD_NAME)
    desc_idx = find_utf8(cp_entries, METHOD_DESC)

    code_len_pos, code_start, code_len, max_stack_pos = \
        find_method(data, cp_entries, cp_end, name_idx, desc_idx)

    print(f"  beforeMoveEntity: code_len={code_len}, code_start={code_start}")
    print(f"  max_stack field at file offset {max_stack_pos}")

    if code_len != EXPECTED_CODE_LEN:
        print(f"ERROR: Expected code_length={EXPECTED_CODE_LEN}, got {code_len}")
        return

    max_stack = struct.unpack_from(">H", data, max_stack_pos)[0]
    max_locals = struct.unpack_from(">H", data, max_stack_pos + 2)[0]
    print(f"  max_stack={max_stack}, max_locals={max_locals}")

    if max_stack == EXPECTED_MAX_STACK:
        print(f"  max_stack is {EXPECTED_MAX_STACK} as expected, updating to {REQUIRED_MAX_STACK}")
    elif max_stack >= REQUIRED_MAX_STACK:
        print(f"  max_stack={max_stack} already >= {REQUIRED_MAX_STACK}, no change needed")
        return
    else:
        print(f"  max_stack={max_stack}, updating to {REQUIRED_MAX_STACK}")

    new_data = bytearray(data)
    struct.pack_into(">H", new_data, max_stack_pos, REQUIRED_MAX_STACK)
    print(f"  max_stack: {max_stack} -> {REQUIRED_MAX_STACK}")

    # Verify
    assert struct.unpack_from(">H", new_data, max_stack_pos)[0] == REQUIRED_MAX_STACK
    assert len(new_data) == len(data), "max_stack update is same-size, length must not change"

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
                    zout.writestr(item, bytes(new_data))
                    print(f"  Replaced {ENTRY}")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(SM_ZIP, 'wb') as f:
        f.write(buf.getvalue())

    print("\nDone! max_stack updated.")
    print("  The injection peaks at 5 operand stack slots (dup+getfield+ldc2_w).")
    print("  max_stack=5 allows the JVM to allocate sufficient stack space.")


if __name__ == "__main__":
    main()
