from __future__ import annotations

import ast
import builtins
import os
import symtable
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .model import (
    REQUIRED_L2_CAPABILITIES, file_in_graph_scope, load_graph_config, read_source,
    sha256_text, stable_symbol_id,
)


EXCLUDE_DIRS = {
    ".git", ".adworkflow", ".codegraph", ".venv", "venv", "node_modules",
    "dist", "build", "__pycache__", ".next", ".turbo", "coverage",
}
MODULE_IMPLICIT_NAMES = {"__file__", "__name__", "__package__", "__spec__", "__loader__", "__builtins__"}


class FunctionLocalCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        for item in node.body:
            self.visit(item)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


class MappingUseCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.value, ast.Name) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            self.names.add(node.value.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

def iter_python_files(project: Path, config: dict[str, Any]) -> Iterable[Path]:
    for root, dirs, files in os.walk(project):
        dirs[:] = [item for item in dirs if item not in EXCLUDE_DIRS]
        for name in files:
            if name.endswith(".py"):
                path = Path(root) / name
                relative_path = path.resolve().relative_to(project.resolve()).as_posix()
                if file_in_graph_scope(relative_path, "python", config):
                    yield path


def relative(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def module_name_for(project: Path, path: Path) -> str:
    rel = path.resolve().relative_to(project.resolve()).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or path.parent.name


def module_aliases_for(project: Path, path: Path, primary: str) -> set[str]:
    relative_path = path.resolve().relative_to(project.resolve())
    parts = list(relative_path.with_suffix("").parts)
    aliases = {primary}
    if parts and parts[-1] == "__init__":
        parts.pop()
    for start in range(len(parts)):
        package_dirs = parts[start:-1]
        if all((project.joinpath(*parts[:start + index + 1]) / "__init__.py").exists() for index in range(len(package_dirs))):
            aliases.add(".".join(parts[start:]))
    if path.name != "__init__.py":
        aliases.add(path.stem)
    return {item for item in aliases if item}


def is_test_path(path: str) -> bool:
    parts = set(Path(path).parts)
    name = Path(path).name
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


class DefinitionCollector(ast.NodeVisitor):
    def __init__(self, module: str, file_path: str) -> None:
        self.module = module
        self.file_path = file_path
        self.symbols: list[dict[str, Any]] = []
        self.scope_names: list[str] = []
        self.scope_ids: list[str] = []
        self.scope_records: list[dict[str, Any]] = []

    def add_symbol(
        self,
        node: ast.AST,
        name: str,
        kind: str,
        signature: str | None = None,
        return_annotation: str | None = None,
    ) -> str:
        qualified = ".".join([*self.scope_names, name]) if self.scope_names else name
        symbol_id = stable_symbol_id("python", self.module, qualified, kind)
        record = {
            "stable_id": symbol_id,
            "file": self.file_path,
            "module": self.module,
            "name": name,
            "qualified_name": f"{self.module}.{qualified}",
            "local_qualified_name": qualified,
            "kind": kind,
            "start_line": getattr(node, "lineno", 1),
            "start_column": getattr(node, "col_offset", 0),
            "end_line": getattr(node, "end_lineno", getattr(node, "lineno", 1)),
            "end_column": getattr(node, "end_col_offset", 0),
            "scope_symbol_id": self.scope_ids[-1] if self.scope_ids else None,
            "exported": not name.startswith("_"),
            "signature": signature,
            "return_annotation": return_annotation,
            "_scope_record": self.scope_records[-1] if self.scope_records else None,
        }
        self.symbols.append(record)
        return symbol_id

    @staticmethod
    def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = [item.arg for item in [*node.args.posonlyargs, *node.args.args]]
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        args.extend(item.arg for item in node.args.kwonlyargs)
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        return f"{node.name}({', '.join(args)})"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol_id = self.add_symbol(node, node.name, "class")
        record = self.symbols[-1]
        self.symbols[-1]["bases"] = [self._expression_text(item) for item in node.bases]
        self.scope_names.append(node.name)
        self.scope_ids.append(symbol_id)
        self.scope_records.append(record)
        self.generic_visit(node)
        self.scope_records.pop()
        self.scope_ids.pop()
        self.scope_names.pop()

    @staticmethod
    def _expression_text(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return "<base>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        kind = "method" if self.scope_ids and self.scope_ids[-1].endswith(":class") else "function"
        return_annotation = self._expression_text(node.returns) if node.returns else None
        symbol_id = self.add_symbol(node, node.name, kind, self.function_signature(node), return_annotation)
        record = self.symbols[-1]
        self.scope_names.append(node.name)
        self.scope_ids.append(symbol_id)
        self.scope_records.append(record)
        self.generic_visit(node)
        self.scope_records.pop()
        self.scope_ids.pop()
        self.scope_names.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self.scope_names:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.add_symbol(target, target.id, "variable")
        self.generic_visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if not self.scope_names and isinstance(node.target, ast.Name):
            self.add_symbol(node.target, node.target.id, "variable")
        if node.value:
            self.visit(node.value)


def resolve_import_module(current_module: str, imported: str | None, level: int, current_is_package: bool) -> str:
    if not level:
        return imported or ""
    base = current_module.split(".") if current_is_package else current_module.split(".")[:-1]
    trim = max(0, level - 1)
    if trim:
        base = base[:-trim]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


class EdgeCollector(ast.NodeVisitor):
    def __init__(
        self,
        module: str,
        file_path: str,
        tree: ast.AST,
        symbols: list[dict[str, Any]],
        symbols_by_module_local: dict[tuple[str, str], str],
        module_files: dict[str, str],
        current_is_package: bool,
        all_symbol_records: list[dict[str, Any]],
    ) -> None:
        self.module = module
        self.file_path = file_path
        self.tree = tree
        self.symbols = symbols
        self.symbols_by_module_local = symbols_by_module_local
        self.module_files = module_files
        self.current_is_package = current_is_package
        self.references: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []
        self.unresolved: list[dict[str, Any]] = []
        self.scope_names: list[str] = []
        self.scope_ids: list[str] = []
        self.scope_kinds: list[str] = []
        self.variable_types: list[dict[str, str]] = [{}]
        self.local_bindings: list[set[str]] = [set()]
        self.import_aliases: dict[str, tuple[str, str | None]] = {}
        self.instance_attribute_types: dict[str, dict[str, str]] = defaultdict(dict)
        self.symbol_records = {item["stable_id"]: item for item in all_symbol_records}
        self.defs_by_parent: dict[str, dict[str, str]] = defaultdict(dict)
        self.symbols_by_location: dict[tuple[str, int, int], str] = {}
        for symbol in symbols:
            local = symbol["local_qualified_name"]
            parent, _, name = local.rpartition(".")
            self.symbols_by_location[(local, symbol["start_line"], symbol.get("start_column", 0))] = symbol["stable_id"]
            if symbol.get("runtime_effective", True):
                self.defs_by_parent[parent][name] = symbol["stable_id"]

    @property
    def caller(self) -> str | None:
        return self.scope_ids[-1] if self.scope_ids else None

    @property
    def local_scope(self) -> str:
        return ".".join(self.scope_names)

    def location(self, node: ast.AST) -> dict[str, int]:
        return {"line": getattr(node, "lineno", 1), "column": getattr(node, "col_offset", 0)}

    def resolve_name(self, name: str) -> tuple[str | None, str]:
        parts = list(self.scope_names)
        while True:
            parent = ".".join(parts)
            if name in self.defs_by_parent.get(parent, {}):
                return self.defs_by_parent[parent][name], "lexical"
            if not parts:
                break
            parts.pop()
        imported = self.import_aliases.get(name)
        if imported and imported[1]:
            target = self.symbols_by_module_local.get((imported[0], imported[1]))
            if target:
                return target, "import"
            return None, "external-import"
        if imported:
            return None, "external-import"
        if any(name in bindings for bindings in reversed(self.local_bindings)):
            return None, "local-value"
        if name in dir(builtins) or name in MODULE_IMPLICIT_NAMES:
            return None, "builtin"
        return None, "unresolved-name"

    def resolve_attribute(self, node: ast.Attribute) -> tuple[str | None, str, str]:
        attr = node.attr
        if isinstance(node.value, ast.Name):
            base = node.value.id
            imported = self.import_aliases.get(base)
            if imported:
                target_module, imported_name = imported
                local_name = f"{imported_name}.{attr}" if imported_name else attr
                target = self.symbols_by_module_local.get((target_module, local_name))
                if target:
                    return target, "import-attribute", f"{base}.{attr}"
                return None, "external-import-attribute", f"{base}.{attr}"
            if base in {"self", "cls"}:
                class_parts = list(self.scope_names)
                if self.scope_kinds and self.scope_kinds[-1] in {"function", "method"} and class_parts:
                    class_parts.pop()
                target = self.symbols_by_module_local.get((self.module, ".".join([*class_parts, attr])))
                if target:
                    return target, "self-attribute", f"{base}.{attr}"
                class_id = self.symbols_by_module_local.get((self.module, ".".join(class_parts)))
                class_record = self.symbol_records.get(class_id or "")
                if class_record:
                    inherited, inherited_resolution = self.resolve_inherited_method(class_record, attr, set())
                    if inherited or inherited_resolution:
                        return inherited, inherited_resolution, f"{base}.{attr}"
        receiver_type = self.infer_expr_type(node.value)
        if receiver_type and receiver_type.startswith("symbol:"):
            class_id = receiver_type.removeprefix("symbol:")
            class_record = self.symbol_records.get(class_id)
            if class_record:
                method_local = f"{class_record['local_qualified_name']}.{attr}"
                target = self.symbols_by_module_local.get((class_record["module"], method_local))
                if target:
                    return target, "typed-instance-attribute", self.expression_text(node)
                inherited, inherited_resolution = self.resolve_inherited_method(class_record, attr, set())
                if inherited or inherited_resolution:
                    return inherited, inherited_resolution, self.expression_text(node)
        if receiver_type and receiver_type.startswith(("external:", "builtin:")):
            return None, "external-typed-attribute", self.expression_text(node)
        try:
            text = ast.unparse(node)
        except Exception:
            text = attr
        return None, "dynamic-dispatch", text

    def resolve_inherited_method(
        self,
        class_record: dict[str, Any],
        attr: str,
        visited: set[str],
    ) -> tuple[str | None, str | None]:
        class_id = class_record["stable_id"]
        if class_id in visited:
            return None, None
        visited.add(class_id)
        external_base = False
        for base in class_record.get("bases", []):
            base_target: str | None = None
            if "." in base:
                root, _, tail = base.partition(".")
                imported = self.import_aliases.get(root)
                if imported:
                    module, imported_name = imported
                    local = ".".join(item for item in (imported_name, tail) if item)
                    base_target = self.symbols_by_module_local.get((module, local))
                    if not base_target:
                        external_base = True
            else:
                base_target, resolution = self.resolve_name(base)
                if not base_target and resolution in {"external-import", "builtin"}:
                    external_base = True
            if not base_target:
                continue
            base_record = self.symbol_records.get(base_target)
            if not base_record or base_record.get("kind") != "class":
                continue
            method_local = f"{base_record['local_qualified_name']}.{attr}"
            method = self.symbols_by_module_local.get((base_record["module"], method_local))
            if method:
                return method, "inherited-project-method"
            nested, nested_resolution = self.resolve_inherited_method(base_record, attr, visited)
            if nested or nested_resolution:
                return nested, nested_resolution
        if external_base:
            return None, "external-inherited-attribute"
        return None, None

    @staticmethod
    def expression_text(node: ast.AST) -> str:
        try:
            return ast.unparse(node)
        except Exception:
            return getattr(node, "attr", "<expression>")

    def lookup_variable_type(self, name: str) -> str | None:
        for scope in reversed(self.variable_types):
            if name in scope:
                return scope[name]
        return None

    def infer_annotation_type(self, annotation: ast.AST | None) -> str | None:
        if annotation is None:
            return None
        if isinstance(annotation, ast.Name):
            variable = self.lookup_variable_type(annotation.id)
            if variable:
                return variable
            target, resolution = self.resolve_name(annotation.id)
            if target and self.symbol_records.get(target, {}).get("kind") == "class":
                return f"symbol:{target}"
            if resolution in {"external-import", "builtin"}:
                return f"external:{annotation.id}" if resolution == "external-import" else f"builtin:{annotation.id}"
        if isinstance(annotation, ast.Subscript):
            outer = self.infer_annotation_type(annotation.value)
            inner_node = annotation.slice.elts[0] if isinstance(annotation.slice, ast.Tuple) and annotation.slice.elts else annotation.slice
            inner = self.infer_annotation_type(inner_node)
            return f"{outer}[{inner}]" if outer and inner else outer
        if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
            return self.infer_annotation_type(annotation.left) or self.infer_annotation_type(annotation.right)
        if isinstance(annotation, ast.Attribute):
            _, resolution, text = self.resolve_attribute(annotation)
            if resolution.startswith("external"):
                return f"external:{text}"
            root = text.split(".", 1)[0]
            if root not in self.module_files and not any(name == root or name.startswith(root + ".") for name in self.module_files):
                return f"external:{text}"
        return None

    def infer_expr_type(self, node: ast.AST | None) -> str | None:
        if node is None:
            return None
        if isinstance(node, ast.Name):
            known = self.lookup_variable_type(node.id)
            if known:
                return known
            target, resolution = self.resolve_name(node.id)
            if target and self.symbol_records.get(target, {}).get("kind") == "class":
                return f"symbol:{target}"
            if resolution == "external-import":
                return f"external:{node.id}"
            if resolution == "builtin":
                return f"builtin:{node.id}"
        if isinstance(node, ast.List):
            first = node.elts[0] if node.elts else None
            if isinstance(first, ast.Starred):
                inner = self.iterable_element_type(self.infer_expr_type(first.value))
            else:
                inner = self.infer_expr_type(first)
            return f"builtin:list[{inner}]" if inner else "builtin:list"
        if isinstance(node, ast.Dict):
            return "builtin:dict"
        if isinstance(node, ast.Set):
            return "builtin:set"
        if isinstance(node, ast.Tuple):
            return "builtin:tuple"
        if isinstance(node, ast.ListComp):
            inner = self.infer_expr_type(node.elt)
            return f"builtin:list[{inner}]" if inner else "builtin:list"
        if isinstance(node, ast.SetComp):
            inner = self.infer_expr_type(node.elt)
            return f"builtin:set[{inner}]" if inner else "builtin:set"
        if isinstance(node, ast.DictComp):
            return "builtin:dict"
        if isinstance(node, ast.GeneratorExp):
            inner = self.infer_expr_type(node.elt)
            return f"external:Iterable[{inner}]" if inner else "external:Iterable"
        if isinstance(node, ast.Constant):
            return f"builtin:{type(node.value).__name__}"
        if isinstance(node, ast.BinOp):
            return self.infer_expr_type(node.left) or self.infer_expr_type(node.right)
        if isinstance(node, ast.BoolOp):
            return next((inferred for value in node.values if (inferred := self.infer_expr_type(value))), None)
        if isinstance(node, ast.Subscript):
            receiver = self.infer_expr_type(node.value)
            if not receiver:
                return None
            if "[" in receiver and receiver.endswith("]"):
                return receiver.split("[", 1)[1][:-1] or None
            if receiver.startswith("external:"):
                return receiver
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                target, resolution = self.resolve_name(node.func.id)
                if target and self.symbol_records.get(target, {}).get("kind") == "class":
                    return f"symbol:{target}"
                if target:
                    annotation = self.symbol_records.get(target, {}).get("return_annotation")
                    if annotation:
                        try:
                            return self.infer_annotation_type(ast.parse(annotation, mode="eval").body)
                        except SyntaxError:
                            pass
                if resolution in {"external-import", "builtin"}:
                    if resolution == "builtin" and node.func.id in {"sorted", "list", "set", "tuple"} and node.args:
                        element = self.iterable_element_type(self.infer_expr_type(node.args[0]))
                        container = "list" if node.func.id == "sorted" else node.func.id
                        if element:
                            return f"builtin:{container}[{element}]"
                    prefix = "external" if resolution == "external-import" else "builtin"
                    return f"{prefix}:{node.func.id}"
            if isinstance(node.func, ast.Attribute):
                receiver = self.infer_expr_type(node.func.value)
                if receiver and receiver.startswith(("external:", "builtin:")):
                    return receiver
                target, resolution, text = self.resolve_attribute(node.func)
                if target:
                    annotation = self.symbol_records.get(target, {}).get("return_annotation")
                    if annotation:
                        try:
                            return self.infer_annotation_type(ast.parse(annotation, mode="eval").body)
                        except SyntaxError:
                            pass
                if resolution.startswith("external"):
                    return f"external:{text}"
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id in {"self", "cls"}:
                class_scope = self.current_class_scope()
                known = self.instance_attribute_types.get(class_scope, {}).get(node.attr)
                if known:
                    return known
            receiver = self.infer_expr_type(node.value)
            if receiver and receiver.startswith(("external:", "builtin:")):
                return receiver
        return None

    def add_unresolved(self, node: ast.AST, kind: str, target: str, reason: str, critical: bool = False) -> None:
        self.unresolved.append({
            "file": self.file_path,
            "source_symbol_id": self.caller,
            "kind": kind,
            "target": target,
            **self.location(node),
            "reason": reason,
            "critical": critical,
        })

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            module = alias.name
            self.import_aliases[local] = (module, None)
            self.imports.append({
                "file": self.file_path, "target_file": self.module_files.get(module),
                "module_specifier": alias.name, "imported_name": None, "local_name": local,
                **self.location(node), "resolution": "resolved" if module in self.module_files else "external",
            })

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = resolve_import_module(self.module, node.module, node.level, self.current_is_package)
        for alias in node.names:
            local = alias.asname or alias.name
            if alias.name == "*":
                self.add_unresolved(node, "import", f"{module}.*", "wildcard-import", True)
                continue
            self.import_aliases[local] = (module, alias.name)
            self.imports.append({
                "file": self.file_path, "target_file": self.module_files.get(module),
                "module_specifier": module, "imported_name": alias.name, "local_name": local,
                **self.location(node), "resolution": "resolved" if module in self.module_files else "external",
            })

    def enter_scope(self, node: ast.AST, name: str, kind: str) -> None:
        local = ".".join([*self.scope_names, name]) if self.scope_names else name
        symbol_id = self.symbols_by_location.get((local, getattr(node, "lineno", 1), getattr(node, "col_offset", 0)))
        if not symbol_id:
            symbol_id = self.symbols_by_module_local[(self.module, local)]
        self.scope_names.append(name)
        self.scope_ids.append(symbol_id)
        self.scope_kinds.append(kind)
        self.variable_types.append({})
        self.local_bindings.append(set())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            if node.args.vararg:
                args.append(node.args.vararg)
            if node.args.kwarg:
                args.append(node.args.kwarg)
            locals_collector = FunctionLocalCollector()
            for statement in node.body:
                locals_collector.visit(statement)
            self.local_bindings[-1].update(locals_collector.names)
            for argument in args:
                self.local_bindings[-1].add(argument.arg)
                inferred = self.infer_annotation_type(argument.annotation)
                if inferred:
                    self.variable_types[-1][argument.arg] = inferred
        self.generic_visit(node)
        self.local_bindings.pop()
        self.variable_types.pop()
        self.scope_kinds.pop()
        self.scope_ids.pop()
        self.scope_names.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.enter_scope(node, node.name, "class")

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        kind = "method" if self.scope_kinds and self.scope_kinds[-1] == "class" else "function"
        self.enter_scope(node, node.name, kind)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign) -> None:
        inferred = self.infer_expr_type(node.value)
        for target in node.targets:
            components = self.assignment_component_types(node.value) if isinstance(target, (ast.Tuple, ast.List)) else []
            if components and len(components) == len(target.elts):
                for item, component in zip(target.elts, components):
                    self.bind_target(item, component)
            else:
                self.bind_target(target, inferred)
            self.record_instance_attribute(target, inferred)
        self.generic_visit(node)

    def assignment_component_types(self, value: ast.AST) -> list[str | None]:
        if not isinstance(value, ast.Call):
            return []
        target: str | None = None
        if isinstance(value.func, ast.Name):
            target, _ = self.resolve_name(value.func.id)
        elif isinstance(value.func, ast.Attribute):
            target, _, _ = self.resolve_attribute(value.func)
        annotation = self.symbol_records.get(target or "", {}).get("return_annotation")
        if not annotation:
            return []
        try:
            parsed = ast.parse(annotation, mode="eval").body
        except SyntaxError:
            return []
        if not isinstance(parsed, ast.Subscript) or not isinstance(parsed.slice, ast.Tuple):
            return []
        return [self.infer_annotation_type(item) for item in parsed.slice.elts]

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            self.local_bindings[-1].add(node.target.id)
            inferred = self.infer_annotation_type(node.annotation) or self.infer_expr_type(node.value)
            if inferred:
                self.variable_types[-1][node.target.id] = inferred
        else:
            inferred = self.infer_annotation_type(node.annotation) or self.infer_expr_type(node.value)
            self.record_instance_attribute(node.target, inferred)
        self.generic_visit(node)

    def current_class_scope(self) -> str:
        for index in range(len(self.scope_kinds) - 1, -1, -1):
            if self.scope_kinds[index] == "class":
                return ".".join(self.scope_names[:index + 1])
        return ""

    def record_instance_attribute(self, target: ast.AST, inferred: str | None) -> None:
        if not inferred or not isinstance(target, ast.Attribute):
            return
        if isinstance(target.value, ast.Name) and target.value.id in {"self", "cls"}:
            class_scope = self.current_class_scope()
            if class_scope:
                self.instance_attribute_types[class_scope][target.attr] = inferred

    def bind_target(self, target: ast.AST, inferred: str | None = None) -> None:
        if isinstance(target, ast.Name):
            self.local_bindings[-1].add(target.id)
            if inferred:
                self.variable_types[-1][target.id] = inferred
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.bind_target(item)

    @staticmethod
    def iterable_element_type(inferred: str | None) -> str | None:
        if not inferred or "[" not in inferred or not inferred.endswith("]"):
            return None
        return inferred.split("[", 1)[1][:-1] or None

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        if (
            isinstance(node.target, (ast.Tuple, ast.List)) and len(node.target.elts) == 3
            and isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Attribute)
            and self.expression_text(node.iter.func) == "os.walk"
        ):
            self.bind_target(node.target.elts[0], "builtin:str")
            self.bind_target(node.target.elts[1], "builtin:list[builtin:str]")
            self.bind_target(node.target.elts[2], "builtin:list[builtin:str]")
        else:
            inferred = self.iterable_element_type(self.infer_expr_type(node.iter))
            if not inferred and isinstance(node.target, ast.Name):
                mapping_use = MappingUseCollector()
                for statement in [*node.body, *node.orelse]:
                    mapping_use.visit(statement)
                if node.target.id in mapping_use.names:
                    inferred = "builtin:dict"
            self.bind_target(node.target, inferred)
        for item in [*node.body, *node.orelse]:
            self.visit(item)

    visit_AsyncFor = visit_For

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type:
            self.visit(node.type)
        if node.name:
            self.local_bindings[-1].add(node.name)
        for item in node.body:
            self.visit(item)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars:
                self.bind_target(item.optional_vars, self.infer_expr_type(item.context_expr))
        for item in node.body:
            self.visit(item)

    visit_AsyncWith = visit_With

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.bind_target(node.target, self.infer_expr_type(node.value))

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.local_bindings.append(set())
        self.variable_types.append({})
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg:
            args.append(node.args.vararg)
        if node.args.kwarg:
            args.append(node.args.kwarg)
        for argument in args:
            self.local_bindings[-1].add(argument.arg)
            inferred = self.infer_annotation_type(argument.annotation)
            if inferred:
                self.variable_types[-1][argument.arg] = inferred
        self.visit(node.body)
        self.variable_types.pop()
        self.local_bindings.pop()

    def visit_comprehension_expression(self, node: ast.AST, element_nodes: list[ast.AST]) -> None:
        self.local_bindings.append(set())
        self.variable_types.append({})
        for generator in node.generators:  # type: ignore[attr-defined]
            self.visit(generator.iter)
            inferred = self.iterable_element_type(self.infer_expr_type(generator.iter))
            if not inferred and isinstance(generator.target, ast.Name):
                mapping_use = MappingUseCollector()
                for element in [*element_nodes, *generator.ifs]:
                    mapping_use.visit(element)
                if generator.target.id in mapping_use.names:
                    inferred = "builtin:dict"
            self.bind_target(generator.target, inferred)
            for condition in generator.ifs:
                self.visit(condition)
        for element in element_nodes:
            self.visit(element)
        self.variable_types.pop()
        self.local_bindings.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self.visit_comprehension_expression(node, [node.elt])

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self.visit_comprehension_expression(node, [node.key, node.value])

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return
        target, resolution = self.resolve_name(node.id)
        self.references.append({
            "file": self.file_path, "source_symbol_id": self.caller, "symbol_id": target,
            "name": node.id, **self.location(node), "context": "read", "resolution": resolution,
        })
        if not target and resolution == "unresolved-name":
            self.add_unresolved(node, "reference", node.id, resolution, critical=self.caller is not None)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        target, resolution, text = self.resolve_attribute(node)
        if target:
            self.references.append({
                "file": self.file_path, "source_symbol_id": self.caller, "symbol_id": target,
                "name": text, **self.location(node), "context": "read", "resolution": resolution,
            })
        self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:
        target: str | None = None
        resolution = "unresolved"
        target_text = "<dynamic>"
        if isinstance(node.func, ast.Name):
            target_text = node.func.id
            target, resolution = self.resolve_name(node.func.id)
            if not target and resolution == "local-value":
                resolution = "dynamic-dispatch"
        elif isinstance(node.func, ast.Attribute):
            target, resolution, target_text = self.resolve_attribute(node.func)
        else:
            try:
                target_text = ast.unparse(node.func)
            except Exception:
                pass
        self.calls.append({
            "file": self.file_path, "caller_symbol_id": self.caller, "callee_symbol_id": target,
            "callee_name": target_text, **self.location(node), "resolution": resolution,
            "confidence": 1.0 if target else 0.0,
        })
        if not target:
            critical = self.caller is not None and resolution in {"unresolved", "unresolved-name", "dynamic-dispatch"}
            self.add_unresolved(node, "call", target_text, resolution, critical=critical)
        self.generic_visit(node)


def analyze_project(project: Path, config: dict[str, Any] | None = None) -> dict[str, Any]:
    project = project.resolve()
    config = load_graph_config(project) if config is None else config
    files: list[dict[str, Any]] = []
    modules: list[dict[str, Any]] = []
    all_symbols: list[dict[str, Any]] = []
    parsed: list[tuple[Path, str, str, ast.AST, bool]] = []
    aliases_by_primary: dict[str, set[str]] = {}
    diagnostics: list[dict[str, Any]] = []

    for path in sorted(iter_python_files(project, config)):
        file_path = relative(project, path)
        module = module_name_for(project, path)
        text = read_source(path)
        files.append({
            "path": file_path, "language": "python", "sha256": sha256_text(text),
            "mtime_ns": path.stat().st_mtime_ns, "is_test": is_test_path(file_path),
            "module": module, "provider": "python-ast-symtable",
        })
        modules.append({"name": module, "file": file_path, "language": "python"})
        aliases_by_primary[module] = module_aliases_for(project, path, module)
        try:
            tree = ast.parse(text, filename=file_path)
            symtable.symtable(text, file_path, "exec")
        except (SyntaxError, ValueError) as error:
            diagnostics.append({
                "file": file_path, "severity": "error", "kind": "syntax",
                "line": getattr(error, "lineno", 1) or 1, "message": str(error),
            })
            continue
        collector = DefinitionCollector(module, file_path)
        collector.visit(tree)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for symbol in collector.symbols:
            groups[(symbol["local_qualified_name"], symbol["kind"])].append(symbol)
        for group in groups.values():
            base_id = group[0]["stable_id"]
            for index, symbol in enumerate(group):
                symbol["symbol_group_id"] = base_id
                symbol["declaration_index"] = index
                symbol["runtime_effective"] = index == len(group) - 1
                if len(group) > 1:
                    symbol["stable_id"] = f"{base_id}:declaration:{index}"
        for symbol in collector.symbols:
            scope_record = symbol.pop("_scope_record", None)
            symbol["scope_symbol_id"] = scope_record["stable_id"] if scope_record else None
        all_symbols.extend(collector.symbols)
        parsed.append((path, file_path, module, tree, path.name == "__init__.py"))

    symbols_by_module_local = {
        (item["module"], item["local_qualified_name"]): item["stable_id"]
        for item in all_symbols if item.get("runtime_effective", True)
    }
    alias_owners: dict[str, set[str]] = defaultdict(set)
    for primary, aliases in aliases_by_primary.items():
        for alias in aliases:
            alias_owners[alias].add(primary)
    for item in all_symbols:
        if not item.get("runtime_effective", True):
            continue
        for alias in aliases_by_primary.get(item["module"], set()):
            if alias == item["module"] or len(alias_owners[alias]) == 1:
                symbols_by_module_local[(alias, item["local_qualified_name"])] = item["stable_id"]
    symbols_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in all_symbols:
        symbols_by_file[item["file"]].append(item)
    module_files = {
        alias: item["file"]
        for item in modules
        for alias in aliases_by_primary.get(item["name"], {item["name"]})
        if alias == item["name"] or len(alias_owners[alias]) == 1
    }
    references: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for _, file_path, module, tree, is_package in parsed:
        collector = EdgeCollector(
            module, file_path, tree, symbols_by_file[file_path],
            symbols_by_module_local, module_files, is_package, all_symbols,
        )
        collector.visit(tree)
        references.extend(collector.references)
        calls.extend(collector.calls)
        imports.extend(collector.imports)
        unresolved.extend(collector.unresolved)

    for diagnostic in diagnostics:
        unresolved.append({
            "file": diagnostic["file"], "source_symbol_id": None, "kind": "file",
            "target": diagnostic["file"], "line": diagnostic["line"], "column": 0,
            "reason": "syntax-error", "critical": True,
        })

    return {
        "provider": "python-ast-symtable",
        "version": "1",
        "implementation_identity": sha256_text(Path(__file__).read_text(encoding="utf-8")),
        "languages": ["python"],
        "capabilities": sorted(REQUIRED_L2_CAPABILITIES),
        "files": files,
        "modules": modules,
        "symbols": all_symbols,
        "references": references,
        "calls": calls,
        "imports": imports,
        "unresolved_edges": unresolved,
        "diagnostics": diagnostics,
    }
