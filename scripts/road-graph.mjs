const EARTH_RADIUS_M = 6371008.8
export const coordinateKey = ([lon, lat]) => `n_${Math.round(lon * 1e5)}_${Math.round(lat * 1e5)}`

export function distanceMetres(a, b) {
  const radians = Math.PI / 180
  const dLat = (b[1] - a[1]) * radians, dLon = (b[0] - a[0]) * radians
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * radians) * Math.cos(b[1] * radians) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(Math.min(1, h)))
}

export function buildRoadGraph(collection) {
  if (collection.type !== 'FeatureCollection' || !collection.features.length) throw new Error('Expected nonempty GeoJSON FeatureCollection')
  const positions = new Map()
  const candidates = new Set()
  const excluded = []
  const roads = collection.features.map((feature, index) => {
    if (feature.geometry?.type !== 'LineString') throw new Error(`Feature ${index} is not a LineString`)
    const coordinates = []
    for (const point of feature.geometry.coordinates) {
      if (!Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite) || Math.abs(point[0]) > 180 || Math.abs(point[1]) > 90) throw new Error(`Invalid coordinates in feature ${index}`)
      const key = coordinateKey(point)
      if (coordinates.length && coordinateKey(coordinates.at(-1)) === key) continue
      coordinates.push(point)
    }
    if (coordinates.length < 2) {
      excluded.push({ source_feature_id: feature.id ?? index, reason: 'zero_length_after_coordinate_deduplication' })
      return null
    }
    for (const point of coordinates) {
      const key = coordinateKey(point)
      if (!positions.has(key)) positions.set(key, { coordinate: point, occurrences: 0 })
      positions.get(key).occurrences++
    }
    candidates.add(coordinateKey(coordinates[0]))
    candidates.add(coordinateKey(coordinates.at(-1)))
    return { feature, index, coordinates }
  }).filter(Boolean)
  // Shared stored vertices and repeated vertices (including loops) are split
  // points. Geometric line crossings and nearby points are never snapped.
  for (const [key, position] of positions) if (position.occurrences > 1) candidates.add(key)
  const edges = []
  for (const { feature, index, coordinates } of roads) {
    let start = 0
    for (let end = 1; end < coordinates.length; end++) {
      if (!candidates.has(coordinateKey(coordinates[end]))) continue
      const path = coordinates.slice(start, end + 1)
      let length = 0
      for (let i = 1; i < path.length; i++) length += distanceMetres(path[i - 1], path[i])
      const properties = feature.properties || {}
      edges.push({
        id: `e_${index}_${start}_${end}`,
        source: coordinateKey(path[0]), target: coordinateKey(path.at(-1)),
        length_m: Math.round(length * 1000) / 1000,
        source_feature_id: feature.id ?? index,
        highway: properties.highway ?? null,
        ...(properties.name ? { name: properties.name } : {}),
        ...(properties.ref ? { ref: properties.ref } : {}),
        coordinates: path,
      })
      start = end
    }
  }
  const nodeById = new Map([...candidates].map(id => {
    const [lon, lat] = positions.get(id).coordinate
    return [id, { id, lon, lat, degree: 0, edge_ids: [] }]
  }))
  for (const edge of edges) {
    for (const id of [edge.source, edge.target]) {
      const node = nodeById.get(id)
      node.degree++ // A self-loop contributes two incidences to the degree.
      if (!node.edge_ids.includes(edge.id)) node.edge_ids.push(edge.id)
    }
  }
  const nodes = [...nodeById.values()].sort((a, b) => a.lon - b.lon || a.lat - b.lat)
  nodes.forEach((node, index) => {
    node.number = index + 1
    node.kind = node.degree >= 3 ? 'junction_candidate' : node.degree === 1 ? 'endpoint' : node.edge_ids.length === 1 ? 'loop_anchor' : 'continuation'
  })
  return removeContinuations({ schema_version: 2, directed: false, multigraph: true, coordinate_reference_system: 'EPSG:4326', excluded_source_features: excluded, nodes, edges })
}

