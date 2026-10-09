import { Popup, type FilterSpecification, type Map, type MapGeoJSONFeature, type MapMouseEvent } from 'maplibre-gl'
import { ROAD_HIT_LAYER_ID, ROAD_LAYER_ID } from './roads'

export type SelectedEdge = { id: string; source: string; target: string }
export function filterSelectedEdge(map: Map, edgeId: string | null) {
  const filter: FilterSpecification | null = edgeId ? ['==', ['get', 'id'], edgeId] : null
  for (const layer of [ROAD_LAYER_ID, ROAD_HIT_LAYER_ID]) {
    if (map.getLayer(layer)) map.setFilter(layer, filter)
  }
}

function strings(value: unknown): string[] {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string')
  if (typeof value === 'string') {
    try { const parsed: unknown = JSON.parse(value); if (Array.isArray(parsed)) return strings(parsed) } catch { /* Plain road name. */ }
    return value ? [value] : []
  }
  return []
}

function detailContent(feature: MapGeoJSONFeature, reset: () => void) {
  const p = feature.properties || {}
  const section = document.createElement('section')
  section.className = 'node-details edge-details'
  section.setAttribute('aria-label', 'Selected road edge details')
  const title = document.createElement('h2')
  title.textContent = 'Road edge'
  const names = strings(p.names).length ? strings(p.names) : strings(p.name)
  const subtitle = document.createElement('p')
  subtitle.className = 'node-kind'
  subtitle.textContent = names.length ? names.join(' / ') : 'Unnamed road'
  const length = Number(p.length_m)
  const classes = strings(p.highways).length ? strings(p.highways) : strings(p.highway)
  const dl = document.createElement('dl')
  for (const [label, value] of [
    ['Edge ID', String(p.id)],
    ['Length', Number.isFinite(length) ? length >= 1000 ? `${(length / 1000).toFixed(2)} km` : `${Math.round(length)} m` : 'Unavailable'],
    ['Road class', classes.join(', ') || 'Unavailable'],
    ['Start node', String(p.source)], ['End node', String(p.target)],
  ]) {
    const dt = document.createElement('dt'), dd = document.createElement('dd')
    dt.textContent = label
    dd.textContent = value
    dl.append(dt, dd)
  }
  const note = document.createElement('p')
  note.className = 'node-note'
  note.textContent = 'One graph edge between its endpoint nodes. A named road may span several edges.'
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'show-all-roads'
  button.textContent = 'Show all roads'
  button.addEventListener('click', event => { event.stopPropagation(); reset() })
  section.append(title, subtitle, dl, note, button)
  return section
}

// Choose the closest line rather than an arbitrary feature at dense crossings.
export function lineDistanceSquared(point: { x: number; y: number }, coordinates: number[][], project: (coordinate: [number, number]) => { x: number; y: number }) {
  let best = Infinity
  for (let i = 1; i < coordinates.length; i++) {
    const a = project(coordinates[i - 1].slice(0, 2) as [number, number]), b = project(coordinates[i].slice(0, 2) as [number, number])
    const dx = b.x - a.x, dy = b.y - a.y
    const t = Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / (dx * dx + dy * dy || 1)))
    best = Math.min(best, (point.x - a.x - t * dx) ** 2 + (point.y - a.y - t * dy) ** 2)
  }
  return best
}

export function addEdgeInteractions(map: Map, onSelection: (edge: SelectedEdge | null) => void) {
  let popup: Popup | null = null
  let selected: string | null = null
  let visible = true
  const reset = () => {
    popup?.off('close', reset)
    popup?.remove()
    popup = null
    selected = null
    filterSelectedEdge(map, null)
    onSelection(null)
  }
  const pick = (event: MapMouseEvent) => {
    if (!visible || event.defaultPrevented || !map.getLayer(ROAD_HIT_LAYER_ID)) return
    const target = event.originalEvent.target
    if (target instanceof Element && target.closest('.graph-node-marker, .node-popup, .edge-popup, .hospital-marker, .fire-station-marker')) return
    const features = map.queryRenderedFeatures(event.point, { layers: [ROAD_HIT_LAYER_ID] })
    let nearest: MapGeoJSONFeature | null = null, distance = 8 ** 2
    for (const feature of features) {
      if (feature.geometry.type !== 'LineString' && feature.geometry.type !== 'MultiLineString') continue
      const lines: number[][][] = feature.geometry.type === 'LineString' ? [feature.geometry.coordinates] : feature.geometry.coordinates
      const squared = Math.min(...lines.map(line => lineDistanceSquared(event.point, line, coordinate => map.project(coordinate))))
      if (squared <= distance) { nearest = feature; distance = squared }
    }
    const p = nearest?.properties
    if (!nearest || !p || typeof p.id !== 'string' || typeof p.source !== 'string' || typeof p.target !== 'string') {
      if (selected) reset()
      return
    }
    reset()
    selected = p.id
    filterSelectedEdge(map, selected)
    onSelection({ id: p.id, source: p.source, target: p.target })
    popup = new Popup({ className: 'node-popup edge-popup', offset: 12, closeOnClick: false, maxWidth: '320px', focusAfterOpen: true })
      .setLngLat(event.lngLat).setDOMContent(detailContent(nearest, reset)).addTo(map)
    popup.on('close', reset)
  }
  const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && selected) reset() }
  map.on('click', pick)
  map.getContainer().addEventListener('keydown', escape)
  return {
    reset,
    setVisible(value: boolean) {
      visible = value
      if (!value) reset()
      for (const layer of [ROAD_LAYER_ID, ROAD_HIT_LAYER_ID]) if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', value ? 'visible' : 'none')
    },
    dispose() {
      popup?.off('close', reset)
      popup?.remove()
      popup = null
      map.off('click', pick)
      map.getContainer().removeEventListener('keydown', escape)
    },
  }
}
