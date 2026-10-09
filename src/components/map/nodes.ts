import { Marker, Popup, type GeoJSONSource, type FilterSpecification, type Map, type MapGeoJSONFeature, type MapMouseEvent } from 'maplibre-gl'
import nodesUrl from '../../../data/bengaluru-road-nodes.geojson?url'

export const NODE_SOURCE_ID = 'road-graph-nodes'
const HIT_LAYER_ID = 'road-graph-node-hit-area'
const ENDPOINT_LAYER_ID = 'selected-edge-endpoints'
type GraphNode = { id: string; number: number; kind: string; degree: number; coordinates: [number, number] }
const kindLabels: Record<string, string> = { junction_candidate: 'Junction candidate', endpoint: 'Road endpoint', loop_anchor: 'Loop anchor' }

function readNode(feature: MapGeoJSONFeature): GraphNode | null {
  if (feature.geometry.type !== 'Point') return null
  const p = feature.properties
  if (!p || typeof p.id !== 'string' || !Number.isInteger(p.number) || !Number.isInteger(p.degree)) return null
  return { id: p.id, number: p.number, kind: p.kind, degree: p.degree, coordinates: feature.geometry.coordinates.slice(0, 2) as [number, number] }
}

function details(node: GraphNode) {
  const content = document.createElement('section')
  content.className = 'node-details'
  content.setAttribute('aria-label', `Details for node ${node.number}`)
  const title = document.createElement('h2')
  title.textContent = `Node ${node.number}`
  const kind = document.createElement('p')
  kind.className = 'node-kind'
  kind.textContent = kindLabels[node.kind] || node.kind
  const list = document.createElement('dl')
  for (const [label, value] of [
    ['ID', node.id], ['Connections', String(node.degree)],
    ['Latitude', node.coordinates[1].toFixed(5)], ['Longitude', node.coordinates[0].toFixed(5)],
  ]) {
    const term = document.createElement('dt'), description = document.createElement('dd')
    term.textContent = label
    description.textContent = value
    list.append(term, description)
  }
  const note = document.createElement('p')
  note.className = 'node-note'
  note.textContent = 'Inferred from the selected road dataset. Click the dot to keep these details open.'
  content.append(title, kind, list, note)
  return content
}

