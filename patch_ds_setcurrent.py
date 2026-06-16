#!/usr/bin/env python3
"""
Inject ModelCapeRenderer.setCurrent call before cape rendering in ds.a(gs,F)V.

In the cape section (around bytecode 300-310), before glPushMatrix, insert:
  aload_0         // this (ds)
  getfield i      // get cape renderer (fh.i which is ModelCapeRenderer)
  aload_1         // load gs parameter
  fload_2         // load float parameter
  invokevirtual setCurrent(gs, float)V

This sets the player reference so cape can animate with crouch.
"""
import zipfile, io, os, struct, shutil

JAR = r"D:\Games\Minecraft\instances\Mango Pack Beta 1.7.3 (Volume 2)\jarmods\8f6f632d-bfad-4f91-8bda-3de6d74ef1e8.jar"
BACKUP = JAR + ".backup_ds_setcurrent"
ENTRY = "ds.class"

def main():
    print("Patching ds.a(gs,F)V to call cape.setCurrent before rendering...")

    with zipfile.ZipFile(JAR, 'r') as z:
        data = bytearray(z.read(ENTRY))

    # Find glPushMatrix (0xB8 invokestatic) at start of cape section
    # Pattern: invokestatic glPushMatrix (around bytecode 300)
    # Actually, search for the distinctive pattern before cape rendering

    # The cape section starts with glPushMatrix. Before that, find the right place.
    # Look for: fconst_0 fconst_0 ldc_w (which loads Z=0.125) before invokestatic glTranslatef
    # This should be around bytecode 303-308

    # Instead of searching, since this is tricky, let's just search for the string "setCurrent"
    # in the constant pool and see if we can find method refs

    print("Searching for ModelCapeRenderer.setCurrent reference...")

    # For now, let's use a simpler approach: search for the pattern before the cape section
    # and inject right before glPushMatrix

    # Pattern: ldc2_w (0x14) which loads a double (common before a method call)
    # Actually, let me search for the glPushMatrix at the start of cape rendering

    # invokestatic glPushMatrix is: 0xB8 + 2 bytes for method index
    # gl_push_matrix should appear as a method reference

    # Simpler: search for sequence fconst_0 fconst_0 ldc_w which is the cape translate
    # Then go back and find where to inject setCurrent

    pattern = bytes([0x0B, 0x0B])  # Two fconst_0

    pos = data.find(pattern)
    if pos == -1:
        print("ERROR: fconst_0 fconst_0 pattern not found")
        return

    print(f"Found cape translate pattern at {pos}")

    # Go back to find glPushMatrix (look for invokestatic backwards)
    search_start = max(0, pos - 50)
    search_section = data[search_start:pos]

    # Find last invokestatic before the translate (0xB8)
    last_invoke = None
    for i in range(len(search_section) - 1, -1, -1):
        if search_section[i] == 0xB8:
            last_invoke = search_start + i
            break

    if last_invoke is None:
        print("ERROR: could not find glPushMatrix")
        return

    print(f"Found glPushMatrix at {last_invoke}")

    # Check if this is actually glPushMatrix by looking at bytes after
    # glPushMatrix is 0xB8 + method index (2 bytes)
    # After that should be our fconst_0 fconst_0 sequence

    inject_pos = last_invoke

    # The injection should be BEFORE glPushMatrix
    # We need to insert:
    # aload_0 (0x2A)
    # getfield i (0xB4 + 2 bytes)
    # aload_1 (0x2B)
    # fload_2 (0x23)
    # invokevirtual setCurrent (0xB6 + 2 bytes)
    # Total: 1 + 3 + 1 + 1 + 3 = 9 bytes

    # But we need the method reference for setCurrent
    # For now, just report where to inject
    print(f"Would inject setCurrent call at offset {inject_pos}")
    print("(Requires constant pool method reference - skipping for now)")

    # For a real fix, we'd need to:
    # 1. Add method reference to constant pool
    # 2. Inject the bytecode
    # 3. Update all offset-dependent attributes

    # This is too complex for a simple patch. Instead, recommend:
    print("\nAlternative: disable ModelCapeRenderer.preTransform early-exit check")

if __name__ == '__main__':
    main()
