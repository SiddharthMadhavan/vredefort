import { readFile, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { buildRoadGraph } from './road-graph.mjs'

const data = new URL('../data/', import.meta.url)
const source = await readFile(new URL('bengaluru-road-widths.geojson', data), 'utf8')
const original = JSON.parse(source)
const features = original.features.flatMap(feature => feature.geometry.coordinates.map((coordinates, index) => ({
  type: 'Feature', id: `${feature.properties.id}_part_${index}`, properties: feature.properties,
  geometry: { type: 'LineString', coordinates },
})))
// Preserve exact KML coordinates: do not merge nearby roads or infer flyover connectivity.
const graph = buildRoadGraph({ type: 'FeatureCollection', features }, {
  coordinateKey: ([lon, lat]) => `kml_n_${lon}_${lat}`,
})
const records = new Map(features.map(feature => [feature.id, feature.properties]))
for (const edge of graph.edges) {
  edge.id = `kml_${edge.id}`
  edge.kml_road_ids = [...new Set(edge.source_feature_ids.map(id => records.get(id).id))]
}
// Edge IDs changed to a separate namespace; rebuild node adjacency.
for (const node of graph.nodes) node.edge_ids = node.edge_ids.map(id => `kml_${id}`)
await writeFile(new URL('bengaluru-kml-road-graph.json', data), JSON.stringify(graph))
await writeFile(new URL('bengaluru-kml-road-nodes.geojson', data), JSON.stringify({ type: 'FeatureCollection', features: graph.nodes.map(({ lon, lat, edge_ids, ...properties }) => ({
  type: 'Feature', id: properties.id, properties, geometry: { type: 'Point', coordinates: [lon, lat] },
})) }))
await writeFile(new URL('bengaluru-kml-road-edges.geojson', data), JSON.stringify({ type: 'FeatureCollection', features: graph.edges.map(({ coordinates, ...properties }) => ({
  type: 'Feature', id: properties.id, properties, geometry: { type: 'LineString', coordinates },
})) }))
const neighbours = new Map(graph.nodes.map(node => [node.id, []]))
for (const edge of graph.edges) { neighbours.get(edge.source).push(edge.target); neighbours.get(edge.target).push(edge.source) }
const seen = new Set(), components = []
for (const node of graph.nodes) {
  if (seen.has(node.id)) continue
  const queue = [node.id]; seen.add(node.id)
  for (let i = 0; i < queue.length; i++) for (const id of neighbours.get(queue[i])) if (!seen.has(id)) { seen.add(id); queue.push(id) }
  components.push(queue.length)
}
const metadata = {
  input: 'data/bengaluru-road-widths.geojson', inputSha256: createHash('sha256').update(source).digest('hex'),
  sourceFeatureCount: original.features.length, linePartCount: features.length,
  nodeCount: graph.nodes.length, edgeCount: graph.edges.length,
  nodeKinds: Object.fromEntries(['junction_candidate', 'endpoint', 'loop_anchor'].map(kind => [kind, graph.nodes.filter(node => node.kind === kind).length])),
  componentCount: components.length, largestComponent: Math.max(...components), simplification: graph.simplification,
  excludedSourceFeatures: graph.excluded_source_features,
  numbering: '1-based number sorted by longitude then latitude. Stable ID kml_n_<exact longitude>_<exact latitude>. Numbers can shift after dataset changes.',
  topology: 'Undirected multigraph. Split at endpoints and exactly shared/repeated stored vertices. Contract degree-two continuation nodes; retain one anchor for closed loops. Keep original geometry and KML road provenance.',
  lengths: 'Haversine sum along the original geometry, metres, rounded to three decimal places.',
  limitations: ['Geometric crossings and nearby endpoints are not joined without a shared stored coordinate.', 'Junction candidates are inferred, not verified physical junctions. Bridge/tunnel connectivity and turn restrictions are unavailable.', 'No one-way routing is inferred. KML widths remain on their original road records; merged graph edges can include multiple widths.'],
}
await writeFile(new URL('bengaluru-kml-road-graph.metadata.json', data), JSON.stringify(metadata, null, 2))
console.log(JSON.stringify(metadata, null, 2))
