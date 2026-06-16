#!/usr/bin/env python3
"""
Patches ModelCapeRenderer.class inside SmartMoving zip.
Adds a null check for entityplayer at the start of preTransform()
to fix the NPE that occurs when Aether rendering is active.

The NPE: at offset 8, getfield gs.o on a null entityplayer reference.
Fix: insert `if (entityplayer == null) return;` at offset 7 of preTransform.
"""

import struct, zipfile, shutil, io, sys, os

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
MCR_ENTRY = "net/minecraft/move/ModelCapeRenderer.class"
BACKUP    = SM_ZIP + ".backup_mcr"


def read_u1(data, pos):  return data[pos], pos+1
def read_u2(data, pos):  v = struct.unpack_from(">H", data, pos)[0]; return v, pos+2
def read_u4(data, pos):  v = struct.unpack_from(">I", data, pos)[0]; return v, pos+4
def write_u2(v):         return struct.pack(">H", v)
def write_u4(v):         return struct.pack(">I", v)

def skip_cp_entries(data, pos, count):
    """Skip 'count' constant pool entries, return new pos."""
    for _ in range(count):
        tag, pos = read_u1(data, pos)
        if tag in (1,):    # Utf8
            length, pos = read_u2(data, pos); pos += length
        elif tag in (3, 4, 9, 10, 11, 12):  # Integer/Float/Fieldref/Methodref/IMethodref/NameType
            pos += 4
        elif tag in (5, 6):  # Long/Double (take 2 slots)
            pos += 8; _ = next(iter(range(1)), None)  # skip extra slot
        elif tag in (7, 8):  # Class/String
            pos += 2
        else:
            raise ValueError(f"Unknown CP tag {tag} at pos {pos-1}")
    return pos

def find_preTransform_code(data):
    """
    Parse the class file to find preTransform(FZModelRotationRenderer)V
    and return (code_attr_offset, code_offset, code_length, max_stack, max_locals).
    code_attr_offset: byte offset of Code attribute's 'attribute_length' field (u4 after u2 name index).
    code_offset: byte offset of the actual bytecode array.
    """
    pos = 0
    # magic
    pos += 4
    # minor, major
    pos += 4
    # constant pool
    cp_count, pos = read_u2(data, pos)
    cp_start = pos
    # Build a mapping of CP index → name (for Utf8 entries)
    pos_save = pos
    cp_utf8 = {}
    i = 1
    while i < cp_count:
        tag, pos = read_u1(data, pos)
        if tag == 1:  # Utf8
            length, pos = read_u2(data, pos)
            cp_utf8[i] = data[pos:pos+length].decode('utf-8', errors='replace')
            pos += length
            i += 1
        elif tag in (3, 4, 9, 10, 11, 12):
            pos += 4; i += 1
        elif tag in (5, 6):
            pos += 8; i += 2  # Long/Double take 2 slots
        elif tag in (7, 8):
            pos += 2; i += 1
        else:
            raise ValueError(f"Unknown CP tag {tag}")

    # access flags, this, super
    pos += 2 + 2 + 2
    # interfaces
    ifaces, pos = read_u2(data, pos)
    pos += ifaces * 2
    # fields
    field_count, pos = read_u2(data, pos)
    for _ in range(field_count):
        pos += 6  # access, name, desc
        attr_count, pos = read_u2(data, pos)
        for _ in range(attr_count):
            pos += 2  # name index
            attr_len, pos = read_u4(data, pos)
            pos += attr_len
    # methods
    method_count, pos = read_u2(data, pos)
    for _ in range(method_count):
        pos += 2  # access
        name_idx, pos = read_u2(data, pos)
        desc_idx, pos = read_u2(data, pos)
        attr_count, pos = read_u2(data, pos)

        method_name = cp_utf8.get(name_idx, '')
        method_desc = cp_utf8.get(desc_idx, '')

        for _ in range(attr_count):
            attr_name_idx, pos = read_u2(data, pos)
            attr_len, pos = read_u4(data, pos)
            attr_name = cp_utf8.get(attr_name_idx, '')

            if (method_name == 'preTransform' and
                method_desc == '(FZLnet/minecraft/move/ModelRotationRenderer;)V' and
                attr_name == 'Code'):
                # Found it! pos is now at start of Code attribute body.
                # We read attr_name_idx (2 bytes) + attr_len (4 bytes) = 6 bytes total.
                # attr_name_idx is at pos-6, attr_len is at pos-4.
                code_attr_start = pos - 6  # offset of attr_name_idx
                code_body_start = pos
                max_stack, pos = read_u2(data, pos)
                max_locals, pos = read_u2(data, pos)
                code_len, pos = read_u4(data, pos)
                code_start = pos
                return {
                    'attr_name_idx_offset': code_attr_start,
                    'attr_len_offset': code_attr_start + 2,
                    'max_stack_offset': code_body_start,
                    'max_locals_offset': code_body_start + 2,
                    'code_len_offset': code_body_start + 4,
                    'code_start': code_start,
                    'code_len': code_len,
                    'max_stack': max_stack,
                    'max_locals': max_locals,
                    'attr_len': attr_len,
                }
            else:
                pos += attr_len

    return None


