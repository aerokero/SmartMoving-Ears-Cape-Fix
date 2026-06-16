#!/usr/bin/env python3
"""
Adds missing StackMapTable entry @187 to SmartMoving.beforeMoveEntity(DDD)V.

The v2 injection added two conditional branches (ifeq @146, ifne @155) that both
target offset 187 (the return instruction). The JVM type-checking verifier requires
an explicit StackMapTable entry at every branch target, so:

  VerifyError: Expecting a stackmap frame at branch target 187

FIX: Append same_frame at offset 187.
  Last existing frame: @142
  offset_delta = 187 - 142 - 1 = 44 = 0x2C
  same_frame frame_type byte = 44  (valid: 0 <= 44 <= 63)

Stack state at 187: empty (consistent from all paths - both branches and fall-through
all reach return with empty operand stack).

Changes:
  StackMapTable num_entries:  5 -> 6
  StackMapTable attr_length:  7 -> 8   (1 byte added)
  Code attr_length:         309 -> 310  (1 byte added)
  Class file size:           +1 byte

Operates on current state: code_len=188, correct branch offsets already in place.
"""

import struct, zipfile, io, shutil, os

SM_ZIP = (r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)"
          r"\.minecraft\mods\SmartMoving for ModLoader.zip")
BACKUP = SM_ZIP + ".backup_crawlhitbox3"
ENTRY  = "net/minecraft/move/SmartMoving.class"

METHOD_NAME = b"beforeMoveEntity"
METHOD_DESC = b"(DDD)V"

EXPECTED_CODE_LEN = 188

# Expected StackMapTable body before the fix.
# same_frame entries for @53, @97, @110, @132, @142 (deltas: 53, 43, 12, 21, 9)
EXPECTED_SMT_BODY = bytes([
    0x00, 0x05,             # num_entries = 5
    0x35,                   # same_frame delta=53  -> @53
    0x2B,                   # same_frame delta=43  -> @97
    0x0C,                   # same_frame delta=12  -> @110
    0x15,                   # same_frame delta=21  -> @132
    0x09,                   # same_frame delta=9   -> @142
])

NEW_ENTRY_BYTE = 0x2C       # same_frame delta=44 -> @187  (187-142-1=44)

# Also verify the correct branch offsets are in place.
# ifeq opcode at code offset 146, offset bytes at code offset 148 (1 byte, low) = 0x29 (41)
# ifne opcode at code offset 155, offset bytes at code offset 157 (1 byte, low) = 0x20 (32)
# full signed int16 is at code_offset 147-148 and 156-157 respectively
EXPECTED_IFEQ_OFFSET = 41   # ifeq target = 146+41=187
EXPECTED_IFNE_OFFSET = 32   # ifne target = 155+32=187


# ---------------------------------------------------------------------------
# Class-file helpers
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
            raise ValueError("No Code attribute in method")
    raise ValueError("Method not found")


