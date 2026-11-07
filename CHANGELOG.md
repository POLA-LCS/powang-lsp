# Changelog

## 0.14.2

### Added

- Token and error source positions for diagnostics.
- Constructor inlay hints for positional `Type.[...]` calls.
- Inline completion for type access defaults, constructor members and
  constructor bodies.
- Code actions for named constructor arguments, member access and missing
  constructor arguments.
- ErrorLens-compatible diagnostics with `source`, `code`,
  `relatedInformation` and standard publishing on open, change, save and close.
- Native method completion, hover and signature help for `str`, `arr`, `map`,
  `tup`, `set`, `file` and `task`.
- Static and instance method completion and highlighting for user types.
- Set type documentation and syntax highlighting for `set`.
- Syntax highlighting and semantic tokens for `&>`.
- Improved inference for native methods, pipelines, sets and empty literals.

### Changed

- Bundled `src/` synced with powang 0.8.0.
- Document index tracks brace depth and type member depth.
- Completion and hover documentation include `typedeep`.

### Fixed

- Code actions are registered in the VS Code client.
- Diagnostics map `relatedInformation` and `tags` into VS Code.
- Constructor hints, completion and code actions skip strings and comments.
- Completion snippets no longer duplicate an existing `|`, `+` or `-`.
- Access actions respect the type access default.
- Add-missing and convert-to-named actions produce valid calls.
- Built-in and native member diagnostics carry parser source positions.

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