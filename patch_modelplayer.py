#!/usr/bin/env python3
import struct, zipfile, io, os, shutil

TARGET_ZIPS = [
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\Armorstand Player fix forge patch.zip",
]
ENTRY  = "net/minecraft/move/ModelPlayer.class"

class ClassRewriter:
    def __init__(self, data: bytes):
        self.data = data
        pos = 0
        
        magic, minor, major = struct.unpack_from('>IHH', data, pos)
        assert magic == 0xCAFEBABE, "Not a class file"
        self.minor = minor
        self.major = major
        pos += 8
        
        # Parse CP
        cp_count, = struct.unpack_from('>H', data, pos)
        pos += 2
        self.cp = [None]
        i = 1
        while i < cp_count:
            tag = data[pos]
            start = pos
            pos += 1
            if tag == 1: # Utf8
                n, = struct.unpack_from('>H', data, pos); pos += 2
                self.cp.append((1, data[pos:pos+n])); pos += n
                i += 1
            elif tag in (7, 8): # Class, String
                v, = struct.unpack_from('>H', data, pos); pos += 2
                self.cp.append((tag, v))
                i += 1
            elif tag in (9, 10, 11, 12): # Field, Method, InterfaceMethod, NameAndType
                a, b = struct.unpack_from('>HH', data, pos); pos += 4
                self.cp.append((tag, a, b))
                i += 1
            elif tag in (3, 4): # Integer, Float
                v, = struct.unpack_from('>I', data, pos); pos += 4
                self.cp.append((tag, v))
                i += 1
            elif tag in (5, 6): # Long, Double
                v, = struct.unpack_from('>Q', data, pos); pos += 8
                self.cp.append((tag, v))
                self.cp.append(None)
                i += 2
            else:
                raise ValueError(f"Unknown CP tag {tag}")
                
        # Header bytes after CP: access_flags, this, super, interfaces
        self.header_start = pos
        pos += 6 # access, this, super
        icount, = struct.unpack_from('>H', data, pos); pos += 2
        pos += icount * 2
        self.header_end = pos
        
        # Fields
        fcount, = struct.unpack_from('>H', data, pos)
        pos += 2
        for _ in range(fcount):
            pos += 6
            ac, = struct.unpack_from('>H', data, pos); pos += 2
            for _ in range(ac):
                pos += 2
                alen, = struct.unpack_from('>I', data, pos); pos += 4 + alen
        self.fields_end = pos
        
        # Methods
        mcount, = struct.unpack_from('>H', data, pos)
        pos += 2
        self.methods = []
        for _ in range(mcount):
            m_access, m_name, m_desc, m_ac = struct.unpack_from('>HHHH', data, pos)
            m_start = pos
            pos += 8
            attrs = []
            for _ in range(m_ac):
                attr_name_idx, attr_len = struct.unpack_from('>HI', data, pos)
                pos += 6
                attr_body = data[pos:pos+attr_len]
                attrs.append((attr_name_idx, attr_body))
                pos += attr_len
            self.methods.append({
                'access': m_access,
                'name_idx': m_name,
                'desc_idx': m_desc,
                'attrs': attrs
            })
        self.after_methods_offset = pos

    def get_utf8_idx(self, val: bytes):
        for idx, entry in enumerate(self.cp):
            if entry and entry[0] == 1 and entry[1] == val:
                return idx
        return 0

    def get_class_idx(self, name_bytes: bytes):
        utf_idx = self.get_utf8_idx(name_bytes)
        if not utf_idx: return 0
        for idx, entry in enumerate(self.cp):
            if entry and entry[0] == 7 and entry[1] == utf_idx:
                return idx
        return 0

    def get_nat_idx(self, name: bytes, desc: bytes):
        n_idx = self.get_utf8_idx(name)
        d_idx = self.get_utf8_idx(desc)
        if not n_idx or not d_idx: return 0
        for idx, entry in enumerate(self.cp):
            if entry and entry[0] == 12 and entry[1] == n_idx and entry[2] == d_idx:
                return idx
        return 0

    # Ensure entries exist
    def eu(self, val: bytes):
        idx = self.get_utf8_idx(val)
        if idx: return idx
        self.cp.append((1, val))
        return len(self.cp) - 1

    def ec(self, name: bytes):
        idx = self.get_class_idx(name)
        if idx: return idx
        n_idx = self.eu(name)
        self.cp.append((7, n_idx))
        return len(self.cp) - 1

    def en(self, name: bytes, desc: bytes):
        idx = self.get_nat_idx(name, desc)
        if idx: return idx
        n_idx = self.eu(name)
        d_idx = self.eu(desc)
        self.cp.append((12, n_idx, d_idx))
        return len(self.cp) - 1

    def em(self, cls: bytes, name: bytes, desc: bytes):
        # find methodref
        c_idx = self.ec(cls)
        n_idx = self.en(name, desc)
        for idx, entry in enumerate(self.cp):
            if entry and entry[0] == 10 and entry[1] == c_idx and entry[2] == n_idx:
                return idx
        self.cp.append((10, c_idx, n_idx))
        return len(self.cp) - 1

    def serialize_cp(self) -> bytes:
        out = struct.pack('>H', len(self.cp))
        for e in self.cp[1:]:
            if e is None: continue
            tag = e[0]
            out += bytes([tag])
            if tag == 1:
                out += struct.pack('>H', len(e[1])) + e[1]
            elif tag in (7, 8):
                out += struct.pack('>H', e[1])
            elif tag in (9, 10, 11, 12):
                out += struct.pack('>HH', e[1], e[2])
            elif tag in (3, 4):
                out += struct.pack('>I', e[1])
            elif tag in (5, 6):
                out += struct.pack('>Q', e[1])
        return out

    def rebuild(self) -> bytes:
        header = self.data[:8]
        cp_bytes = self.serialize_cp()
        header_etc = self.data[self.header_start : self.fields_end]
        
        # Serialize methods
        methods_bytes = struct.pack('>H', len(self.methods))
        for m in self.methods:
            methods_bytes += struct.pack('>HHHH', m['access'], m['name_idx'], m['desc_idx'], len(m['attrs']))
            for attr_name_idx, attr_body in m['attrs']:
                methods_bytes += struct.pack('>HI', attr_name_idx, len(attr_body)) + attr_body
                
        tail = self.data[self.after_methods_offset:]
        return header + cp_bytes + header_etc + methods_bytes + tail

