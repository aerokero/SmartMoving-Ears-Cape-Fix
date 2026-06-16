#!/usr/bin/env python3
import struct, zipfile, io, os, shutil

JAR_MOD = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\97bbe32f-8e2e-4e99-bd9f-32286239e4c0.jar"
BACKUP = JAR_MOD + ".backup_fh"
ENTRY  = "fh.class"

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

def main():
    print(f"Reading fh.class from jarmod: {JAR_MOD}")
    if not os.path.exists(BACKUP):
        shutil.copy2(JAR_MOD, BACKUP)
        print(f"Created backup: {BACKUP}")
    else:
        print(f"Backup already exists: {BACKUP}")
        
    with zipfile.ZipFile(JAR_MOD, 'r') as z:
        class_data = z.read(ENTRY)
        
    rewriter = ClassRewriter(class_data)
    
    # Define method refs for EarSkinCompat.beforeRenderCape and afterRenderCape
    m_before = rewriter.em(b"farn/ears_compat/EarSkinCompat", b"beforeRenderCape", b"(Ljava/lang/Object;)V")
    m_after  = rewriter.em(b"farn/ears_compat/EarSkinCompat", b"afterRenderCape", b"(Ljava/lang/Object;)V")
    
    b_name_idx = rewriter.get_utf8_idx(b"b")
    f_desc_idx = rewriter.get_utf8_idx(b"(F)V")
    assert b_name_idx and f_desc_idx, "Method name 'b' or desc '(F)V' not found in CP"
    
    target_method = None
    for m in rewriter.methods:
        if m['name_idx'] == b_name_idx and m['desc_idx'] == f_desc_idx:
            target_method = m
            break
            
    assert target_method is not None, "Method fh.b(F)V not found"
    print("Found method fh.b(F)V")
    
    for attr_idx, (name_idx, attr_body) in enumerate(target_method['attrs']):
        name = rewriter.cp[name_idx][1]
        if name == b"Code":
            max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
            orig_code = attr_body[8 : 8+code_len]
            print(f"Original b(F)V bytecode: {orig_code.hex()}")
            
            # Verify original:
            # 0: aload_0 (0x2A)
            # 1: getfield (0xB4, XX, YY)
            # 4: fload_1 (0x23)
            # 5: invokevirtual (0xB6, ZZ, WW)
            # 8: return (0xB1)
            assert orig_code[0] == 0x2A
            assert orig_code[1] == 0xB4
            getfield_idx = struct.unpack_from('>H', orig_code, 2)[0]
            assert orig_code[4] == 0x23
            assert orig_code[5] == 0xB6
            invokevirtual_idx = struct.unpack_from('>H', orig_code, 6)[0]
            assert orig_code[8] == 0xB1
            
            # Patch bytecode:
            new_code = bytes([
                0x2A, # aload_0
                0xB8, (m_before >> 8) & 0xFF, m_before & 0xFF, # invokestatic beforeRenderCape(Object)
                0x2A, # aload_0
                0xB4, (getfield_idx >> 8) & 0xFF, getfield_idx & 0xFF, # getfield i
                0x23, # fload_1
                0xB6, (invokevirtual_idx >> 8) & 0xFF, invokevirtual_idx & 0xFF, # invokevirtual ps.a(F)
                0x2A, # aload_0
                0xB8, (m_after >> 8) & 0xFF, m_after & 0xFF, # invokestatic afterRenderCape(Object)
                0xB1  # return
            ])
            new_code_len = len(new_code)
            
            new_attr_body = struct.pack('>HHI', max_stack, max_locals, new_code_len)
            new_attr_body += new_code
            new_attr_body += struct.pack('>H', 0) # exception_table_len = 0
            new_attr_body += struct.pack('>H', 0) # sub_attributes_count = 0 (stripping LineNumber/LocalVariable Tables)
            
            target_method['attrs'][attr_idx] = (name_idx, new_attr_body)
            break
            
    # Rebuild class file
    patched_class = rewriter.rebuild()
    print(f"Patched class file size: {len(patched_class)} (was {len(class_data)})")
    
    # Write back to zip
    buf = io.BytesIO()
    with zipfile.ZipFile(JAR_MOD, 'r') as zin:
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == ENTRY:
                    zout.writestr(item, patched_class)
                    print(f"Replaced {ENTRY} in jar")
                else:
                    zout.writestr(item, zin.read(item.filename))
                    
    with open(JAR_MOD, 'wb') as f:
        f.write(buf.getvalue())
        
    print("Successfully patched and packed fh.class into the jarmod!")
    
    # Verify
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".class", delete=False) as tmp:
        tmp.write(patched_class)
        tmp_name = tmp.name
    try:
        res = subprocess.run(["javap", "-c", "-p", tmp_name], capture_output=True, text=True)
        lines = res.stdout.splitlines()
        found = False
        for idx, line in enumerate(lines):
            if "public void b(float);" in line:
                found = True
                print("\n=== Verified fh.b(F)V ===")
                print("\n".join(lines[idx:idx+15]))
                break
    finally:
        os.unlink(tmp_name)

if __name__ == '__main__':
    main()
