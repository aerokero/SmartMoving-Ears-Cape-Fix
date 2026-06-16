#!/usr/bin/env python3
"""
Fixes dry-land crawl hitbox not reducing to 0.8 blocks in SmartMoving Beta 1.7.3.

ROOT CAUSE:
  SmartMoving.moveEntityWithHeading(FF)V calls resetHeightOffset() at offset 628
  every tick, which undoes the setHeightOffset(-1.0f) applied by updateEntityActionState.
  For dry-land crawl, there is NO re-application of setHeightOffset in moveEntityWithHeading
  (only water/climbing paths re-apply it). So the main gs.b(DDD)V call at offset 3978
  always uses the full 1.8-block bbox, preventing passage through 1-block gaps.

  Timeline per tick:
    1. updateEntityActionState: setHeightOffset(-1.0) -> bbox 0.8 tall, sp.b(0,-1,0)
    2. moveEntityWithHeading: resetHeightOffset() at offset 628 -> bbox 1.8 tall again
    3. gs.b(motionX,Y,Z) at offset 3978 -> physics with 1.8 bbox -> CAN'T enter 1-block gaps

FIX:
  Inject into SmartMoving.beforeMoveEntity(DDD)V (called by SmartMoving.moveEntity which
  is invoked by our SmartMovingPlayerBase.moveEntity patch):

    // At end of beforeMoveEntity, before existing return:
    if (this.isCrawling && this.heightOffset == 0f) {
        this.setHeightOffset(-1.0f);
    }

  When moveEntityWithHeading calls gs.b(DDD)V -> PlayerAPI -> SmartMovingPlayerBase.moveEntity
  -> SmartMoving.moveEntity -> beforeMoveEntity, at that point heightOffset=0 (reset by
  resetHeightOffset at offset 628). Our injection re-applies setHeightOffset(-1.0f), making
  the physics call use a 0.8-tall bbox. The entity fits through 1-block gaps.

  When updateEntityActionState calls sp.b(0,-1,0) -> SmartMoving.moveEntity -> beforeMoveEntity,
  at that point heightOffset=-1.0 (just set by updateEntityActionState's own setHeightOffset
  call). Our injection's "heightOffset == 0" check is FALSE -> not applied -> no double-apply.

  afterMoveEntity then corrects posY += heightOffset (-1.0) -> posY = floor+0.62 (crawl cam).

INJECTION BYTES (22 bytes, inserted at offset 142 before the 'return'):
  0x2A              aload_0
  0xB4 0x00 0x1C    getfield #28 (SmartMoving.isCrawling:Z)
  0x99 0x00 0x12    ifeq +18    (goto return at new offset 164 if !isCrawling)
  0x2A              aload_0
  0xB4 0x00 0x35    getfield #53 (SmartMoving.heightOffset:F)
  0x0B              fconst_0
  0x95              fcmpl
  0x9A 0x00 0x09    ifne +9     (goto return at new offset 164 if heightOffset != 0)
  0x2A              aload_0
  0x12 0x53         ldc #83     (float -1.0f)
  0xB7 0x00 0x9E    invokespecial #158 (SmartMoving.setHeightOffset:(F)V)
  -- existing return (0xB1) now at offset 164 --

Constant pool indices verified from javap -c -p SmartMoving.class:
  #28  = Field SmartMoving.isCrawling:Z
  #53  = Field SmartMoving.heightOffset:F
  #83  = float constant -1.0f
  #158 = Method SmartMoving.setHeightOffset:(F)V

Run: python patch_crawlhitbox.py
"""

import struct, zipfile, io, shutil, os

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_crawlhitbox"
ENTRY  = "net/minecraft/move/SmartMoving.class"

METHOD_NAME = b"beforeMoveEntity"
METHOD_DESC = b"(DDD)V"
EXPECTED_CODE_LEN = 143   # offsets 0-142, return at 142

