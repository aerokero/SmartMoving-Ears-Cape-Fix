"""
Patch mod_Somnia_SleepingScreenRenderer.tick() to add Thread.sleep(50)
throttle, limiting sleep simulation to ~20 world ticks/sec.
This makes the sleep take ~10 real minutes (12000 ticks / 20 tps = real-time speed).
"""

import zipfile, struct, shutil, os, subprocess, tempfile

SOMNIA_ZIP = r'D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\.minecraft\mods\[1.7.3] Somnia v11.zip'
BACKUP = SOMNIA_ZIP + '.backup_throttle'
TARGET_CLASS = 'mod_Somnia_SleepingScreenRenderer.class'

# ── helpers ──────────────────────────────────────────────────────────────────

def read_u2(data, pos):
    return struct.unpack_from('>H', data, pos)[0]

def write_u2(val):
    return struct.pack('>H', val)

def encode_utf8_entry(s):
    b = s.encode('utf-8')
    return bytes([1]) + struct.pack('>H', len(b)) + b

def encode_class_entry(name_idx):
    return bytes([7]) + struct.pack('>H', name_idx)

def encode_nameandtype_entry(name_idx, desc_idx):
    return bytes([12]) + struct.pack('>HH', name_idx, desc_idx)

def encode_methodref_entry(class_idx, nat_idx):
    return bytes([10]) + struct.pack('>HH', class_idx, nat_idx)

# ── parse constant pool ───────────────────────────────────────────────────────

def parse_cp(data):
    pos = 8
    cp_count = read_u2(data, pos); pos += 2
    entries = {}
    i = 1
    while i < cp_count:
        tag = data[pos]; pos += 1
        if tag == 1:
            n = read_u2(data, pos); pos += 2
            s = data[pos:pos+n]; pos += n
            entries[i] = ('Utf8', s)
        elif tag in (7, 8):
            idx = read_u2(data, pos); pos += 2
            entries[i] = (('Class','String')[tag-7], idx)
        elif tag in (9, 10, 11):
            ci, ni = struct.unpack_from('>HH', data, pos); pos += 4
            entries[i] = (('Field','Method','IMethod')[tag-9], ci, ni)
        elif tag == 12:
            ni, di = struct.unpack_from('>HH', data, pos); pos += 4
            entries[i] = ('NameType', ni, di)
        elif tag in (3, 4):
            pos += 4; entries[i] = ('IntFloat',)
        elif tag in (5, 6):
            pos += 8; entries[i] = ('LongDouble',); i += 1
        else:
            raise ValueError(f'Unknown CP tag {tag} at byte {pos-1}')
        i += 1
    return entries, cp_count, pos  # pos = start of rest of class after CP

# ── main ─────────────────────────────────────────────────────────────────────

if not os.path.exists(BACKUP):
    print(f'Backing up {SOMNIA_ZIP}...')
    shutil.copy2(SOMNIA_ZIP, BACKUP)
    print(f'Backup: {BACKUP}')
else:
    print(f'Using existing backup: {BACKUP}')

# Always read from backup so script is safely re-runnable
z = zipfile.ZipFile(BACKUP, 'r')
data = z.read(TARGET_CLASS)
z.close()

entries, cp_count, cp_end = parse_cp(data)
print(f'CP count: {cp_count}, CP ends at byte {cp_end}')

# ── find needed existing CP entries ──────────────────────────────────────────

# Thread class (#234 → #291 = "java/lang/Thread")
thread_class_idx = None
for idx, e in entries.items():
    if e[0] == 'Class':
        name_e = entries.get(e[1], ('',))
        if name_e[0] == 'Utf8' and name_e[1] == b'java/lang/Thread':
            thread_class_idx = idx
            break
assert thread_class_idx is not None, 'Thread class not found in CP'
print(f'Thread class: #{thread_class_idx}')

# ── add new CP entries ────────────────────────────────────────────────────────

new_cp_bytes = bytearray()
next_idx = cp_count  # new entries start at cp_count (= old max_index + 1)

def add_utf8(s):
    global next_idx
    idx = next_idx
    new_cp_bytes.extend(encode_utf8_entry(s))
    next_idx += 1
    return idx

def add_class(name_idx):
    global next_idx
    idx = next_idx
    new_cp_bytes.extend(encode_class_entry(name_idx))
    next_idx += 1
    return idx

