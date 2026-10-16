import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const source = ts.transpileModule(
  readFileSync(new URL('../lib/verified-place-photos.ts', import.meta.url), 'utf8'),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } },
).outputText;
const { verifiedPlacePhotos } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const market = { name: 'Chợ Bình Tây', category: 'market', latitude: 10.7493311, longitude: 106.6510683 };

test('both live Binh Tay records receive the actual facade photograph', () => {
  for (const place of [market, { ...market, latitude: 10.75, longitude: 106.6535 }]) {
    const [photo] = verifiedPlacePhotos(place);
    assert.equal(photo.confidence, 'place');
    assert.match(photo.title, /2008/);
    assert.equal(photo.attribution, 'Bùi Thụy Đào Nguyên');
    assert.equal(photo.licenseUrl, 'https://creativecommons.org/licenses/by/3.0/');
    assert.ok(existsSync(new URL(`../public${photo.url}`, import.meta.url)));
  }
});

test('similar names, other businesses and distant namesakes never get the photo', () => {
  for (const place of [
    null,
    { ...market, name: 'Chợ Bình Thới' },
    { ...market, name: 'Quán ăn Chợ Bình Tây' },
    { ...market, category: 'restaurant' },
    { ...market, latitude: 10.8 },
    { ...market, longitude: Number.NaN },
  ]) assert.deepEqual(verifiedPlacePhotos(place), []);
});

test('Unicode and English names still identify the same place', () => {
  for (const name of ['Chợ Bình Tây'.normalize('NFD'), '  CHỢ BÌNH TÂY  ', 'Binh Tay Market']) {
    assert.equal(verifiedPlacePhotos({ ...market, name }).length, 1);
  }
});
