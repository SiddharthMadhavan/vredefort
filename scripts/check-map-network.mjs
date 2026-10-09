import { loadEnv } from 'vite'
import fs from 'node:fs'
import ts from 'typescript'
import vm from 'node:vm'
const env = loadEnv('development', process.cwd(), 'VITE_')
const source = fs.readFileSync('src/config/map.ts', 'utf8').replaceAll('import.meta.env', JSON.stringify(env))
const exports = {}
vm.runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), { exports, URL })
console.log('Configured variables:', Object.keys(env).join(', '))
console.log('Style configuration valid:', !exports.configurationError)
async function check(url, label) {
  const target = exports.mapRequest(url).url
  try {
    const result = await fetch(target, { signal: AbortSignal.timeout(15000) })
    console.log(label, { host: new URL(target).hostname, status: result.status, type: result.headers.get('content-type') })
    if (result.ok && result.headers.get('content-type')?.includes('json')) return await result.json()
  } catch { console.log(label, 'Network request failed or timed out') }
}
if (!exports.configurationError) {
  if (typeof exports.mapStyle === 'string') {
    const style = await check(exports.mapStyle, 'Style')
    if (style) {
      console.log('Style layers:', style.layers?.length)
      for (const source of Object.values(style.sources || {})) {
        if (source.url?.startsWith('https://')) {
          const tilejson = await check(source.url, 'Source metadata')
          if (tilejson?.tiles?.[0]) await check(tilejson.tiles[0].replace('{z}', '11').replace('{x}', '1465').replace('{y}', '949'), 'Bengaluru tile')
        }
      }
    }
  } else {
    await check(exports.mapStyle.sources.basemap.tiles[0].replace('{z}', '11').replace('{x}', '1465').replace('{y}', '949'), 'Bengaluru basemap tile')
  }
}
await check('https://tiles.openfreemap.org/styles/dark', 'Key-free alternative style')
console.log('Local road data present:', fs.existsSync('public/data/bengaluru-roads.geojson'))
