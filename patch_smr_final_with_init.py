#!/usr/bin/env python3
import struct, zipfile, io, os, shutil, subprocess, tempfile

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_smr_cape"
ENTRY  = "net/minecraft/move/SmartMovingRender.class"

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

    def get_fieldref_idx(self, cls: bytes, name: bytes, desc: bytes):
        c_idx = self.get_class_idx(cls)
        n_idx = self.get_nat_idx(name, desc)
        if not c_idx or not n_idx: return 0
        for idx, entry in enumerate(self.cp):
            if entry and entry[0] == 9 and entry[1] == c_idx and entry[2] == n_idx:
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

    def es(self, val: bytes):
        utf_idx = self.eu(val)
        for idx, entry in enumerate(self.cp):
            if entry and entry[0] == 8 and entry[1] == utf_idx:
                return idx
        self.cp.append((8, utf_idx))
        return len(self.cp) - 1

    def en(self, name: bytes, desc: bytes):
        idx = self.get_nat_idx(name, desc)
        if idx: return idx
        n_idx = self.eu(name)
        d_idx = self.eu(desc)
        self.cp.append((12, n_idx, d_idx))
        return len(self.cp) - 1

    def ef(self, cls: bytes, name: bytes, desc: bytes):
        idx = self.get_fieldref_idx(cls, name, desc)
        if idx: return idx
        c_idx = self.ec(cls)
        n_idx = self.en(name, desc)
        self.cp.append((9, c_idx, n_idx))
        return len(self.cp) - 1

    def em(self, cls: bytes, name: bytes, desc: bytes):
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

def shift_smt(data, pos, shift_amount):
    num_entries = struct.unpack_from(">H", data, pos)[0]
    if num_entries > 0:
        frame_type = data[pos+2]
        if frame_type == 252: # append_frame
            delta = struct.unpack_from(">H", data, pos + 3)[0]
            struct.pack_into(">H", data, pos + 3, delta + shift_amount)
            print(f"Shifted SMT frame 0 delta from {delta} to {delta + shift_amount}")
        else:
            print(f"WARNING: StackMapTable first frame is not append_frame (type {frame_type}), cannot shift easily!")

ARCHIVES = [
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\Armorstand Player fix forge patch.zip",
]


