import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { webcrypto } from 'node:crypto';
import { test } from 'node:test';
import ts from 'typescript';

const source = ts.transpileModule(
  readFileSync(new URL('../lib/telemetry.ts', import.meta.url), 'utf8'),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  },
).outputText;
const storage = () => {
  const entries = new Map();
  return {
    getItem: (key) => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
  };
};
async function loadPage(
  localStorage,
  sessionStorage,
  ua = 'Desktop Browser',
  touches = 0,
) {
  globalThis.window = {
    crypto: webcrypto,
    localStorage,
    sessionStorage,
    navigator: { userAgent: ua, maxTouchPoints: touches },
  };
  const sent = [];
  globalThis.fetch = async (_url, request) => {
    sent.push(...JSON.parse(request.body).events);
    return { ok: true, json: async () => ({ delivery: 'redis-stream' }) };
  };
  const { getTelemetry } = await import(
    `data:text/javascript;base64,${Buffer.from(source).toString('base64')}#${webcrypto.randomUUID()}`
  );
  const client = getTelemetry('http://test');
  client.capturePageView();
  client.capturePageView(); // React strict-mode remount.
  await client.drain();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].event_type, 'page_view');
  assert.equal(sent[0].location, undefined);
  assert.deepEqual(Object.keys(sent[0].metadata).sort(), [
    'device',
    'visit_id',
  ]);
  return sent[0];
}

test('one view per load; reloads share a visit, new tabs share only the browser', async () => {
  const local = storage(),
    tab = storage();
  const first = await loadPage(local, tab);
  const reload = await loadPage(local, tab);
  const newTab = await loadPage(local, storage());
  assert.equal(first.session_id, reload.session_id);
  assert.equal(first.session_id, newTab.session_id);
  assert.equal(first.metadata.visit_id, reload.metadata.visit_id);
  assert.notEqual(first.metadata.visit_id, newTab.metadata.visit_id);
  assert.notEqual(first.id, reload.id);
});

test('storage restrictions do not break the app or page-view tracking', async () => {
  const blocked = {
    getItem() {
      throw new Error('disabled');
    },
    setItem() {
      throw new Error('disabled');
    },
  };
  const event = await loadPage(blocked, blocked);
  assert.match(event.session_id, /^[0-9a-f-]{36}$/);
});

test('classifies phones, tablets, desktop-mode iPads and computers', async () => {
  for (const [ua, touches, device] of [
    ['iPhone Mobile', 1, 'mobile'],
    ['Android Mobile', 1, 'mobile'],
    ['Android Tablet', 1, 'tablet'],
    ['Macintosh', 5, 'tablet'],
    ['Windows', 0, 'desktop'],
  ]) {
    const event = await loadPage(storage(), storage(), ua, touches);
    assert.equal(event.metadata.device, device);
  }
});
