#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import ts from "typescript";


function argument(name, fallback = null) {
  const index = process.argv.indexOf(name);
  return index >= 0 && index + 1 < process.argv.length ? process.argv[index + 1] : fallback;
}


const project = path.resolve(argument("--project", process.cwd()));
const out = argument("--out");
if (!out) throw new Error("--out is required");
const graphConfigPath = argument("--graph-config");
const graphConfig = graphConfigPath ? JSON.parse(fs.readFileSync(graphConfigPath, "utf8")) : {};

const supported = new Set([".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"]);
const excluded = new Set([".git", ".adworkflow", ".codegraph", "node_modules", "dist", "build", "coverage", ".next", ".turbo"]);

function matchesPath(file, pattern) {
  const normalized = pattern.replaceAll("\\", "/").replace(/^\/+|\/+$/g, "");
  if (!normalized) return false;
  if (file === normalized || file.startsWith(`${normalized}/`)) return true;
  let escaped = "";
  for (let index = 0; index < normalized.length; index += 1) {
    const character = normalized[index];
    if (character === "*" && normalized[index + 1] === "*") {
      if (normalized[index + 2] === "/") {
        escaped += "(?:.*/)?";
        index += 2;
      } else {
        escaped += ".*";
        index += 1;
      }
    } else if (character === "*") {
      escaped += "[^/]*";
    } else if (character === "?") {
      escaped += "[^/]";
    } else {
      escaped += character.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    }
  }
  return new RegExp(`^${escaped}$`).test(file);
}

function configuredFile(fileName) {
  const file = relative(fileName);
  const language = languageFor(fileName);
  const languages = (graphConfig.languages || []).map((item) => String(item).toLowerCase());
  if (languages.length && !languages.includes(language)) return false;
  const include = graphConfig.include || [];
  const exclude = graphConfig.exclude || [];
  if (include.length && !include.some((pattern) => matchesPath(file, String(pattern)))) return false;
  return !exclude.some((pattern) => matchesPath(file, String(pattern)));
}

function walk(root, found = []) {
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.isDirectory() && excluded.has(entry.name)) continue;
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) walk(full, found);
    else if (supported.has(path.extname(entry.name).toLowerCase())) found.push(full);
  }
  return found;
}

function compilerInput() {
  const configPath = ts.findConfigFile(project, ts.sys.fileExists, "tsconfig.json");
  if (configPath) {
    const loaded = ts.readConfigFile(configPath, ts.sys.readFile);
    if (loaded.error) throw new Error(ts.flattenDiagnosticMessageText(loaded.error.messageText, "\n"));
    const parsed = ts.parseJsonConfigFileContent(loaded.config, ts.sys, path.dirname(configPath), {
      noEmit: true,
      allowJs: true,
      checkJs: true,
    }, configPath);
    return { rootNames: parsed.fileNames, options: parsed.options, configPath };
  }
  return {
    rootNames: walk(project),
    options: {
      noEmit: true,
      allowJs: true,
      checkJs: true,
      target: ts.ScriptTarget.ESNext,
      module: ts.ModuleKind.ESNext,
      moduleResolution: ts.ModuleResolutionKind.Node10,
      jsx: ts.JsxEmit.Preserve,
    },
    configPath: null,
  };
}

function insideProject(fileName) {
  const rel = path.relative(project, path.resolve(fileName));
  return rel !== "" && !rel.startsWith("..") && !path.isAbsolute(rel) && !rel.split(path.sep).some((part) => excluded.has(part));
}

function relative(fileName) {
  return path.relative(project, fileName).split(path.sep).join("/");
}

function moduleName(fileName) {
  let value = relative(fileName).replace(/\.(?:d\.)?(?:tsx?|jsx?|mts|cts|mjs|cjs)$/i, "");
  value = value.replace(/\/index$/, "");
  return value.split("/").filter(Boolean).join(".") || path.basename(project);
}

function languageFor(fileName) {
  return /\.(?:js|jsx|mjs|cjs)$/i.test(fileName) ? "javascript" : "typescript";
}

function hashText(text) {
  return requireHash(text);
}

import { createHash } from "node:crypto";
function requireHash(text) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function location(source, node) {
  const start = source.getLineAndCharacterOfPosition(node.getStart(source));
  const end = source.getLineAndCharacterOfPosition(node.getEnd());
  return { start_line: start.line + 1, start_column: start.character, end_line: end.line + 1, end_column: end.character };
}

function kindFor(node) {
  if (ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) || ts.isArrowFunction(node)) return "function";
  if (ts.isMethodDeclaration(node) || ts.isMethodSignature(node)) return "method";
  if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) return "class";
  if (ts.isInterfaceDeclaration(node)) return "interface";
  if (ts.isTypeAliasDeclaration(node)) return "type";
  if (ts.isEnumDeclaration(node)) return "enum";
  if (ts.isVariableDeclaration(node)) return "variable";
  return null;
}

