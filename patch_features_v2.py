#!/usr/bin/env python3
import struct, zipfile, io, os, shutil

SM_ZIP = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\SmartMoving for ModLoader.zip"
BACKUP = SM_ZIP + ".backup_features_v2"
ENTRY = "net/minecraft/move/EntityClientPlayerMP.class"

class ClassRewriter:
    def __init__(self, data: bytes):
        self.data = data
        pos = 0
        magic, minor, major = struct.unpack_from('>IHH', data, pos)
        assert magic == 0xCAFEBABE, "Not a class file"
        pos += 8

        cp_count, = struct.unpack_from('>H', data, pos)
        pos += 2
        self.cp = [None]
        i = 1
        while i < cp_count:
            tag = data[pos]
            pos += 1
            if tag == 1:
                n, = struct.unpack_from('>H', data, pos); pos += 2
                self.cp.append((1, data[pos:pos+n])); pos += n
                i += 1
            elif tag in (7, 8):
                v, = struct.unpack_from('>H', data, pos); pos += 2
                self.cp.append((tag, v))
                i += 1
            elif tag in (9, 10, 11, 12):
                a, b = struct.unpack_from('>HH', data, pos); pos += 4
                self.cp.append((tag, a, b))
                i += 1
            elif tag in (3, 4):
                v, = struct.unpack_from('>I', data, pos); pos += 4
                self.cp.append((tag, v))
                i += 1
            elif tag in (5, 6):
                v, = struct.unpack_from('>Q', data, pos); pos += 8
                self.cp.append((tag, v))
                self.cp.append(None)
                i += 2
            else:
                raise ValueError(f"Unknown CP tag {tag}")

        self.header_start = pos
        pos += 6
        icount, = struct.unpack_from('>H', data, pos); pos += 2
        pos += icount * 2
        self.header_end = pos

        fcount, = struct.unpack_from('>H', data, pos)
        pos += 2
        for _ in range(fcount):
            pos += 6
            ac, = struct.unpack_from('>H', data, pos); pos += 2
            for _ in range(ac):
                pos += 2
                alen, = struct.unpack_from('>I', data, pos); pos += 4 + alen
        self.fields_end = pos

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
        methods_bytes = struct.pack('>H', len(self.methods))
        for m in self.methods:
            methods_bytes += struct.pack('>HHHH', m['access'], m['name_idx'], m['desc_idx'], len(m['attrs']))
            for attr_name_idx, attr_body in m['attrs']:
                methods_bytes += struct.pack('>HI', attr_name_idx, len(attr_body)) + attr_body
        tail = self.data[self.after_methods_offset:]
        return header + cp_bytes + header_etc + methods_bytes + tail

def main():
    print(f"Reading {ENTRY} from zip...")
    with zipfile.ZipFile(SM_ZIP, 'r') as z:
        class_data = z.read(ENTRY)

    rewriter = ClassRewriter(class_data)

    # Create method refs
    update_fov_methodref = rewriter.em(b"SmartMovingFeatures", b"updateFOV", b"(Ljava/lang/Object;)V")
    detect_sprint_methodref = rewriter.em(b"SmartMovingFeatures", b"detectDoubleTapSprint", b"(Ljava/lang/Object;)V")
    grab_methodref = rewriter.em(b"SmartMovingFeatures", b"grabOnInteract", b"(Ljava/lang/Object;)V")

    print(f"updateFOV methodref: #{update_fov_methodref}")
    print(f"detectDoubleTapSprint methodref: #{detect_sprint_methodref}")
    print(f"grabOnInteract methodref: #{grab_methodref}")

    # Find f_() method: name=f_, desc=()V
    f_name_idx = rewriter.get_utf8_idx(b"f_")
    f_desc_idx = rewriter.get_utf8_idx(b"()V")
    print(f"Looking for f_() with name_idx={f_name_idx}, desc_idx={f_desc_idx}")

    target_method = None
    for m in rewriter.methods:
        if m['name_idx'] == f_name_idx and m['desc_idx'] == f_desc_idx:
            target_method = m
            break

    assert target_method is not None, "f_() method not found"
    print("Found f_() method")

    for attr_idx, (name_idx, attr_body) in enumerate(target_method['attrs']):
        name = rewriter.cp[name_idx][1]
        if name == b"Code":
            max_stack, max_locals, code_len = struct.unpack_from('>HHI', attr_body, 0)
            orig_code = attr_body[8 : 8+code_len]
            print(f"Original code length: {code_len}")
            print(f"Original code hex: {orig_code.hex()}")

            # Current: aload_0, getfield, iconst_0, invokevirtual, return
            # Inject before return (offset 8)
            injection_point = code_len - 1

            # aload_0, invokestatic updateFOV, aload_0, invokestatic detectDoubleTapSprint, aload_0, invokestatic grabOnInteract
            injection = bytes([
                0x2A,  # aload_0
                0xB8, (update_fov_methodref >> 8) & 0xFF, update_fov_methodref & 0xFF,
                0x2A,  # aload_0
                0xB8, (detect_sprint_methodref >> 8) & 0xFF, detect_sprint_methodref & 0xFF,
                0x2A,  # aload_0
                0xB8, (grab_methodref >> 8) & 0xFF, grab_methodref & 0xFF,
            ])

            new_code = orig_code[:injection_point] + injection + orig_code[injection_point:]
            new_code_len = len(new_code)
            print(f"New code length: {new_code_len} (+{new_code_len - code_len})")

            et_pos = 8 + code_len
            et_count = struct.unpack_from('>H', attr_body, et_pos)[0]

            new_attr_body = struct.pack('>HHI', max_stack + 1, max_locals, new_code_len)
            new_attr_body += new_code
            new_attr_body += attr_body[et_pos:]

            target_method['attrs'][attr_idx] = (name_idx, new_attr_body)
            break

    patched_class = rewriter.rebuild()

    if not os.path.exists(BACKUP):
        shutil.copy2(SM_ZIP, BACKUP)
        print(f"Created backup: {BACKUP}")

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

    print("Done! Patched EntityClientPlayerMP.f_()")

if __name__ == '__main__':
    main()
