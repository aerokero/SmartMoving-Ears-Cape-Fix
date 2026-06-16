#!/usr/bin/env python3
"""
Adds SmartMovingPlayerBase.moveEntity(DDD)Z method to route dc.b(DDD)V through
SmartMoving's beforeMoveEntity/afterMoveEntity pipeline.

ROOT CAUSE of crawl floating:
  dc.b(DDD)V (Entity.move override) calls PlayerAPI.moveEntity which routes to
  SmartMovingPlayerBase.moveEntity(DDD)Z — but that method returns false (inherited
  from PlayerBase default). So PlayerAPI.moveEntity returns false and dc.b falls
  through to its own move logic, bypassing SmartMoving entirely.

  Without SmartMoving's beforeMoveEntity (which calls setYSize) and afterMoveEntity
  (which does posY += heightOffset to correct for crawl bbox adjustment), the height
  offset mechanism is broken:
  - setHeightOffset(-1.0f) raises bbox.minY by 1.0 during crawl
  - Entity.move() then computes posY = bbox.minY (player appears to float by 1.0)
  - afterMoveEntity should correct posY -= 1.0 but is never called

FIX:
  Add to SmartMovingPlayerBase:
    public boolean moveEntity(double dx, double dy, double dz) {
        this.moving.moveEntity(dx, dy, dz);
        return true;
    }

  When this returns true, PlayerAPI.moveEntity returns true, dc.b(DDD)V sees it
  was handled and skips its own move. SmartMoving.moveEntity already calls:
    1. beforeMoveEntity (saves pos, sets ySize)
    2. isp.superMoveEntity (actual physics via dc.superMoveEntity -> gs.b -> Entity.move)
    3. afterMoveEntity (corrects posY by heightOffset)

Run: python patch_movementity.py
"""

import struct, zipfile, io, shutil, os

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_movementity"
ENTRY = "net/minecraft/move/SmartMovingPlayerBase.class"

# Constant pool indices verified from javap -verbose:
# #2  = Class SmartMoving (net/minecraft/move/SmartMoving)
# #5  = Fieldref SmartMovingPlayerBase.moving:Lnet/minecraft/move/SmartMoving;
# #44 = Utf8 "Code" (attribute name)
# #52 = Utf8 "(DDD)V" (descriptor for moveEntity on SmartMoving)
# #75 = Utf8 "(DDD)Z" (descriptor for new moveEntity method: boolean return)
# New entries to add:
# #168 = Utf8 "moveEntity"
# #169 = NameAndType #168:#52  -> moveEntity:(DDD)V
# #170 = Methodref #2.#169     -> SmartMoving.moveEntity:(DDD)V

FIELDREF_MOVING = 5     # Fieldref for SmartMovingPlayerBase.moving
CODE_ATTR_NAME  = 44    # Utf8 "Code"
DESC_DDDV       = 52    # Utf8 "(DDD)V"
DESC_DDDZ       = 75    # Utf8 "(DDD)Z"
CLASS_SMARTMOVING = 2   # Class SmartMoving

NEW_CP_MOVEENTITY_NAME = 168   # Utf8 "moveEntity"
NEW_CP_NAT         = 169       # NameAndType: moveEntity:(DDD)V
NEW_CP_METHODREF   = 170       # Methodref: SmartMoving.moveEntity:(DDD)V


def skip_cp_entry(data, pos):
    tag = data[pos]; pos += 1
    if tag == 1:    # Utf8
        length = struct.unpack_from(">H", data, pos)[0]; pos += 2 + length
    elif tag in (7, 8):   # Class, String
        pos += 2
    elif tag in (9, 10, 11, 12):  # Fieldref, Methodref, InterfaceMethodref, NameAndType
        pos += 4
    elif tag in (3, 4):   # Integer, Float
        pos += 4
    elif tag in (5, 6):   # Long, Double (take 2 CP slots)
        pos += 8; return pos, True  # double-slot
    else:
        raise ValueError(f"Unknown CP tag {tag}")
    return pos, False


def parse_class(data):
    pos = 0
    magic = struct.unpack_from(">I", data, pos)[0]; pos += 4
    assert magic == 0xCAFEBABE, "Not a class file"
    minor, major = struct.unpack_from(">HH", data, pos); pos += 4
    cp_count_offset = pos
    cp_count = struct.unpack_from(">H", data, pos)[0]; pos += 2
    cp_entries_start = pos

    i = 1
    while i < cp_count:
        pos, double_slot = skip_cp_entry(data, pos)
        if double_slot:
            i += 2
        else:
            i += 1

    cp_end = pos

    # Parse rest: access_flags, this, super, interfaces, fields, methods
    rp = cp_end
    rp += 2  # access_flags
    rp += 2  # this_class
    rp += 2  # super_class
    icount = struct.unpack_from(">H", data, rp)[0]; rp += 2
    rp += icount * 2

    fcount = struct.unpack_from(">H", data, rp)[0]; rp += 2
    for _ in range(fcount):
        rp += 6  # access, name, descriptor
        ac = struct.unpack_from(">H", data, rp)[0]; rp += 2
        for _ in range(ac):
            rp += 2
            alen = struct.unpack_from(">I", data, rp)[0]; rp += 4 + alen

    methods_count_offset = rp
    mcount = struct.unpack_from(">H", data, rp)[0]; rp += 2
    methods_data_start = rp
    for _ in range(mcount):
        rp += 6  # access, name, descriptor
        ac = struct.unpack_from(">H", data, rp)[0]; rp += 2
        for _ in range(ac):
            rp += 2
            alen = struct.unpack_from(">I", data, rp)[0]; rp += 4 + alen
    methods_data_end = rp

    return {
        'cp_count_offset': cp_count_offset,
        'cp_count': cp_count,
        'cp_entries_start': cp_entries_start,
        'cp_end': cp_end,
        'methods_count_offset': methods_count_offset,
        'methods_count': mcount,
        'methods_data_start': methods_data_start,
        'methods_data_end': methods_data_end,
        'minor': minor, 'major': major,
    }


