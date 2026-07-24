"""tree-sitter 解析器 — 抽函数签名 + call sites（Layer 2 精筛用）。"""
from __future__ import annotations

import dataclasses
import pathlib

from tree_sitter_languages import get_parser


@dataclasses.dataclass
class FunctionSignature:
    name: str
    signature: str  # 完整签名文本
    line_start: int
    line_end: int
    enclosing_class: str | None


@dataclasses.dataclass
class CallSite:
    callee_name: str  # 函数调用名（可能含 obj. 前缀）
    line: int
    column: int
    enclosing_function: str | None


@dataclasses.dataclass
class ParsedFile:
    path: pathlib.Path
    language: str
    functions: list[FunctionSignature]
    call_sites: list[CallSite]


class TreeSitterParser:
    def parse_file(self, path: pathlib.Path, language: str) -> ParsedFile:
        parser = get_parser(language)
        source = path.read_bytes()
        tree = parser.parse(source)
        root = tree.root_node

        functions = self._extract_functions(root, source, language)
        call_sites = self._extract_call_sites(root, source)

        return ParsedFile(
            path=path, language=language,
            functions=functions, call_sites=call_sites,
        )

    def _extract_functions(
        self, root, source: bytes, language: str
    ) -> list[FunctionSignature]:
        functions: list[FunctionSignature] = []
        if language == "python":
            fn_node_type = "function_definition"
            name_field = "name"
        else:  # c
            fn_node_type = "function_definition"
            name_field = "declarator"

        def walk(node, enclosing_class: str | None) -> None:
            if node.type == "class_definition" and language == "python":
                cls_name_node = node.child_by_field_name("name")
                cls_name = (
                    source[cls_name_node.start_byte:cls_name_node.end_byte].decode("utf-8")
                    if cls_name_node else None
                )
                for child in node.children:
                    walk(child, cls_name)
                return
            if node.type == fn_node_type:
                name_node = node.child_by_field_name(name_field)
                if language == "c" and name_node:
                    # declarator 通常是 function_declarator，里面才是 name
                    name_node = name_node.child_by_field_name("declarator") or name_node
                    while name_node and name_node.type == "function_declarator":
                        name_node = name_node.child_by_field_name("declarator")
                if name_node:
                    name = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                    signature = source[node.start_byte:node.end_byte].decode("utf-8").splitlines()[0]
                    functions.append(FunctionSignature(
                        name=name, signature=signature,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        enclosing_class=enclosing_class,
                    ))
            for child in node.children:
                walk(child, enclosing_class)

        walk(root, None)
        return functions

    def _extract_call_sites(self, root, source: bytes) -> list[CallSite]:
        sites: list[CallSite] = []
        # 找当前函数上下文
        current_fn: list[str | None] = [None]

        def walk(node) -> None:
            if node.type == "function_definition":
                # 用 _extract_functions 同样的 name_field 逻辑这里简化
                prev_fn = current_fn[0]
                # 找名字
                name_node = node.child_by_field_name("name") or node.child_by_field_name("declarator")
                while name_node and name_node.type == "function_declarator":
                    name_node = name_node.child_by_field_name("declarator")
                if name_node:
                    current_fn[0] = source[name_node.start_byte:name_node.end_byte].decode("utf-8")
                for child in node.children:
                    walk(child)
                current_fn[0] = prev_fn
                return
            if node.type == "call":
                # callee 可能是 identifier 或 attribute (LOG.info)
                callee_node = node.child_by_field_name("function")
                if callee_node:
                    callee_name = source[callee_node.start_byte:callee_node.end_byte].decode("utf-8")
                    sites.append(CallSite(
                        callee_name=callee_name,
                        line=node.start_point[0] + 1,
                        column=node.start_point[1],
                        enclosing_function=current_fn[0],
                    ))
            for child in node.children:
                walk(child)

        walk(root)
        return sites
