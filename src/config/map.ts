import type { StyleSpecification } from 'maplibre-gl'
export const BENGALURU: [number, number] = [77.5946, 12.9716]
export const INITIAL_ZOOM = 11
export const mapStyle: string | StyleSpecification = import.meta.env.VITE_MAP_STYLE_URL || {
  version: 8,
  sources: {
    basemap: {
      type: 'raster',
      tiles: [import.meta.env.VITE_MAP_TILE_URL || 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: import.meta.env.VITE_MAP_ATTRIBUTION || '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors · © <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>',
    },
  },
  layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
}
