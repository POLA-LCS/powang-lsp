# Changelog

## 0.7.0

### Changed
- Builtin types renamed to `int`, `num`, `str` and `arr`.
- Hover, completion and semantic tokens now use the new type names.

## 0.6.0

### Added
- Rich hover with builtin documentation, declaration comments, signatures and variable types.
- Context-aware completion with documentation, module members, type members and snippets.
- Signature help for functions, methods, module members and builtins.
- Go to definition, declaration and type definition.
- Workspace references and rename with prepare support.
- Document highlights, document symbols and workspace symbols with hierarchy.
- Inlay hints for inferred variable types.
- Folding ranges for blocks and comments.
- Builtin type hover now reports the type instead of treating it as an identifier.
- Treat `as` as a keyword in completion, hover and syntax highlighting.

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