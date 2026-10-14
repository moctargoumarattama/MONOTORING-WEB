'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { EventEmitter } = require('node:events');
const { Readable } = require('node:stream');
const { attachNocWebhook } = require('../integrations/baileys-noc.cjs');

const incoming = (id, message, extra = {}) => ({ key: { id, fromMe: false, remoteJid: '212770010264@s.whatsapp.net', ...extra }, message, messageTimestamp: Math.floor(Date.now() / 1000) });
const event = messages => ({ type: 'notify', sessionId: '1', messages });
const sleep = delay => new Promise(resolve => setTimeout(resolve, delay));
async function until(predicate) {
  for (let attempt = 0; attempt < 150; attempt++) { if (predicate()) return; await sleep(20); }
  assert.fail('Mock bridge did not finish within three seconds');
}
async function fixture(t, overrides = {}, responder) {
  const received = [];
  const logs = [];
  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', chunk => chunks.push(chunk));
    request.on('end', () => {
      received.push({ path: request.url, headers: request.headers, body: Buffer.concat(chunks) });
      if (responder) responder(response, received.length);
      else { response.writeHead(202, { 'Content-Type': 'application/json' }); response.end('{"queued":true}'); }
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const sock = { ev: new EventEmitter(), updateMediaMessage: async message => message };
  const detach = attachNocWebhook(sock, {
    adminPhone: '212770010264', sessionId: '1', webhookToken: 'private-mock-token',
    baseUrl: `http://127.0.0.1:${server.address().port}`, logger: { warn: message => logs.push(message) },
    downloadMediaMessage: async () => Readable.from([Buffer.from('OggS-test')]), ...overrides
  });
  t.after(async () => { detach(); server.closeAllConnections?.(); await new Promise(resolve => server.close(resolve)); });
  return { sock, detach, received, logs };
}

test('text and decrypted audio reach real HTTP mock without disturbing other gateway listeners', async t => {
  let downloads = 0;
  const f = await fixture(t, { downloadMediaMessage: async (_message, mode) => { downloads++; assert.equal(mode, 'stream'); return Readable.from([Buffer.from('OggS-'), Buffer.from('decrypted')]); } });
  let originalCalls = 0;
  f.sock.ev.on('messages.upsert', () => originalCalls++);
  f.sock.ev.emit('messages.upsert', event([incoming('TEXT_1', { conversation: 'statut' }), incoming('AUDIO_1', { audioMessage: { mimetype: 'audio/ogg; codecs=opus', seconds: 2 } })]));
  await until(() => f.received.length === 2);
  assert.equal(f.received[0].path, '/api/voice/webhook');
  assert.equal(JSON.parse(f.received[0].body).data.text, 'statut');
  assert.equal(f.received[1].path, '/api/voice/process');
  assert.equal(f.received[1].headers['x-gateway-secret'], 'private-mock-token');
  assert.equal(f.received[1].headers['x-message-id'], 'AUDIO_1');
  assert.equal(f.received[1].headers['x-session-id'], '1');
  assert.equal(f.received[1].body.toString(), 'OggS-decrypted');
  assert.equal(downloads, 1);
  assert.equal(originalCalls, 1);
  f.detach();
  assert.equal(f.sock.ev.listenerCount('messages.upsert'), 1);
});

test('other sender, groups, fromMe, historical messages and wrong session do not download or POST', async t => {
  const f = await fixture(t, { downloadMediaMessage: async () => assert.fail('unauthorized download') });
  f.sock.ev.emit('messages.upsert', event([
    incoming('OTHER', { conversation: 'statut' }, { remoteJid: '212600000000@s.whatsapp.net' }),
    incoming('GROUP', { conversation: 'statut' }, { remoteJid: 'group@g.us', participant: '212770010264@s.whatsapp.net' }),
    incoming('FROMME', { conversation: 'statut' }, { fromMe: true })
  ]));
  f.sock.ev.emit('messages.upsert', { ...event([incoming('HISTORY', { conversation: 'statut' })]), type: 'append' });
  f.sock.ev.emit('messages.upsert', { ...event([incoming('SESSION', { conversation: 'statut' })]), sessionId: '2' });
  await sleep(100);
  assert.equal(f.received.length, 0);
});

test('delivery retries preserve message ID and duplicate upserts are ignored', async t => {
  const f = await fixture(t, {}, (response, count) => { response.writeHead(count === 1 ? 503 : 202); response.end('{}'); });
  const message = incoming('RETRY_1', { conversation: 'statut' });
  f.sock.ev.emit('messages.upsert', event([message, message]));
  await until(() => f.received.length === 2);
  assert.deepEqual(f.received.map(row => row.headers['x-message-id']), ['RETRY_1', 'RETRY_1']);
  assert.equal(f.logs.length, 0);
});

test('stream size limit prevents an oversized upload, without logging media or secrets', async t => {
  const f = await fixture(t, { maxAudioBytes: 128, downloadMediaMessage: async () => Readable.from([Buffer.alloc(256)]) });
  f.sock.ev.emit('messages.upsert', event([incoming('TOO_BIG', { audioMessage: { mimetype: 'audio/ogg' } })]));
  await until(() => f.logs.length > 0);
  assert.equal(f.received.length, 0);
  assert.ok(f.logs.some(line => line.includes('audio_limit')));
  assert.ok(f.logs.every(line => !line.includes('private-mock-token')));
});

test('one active download and bounded queue preserve gateway responsiveness', async t => {
  let current = 0;
  let peak = 0;
  const f = await fixture(t, { maxQueued: 1, downloadMediaMessage: async () => { current++; peak = Math.max(peak, current); await sleep(80); current--; return Readable.from([Buffer.from('OggS')]); } });
  f.sock.ev.emit('messages.upsert', event(['Q1', 'Q2', 'Q3'].map(id => incoming(id, { audioMessage: { mimetype: 'audio/ogg' } }))));
  await until(() => f.received.length === 2);
  assert.equal(peak, 1);
  assert.ok(f.logs.some(line => line.includes('queue_full')));
  assert.deepEqual(f.received.map(row => row.headers['x-message-id']), ['Q1', 'Q2']);
});

test('LID alternate phone and device-specific administrator JIDs remain supported', async t => {
  const f = await fixture(t);
  f.sock.ev.emit('messages.upsert', event([incoming('LID', { conversation: 'statut' }, { remoteJid: '123456@lid', remoteJidAlt: '212770010264:2@s.whatsapp.net' })]));
  await until(() => f.received.length === 1);
  assert.equal(f.received[0].headers['x-whatsapp-from'], '212770010264@s.whatsapp.net');
});

test('public plaintext targets and invalid credentials fail before attaching', () => {
  const sock = { ev: new EventEmitter() };
  const config = { adminPhone: '212770010264', webhookToken: 'private-mock-token', downloadMediaMessage: async () => Readable.from([]) };
  assert.throws(() => attachNocWebhook(sock, { ...config, baseUrl: 'http://8.8.8.8:5050' }), /configuration_transport/);
  assert.throws(() => attachNocWebhook(sock, { ...config, webhookToken: 'bad\r\nheader' }), /configuration_identity/);
  assert.equal(sock.ev.listenerCount('messages.upsert'), 0);
});

test('an unresolved Baileys download cannot accumulate orphan downloads', async t => {
  let calls = 0;
  let release;
  const f = await fixture(t, {
    timeoutMs: 1000,
    downloadMediaMessage: async () => {
      calls++;
      if (calls === 1) return new Promise(resolve => { release = resolve; });
      return Readable.from([Buffer.from('OggS')]);
    }
  });
  f.sock.ev.emit('messages.upsert', event(['HANG', 'AFTER'].map(id => incoming(id, { audioMessage: { mimetype: 'audio/ogg' } }))));
  await until(() => f.logs.some(line => line.includes('download_timeout')));
  assert.equal(calls, 1);
  release(Readable.from([Buffer.from('discard-late-stream')]));
  await until(() => f.received.length === 1);
  assert.equal(calls, 2);
  assert.equal(f.received[0].headers['x-message-id'], 'AFTER');
});