def shift_pc(pc):
    """Map original bytecode offset to new offset after all patches."""
    if pc < 6:    return pc
    elif pc < 324: return pc + 5
    elif pc < 328: return pc + 9   # inside arm UV replacement
    elif pc < 346: return pc + 9
    elif pc < 347: return pc + 12  # inside arm mirror replacement
    elif pc < 437: return pc + 12
    elif pc < 440: return pc + 17  # inside leg UV replacement
    elif pc < 458: return pc + 17
    elif pc < 459: return pc + 20  # inside leg mirror replacement
    else:          return pc + 20


def patch_zip(zip_path):
    backup = zip_path + ".backup_modelplayer"
    print(f"\n=== Patching: {zip_path} ===")
    if not os.path.exists(backup):
        shutil.copy2(zip_path, backup)
        print(f"Backup -> {backup}")
    else:
        print(f"Using existing backup: {backup}")

    # Always read from backup so script is safely re-runnable
    with zipfile.ZipFile(backup, 'r') as z:
        class_data = z.read(ENTRY)

    rewriter = ClassRewriter(class_data)

    init_name_idx = rewriter.get_utf8_idx(b"<init>")
    init_desc_idx = rewriter.get_utf8_idx(b"(FIILnet/minecraft/move/SmartMovingRender;)V")
    assert init_name_idx and init_desc_idx

    target_method = None
    for m in rewriter.methods:
        if m['name_idx'] == init_name_idx and m['desc_idx'] == init_desc_idx:
            target_method = m
            break

    assert target_method is not None, "ModelPlayer constructor not found"
    print("Found ModelPlayer constructor")

    # CP entries — scale-aware helpers in EarSkinCompat
    ESC = b"farn/ears_compat/EarSkinCompat"
    m_height_cond = rewriter.em(ESC, b"setForceHeightConditional", b"(ZF)V")
    m_arm_x       = rewriter.em(ESC, b"getLeftArmX",      b"(F)I")
    m_arm_y       = rewriter.em(ESC, b"getLeftArmY",      b"(F)I")
    m_leg_x       = rewriter.em(ESC, b"getLeftLegX",      b"(F)I")
    m_leg_y       = rewriter.em(ESC, b"getLeftLegY",      b"(F)I")
    m_mirror      = rewriter.em(ESC, b"getLeftLimbMirror", b"(F)Z")
    print(f"  setForceHeightConditional: #{m_height_cond}")
    print(f"  getLeftArmX/Y:             #{m_arm_x}/#{m_arm_y}")
    print(f"  getLeftLegX/Y:             #{m_leg_x}/#{m_leg_y}")
    print(f"  getLeftLimbMirror:         #{m_mirror}")

    def hi(idx): return (idx >> 8) & 0xFF
    def lo(idx): return idx & 0xFF

    for attr_idx, (name_idx, attr_body) in enumerate(target_method['attrs']):
        name = rewriter.cp[name_idx][1]
        if name == b"Code":
            max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
            print(f"Original Code: max_stack={max_stack}, max_locals={max_locals}, code_len={code_len}")

            orig_code = attr_body[8 : 8+code_len]

            assert orig_code[0] == 0x2A and orig_code[1] == 0x23 and orig_code[2] == 0x0B and orig_code[3] == 0xB7, \
                "Constructor start mismatch"
            print("Constructor start verified")

            assert orig_code[324:328] == bytes([0x10, 0x28, 0x10, 0x10]), \
                f"Left arm UV mismatch: {orig_code[324:328].hex()}"
            print("Left arm UV verified (40,16)")

            assert orig_code[346] == 0x04, f"Left arm mirror mismatch: {orig_code[346]:02x}"
            print("Left arm mirror flag verified (iconst_1)")

            assert orig_code[437:440] == bytes([0x03, 0x10, 0x10]), \
                f"Left leg UV mismatch: {orig_code[437:440].hex()}"
            print("Left leg UV verified (0,16)")

            assert orig_code[458] == 0x04, f"Left leg mirror mismatch: {orig_code[458]:02x}"
            print("Left leg mirror flag verified (iconst_1)")

            # fload_1 = 0x23 (loads scale parameter, local var slot 1)
            FLOAD1 = 0x23

            # Start injection (5 bytes): setForceHeightConditional(true, scale)
            part_b = bytes([0x04, FLOAD1, 0xB8, hi(m_height_cond), lo(m_height_cond)])

            # Left arm UV (8 bytes): getLeftArmX(scale), getLeftArmY(scale)
            part_d = bytes([FLOAD1, 0xB8, hi(m_arm_x), lo(m_arm_x),
                            FLOAD1, 0xB8, hi(m_arm_y), lo(m_arm_y)])

            # Left arm mirror (4 bytes): getLeftLimbMirror(scale)
            part_em = bytes([FLOAD1, 0xB8, hi(m_mirror), lo(m_mirror)])

            # Left leg UV (8 bytes): getLeftLegX(scale), getLeftLegY(scale)
            part_f = bytes([FLOAD1, 0xB8, hi(m_leg_x), lo(m_leg_x),
                            FLOAD1, 0xB8, hi(m_leg_y), lo(m_leg_y)])

            # Left leg mirror (4 bytes): getLeftLimbMirror(scale)
            part_fm = bytes([FLOAD1, 0xB8, hi(m_mirror), lo(m_mirror)])

            # End injection (5 bytes): setForceHeightConditional(false, scale)
            part_h = bytes([0x03, FLOAD1, 0xB8, hi(m_height_cond), lo(m_height_cond)])

            new_code = (
                orig_code[0:6]    +  # super() call (6)
                part_b            +  # start injection (5)
                orig_code[6:324]  +  # body up to left arm UV (318)
                part_d            +  # left arm UV call (8)
                orig_code[328:346]+  # arm ctor + field store (18)
                part_em           +  # left arm mirror call (4)
                orig_code[347:437]+  # putfield mirror + box + right leg (90)
                part_f            +  # left leg UV call (8)
                orig_code[440:458]+  # leg ctor + field store (18)
                part_fm           +  # left leg mirror call (4)
                orig_code[459:512]+  # putfield mirror + remaining fields (53)
                part_h            +  # end injection (5)
                bytes([0xB1])        # return (1)
            )
            new_code_len = len(new_code)

            # 6+5+318+8+18+4+90+8+18+4+53+5+1 = 538
            assert new_code_len == 538, f"Expected 538, got {new_code_len}"
            print(f"New code size: {new_code_len} bytes (+{new_code_len - code_len} from original)")

            et_pos = 8 + code_len
            et_len = struct.unpack_from('>H', attr_body, et_pos)[0]
            assert et_len == 0, f"Unexpected exception entries: {et_len}"

            p_sub = et_pos + 2
            sub_ac = struct.unpack_from('>H', attr_body, p_sub)[0]
            p_sub += 2

            new_sub_attrs = bytearray()
            for _ in range(sub_ac):
                sa_name_idx, sa_len = struct.unpack_from('>HI', attr_body, p_sub)
                sa_name = rewriter.cp[sa_name_idx][1]
                sa_body = bytearray(attr_body[p_sub+6 : p_sub+6+sa_len])

                if sa_name == b"LineNumberTable":
                    lnt_len = struct.unpack_from('>H', sa_body, 0)[0]
                    p_lnt = 2
                    for _ in range(lnt_len):
                        spc = struct.unpack_from('>H', sa_body, p_lnt)[0]
                        struct.pack_into('>H', sa_body, p_lnt, shift_pc(spc))
                        p_lnt += 4
                    print(f"Shifted LineNumberTable ({lnt_len} entries)")
                elif sa_name == b"LocalVariableTable":
                    lvt_len = struct.unpack_from('>H', sa_body, 0)[0]
                    p_lvt = 2
                    for _ in range(lvt_len):
                        spc, slen = struct.unpack_from('>HH', sa_body, p_lvt)
                        new_spc = shift_pc(spc)
                        # end offset = first byte NOT in range; shift it too
                        new_end = shift_pc(spc + slen) if spc + slen <= 513 else new_code_len
                        struct.pack_into('>H', sa_body, p_lvt, new_spc)
                        struct.pack_into('>H', sa_body, p_lvt + 2, new_end - new_spc)
                        p_lvt += 10
                    print(f"Shifted LocalVariableTable ({lvt_len} entries)")

                new_sub_attrs += struct.pack('>HI', sa_name_idx, len(sa_body)) + sa_body
                p_sub += 6 + sa_len

            new_attr_body = struct.pack('>HHI', max_stack, max_locals, new_code_len)
            new_attr_body += new_code
            new_attr_body += struct.pack('>H', 0)
            new_attr_body += struct.pack('>H', sub_ac)
            new_attr_body += new_sub_attrs

            target_method['attrs'][attr_idx] = (name_idx, new_attr_body)
            break

    patched_class = rewriter.rebuild()
    print(f"Patched class size: {len(patched_class)} (was {len(class_data)})")

    buf = io.BytesIO()
    with zipfile.ZipFile(zip_path, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, patched_class)
                    print(f"Replaced {ENTRY} in zip")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(zip_path, 'wb') as f:
        f.write(buf.getvalue())

    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".class", delete=False) as tmp:
        tmp.write(patched_class)
        tmp_name = tmp.name

    try:
        res = subprocess.run(["javap", "-c", "-p", tmp_name], capture_output=True, text=True)
        lines = res.stdout.splitlines()
        for idx, line in enumerate(lines):
            if "public net.minecraft.move.ModelPlayer(float, int, int," in line:
                print("\n".join(lines[idx:idx+20]))
                break
    finally:
        os.unlink(tmp_name)


def main():
    for zip_path in TARGET_ZIPS:
        patch_zip(zip_path)
    print("\nAll zips patched.")

if __name__ == '__main__':
    main()