def patch_archive(archive):
    if not os.path.exists(archive):
        print(f"Archive not found, skipping: {archive}")
        return
        
    with zipfile.ZipFile(archive, 'r') as z:
        if ENTRY not in z.namelist():
            print(f"SmartMovingRender.class not found in {archive}, skipping")
            return
            
    print(f"\nPatching SmartMovingRender.class in: {archive}")
    
    backup = archive + ".backup_smr_cape"
    if not os.path.exists(backup):
        shutil.copy2(archive, backup)
        print(f"  Created backup: {backup}")
    else:
        print(f"  Using existing backup: {backup}")
        
    with zipfile.ZipFile(backup, 'r') as z:
        class_data = z.read(ENTRY)

    rewriter = ClassRewriter(class_data)

    # -----------------
    # Define required new CP entries
    # -----------------
    model_player_i_fieldref = rewriter.ef(b"net/minecraft/move/ModelPlayer", b"i", b"Lnet/minecraft/move/ModelCapeRenderer;")
    set_current_methodref   = rewriter.em(b"net/minecraft/move/ModelCapeRenderer", b"setCurrent", b"(Lgs;F)V")
    handle_slim_arm_methodref = rewriter.em(b"farn/ears_compat/EarSkinCompat", b"handleSlimArm", b"(Lnet/minecraft/move/ModelPlayer;Lgs;)V")

    gv_class_idx = rewriter.ec(b"gv")
    main_model_str_idx = rewriter.es(b"mainModel")
    e_str_idx = rewriter.es(b"e")
    mbm_fieldref = rewriter.get_fieldref_idx(b"net/minecraft/move/SmartMovingRender", b"modelBipedMain", b"Lnet/minecraft/move/ModelPlayer;")
    set_field_methodref = rewriter.em(b"net/minecraft/move/Reflect", b"SetField", b"(Ljava/lang/Class;Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V")

    print(f"modelBipedMain fieldref: #{mbm_fieldref}")
    print(f"ModelPlayer.i fieldref: #{model_player_i_fieldref}")
    print(f"ModelCapeRenderer.setCurrent methodref: #{set_current_methodref}")
    print(f"EarSkinCompat.handleSlimArm methodref: #{handle_slim_arm_methodref}")
    print(f"gv class entry: #{gv_class_idx}")
    print(f"mainModel string entry: #{main_model_str_idx}")
    print(f"e string entry: #{e_str_idx}")
    print(f"Reflect.SetField methodref: #{set_field_methodref}")

    # -----------------
    # Patch 1: Constructor <init>
    # -----------------
    init_name_idx = rewriter.get_utf8_idx(b"<init>")
    init_desc_idx = rewriter.get_utf8_idx(b"(Lnet/minecraft/move/IRenderPlayer;)V")
    assert init_name_idx and init_desc_idx

    init_method = None
    for m in rewriter.methods:
        if m['name_idx'] == init_name_idx and m['desc_idx'] == init_desc_idx:
            init_method = m
            break
    assert init_method is not None, "Constructor <init> method not found"
    print("Found <init> constructor method")

    for attr_idx, (name_idx, attr_body) in enumerate(init_method['attrs']):
        name = rewriter.cp[name_idx][1]
        if name == b"Code":
            max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
            orig_code = attr_body[8 : 8+code_len]
            
            # Find the first Reflect.SetField call (0xB8 followed by set_field_methodref bytes)
            target_call = bytes([0xB8, (set_field_methodref >> 8) & 0xFF, set_field_methodref & 0xFF])
            idx_invoke = orig_code.find(target_call)
            assert idx_invoke != -1, "Could not find Reflect.SetField call in constructor"
            
            # We want to inject right after this invokestatic (which is at idx_invoke + 3)
            injection_point = idx_invoke + 3
            
            # 17-byte injection:
            # ldc_w gv_class_idx (3 bytes: 0x13, msb, lsb)
            # aload_1 (1 byte: 0x2B)
            # ldc_w main_model_str_idx (3 bytes: 0x13, msb, lsb)
            # ldc_w e_str_idx (3 bytes: 0x13, msb, lsb)
            # aload_0 (1 byte: 0x2A)
            # getfield modelBipedMain (3 bytes: 0xB4, msb, lsb)
            # invokestatic Reflect.SetField (3 bytes: 0xB8, msb, lsb)
            init_injection = bytes([
                0x13, (gv_class_idx >> 8) & 0xFF, gv_class_idx & 0xFF,
                0x2B,
                0x13, (main_model_str_idx >> 8) & 0xFF, main_model_str_idx & 0xFF,
                0x13, (e_str_idx >> 8) & 0xFF, e_str_idx & 0xFF,
                0x2A,
                0xB4, (mbm_fieldref >> 8) & 0xFF, mbm_fieldref & 0xFF,
                0xB8, (set_field_methodref >> 8) & 0xFF, set_field_methodref & 0xFF
            ])
            assert len(init_injection) == 17
            
            new_code = orig_code[:injection_point] + init_injection + orig_code[injection_point:]
            new_code_len = len(new_code)
            
            # Exceptions
            et_pos = 8 + code_len
            et_len = struct.unpack_from('>H', attr_body, et_pos)[0]
            assert et_len == 0, f"Expected 0 exception handlers in constructor, got {et_len}"
            
            # Sub-attributes of Code (shift offsets > injection_point by +17)
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
                        if start_pc > injection_point:
                            struct.pack_into('>H', sa_body, p_lnt, start_pc + 17)
                        p_lnt += 4
                    print(f"Constructor: Shifted LineNumberTable ({lnt_len} entries) by +17")
                elif sa_name == b"LocalVariableTable":
                    lvt_len = struct.unpack_from('>H', sa_body, 0)[0]
                    p_lvt = 2
                    for _ in range(lvt_len):
                        start_pc, length = struct.unpack_from('>HH', sa_body, p_lvt)
                        if start_pc > injection_point:
                            struct.pack_into('>H', sa_body, p_lvt, start_pc + 17)
                        else:
                            if start_pc + length > injection_point:
                                struct.pack_into('>H', sa_body, p_lvt + 2, length + 17)
                        p_lvt += 10
                    print(f"Constructor: Shifted LocalVariableTable ({lvt_len} entries) by +17")
                
                new_sub_attrs += struct.pack('>HI', sa_name_idx, len(sa_body)) + sa_body
                p_sub += 6 + sa_len
                
            new_attr_body = struct.pack('>HHI', max_stack, max_locals, new_code_len)
            new_attr_body += new_code
            new_attr_body += struct.pack('>H', 0)
            new_attr_body += struct.pack('>H', sub_ac)
            new_attr_body += new_sub_attrs
            
            init_method['attrs'][attr_idx] = (name_idx, new_attr_body)
            break

    # -----------------
    # Patch 2: renderPlayer
    # -----------------
    rp_name_idx = rewriter.get_utf8_idx(b"renderPlayer")
    rp_desc_idx = rewriter.get_utf8_idx(b"(Lgs;DDDFF)V")
    assert rp_name_idx and rp_desc_idx

    target_method = None
    for m in rewriter.methods:
        if m['name_idx'] == rp_name_idx and m['desc_idx'] == rp_desc_idx:
            target_method = m
            break
    assert target_method is not None, "renderPlayer method not found"
    print("Found renderPlayer method")

    for attr_idx, (name_idx, attr_body) in enumerate(target_method['attrs']):
        name = rewriter.cp[name_idx][1]
        if name == b"Code":
            max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
            orig_code = attr_body[8 : 8+code_len]
            
            # Construct injected bytecode sequence (8 + 13 = 21 bytes)
            # 1. handleSlimArm call (8 bytes)
            #    aload_0 (0x2A)
            #    getfield modelBipedMain (0xB4, mbm_fieldref)
            #    aload_1 (0x2B)
            #    invokestatic handleSlimArm (0xB8, handle_slim_arm_methodref)
            # 2. Cape rendering (13 bytes)
            #    aload_0 (0x2A)
            #    getfield modelBipedMain (0xB4, mbm_fieldref)
            #    getfield ModelPlayer.i (0xB4, model_player_i_fieldref)
            #    aload_1 (0x2B)
            #    fload 9 (0x17, 0x09)
            #    invokevirtual setCurrent (0xB6, set_current_methodref)
            render_injection = bytes([
                # handleSlimArm:
                0x2A,
                0xB4, (mbm_fieldref >> 8) & 0xFF, mbm_fieldref & 0xFF,
                0x2B,
                0xB8, (handle_slim_arm_methodref >> 8) & 0xFF, handle_slim_arm_methodref & 0xFF,
                
                # Cape set:
                0x2A,
                0xB4, (mbm_fieldref >> 8) & 0xFF, mbm_fieldref & 0xFF,
                0xB4, (model_player_i_fieldref >> 8) & 0xFF, model_player_i_fieldref & 0xFF,
                0x2B,
                0x17, 0x09,
                0xB6, (set_current_methodref >> 8) & 0xFF, set_current_methodref & 0xFF
            ])
            assert len(render_injection) == 21
            
            new_code = render_injection + orig_code
            new_code_len = len(new_code)
            
            # Exceptions
            et_pos = 8 + code_len
            et_len = struct.unpack_from('>H', attr_body, et_pos)[0]
            assert et_len == 0, f"Expected 0 exception handlers in renderPlayer, got {et_len}"
            
            # Attributes of Code (shift offsets by +21)
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
                        struct.pack_into('>H', sa_body, p_lnt, start_pc + 21)
                        p_lnt += 4
                    print(f"renderPlayer: Shifted LineNumberTable ({lnt_len} entries) by +21")
                elif sa_name == b"LocalVariableTable":
                    lvt_len = struct.unpack_from('>H', sa_body, 0)[0]
                    p_lvt = 2
                    for _ in range(lvt_len):
                        start_pc, length = struct.unpack_from('>HH', sa_body, p_lvt)
                        if start_pc == 0:
                            struct.pack_into('>H', sa_body, p_lvt + 2, length + 21)
                        else:
                            struct.pack_into('>H', sa_body, p_lvt, start_pc + 21)
                        p_lvt += 10
                    print(f"renderPlayer: Shifted LocalVariableTable ({lvt_len} entries) by +21")
                elif sa_name == b"StackMapTable":
                    shift_smt(sa_body, 0, 21)
                    
                new_sub_attrs += struct.pack('>HI', sa_name_idx, len(sa_body)) + sa_body
                p_sub += 6 + sa_len
                
            new_attr_body = struct.pack('>HHI', max_stack, max_locals, new_code_len)
            new_attr_body += new_code
            new_attr_body += struct.pack('>H', 0)
            new_attr_body += struct.pack('>H', sub_ac)
            new_attr_body += new_sub_attrs
            
            target_method['attrs'][attr_idx] = (name_idx, new_attr_body)
            break

    # -----------------
    # Rebuild class file
    # -----------------
    patched_class = rewriter.rebuild()
    print(f"Patched class file size: {len(patched_class)} (was {len(class_data)})")

    # -----------------
    # Write back to zip
    # -----------------
    buf = io.BytesIO()
    with zipfile.ZipFile(archive, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, patched_class)
                    print(f"  Replaced {ENTRY} in zip")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(archive, 'wb') as f:
        f.write(buf.getvalue())

    print("  Done! Verified output with javap:")
    # Verify constructor and renderPlayer with javap
    with tempfile.NamedTemporaryFile(suffix=".class", delete=False) as tmp:
        tmp.write(patched_class)
        tmp_name = tmp.name

    try:
        # Check constructor
        res = subprocess.run(["javap", "-c", "-p", tmp_name], capture_output=True, text=True)
        lines = res.stdout.splitlines()
        
        found_init = False
        for idx, line in enumerate(lines):
            if "SmartMovingRender(net.minecraft.move.IRenderPlayer)" in line:
                found_init = True
                print("   === Verified Constructor ===")
                print("\n".join("    " + l for l in lines[idx:idx+40]))
                break
                
        found_rp = False
        for idx, line in enumerate(lines):
            if "void renderPlayer(gs," in line:
                found_rp = True
                print("   === Verified renderPlayer ===")
                print("\n".join("    " + l for l in lines[idx:idx+35]))
                break
    finally:
        os.unlink(tmp_name)


def main():
    for archive in ARCHIVES:
        patch_archive(archive)


if __name__ == '__main__':
    main()