def patch_class(data):
    """Patch preTransform to add null check for entityplayer."""
    info = find_preTransform_code(data)
    if info is None:
        raise RuntimeError("Could not find preTransform Code attribute")

    print(f"Found preTransform Code: code_start={info['code_start']}, "
          f"code_len={info['code_len']}, max_stack={info['max_stack']}, "
          f"max_locals={info['max_locals']}")

    orig_code = data[info['code_start']:info['code_start']+info['code_len']]

    # Verify: offset 0-6 of code should be:
    # 2A (aload_0), 23 (fload_1), 1C (iload_2), 2D (aload_3), B7 00 04 (invokespecial #4)
    # Then offset 7: 2A (aload_0)
    expected_start = bytes([0x2A, 0x23, 0x1C, 0x2D, 0xB7, 0x00, 0x04])
    if orig_code[:7] != expected_start:
        print(f"  WARNING: expected start {expected_start.hex()} got {orig_code[:7].hex()}")
        print("  Continuing anyway...")

    # The return is at the END of the method (offset code_len - 1 = 479)
    orig_return_offset = info['code_len'] - 1
    assert orig_code[orig_return_offset] == 0xB1, f"Expected RETURN (0xB1) at end, got {orig_code[orig_return_offset]:02X}"

    # Insert null check at offset 7 (after the super.preTransform call):
    # Bytecode to insert (7 bytes):
    #   ALOAD_0           = 0x2A             (1 byte)
    #   GETFIELD #2       = 0xB4 0x00 0x02   (3 bytes)  [#2 = entityplayer field]
    #   IFNULL target     = 0xC6 0xHH 0xLL   (3 bytes)
    #
    # After insertion, the code is:
    #   [0..6]   original super call
    #   [7..13]  our null check (7 bytes)
    #   [14..]   original code from offset 7 onward
    #   [14 + (original_len - 7) - 1] = [14 + 473] = [487 - 1] = [486] = RETURN
    #
    # IFNULL at offset 11, target = new_return_offset = 486
    # branch_offset = 486 - 11 = 475 = 0x01BB

    INSERT_AT = 7
    INSERT_BYTES = 7
    new_code_len = info['code_len'] + INSERT_BYTES
    new_return_offset = orig_return_offset + INSERT_BYTES  # = 479 + 7 = 486
    ifnull_offset = INSERT_AT + 4  # = 11 (position of IFNULL instruction)
    ifnull_branch = new_return_offset - ifnull_offset  # = 486 - 11 = 475 = 0x01BB

    print(f"  Inserting {INSERT_BYTES} bytes at offset {INSERT_AT}")
    print(f"  New code length: {new_code_len}")
    print(f"  IFNULL at offset {ifnull_offset}, branch to {new_return_offset} (offset +{ifnull_branch})")

    null_check = bytes([
        0x2A,                           # ALOAD_0
        0xB4, 0x00, 0x02,               # GETFIELD #2 (entityplayer)
        0xC6,                           # IFNULL
        (ifnull_branch >> 8) & 0xFF,    # high byte
        ifnull_branch & 0xFF,           # low byte
    ])
    assert len(null_check) == INSERT_BYTES

    new_code = orig_code[:INSERT_AT] + null_check + orig_code[INSERT_AT:]
    assert len(new_code) == new_code_len

    # Verify the return is still there
    assert new_code[new_return_offset] == 0xB1, "RETURN not at expected offset after patch"

    # Build patched class:
    # 1. Replace code bytes
    # 2. Update code_len (u4)
    # 3. Update attr_len (u4) += INSERT_BYTES

    new_data = bytearray(data)

    # Patch code_len
    struct.pack_into(">I", new_data, info['code_len_offset'], new_code_len)

    # Patch attr_len (the Code attribute's length includes max_stack(2)+max_locals(2)+code_len(4)+code+exception_table+sub_attrs)
    new_attr_len = info['attr_len'] + INSERT_BYTES
    struct.pack_into(">I", new_data, info['attr_len_offset'], new_attr_len)

    # Replace the code bytes in-place by rebuilding the bytearray
    code_start = info['code_start']
    code_end   = code_start + info['code_len']
    new_data = new_data[:code_start] + bytearray(new_code) + new_data[code_end:]

    return bytes(new_data)