def find_stackmaptable(data, cp_entries, code_start, code_len):
    """Find StackMapTable sub-attribute in Code body.
    Returns (attr_name_pos, attr_len_pos, body_pos, body_len) or None."""
    pos = code_start + code_len
    et_count = struct.unpack_from(">H", data, pos)[0]; pos += 2
    pos += et_count * 8
    ac = struct.unpack_from(">H", data, pos)[0]; pos += 2
    for _ in range(ac):
        a_name_pos = pos
        a_idx = struct.unpack_from(">H", data, pos)[0]; pos += 2
        a_len_pos = pos
        a_len = struct.unpack_from(">I", data, pos)[0]; pos += 4
        a_body_pos = pos
        e = cp_entries[a_idx]
        if e and e[0] == 1:
            raw = e[1]
            utf8_len = struct.unpack_from(">H", raw, 1)[0]
            if raw[3:3+utf8_len] == b"StackMapTable":
                return a_name_pos, a_len_pos, a_body_pos, a_len
        pos += a_len
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))
    print(f"SmartMoving.class: {len(data)} bytes")

    assert struct.unpack_from(">I", data, 0)[0] == 0xCAFEBABE
    major_ver = struct.unpack_from(">H", data, 6)[0]
    print(f"  Class file major version: {major_ver} (Java {major_ver-44})")

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

    # Verify branch offsets in the injection (at code offsets 142-186)
    ifeq_offset = struct.unpack_from(">h", data, code_start + 147)[0]
    ifne_offset = struct.unpack_from(">h", data, code_start + 156)[0]
    ifeq_target = 146 + ifeq_offset
    ifne_target = 155 + ifne_offset
    print(f"  ifeq at code offset 146: offset={ifeq_offset}, target={ifeq_target}")
    print(f"  ifne at code offset 155: offset={ifne_offset}, target={ifne_target}")
    if ifeq_offset != EXPECTED_IFEQ_OFFSET or ifne_offset != EXPECTED_IFNE_OFFSET:
        print(f"ERROR: Branch offsets not as expected ({EXPECTED_IFEQ_OFFSET}, {EXPECTED_IFNE_OFFSET})")
        return
    if ifeq_target != 187 or ifne_target != 187:
        print("ERROR: Branch targets are not 187")
        return
    print("  Branch offsets OK.")

    # Find StackMapTable
    smt = find_stackmaptable(data, cp_entries, code_start, code_len)
    if smt is None:
        print("ERROR: StackMapTable not found in Code attribute")
        return
    _, a_len_pos, a_body_pos, a_len = smt
    current_smt = bytes(data[a_body_pos:a_body_pos + a_len])
    print(f"  StackMapTable at body_pos={a_body_pos}, attr_len={a_len}")
    print(f"  Current SMT body: {current_smt.hex()}")

    if current_smt != EXPECTED_SMT_BODY:
        print(f"ERROR: SMT body does not match expected {EXPECTED_SMT_BODY.hex()}")
        return
    print("  SMT verified: 5 entries (@53, @97, @110, @132, @142)")

    # Append same_frame(@187) = byte 0x2C at the end of the SMT body
    insert_pos = a_body_pos + a_len
    new_data = bytearray(data[:insert_pos] + bytes([NEW_ENTRY_BYTE]) + data[insert_pos:])

    # Update SMT num_entries: 5 -> 6
    struct.pack_into(">H", new_data, a_body_pos, 6)

    # Update SMT attr_length: a_len -> a_len+1
    struct.pack_into(">I", new_data, a_len_pos, a_len + 1)

    # Update Code attr_length (attr_hdr+2): attr_body_len -> attr_body_len+1
    attr_len_pos = attr_hdr + 2
    old_code_attr_len = struct.unpack_from(">I", data, attr_len_pos)[0]
    struct.pack_into(">I", new_data, attr_len_pos, old_code_attr_len + 1)

    print(f"  SMT: num_entries 5->6, attr_len {a_len}->{a_len+1}")
    print(f"  Code: attr_len {old_code_attr_len}->{old_code_attr_len+1}")
    print(f"  New class size: {len(new_data)} bytes (was {len(data)}, delta +1)")

    # Verify the new SMT body
    # num_entries is now 6 (was updated by pack_into above), entries unchanged + 0x2C appended
    new_smt_body = bytes(new_data[a_body_pos:a_body_pos + a_len + 1])
    print(f"  New SMT body: {new_smt_body.hex()}")
    expected_new = bytes([0x00, 0x06]) + EXPECTED_SMT_BODY[2:] + bytes([NEW_ENTRY_BYTE])
    if new_smt_body != expected_new:
        print(f"ERROR: New SMT body {new_smt_body.hex()} != expected {expected_new.hex()}")
        return
    print("  New SMT verified: 6 entries (@53,@97,@110,@132,@142,@187)")

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
                    zout.writestr(item, bytes(new_data))
                    print(f"  Replaced {ENTRY}")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(SM_ZIP, 'wb') as f:
        f.write(buf.getvalue())

    print("\nDone! StackMapTable now has same_frame(@187).")
    print("  The JVM verifier will accept both ifeq and ifne branching to offset 187.")


if __name__ == "__main__":
    main()
