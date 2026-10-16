import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const source = ts.transpileModule(readFileSync(new URL('../lib/ar-view.ts', import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { arViewOffset, arArrivalDistance } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('a nearby school disappears after turning away and returns when facing it', () => {
  assert.equal(arViewOffset(78, 78, 60), 0);
  assert.equal(arViewOffset(78, 180, 60), null);
  assert.equal(arViewOffset(78, 258, 60), null);
  assert.equal(arViewOffset(78, 78, 60), 0);
});

test('camera visibility wraps across north and uses portrait/landscape FOV', () => {
  assert.equal(arViewOffset(5, 355, 40), 10);
  assert.equal(arViewOffset(355, 5, 40), -10);
  assert.equal(arViewOffset(30, 0, 40), null);
  assert.equal(arViewOffset(30, 0, 63), 30);
});

test('schools 96-123 m away are not treated as arrived even with poor GPS', () => {
  for (const accuracy of [0, 13, 15, 200]) {
    for (const distance of [96, 103, 115, 123]) {
      assert.ok(distance > arArrivalDistance(accuracy));
    }
  }
  assert.ok(10 <= arArrivalDistance(13));
});