export function addNodeInteractions(map: Map, onReady: () => void, onError: () => void, initialDataset = nodesUrl) {
  let active: GraphNode | null = null
  let marker: Marker | null = null
  let popup: Popup | null = null
  let pinned = false, visible = true, disposed = false
  let frame = 0
  let pendingPoint: { x: number; y: number } | null = null
  const timeout = window.setTimeout(onError, 20000)

  const clear = () => {
    active = null
    pinned = false
    popup?.off('close', close)
    popup?.remove()
    marker?.remove()
    popup = null
    marker = null
  }
  const close = () => clear()
  const reveal = (node: GraphNode) => {
    if (active?.id === node.id) return
    clear()
    active = node
    const dot = document.createElement('button')
    dot.type = 'button'
    dot.className = 'graph-node-marker'
    dot.setAttribute('aria-label', `Show details for node ${node.number}, ${node.degree} connections`)
    dot.addEventListener('click', event => {
      event.stopPropagation()
      pinned = true
      dot.setAttribute('aria-pressed', 'true')
      popup?.getElement().querySelector<HTMLButtonElement>('.maplibregl-popup-close-button')?.focus()
    })
    dot.addEventListener('keydown', event => { if (event.key === 'Escape') clear() })
    marker = new Marker({ element: dot }).setLngLat(node.coordinates).addTo(map)
    popup = new Popup({ className: 'node-popup', offset: 14, closeOnClick: false, focusAfterOpen: false, maxWidth: '280px' })
      .setLngLat(node.coordinates).setDOMContent(details(node)).addTo(map)
    popup.on('close', close)
  }
  const locate = () => {
    frame = 0
    if (!visible || pinned || !pendingPoint || !map.getLayer(HIT_LAYER_ID)) return
    const point = pendingPoint
    const features = map.queryRenderedFeatures([[point.x - 12, point.y - 12], [point.x + 12, point.y + 12]], { layers: [HIT_LAYER_ID] })
    let nearest: GraphNode | null = null, distance = 12 ** 2
    for (const feature of features) {
      const node = readNode(feature)
      if (!node) continue
      const projected = map.project(node.coordinates)
      const squared = (projected.x - point.x) ** 2 + (projected.y - point.y) ** 2
      if (squared <= distance) { nearest = node; distance = squared }
    }
    if (nearest) reveal(nearest)
    else clear()
  }
  const move = (event: MapMouseEvent) => {
    const target = event.originalEvent.target
    if (target instanceof Element && target.closest('.graph-node-marker, .node-popup, .edge-popup')) return
    pendingPoint = event.point
    if (!frame) frame = requestAnimationFrame(locate)
  }
  const leave = () => { pendingPoint = null; if (!pinned) clear() }
  const click = (event: MapMouseEvent) => {
    const target = event.originalEvent.target
    if (target instanceof Element && target.closest('.graph-node-marker, .node-popup, .edge-popup')) return
    if (pinned) return
    pendingPoint = event.point
    locate() // Also supports tapping near a node on touch screens.
    if (active) { pinned = true; event.preventDefault() }
  }
  const loaded = (event: { sourceId?: string; sourceDataType?: string; isSourceLoaded?: boolean }) => {
    if (event.sourceId === NODE_SOURCE_ID && (event.isSourceLoaded || event.sourceDataType === 'content')) {
      window.clearTimeout(timeout)
      onReady()
    }
  }
  map.on('sourcedata', loaded)
  map.addSource(NODE_SOURCE_ID, { type: 'geojson', data: initialDataset })
  // A nearly transparent hit layer allows discovery without displaying
  // thousands of permanent dots. Only the nearest hovered node gets a marker.
  map.addLayer({ id: HIT_LAYER_ID, type: 'circle', source: NODE_SOURCE_ID, paint: { 'circle-radius': 12, 'circle-color': '#7eac85', 'circle-opacity': 0.001 } })
  map.addLayer({ id: ENDPOINT_LAYER_ID, type: 'circle', source: NODE_SOURCE_ID, filter: ['==', ['get', 'id'], ''], paint: { 'circle-radius': 4, 'circle-color': '#7eac85', 'circle-stroke-color': '#c4e5c4', 'circle-stroke-width': 1.5 } })
  map.on('mousemove', move)
  map.getContainer().addEventListener('mouseleave', leave)
  map.on('click', click)
  return {
    setDataset(url: string) {
      clear()
      pendingPoint = null
      const source = map.getSource(NODE_SOURCE_ID) as GeoJSONSource | undefined
      source?.setData(url)
    },
    setVisible(value: boolean) {
      visible = value
      if (!value) clear()
      for (const layer of [HIT_LAYER_ID, ENDPOINT_LAYER_ID]) if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', value ? 'visible' : 'none')
    },
    setEdgeEndpoints(ids: string[] | null) {
      clear()
      const filter: FilterSpecification | null = ids ? ['in', ['get', 'id'], ['literal', ids]] : null
      if (map.getLayer(HIT_LAYER_ID)) map.setFilter(HIT_LAYER_ID, filter)
      if (map.getLayer(ENDPOINT_LAYER_ID)) map.setFilter(ENDPOINT_LAYER_ID, filter || ['==', ['get', 'id'], ''])
    },
    dispose() {
      if (disposed) return
      disposed = true
      window.clearTimeout(timeout)
      cancelAnimationFrame(frame)
      clear()
      map.off('sourcedata', loaded)
      map.off('mousemove', move)
      map.getContainer().removeEventListener('mouseleave', leave)
      map.off('click', click)
    },
  }
}
