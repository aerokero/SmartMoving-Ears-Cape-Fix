#!/usr/bin/env python3
import struct, zipfile, io, os, shutil

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_modelplayer"
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

def main():
    print(f"Backing up {SM_ZIP}...")
    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Backup saved to: {BACKUP}")
    else:
        print("Backup already exists.")

    # Read zip
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        class_data = z.read(ENTRY)

    rewriter = ClassRewriter(class_data)

    # Find name index of "<init>" and descriptor index of "(FIILnet/minecraft/move/SmartMovingRender;)V"
    init_name_idx = rewriter.get_utf8_idx(b"<init>")
    init_desc_idx = rewriter.get_utf8_idx(b"(FIILnet/minecraft/move/SmartMovingRender;)V")
    assert init_name_idx and init_desc_idx

    # Find constructor method
    target_method = None
    for m in rewriter.methods:
        if m['name_idx'] == init_name_idx and m['desc_idx'] == init_desc_idx:
            target_method = m
            break

    assert target_method is not None, "ModelPlayer constructor not found"
    print("Found ModelPlayer constructor")

    # Add required new CP entries
    m_set_height = rewriter.em(b"farn/ears_compat/EarSkinCompat", b"setForceTextureHeight", b"(Z)V")
    print(f"EarSkinCompat.setForceTextureHeight Methodref: #{m_set_height}")

    # Patch the Code attribute of target_method
    for attr_idx, (name_idx, attr_body) in enumerate(target_method['attrs']):
        name = rewriter.cp[name_idx][1]
        if name == b"Code":
            max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
            print(f"Original Code: max_stack={max_stack}, max_locals={max_locals}, code_len={code_len}")
            
            orig_code = attr_body[8 : 8+code_len]
            
            # Verify the start of the constructor (offset 0-5)
            # aload_0 (2A), fload_1 (23), fconst_0 (0B), invokespecial #3 (B7 00 03)
            # invokespecial is B7, followed by 2 bytes
            assert orig_code[0] == 0x2A and orig_code[1] == 0x23 and orig_code[2] == 0x0B and orig_code[3] == 0xB7
            print("Constructor start verified")
            
            # Let's perform the bytecode modifications:
            # 1. Start injection (4 bytes) at offset 6:
            #    iconst_1 (0x04)
            #    invokestatic m_set_height (0xB8, high, low)
            start_inj = bytes([0x04, 0xB8, (m_set_height >> 8) & 0xFF, m_set_height & 0xFF])
            
            # 2. Swap texture offsets of left arm (e) at original offsets 324 and 326:
            #    Original: bipush 40 (10 28), bipush 16 (10 10)
            #    Patched:  bipush 32 (10 20), bipush 48 (10 30)
            #    We check if the original bytes at 324 and 326 are indeed 10 28 and 10 10:
            assert orig_code[324:328] == bytes([0x10, 0x28, 0x10, 0x10]), f"Left arm offsets mismatch: {orig_code[324:328].hex()}"
            print("Left arm offsets verified")
            
            # 3. Swap texture offsets of left leg (g) at original offsets 437 and 438:
            #    Original: iconst_0 (0x03), bipush 16 (10 10)
            #    Patched:  bipush 16 (10 10), bipush 48 (10 30)
            #    We check if the original bytes at 437 and 438 are indeed 03 and 10 10:
            assert orig_code[437:440] == bytes([0x03, 0x10, 0x10]), f"Left leg offsets mismatch: {orig_code[437:440].hex()}"
            print("Left leg offsets verified")
            
            # Let's build the modified code array:
            # Part A: orig_code[0:6] (the super constructor call)
            part_a = orig_code[0:6]
            
            # Part B: our start injection (4 bytes)
            part_b = start_inj
            
            # Part C: orig_code[6:324]
            part_c = orig_code[6:324]
            
            # Part D: patched left arm offsets (4 bytes)
            part_d = bytes([0x10, 0x20, 0x10, 0x30])
            
            # Part E: orig_code[328:437]
            part_e = orig_code[328:437]
            
            # Part F: patched left leg offsets (4 bytes)
            part_f = bytes([0x10, 0x10, 0x10, 0x30])
            
            # Part G: orig_code[440:512]
            part_g = orig_code[440:512]
            
            # Part H: end injection (4 bytes) at end:
            #    iconst_0 (0x03)
            #    invokestatic m_set_height (0xB8, high, low)
            part_h = bytes([0x03, 0xB8, (m_set_height >> 8) & 0xFF, m_set_height & 0xFF])
            
            # Part I: the final return (0xB1)
            part_i = bytes([0xB1])
            
            new_code = part_a + part_b + part_c + part_d + part_e + part_f + part_g + part_h + part_i
            new_code_len = len(new_code)
            
            # Verify new code len is 522
            assert new_code_len == 522, f"Expected 522, got {new_code_len}"
            print("New code size is exactly 522 bytes (+9)")
            
            # Sub-attributes of Code (LineNumberTable, LocalVariableTable)
            # No StackMapTable exists for this method
            et_pos = 8 + code_len
            et_len = struct.unpack_from('>H', attr_body, et_pos)[0]
            assert et_len == 0
            
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
                        start_pc = struct.unpack_from('>H', sa_body, p_lnt)[0]
                        if start_pc <= 6:
                            pass
                        elif start_pc <= 437:
                            struct.pack_into('>H', sa_body, p_lnt, start_pc + 4)
                        else:
                            struct.pack_into('>H', sa_body, p_lnt, start_pc + 5)
                        p_lnt += 4
                    print(f"Shifted LineNumberTable ({lnt_len} entries)")
                elif sa_name == b"LocalVariableTable":
                    lvt_len = struct.unpack_from('>H', sa_body, 0)[0]
                    p_lvt = 2
                    for _ in range(lvt_len):
                        start_pc, length = struct.unpack_from('>HH', sa_body, p_lvt)
                        if start_pc == 0:
                            struct.pack_into('>H', sa_body, p_lvt + 2, length + 9)
                        else:
                            if start_pc <= 6:
                                if start_pc + length > 437:
                                    struct.pack_into('>H', sa_body, p_lvt + 2, length + 9)
                                else:
                                    struct.pack_into('>H', sa_body, p_lvt + 2, length + 4)
                            elif start_pc <= 437:
                                struct.pack_into('>H', sa_body, p_lvt, start_pc + 4)
                                if start_pc + length > 437:
                                    struct.pack_into('>H', sa_body, p_lvt + 2, length + 5)
                            else:
                                struct.pack_into('>H', sa_body, p_lvt, start_pc + 5)
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

    # Rebuild class file
    patched_class = rewriter.rebuild()
    print(f"Patched class file size: {len(patched_class)} (was {len(class_data)})")

    # Write back to zip
    buf = io.BytesIO()
    with zipfile.ZipFile(SM_ZIP, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, patched_class)
                    print(f"Replaced {ENTRY} in zip")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(SM_ZIP, 'wb') as f:
        f.write(buf.getvalue())

    print("\nDone! Verified output with javap:")
    # Verify with javap
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".class", delete=False) as tmp:
        tmp.write(patched_class)
        tmp_name = tmp.name

    try:
        res = subprocess.run(["javap", "-c", "-p", tmp_name], capture_output=True, text=True)
        # Find constructor method in output
        lines = res.stdout.splitlines()
        found_m = False
        for idx, line in enumerate(lines):
            if "public net.minecraft.move.ModelPlayer(float, int, int," in line:
                found_m = True
                print("\n".join(lines[idx:idx+45]))
                break
    finally:
        os.unlink(tmp_name)

if __name__ == '__main__':
    main()
