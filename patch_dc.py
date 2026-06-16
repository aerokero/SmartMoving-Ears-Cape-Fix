#!/usr/bin/env python3
"""
Patches SPC's dc.class (in the SPC jarmod) to add 18 missing PlayerAPI bridge
methods that SmartMoving requires. Without these methods, the game crashes with:
  java.lang.NoSuchMethodError: dc.superUpdatePlayerActionState()V

Run: python patch_dc.py
Requires: Python 3.x (standard library only, no pip installs needed)
"""

import struct, zipfile, shutil, io, sys, os

JAR_PATH  = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\550432ac-f040-473c-8d30-7aeea8b17e89.jar"
BACKUP    = JAR_PATH + ".backup"
DC_ENTRY  = "dc.class"

# ── Bytecode opcodes ──────────────────────────────────────────────────────────
ALOAD_0       = 0x2A
ALOAD_1       = 0x2B
ILOAD_1       = 0x1B
ILOAD_2       = 0x1C
ILOAD_3       = 0x1D
FLOAD_1       = 0x23
FLOAD_2       = 0x24
DLOAD_1       = 0x27
DLOAD_3       = 0x29
DLOAD         = 0x18   # wide form: followed by 1-byte local index
GETFIELD      = 0xB4   # followed by 2-byte CP index
PUTFIELD      = 0xB5
INVOKEVIRTUAL = 0xB6
INVOKESPECIAL = 0xB7
RETURN        = 0xB1
FRETURN       = 0xAE
IRETURN       = 0xAC
ARETURN       = 0xB0

def i2(idx):
    """Big-endian 2-byte index as a list of ints."""
    return [(idx >> 8) & 0xFF, idx & 0xFF]


# ── Minimal Java class file parser / patcher ─────────────────────────────────

