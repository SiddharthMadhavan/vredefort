import { Popup, type ExpressionSpecification, type Map, type MapMouseEvent } from 'maplibre-gl'
import widthsUrl from '../../../data/bengaluru-road-widths.geojson?url'
import metadata from '../../../data/bengaluru-road-widths.metadata.json'
import { lineDistanceSquared } from './edges'

export const WIDTH_SOURCE_ID = 'kml-road-widths'
const WIDTH_LAYER_ID = 'kml-road-width-lines'
const WIDTH_HIT_ID = 'kml-road-width-hit-area'
export type WidthField = 'RR_WIDTH_P' | 'RR_width_B'
export const widthStatistics = metadata.widthFields

export function widthColor(field: WidthField): ExpressionSpecification {
  const { min, max } = widthStatistics[field]
  return ['case', ['all', ['has', field], ['>', ['to-number', ['get', field], 0], 0]],
    ['interpolate', ['linear'], ['to-number', ['get', field], 0], min, '#8a9290', min + (max - min) * .25, '#728479', min + (max - min) * .5, '#566f60', max, '#344b3c'], '#8b909a']
}

export function widthStroke(field: WidthField): ExpressionSpecification {
  const { min, max } = widthStatistics[field]
  // Keep the increase subtle: the widest roads are only 35% thicker.
  const scale: ExpressionSpecification = ['interpolate', ['linear'], ['to-number', ['get', field], min], min, 1, max, 1.35]
  return ['interpolate', ['linear'], ['zoom'], 10, ['*', 1.5, scale], 14, ['*', 3, scale], 18, ['*', 6, scale]]
}

export function addWidthOverlay(map: Map, onReady: () => void, onError: () => void, onSelected: (selected: boolean) => void) {
  let field: WidthField = 'RR_WIDTH_P'
  let visible = true, selected = false
  let popup: Popup | null = null
  const timeout = window.setTimeout(onError, 30000)
  const loaded = (event: { sourceId?: string; sourceDataType?: string; isSourceLoaded?: boolean }) => {
    if (event.sourceId === WIDTH_SOURCE_ID && (event.isSourceLoaded || event.sourceDataType === 'content')) { window.clearTimeout(timeout); onReady() }
  }
  const reset = () => {
    popup?.off('close', reset)
    popup?.remove()
    popup = null
    selected = false
    for (const layer of [WIDTH_LAYER_ID, WIDTH_HIT_ID]) if (map.getLayer(layer)) map.setFilter(layer, null)
    onSelected(false)
  }
  map.on('sourcedata', loaded)
  map.addSource(WIDTH_SOURCE_ID, { type: 'geojson', data: widthsUrl })
  map.addLayer({ id: WIDTH_LAYER_ID, type: 'line', source: WIDTH_SOURCE_ID, layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: {
    'line-color': widthColor(field), 'line-opacity': 1,
    'line-width': widthStroke(field),
  } })
  map.addLayer({ id: WIDTH_HIT_ID, type: 'line', source: WIDTH_SOURCE_ID, paint: { 'line-width': 14, 'line-opacity': .001, 'line-color': '#ffffff' } })
  const click = (event: MapMouseEvent) => {
    if (!visible || event.defaultPrevented) return
    const target = event.originalEvent.target
    if (target instanceof Element && target.closest('.node-popup, .graph-node-marker')) return
    const features = map.queryRenderedFeatures(event.point, { layers: [WIDTH_HIT_ID] })
    let closest = null, distance = 64
    for (const feature of features) {
      if (feature.geometry.type !== 'MultiLineString' && feature.geometry.type !== 'LineString') continue
      const lines: number[][][] = feature.geometry.type === 'LineString' ? [feature.geometry.coordinates] : feature.geometry.coordinates
      const squared = Math.min(...lines.map(line => lineDistanceSquared(event.point, line, point => map.project(point))))
      if (squared <= distance) { distance = squared; closest = feature }
    }
    if (!closest?.properties?.id) { if (selected) reset(); return }
    reset()
    selected = true
    onSelected(true)
    for (const layer of [WIDTH_LAYER_ID, WIDTH_HIT_ID]) map.setFilter(layer, ['==', ['get', 'id'], closest.properties.id])
    const content = document.createElement('section')
    content.className = 'node-details'
    const title = document.createElement('h2')
    title.textContent = 'Road width'
    const dl = document.createElement('dl')
    for (const [label, value] of [['KML road ID', closest.properties.id], ['OBJECTID', closest.properties.OBJECTID], ['RR_WIDTH_P', closest.properties.RR_WIDTH_P], ['RR_width_B', closest.properties.RR_width_B]]) {
      const dt = document.createElement('dt'), dd = document.createElement('dd')
      dt.textContent = String(label); dd.textContent = value == null ? 'Unknown' : String(value)
      dl.append(dt, dd)
    }
    const note = document.createElement('p')
    note.className = 'node-note'
    note.textContent = `Shaded by ${field}. Width units are not specified in the KML. This record is not matched to an OSM graph edge.`
    content.append(title, dl, note)
    popup = new Popup({ className: 'node-popup width-popup', closeOnClick: false, offset: 12, maxWidth: '310px' }).setLngLat(event.lngLat).setDOMContent(content).addTo(map)
    popup.on('close', reset)
  }
  const key = (event: KeyboardEvent) => { if (event.key === 'Escape' && selected) reset() }
  map.on('click', click)
  map.getContainer().addEventListener('keydown', key)
  return {
    reset,
    setField(value: WidthField) { reset(); field = value; map.setPaintProperty(WIDTH_LAYER_ID, 'line-color', widthColor(field)); map.setPaintProperty(WIDTH_LAYER_ID, 'line-width', widthStroke(field)) },
    setVisible(value: boolean) {
      visible = value
      if (!value) reset()
      for (const layer of [WIDTH_LAYER_ID, WIDTH_HIT_ID]) if (map.getLayer(layer)) map.setLayoutProperty(layer, 'visibility', value ? 'visible' : 'none')
    },
    dispose() {
      window.clearTimeout(timeout)
      popup?.off('close', reset); popup?.remove()
      map.off('sourcedata', loaded); map.off('click', click)
      map.getContainer().removeEventListener('keydown', key)
    },
  }
}
