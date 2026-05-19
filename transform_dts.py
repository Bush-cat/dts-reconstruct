#!/usr/bin/env python3

import re
import os
from collections import defaultdict

def tree_factory(): return {'labels': [], 'props': [], 'children': defaultdict(tree_factory)}

def parse_decompiled_dts(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Parse root properties
    root_props = []
    in_root = False
    brace_level = 0
    for line in content.splitlines():
        s = line.strip()
        if s == '/ {':
            in_root = True
            brace_level = 1
            continue
        if in_root:
            if s.endswith('{'):
                brace_level += 1
            elif s == '};':
                brace_level -= 1
                if brace_level == 0:
                    in_root = False
            elif brace_level == 1 and s.endswith(';'):
                if not s.startswith('//') and not s.startswith('/*'):
                    root_props.append(s)

    # Parse __symbols__ (labels)
    symbols = {}
    path_to_labels = defaultdict(list)
    in_symbols = False
    for line in content.splitlines():
        if '__symbols__ {' in line:
            in_symbols = True
            continue
        if in_symbols and '};' in line:
            in_symbols = False
            continue
        if in_symbols and '=' in line:
            label, path = line.split('=', 1)
            label = label.strip()
            path = path.strip().strip('";')
            symbols[label] = path
            path_to_labels[path].append(label)

    # Parse __fixups__ (references)
    fixups = {}
    target_fixups = {}
    in_fixups = False
    fixup_arrays = {}
    fixup_paths = []

    for line in content.splitlines():
        if '__fixups__ {' in line:
            in_fixups = True
            continue
        if in_fixups and '};' in line:
            in_fixups = False
            continue
        if in_fixups and '=' in line:
            label, ps = line.split('=', 1)
            label = label.strip()
            paths = re.findall(r'"([^"]+)"', ps)
            fixup_arrays[label] = paths
            fixup_paths.append(paths)
            for p in paths:
                if p.endswith(':target:0'):
                    frag = p.split(':')[0]
                    target_fixups[frag] = label
                else:
                    fixups[p] = label

    # Parse __local_fixups__ (offsets)
    local_fixups = defaultdict(list)
    m = re.search(r'__local_fixups__ \{(.*?)\n\t\};', content, re.DOTALL)
    if m:
        lf_body = m.group(1)
        path_stack = []
        path_str_stack = [""]
        for line in lf_body.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.endswith('{'):
                nm = re.match(r'^([\w,:-]+: )?([\w,@\.-]+) \{', s)
                if nm:
                    node_name = nm.group(2)
                    path_stack.append(node_name)
                    path_str_stack.append(path_str_stack[-1] + "/" + node_name)
                continue
            if s == '};':
                if len(path_stack) > 0:
                    path_stack.pop()
                    path_str_stack.pop()
                continue
            if s.endswith(';'):
                if ' = <' in s:
                    prop_m = re.search(r'^([\w,#,-]+) = <(.*)>;', s)
                    if prop_m:
                        prop = prop_m.group(1)
                        vals = prop_m.group(2).split()
                        offsets = []
                        for v in vals:
                            try:
                                offsets.append(int(v, 16))
                            except ValueError:
                                pass
                        local_fixups[(path_str_stack[-1], prop)] = offsets

    # Collect phandle values
    node_phandles = {}
    path_stack = []
    in_meta = False
    for line in content.splitlines():
        s = line.strip()
        if s.startswith('__fixups__ {') or s.startswith('__symbols__ {') or s.startswith('__local_fixups__ {'):
            in_meta = True
            continue
        if in_meta and s == '};':
            in_meta = False
            continue
        if in_meta:
            continue

        if s.endswith('{'):
            nm = re.match(r'^([\w,:-]+: )?([\w,@\.-]+) \{', s)
            if nm:
                path_stack.append(nm.group(2))
            else:
                path_stack.append('UNKNOWN')
        elif s == '};':
            if path_stack:
                path_stack.pop()
        elif s.startswith('phandle = <'):
            pm = re.search(r'phandle = <(0x[0-9a-fA-F]+)>;', s)
            if pm:
                path = '/' + '/'.join(path_stack)
                node_phandles[path] = int(pm.group(1), 16)

    # Remove metadata sections
    content_for_frags = re.sub(r'^\t__local_fixups__ \{.*?^\t\};', '', content, flags=re.MULTILINE|re.DOTALL)
    content_for_frags = re.sub(r'^\t__fixups__ \{.*?^\t\};', '', content_for_frags, flags=re.MULTILINE|re.DOTALL)
    content_for_frags = re.sub(r'^\t__symbols__ \{.*?^\t\};', '', content_for_frags, flags=re.MULTILINE|re.DOTALL)

    # Extract fragments
    def extract_frags():
        frags = []
        pos = 0
        while True:
            match = re.search(r'^\t(fragment@[\w-]+) \{', content_for_frags[pos:], re.MULTILINE)
            if not match:
                break
            fid = match.group(1)
            start = pos + match.start()
            brace_level = 0
            i = start + (match.end() - match.start()) - 1
            while i < len(content_for_frags):
                if content_for_frags[i] == '{':
                    brace_level += 1
                elif content_for_frags[i] == '}':
                    brace_level -= 1
                i += 1
                if brace_level == 0:
                    break
            body = content_for_frags[start:i]
            frags.append((fid, body))
            pos = i
        return frags

    full_tree = defaultdict(tree_factory)
    phandle_to_label = {}

    # Build tree representation
    for fid, body in extract_frags():
        root = full_tree[fid]

        path_stack = [root]
        path_str_stack = [f"/{fid}"]

        for line in body.splitlines():
            s = line.strip()
            if not s or s.startswith('fragment@'):
                continue

            if s.endswith('{'):
                nm = re.match(r'^([\w,:-]+: )?([\w,@\.-]+) \{', s)
                if nm:
                    node_name = nm.group(2)
                    new_node = path_stack[-1]['children'][node_name]
                    path_stack.append(new_node)
                    path_str_stack.append(path_str_stack[-1] + "/" + node_name)

                    # Attach labels
                    for label in path_to_labels.get(path_str_stack[-1], []):
                        if label not in new_node['labels']:
                            new_node['labels'].append(label)
                continue

            if s == '};':
                if len(path_stack) > 1:
                    path_stack.pop()
                    path_str_stack.pop()
                continue

            if s.endswith(';'):
                # Convert phandle values into labels
                if 'phandle =' in s:
                    phm = re.search(r'phandle = <(0x[0-9a-fA-F]+)>;', s)
                    if phm:
                        ph_val = int(phm.group(1), 16)
                        if path_str_stack[-1] in path_to_labels:
                            phandle_to_label[ph_val] = path_to_labels[path_str_stack[-1]][0]
                        else:
                            base_name = path_str_stack[-1].split('/')[-1].split('@')[0]
                            base_name = base_name.replace(',', '_').replace('-', '_')
                            syn_label = f"local_ph_{base_name}_{hex(ph_val)}"
                            phandle_to_label[ph_val] = syn_label
                            if syn_label not in path_stack[-1]['labels']:
                                path_stack[-1]['labels'].append(syn_label)
                    continue

                prop_entry = (s, path_str_stack[-1])
                if prop_entry not in path_stack[-1]['props']:
                    path_stack[-1]['props'].append(prop_entry)

    return full_tree, fixups, target_fixups, local_fixups, phandle_to_label, node_phandles, root_props

# Replace phandle values with labels where possible
def resolver(line, node_path, fixups, local_fixups, phandle_to_label):
    if ' = <' not in line:
        return line
    m = re.search(r'^([\w,#,-]+) = <(.*)>;', line)
    if not m:
        return line
    prop, vals = m.group(1), m.group(2).split()
    res = []

    local_offsets = local_fixups.get((node_path, prop), [])

    for i, v in enumerate(vals):
        offset = i * 4
        key = f"{node_path}:{prop}:{offset}"
        if key in fixups:
            res.append(f"&{fixups[key]}")
        elif offset in local_offsets:
            try:
                vi = int(v, 16)
                if vi in phandle_to_label:
                    res.append(f"&{phandle_to_label[vi]}")
                else:
                    res.append(f"&UNKNOWN_PHANDLE_{hex(vi)}")
            except ValueError:
                res.append(v)
        else:
            res.append(v)
    return f"{prop} = <{' '.join(res)}>; "

# Recursively write DTS nodes
def walk_tree(output, node_dict, indent, fixups, local_fixups, phandle_to_label, path_str, node_phandles):
    for name, child in node_dict.get('children', {}).items():
        labels_str = "".join([f"{lbl}: " for lbl in child['labels']])
        output.append("\t" * indent + f"{labels_str}{name} {{")

        child_path = path_str + "/" + name if path_str else "/" + name

        props = child.get('props', [])
        for p_raw, p_path in props:
            output.append("\t" * (indent + 1) + resolver(p_raw, p_path, fixups, local_fixups, phandle_to_label).strip())

        walk_tree(output, child, indent + 1, fixups, local_fixups, phandle_to_label, child_path, node_phandles)
        output.append("\t" * indent + "};")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input', required=True, help="Input decompiled DTS file")
    parser.add_argument('-o', '--output', required=True, help="Output reconstructed DTS file")
    args = parser.parse_args()

    in_file = args.input
    out_file = args.output
    os.makedirs(os.path.dirname(out_file) or '.', exist_ok=True)

    full_tree, fixups, target_fixups, local_fixups, phandle_to_label, node_phandles, root_props = parse_decompiled_dts(in_file)

    output = ["/dts-v1/;\n/plugin/;\n"]

    # Rebuild root node
    output.append("/ {")
    for prop in root_props:
        output.append(f"\t{prop}")
    output.append("};\n")


    for fid, root in full_tree.items():
        parts = fid.split('@')
        is_numeric = len(parts) > 1 and parts[1].isdigit()

        target_path = None
        target_label = None
        for p_raw, p_path in root.get('props', []):
            if p_raw.startswith('target-path ='):
                m = re.search(r'target-path = "([^"]+)"', p_raw)
                if m:
                    target_path = m.group(1)

        if f"/{fid}" in target_fixups:
            target_label = target_fixups[f"/{fid}"]

        overlay = root.get('children', {}).get('__overlay__')

        # Handle named fragments
        if not is_numeric:
            output.append("/ {")
            output.append(f"\t{fid} {{")
            for p_raw, p_path in root.get('props', []):
                output.append("\t\t" + resolver(p_raw, p_path, fixups, local_fixups, phandle_to_label).strip())
            walk_tree(output, root, 2, fixups, local_fixups, phandle_to_label, f"/{fid}", node_phandles)
            output.append("\t};")
            output.append("};\n")

        # Handle overlay fragments
        elif overlay:
            if target_label:
                output.append(f"&{target_label} {{")
                for p_raw, p_path in overlay.get('props', []):
                    output.append("\t" + resolver(p_raw, p_path, fixups, local_fixups, phandle_to_label).strip())
                walk_tree(output, overlay, 1, fixups, local_fixups, phandle_to_label, f"/{fid}/__overlay__", node_phandles)
                output.append("};\n")
            elif target_path:
                if target_path == "/":
                    output.append("/ {")
                else:
                    output.append(f"&{{{target_path}}} {{")
                for p_raw, p_path in overlay.get('props', []):
                    output.append("\t" + resolver(p_raw, p_path, fixups, local_fixups, phandle_to_label).strip())
                walk_tree(output, overlay, 1, fixups, local_fixups, phandle_to_label, f"/{fid}/__overlay__", node_phandles)
                output.append("};\n")
            else:
                output.append("/ {")
                output.append(f"\t{fid} {{")
                for p_raw, p_path in root.get('props', []):
                    output.append("\t\t" + resolver(p_raw, p_path, fixups, local_fixups, phandle_to_label).strip())
                walk_tree(output, root, 2, fixups, local_fixups, phandle_to_label, f"/{fid}", node_phandles)
                output.append("\t};")
                output.append("};\n")
        else:
            output.append("/ {")
            output.append(f"\t{fid} {{")
            for p_raw, p_path in root.get('props', []):
                output.append("\t\t" + resolver(p_raw, p_path, fixups, local_fixups, phandle_to_label).strip())
            walk_tree(output, root, 2, fixups, local_fixups, phandle_to_label, f"/{fid}", node_phandles)
            output.append("\t};")
            output.append("};\n")

    with open(out_file, 'w') as f:
        f.write("\n".join(output))

if __name__ == '__main__':
    main()
