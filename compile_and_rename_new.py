import struct, subprocess, os

def main():
    classpath_entries = [
        "minecraft-b1.7.3-client.jar",
        "SmartMoving for ModLoader",
        "SmartMoving for ModLoader.zip",
        "..\\.minecraft\\agent\\ears-vanilla-b1.7.3-1.4.7.jar",
        "..\\jarmods\\8f49a71e-2bd4-4601-a3db-a769de5d72e3.jar",
        "..\\.minecraft\\bin\\lwjgl.jar",
        ".",
    ]
    classpath = ";".join(path for path in classpath_entries if os.path.exists(path))

    # 1. Compile
    cmd = [
        "javac",
        "-source", "1.8",
        "-target", "1.8",
        "-cp", classpath,
        "EarSkinCompat.java"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("Compilation failed:")
        print(res.stderr)
        return
    print("Compilation successful")

    # 2. Rename class in bytecode
    with open("EarSkinCompat.class", "rb") as f:
        data = bytearray(f.read())

    # Parse and rewrite CP
    pos = 0
    magic, minor, major = struct.unpack_from(">IHH", data, pos)
    assert magic == 0xCAFEBABE
    pos += 8

    cp_count = struct.unpack_from(">H", data, pos)[0]
    pos += 2

    # We will build a new constant pool
    new_cp = bytearray()
    i = 1
    while i < cp_count:
        tag = data[pos]
        if tag == 1: # Utf8
            length = struct.unpack_from(">H", data, pos + 1)[0]
            val = data[pos + 3 : pos + 3 + length]
            if val == b"EarSkinCompat":
                new_val = b"farn/ears_compat/EarSkinCompat"
                print(f"Renaming CP entry #{i} from EarSkinCompat to farn/ears_compat/EarSkinCompat")
                new_cp += bytes([1]) + struct.pack(">H", len(new_val)) + new_val
            else:
                new_cp += data[pos : pos + 3 + length]
            pos += 3 + length
            i += 1
        elif tag in (7, 8):
            new_cp += data[pos : pos + 3]
            pos += 3
            i += 1
        elif tag in (9, 10, 11, 12):
            new_cp += data[pos : pos + 5]
            pos += 5
            i += 1
        elif tag in (3, 4):
            new_cp += data[pos : pos + 5]
            pos += 5
            i += 1
        elif tag in (5, 6):
            new_cp += data[pos : pos + 9]
            pos += 9
            i += 2
        else:
            raise ValueError(f"Unknown tag {tag} at pos {pos}")

    # Reassemble class file
    patched_data = data[:8] + struct.pack(">H", cp_count) + new_cp + data[pos:]

    # Ensure farn/ears_compat folder exists
    os.makedirs(os.path.join("farn", "ears_compat"), exist_ok=True)
    out_path = os.path.join("farn", "ears_compat", "EarSkinCompat.class")
    with open(out_path, "wb") as f:
        f.write(patched_data)
    print(f"Patched and saved to {out_path}")

    # Verification with javap
    res = subprocess.run(["javap", "-c", "-p", out_path], capture_output=True, text=True)
    print("\nVerified output of javap:")
    print("\n".join(res.stdout.splitlines()[:15]))

if __name__ == '__main__':
    main()
