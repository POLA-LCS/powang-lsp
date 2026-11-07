const test = require('node:test');
const assert = require('node:assert/strict');
const { createProtocol } = require('../protocol');

function frame(message) {
    const body = Buffer.from(JSON.stringify(message), 'utf-8');
    return Buffer.concat([
        Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, 'ascii'),
        body,
    ]);
}

function fakeProcess() {
    const chunks = [];
    return {
        stdin: {
            writable: true,
            write(buffer) {
                chunks.push(buffer);
            },
        },
        chunks,
    };
}

test('fragmented frame is parsed once', () => {
    const protocol = createProtocol();
    const payload = frame({ jsonrpc: '2.0', method: 'test', params: { value: 1 } });
    const messages = [];
    for (let index = 0; index < payload.length; index += 3) {
        messages.push(...protocol.appendChunk(payload.subarray(index, index + 3)));
    }
    assert.deepEqual(messages, [{ jsonrpc: '2.0', method: 'test', params: { value: 1 } }]);
});

test('multiple frames in one chunk are parsed', () => {
    const protocol = createProtocol();
    const payload = Buffer.concat([
        frame({ jsonrpc: '2.0', id: 1, result: null }),
        frame({ jsonrpc: '2.0', method: 'notification', params: {} }),
    ]);
    assert.deepEqual(protocol.appendChunk(payload), [
        { jsonrpc: '2.0', id: 1, result: null },
        { jsonrpc: '2.0', method: 'notification', params: {} },
    ]);
});

test('stopping the process rejects pending requests', async () => {
    const protocol = createProtocol();
    protocol.setProcess(fakeProcess());
    const pending = protocol.request('test/method', {}, { timeout: 10000 });
    protocol.setProcess(null);
    await assert.rejects(pending, /LSP server stopped/);
});