# Bytes to inject at offset 142 (before the 'return' = 0xB1):
INJECTION = bytes([
    0x2A,                   # aload_0
    0xB4, 0x00, 0x1C,       # getfield #28  (isCrawling:Z)
    0x99, 0x00, 0x12,       # ifeq +18      (skip if !crawling -> new return at 164)
    0x2A,                   # aload_0
    0xB4, 0x00, 0x35,       # getfield #53  (heightOffset:F)
    0x0B,                   # fconst_0
    0x95,                   # fcmpl
    0x9A, 0x00, 0x09,       # ifne +9       (skip if heightOffset != 0 -> return at 164)
    0x2A,                   # aload_0
    0x12, 0x53,             # ldc #83       (float -1.0f)
    0xB7, 0x00, 0x9E,       # invokespecial #158  (setHeightOffset:(F)V)
])
assert len(INJECTION) == 22


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
    """Return list of (tag, raw_bytes) for CP entries 1..cp_count-1, plus end pos."""
    entries = [None]  # index 0 unused
    i = 1
    while i < cp_count:
        start = pos
        tag = data[pos]
        pos, double_slot = skip_cp_entry(data, pos)
        entries.append((tag, bytes(data[start:pos])))
        i += 1
        if double_slot:
            entries.append(None)  # placeholder for 2nd slot of Long/Double
            i += 1
    return entries, pos


def find_utf8(entries, text_bytes):
    """Return CP index of a Utf8 entry matching text_bytes, or None."""
    for i, e in enumerate(entries):
        if e is None: continue
        tag, raw = e
        if tag == 1:
            length = struct.unpack_from(">H", raw, 1)[0]
            if raw[3:3+length] == text_bytes:
                return i
    return None


def find_method(data, cp_entries, cp_end, name_idx, desc_idx):
    """
    Walk the class body after CP to find a method with the given name/desc CP indices.
    Returns (method_pos, code_attr_pos, code_len_pos, code_start, code_len) or raises.
    """
    pos = cp_end
    pos += 2  # access_flags
    pos += 2  # this_class
    pos += 2  # super_class
    icount = struct.unpack_from(">H", data, pos)[0]; pos += 2
    pos += icount * 2

    # Skip fields
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
            attr_name = struct.unpack_from(">H", data, pos)[0]; pos += 2
            alen = struct.unpack_from(">I", data, pos)[0]; pos += 4 + alen
        attrs_end = pos

        if m_name == name_idx and m_desc == desc_idx:
            # Found our method — now find its Code attribute
            apos = attrs_start
            for _ in range(ac):
                attr_name_idx = struct.unpack_from(">H", data, apos)[0]; apos += 2
                alen = struct.unpack_from(">I", data, apos)[0]; apos += 4
                # Check if this is the "Code" attribute
                e = cp_entries[attr_name_idx]
                if e and e[0] == 1:
                    raw = e[1]
                    utf8_len = struct.unpack_from(">H", raw, 1)[0]
                    if raw[3:3+utf8_len] == b"Code":
                        # Code attribute body starts at apos
                        # Layout: max_stack(2), max_locals(2), code_length(4), code[code_length]
                        code_len_pos = apos + 4  # skip max_stack + max_locals
                        code_len = struct.unpack_from(">I", data, code_len_pos)[0]
                        code_start = code_len_pos + 4
                        return (m_start, apos - 6, code_len_pos, code_start, code_len, alen)
                apos += alen
            raise ValueError("Method found but has no Code attribute")

    raise ValueError(f"Method not found: name_idx={name_idx} desc_idx={desc_idx}")


