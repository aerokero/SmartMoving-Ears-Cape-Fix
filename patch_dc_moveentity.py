#!/usr/bin/env python3
import struct, zipfile, io, os, shutil, sys

JAR_PATH  = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\550432ac-f040-473c-8d30-7aeea8b17e89.jar"
BACKUP    = JAR_PATH + ".backup_moveentity"
DC_ENTRY  = "dc.class"

# Bytecode opcodes
ALOAD_0       = 0x2A
DLOAD_1       = 0x27
DLOAD_3       = 0x29
DLOAD         = 0x18
INVOKESTATIC  = 0xB8
INVOKESPECIAL = 0xB7
IFEQ          = 0x99
RETURN        = 0xB1

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

    def get_methodref_idx(self, cls: bytes, name: bytes, desc: bytes):
        c_idx = self.get_class_idx(cls)
        n_idx = self.get_nat_idx(name, desc)
        if not c_idx or not n_idx: return 0
        for idx, entry in enumerate(self.cp):
            if entry and entry[0] == 10 and entry[1] == c_idx and entry[2] == n_idx:
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
        idx = self.get_methodref_idx(cls, name, desc)
        if idx: return idx
        c_idx = self.ec(cls)
        n_idx = self.en(name, desc)
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
    print(f"Backing up {JAR_PATH}...")
    if not os.path.exists(BACKUP):
        shutil.copy2(JAR_PATH, BACKUP)
        print(f"Backup saved to: {BACKUP}")
    else:
        print("Backup already exists.")

    # Read zip
    with zipfile.ZipFile(JAR_PATH, 'r') as z:
        class_data = z.read(DC_ENTRY)

    rewriter = ClassRewriter(class_data)

    # Find name index of "b" and descriptor index of "(DDD)V"
    b_name_idx = rewriter.get_utf8_idx(b"b")
    b_desc_idx = rewriter.get_utf8_idx(b"(DDD)V")
    assert b_name_idx and b_desc_idx, "Could not find method name/desc in constant pool"

    # Find the method
    target_method = None
    for m in rewriter.methods:
        if m['name_idx'] == b_name_idx and m['desc_idx'] == b_desc_idx:
            target_method = m
            break

    assert target_method is not None, "Method b(DDD)V not found"
    print("Found method b(DDD)V")

    # Add required CP entries
    m_papi_move = rewriter.em(b"PlayerAPI", b"moveEntity", b"(Ldc;DDD)Z")
    m_gs_move   = rewriter.em(b"gs", b"b", b"(DDD)V")
    code_idx    = rewriter.eu(b"Code")
    smt_idx     = rewriter.eu(b"StackMapTable")

    # Construct StackMapTable sub-attribute
    # 1 entry, type same_frame (12), offset_delta = 12
    smt_body = struct.pack('>H', 1) + bytes([12])
    smt_attr = struct.pack('>HI', smt_idx, len(smt_body)) + smt_body

    # Construct new bytecode (21 bytes)
    bytecode = bytes([
        ALOAD_0,
        DLOAD_1,
        DLOAD_3,
        DLOAD, 0x05,
        INVOKESTATIC, (m_papi_move >> 8) & 0xFF, m_papi_move & 0xFF,
        IFEQ, 0x00, 0x04,
        RETURN,
        ALOAD_0,
        DLOAD_1,
        DLOAD_3,
        DLOAD, 0x05,
        INVOKESPECIAL, (m_gs_move >> 8) & 0xFF, m_gs_move & 0xFF,
        RETURN
    ])

    # Construct Code attribute body
    max_stack = 7
    max_locals = 7
    code_attr_body = struct.pack('>HHI', max_stack, max_locals, len(bytecode))
    code_attr_body += bytecode
    code_attr_body += struct.pack('>H', 0) # Exception table length = 0
    code_attr_body += struct.pack('>H', 1) # Sub-attributes count = 1 (StackMapTable)
    code_attr_body += smt_attr

    # Replace the Code attribute of target_method
    # We find the existing Code attribute and replace its body, keeping other attributes if any (though usually it only has Code or LineNumberTable, let's keep only Code to be safe and clean)
    new_attrs = [(code_idx, code_attr_body)]
    target_method['attrs'] = new_attrs

    # Rebuild class file
    patched_class = rewriter.rebuild()
    print(f"Patched class file size: {len(patched_class)} (was {len(class_data)})")

    # Write back to zip
    buf = io.BytesIO()
    with zipfile.ZipFile(JAR_PATH, 'r') as zin:
        with zipfile.ZipFile(buf, 'w') as zout:
            for item in zin.infolist():
                if item.filename == DC_ENTRY:
                    zout.writestr(item, patched_class)
                    print(f"Replaced {DC_ENTRY} in jar")
                else:
                    zout.writestr(item, zin.read(item.filename))

    with open(JAR_PATH, 'wb') as f:
        f.write(buf.getvalue())

    print("\nDone! Verified output with javap:")
    # Verify with javap
    import subprocess, tempfile
    with tempfile.NamedTemporaryFile(suffix=".class", delete=False) as tmp:
        tmp.write(patched_class)
        tmp_name = tmp.name

    try:
        res = subprocess.run(["javap", "-c", "-p", tmp_name], capture_output=True, text=True)
        # Find b(DDD)V method in output
        lines = res.stdout.splitlines()
        found_m = False
        for idx, line in enumerate(lines):
            if "void b(double, double, double)" in line:
                found_m = True
                print("\n".join(lines[idx:idx+20]))
                break
    finally:
        os.unlink(tmp_name)

if __name__ == '__main__':
    main()
