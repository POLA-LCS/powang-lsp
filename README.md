# Powang LSP

Syntax highlighting, diagnostics and completion for the [Powang](https://github.com/POLA-LCS/powang) programming language.

## Features

- **Syntax highlighting** via TextMate grammar
- **Diagnostics** from the parser and gradual type checker
- **Keyword and builtin completion** (30 items)
- **Language configuration**: brackets, comments, indentation rules, auto-closing pairs

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

The extension starts the powang LSP server automatically. The server requires Python 3.12+ and the powang repository on the Python path.

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

The server script (`powang_lsp.py`) is expected to be at `<powang_repo>/tools/powang_lsp.py`. Set the `powang.server.extraArgs` setting to pass additional arguments.

## What the LSP does

- Publishes syntax diagnostics from the parser.
- Publishes type diagnostics from the gradual checker.
- Offers keyword and builtin completion.

It does not yet provide hover, rename or goto-definition.

## Links

- [Powang language repository](https://github.com/POLA-LCS/powang)
- [Issue tracker](https://github.com/POLA-LCS/powang-lsp/issues)
- [Changelog](CHANGELOG.md)
