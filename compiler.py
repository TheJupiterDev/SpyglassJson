import os
import re
import json
from typing import Any, Dict, List, Optional

# --- Helper Utilities ---
def strip_comments(content: str) -> str:
    lines = content.splitlines()
    stripped = []
    for line in lines:
        line = re.sub(r'//.*', '', line).strip()
        if line:
            stripped.append(line)
    return '\n'.join(stripped)

def strip_attributes(content: str) -> str:
    return re.sub(r'#\[.*?\]\s*', '', content, flags=re.DOTALL)

def parse_typed_value(value: str) -> Dict[str, Any]:
    if re.match(r'^".*"$', value):
        return {"const": value.strip('"'), "type": "string"}
    if value in ('true', 'false'):
        return {"const": value == 'true', "type": "boolean"}
    if re.match(r'^-?\d+(\.\d+)?([eE][+-]?\d+)?[bBsSlLfFdD]?$' , value):
        if value[-1].lower() in 'bsil':
            return {"const": int(value[:-1]), "type": "integer"}
        return {"const": float(value.rstrip('dDfF')), "type": "number"}
    return {"const": value}

def parse_range(range_str: str) -> Dict[str, int]:
    result = {}
    match = re.match(r'@\s*(\d+)?\.\.(\d+)?', range_str)
    if match:
        if match.group(1):
            result['minItems'] = int(match.group(1))
        if match.group(2):
            result['maxItems'] = int(match.group(2))
    return result

def resolve_type(value: str, current_file: str, type_map: Dict[str, str]) -> Dict[str, Any]:
    value = value.strip()
    range_match = re.search(r'@\s*[\d.<]+', value)
    range_part = value[range_match.start():] if range_match else ''
    value = value[:range_match.start()].strip() if range_match else value

    if value.startswith('(') and value.endswith(')') and '|' in value:
        types = [resolve_type(part, current_file, type_map) for part in value[1:-1].split('|')]
        return {"anyOf": types}

    if re.match(r'^\[.*\]$', value):
        inner = value[1:-1].strip()
        items = resolve_type(inner, current_file, type_map)
        array_schema = {"type": "array", "items": items}
        array_schema.update(parse_range(range_part))
        return array_schema

    if value in ('true', 'false') or value.startswith('"'):
        return parse_typed_value(value)

    type_map_builtins = {
        'string': {"type": "string"},
        'boolean': {"type": "boolean"},
        'byte': {"type": "integer"},
        'short': {"type": "integer"},
        'int': {"type": "integer"},
        'long': {"type": "integer"},
        'float': {"type": "number"},
        'double': {"type": "number"},
        'any': {},
    }
    if value in type_map_builtins:
        return type_map_builtins[value]

    ref_file = type_map.get(value, current_file)
    rel_path = os.path.relpath(ref_file, os.path.dirname(current_file)).replace('\\', '/')
    return {"$ref": f"{rel_path}.json#/definitions/{value}"}

def parse_struct(content: str, current_file: str, type_map: Dict[str, str]) -> Dict[str, Any]:
    content = strip_attributes(content.strip('{}').strip())
    lines = [line.strip() for line in content.split(',') if line.strip()]
    properties = {}
    required = []
    for line in lines:
        if line.startswith('...'):
            continue
        parts = line.split(':')
        if len(parts) != 2:
            continue
        key, type_part = parts[0].strip(), parts[1].strip()
        optional = key.endswith('?')
        key = key.rstrip('?')
        resolved = resolve_type(type_part, current_file, type_map)
        properties[key] = resolved
        if not optional:
            required.append(key)
    struct_schema = {"type": "object", "properties": properties}
    if required:
        struct_schema["required"] = required
    return struct_schema

def parse_enum(content: str) -> Dict[str, Any]:
    content = content.strip('{}').strip()
    values = []
    for line in content.split(','):
        if '=' not in line:
            continue
        _, val = map(str.strip, line.split('=', 1))
        parsed = parse_typed_value(val)
        values.append(parsed["const"])
    return {"enum": values}

# --- Compiler ---
class McdocCompiler:
    def __init__(self, base_path: str, output_root: str):
        self.base_path = os.path.abspath(base_path)
        self.output_root = os.path.abspath(output_root)
        self.type_map: Dict[str, str] = {}

    def compile(self) -> None:
        # First pass: collect all type names and their file paths
        for root, _, files in os.walk(self.base_path):
            for file in files:
                if file.endswith('.mcdoc'):
                    full_path = os.path.join(root, file)
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = strip_attributes(strip_comments(f.read()))
                        structs = re.findall(r'struct\s+(\w+)\s*\{', content)
                        enums = re.findall(r'enum\s*\(\w+\)\s+(\w+)\s*\{', content)
                        for t in structs + enums:
                            self.type_map[t] = os.path.splitext(os.path.relpath(full_path, self.base_path))[0]

        # Second pass: process and write schemas
        for root, _, files in os.walk(self.base_path):
            for file in files:
                if file.endswith('.mcdoc'):
                    input_path = os.path.join(root, file)
                    self._process_file(input_path)

    def _process_file(self, path: str) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read()

        content = strip_attributes(strip_comments(raw))
        current_rel_path = os.path.splitext(os.path.relpath(path, self.base_path))[0]
        structs = re.finditer(r'struct\s+(\w+)\s*\{(.*?)\}', content, re.DOTALL)
        enums = re.finditer(r'enum\s*\(\w+\)\s+(\w+)\s*\{(.*?)\}', content, re.DOTALL)

        out_path = os.path.join(self.output_root, current_rel_path + '.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        schema_defs = {}
        for match in structs:
            name, body = match.groups()
            schema_defs[name] = parse_struct(body, current_rel_path, self.type_map)

        for match in enums:
            name, body = match.groups()
            schema_defs[name] = parse_enum(body)

        if schema_defs:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "$id": f"{current_rel_path}.json",
                    "definitions": schema_defs
                }, f, indent=2)
            print(f"✅ Wrote schema: {out_path}")

# --- CLI ---
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Compile full mcdoc schema to JSON Schema.')
    parser.add_argument('mcdoc_path', help='Path to the root directory containing .mcdoc files (e.g., java/)')
    parser.add_argument('--output_root', help='Root output directory (e.g., koffee/)', default='koffee')
    args = parser.parse_args()

    compiler = McdocCompiler(args.mcdoc_path, args.output_root)
    compiler.compile()