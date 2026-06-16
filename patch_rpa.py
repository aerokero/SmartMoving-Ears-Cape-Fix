#!/usr/bin/env python3
import struct, zipfile, io, os, shutil, subprocess, tempfile

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_rpa"
ENTRY  = "net/minecraft/move/RenderPlayerAether.class"

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

ARCHIVES = [
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip",
    r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\Armorstand Player fix forge patch.zip",
]


def main():
    for archive in ARCHIVES:
        if not os.path.exists(archive):
            print(f"Archive not found, skipping: {archive}")
            continue
            
        with zipfile.ZipFile(archive, 'r') as z:
            if ENTRY not in z.namelist():
                print(f"RenderPlayerAether.class not found in {archive}, skipping")
                continue
                
        print(f"\nPatching RenderPlayerAether.class in: {archive}")
        
        backup = archive + ".backup_rpa"
        if not os.path.exists(backup):
            shutil.copy2(archive, backup)
            print(f"  Created backup: {backup}")
        else:
            print(f"  Using existing backup: {backup}")
            
        with zipfile.ZipFile(backup, 'r') as z:
            class_data = z.read(ENTRY)
            
        rewriter = ClassRewriter(class_data)
        
        # Define restorePlayerSkin method ref
        restore_skin_methodref = rewriter.em(
            b"farn/ears_compat/EarSkinCompat", 
            b"restorePlayerSkin", 
            b"(Ljava/lang/Object;Ljava/lang/Object;)V"
        )
        print(f"  EarSkinCompat.restorePlayerSkin methodref: #{restore_skin_methodref}")
        
        # Define setupAetherCape method ref
        setup_aether_cape_methodref = rewriter.em(
            b"farn/ears_compat/EarSkinCompat", 
            b"setupAetherCape", 
            b"(Ljava/lang/Object;)V"
        )
        print(f"  EarSkinCompat.setupAetherCape methodref: #{setup_aether_cape_methodref}")
        
        # -----------------
        # Patch 1: Constructor <init>
        # -----------------
        init_name_idx = rewriter.get_utf8_idx(b"<init>")
        init_desc_idx = rewriter.get_utf8_idx(b"()V")
        assert init_name_idx and init_desc_idx, "Constructor name or desc not found"
        
        init_method = None
        for m in rewriter.methods:
            if m['name_idx'] == init_name_idx and m['desc_idx'] == init_desc_idx:
                init_method = m
                break
        assert init_method is not None, "Constructor <init> method not found"
        print("  Found <init> constructor method")
        
        for attr_idx, (name_idx, attr_body) in enumerate(init_method['attrs']):
            name = rewriter.cp[name_idx][1]
            if name == b"Code":
                max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
                orig_code = attr_body[8 : 8+code_len]
                print(f"  Original constructor length: {code_len} bytes")
                
                # Verify the last byte is return (0xB1)
                assert orig_code[-1] == 0xB1, f"Expected last byte to be return (0xB1), got {orig_code[-1]:02X}"
                injection_point = code_len - 1
                
                # Injection (4 bytes):
                # aload_0 (0x2A)
                # invokestatic setupAetherCape (0xB8, msb, lsb)
                injection = bytes([
                    0x2A,
                    0xB8, (setup_aether_cape_methodref >> 8) & 0xFF, setup_aether_cape_methodref & 0xFF
                ])
                assert len(injection) == 4
                
                new_code = orig_code[:injection_point] + injection + bytes([0xB1])
                new_code_len = len(new_code)
                
                # Exceptions
                et_pos = 8 + code_len
                et_len = struct.unpack_from('>H', attr_body, et_pos)[0]
                assert et_len == 0, f"Expected 0 exception handlers in constructor, got {et_len}"
                
                # Sub-attributes of Code (shift offsets > injection_point by +4)
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
                                struct.pack_into('>H', sa_body, p_lnt, start_pc + 4)
                            p_lnt += 4
                        print(f"  Constructor: Shifted LineNumberTable ({lnt_len} entries) by +4")
                    elif sa_name == b"LocalVariableTable":
                        lvt_len = struct.unpack_from('>H', sa_body, 0)[0]
                        p_lvt = 2
                        for _ in range(lvt_len):
                            start_pc, length = struct.unpack_from('>HH', sa_body, p_lvt)
                            if start_pc > injection_point:
                                struct.pack_into('>H', sa_body, p_lvt, start_pc + 4)
                            else:
                                if start_pc + length > injection_point:
                                    struct.pack_into('>H', sa_body, p_lvt + 2, length + 4)
                            p_lvt += 10
                        print(f"  Constructor: Shifted LocalVariableTable ({lvt_len} entries) by +4")
                        
                    new_sub_attrs += struct.pack('>HI', sa_name_idx, len(sa_body)) + sa_body
                    p_sub += 6 + sa_len
                    
                new_attr_body = struct.pack('>HHI', max_stack + 1, max_locals, new_code_len)
                new_attr_body += new_code
                new_attr_body += struct.pack('>H', 0)
                new_attr_body += struct.pack('>H', sub_ac)
                new_attr_body += new_sub_attrs
                
                init_method['attrs'][attr_idx] = (name_idx, new_attr_body)
                break
                
        # -----------------
        # Patch 2: doEntityPlayerAetherRender_corrected
        # -----------------
        m_name_idx = rewriter.get_utf8_idx(b"doEntityPlayerAetherRender_corrected")
        m_desc_idx = rewriter.get_utf8_idx(b"(Lsn;DDDFF)V")
        assert m_name_idx and m_desc_idx, "Method name or desc not found in CP"
        
        target_method = None
        for m in rewriter.methods:
            if m['name_idx'] == m_name_idx and m['desc_idx'] == m_desc_idx:
                target_method = m
                break
        assert target_method is not None, "doEntityPlayerAetherRender_corrected method not found"
        print("  Found doEntityPlayerAetherRender_corrected method")
        
        for attr_idx, (name_idx, attr_body) in enumerate(target_method['attrs']):
            name = rewriter.cp[name_idx][1]
            if name == b"Code":
                max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
                orig_code = attr_body[8 : 8+code_len]
                print(f"  Original method code length: {code_len} bytes")
                
                # Verify the last byte is return (0xB1)
                assert orig_code[-1] == 0xB1, f"Expected last byte to be return (0xB1), got {orig_code[-1]:02X}"
                injection_point = code_len - 1
                
                # Injection (5 bytes):
                # aload_0 (0x2A)
                # aload_1 (0x2B)
                # invokestatic restorePlayerSkin (0xB8, msb, lsb)
                # (return 0xB1 is appended after this)
                injection = bytes([
                    0x2A,
                    0x2B,
                    0xB8, (restore_skin_methodref >> 8) & 0xFF, restore_skin_methodref & 0xFF
                ])
                assert len(injection) == 5
                
                new_code = orig_code[:injection_point] + injection + bytes([0xB1])
                new_code_len = len(new_code)
                print(f"  New method code length: {new_code_len} bytes")
                
                # Exceptions
                et_pos = 8 + code_len
                et_len = struct.unpack_from('>H', attr_body, et_pos)[0]
                assert et_len == 0, f"Expected 0 exception handlers, got {et_len}"
                
                # Sub-attributes of Code (shift offsets > injection_point by +5)
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
                                struct.pack_into('>H', sa_body, p_lnt, start_pc + 5)
                            p_lnt += 4
                        print(f"  Shifted LineNumberTable ({lnt_len} entries) by +5")
                    elif sa_name == b"LocalVariableTable":
                        lvt_len = struct.unpack_from('>H', sa_body, 0)[0]
                        p_lvt = 2
                        for _ in range(lvt_len):
                            start_pc, length = struct.unpack_from('>HH', sa_body, p_lvt)
                            if start_pc > injection_point:
                                struct.pack_into('>H', sa_body, p_lvt, start_pc + 5)
                            else:
                                if start_pc + length > injection_point:
                                    struct.pack_into('>H', sa_body, p_lvt + 2, length + 5)
                            p_lvt += 10
                        print(f"  Shifted LocalVariableTable ({lvt_len} entries) by +5")
                        
                    new_sub_attrs += struct.pack('>HI', sa_name_idx, len(sa_body)) + sa_body
                    p_sub += 6 + sa_len
                    
                new_attr_body = struct.pack('>HHI', max_stack + 2, max_locals, new_code_len)
                new_attr_body += new_code
                new_attr_body += struct.pack('>H', 0)
                new_attr_body += struct.pack('>H', sub_ac)
                new_attr_body += new_sub_attrs
                
                target_method['attrs'][attr_idx] = (name_idx, new_attr_body)
                break
                
        # Rebuild class file
        patched_class = rewriter.rebuild()
        
        # Write back to zip
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
            
        print("  Done! Verify output with javap:")
        with tempfile.NamedTemporaryFile(suffix=".class", delete=False) as tmp:
            tmp.write(patched_class)
            tmp_name = tmp.name
        try:
            res = subprocess.run(["javap", "-c", "-p", tmp_name], capture_output=True, text=True)
            lines = res.stdout.splitlines()
            found = False
            for idx, line in enumerate(lines):
                if "doEntityPlayerAetherRender_corrected" in line:
                    found = True
                    print("   === Verified doEntityPlayerAetherRender_corrected ===")
                    print("\n".join("    " + l for l in lines[idx:idx+25]))
                    break
        finally:
            os.unlink(tmp_name)


if __name__ == '__main__':
    main()