function nameNodeFor(node) {
  if (node.name && ts.isIdentifier(node.name)) return node.name;
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) return node.name;
  return null;
}

function parentNames(node) {
  const names = [];
  let current = node.parent;
  while (current && !ts.isSourceFile(current)) {
    const name = nameNodeFor(current);
    if (name && kindFor(current)) names.unshift(name.text);
    current = current.parent;
  }
  return names;
}

function isExported(node) {
  return Boolean(node.modifiers?.some((item) => item.kind === ts.SyntaxKind.ExportKeyword || item.kind === ts.SyntaxKind.DefaultKeyword));
}

function signature(checker, node) {
  if (!ts.isFunctionLike(node)) return null;
  const resolved = checker.getSignatureFromDeclaration(node);
  return resolved ? checker.signatureToString(resolved) : null;
}

function isDeclarationIdentifier(node) {
  const parent = node.parent;
  return Boolean(parent && nameNodeFor(parent) === node);
}

const input = compilerInput();
const program = ts.createProgram({ rootNames: input.rootNames, options: input.options });
const checker = program.getTypeChecker();
const sourceFiles = program.getSourceFiles().filter((source) => insideProject(source.fileName)
  && supported.has(path.extname(source.fileName).toLowerCase()) && configuredFile(source.fileName));

const files = [];
const modules = [];
const symbols = [];
const references = [];
const calls = [];
const imports = [];
const unresolved_edges = [];
const diagnostics = [];
const symbolMap = new Map();
const declarationMap = new Map();

for (const source of sourceFiles) {
  const file = relative(source.fileName);
  const module = moduleName(source.fileName);
  const text = source.getFullText();
  files.push({
    path: file,
    language: languageFor(source.fileName),
    sha256: hashText(text),
    mtime_ns: Math.trunc(fs.statSync(source.fileName).mtimeMs * 1_000_000),
    is_test: /(^|\/)(tests?|__tests__)(\/|$)|\.(?:test|spec)\.[^.]+$/i.test(file),
    module,
    provider: "typescript-compiler-api",
  });
  modules.push({ name: module, file, language: languageFor(source.fileName) });

  function collect(node) {
    const kind = kindFor(node);
    const nameNode = nameNodeFor(node);
    if (kind && nameNode) {
      const local = [...parentNames(node), nameNode.text].join(".");
      const stable_id = `${languageFor(source.fileName)}:${module}:${local}:${kind}`;
      const compilerSymbol = checker.getSymbolAtLocation(nameNode);
      const record = {
        stable_id,
        file,
        module,
        name: nameNode.text,
        qualified_name: `${module}.${local}`,
        local_qualified_name: local,
        kind,
        ...location(source, node),
        scope_symbol_id: null,
        exported: isExported(node),
        signature: signature(checker, node),
      };
      if (!symbols.some((item) => item.stable_id === stable_id)) symbols.push(record);
      declarationMap.set(node, stable_id);
      if (compilerSymbol) symbolMap.set(compilerSymbol, stable_id);
    }
    ts.forEachChild(node, collect);
  }
  collect(source);
}

function canonicalSymbol(symbol) {
  if (!symbol) return null;
  if (symbol.flags & ts.SymbolFlags.Alias) {
    try { return checker.getAliasedSymbol(symbol); } catch { return symbol; }
  }
  return symbol;
}

function internalSymbolId(symbol) {
  const canonical = canonicalSymbol(symbol);
  if (!canonical) return null;
  if (symbolMap.has(canonical)) return symbolMap.get(canonical);
  for (const declaration of canonical.declarations || []) {
    if (declarationMap.has(declaration)) return declarationMap.get(declaration);
  }
  return null;
}

function isCallableDeclaration(node) {
  if (ts.isFunctionLike(node)) return true;
  return ts.isVariableDeclaration(node)
    && Boolean(node.initializer)
    && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer));
}

function enclosingSymbolId(node) {
  let current = node.parent;
  while (current && !ts.isSourceFile(current)) {
    if (declarationMap.has(current) && isCallableDeclaration(current)) return declarationMap.get(current);
    current = current.parent;
  }
  return null;
}

function isExternalSymbol(symbol) {
  const canonical = canonicalSymbol(symbol);
  const declarations = canonical?.declarations || [];
  return declarations.length > 0 && declarations.every((declaration) => {
    const source = declaration.getSourceFile();
    return source.isDeclarationFile || !insideProject(source.fileName);
  });
}

