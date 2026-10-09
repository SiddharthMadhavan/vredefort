import type { Map } from 'maplibre-gl'
import edgesUrl from '../../../data/bengaluru-road-edges.geojson?url'

export const ROAD_SOURCE_ID = 'bengaluru-roads'
export const ROAD_LAYER_ID = 'bengaluru-roads-lines'
export const ROAD_HIT_LAYER_ID = 'bengaluru-roads-hit-area'
export function addRoadOverlay(map: Map) {
  if (!map.getSource(ROAD_SOURCE_ID)) map.addSource(ROAD_SOURCE_ID, {
    type: 'geojson',
    data: edgesUrl,
    attribution: 'Roads: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a> (ODbL)',
  })
  if (map.getLayer(ROAD_LAYER_ID)) return
  // Append above every basemap layer so opaque base layers cannot hide it.
  map.addLayer({
    id: ROAD_LAYER_ID, type: 'line', source: ROAD_SOURCE_ID,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: {
      'line-color': '#c4a7ff',
      'line-opacity': 1,
      'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1, 11, 2.5, 14, 4, 17, 7],
    },
  })
  map.addLayer({
    id: ROAD_HIT_LAYER_ID, type: 'line', source: ROAD_SOURCE_ID,
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-width': 14, 'line-color': '#c4a7ff', 'line-opacity': 0.001 },
  })
}
