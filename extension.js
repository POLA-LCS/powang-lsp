const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');
const { createProtocol } = require('./protocol');

let serverProcess = null;
let diagnosticCollection = null;
let isDisposing = false;
const protocol = createProtocol();

function handleMessage(message) {
    if (protocol.resolvePending(message)) return;
    if (message.method === 'textDocument/publishDiagnostics') {
        const uri = message.params.uri;
        const diagnostics = (message.params.diagnostics || []).map(d => {
            const severity = d.severity === 1 ? vscode.DiagnosticSeverity.Error :
                            d.severity === 2 ? vscode.DiagnosticSeverity.Warning :
                            d.severity === 3 ? vscode.DiagnosticSeverity.Information :
                            vscode.DiagnosticSeverity.Hint;
            const range = new vscode.Range(
                d.range.start.line, d.range.start.character,
                d.range.end.line, d.range.end.character
            );
            const diag = new vscode.Diagnostic(range, d.message, severity);
            if (d.code !== undefined) diag.code = d.code;
            if (d.source) diag.source = d.source;
            return diag;
        });
        diagnosticCollection.set(vscode.Uri.parse(uri), diagnostics);
    }
}

function stopServer() {
    const proc = serverProcess;
    serverProcess = null;
    protocol.setProcess(null);
    if (proc) {
        proc.kill();
    }
}

function startServer(context) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const config = vscode.workspace.getConfiguration('powang.server');
    const pythonPath = config.get('pythonPath', 'python');
    const extraArgs = config.get('extraArgs', []);
    const repositoryPath = config.get('repositoryPath', '');

    let cwd = workspaceFolder || undefined;
    const scriptPath = path.join(context.extensionPath, 'server', 'powang_lsp.py');

    const fs = require('fs');
    let repoRoot = repositoryPath;
    if (!repoRoot && workspaceFolder) {
        const candidates = [workspaceFolder, path.join(workspaceFolder, 'powang')];
        for (const candidate of candidates) {
            if (fs.existsSync(path.join(candidate, 'src', 'parser.py')) || fs.existsSync(path.join(candidate, 'powang.py'))) {
                repoRoot = candidate;
                break;
            }
        }
    }
    if (repoRoot) {
        cwd = repoRoot;
    }

    serverProcess = spawn(pythonPath, [scriptPath, ...extraArgs], {
        cwd: cwd,
        env: { ...process.env, POWANG_REPO: repoRoot || cwd || process.cwd() },
        stdio: ['pipe', 'pipe', 'pipe'],
    });
    const proc = serverProcess;
    protocol.setProcess(proc);

    proc.stderr.on('data', (data) => {
        console.error('Powang LSP stderr:', data.toString());
    });

    proc.on('error', (error) => {
        if (serverProcess === proc) {
            serverProcess = null;
            protocol.setProcess(null);
        }
        vscode.window.showErrorMessage(`Powang LSP failed to start: ${error.message}`);
    });

    proc.stdout.on('data', (data) => {
        protocol.appendChunk(data).forEach(msg => handleMessage(msg));
    });

    proc.on('exit', (code) => {
        console.log('Powang LSP exited with code', code);
        if (serverProcess !== proc) return;
        if (!isDisposing) {
            serverProcess = null;
            protocol.setProcess(null);
            setTimeout(() => {
                if (!isDisposing && !serverProcess) {
                    startServer(context);
                }
            }, 1000);
        }
    });

    const rootUri = workspaceFolder ? vscode.Uri.file(workspaceFolder).toString() : null;
    protocol.request('initialize', {
        processId: process.pid,
        rootUri: rootUri,
        capabilities: {
            textDocument: {
                synchronization: { didSave: true, willSave: false, willSaveWaitUntil: false },
                completion: { completionItem: { snippetSupport: false } },
                hover: { contentFormat: ['plaintext', 'markdown'] },
                definition: { linkSupport: false },
                documentSymbol: { hierarchicalDocumentSymbolSupport: true },
                rename: { prepareSupport: false },
                semanticTokens: { requests: { full: true }, tokenTypes: [], tokenModifiers: [], formats: ['relative'] },
            },
            workspace: { symbol: {} },
        },
    }).catch(() => {});

    setTimeout(() => {
        protocol.send({ jsonrpc: '2.0', method: 'initialized', params: {} });
        vscode.workspace.textDocuments.forEach(doc => {
            if (doc.languageId === 'powang') {
                protocol.send({
                    jsonrpc: '2.0',
                    method: 'textDocument/didOpen',
                    params: {
                        textDocument: {
                            uri: doc.uri.toString(),
                            languageId: 'powang',
                            version: doc.version,
                            text: doc.getText(),
                        },
                    },
                });
            }
        });
    }, 100);
}