function lineColumn(source, node) {
  const point = source.getLineAndCharacterOfPosition(node.getStart(source));
  return { line: point.line + 1, column: point.character };
}

for (const source of sourceFiles) {
  const file = relative(source.fileName);
  function analyze(node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const specifier = node.moduleSpecifier.text;
      const resolved = ts.resolveModuleName(specifier, source.fileName, input.options, ts.sys).resolvedModule;
      const target = resolved && insideProject(resolved.resolvedFileName) ? relative(resolved.resolvedFileName) : null;
      const bindings = [];
      const clause = node.importClause;
      if (clause?.name) bindings.push({ imported: "default", local: clause.name.text });
      if (clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
        bindings.push({ imported: "*", local: clause.namedBindings.name.text });
      } else if (clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
        for (const element of clause.namedBindings.elements) {
          bindings.push({ imported: element.propertyName?.text || element.name.text, local: element.name.text });
        }
      }
      if (!bindings.length) bindings.push({ imported: null, local: null });
      for (const binding of bindings) imports.push({
        file,
        target_file: target,
        module_specifier: specifier,
        imported_name: binding.imported,
        local_name: binding.local,
        ...lineColumn(source, node),
        resolution: target ? "resolved" : (resolved ? "external" : "unresolved"),
      });
    }

    if (ts.isIdentifier(node) && !isDeclarationIdentifier(node) && !ts.isPropertyAccessExpression(node.parent)) {
      const compilerSymbol = checker.getSymbolAtLocation(node);
      const symbol_id = internalSymbolId(compilerSymbol);
      references.push({
        file,
        source_symbol_id: enclosingSymbolId(node),
        symbol_id,
        name: node.text,
        ...lineColumn(source, node),
        context: "read",
        resolution: symbol_id ? "type-checker" : (compilerSymbol ? "external" : "unresolved-name"),
      });
    }

    if (ts.isPropertyAccessExpression(node)) {
      const compilerSymbol = checker.getSymbolAtLocation(node.name);
      const symbol_id = internalSymbolId(compilerSymbol);
      references.push({
        file,
        source_symbol_id: enclosingSymbolId(node),
        symbol_id,
        name: node.getText(source),
        ...lineColumn(source, node),
        context: "read",
        resolution: symbol_id ? "type-checker" : (compilerSymbol ? "external" : "dynamic-dispatch"),
      });
    }

    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      const expression = node.expression;
      const lookup = ts.isPropertyAccessExpression(expression) ? expression.name : expression;
      const compilerSymbol = checker.getSymbolAtLocation(lookup);
      const callee_symbol_id = internalSymbolId(compilerSymbol);
      const external = !callee_symbol_id && isExternalSymbol(compilerSymbol);
      const caller_symbol_id = enclosingSymbolId(node);
      const text = expression.getText(source);
      const point = lineColumn(source, node);
      calls.push({
        file,
        caller_symbol_id,
        callee_symbol_id,
        callee_name: text,
        ...point,
        resolution: callee_symbol_id ? "type-checker" : (external ? "external" : "dynamic-dispatch"),
        confidence: callee_symbol_id ? 1.0 : 0.0,
      });
      if (!callee_symbol_id) unresolved_edges.push({
        file,
        source_symbol_id: caller_symbol_id,
        kind: "call",
        target: text,
        ...point,
        reason: external ? "external-call" : "dynamic-dispatch",
        critical: Boolean(caller_symbol_id && !external),
      });
    }
    ts.forEachChild(node, analyze);
  }
  analyze(source);
}

for (const diagnostic of program.getSyntacticDiagnostics()) {
  if (!diagnostic.file || !insideProject(diagnostic.file.fileName)) continue;
  const point = diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start || 0);
  const record = {
    file: relative(diagnostic.file.fileName),
    severity: "error",
    kind: "syntax",
    line: point.line + 1,
    message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
  };
  diagnostics.push(record);
  unresolved_edges.push({
    file: record.file,
    source_symbol_id: null,
    kind: "file",
    target: record.file,
    line: record.line,
    column: point.character,
    reason: "syntax-error",
    critical: true,
  });
}

const result = {
  provider: "typescript-compiler-api",
  version: ts.version,
  implementation_identity: hashText(fs.readFileSync(new URL(import.meta.url), "utf8")),
  languages: [...new Set(files.map((item) => item.language))].sort(),
  capabilities: ["calls", "definitions", "imports", "references", "source_ranges", "unresolved_edges"],
  files,
  modules,
  symbols,
  references,
  calls,
  imports,
  unresolved_edges,
  diagnostics,
  config_path: input.configPath ? relative(input.configPath) : null,
};

fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
fs.writeFileSync(path.resolve(out), `${JSON.stringify(result, null, 2)}\n`, "utf8");
