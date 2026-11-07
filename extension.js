const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');
const { createProtocol } = require('./protocol');

let serverProcess = null;
let diagnosticCollection = null;
let isDisposing = false;
const protocol = createProtocol();

function toDiagnosticSeverity(severity) {
    return severity === 1 ? vscode.DiagnosticSeverity.Error :
        severity === 2 ? vscode.DiagnosticSeverity.Warning :
        severity === 3 ? vscode.DiagnosticSeverity.Information :
        vscode.DiagnosticSeverity.Hint;
}

function toDiagnosticTag(tag) {
    return tag === 1 ? vscode.DiagnosticTag.Unnecessary :
        tag === 2 ? vscode.DiagnosticTag.Deprecated :
        undefined;
}

function toRange(range) {
    return new vscode.Range(
        range.start.line, range.start.character,
        range.end.line, range.end.character
    );
}

function toDiagnostic(d) {
    const diag = new vscode.Diagnostic(toRange(d.range), d.message, toDiagnosticSeverity(d.severity));
    if (d.code !== undefined) diag.code = d.code;
    if (d.source) diag.source = d.source;
    if (Array.isArray(d.tags)) {
        diag.tags = d.tags.map(toDiagnosticTag).filter(tag => tag !== undefined);
    }
    if (Array.isArray(d.relatedInformation)) {
        diag.relatedInformation = d.relatedInformation
            .filter(info => info && info.location)
            .map(info => new vscode.DiagnosticRelatedInformation(
                new vscode.Location(vscode.Uri.parse(info.location.uri), toRange(info.location.range)),
                info.message || ''
            ));
    }
    return diag;
}

function toRawDiagnostic(diag) {
    return {
        range: {
            start: { line: diag.range.start.line, character: diag.range.start.character },
            end: { line: diag.range.end.line, character: diag.range.end.character },
        },
        severity: diag.severity === vscode.DiagnosticSeverity.Error ? 1 :
            diag.severity === vscode.DiagnosticSeverity.Warning ? 2 :
            diag.severity === vscode.DiagnosticSeverity.Information ? 3 : 4,
        code: diag.code,
        source: diag.source,
        message: diag.message,
    };
}