def build_new_method():
    # public boolean moveEntity(double dx, double dy, double dz) {
    #     this.moving.moveEntity(dx, dy, dz);
    #     return true;
    # }
    code_bytes = bytes([
        0x2A,                   # aload_0  (this)
        0xB4, 0x00, FIELDREF_MOVING,  # getfield #5 (this.moving)
        0x27,                   # dload_1  (dx)
        0x29,                   # dload_3  (dy)
        0x18, 0x05,             # dload 5  (dz)
        0xB6, 0x00, NEW_CP_METHODREF,  # invokevirtual #170 (SmartMoving.moveEntity)
        0x04,                   # iconst_1
        0xAC,                   # ireturn
    ])

    max_stack = 7   # this.moving(1) + dx(2) + dy(2) + dz(2)
    max_locals = 7  # this(1) + dx(2) + dy(2) + dz(2)

    code_attr_body = struct.pack(">HHI", max_stack, max_locals, len(code_bytes))
    code_attr_body += code_bytes
    code_attr_body += struct.pack(">HH", 0, 0)  # exception_table_length=0, attrs_count=0

    code_attr = struct.pack(">HI", CODE_ATTR_NAME, len(code_attr_body)) + code_attr_body

    # method_info: access=public(0x0001), name=#168, descriptor=#75, attrs_count=1
    method = struct.pack(">HHHH", 0x0001, NEW_CP_MOVEENTITY_NAME, DESC_DDDZ, 1) + code_attr
    return method


def main():
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        data = bytearray(z.read(ENTRY))

    print(f"SmartMovingPlayerBase.class: {len(data)} bytes")

    info = parse_class(data)
    print(f"Version: {info['major']}.{info['minor']}")
    print(f"CP count: {info['cp_count']} (entries 1..{info['cp_count']-1})")
    print(f"CP ends at offset {info['cp_end']}")
    print(f"Methods count: {info['methods_count']}")

    # Verify expected CP count (should be 167+1=168 entries total, so cp_count=168)
    expected_cp_count = 168  # 167 entries (1..167) + 1 for the count field
    if info['cp_count'] != expected_cp_count:
        print(f"WARNING: Expected cp_count={expected_cp_count}, got {info['cp_count']}")
        print("Indices may be wrong — aborting.")
        return

    # New CP entries to append:
    # #168 = Utf8 "moveEntity"
    # #169 = NameAndType #168:#52 (moveEntity:(DDD)V)
    # #170 = Methodref #2.#169 (SmartMoving.moveEntity:(DDD)V)
    new_cp = bytearray()
    name = b"moveEntity"
    new_cp += bytes([1]) + struct.pack(">H", len(name)) + name   # Utf8
    new_cp += bytes([12]) + struct.pack(">HH", NEW_CP_MOVEENTITY_NAME, DESC_DDDV)  # NameAndType
    new_cp += bytes([10]) + struct.pack(">HH", CLASS_SMARTMOVING, NEW_CP_NAT)      # Methodref

    new_cp_count = info['cp_count'] + 3  # 168 -> 171

    new_method = build_new_method()
    print(f"New method bytes: {len(new_method)}")

    # Reconstruct the class file:
    new_data = bytearray()
    # Before cp_count field:
    new_data += data[:info['cp_count_offset']]
    # New cp_count:
    new_data += struct.pack(">H", new_cp_count)
    # Original CP entries:
    new_data += data[info['cp_entries_start']:info['cp_end']]
    # New CP entries:
    new_data += new_cp
    # Class body up to methods_count:
    new_data += data[info['cp_end']:info['methods_count_offset']]
    # New methods count:
    new_data += struct.pack(">H", info['methods_count'] + 1)
    # Original methods:
    new_data += data[info['methods_data_start']:info['methods_data_end']]
    # New method:
    new_data += new_method
    # Class attributes and rest:
    new_data += data[info['methods_data_end']:]

    print(f"New class size: {len(new_data)} bytes (was {len(data)}, delta +{len(new_data)-len(data)})")

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
    print("SmartMovingPlayerBase.moveEntity(DDD)Z now delegates to SmartMoving.moveEntity(DDD)V")
    print("This fixes crawl floating (afterMoveEntity adjusts posY by heightOffset)")
    print("and sneak height (beforeMoveEntity calls setYSize(0.6f)).")


if __name__ == "__main__":
    main()
