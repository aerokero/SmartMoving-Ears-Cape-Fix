#!/usr/bin/env python3
import struct, zipfile, io, os, shutil

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

def shift_smt(data, pos, shift_amount):
    # StackMapTable parser and shifter
    # We only need to shift the first frame's delta
    num_entries = struct.unpack_from(">H", data, pos)[0]
    if num_entries > 0:
        # First frame is at pos + 2
        frame_type = data[pos+2]
        if frame_type == 252: # append_frame
            # 2-byte delta is at pos + 3
            delta = struct.unpack_from(">H", data, pos + 3)[0]
            struct.pack_into(">H", data, pos + 3, delta + shift_amount)
            print(f"Shifted SMT frame 0 delta from {delta} to {delta + shift_amount}")
        else:
            print(f"WARNING: StackMapTable first frame is not append_frame (type {frame_type}), cannot shift easily!")

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

    # Find name index of "renderPlayer" and desc index of "(Lgs;DDDFF)V"
    rp_name_idx = rewriter.get_utf8_idx(b"renderPlayer")
    rp_desc_idx = rewriter.get_utf8_idx(b"(Lgs;DDDFF)V")
    assert rp_name_idx and rp_desc_idx

    # Find method
    target_method = None
    for m in rewriter.methods:
        if m['name_idx'] == rp_name_idx and m['desc_idx'] == rp_desc_idx:
            target_method = m
            break

    assert target_method is not None, "renderPlayer method not found"
    print("Found renderPlayer method")

    # Find indices for modelBipedMain fieldref
    mbm_fieldref = rewriter.get_fieldref_idx(b"net/minecraft/move/SmartMovingRender", b"modelBipedMain", b"Lnet/minecraft/move/ModelPlayer;")
    assert mbm_fieldref, "Could not find modelBipedMain fieldref in constant pool"

    # Add required new CP entries
    model_player_i_fieldref = rewriter.ef(b"net/minecraft/move/ModelPlayer", b"i", b"Lnet/minecraft/move/ModelCapeRenderer;")
    set_current_methodref   = rewriter.em(b"net/minecraft/move/ModelCapeRenderer", b"setCurrent", b"(Lgs;F)V")

    print(f"modelBipedMain fieldref: #{mbm_fieldref}")
    print(f"ModelPlayer.i fieldref: #{model_player_i_fieldref}")
    print(f"ModelCapeRenderer.setCurrent methodref: #{set_current_methodref}")

    # Patch the Code attribute of target_method
    # We find the existing Code attribute
    for attr_idx, (name_idx, attr_body) in enumerate(target_method['attrs']):
        name = rewriter.cp[name_idx][1]
        if name == b"Code":
            max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
            print(f"Original Code: max_stack={max_stack}, max_locals={max_locals}, code_len={code_len}")
            
            # The original code bytes
            orig_code = attr_body[8 : 8+code_len]
            
            # Construct injected bytecode sequence (13 bytes)
            # aload_0 (0x2A)
            # getfield modelBipedMain (0xB4, high, low)
            # getfield ModelPlayer.i (0xB4, high, low)
            # aload_1 (0x2B)
            # fload 9 (0x15, 0x09)
            # invokevirtual setCurrent (0xB6, high, low)
            injection = bytes([
                0x2A,
                0xB4, (mbm_fieldref >> 8) & 0xFF, mbm_fieldref & 0xFF,
                0xB4, (model_player_i_fieldref >> 8) & 0xFF, model_player_i_fieldref & 0xFF,
                0x2B,
                0x17, 0x09,
                0xB6, (set_current_methodref >> 8) & 0xFF, set_current_methodref & 0xFF
            ])
            assert len(injection) == 13
            
            new_code = injection + orig_code
            new_code_len = len(new_code)
            
            # Exceptions (there are 0)
            et_pos = 8 + code_len
            et_len = struct.unpack_from('>H', attr_body, et_pos)[0]
            assert et_len == 0, f"Expected 0 exception handlers, got {et_len}"
            
            # Attributes of Code (we need to shift offsets in LNT, LVT, SMT)
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
                        struct.pack_into('>H', sa_body, p_lnt, start_pc + 13)
                        p_lnt += 4
                    print(f"Shifted LineNumberTable ({lnt_len} entries) by +13")
                elif sa_name == b"LocalVariableTable":
                    lvt_len = struct.unpack_from('>H', sa_body, 0)[0]
                    p_lvt = 2
                    for _ in range(lvt_len):
                        start_pc, length = struct.unpack_from('>HH', sa_body, p_lvt)
                        if start_pc == 0:
                            struct.pack_into('>H', sa_body, p_lvt + 2, length + 13)
                        else:
                            struct.pack_into('>H', sa_body, p_lvt, start_pc + 13)
                        p_lvt += 10
                    print(f"Shifted LocalVariableTable ({lvt_len} entries) by +13")
                elif sa_name == b"StackMapTable":
                    shift_smt(sa_body, 0, 13)
                    
                new_sub_attrs += struct.pack('>HI', sa_name_idx, len(sa_body)) + sa_body
                p_sub += 6 + sa_len
                
            # Reassemble Code attribute body
            # max_stack is originally 10. Our peak stack is 5, so 10 is plenty.
            new_attr_body = struct.pack('>HHI', max_stack, max_locals, new_code_len)
            new_attr_body += new_code
            new_attr_body += struct.pack('>H', 0) # Exceptions
            new_attr_body += struct.pack('>H', sub_ac) # Sub-attributes count
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
        # Find renderPlayer method in output
        lines = res.stdout.splitlines()
        found_m = False
        for idx, line in enumerate(lines):
            if "void renderPlayer(gs," in line:
                found_m = True
                print("\n".join(lines[idx:idx+25]))
                break
    finally:
        os.unlink(tmp_name)

if __name__ == '__main__':
    main()