def add_nameandtype(ni, di):
    global next_idx
    idx = next_idx
    new_cp_bytes.extend(encode_nameandtype_entry(ni, di))
    next_idx += 1
    return idx

def add_methodref(ci, ni):
    global next_idx
    idx = next_idx
    new_cp_bytes.extend(encode_methodref_entry(ci, ni))
    next_idx += 1
    return idx

sleep_utf8_idx      = add_utf8('sleep')
j_v_utf8_idx        = add_utf8('(J)V')
sleep_nat_idx       = add_nameandtype(sleep_utf8_idx, j_v_utf8_idx)
sleep_method_idx    = add_methodref(thread_class_idx, sleep_nat_idx)

interrupt_utf8_idx  = add_utf8('java/lang/InterruptedException')
interrupt_class_idx = add_class(interrupt_utf8_idx)

print(f'Added CP entries #{cp_count}..#{next_idx-1}:')
print(f'  #{cp_count  }: Utf8 "sleep"')
print(f'  #{cp_count+1}: Utf8 "(J)V"')
print(f'  #{cp_count+2}: NameAndType sleep:(J)V')
print(f'  #{cp_count+3}: Methodref Thread.sleep(J)V')
print(f'  #{cp_count+4}: Utf8 "java/lang/InterruptedException"')
print(f'  #{cp_count+5}: Class java/lang/InterruptedException')

new_cp_count = next_idx  # = cp_count + 6

# ── patch tick() method ───────────────────────────────────────────────────────

# We need to find the tick() method in the class and modify its Code attribute.
# Navigate: after CP → access_flags(2) + this_class(2) + super_class(2) +
#   interfaces_count(2) + interfaces + fields_count(2) + fields +
#   methods_count(2) + methods...

pos = cp_end  # start after constant pool

# Skip: access_flags, this_class, super_class
pos += 6
# interfaces
iface_count = read_u2(data, pos); pos += 2
pos += iface_count * 2
# fields
field_count = read_u2(data, pos); pos += 2
for _ in range(field_count):
    pos += 6  # flags + name + desc
    attr_count = read_u2(data, pos); pos += 2
    for _ in range(attr_count):
        pos += 2  # attr name
        attr_len = struct.unpack_from('>I', data, pos)[0]; pos += 4
        pos += attr_len

# methods
method_count = read_u2(data, pos); pos += 2
print(f'Methods count: {method_count}')

tick_method_start = None
tick_code_pos = None  # position of code_length field inside Code attribute

for m in range(method_count):
    m_start = pos
    flags = read_u2(data, pos); pos += 2
    name_idx = read_u2(data, pos); pos += 2
    desc_idx = read_u2(data, pos); pos += 2
    attr_count = read_u2(data, pos); pos += 2

    name_entry = entries.get(name_idx, ('?',))
    method_name = name_entry[1].decode() if name_entry[0] == 'Utf8' else '?'

    for a in range(attr_count):
        attr_name_idx = read_u2(data, pos); pos += 2
        attr_len = struct.unpack_from('>I', data, pos)[0]; pos += 4
        attr_start = pos
        attr_name = entries.get(attr_name_idx, ('?',))[1]
        if isinstance(attr_name, bytes): attr_name = attr_name.decode()

        if method_name == 'tick' and attr_name == 'Code':
            tick_method_start = m_start
            tick_code_pos = attr_start
            print(f'Found tick() Code at pos {attr_start}')

        pos = attr_start + attr_len

# Verify we found it
assert tick_code_pos is not None, 'tick() method not found!'

# Parse the Code attribute
pos = tick_code_pos
max_stack = read_u2(data, pos); pos += 2
max_locals = read_u2(data, pos); pos += 2
code_len = struct.unpack_from('>I', data, pos)[0]; pos += 4
code_start = pos
code = bytearray(data[pos:pos+code_len])
pos += code_len

# Expect: code ends with 0xB1 (return) at offset 30
print(f'tick() code_len={code_len}, max_stack={max_stack}, max_locals={max_locals}')
print(f'Last byte: 0x{code[-1]:02X}')
assert code_len == 31, f'Expected code_len=31, got {code_len}'
assert code[-1] == 0xB1, f'Expected return (0xB1) at end, got 0x{code[-1]:02X}'

