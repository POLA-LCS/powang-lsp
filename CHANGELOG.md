# Changelog

## 0.5.0

### Added
- Distinct semantic token colors for builtins, builtin types, user types, module names,
  functions, methods, parameters, properties, macros, constants, variables and keywords.
- Bundled `Powang Dark` color theme with a unique color for each language feature.
- Expanded TextMate scopes for declarations, type annotations, builtins, builtin types,
  namespaces and properties.

## 0.4.0

### Added
- Bundled LSP server at `server/powang_lsp.py`.
- Hover for keywords, builtins, and identifiers.
- Go to definition and declaration.
- Document and workspace symbols.
- Find references and rename.
- Formatting and semantic tokens.
- Server restart command and crash recovery.
- Refreshed protocol client with monotonic request ids.

### Changed
- Builtin completion and highlighting track `print`, `println`, `format`, and `inputf`.
- Syntax highlighting covers `#! ... !#` block comments, `$"..."` interpolation,
  `match`, `case`, `const`, `?.`, `??` and `|>`.

## 0.2.0

### Added
- Syntax highlighting for all powang constructs.
- LSP diagnostics from the parser and gradual type checker.
- Keyword and builtin completion.
- Language configuration: brackets, comments, indentation, auto-closing pairs.