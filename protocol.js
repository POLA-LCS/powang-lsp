function createProtocol() {
    let proc = null;
    let messageId = 0;
    const pending = new Map();
    let buffer = Buffer.alloc(0);

    function setProcess(p) {
        if (p === null) {
            for (const entry of pending.values()) {
                clearTimeout(entry.timer);
                entry.reject(new Error('LSP server stopped'));
            }
            pending.clear();
        }
        proc = p;
        buffer = Buffer.alloc(0);
    }

    function send(message) {
        if (!proc || !proc.stdin.writable) return;
        const body = Buffer.from(JSON.stringify(message), 'utf-8');
        const header = Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, 'ascii');
        proc.stdin.write(Buffer.concat([header, body]));
    }

    function request(method, params, options = {}) {
        const id = ++messageId;
        const timeout = options.timeout ?? 2000;
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
                if (pending.has(id)) {
                    pending.delete(id);
                    reject(new Error('LSP request timed out'));
                }
            }, timeout);
            pending.set(id, { resolve, reject, timer });
            send({ jsonrpc: '2.0', id, method, params });
        });
    }

    function respond(id, result) {
        send({ jsonrpc: '2.0', id, result });
    }

    function respondError(id, code, message) {
        send({ jsonrpc: '2.0', id, error: { code, message } });
    }

    function resolvePending(message) {
        if (message.id === undefined || !pending.has(message.id)) return false;
        const entry = pending.get(message.id);
        clearTimeout(entry.timer);
        pending.delete(message.id);
        if (message.error) {
            entry.reject(new Error(message.error.message || 'LSP error'));
        } else {
            entry.resolve(message.result);
        }
        return true;
    }

    function appendChunk(chunk) {
        buffer = Buffer.concat([buffer, chunk]);
        const messages = [];
        while (true) {
            let headerEnd = buffer.indexOf('\r\n\r\n');
            let separatorLength = 4;
            if (headerEnd < 0) {
                headerEnd = buffer.indexOf('\n\n');
                separatorLength = 2;
            }
            if (headerEnd < 0) break;

            const header = buffer.subarray(0, headerEnd).toString('ascii');
            const match = header.match(/Content-Length:\s*(\d+)/i);
            if (!match) {
                buffer = buffer.subarray(headerEnd + separatorLength);
                continue;
            }
            const length = parseInt(match[1], 10);
            const bodyStart = headerEnd + separatorLength;
            if (buffer.length < bodyStart + length) break;
            const body = buffer.subarray(bodyStart, bodyStart + length);
            buffer = buffer.subarray(bodyStart + length);
            try {
                messages.push(JSON.parse(body.toString('utf-8')));
            } catch (e) {
                // ignore malformed messages
            }
        }
        return messages;
    }

    return { setProcess, send, request, respond, respondError, resolvePending, appendChunk, pending };
}

module.exports = { createProtocol };