# Read existing exception table (should be empty)
exc_table_len = read_u2(data, pos); pos += 2
print(f'Existing exception table entries: {exc_table_len}')
assert exc_table_len == 0, 'Unexpected exception table entries in tick()'
pos += exc_table_len * 8  # each entry is 8 bytes

# Keep rest of Code attribute (line number table etc)
rest_of_code_attr = data[pos:]  # everything after exception table

# ── build new code ────────────────────────────────────────────────────────────

# New code: original[0:30] + bipush 50 + i2l + invokestatic sleep + goto +3 + pop + return
# sleep(50ms) — ~20 ticks/sec → ~10 min night (real-time equivalent)
# Offsets:
#   [0:30]: unchanged
#   30: bipush 50         (0x10 0x32)  → pushes int 50
#   32: i2l               (0x85)       → convert int to long
#   33: invokestatic      (0xB8 hi lo) → Thread.sleep(50L)
#   36: goto +3           (0xA7 00 03) → target = 36+3 = 39
#   39: pop               (0x57)       ← catch handler
#   40: return            (0xB1)
#
# Exception table entry: from=30 to=36 target=39

new_code = bytearray(code[:-1])  # remove old 'return' (offset 30)
new_code += bytes([
    0x10, 0x32,                                   # bipush 50
    0x85,                                         # i2l
    0xB8, (sleep_method_idx >> 8) & 0xFF, sleep_method_idx & 0xFF,  # invokestatic Thread.sleep
    0xA7, 0x00, 0x03,                             # goto +3 (skip catch → target 39)
    0x57,                                         # pop (catch handler, discard InterruptedException)
    0xB1,                                         # return
])

assert len(new_code) == 41, f'Expected 41 bytes, got {len(new_code)}'
print(f'New code length: {len(new_code)} bytes (was {code_len}) — sleep(50ms)')

# New exception table: 1 entry
new_exc_table = struct.pack('>H', 1)  # count = 1
new_exc_table += struct.pack('>HHHH',
    30,                   # from (start of try block)
    36,                   # to (end of try block, exclusive)
    39,                   # target (catch handler)
    interrupt_class_idx   # catch type (java/lang/InterruptedException)
)

# ── assemble new Code attribute ───────────────────────────────────────────────

new_max_stack = max(max_stack, 2)  # lconst_1 needs 2 slots (long)
new_max_locals = max_locals  # no new locals needed (pop discards exception)

new_code_attr_body = bytearray()
new_code_attr_body += struct.pack('>HH', new_max_stack, new_max_locals)
new_code_attr_body += struct.pack('>I', len(new_code))
new_code_attr_body += new_code
new_code_attr_body += new_exc_table

# Append remaining attributes (LineNumberTable etc) from rest_of_code_attr
# rest_of_code_attr starts AFTER the old exception table, which is just the extra attrs
# We need to continue from data after the old exception table entries
# (we set rest_of_code_attr = data[pos:] where pos was right after exception table)
# The remaining Code attribute sub-attributes follow
remaining_pos = tick_code_pos + 2 + 2 + 4 + code_len + 2 + exc_table_len * 8

# Read remaining sub-attrs of Code; fix LVT/LVTT entries that span to old code end
extra_attrs_count = read_u2(data, remaining_pos); remaining_pos += 2
extra_attrs_raw = bytearray(struct.pack('>H', extra_attrs_count))
for _ in range(extra_attrs_count):
    an_idx = read_u2(data, remaining_pos); remaining_pos += 2
    an_len = struct.unpack_from('>I', data, remaining_pos)[0]; remaining_pos += 4
    attr_body = bytearray(data[remaining_pos:remaining_pos+an_len])
    remaining_pos += an_len

    attr_name_e = entries.get(an_idx, ('?',))
    attr_name_str = attr_name_e[1].decode() if attr_name_e[0] == 'Utf8' else ''
    if attr_name_str in ('LocalVariableTable', 'LocalVariableTypeTable'):
        # Each LVT entry is 10 bytes: start_pc(2) length(2) name(2) desc(2) index(2)
        lv_count = struct.unpack_from('>H', attr_body, 0)[0]
        for j in range(lv_count):
            off = 2 + j * 10
            start_pc_j = struct.unpack_from('>H', attr_body, off)[0]
            length_j   = struct.unpack_from('>H', attr_body, off + 2)[0]
            if start_pc_j + length_j == code_len:
                new_len_j = len(new_code) - start_pc_j
                struct.pack_into('>H', attr_body, off + 2, new_len_j)
                print(f'  LVT fix [{attr_name_str}] entry {j}: start={start_pc_j} length {length_j} -> {new_len_j}')

    extra_attrs_raw += struct.pack('>HI', an_idx, an_len)
    extra_attrs_raw += attr_body

