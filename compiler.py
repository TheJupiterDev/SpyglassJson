# Main script to compile mcdocs (specifically vanilla-mcdoc, but may work with others) into JSON Schemas
# Usage - python compiler.py FOLDER-FILLED-WITH-MCDOCS/ --target-version 1.21.5

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
    return re.sub(r'#\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]\s*', '', content)

def parse_attributes(line: str) -> Dict[str, str]:
    """Parse attribute decorators into a dictionary."""
    attributes = {}
    matches = re.finditer(r'#\[(\w+)="([^"]+)"\]', line)
    for match in matches:
        key, value = match.groups()
        attributes[key] = value
    return attributes

def should_include_field(attributes: Dict[str, str], target_version: str) -> bool:
    """
    Determine if a field should be included based on version attributes.
    Returns True if the field should be included for the target version.
    """
    if 'since' in attributes:
        if target_version < attributes['since']:
            return False
    if 'until' in attributes:
        if target_version >= attributes['until']:
            return False
    return True

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

def resolve_type(value: str, current_file_no_ext: str, type_map: Dict[str, str]) -> Any:
    value = value.strip()

    if value == '()':
        return False

    range_match = re.search(r'@\s*[\d.<]+', value)
    range_part = value[range_match.start():] if range_match else ''
    value = value[:range_match.start()].strip() if range_match else value

    if value.startswith('(') and value.endswith(')') and '|' in value:
        types = []
        for part in split_union_types(value[1:-1]):
            # Skip empty parts
            if not part.strip():
                continue
            resolved = resolve_type(part.strip(), current_file_no_ext, type_map)
            if resolved:  # Only add non-None values
                types.append(resolved)
        return {"anyOf": types} if types else {}


    bracket_match = re.match(r'^(\[+)(.*?)(\]+)$', value)
    if bracket_match and len(bracket_match.group(1)) == len(bracket_match.group(3)):
        depth = len(bracket_match.group(1))
        inner = bracket_match.group(2).strip()
        items = resolve_type(inner, current_file_no_ext, type_map)
        for _ in range(depth):
            items = {"type": "array", "items": items}
        items.update(parse_range(range_part))
        return items


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

    ref_file_no_ext = type_map.get(value)
    if not ref_file_no_ext:
        return {"$ref": f"#/definitions/{value}"}  # fallback if unknown

    if ref_file_no_ext == current_file_no_ext:
        return {"$ref": f"#/definitions/{value}"}

    return {"$ref": f"output/{ref_file_no_ext}.json#/definitions/{value}"}

def parse_struct(content: str, current_file_no_ext: str, type_map: Dict[str, str], target_version: str = "1.21.5") -> Dict[str, Any]:
    lines = [line.strip() for line in content.strip('{}').split(',') if line.strip()]
    
    properties = {}
    required = []
    all_of = []
    discriminator_info = []

    for line in lines:
        if line.startswith('...'):
            # ... handle spread operator as before ...
            continue

        # Extract attributes before processing the line
        attributes = parse_attributes(line)
        # Strip attributes for further processing
        clean_line = strip_attributes(line)

        # Skip this field if it shouldn't be included for the target version
        if not should_include_field(attributes, target_version):
            continue

        parts = clean_line.split(':')
        if len(parts) != 2:
            continue

        key, type_part = parts[0].strip(), parts[1].strip()
        optional = key.endswith('?')
        key = key.rstrip('?')
        resolved = resolve_type(type_part, current_file_no_ext, type_map)

        if isinstance(resolved, dict):
            resolved.setdefault("title", key)

        properties[key] = resolved
        if not optional:
            required.append(key)

    base_object = {"type": "object", "properties": properties}
    if required:
        base_object["required"] = required

    if not all_of:
        return base_object

    all_of.insert(0, base_object)
    result = {"allOf": all_of}

    # Attach discriminator if valid and consistent
    if discriminator_info:
        field_names = {field for field, _ in discriminator_info}
        if len(field_names) == 1:
            discriminator_field = field_names.pop()
            mapping = {ref.split('/')[-1]: ref for _, ref in discriminator_info}
            result["discriminator"] = {
                "propertyName": discriminator_field,
                "mapping": mapping
            }

    return result

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

def parse_use_statements(content: str, current_file_no_ext: str) -> Dict[str, str]:
    use_pattern = re.compile(r'use\s+(?P<path>(::|super::|[\w:]+)+)(?:\s+as\s+(?P<alias>\w+))?')
    uses = {}
    current_parts = current_file_no_ext.split(os.sep)

    for match in use_pattern.finditer(content):
        path = match.group('path')
        alias = match.group('alias')
        parts = []

        if path.startswith('::'):
            parts = path[2:].split('::')
        else:
            scope = current_parts[:-1]
            for part in path.split('::'):
                if part == 'super':
                    if scope:
                        scope.pop()
                else:
                    scope.append(part)
            parts = scope

        typename = parts[-1]
        resolved_path = '/'.join(parts[:-1]) if len(parts) > 1 else ''
        uses[alias or typename] = resolved_path

    return uses