def main():
    print(f"Patching {SM_ZIP}")

    # Backup
    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup: {BACKUP}")
    else:
        print(f"Backup already exists: {BACKUP}")

    # Read zip, get class
    with zipfile.ZipFile(SM_ZIP, 'r') as zin:
        orig_class = zin.read(MCR_ENTRY)

    print(f"Original ModelCapeRenderer.class: {len(orig_class)} bytes")

    # Patch
    patched = patch_class(orig_class)
    print(f"Patched  ModelCapeRenderer.class: {len(patched)} bytes")

    # Write back to zip
    tmp_zip = SM_ZIP + ".tmp"
    with zipfile.ZipFile(SM_ZIP, 'r') as zin:
        with zipfile.ZipFile(tmp_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == MCR_ENTRY:
                    zout.writestr(item, patched)
                    print(f"  Replaced {MCR_ENTRY} in zip")
                else:
                    zout.writestr(item, zin.read(item.filename))

    os.replace(tmp_zip, SM_ZIP)
    print("Done! Verifying with javap...")

    # Verify
    import subprocess, tempfile
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        cls = z.read(MCR_ENTRY)
    with tempfile.NamedTemporaryFile(suffix='.class', delete=False) as f:
        f.write(cls)
        fname = f.name
    result = subprocess.run(
        ['javap', '-p', '-c', fname],
        capture_output=True, text=True
    )
    os.unlink(fname)

    # Show preTransform first 20 lines to confirm null check is there
    lines = result.stdout.splitlines()
    in_pre = False
    count = 0
    for line in lines:
        if 'preTransform' in line:
            in_pre = True
        if in_pre:
            print(line)
            count += 1
            if count > 25:
                break


def apply_pending():
    """Apply a .tmp zip file if present (run after closing Minecraft)."""
    tmp_zip = SM_ZIP + ".tmp"
    if os.path.exists(tmp_zip):
        print(f"Applying pending patch: {tmp_zip}")
        if os.path.exists(SM_ZIP):
            os.remove(SM_ZIP)
        os.rename(tmp_zip, SM_ZIP)
        print("Done!")
    else:
        print("No pending patch found.")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'apply':
        apply_pending()
    else:
        main()
