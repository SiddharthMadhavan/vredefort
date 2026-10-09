import fs from 'node:fs'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import ts from 'typescript'

const source = fs.readFileSync(new URL('../src/config/map.ts', import.meta.url), 'utf8')
for (const env of [
  { VITE_CARTO_API_KEY: 'test-key' },
  { VITE_MAPTILER_API_KEY: 'test-key' },
  { VITE_MAP_STYLE_URL: 'raw-key' },
  { VITE_MAP_STYLE_URL: 'https://example.com/style.json' },
]) {
  const code = ts.transpile(source.replaceAll('import.meta.env', JSON.stringify(env)), { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 })
  const exports = {}
  vm.runInNewContext(code, { exports, URL })
  if (env.VITE_CARTO_API_KEY) {
    assert.equal(exports.mapRequest('https://basemaps.cartocdn.com/tile.png').url, 'https://basemaps.cartocdn.com/tile.png?key=test-key')
    assert.equal(exports.mapRequest('https://example.com/tile.png').url, 'https://example.com/tile.png')
    assert.equal(exports.mapRequest('https://basemaps.cartocdn.com/tile.png?key=existing').url, 'https://basemaps.cartocdn.com/tile.png?key=existing')
  }
  if (env.VITE_MAPTILER_API_KEY) assert.match(exports.mapStyle, /streets-v4-dark\/style.json\?key=test-key/)
  if (env.VITE_MAP_STYLE_URL === 'raw-key') assert.ok(exports.configurationError)
  if (env.VITE_MAP_STYLE_URL?.startsWith('https')) assert.equal(exports.configurationError, '')
}
console.log('Map configuration checks passed.')