function removeContinuations(graph) {
  const byNode = new Map(graph.nodes.map(node => [node.id, node]))
  const byEdge = new Map(graph.edges.map(edge => [edge.id, edge]))
  const anchors = new Set(graph.nodes.filter(node => node.kind !== 'continuation').map(node => node.id))
  // A component made entirely of degree-two nodes is a closed road loop.
  // Keep one deterministic loop anchor instead of deleting its road geometry.
  const seen = new Set()
  for (const node of graph.nodes) {
    if (seen.has(node.id)) continue
    const component = [node.id]
    seen.add(node.id)
    for (let i = 0; i < component.length; i++) {
      for (const edgeId of byNode.get(component[i]).edge_ids) {
        const edge = byEdge.get(edgeId)
        const other = edge.source === component[i] ? edge.target : edge.source
        if (!seen.has(other)) { seen.add(other); component.push(other) }
      }
    }
    if (!component.some(id => anchors.has(id))) anchors.add(component[0])
  }
  const used = new Set(), edges = []
  for (const node of graph.nodes) {
    if (!anchors.has(node.id)) continue
    for (const firstId of node.edge_ids) {
      if (used.has(firstId)) continue
      let current = node.id, edge = byEdge.get(firstId)
      const parts = [], coordinates = []
      while (true) {
        if (used.has(edge.id)) throw new Error('Road-chain traversal revisited an edge')
        used.add(edge.id)
        parts.push(edge)
        const forward = edge.source === current
        const path = forward ? edge.coordinates : [...edge.coordinates].reverse()
        coordinates.push(...(coordinates.length ? path.slice(1) : path))
        current = forward ? edge.target : edge.source
        if (anchors.has(current)) break
        const nextId = byNode.get(current).edge_ids.find(id => id !== edge.id)
        if (!nextId) throw new Error('Continuation node has no onward road')
        edge = byEdge.get(nextId)
      }
      const sourceFeatures = [...new Set(parts.map(part => part.source_feature_id))]
      const highways = [...new Set(parts.map(part => part.highway).filter(Boolean))]
      const names = [...new Set(parts.map(part => part.name).filter(Boolean))]
      const refs = [...new Set(parts.map(part => part.ref).filter(Boolean))]
      let length = 0
      for (let i = 1; i < coordinates.length; i++) length += distanceMetres(coordinates[i - 1], coordinates[i])
      edges.push({
        id: parts.length === 1 ? parts[0].id : `merged_${parts.map(part => part.id).sort()[0]}`,
        source: node.id, target: current,
        length_m: Math.round(length * 1000) / 1000,
        source_edge_ids: parts.map(part => part.id), source_feature_ids: sourceFeatures,
        ...(sourceFeatures.length === 1 ? { source_feature_id: sourceFeatures[0] } : {}),
        highway: highways.length === 1 ? highways[0] : null, highways,
        ...(names.length === 1 ? { name: names[0] } : {}), names,
        ...(refs.length === 1 ? { ref: refs[0] } : {}), refs,
        coordinates,
      })
    }
  }
  if (used.size !== graph.edges.length) throw new Error('Some road edges were lost during simplification')
  const nodes = graph.nodes.filter(node => anchors.has(node.id)).map(node => ({ ...node, degree: 0, edge_ids: [] }))
  const finalNodes = new Map(nodes.map(node => [node.id, node]))
  for (const edge of edges) for (const id of [edge.source, edge.target]) {
    const node = finalNodes.get(id)
    node.degree++
    if (!node.edge_ids.includes(edge.id)) node.edge_ids.push(edge.id)
  }
  nodes.forEach((node, index) => {
    node.number = index + 1
    node.kind = node.degree >= 3 ? 'junction_candidate' : node.degree === 1 ? 'endpoint' : 'loop_anchor'
  })
  return { ...graph, simplification: { removed_node_count: graph.nodes.length - nodes.length, original_node_count: graph.nodes.length, original_edge_count: graph.edges.length }, nodes, edges }
}
