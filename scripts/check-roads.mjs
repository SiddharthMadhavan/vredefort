import fs from 'node:fs'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import ts from 'typescript'
const data = JSON.parse(fs.readFileSync(new URL('../public/data/bengaluru-roads.geojson', import.meta.url)))
const metadata = JSON.parse(fs.readFileSync(new URL('../public/data/bengaluru-roads.metadata.json', import.meta.url)))
assert.equal(data.type, 'FeatureCollection')
assert.equal(data.features.length, metadata.featureCount)
assert.ok(data.features.length > 10000)
let centralVertices = 0
for (const feature of data.features) {
  assert.equal(feature.geometry.type, 'LineString')
  assert.ok(feature.geometry.coordinates.length >= 2)
  assert.match(feature.properties.highway, /^(motorway|trunk|primary|secondary|tertiary)(_link)?$/)
  for (const [lon, lat] of feature.geometry.coordinates) {
    assert.ok(Number.isFinite(lon) && Number.isFinite(lat) && lon > 77 && lon < 79 && lat > 12 && lat < 14)
    if (Math.abs(lon - 77.5946) < .02 && Math.abs(lat - 12.9716) < .02) centralVertices++
  }
}
assert.ok(centralVertices > 100, 'Expected road vertices near the Bengaluru initial camera')
const source = fs.readFileSync(new URL('../src/components/map/roads.ts', import.meta.url), 'utf8').replace('import.meta.env.BASE_URL', JSON.stringify('/'))
const exports = {}
vm.runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), { exports, require: () => ({ default: '/assets/bengaluru-road-edges.geojson' }) })
const captured = {}
const layers = new Map()
let additions = 0
const map = {
  getSource: () => captured.source,
  getLayer: id => layers.get(id),
  addSource: (id, spec) => { captured.sourceId = id; captured.source = spec; additions++ },
  getStyle: () => ({ layers: [{ id: 'labels', type: 'symbol' }] }),
  addLayer: (layer, before) => { layers.set(layer.id, layer); if (layer.id === exports.ROAD_LAYER_ID) { captured.layer = layer; captured.before = before } },
}
exports.addRoadOverlay(map)
assert.equal(captured.source.data, '/assets/bengaluru-road-edges.geojson')
assert.equal(captured.layer.source, captured.sourceId)
assert.equal(captured.before, undefined, 'Roads must be above all basemap layers')
assert.equal(captured.layer.paint['line-opacity'], 1)
exports.addRoadOverlay(map)
assert.equal(additions, 1)
assert.ok(layers.has(exports.ROAD_HIT_LAYER_ID))
console.log(`Validated ${data.features.length} road geometries, Bengaluru coverage and overlay source/layer wiring.`)