function handleMessage(message) {
    if (protocol.resolvePending(message)) return;
    if (message.method === 'textDocument/publishDiagnostics') {
        const uri = message.params.uri;
        const diagnostics = (message.params.diagnostics || []).map(toDiagnostic);
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
                completion: { completionItem: { snippetSupport: true } },
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
                const kindMap = {
                    2: vscode.CompletionItemKind.Method,
                    3: vscode.CompletionItemKind.Function,
                    6: vscode.CompletionItemKind.Variable,
                    7: vscode.CompletionItemKind.Class,
                    9: vscode.CompletionItemKind.Module,
                    10: vscode.CompletionItemKind.Property,
                    14: vscode.CompletionItemKind.Keyword,
                    15: vscode.CompletionItemKind.Snippet,
                    21: vscode.CompletionItemKind.Constant,
                };
                return result.map(item => {
                    const ci = new vscode.CompletionItem(item.label);
                    ci.kind = kindMap[item.kind] || vscode.CompletionItemKind.Text;
                    if (item.detail) ci.detail = item.detail;
                    if (item.documentation) {
                        const documentation = item.documentation.value || item.documentation;
                        ci.documentation = new vscode.MarkdownString(documentation);
                    }
                    if (item.insertText) {
                        ci.insertText = item.insertText;
                        if (item.insertTextFormat === 2) {
                            ci.insertTextFormat = vscode.InsertTextFormat.Snippet;
                        }
                    }
                    if (item.filterText) ci.filterText = item.filterText;
                    if (item.sortText) ci.sortText = item.sortText;
                    return ci;
                });
            }).catch(() => []);
        },
    }, '.', ':', '@', '&', '|', '[', '+', '-');

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
                const locations = Array.isArray(result) ? result : [result];
                return locations.filter(Boolean).map(loc => {
                    const r = loc.range;
                    return new vscode.Location(
                        vscode.Uri.parse(loc.uri),
                        new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character)
                    );
                });
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
                const locations = Array.isArray(result) ? result : [result];
                return locations.filter(Boolean).map(loc => {
                    const r = loc.range;
                    return new vscode.Location(
                        vscode.Uri.parse(loc.uri),
                        new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character)
                    );
                });
            }).catch(() => null);
        },
    });

    const typeDefinitionProvider = vscode.languages.registerTypeDefinitionProvider('powang', {
        provideTypeDefinition(document, position) {
            return protocol.request('textDocument/typeDefinition', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!result) return null;
                const locations = Array.isArray(result) ? result : [result];
                return locations.filter(Boolean).map(loc => {
                    const r = loc.range;
                    return new vscode.Location(
                        vscode.Uri.parse(loc.uri),
                        new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character)
                    );
                });
            }).catch(() => null);
        },
    });

    const documentSymbolKindMap = {
        2: vscode.SymbolKind.Module,
        5: vscode.SymbolKind.Class,
        6: vscode.SymbolKind.Method,
        7: vscode.SymbolKind.Property,
        12: vscode.SymbolKind.Function,
        13: vscode.SymbolKind.Variable,
        14: vscode.SymbolKind.Constant,
    };

    const toDocumentSymbol = s => {
        const symbol = new vscode.DocumentSymbol(
            s.name,
            s.detail || '',
            documentSymbolKindMap[s.kind] || vscode.SymbolKind.Variable,
            new vscode.Range(s.range.start.line, s.range.start.character, s.range.end.line, s.range.end.character),
            new vscode.Range(s.selectionRange.start.line, s.selectionRange.start.character, s.selectionRange.end.line, s.selectionRange.end.character)
        );
        if (Array.isArray(s.children)) {
            symbol.children = s.children.map(toDocumentSymbol);
        }
        return symbol;
    };

    const documentSymbolProvider = vscode.languages.registerDocumentSymbolProvider('powang', {
        provideDocumentSymbols(document) {
            return protocol.request('textDocument/documentSymbol', {
                textDocument: { uri: document.uri.toString() },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(toDocumentSymbol);
            }).catch(() => []);
        },
    });

    const workspaceSymbolKindMap = {
        2: vscode.SymbolKind.Module,
        5: vscode.SymbolKind.Class,
        6: vscode.SymbolKind.Method,
        7: vscode.SymbolKind.Property,
        12: vscode.SymbolKind.Function,
        13: vscode.SymbolKind.Variable,
        14: vscode.SymbolKind.Constant,
    };

    const workspaceSymbolProvider = vscode.languages.registerWorkspaceSymbolProvider({
        provideWorkspaceSymbols(query) {
            return protocol.request('workspace/symbol', { query }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(s => {
                    const loc = s.location;
                    return new vscode.SymbolInformation(
                        s.name,
                        workspaceSymbolKindMap[s.kind] || vscode.SymbolKind.Variable,
                        s.containerName || '',
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
        prepareRename(document, position) {
            return protocol.request('textDocument/prepareRename', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!result || !result.range) return null;
                const r = result.range;
                return {
                    range: new vscode.Range(r.start.line, r.start.character, r.end.line, r.end.character),
                    placeholder: result.placeholder,
                };
            }).catch(() => null);
        },
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

    const codeActionKindMap = {
        quickfix: vscode.CodeActionKind.QuickFix,
        source: vscode.CodeActionKind.Source,
        'source.fixAll': vscode.CodeActionKind.SourceFixAll,
        'source.organizeImports': vscode.CodeActionKind.SourceOrganizeImports,
    };

    const codeActionProvider = vscode.languages.registerCodeActionsProvider('powang', {
        provideCodeActions(document, range, context) {
            return protocol.request('textDocument/codeAction', {
                textDocument: { uri: document.uri.toString() },
                range: {
                    start: { line: range.start.line, character: range.start.character },
                    end: { line: range.end.line, character: range.end.character },
                },
                context: {
                    diagnostics: (context.diagnostics || []).map(toRawDiagnostic),
                },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(item => {
                    const action = new vscode.CodeAction(
                        item.title,
                        codeActionKindMap[item.kind] || vscode.CodeActionKind.QuickFix
                    );
                    if (item.edit && item.edit.changes) {
                        const edit = new vscode.WorkspaceEdit();
                        Object.keys(item.edit.changes).forEach(uri => {
                            item.edit.changes[uri].forEach(change => {
                                edit.replace(
                                    vscode.Uri.parse(uri),
                                    toRange(change.range),
                                    change.newText
                                );
                            });
                        });
                        action.edit = edit;
                    }
                    if (item.command) {
                        action.command = {
                            title: item.command.title || item.title,
                            command: item.command.command,
                            arguments: item.command.arguments || [],
                        };
                    }
                    return action;
                });
            }).catch(() => []);
        },
    });

    const signatureProvider = vscode.languages.registerSignatureHelpProvider('powang', {
        provideSignatureHelp(document, position) {
            return protocol.request('textDocument/signatureHelp', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!result || !Array.isArray(result.signatures)) return null;
                const help = new vscode.SignatureHelp();
                help.signatures = result.signatures.map(s => {
                    const documentation = s.documentation && (s.documentation.value || s.documentation);
                    const info = new vscode.SignatureInformation(s.label, new vscode.MarkdownString(documentation || ''));
                    info.parameters = (s.parameters || []).map(p => new vscode.ParameterInformation(p.label));
                    return info;
                });
                help.activeSignature = result.activeSignature || 0;
                help.activeParameter = result.activeParameter || 0;
                return help;
            }).catch(() => null);
        },
    }, '(', ',');

    const highlightProvider = vscode.languages.registerDocumentHighlightProvider('powang', {
        provideDocumentHighlights(document, position) {
            return protocol.request('textDocument/documentHighlight', {
                textDocument: { uri: document.uri.toString() },
                position: { line: position.line, character: position.character },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(h => {
                    const range = new vscode.Range(h.range.start.line, h.range.start.character, h.range.end.line, h.range.end.character);
                    const kind = h.kind === 3 ? vscode.DocumentHighlightKind.Write :
                        h.kind === 2 ? vscode.DocumentHighlightKind.Read :
                        vscode.DocumentHighlightKind.Text;
                    return new vscode.DocumentHighlight(range, kind);
                });
            }).catch(() => []);
        },
    });

    const inlayHintProvider = vscode.languages.registerInlayHintsProvider('powang', {
        provideInlayHints(document, range) {
            return protocol.request('textDocument/inlayHint', {
                textDocument: { uri: document.uri.toString() },
                range: {
                    start: { line: range.start.line, character: range.start.character },
                    end: { line: range.end.line, character: range.end.character },
                },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(h => {
                    const hint = new vscode.InlayHint(
                        new vscode.Position(h.position.line, h.position.character),
                        h.label
                    );
                    hint.kind = h.kind === 1 ? vscode.InlayHintKind.Type : vscode.InlayHintKind.Parameter;
                    if (h.paddingLeft) hint.paddingLeft = true;
                    if (h.paddingRight) hint.paddingRight = true;
                    return hint;
                });
            }).catch(() => []);
        },
    });

    const foldingProvider = vscode.languages.registerFoldingRangeProvider('powang', {
        provideFoldingRanges(document) {
            return protocol.request('textDocument/foldingRange', {
                textDocument: { uri: document.uri.toString() },
            }).then(result => {
                if (!Array.isArray(result)) return [];
                return result.map(f => new vscode.FoldingRange(
                    f.startLine,
                    f.endLine,
                    f.kind === 'comment' ? vscode.FoldingRangeKind.Comment : vscode.FoldingRangeKind.Region
                ));
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
        signatureProvider,
        definitionProvider,
        declarationProvider,
        typeDefinitionProvider,
        highlightProvider,
        documentSymbolProvider,
        workspaceSymbolProvider,
        referenceProvider,
        renameProvider,
        formattingProvider,
        codeActionProvider,
        inlayHintProvider,
        foldingProvider,
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
