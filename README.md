# Powang LSP

Syntax highlighting, diagnostics and completion for the [Powang](https://github.com/POLA-LCS/powang) programming language.

## Features

- **Syntax highlighting** via TextMate grammar and semantic tokens, including typed arrays,
  pattern matching, destructuring, interpolation and null-safe operators
- **Distinct colors** for builtins, builtin types, user types, module names, functions,
  methods, parameters, properties, macros, constants, variables and keywords
- **Diagnostics** from the parser and gradual type checker, including typed array element checks
- **Keyword and builtin completion**
- **Hover** for keywords, builtins, and identifiers
- **Go to definition and declaration**
- **Document and workspace symbols**
- **Find references and rename**
- **Formatting**
- **Language configuration**: brackets, comments, indentation rules, auto-closing pairs

## Colors

The extension ships the `Powang Dark` color theme. Every language feature has its own
color, including builtins, builtin types, user types, module names, functions, methods,
parameters, properties, macros, constants, variables and keywords.

Select it from `Preferences: Color Theme` and choose `Powang Dark`.

## Installation

### From the VS Code Marketplace (once published)

1. Open VS Code.
2. Press `Ctrl+Shift+X` to open the Extensions panel.
3. Search for `Powang`.
4. Click Install.

### From a `.vsix` file

1. Download the `.vsix` file from the [releases page](https://github.com/POLA-LCS/powang-lsp/releases).
2. Open VS Code.
3. Press `Ctrl+Shift+P`, run `Extensions: Install from VSIX...`, and select the file.

### From source (development)

```bash
git clone https://github.com/POLA-LCS/powang-lsp
cd powang-lsp
code --extensionDevelopmentPath=.
```

## LSP server

The extension bundles the LSP server at `server/powang_lsp.py` and starts it
automatically. The server requires Python 3.12+ and a checkout of the powang
repository, because it imports the language implementation from `src/`.

Configure the Python interpreter in your VS Code settings:

```json
{
  "powang.server.pythonPath": "python"
}
```

If Python is not on your PATH, set the full path:

```json
{
  "powang.server.pythonPath": "C:/Python312/python.exe"
}
```

Set `powang.server.repositoryPath` to the powang repository root. If the
workspace itself is the powang repository, the extension detects it
automatically. Set the `powang.server.extraArgs` setting to pass additional
arguments to the server.

## What the LSP does

- Publishes syntax diagnostics from the parser.
- Publishes type diagnostics from the gradual checker.
- Offers keyword and builtin completion.
- Provides hover, goto definition and declaration.
- Provides document and workspace symbols.
- Provides find references and rename.
- Provides formatting and semantic tokens.

## Links

- [Powang language repository](https://github.com/POLA-LCS/powang)
- [Issue tracker](https://github.com/POLA-LCS/powang-lsp/issues)
- [Changelog](CHANGELOG.md)