def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    print(f"SmartMoving.class: {len(data)} bytes")

    # Parse header
    assert struct.unpack_from(">I", data, 0)[0] == 0xCAFEBABE, "Not a class file"
    cp_count = struct.unpack_from(">H", data, 8)[0]
    print(f"CP count: {cp_count}")

    cp_entries, cp_end = read_cp(data, 10, cp_count)
    print(f"CP ends at offset {cp_end}")

    # Find CP indices for method name and descriptor
    name_idx = find_utf8(cp_entries, METHOD_NAME)
    desc_idx = find_utf8(cp_entries, METHOD_DESC)
    if name_idx is None:
        raise RuntimeError(f"CP entry for '{METHOD_NAME}' not found")
    if desc_idx is None:
        raise RuntimeError(f"CP entry for '{METHOD_DESC}' not found")
    print(f"  'beforeMoveEntity' at CP #{name_idx}")
    print(f"  '(DDD)V' at CP #{desc_idx}")

    # Find the method and its Code attribute
    result = find_method(data, cp_entries, cp_end, name_idx, desc_idx)
    m_start, attr_header_pos, code_len_pos, code_start, code_len, attr_body_len = result
    print(f"  Method at byte offset {m_start}")
    print(f"  Code attribute: code_len={code_len}, code_start={code_start}")

    # Verify expected code length
    if code_len != EXPECTED_CODE_LEN:
        print(f"ERROR: Expected code_length={EXPECTED_CODE_LEN}, got {code_len}")
        print("Class may already be patched or is a different version.")
        return

    # Verify return instruction at offset 142 within code
    return_byte = data[code_start + 142]
    if return_byte != 0xB1:
        print(f"ERROR: Expected 'return' (0xB1) at code offset 142, got 0x{return_byte:02X}")
        return

    print(f"  Verified: return (0xB1) at code offset 142 OK")

    # Inject 22 bytes before the return at code_start+142
    inject_pos = code_start + 142

    new_data = (
        data[:inject_pos] +
        INJECTION +
        data[inject_pos:]
    )

    # Update code_length (at code_len_pos): was 143, now 143+22=165
    new_code_len = code_len + len(INJECTION)
    struct.pack_into(">I", new_data, code_len_pos, new_code_len)

    # Update Code attribute body length (4 bytes before code_len_pos)
    # attr structure: attr_name(2) + attr_len(4) + [max_stack(2)+max_locals(2)+code_len(4)+code+...]
    # attr_len_pos = attr_header_pos + 2  (after the name index)
    attr_len_pos = attr_header_pos + 2
    old_attr_len = struct.unpack_from(">I", new_data, attr_len_pos)[0]
    struct.pack_into(">I", new_data, attr_len_pos, old_attr_len + len(INJECTION))

    print(f"  Injected {len(INJECTION)} bytes at code offset 142")
    print(f"  code_length: {code_len} -> {new_code_len}")
    print(f"  attr body length: {old_attr_len} -> {old_attr_len + len(INJECTION)}")

    # Sanity check: new return at new offset 164
    new_return_byte = new_data[code_start + 164]
    if new_return_byte != 0xB1:
        print(f"ERROR: Return not at new offset 164 (got 0x{new_return_byte:02X})")
        return
    print(f"  Verified: return (0xB1) at new code offset 164 OK")

    # Jump offset verification
    # ifeq at new offset 146 (inject_pos+4), offset bytes at inject_pos+5..6
    ifeq_offset = struct.unpack_from(">h", new_data, code_start + 146 + 1)[0]
    print(f"  ifeq  at offset 146: branch offset={ifeq_offset}, target={146+ifeq_offset} (should be 164)")
    ifne_offset = struct.unpack_from(">h", new_data, code_start + 155 + 1)[0]
    print(f"  ifne  at offset 155: branch offset={ifne_offset}, target={155+ifne_offset} (should be 164)")

    print(f"\nNew class size: {len(new_data)} bytes (was {len(data)}, delta +{len(new_data)-len(data)})")

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

    print("\nDone!")
    print("SmartMoving.beforeMoveEntity now re-applies setHeightOffset(-1.0f) when")
    print("isCrawling=true and heightOffset=0 (i.e., during moveEntityWithHeading's")
    print("main gs.b call). This makes the 0.8-tall crawl bbox active for horizontal")
    print("movement, allowing passage through 1-block-high gaps.")


if __name__ == "__main__":
    main()