class ClassPatcher:
    def __init__(self, data: bytes):
        self.data = data
        pos = 0

        magic, _minor, _major = struct.unpack_from('>IHH', data, pos)
        assert magic == 0xCAFEBABE, "Not a Java class file!"
        pos += 8

        # ── constant pool ──
        cp_count, = struct.unpack_from('>H', data, pos); pos += 2
        # cp[0] = None  (index 0 is unused by JVM spec)
        self.cp = [None]
        i = 1
        while i < cp_count:
            tag = data[pos]; pos += 1
            if tag == 1:          # Utf8
                n, = struct.unpack_from('>H', data, pos); pos += 2
                self.cp.append((1, data[pos:pos+n])); pos += n
            elif tag == 7:        # Class
                v, = struct.unpack_from('>H', data, pos); pos += 2
                self.cp.append((7, v))
            elif tag == 8:        # String
                v, = struct.unpack_from('>H', data, pos); pos += 2
                self.cp.append((8, v))
            elif tag in (9, 10, 11):  # Fieldref / Methodref / InterfaceMethodref
                a, b = struct.unpack_from('>HH', data, pos); pos += 4
                self.cp.append((tag, a, b))
            elif tag == 12:       # NameAndType
                a, b = struct.unpack_from('>HH', data, pos); pos += 4
                self.cp.append((12, a, b))
            elif tag in (3, 4):   # Integer / Float
                v, = struct.unpack_from('>I', data, pos); pos += 4
                self.cp.append((tag, v))
            elif tag in (5, 6):   # Long / Double  ← take TWO slots
                v, = struct.unpack_from('>Q', data, pos); pos += 8
                self.cp.append((tag, v))
                self.cp.append(None)   # second slot (no bytes in file)
                i += 1
            else:
                raise ValueError(f"Unknown constant pool tag {tag} at byte offset {pos-1}")
            i += 1

        self.cp_end_offset = pos   # first byte after the constant pool

        # ── skip access_flags, this_class, super_class, interfaces ──
        pos += 6
        icount, = struct.unpack_from('>H', data, pos); pos += 2 + 2 * icount

        # ── skip fields ──
        fcount, = struct.unpack_from('>H', data, pos); pos += 2
        for _ in range(fcount):
            pos += 6   # access_flags, name_index, descriptor_index
            ac, = struct.unpack_from('>H', data, pos); pos += 2
            for _ in range(ac):
                pos += 2   # attribute_name_index
                alen, = struct.unpack_from('>I', data, pos); pos += 4 + alen

        self.methods_count_offset = pos
        mcount, = struct.unpack_from('>H', data, pos); pos += 2
        self.orig_method_count = mcount
        for _ in range(mcount):
            pos += 6
            ac, = struct.unpack_from('>H', data, pos); pos += 2
            for _ in range(ac):
                pos += 2
                alen, = struct.unpack_from('>I', data, pos); pos += 4 + alen

        self.after_methods_offset = pos   # class attributes follow here

    # ── CP lookup helpers (return 0 = not found) ──

    def _utf8(self, s):
        b = s.encode('utf-8') if isinstance(s, str) else s
        for i, e in enumerate(self.cp):
            if e and e[0] == 1 and e[1] == b:
                return i
        return 0

    def _class(self, name):
        ni = self._utf8(name)
        if not ni: return 0
        for i, e in enumerate(self.cp):
            if e and e[0] == 7 and e[1] == ni:
                return i
        return 0

    def _nat(self, name, desc):
        ni = self._utf8(name); di = self._utf8(desc)
        if not ni or not di: return 0
        for i, e in enumerate(self.cp):
            if e and e[0] == 12 and e[1] == ni and e[2] == di:
                return i
        return 0

    def _fref(self, cls, name, desc):
        ci = self._class(cls); ni = self._nat(name, desc)
        if not ci or not ni: return 0
        for i, e in enumerate(self.cp):
            if e and e[0] == 9 and e[1] == ci and e[2] == ni:
                return i
        return 0

    def _mref(self, cls, name, desc):
        ci = self._class(cls); ni = self._nat(name, desc)
        if not ci or not ni: return 0
        for i, e in enumerate(self.cp):
            if e and e[0] == 10 and e[1] == ci and e[2] == ni:
                return i
        return 0

    # ── CP ensure helpers (find-or-create, always return valid index) ──

    def _eu(self, s):
        x = self._utf8(s)
        if x: return x
        self.cp.append((1, s.encode('utf-8'))); return len(self.cp)-1

    def _ec(self, name):
        x = self._class(name)
        if x: return x
        ni = self._eu(name); self.cp.append((7, ni)); return len(self.cp)-1

    def _en(self, name, desc):
        x = self._nat(name, desc)
        if x: return x
        ni = self._eu(name); di = self._eu(desc)
        self.cp.append((12, ni, di)); return len(self.cp)-1

    def _ef(self, cls, name, desc):
        x = self._fref(cls, name, desc)
        if x: return x
        ci = self._ec(cls); ni = self._en(name, desc)
        self.cp.append((9, ci, ni)); return len(self.cp)-1

    def _em(self, cls, name, desc):
        x = self._mref(cls, name, desc)
        if x: return x
        ci = self._ec(cls); ni = self._en(name, desc)
        self.cp.append((10, ci, ni)); return len(self.cp)-1

    # ── CP serialiser ──

    def _serialize_cp(self):
        out = struct.pack('>H', len(self.cp))   # count includes index-0 slot
        for e in self.cp[1:]:
            if e is None: continue              # Long/Double second slot — no bytes
            tag = e[0]
            out += bytes([tag])
            if   tag == 1:          out += struct.pack('>H', len(e[1])) + e[1]
            elif tag in (7, 8):     out += struct.pack('>H',  e[1])
            elif tag in (9,10,11,12): out += struct.pack('>HH', e[1], e[2])
            elif tag in (3, 4):     out += struct.pack('>I',  e[1])
            elif tag in (5, 6):     out += struct.pack('>Q',  e[1])
        return out

    # ── Method / Code builder ──

    def _code_attr(self, code_name_idx, max_stack, max_locals, bytecode: bytes):
        body  = struct.pack('>HHI', max_stack, max_locals, len(bytecode))
        body += bytecode
        body += struct.pack('>HH', 0, 0)   # no exceptions, no sub-attributes
        return struct.pack('>HI', code_name_idx, len(body)) + body

    def _method(self, acc, name_idx, desc_idx, code_attr: bytes):
        return struct.pack('>HHHH', acc, name_idx, desc_idx, 1) + code_attr

    # ── Main patch logic ──

    def build_new_methods(self):
        code_idx = self._eu("Code")

        # ── method references (mostly already in SPC's cp) ──
        m_f_      = self._em("gs", "f_",  "()V")
        m_bDDD    = self._em("gs", "b",   "(DDD)V")
        m_bF      = self._em("gs", "b",   "(F)V")
        m_R       = self._em("gs", "R",   "()V")
        m_bIII    = self._em("gs", "b",   "(III)Lcw;")
        m_aFF     = self._em("gs", "a",   "(F)F")
        m_aLln    = self._em("gs", "a",   "(Lln;)Z")

        # ── field references (all already in SPC's cp) ──
        f_ax  = self._ef("dc", "ax", "F")
        f_aw  = self._ef("dc", "aw", "F")
        f_az  = self._ef("dc", "az", "Z")
        f_bk  = self._ef("dc", "bk", "F")
        f_bo  = self._ef("dc", "bo", "F")
        f_bs  = self._ef("dc", "bs", "Ljava/util/Random;")
        f_u   = self._ef("dc", "u",  "Z")
        f_b   = self._ef("dc", "b",  "Lnet/minecraft/client/Minecraft;")

        ACC_PUBLIC = 0x0001

        def M(mname, mdesc, max_stack, max_locals, bc):
            ni  = self._eu(mname)
            di  = self._eu(mdesc)
            code = self._code_attr(code_idx, max_stack, max_locals, bytes(bc))
            return self._method(ACC_PUBLIC, ni, di, code)

        out = b''

        # 1. superUpdatePlayerActionState()V
        out += M("superUpdatePlayerActionState", "()V", 1, 1,
            [ALOAD_0, INVOKESPECIAL] + i2(m_f_) + [RETURN])

        # 2. superMoveEntity(DDD)V
        out += M("superMoveEntity", "(DDD)V", 7, 7,
            [ALOAD_0, DLOAD_1, DLOAD_3, DLOAD, 5,
             INVOKESPECIAL] + i2(m_bDDD) + [RETURN])

        # 3. superSleepInBedAt(III)Lcw;
        out += M("superSleepInBedAt", "(III)Lcw;", 4, 4,
            [ALOAD_0, ILOAD_1, ILOAD_2, ILOAD_3,
             INVOKESPECIAL] + i2(m_bIII) + [ARETURN])

        # 4. superGetEntityBrightness(F)F
        out += M("superGetEntityBrightness", "(F)F", 2, 2,
            [ALOAD_0, FLOAD_1, INVOKESPECIAL] + i2(m_aFF) + [FRETURN])

        # 5. superIsInsideOfMaterial(Lln;)Z
        out += M("superIsInsideOfMaterial", "(Lln;)Z", 2, 2,
            [ALOAD_0, ALOAD_1, INVOKESPECIAL] + i2(m_aLln) + [IRETURN])

        # 6. setMoveForward(F)V
        out += M("setMoveForward", "(F)V", 2, 2,
            [ALOAD_0, FLOAD_1, PUTFIELD] + i2(f_ax) + [RETURN])

        # 7. setMoveStrafing(F)V
        out += M("setMoveStrafing", "(F)V", 2, 2,
            [ALOAD_0, FLOAD_1, PUTFIELD] + i2(f_aw) + [RETURN])

        # 8. setIsJumping(Z)V
        out += M("setIsJumping", "(Z)V", 2, 2,
            [ALOAD_0, ILOAD_1, PUTFIELD] + i2(f_az) + [RETURN])

        # 9. setActionState(FFZ)V   (this=0, f1=1, f2=2, b=3)
        out += M("setActionState", "(FFZ)V", 2, 4,
            [ALOAD_0, FLOAD_1, PUTFIELD] + i2(f_aw) +
            [ALOAD_0, FLOAD_2, PUTFIELD] + i2(f_ax) +
            [ALOAD_0, ILOAD_3, PUTFIELD] + i2(f_az) +
            [RETURN])

        # 10. doFall(F)V
        out += M("doFall", "(F)V", 2, 2,
            [ALOAD_0, FLOAD_1, INVOKESPECIAL] + i2(m_bF) + [RETURN])

        # 11. getFallDistance()F
        out += M("getFallDistance", "()F", 1, 1,
            [ALOAD_0, GETFIELD] + i2(f_bk) + [FRETURN])

        # 12. getSleeping()Z
        out += M("getSleeping", "()Z", 1, 1,
            [ALOAD_0, GETFIELD] + i2(f_u) + [IRETURN])

        # 13. getJumping()Z
        out += M("getJumping", "()Z", 1, 1,
            [ALOAD_0, GETFIELD] + i2(f_az) + [IRETURN])

        # 14. doJump()V  — invokevirtual so dynamic dispatch works if dc overrides R()
        out += M("doJump", "()V", 1, 1,
            [ALOAD_0, INVOKEVIRTUAL] + i2(m_R) + [RETURN])

        # 15. getRandom()Ljava/util/Random;
        out += M("getRandom", "()Ljava/util/Random;", 1, 1,
            [ALOAD_0, GETFIELD] + i2(f_bs) + [ARETURN])

        # 16. setFallDistance(F)V
        out += M("setFallDistance", "(F)V", 2, 2,
            [ALOAD_0, FLOAD_1, PUTFIELD] + i2(f_bk) + [RETURN])

        # 17. setYSize(F)V
        out += M("setYSize", "(F)V", 2, 2,
            [ALOAD_0, FLOAD_1, PUTFIELD] + i2(f_bo) + [RETURN])

        # 18. getMc()Lnet/minecraft/client/Minecraft;
        out += M("getMc", "()Lnet/minecraft/client/Minecraft;", 1, 1,
            [ALOAD_0, GETFIELD] + i2(f_b) + [ARETURN])

        print(f"  Constant pool entries: {len(self.cp)-1} (was {self.orig_cp_size-1})")
        return out

    def assemble(self, new_methods: bytes, n_new: int = 18) -> bytes:
        new_cp    = self._serialize_cp()
        header    = self.data[:8]
        between   = self.data[self.cp_end_offset : self.methods_count_offset]
        new_mc    = struct.pack('>H', self.orig_method_count + n_new)
        old_mdata = self.data[self.methods_count_offset+2 : self.after_methods_offset]
        tail      = self.data[self.after_methods_offset:]
        return header + new_cp + between + new_mc + old_mdata + new_methods + tail

    # Store original CP size for reporting
    @property
    def orig_cp_size(self):
        count, = struct.unpack_from('>H', self.data, 8)
        return count


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    if not os.path.isfile(JAR_PATH):
        print(f"ERROR: JAR not found at:\n  {JAR_PATH}")
        sys.exit(1)

    print(f"[1/5] Backing up JAR ...")
    shutil.copy2(JAR_PATH, BACKUP)
    print(f"      Backup: {BACKUP}")

    print(f"[2/5] Extracting dc.class ...")
    with zipfile.ZipFile(JAR_PATH, 'r') as z:
        if DC_ENTRY not in z.namelist():
            print(f"ERROR: {DC_ENTRY} not found inside JAR!")
            sys.exit(1)
        dc_data = z.read(DC_ENTRY)
    print(f"      dc.class: {len(dc_data)} bytes")

    print(f"[3/5] Parsing class file ...")
    patcher = ClassPatcher(dc_data)
    print(f"      Methods: {patcher.orig_method_count}, CP entries: {patcher.orig_cp_size-1}")

    if patcher._utf8("superUpdatePlayerActionState"):
        print("\ndc.class already contains 'superUpdatePlayerActionState'.")
        print("Looks like it's already been patched — nothing to do!")
        return

    print(f"[4/5] Building 18 bridge methods ...")
    new_methods = patcher.build_new_methods()
    patched     = patcher.assemble(new_methods)
    print(f"      Patched dc.class: {len(patched)} bytes (+{len(patched)-len(dc_data)})")

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
    print("Done! SmartMoving bridge methods added.")
    print("You can now launch Minecraft — SmartMoving should work!")
    print()
    print("If something goes wrong, restore the backup:")
    print(f"  copy \"{BACKUP}\" \"{JAR_PATH}\"")


if __name__ == "__main__":
    main()
