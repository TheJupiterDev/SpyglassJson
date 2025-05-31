#!/usr/bin/env python3
"""
Full Mcdoc to JSON Compiler

A comprehensive compiler that converts mcdoc files and folder structures into JSON schemas.
Based on the official mcdoc specification from spyglassmc.com.

Usage:
    python mcdoc_compiler.py <input_folder> <output_folder>
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum

# Token types for lexical analysis
class TokenType(Enum):
    # Literals
    INTEGER = "INTEGER"
    FLOAT = "FLOAT" 
    STRING = "STRING"
    BOOLEAN = "BOOLEAN"
    RESOURCE_LOCATION = "RESOURCE_LOCATION"
    IDENTIFIER = "IDENTIFIER"
    
    # Keywords
    STRUCT = "struct"
    ENUM = "enum"
    TYPE = "type"
    USE = "use"
    DISPATCH = "dispatch"
    SUPER = "super"
    ANY = "any"
    BOOLEAN_TYPE = "boolean"
    STRING_TYPE = "string"
    BYTE = "byte"
    SHORT = "short"
    INT = "int"
    LONG = "long"
    FLOAT_TYPE = "float"
    DOUBLE = "double"
    TRUE = "true"
    FALSE = "false"
    TO = "to"
    
    # Special keys
    FALLBACK = "%fallback"
    NONE = "%none"
    UNKNOWN = "%unknown"
    KEY = "%key"
    PARENT = "%parent"
    
    # Symbols
    LBRACE = "{"
    RBRACE = "}"
    LBRACKET = "["
    RBRACKET = "]"
    LPAREN = "("
    RPAREN = ")"
    LANGLE = "<"
    RANGLE = ">"
    COLON = ":"
    SEMICOLON = ";"
    COMMA = ","
    DOT = "."
    QUESTION = "?"
    PIPE = "|"
    AMPERSAND = "&"
    EQUALS = "="
    HASH = "#"
    AT = "@"
    ELLIPSIS = "..."
    DOUBLE_COLON = "::"
    RANGE = ".."
    EXCLUSIVE_RANGE = "<.."
    RANGE_EXCLUSIVE = "..<"
    EXCLUSIVE_RANGE_EXCLUSIVE = "<..<"
    
    # Special
    EOF = "EOF"
    NEWLINE = "NEWLINE"
    COMMENT = "COMMENT"
    DOC_COMMENT = "DOC_COMMENT"
    WHITESPACE = "WHITESPACE"

@dataclass
class Token:
    type: TokenType
    value: str
    line: int
    column: int

@dataclass 
class Position:
    line: int
    column: int

class LexerError(Exception):
    def __init__(self, message: str, position: Position):
        self.message = message
        self.position = position
        super().__init__(f"Line {position.line}, Column {position.column}: {message}")

class ParseError(Exception):
    def __init__(self, message: str, token: Token):
        self.message = message
        self.token = token
        super().__init__(f"Line {token.line}, Column {token.column}: {message}")

class Lexer:
    """Lexical analyzer for mcdoc files"""
    
    KEYWORDS = {
        'struct': TokenType.STRUCT,
        'enum': TokenType.ENUM,
        'type': TokenType.TYPE,
        'use': TokenType.USE,
        'dispatch': TokenType.DISPATCH,
        'super': TokenType.SUPER,
        'any': TokenType.ANY,
        'boolean': TokenType.BOOLEAN_TYPE,
        'string': TokenType.STRING_TYPE,
        'byte': TokenType.BYTE,
        'short': TokenType.SHORT,
        'int': TokenType.INT,
        'long': TokenType.LONG,
        'float': TokenType.FLOAT_TYPE,
        'double': TokenType.DOUBLE,
        'true': TokenType.TRUE,
        'false': TokenType.FALSE,
        'to': TokenType.TO
    }
    
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens = []
    
    def error(self, message: str):
        raise LexerError(message, Position(self.line, self.column))
    
    def peek(self, offset: int = 0) -> str:
        pos = self.pos + offset
        if pos >= len(self.text):
            return '\0'
        return self.text[pos]
    
    def advance(self) -> str:
        if self.pos >= len(self.text):
            return '\0'
        
        char = self.text[self.pos]
        self.pos += 1
        
        if char == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
            
        return char
    
    def skip_whitespace(self):
        while self.peek().isspace() and self.peek() != '\n':
            self.advance()
    
    def read_string(self) -> str:
        quote = self.advance()  # Skip opening quote
        value = ""
        
        while self.peek() != quote and self.peek() != '\0':
            if self.peek() == '\\':
                self.advance()  # Skip backslash
                escaped = self.advance()
                escape_map = {
                    'n': '\n', 't': '\t', 'r': '\r', '\\': '\\',
                    '"': '"', "'": "'", 'b': '\b', 'f': '\f'
                }
                value += escape_map.get(escaped, escaped)
            else:
                value += self.advance()
        
        if self.peek() == '\0':
            self.error("Unterminated string")
        
        self.advance()  # Skip closing quote
        return value
    
    def read_number(self) -> Tuple[str, TokenType]:
        value = ""
        has_dot = False
        
        # Handle negative numbers
        if self.peek() == '-' or self.peek() == '+':
            value += self.advance()
        
        while self.peek().isdigit() or (self.peek() == '.' and not has_dot):
            if self.peek() == '.':
                # Check if it's a range operator
                if self.peek(1) == '.':
                    break
                has_dot = True
            value += self.advance()
        
        # Handle scientific notation
        if self.peek().lower() == 'e':
            value += self.advance()
            if self.peek() in '+-':
                value += self.advance()
            while self.peek().isdigit():
                value += self.advance()
            has_dot = True
        
        # Handle typed numbers (suffixes)
        if self.peek().lower() in 'bslfd':
            suffix = self.advance().lower()
            return value + suffix, TokenType.FLOAT if suffix in 'fd' else TokenType.INTEGER
        
        return value, TokenType.FLOAT if has_dot else TokenType.INTEGER
    
    def read_identifier(self) -> str:
        value = ""
        while (self.peek().isalnum() or self.peek() in '_'):
            value += self.advance()
        return value
    
    def read_comment(self) -> Tuple[str, TokenType]:
        content = ""
        if self.peek() == '/' and self.peek(1) == '/':
            self.advance()  # Skip first /
            self.advance()  # Skip second /
            
            # Check for doc comment
            is_doc = self.peek() == '/'
            if is_doc:
                self.advance()  # Skip third /
            
            while self.peek() != '\n' and self.peek() != '\0':
                content += self.advance()
            
            return content.strip(), TokenType.DOC_COMMENT if is_doc else TokenType.COMMENT
        
        return content, TokenType.COMMENT
    
    def tokenize(self) -> List[Token]:
        self.tokens = []
        
        while self.pos < len(self.text):
            start_line = self.line
            start_column = self.column
            
            char = self.peek()
            
            if char == '\0':
                break
            elif char == '\n':
                self.advance()
                self.tokens.append(Token(TokenType.NEWLINE, '\\n', start_line, start_column))
            elif char.isspace():
                self.skip_whitespace()
            elif char == '/' and self.peek(1) == '/':
                content, token_type = self.read_comment()
                if token_type == TokenType.DOC_COMMENT:
                    self.tokens.append(Token(token_type, content, start_line, start_column))
            elif char in '"\'':
                value = self.read_string()
                self.tokens.append(Token(TokenType.STRING, value, start_line, start_column))
            elif char.isdigit() or (char in '+-' and self.peek(1).isdigit()):
                value, token_type = self.read_number()
                self.tokens.append(Token(token_type, value, start_line, start_column))
            elif char.isalpha() or char == '_':
                value = self.read_identifier()
                token_type = self.KEYWORDS.get(value, TokenType.IDENTIFIER)
                if value in ['true', 'false']:
                    token_type = TokenType.BOOLEAN
                self.tokens.append(Token(token_type, value, start_line, start_column))
            elif char == ':':
                if self.peek(1) == ':':
                    self.advance()
                    self.advance()
                    self.tokens.append(Token(TokenType.DOUBLE_COLON, '::', start_line, start_column))
                else:
                    self.advance()
                    self.tokens.append(Token(TokenType.COLON, ':', start_line, start_column))
            elif char == '.':
                if self.peek(1) == '.' and self.peek(2) == '.':
                    self.advance()
                    self.advance()
                    self.advance()
                    self.tokens.append(Token(TokenType.ELLIPSIS, '...', start_line, start_column))
                elif self.peek(1) == '.':
                    self.advance()
                    self.advance()
                    if self.peek() == '<':
                        self.advance()
                        self.tokens.append(Token(TokenType.RANGE_EXCLUSIVE, '..<', start_line, start_column))
                    else:
                        self.tokens.append(Token(TokenType.RANGE, '..', start_line, start_column))
                else:
                    self.advance()
                    self.tokens.append(Token(TokenType.DOT, '.', start_line, start_column))
            elif char == '<':
                if self.peek(1) == '.' and self.peek(2) == '.':
                    self.advance()
                    self.advance()
                    self.advance()
                    if self.peek() == '<':
                        self.advance()
                        self.tokens.append(Token(TokenType.EXCLUSIVE_RANGE_EXCLUSIVE, '<..<', start_line, start_column))
                    else:
                        self.tokens.append(Token(TokenType.EXCLUSIVE_RANGE, '<..', start_line, start_column))
                else:
                    self.advance()
                    self.tokens.append(Token(TokenType.LANGLE, '<', start_line, start_column))
            elif char == '%':
                self.advance()
                identifier = self.read_identifier()
                special_key = f"%{identifier}"
                
                special_tokens = {
                    "%fallback": TokenType.FALLBACK,
                    "%none": TokenType.NONE,
                    "%unknown": TokenType.UNKNOWN,
                    "%key": TokenType.KEY,
                    "%parent": TokenType.PARENT
                }
                
                token_type = special_tokens.get(special_key, TokenType.IDENTIFIER)
                self.tokens.append(Token(token_type, special_key, start_line, start_column))
            else:
                # Single character tokens
                char_map = {
                    '{': TokenType.LBRACE, '}': TokenType.RBRACE,
                    '[': TokenType.LBRACKET, ']': TokenType.RBRACKET,
                    '(': TokenType.LPAREN, ')': TokenType.RPAREN,
                    '>': TokenType.RANGLE, ';': TokenType.SEMICOLON,
                    ',': TokenType.COMMA, '?': TokenType.QUESTION,
                    '|': TokenType.PIPE, '&': TokenType.AMPERSAND,
                    '=': TokenType.EQUALS, '#': TokenType.HASH,
                    '@': TokenType.AT
                }
                
                if char in char_map:
                    self.advance()
                    self.tokens.append(Token(char_map[char], char, start_line, start_column))
                else:
                    self.error(f"Unexpected character: {char}")
        
        self.tokens.append(Token(TokenType.EOF, '', self.line, self.column))
        return self.tokens

# AST Node definitions
@dataclass
class ASTNode:
    line: int
    column: int

@dataclass 
class Type(ASTNode):
    pass

@dataclass
class AnyType(Type):
    pass

@dataclass
class BooleanType(Type):
    pass

@dataclass
class StringType(Type):
    range: Optional['NumberRange'] = None

@dataclass
class NumericType(Type):
    type_name: str  # byte, short, int, long, float, double
    range: Optional['NumberRange'] = None

@dataclass
class LiteralType(Type):
    value: Any
    type_name: Optional[str] = None

@dataclass
class PrimitiveArrayType(Type):
    element_type: str
    value_range: Optional['NumberRange'] = None
    size_range: Optional['NumberRange'] = None

@dataclass
class ListType(Type):
    element_type: Type
    size_range: Optional['NumberRange'] = None

@dataclass
class TupleType(Type):
    element_types: List[Type]

@dataclass
class UnionType(Type):
    types: List[Type]

@dataclass
class ReferenceType(Type):
    path: str
    type_args: List[Type] = field(default_factory=list)

@dataclass
class IndexedType(Type):
    base_type: Type
    indices: List[Union[str, 'DynamicIndex']]

@dataclass
class DynamicIndex:
    path: List[str]

@dataclass
class NumberRange:
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_exclusive: bool = False
    max_exclusive: bool = False

@dataclass
class StructField:
    name: str
    type: Type
    optional: bool = False
    doc_comment: Optional[str] = None

@dataclass
class StructType(Type):
    fields: List[StructField]
    spreads: List[Type] = field(default_factory=list)

@dataclass
class EnumVariant:
    name: str
    value: Optional[int] = None
    doc_comment: Optional[str] = None

@dataclass
class EnumType(Type):
    variants: List[EnumVariant]

@dataclass 
class TypeAlias(ASTNode):
    name: str
    type_params: List[str]
    target_type: Type
    doc_comment: Optional[str] = None

@dataclass
class UseStatement(ASTNode):
    path: str
    alias: Optional[str] = None

@dataclass
class DispatchStatement(ASTNode):
    dispatcher: str
    indices: List[str]
    target_type: Type

@dataclass
class Injection(ASTNode):
    target_path: str
    fields: List[StructField]

@dataclass
class Module(ASTNode):
    statements: List[Union[TypeAlias, UseStatement, DispatchStatement, Injection, StructType, EnumType]]
    doc_comments: Dict[str, str] = field(default_factory=dict)

class Parser:
    """Parser for mcdoc syntax"""
    
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.current_token = tokens[0] if tokens else Token(TokenType.EOF, '', 0, 0)
    
    def error(self, message: str):
        raise ParseError(message, self.current_token)
    
    def advance(self):
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
            self.current_token = self.tokens[self.pos]
        return self.current_token
    
    def peek(self, offset: int = 1) -> Token:
        pos = self.pos + offset
        if pos >= len(self.tokens):
            return Token(TokenType.EOF, '', 0, 0)
        return self.tokens[pos]
    
    def match(self, *token_types: TokenType) -> bool:
        return self.current_token.type in token_types
    
    def consume(self, token_type: TokenType, message: str = None) -> Token:
        if self.current_token.type != token_type:
            if message is None:
                message = f"Expected {token_type}, got {self.current_token.type}"
            self.error(message)
        
        token = self.current_token
        self.advance()
        return token
    
    def skip_newlines(self):
        while self.match(TokenType.NEWLINE):
            self.advance()
    
    def parse_module(self) -> Module:
        statements = []
        doc_comments = {}
        
        while not self.match(TokenType.EOF):
            self.skip_newlines()
            
            if self.match(TokenType.EOF):
                break
            
            # Collect doc comments
            current_doc = None
            if self.match(TokenType.DOC_COMMENT):
                doc_lines = []
                while self.match(TokenType.DOC_COMMENT):
                    doc_lines.append(self.current_token.value)
                    self.advance()
                current_doc = '\n'.join(doc_lines)
                self.skip_newlines()
            
            if self.match(TokenType.STRUCT):
                stmt = self.parse_struct()
                statements.append(stmt)
            elif self.match(TokenType.ENUM):
                stmt = self.parse_enum()
                statements.append(stmt)
            elif self.match(TokenType.TYPE):
                stmt = self.parse_type_alias()
                if current_doc:
                    stmt.doc_comment = current_doc
                statements.append(stmt)
            elif self.match(TokenType.USE):
                statements.append(self.parse_use_statement())
            elif self.match(TokenType.DISPATCH):
                statements.append(self.parse_dispatch_statement())
            else:
                self.error(f"Unexpected token: {self.current_token.type}")
            
            self.skip_newlines()
        
        return Module(0, 0, statements, doc_comments)
    
    def parse_struct(self) -> StructType:
        line, col = self.current_token.line, self.current_token.column
        self.consume(TokenType.STRUCT)
        self.consume(TokenType.LBRACE)
        
        fields = []
        spreads = []
        
        while not self.match(TokenType.RBRACE):
            self.skip_newlines()
            
            if self.match(TokenType.RBRACE):
                break
            
            # Doc comment for field
            field_doc = None
            if self.match(TokenType.DOC_COMMENT):
                field_doc = self.current_token.value
                self.advance()
                self.skip_newlines()
            
            # Spread operator
            if self.match(TokenType.ELLIPSIS):
                self.advance()
                spread_type = self.parse_type()
                spreads.append(spread_type)
            else:
                # Regular field
                field_name = self.consume(TokenType.IDENTIFIER).value
                
                # Optional field
                optional = False
                if self.match(TokenType.QUESTION):
                    optional = True
                    self.advance()
                
                self.consume(TokenType.COLON)
                field_type = self.parse_type()
                
                field = StructField(field_name, field_type, optional, field_doc)
                fields.append(field)
            
            # Optional comma
            if self.match(TokenType.COMMA):
                self.advance()
            
            self.skip_newlines()
        
        self.consume(TokenType.RBRACE)
        return StructType(line, col, fields, spreads)
    
    def parse_enum(self) -> EnumType:
        line, col = self.current_token.line, self.current_token.column
        self.consume(TokenType.ENUM)
        self.consume(TokenType.LBRACE)
        
        variants = []
        
        while not self.match(TokenType.RBRACE):
            self.skip_newlines()
            
            if self.match(TokenType.RBRACE):
                break
            
            # Doc comment for variant
            variant_doc = None
            if self.match(TokenType.DOC_COMMENT):
                variant_doc = self.current_token.value
                self.advance()
                self.skip_newlines()
            
            variant_name = self.consume(TokenType.IDENTIFIER).value
            
            # Optional value
            variant_value = None
            if self.match(TokenType.EQUALS):
                self.advance()
                if self.match(TokenType.INTEGER):
                    variant_value = int(self.current_token.value)
                    self.advance()
                else:
                    self.error("Expected integer value for enum variant")
            
            variant = EnumVariant(variant_name, variant_value, variant_doc)
            variants.append(variant)
            
            # Optional comma
            if self.match(TokenType.COMMA):
                self.advance()
            
            self.skip_newlines()
        
        self.consume(TokenType.RBRACE)
        return EnumType(line, col, variants)
    
    def parse_type_alias(self) -> TypeAlias:
        line, col = self.current_token.line, self.current_token.column
        self.consume(TokenType.TYPE)
        
        name = self.consume(TokenType.IDENTIFIER).value
        
        # Type parameters
        type_params = []
        if self.match(TokenType.LANGLE):
            self.advance()
            while not self.match(TokenType.RANGLE):
                param = self.consume(TokenType.IDENTIFIER).value
                type_params.append(param)
                
                if self.match(TokenType.COMMA):
                    self.advance()
                elif not self.match(TokenType.RANGLE):
                    self.error("Expected ',' or '>' in type parameters")
            
            self.consume(TokenType.RANGLE)
        
        self.consume(TokenType.EQUALS)
        target_type = self.parse_type()
        
        return TypeAlias(line, col, name, type_params, target_type)
    
    def parse_use_statement(self) -> UseStatement:
        line, col = self.current_token.line, self.current_token.column
        self.consume(TokenType.USE)
        
        path = self.parse_path()
        
        alias = None
        if self.match(TokenType.AS):
            self.advance()
            alias = self.consume(TokenType.IDENTIFIER).value
        
        return UseStatement(line, col, path, alias)
    
    def parse_dispatch_statement(self) -> DispatchStatement:
        line, col = self.current_token.line, self.current_token.column
        self.consume(TokenType.DISPATCH)
        
        dispatcher = self.consume(TokenType.IDENTIFIER).value
        
        indices = []
        if self.match(TokenType.LBRACKET):
            self.advance()
            while not self.match(TokenType.RBRACKET):
                if self.match(TokenType.IDENTIFIER):
                    indices.append(self.current_token.value)
                    self.advance()
                else:
                    self.error("Expected identifier in dispatch indices")
                
                if self.match(TokenType.COMMA):
                    self.advance()
                elif not self.match(TokenType.RBRACKET):
                    self.error("Expected ',' or ']' in dispatch indices")
            
            self.consume(TokenType.RBRACKET)
        
        self.consume(TokenType.TO)
        target_type = self.parse_type()
        
        return DispatchStatement(line, col, dispatcher, indices, target_type)
    
    def parse_type(self) -> Type:
        return self.parse_union_type()
    
    def parse_union_type(self) -> Type:
        left = self.parse_primary_type()
        
        if self.match(TokenType.PIPE):
            types = [left]
            while self.match(TokenType.PIPE):
                self.advance()
                types.append(self.parse_primary_type())
            return UnionType(left.line, left.column, types)
        
        return left
    
    def parse_primary_type(self) -> Type:
        line, col = self.current_token.line, self.current_token.column
        
        if self.match(TokenType.ANY):
            self.advance()
            return AnyType(line, col)
        elif self.match(TokenType.BOOLEAN_TYPE):
            self.advance()
            return BooleanType(line, col)
        elif self.match(TokenType.STRING_TYPE):
            self.advance()
            # Optional length constraint
            range_def = None
            if self.match(TokenType.AT):
                self.advance()
                range_def = self.parse_number_range()
            return StringType(line, col, range_def)
        elif self.match(TokenType.BYTE, TokenType.SHORT, TokenType.INT, TokenType.LONG, 
                        TokenType.FLOAT_TYPE, TokenType.DOUBLE):
            type_name = self.current_token.value
            self.advance()
            # Optional range constraint
            range_def = None
            if self.match(TokenType.AT):
                self.advance()
                range_def = self.parse_number_range()
            return NumericType(line, col, type_name, range_def)
        elif self.match(TokenType.INTEGER, TokenType.FLOAT):
            value = self.current_token.value
            self.advance()
            return LiteralType(line, col, value)
        elif self.match(TokenType.STRING):
            value = self.current_token.value
            self.advance()
            return LiteralType(line, col, value)
        elif self.match(TokenType.BOOLEAN):
            value = self.current_token.value == 'true'
            self.advance()
            return LiteralType(line, col, value)
        elif self.match(TokenType.LBRACKET):
            return self.parse_list_type()
        elif self.match(TokenType.LPAREN):
            return self.parse_parenthesized_type()
        elif self.match(TokenType.LBRACE):
            return self.parse_struct()
        elif self.match(TokenType.IDENTIFIER):
            return self.parse_reference_type()
        else:
            self.error(f"Unexpected token in type: {self.current_token.type}")
    
    def parse_list_type(self) -> Type:
        line, col = self.current_token.line, self.current_token.column
        self.consume(TokenType.LBRACKET)
        
        element_type = self.parse_type()
        self.consume(TokenType.RBRACKET)
        
        # Check for size constraint
        size_range = None
        if self.match(TokenType.AT):
            self.advance()
            size_range = self.parse_number_range()
        
        return ListType(line, col, element_type, size_range)
    
    def parse_parenthesized_type(self) -> Type:
        self.consume(TokenType.LPAREN)
        
        if self.match(TokenType.RPAREN):
            # Empty tuple
            self.advance()
            return TupleType(self.current_token.line, self.current_token.column, [])
        
        first_type = self.parse_type()
        
        if self.match(TokenType.COMMA):
            # Tuple type
            types = [first_type]
            while self.match(TokenType.COMMA):
                self.advance()
                if not self.match(TokenType.RPAREN):
                    types.append(self.parse_type())
            self.consume(TokenType.RPAREN)
            return TupleType(first_type.line, first_type.column, types)
        else:
            # Parenthesized type
            self.consume(TokenType.RPAREN)
            return first_type
    
    def parse_reference_type(self) -> Type:
        line, col = self.current_token.line, self.current_token.column
        path = self.parse_path()
        
        # Type arguments
        type_args = []
        if self.match(TokenType.LANGLE):
            self.advance()
            while not self.match(TokenType.RANGLE):
                type_args.append(self.parse_type())
                
                if self.match(TokenType.COMMA):
                    self.advance()
                elif not self.match(TokenType.RANGLE):
                    self.error("Expected ',' or '>' in type arguments")
            
            self.consume(TokenType.RANGLE)
        
        ref_type = ReferenceType(line, col, path, type_args)
        
        # Check for indexing
        if self.match(TokenType.LBRACKET):
            return self.parse_indexed_type(ref_type)
        
        return ref_type
    
    def parse_indexed_type(self, base_type: Type) -> Type:
        indices = []
        
        while self.match(TokenType.LBRACKET):
            self.advance()
            
            if self.match(TokenType.IDENTIFIER):
                indices.append(self.current_token.value)
                self.advance()
            elif self.match(TokenType.FALLBACK, TokenType.NONE, TokenType.UNKNOWN, TokenType.KEY, TokenType.PARENT):
                indices.append(self.current_token.value)
                self.advance()
            else:
                self.error("Expected index")
            
            self.consume(TokenType.RBRACKET)
        
        return IndexedType(base_type.line, base_type.column, base_type, indices)

    def parse_number_range(self) -> NumberRange:
        """Parse number range like 1..10, <5, 3..<7, etc."""
        min_val = None
        max_val = None
        min_exclusive = False
        max_exclusive = False
        
        # Handle single values or range start
        if self.match(TokenType.INTEGER, TokenType.FLOAT):
            min_val = float(self.current_token.value)
            self.advance()
            
            # Check for range operators
            if self.match(TokenType.RANGE):
                self.advance()
                if self.match(TokenType.INTEGER, TokenType.FLOAT):
                    max_val = float(self.current_token.value)
                    self.advance()
            elif self.match(TokenType.RANGE_EXCLUSIVE):
                max_exclusive = True
                self.advance()
                if self.match(TokenType.INTEGER, TokenType.FLOAT):
                    max_val = float(self.current_token.value)
                    self.advance()
        elif self.match(TokenType.EXCLUSIVE_RANGE):
            min_exclusive = True
            self.advance()
            if self.match(TokenType.INTEGER, TokenType.FLOAT):
                max_val = float(self.current_token.value)
                self.advance()
        elif self.match(TokenType.EXCLUSIVE_RANGE_EXCLUSIVE):
            min_exclusive = True
            max_exclusive = True
            self.advance()
            if self.match(TokenType.INTEGER, TokenType.FLOAT):
                max_val = float(self.current_token.value)
                self.advance()
        
        return NumberRange(min_val, max_val, min_exclusive, max_exclusive)
    
    def parse_path(self) -> str:
        """Parse dot-separated path like foo.bar.baz"""
        parts = [self.consume(TokenType.IDENTIFIER).value]
        
        while self.match(TokenType.DOUBLE_COLON):
            self.advance()
            parts.append(self.consume(TokenType.IDENTIFIER).value)
        
        return "::".join(parts)


class JSONSchemaGenerator:
    """Converts mcdoc AST to JSON Schema"""
    
    def __init__(self):
        self.schema_cache = {}
        self.type_definitions = {}
    
    def generate_schema(self, module: Module) -> Dict[str, Any]:
        """Generate JSON Schema from mcdoc module"""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "definitions": {}
        }
        
        # Process all type definitions first
        for stmt in module.statements:
            if isinstance(stmt, TypeAlias):
                self.type_definitions[stmt.name] = stmt
                schema["definitions"][stmt.name] = self.convert_type(stmt.target_type)
            elif isinstance(stmt, StructType):
                # Anonymous struct - add to definitions with generated name
                struct_name = f"Struct_{id(stmt)}"
                schema["definitions"][struct_name] = self.convert_type(stmt)
            elif isinstance(stmt, EnumType):
                # Anonymous enum - add to definitions with generated name
                enum_name = f"Enum_{id(stmt)}"
                schema["definitions"][enum_name] = self.convert_type(stmt)
        
        return schema
    
    def convert_type(self, type_node: Type) -> Dict[str, Any]:
        """Convert mcdoc type to JSON Schema"""
        if isinstance(type_node, AnyType):
            return {}
        
        elif isinstance(type_node, BooleanType):
            return {"type": "boolean"}
        
        elif isinstance(type_node, StringType):
            schema = {"type": "string"}
            if type_node.range:
                if type_node.range.min_value is not None:
                    schema["minLength"] = int(type_node.range.min_value)
                if type_node.range.max_value is not None:
                    schema["maxLength"] = int(type_node.range.max_value)
            return schema
        
        elif isinstance(type_node, NumericType):
            if type_node.type_name in ["float", "double"]:
                schema = {"type": "number"}
            else:
                schema = {"type": "integer"}
            
            if type_node.range:
                if type_node.range.min_value is not None:
                    key = "exclusiveMinimum" if type_node.range.min_exclusive else "minimum"
                    schema[key] = type_node.range.min_value
                if type_node.range.max_value is not None:
                    key = "exclusiveMaximum" if type_node.range.max_exclusive else "maximum"
                    schema[key] = type_node.range.max_value
            
            return schema
        
        elif isinstance(type_node, LiteralType):
            return {"const": type_node.value}
        
        elif isinstance(type_node, ListType):
            schema = {
                "type": "array",
                "items": self.convert_type(type_node.element_type)
            }
            if type_node.size_range:
                if type_node.size_range.min_value is not None:
                    schema["minItems"] = int(type_node.size_range.min_value)
                if type_node.size_range.max_value is not None:
                    schema["maxItems"] = int(type_node.size_range.max_value)
            return schema
        
        elif isinstance(type_node, TupleType):
            return {
                "type": "array",
                "prefixItems": [self.convert_type(t) for t in type_node.element_types],
                "items": False
            }
        
        elif isinstance(type_node, UnionType):
            return {"anyOf": [self.convert_type(t) for t in type_node.types]}
        
        elif isinstance(type_node, StructType):
            schema = {
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
            
            required = []
            for field in type_node.fields:
                schema["properties"][field.name] = self.convert_type(field.type)
                if not field.optional:
                    required.append(field.name)
            
            if required:
                schema["required"] = required
            
            # Handle spreads
            if type_node.spreads:
                all_of = [{"type": "object", "properties": schema["properties"]}]
                if required:
                    all_of[0]["required"] = required
                
                for spread in type_node.spreads:
                    all_of.append(self.convert_type(spread))
                
                return {"allOf": all_of}
            
            return schema
        
        elif isinstance(type_node, EnumType):
            if all(v.value is not None for v in type_node.variants):
                # Integer enum
                return {"enum": [v.value for v in type_node.variants]}
            else:
                # String enum
                return {"enum": [v.name for v in type_node.variants]}
        
        elif isinstance(type_node, ReferenceType):
            return {"$ref": f"#/definitions/{type_node.path}"}
        
        elif isinstance(type_node, IndexedType):
            # For indexed types, we'll create a more complex schema
            base_schema = self.convert_type(type_node.base_type)
            # This is simplified - real implementation would need dispatch logic
            return base_schema
        
        else:
            return {}


class McdocCompiler:
    """Main compiler class"""
    
    def __init__(self):
        self.modules = {}
        self.schema_generator = JSONSchemaGenerator()
    
    def compile_file(self, file_path: Path) -> Dict[str, Any]:
        """Compile a single mcdoc file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lexer = Lexer(content)
            tokens = lexer.tokenize()
            
            parser = Parser(tokens)
            module = parser.parse_module()
            
            return self.schema_generator.generate_schema(module)
            
        except (LexerError, ParseError) as e:
            print(f"Error compiling {file_path}: {e}")
            return {}
        except Exception as e:
            print(f"Unexpected error compiling {file_path}: {e}")
            return {}
    
    def compile_directory(self, input_dir: Path, output_dir: Path):
        """Compile all mcdoc files in a directory"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for mcdoc_file in input_dir.rglob("*.mcdoc"):
            print(f"Compiling {mcdoc_file}")
            
            schema = self.compile_file(mcdoc_file)
            
            # Create output path
            relative_path = mcdoc_file.relative_to(input_dir)
            output_file = output_dir / relative_path.with_suffix('.json')
            
            # Ensure output directory exists
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Write JSON schema
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(schema, f, indent=2)
            
            print(f"Generated {output_file}")


def main():
    """Main entry point"""
    if len(sys.argv) != 3:
        print("Usage: python mcdoc_compiler.py <input_folder> <output_folder>")
        sys.exit(1)
    
    input_folder = Path(sys.argv[1])
    output_folder = Path(sys.argv[2])
    
    if not input_folder.exists():
        print(f"Input folder {input_folder} does not exist")
        sys.exit(1)
    
    compiler = McdocCompiler()
    compiler.compile_directory(input_folder, output_folder)
    
    print("Compilation complete!")


if __name__ == "__main__":
    main()