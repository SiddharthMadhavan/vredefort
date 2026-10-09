import type { StyleSpecification } from 'maplibre-gl'
export const BENGALURU: [number, number] = [77.5946, 12.9716]
export const INITIAL_ZOOM = 11
export const KEY_FREE_MAP_STYLE = 'https://tiles.openfreemap.org/styles/dark'
export const cartoKey = import.meta.env.VITE_CARTO_API_KEY?.trim() || ''
const styleUrl = import.meta.env.VITE_MAP_STYLE_URL?.trim() || ''
const maptilerKey = import.meta.env.VITE_MAPTILER_API_KEY?.trim() || ''
const tileUrl = import.meta.env.VITE_MAP_TILE_URL?.trim() || ''
export const configurationError = styleUrl && !/^https?:\/\//i.test(styleUrl)
  ? 'VITE_MAP_STYLE_URL must be a full https:// style URL. Put your key in VITE_CARTO_API_KEY or VITE_MAPTILER_API_KEY instead.'
  : ''
export const mapStyle: string | StyleSpecification = styleUrl || (maptilerKey ? `https://api.maptiler.com/maps/streets-v4-dark/style.json?key=${encodeURIComponent(maptilerKey)}` : !tileUrl && !cartoKey ? KEY_FREE_MAP_STYLE : {
  version: 8,
  sources: {
    basemap: {
      type: 'raster',
      tiles: [tileUrl || 'https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: import.meta.env.VITE_MAP_ATTRIBUTION || '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors · © <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a>',
    },
  },
  layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
})

// CARTO requires the key on style, tile, sprite and glyph requests.
export function mapRequest(url: string) {
  try {
    const parsed = new URL(url)
    if (cartoKey && (parsed.hostname === 'basemaps.cartocdn.com' || parsed.hostname.endsWith('.basemaps.cartocdn.com')) && !parsed.searchParams.has('key')) {
      return { url: `${url}${url.includes('?') ? '&' : '?'}key=${encodeURIComponent(cartoKey)}` }
    }
  } catch { /* MapLibre may supply relative resource URLs. */ }
  return { url }
}
