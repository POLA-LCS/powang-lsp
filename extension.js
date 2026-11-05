const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');

let serverProcess = null;
let diagnosticCollection = null;
let buffer = '';
let messageId = 0;
const pendingRequests = new Map();

function send(message) {
    if (!serverProcess || !serverProcess.stdin.writable) return;
    const body = JSON.stringify(message);
    const header = `Content-Length: ${Buffer.byteLength(body, 'utf-8')}\r\n\r\n`;
    serverProcess.stdin.write(header + body);
}

function handleMessage(message) {
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
            return new vscode.Diagnostic(range, d.message, severity);
        });
        diagnosticCollection.set(vscode.Uri.parse(uri), diagnostics);
    } else if (message.id !== undefined && pendingRequests.has(message.id)) {
        const { resolve } = pendingRequests.get(message.id);
        pendingRequests.delete(message.id);
        resolve(message.result || []);
    }
}

function startServer(context) {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    const config = vscode.workspace.getConfiguration('powang.server');
    const pythonPath = config.get('pythonPath', 'python');
    const extraArgs = config.get('extraArgs', []);
    const repositoryPath = config.get('repositoryPath', '');

    let cwd = workspaceFolder || undefined;
    let lspArgs = ['-m', 'tools.powang_lsp', ...extraArgs];

    if (repositoryPath) {
        cwd = repositoryPath;
    } else if (workspaceFolder) {
        const path = require('path');
        const fs = require('fs');
        const repoScript = path.join(workspaceFolder, 'tools', 'powang_lsp.py');
        if (fs.existsSync(repoScript)) {
            // Run from the repository root so src/ is importable.
            cwd = workspaceFolder;
        }
    }

    serverProcess = spawn(pythonPath, lspArgs, {
        cwd: cwd,
        stdio: ['pipe', 'pipe', 'pipe'],
    });

    serverProcess.stderr.on('data', (data) => {
        console.error('Powang LSP stderr:', data.toString());
    });

    serverProcess.stdout.on('data', (data) => {
        buffer += data.toString('utf-8');
        while (true) {
            const match = buffer.match(/Content-Length:\s*(\d+)\r?\n\r?\n/);
            if (!match) break;
            const length = parseInt(match[1], 10);
            const headerEnd = match.index + match[0].length;
            if (buffer.length < headerEnd + length) break;
            const body = buffer.substring(headerEnd, headerEnd + length);
            buffer = buffer.substring(headerEnd + length);
            try {
                handleMessage(JSON.parse(body));
            } catch (e) {
                console.error('Failed to parse LSP message:', e);
            }
        }
    });

    serverProcess.on('exit', (code) => {
        console.log('Powang LSP exited with code', code);
    });

    const rootUri = workspaceFolder ? `file://${workspaceFolder}` : null;
    send({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
            processId: process.pid,
            rootUri: rootUri,
            capabilities: {
                textDocument: {
                    synchronization: { didSave: true, willSave: false, willSaveWaitUntil: false },
                    completion: { completionItem: { snippetSupport: false } },
                },
            },
        },
    });

    setTimeout(() => {
        send({ jsonrpc: '2.0', method: 'initialized', params: {} });
        vscode.workspace.textDocuments.forEach(doc => {
            if (doc.languageId === 'powang') {
                send({
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

    vscode.workspace.onDidChangeTextDocument(event => {
        if (event.document.languageId === 'powang') {
            send({
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

    vscode.workspace.onDidOpenTextDocument(doc => {
        if (doc.languageId === 'powang') {
            send({
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

    vscode.workspace.onDidSaveTextDocument(doc => {
        if (doc.languageId === 'powang') {
            send({
                jsonrpc: '2.0',
                method: 'textDocument/didSave',
                params: {
                    textDocument: { uri: doc.uri.toString() },
                },
            });
        }
    });

    const completionProvider = vscode.languages.registerCompletionItemProvider('powang', {
        provideCompletionItems(document, position) {
            return new Promise((resolve) => {
                const requestId = Date.now();
                pendingRequests.set(requestId, { resolve });
                send({
                    jsonrpc: '2.0',
                    id: requestId,
                    method: 'textDocument/completion',
                    params: {
                        textDocument: { uri: document.uri.toString() },
                        position: { line: position.line, character: position.character },
                    },
                });
                setTimeout(() => {
                    if (pendingRequests.has(requestId)) {
                        pendingRequests.delete(requestId);
                        resolve([]);
                    }
                }, 2000);
            });
        },
    }, '.');

    context.subscriptions.push(diagnosticCollection, completionProvider);

    context.subscriptions.push({
        dispose: () => {
            if (serverProcess) {
                serverProcess.kill();
                serverProcess = null;
            }
        },
    });
}

function deactivate() {
    if (serverProcess) {
        serverProcess.kill();
        serverProcess = null;
    }
}

module.exports = { activate, deactivate };
