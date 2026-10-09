import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { buildRoadGraph } from './road-graph.mjs'

const inputUrl = new URL('../public/data/bengaluru-roads.geojson', import.meta.url)
const sourceText = await readFile(inputUrl, 'utf8')
const provenance = JSON.parse(await readFile(new URL('../public/data/bengaluru-roads.metadata.json', import.meta.url), 'utf8'))
const collection = JSON.parse(sourceText)
const graph = buildRoadGraph(collection)
const output = new URL('../data/', import.meta.url)
await mkdir(output, { recursive: true })
await writeFile(new URL('bengaluru-road-graph.json', output), JSON.stringify(graph))
await writeFile(new URL('bengaluru-road-nodes.geojson', output), JSON.stringify({
  type: 'FeatureCollection',
  features: graph.nodes.map(({ lon, lat, edge_ids, ...properties }) => ({
    type: 'Feature', id: properties.id, properties,
    geometry: { type: 'Point', coordinates: [lon, lat] },
  })),
}))
await writeFile(new URL('bengaluru-road-edges.geojson', output), JSON.stringify({
  type: 'FeatureCollection',
  features: graph.edges.map(({ coordinates, ...properties }) => ({
    type: 'Feature', id: properties.id, properties,
    geometry: { type: 'LineString', coordinates },
  })),
}))
const kinds = Object.fromEntries(['junction_candidate', 'endpoint', 'continuation', 'loop_anchor'].map(kind => [kind, graph.nodes.filter(node => node.kind === kind).length]))
const neighbours = new Map(graph.nodes.map(node => [node.id, []]))
for (const edge of graph.edges) {
  neighbours.get(edge.source).push(edge.target)
  neighbours.get(edge.target).push(edge.source)
}
const seen = new Set(), componentSizes = []
for (const node of graph.nodes) {
  if (seen.has(node.id)) continue
  const queue = [node.id]
  seen.add(node.id)
  for (let i = 0; i < queue.length; i++) for (const neighbour of neighbours.get(queue[i])) {
    if (!seen.has(neighbour)) { seen.add(neighbour); queue.push(neighbour) }
  }
  componentSizes.push(queue.length)
}
componentSizes.sort((a, b) => b - a)
await writeFile(new URL('bengaluru-road-graph.metadata.json', output), JSON.stringify({
  generatedAt: new Date().toISOString(),
  input: 'public/data/bengaluru-roads.geojson',
  inputSha256: createHash('sha256').update(sourceText).digest('hex'),
  source: provenance,
  nodeCount: graph.nodes.length, edgeCount: graph.edges.length, nodeKinds: kinds,
  simplification: graph.simplification,
  excludedSourceFeatures: graph.excluded_source_features,
  componentCount: componentSizes.length, componentSizes,
  totalEdgeLengthM: Math.round(graph.edges.reduce((sum, edge) => sum + edge.length_m, 0) * 1000) / 1000,
  numbering: 'number is 1-based, sorted by longitude then latitude. Stable ID n_<longitude*100000>_<latitude*100000>; numbers may shift if the dataset changes. Edges reference stable IDs.',
  edgeIds: 'Original segments use e_<source feature array index>_<start vertex index>_<end vertex index>. Merged chains use merged_<smallest original segment ID>. source_edge_ids and source_feature_ids retain provenance. These identifiers are local, not original OSM IDs.',
  topology: 'Undirected multigraph. Split at endpoints and exactly shared or repeated stored vertices, then contract all degree-two continuation nodes into road chains. Preserve geometry, lengths, connectivity and source provenance. Closed components retain one loop anchor. No geometric intersection splitting or proximity snapping.',
  lengths: 'Sum of Haversine distances along each edge, metres, mean Earth radius 6371008.8 m, rounded to millimetres; precision does not imply millimetre spatial accuracy.',
  limitations: [
    'Major-road extract only: local streets are not included.',
    'The source simplified geometry to 6 metres and rounded coordinates to five decimals; original OSM node IDs and some junction vertices are missing.',
    'Junction candidates are inferred from coordinate connectivity and degree, not verified physical junctions. Degree counts edge incidences, including parallel edges and loops.',
    'Geometric crossings without shared vertices are left disconnected. Bridge, tunnel and layer tags are unavailable, so grade separation cannot be verified at coincident coordinates.',
    'One-way directions and turn restrictions are not present in the input. This graph is not suitable for authoritative routing.',
  ],
}, null, 2))
console.log(JSON.stringify({ nodes: graph.nodes.length, edges: graph.edges.length, ...kinds, components: componentSizes.length, largestComponent: componentSizes[0] }, null, 2))