function activate(context) {
    diagnosticCollection = vscode.languages.createDiagnosticCollection('powang');

    startServer(context);

    const restartCommand = vscode.commands.registerCommand('powang.server.restart', () => {
        isDisposing = true;
        stopServer();
        isDisposing = false;
        startServer(context);
    });
    context.subscriptions.push(restartCommand);

    const configurationListener = vscode.workspace.onDidChangeConfiguration(event => {
        if (event.affectsConfiguration('powang.server')) {
            isDisposing = true;
            stopServer();
            isDisposing = false;
            startServer(context);
        }
    });
    context.subscriptions.push(configurationListener);

    const changeListener = vscode.workspace.onDidChangeTextDocument(event => {
        if (event.document.languageId === 'powang') {
            protocol.send({
                jsonrpc: '2.0',
                method: 'textDocument/didChange',
                params: {
                    textDocument: {
                        uri: event.document.uri.toString(),
                        version: event.document.version,
                    },
                    contentChanges: [{ text: event.document.getText() }],
                },
            });
        }
    });
    context.subscriptions.push(changeListener);

    const openListener = vscode.workspace.onDidOpenTextDocument(doc => {
        if (doc.languageId === 'powang') {
            protocol.send({
                jsonrpc: '2.0',
                method: 'textDocument/didOpen',
                params: {
                    textDocument: {
                        uri: doc.uri.toString(),
                        languageId: 'powang',
                        version: doc.version,
                        text: doc.getText(),
                    },
                },
            });
        }
    });
    context.subscriptions.push(openListener);

    const saveListener = vscode.workspace.onDidSaveTextDocument(doc => {
        if (doc.languageId === 'powang') {
            protocol.send({
                jsonrpc: '2.0',
                method: 'textDocument/didSave',
                params: {
                    textDocument: { uri: doc.uri.toString() },
                },
            });
        }
    });
    context.subscriptions.push(saveListener);

    const closeListener = vscode.workspace.onDidCloseTextDocument(doc => {
        if (doc.languageId === 'powang') {
            protocol.send({
                jsonrpc: '2.0',
                method: 'textDocument/didClose',
                params: {
                    textDocument: { uri: doc.uri.toString() },
                },
            });
        }
    });
    context.subscriptions.push(closeListener);

    const completionProvider = vscode.languages.registerCompletionItemProvider('powang', {
        provideCompletionItems(document, position) {
            return protocol.request('textDocument/completion', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(item => {
                    const ci = new vscode.CompletionItem(item.label);
                    ci.kind = item.kind === 14 ? vscode.CompletionItemKind.Keyword : vscode.CompletionItemKind.Function;
                    if (item.detail) ci.detail = item.detail;
                    return ci;
                });
            }).catch(() => []);
        },
    }, '.', ':');

    const hoverProvider = vscode.languages.registerHoverProvider('powang', {
        provideHover(document, position) {
            return protocol.request('textDocument/hover', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!result || !result.contents) return null;
                const value = typeof result.contents === 'string' ? result.contents : (result.contents.value || '');
                return new vscode.Hover(new vscode.MarkdownString(value));
            }).catch(() => null);
        },
    });

    const definitionProvider = vscode.languages.registerDefinitionProvider('powang', {
        provideDefinition(document, position) {
            return protocol.request('textDocument/definition', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!result) return null;
                const loc = Array.isArray(result) ? result[0] : result;
                if (!loc) return null;
                const uri = vscode.Uri.parse(loc.uri);
                const r = loc.range;
                return new vscode.Location(uri, new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character));
            }).catch(() => null);
        },
    });

    const declarationProvider = vscode.languages.registerDeclarationProvider('powang', {
        provideDeclaration(document, position) {
            return protocol.request('textDocument/declaration', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!result) return null;
                const loc = Array.isArray(result) ? result[0] : result;
                if (!loc) return null;
                const uri = vscode.Uri.parse(loc.uri);
                const r = loc.range;
                return new vscode.Location(uri, new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character));
            }).catch(() => null);
        },
    });

    const documentSymbolProvider = vscode.languages.registerDocumentSymbolProvider('powang', {
        provideDocumentSymbols(document) {
            return protocol.request('textDocument/documentSymbol', {
                textDocument: { uri: document.uri.toString() },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(s => new vscode.DocumentSymbol(
                    s.name,
                    '',
                    s.kind === 5 ? vscode.SymbolKind.Class :
                    s.kind === 12 ? vscode.SymbolKind.Function :
                    vscode.SymbolKind.Variable,
                    new vscode.Range(s.range.start.line, s.range.start.character, s.range.end.line, s.range.end.character),
                    new vscode.Range(s.selectionRange.start.line, s.selectionRange.start.character, s.selectionRange.end.line, s.selectionRange.end.character)
                ));
            }).catch(() => []);
        },
    });

    const workspaceSymbolProvider = vscode.languages.registerWorkspaceSymbolProvider({
        provideWorkspaceSymbols(query) {
            return protocol.request('workspace/symbol', { query }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(s => {
                    const loc = s.location;
                    return new vscode.SymbolInformation(
                        s.name,
                        s.kind === 5 ? vscode.SymbolKind.Class :
                    s.kind === 12 ? vscode.SymbolKind.Function :
                    vscode.SymbolKind.Variable,
                        '',
                        new vscode.Location(vscode.Uri.parse(loc.uri), new vscode.Range(loc.range.start.line, loc.range.start.character, loc.range.end.line, loc.range.end.character))
                    );
                });
            }).catch(() => []);
        },
    });

    const referenceProvider = vscode.languages.registerReferenceProvider('powang', {
        provideReferences(document, position) {
            return protocol.request('textDocument/references', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(loc => new vscode.Location(vscode.Uri.parse(loc.uri), new vscode.Range(loc.range.start.line, loc.range.start.character, loc.range.end.line, loc.range.end.character)));
            }).catch(() => []);
        },
    });

    const renameProvider = vscode.languages.registerRenameProvider('powang', {
        provideRenameEdits(document, position, newName) {
            return protocol.request('textDocument/rename', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
                newName: newName,
            }).then(result => {
                if (!result || !result.changes) return null;
                const edit = new vscode.WorkspaceEdit();
                Object.keys(result.changes).forEach(uri => {
                    result.changes[uri].forEach(e => {
                        edit.replace(vscode.Uri.parse(uri), new vscode.Range(e.range.start.line, e.range.start.character, e.range.end.line, e.range.end.character), e.newText);
                    });
                });
                return edit;
            }).catch(() => null);
        },
    });

    const formattingProvider = vscode.languages.registerDocumentFormattingEditProvider('powang', {
        provideDocumentFormattingEdits(document) {
            return protocol.request('textDocument/formatting', {
                textDocument: { uri: document.uri.toString() },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(e => new vscode.TextEdit(new vscode.Range(e.range.start.line, e.range.start.character, e.range.end.line, e.range.end.character), e.newText));
            }).catch(() => []);
        },
    });

    const semanticLegend = new vscode.SemanticTokensLegend(
        [
            'namespace',
            'type',
            'parameter',
            'variable',
            'property',
            'function',
            'method',
            'macro',
            'keyword',
            'comment',
            'string',
            'number',
            'operator',
            'builtin',
            'builtinType',
            'constant',
        ],
        []
    );
    const semanticProvider = vscode.languages.registerDocumentSemanticTokensProvider('powang', {
        provideDocumentSemanticTokens(document) {
            return protocol.request('textDocument/semanticTokens/full', {
                textDocument: { uri: document.uri.toString() },
            }).then(result => {
                if (!result || !Array.isArray(result.data)) return null;
                const builder = new vscode.SemanticTokensBuilder(semanticLegend);
                let line = 0;
                let char = 0;
                for (let i = 0; i < result.data.length; i += 5) {
                    const dl = result.data[i];
                    const dc = result.data[i + 1];
                    const length = result.data[i + 2];
                    const type = result.data[i + 3];
                    line += dl;
                    if (dl > 0) char = dc; else char += dc;
                    builder.push(line, char, length, type, 0);
                }
                return builder.build();
            }).catch(() => null);
        },
    }, semanticLegend);

    context.subscriptions.push(
        diagnosticCollection,
        completionProvider,
        hoverProvider,
        definitionProvider,
        declarationProvider,
        documentSymbolProvider,
        workspaceSymbolProvider,
        referenceProvider,
        renameProvider,
        formattingProvider,
        semanticProvider
    );

    context.subscriptions.push({
        dispose: () => {
            isDisposing = true;
            stopServer();
        },
    });
}

function deactivate() {
    isDisposing = true;
    if (serverProcess) {
        serverProcess.kill();
        serverProcess = null;
    }
}

module.exports = { activate, deactivate };
