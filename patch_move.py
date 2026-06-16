#!/usr/bin/env python3
"""
Adds moveEntityWithHeading (a_(FF)V) and isOnLadder (p()Z) PlayerAPI hooks
to SPC's dc.class so that SmartMoving's sprint and wall-climbing work.

Must be run AFTER patch_dc.py (which adds the 18 bridge methods).

Run: python patch_move.py
"""

import struct, zipfile, io, sys, os, shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from patch_dc import ClassPatcher

JAR_PATH  = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\550432ac-f040-473c-8d30-7aeea8b17e89.jar"
BACKUP    = JAR_PATH + ".backup_move"
DC_ENTRY  = "dc.class"

ALOAD_0       = 0x2A
FLOAD_1       = 0x23
FLOAD_2       = 0x24
INVOKESPECIAL = 0xB7
INVOKESTATIC  = 0xB8
IFNE          = 0x9A
RETURN        = 0xB1
IRETURN       = 0xAC

def i2(idx):
    return [(idx >> 8) & 0xFF, idx & 0xFF]


def build_hook_methods(patcher):
    code_idx = patcher._eu("Code")
    smt_idx  = patcher._eu("StackMapTable")

    # ── Method 1: public void a_(float, float)  →  moveEntityWithHeading hook ──
    #
    # Bytecode (16 bytes):
    #   0: aload_0
    #   1: fload_1
    #   2: fload_2
    #   3: invokestatic  PlayerAPI.moveEntityWithHeading:(Ldc;FF)Z
    #   6: ifne +9       (→ offset 15 = return)
    #   9: aload_0
    #  10: fload_1
    #  11: fload_2
    #  12: invokespecial gs.a_:(FF)V
    #  15: return
    #
    # Java 8 class file (major 52) requires StackMapTable for methods with branches.
    # Branch target at offset 15 (RETURN): same locals [dc, float, float], empty stack.
    # Frame type 15 = "same" frame with offset_delta=15 (fits 0..63 range).
    m_mewh = patcher._em("PlayerAPI", "moveEntityWithHeading", "(Ldc;FF)Z")
    m_gsa_ = patcher._em("gs", "a_", "(FF)V")

    a__code = bytes([
        ALOAD_0, FLOAD_1, FLOAD_2,
        INVOKESTATIC, *i2(m_mewh),
        IFNE, 0x00, 0x09,            # +9: from offset 6 → target 15
        ALOAD_0, FLOAD_1, FLOAD_2,
        INVOKESPECIAL, *i2(m_gsa_),
        RETURN,
    ])
    assert len(a__code) == 16, f"a_ code length mismatch: {len(a__code)}"

    # StackMapTable: 1 entry, same-frame (type=15 = offset_delta=15)
    smt_body = struct.pack('>H', 1) + bytes([15])   # count=1, frame_type=15
    smt_attr = struct.pack('>HI', smt_idx, len(smt_body)) + smt_body

    # Code body with StackMapTable sub-attribute
    code_body = (struct.pack('>HHI', 3, 3, len(a__code))
                 + a__code
                 + struct.pack('>HH', 0, 1)   # 0 exceptions, 1 sub-attr
                 + smt_attr)
    a__attr = struct.pack('>HI', code_idx, len(code_body)) + code_body

    ni_a_  = patcher._eu("a_")
    di_ffv = patcher._eu("(FF)V")
    method_a_ = patcher._method(0x0001, ni_a_, di_ffv, a__attr)

    # ── Method 2: public boolean p()  →  isOnLadder hook ──
    #
    # Bytecode (9 bytes):
    #   0: aload_0
    #   1: aload_0
    #   2: invokespecial gs.p:()Z     (get vanilla isOnLadder result)
    #   5: invokestatic  PlayerAPI.isOnLadder:(Ldc;Z)Z
    #   8: ireturn
    m_gsp      = patcher._em("gs", "p", "()Z")
    pa_ladder  = patcher._em("PlayerAPI", "isOnLadder", "(Ldc;Z)Z")

    p_code = bytes([
        ALOAD_0, ALOAD_0,
        INVOKESPECIAL, *i2(m_gsp),
        INVOKESTATIC,  *i2(pa_ladder),
        IRETURN,
    ])
    assert len(p_code) == 9, f"p code length mismatch: {len(p_code)}"

    ni_p  = patcher._eu("p")
    di_z  = patcher._eu("()Z")   # almost certainly already in CP
    method_p = patcher._method(0x0001, ni_p, di_z,
                   patcher._code_attr(code_idx, 2, 1, p_code))

    return method_a_ + method_p


def main():
    if not os.path.isfile(JAR_PATH):
        print(f"ERROR: JAR not found:\n  {JAR_PATH}")
        sys.exit(1)

    print(f"[1/5] Backing up JAR ...")
    if not os.path.exists(BACKUP):
        shutil.copy2(JAR_PATH, BACKUP)
        print(f"      Backup: {BACKUP}")
    else:
        print(f"      Backup already exists: {BACKUP}")

    print(f"[2/5] Extracting dc.class ...")
    with zipfile.ZipFile(JAR_PATH, 'r') as z:
        dc_data = z.read(DC_ENTRY)
    print(f"      dc.class: {len(dc_data)} bytes")

    print(f"[3/5] Parsing class file ...")
    patcher = ClassPatcher(dc_data)
    print(f"      Methods: {patcher.orig_method_count}, "
          f"CP entries: {patcher.orig_cp_size - 1}")

    if patcher._utf8("moveEntityWithHeading"):
        print("\nCP already contains 'moveEntityWithHeading'.")
        print("Looks like move hooks already patched — nothing to do!")
        return

    if not patcher._utf8("superUpdatePlayerActionState"):
        print("\nERROR: 'superUpdatePlayerActionState' not found in CP.")
        print("Run patch_dc.py first to add the bridge methods!")
        sys.exit(1)

    print(f"[4/5] Building move hooks ...")
    new_methods = build_hook_methods(patcher)
    patched = patcher.assemble(new_methods, n_new=2)
    delta = len(patched) - len(dc_data)
    print(f"      Patched dc.class: {len(patched)} bytes (+{delta})")

    print(f"[5/5] Writing patched dc.class back into JAR ...")
    with zipfile.ZipFile(JAR_PATH, 'r') as zin:
        entries = [(info, zin.read(info.filename)) for info in zin.infolist()]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zout:
        for info, data in entries:
            if info.filename == DC_ENTRY:
                zout.writestr(info, patched)
            else:
                zout.writestr(info, data)

    with open(JAR_PATH, 'wb') as f:
        f.write(buf.getvalue())

    print()
    print("Done! moveEntityWithHeading and isOnLadder hooks added.")
    print("Launch Minecraft — SmartMoving sprint and wall-climb should now work!")
    print()
    print("If something goes wrong, restore from backup:")
    print(f"  copy \"{BACKUP}\" \"{JAR_PATH}\"")


if __name__ == "__main__":
    main()
