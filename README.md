# dts-reconstruct

Many OEMs do not release the original DTS source files.
While `dtc` can decompile DTBs, the output is often difficult to read and modify because of fixups, phandles, and fragmented overlays.

This repo contains scripts to reconstruct and clean up decompiled DTS files into a more reusable format.

## Requirements

- `python3`
- `gcc`
- `dtc` (`device-tree-compiler`)

## Transform Script

### Features
- Rebuilds decompiled overlay fragments
- Resolves fixups and local phandles
- Restores labels where possible

### Preparing Input Files

The script requires a decompiled DTS file.

If you only have a DTS file, first compile it into a DTB and decompile it again using `dtc`.

### Build DTB

```bash
# GCC preprocessing
gcc -E -nostdinc -undef -x assembler-with-cpp "arch/arm64/boot/dts/samsung/input.dts" > "input-gcc.dts"

# Build DTB
dtc -@ -I dts -O dtb -o "input.dtb" "input-gcc.dts"
```

### Decompile DTB

Do not use the `-s` option with `dtc`.
Sorted output changes the layout and can break reconstruction.

```bash
dtc -I dtb -O dts -o "input-decompiled.dts" "input.dtb"
```

### Usage

```bash
python3 scripts/transform_dts.py -i "input-decompiled.dts" -o "output.dts"
```

It is recommended to compile and decompile the reconstructed DTS again and compare the decompiled output-decompiled.dts against the original input-decompiled.dts.

## Notes

- Tested mainly on Samsung Qualcomm Android device trees
- More DTS cleanup and reconstruction scripts may be added later
