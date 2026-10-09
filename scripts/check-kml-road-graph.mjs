import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import ts from 'typescript'
import { createRequire } from 'node:module'
import { distanceMetres } from './road-graph.mjs'

const load = async name => JSON.parse(await readFile(`data/${name}`, 'utf8'))
const graph = await load('bengaluru-kml-road-graph.json')
const original = await load('bengaluru-road-widths.geojson')
const nodes = new Map(graph.nodes.map(node => [node.id, node]))
const edges = new Map(graph.edges.map(edge => [edge.id, edge]))
assert.equal(nodes.size, graph.nodes.length)
assert.equal(edges.size, graph.edges.length)
assert.ok(graph.nodes.every(node => node.kind !== 'continuation'))
const incidence = new Map(graph.nodes.map(node => [node.id, 0]))
const parts = new Set()
for (const edge of graph.edges) {
  const start = nodes.get(edge.source), end = nodes.get(edge.target)
  assert.ok(start && end)
  assert.deepEqual(edge.coordinates[0], [start.lon, start.lat])
  assert.deepEqual(edge.coordinates.at(-1), [end.lon, end.lat])
  incidence.set(start.id, incidence.get(start.id) + 1)
  incidence.set(end.id, incidence.get(end.id) + 1)
  for (const id of edge.source_feature_ids) parts.add(id)
}
graph.nodes.forEach((node, index) => {
  assert.equal(node.number, index + 1)
  assert.equal(node.degree, incidence.get(node.id))
  assert.ok(node.edge_ids.every(id => edges.has(id) && [edges.get(id).source, edges.get(id).target].includes(node.id)))
})
let originalLength = 0, partCount = 0
for (const road of original.features) road.geometry.coordinates.forEach((line, index) => {
  partCount++
  assert.ok(parts.has(`${road.properties.id}_part_${index}`))
  for (let i = 1; i < line.length; i++) originalLength += distanceMetres(line[i - 1], line[i])
})
assert.equal(parts.size, partCount)
assert.ok(Math.abs(originalLength - graph.edges.reduce((sum, edge) => sum + edge.length_m, 0)) <= graph.edges.length * .00051)
console.log(`KML graph verified: ${nodes.size} nodes, ${edges.size} edges; every original line part and total road length preserved.`)

const metadata = await load('bengaluru-road-widths.metadata.json')
const exports = {}
const compiled = ts.transpileModule(await readFile('src/components/map/widths.ts', 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
vm.runInNewContext(compiled, { exports, require: name => name.includes('metadata') ? { default: metadata } : {} })
const require = createRequire(import.meta.url)
const { createExpression } = require('@maplibre/maplibre-gl-style-spec')
for (const field of ['RR_WIDTH_P', 'RR_width_B']) {
  const expression = createExpression(exports.widthStroke(field), { type: 'number' })
  assert.equal(expression.result, 'success', JSON.stringify(expression.value))
  for (const zoom of [10, 11, 14, 18]) {
    const evaluate = value => expression.value.evaluate({ zoom }, { properties: { [field]: value } })
    const narrow = evaluate(metadata.widthFields[field].min), wide = evaluate(metadata.widthFields[field].max)
    assert.ok(narrow > 0 && wide > narrow)
    assert.ok(Math.abs(wide / narrow - 1.35) < .000001)
  }
}
console.log('Both width fields produce a valid MapLibre expression with a subtle 35% maximum thickness increase.')