new_code_attr_body += extra_attrs_raw

# The Code attribute has a 6-byte header: attr_name(2) + attr_length(4)
# We need to find the attr_name index for 'Code' in the CP
code_attr_name_idx = None
for idx, e in entries.items():
    if e[0] == 'Utf8' and e[1] == b'Code':
        code_attr_name_idx = idx
        break
assert code_attr_name_idx is not None

# ── assemble patched class file ───────────────────────────────────────────────

# Original layout:
#   [0:8]         magic + version
#   [8:10]        old cp_count
#   [10:cp_end]   original CP entries
#   [cp_end:...]  rest of class
#
# The 'tick()' method's Code attribute starts at tick_code_pos and we need to
# replace it. The Code attr length field is at tick_code_pos - 4.

# Find the exact byte range of the Code attribute for tick()
# Code attr header is at tick_code_pos - 6: attr_name(2) + attr_len(4)
code_attr_header_start = tick_code_pos - 6  # relative to original data, after CP
# But everything after cp_end has been shifted by new_cp_bytes, so let's compute
# the offset relative to cp_end:
code_attr_header_offset = code_attr_header_start - cp_end  # offset from cp_end in original

# Old Code attribute total length (attr_name + attr_len + body)
old_code_attr_len_field = struct.unpack_from('>I', data, tick_code_pos - 4)[0]
old_code_attr_total = 6 + old_code_attr_len_field  # 2 (name) + 4 (len) + body

# New Code attribute total
new_code_attr_len = len(new_code_attr_body)
new_code_attr_header = struct.pack('>HI', code_attr_name_idx, new_code_attr_len)
new_code_attr_full = new_code_attr_header + bytes(new_code_attr_body)

# Build patched class:
# 1. magic + version (8 bytes)
# 2. new cp_count (2 bytes)
# 3. original CP entries (cp_end - 10 bytes)
# 4. new CP entries
# 5. rest of class up to tick Code attr
# 6. new tick Code attr
# 7. rest of class after old tick Code attr

part1 = data[0:8]
part2 = struct.pack('>H', new_cp_count)
part3 = data[10:cp_end]
part4 = bytes(new_cp_bytes)

# The tick code attr header starts at: cp_end + code_attr_header_offset
abs_code_attr_start = cp_end + code_attr_header_offset
abs_code_attr_end = abs_code_attr_start + old_code_attr_total

part5 = data[cp_end:abs_code_attr_start]
part6 = new_code_attr_full
part7 = data[abs_code_attr_end:]

new_class = part1 + part2 + part3 + part4 + part5 + part6 + part7

print(f'Old class size: {len(data)}, New class size: {len(new_class)}')
print(f'CP count: {cp_count} -> {new_cp_count}')

# ── verify with javap ─────────────────────────────────────────────────────────

tmpdir = tempfile.mkdtemp()
tmp_class = os.path.join(tmpdir, TARGET_CLASS)
with open(tmp_class, 'wb') as f:
    f.write(new_class)

result = subprocess.run(['javap', '-c', '-p', tmp_class], capture_output=True, text=True)
print('\njavap output for tick():')
lines = result.stdout.split('\n')
in_tick = False
for line in lines:
    if 'public void tick' in line:
        in_tick = True
    if in_tick:
        print(line)
        if line.strip() == '':
            break
if result.stderr:
    print('STDERR:', result.stderr[:500])

# ── write to zip ──────────────────────────────────────────────────────────────

# Read all existing entries
with zipfile.ZipFile(SOMNIA_ZIP, 'r') as zin:
    entries_data = {}
    for name in zin.namelist():
        entries_data[name] = zin.read(name)

entries_data[TARGET_CLASS] = new_class

with zipfile.ZipFile(SOMNIA_ZIP, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
    for name, d in entries_data.items():
        zout.writestr(name, d)

print(f'\nWrote patched {TARGET_CLASS} to {SOMNIA_ZIP}')
print('Done!')