def split_union_types(s: str) -> List[str]:
    parts = []
    current = ''
    depth = 0
    for c in s:
        if c == '|' and depth == 0:
            parts.append(current.strip())
            current = ''
        else:
            current += c
            if c in '([{':
                depth += 1
            elif c in ')]}':
                depth = max(0, depth - 1)
    if current.strip():
        parts.append(current.strip())
    return parts
                
# --- Compiler ---
class McdocCompiler:
    def __init__(self, base_path: str, output_root: str, target_version: str = "1.21.5"):
        self.base_path = os.path.abspath(base_path)
        self.output_root = os.path.abspath(os.path.join('output', output_root))
        self.type_map: Dict[str, str] = {}
        self.target_version = target_version

    def compile(self) -> None:
        for root, _, files in os.walk(self.base_path):
            for file in files:
                if file.endswith('.mcdoc'):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.splitext(os.path.relpath(full_path, self.base_path))[0]
                    out_path = os.path.join(self.output_root, rel_path)
                    self._collect_types(full_path, out_path.replace(os.sep, '/'))

        for root, _, files in os.walk(self.base_path):
            for file in files:
                if file.endswith('.mcdoc'):
                    input_path = os.path.join(root, file)
                    self._process_file(input_path)

    def _collect_types(self, full_path: str, out_path_no_ext: str):
        with open(full_path, 'r', encoding='utf-8') as f:
            content = strip_attributes(strip_comments(f.read()))
            structs = re.findall(r'struct\s+(\w+)\s*\{', content)
            enums = re.findall(r'enum\s*\(\w+\)\s+(\w+)\s*\{', content)
            
            rel_path_no_ext = os.path.relpath(full_path, self.base_path)
            rel_path_no_ext = os.path.splitext(rel_path_no_ext)[0].replace(os.sep, '/')

            for t in structs + enums:
                self.type_map[t] = rel_path_no_ext

    def _process_file(self, path: str) -> None:
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read()

        content = strip_attributes(strip_comments(raw))
        rel_path_no_ext = os.path.splitext(os.path.relpath(path, self.base_path))[0].replace(os.sep, '/')
        uses = parse_use_statements(content, rel_path_no_ext)
        self.type_map.update(uses)

        structs = re.finditer(r'struct\s+(\w+)\s*\{(.*?)\}', content, re.DOTALL)
        enums = re.finditer(r'enum\s*\(\w+\)\s+(\w+)\s*\{(.*?)\}', content, re.DOTALL)
        types = re.finditer(r'type\s+(\w+)\s*=\s*(\((?:[^()]*|\([^()]*\))*\)|[^\n]*)', content, re.DOTALL)

        out_file = os.path.join(self.output_root, rel_path_no_ext + '.json')
        os.makedirs(os.path.dirname(out_file), exist_ok=True)

        schema_defs = {}

        for match in structs:
            name, body = match.groups()
            schema_defs[name] = parse_struct(body, rel_path_no_ext, self.type_map, self.target_version)

        for match in enums:
            name, body = match.groups()
            schema_defs[name] = parse_enum(body)

        for match in types:
            name, body = match.groups()
            body = body.strip()

            if body.startswith('(') and body.endswith(')'):
                parts = split_union_types(body[1:-1])
                refs = []
                for part in parts:
                    # If it's a full struct definition, try to extract the name
                    if part.startswith('struct'):
                        struct_match = re.match(r'struct(?:\s+\w+)?\s*\{(.*)\}', part, re.DOTALL)
                        if struct_match:
                            refs.append(parse_struct('{' + struct_match.group(1) + '}', rel_path_no_ext, self.type_map))
                        else:
                            print(f"⚠️ Could not parse inline struct: {part}")
                    else:
                        refs.append(resolve_type(part, rel_path_no_ext, self.type_map))


                schema_defs[name] = { "anyOf": refs }
            else:
                schema_defs[name] = resolve_type(body, rel_path_no_ext, self.type_map)

        if schema_defs:
            with open(out_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "definitions": schema_defs
                }, f, indent=2)
            print(f"✅ Wrote schema: {out_file}")

# --- CLI ---
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Compile full mcdoc schema to JSON Schema.')
    parser.add_argument('mcdoc_path', help='Path to the root directory containing .mcdoc files (e.g., java/)')
    parser.add_argument('--target-version', default="1.21.5", help='Target Minecraft version (default: 1.21.5)')
    args = parser.parse_args()

    compiler = McdocCompiler(args.mcdoc_path, 'java', args.target_version)
    compiler.compile()