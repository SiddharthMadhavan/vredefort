import { LngLatBounds, Marker, Popup, type Map } from 'maplibre-gl'

export type Vehicle = { id: string; edgeId: string; source: string; target: string; distanceFromNodeM: number; edgeLengthM: number; coordinates: [number, number]; bearing: number }

export function readVehicleSnapshot(data: unknown): Vehicle[] {
  if (!data || typeof data !== 'object' || !('mode' in data) || data.mode !== 'initialization' || !('vehicles' in data) || !Array.isArray(data.vehicles)) throw new Error('Invalid vehicle backend response')
  return data.vehicles.map((vehicle: unknown) => {
    if (!vehicle || typeof vehicle !== 'object') throw new Error('Invalid vehicle')
    const v = vehicle as Vehicle
    if (![v.id, v.edgeId, v.source, v.target].every(value => typeof value === 'string' && value.length > 0) || !Array.isArray(v.coordinates) || v.coordinates.length !== 2 || !v.coordinates.every(Number.isFinite) || Math.abs(v.coordinates[0]) > 180 || Math.abs(v.coordinates[1]) > 90 || ![v.bearing, v.distanceFromNodeM, v.edgeLengthM].every(Number.isFinite) || v.distanceFromNodeM < 0 || v.distanceFromNodeM > v.edgeLengthM + .01 || v.edgeLengthM <= 0) throw new Error('Invalid vehicle position from backend')
    return v
  })
}

export function addVehicleOverlay(map: Map, onReady: (count: number) => void, onError: (message: string) => void) {
  let disposed = false
  let popup: Popup | null = null
  const markers: Marker[] = []
  const bounds = new LngLatBounds()
  const abort = new AbortController()
  const timeout = window.setTimeout(() => abort.abort(), 150000)
  const focus = () => {
    if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: { top: 70, right: 60, bottom: 70, left: Math.min(320, map.getContainer().clientWidth / 3) }, maxZoom: 13, duration: 600 })
  }
  fetch('/api/vehicles', { signal: abort.signal }).then(async response => {
    const data: unknown = await response.json()
    if (!response.ok) throw new Error(data && typeof data === 'object' && 'error' in data && typeof data.error === 'string' ? data.error : 'Vehicle backend unavailable')
    const vehicles = readVehicleSnapshot(data)
    if (disposed) return
    for (const vehicle of vehicles) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'vehicle-marker'
      button.setAttribute('aria-label', `Show ${vehicle.id.replace('_', ' ')} details`)
      button.title = vehicle.id
      button.innerHTML = '<svg viewBox="0 0 20 32" width="20" height="32" aria-hidden="true" shape-rendering="crispEdges"><path fill="#07120d" d="M0 6h4v6H0zm16 0h4v6h-4zM0 21h4v6H0zm16 0h4v6h-4z"/><path fill="#b0e1a1" d="M6 0h8v2h3v28h-3v2H6v-2H3V2h3z"/><path fill="#234c35" d="M5 6h10v6H5zm0 16h10v5H5z"/><path fill="#dcf2ce" d="M4 2h3v2H4zm9 0h3v2h-3z"/></svg>'
      button.addEventListener('click', event => {
        event.stopPropagation()
        popup?.remove()
        const section = document.createElement('section')
        section.className = 'node-details'
        const title = document.createElement('h2')
        title.textContent = vehicle.id.replace('_', ' ')
        const list = document.createElement('dl')
        for (const [label, value] of [['Edge', vehicle.edgeId], ['Start node', vehicle.source], ['End node', vehicle.target], ['Distance along road', `${vehicle.distanceFromNodeM.toFixed(1)} m`], ['Edge length', `${vehicle.edgeLengthM.toFixed(1)} m`]]) {
          const dt = document.createElement('dt'), dd = document.createElement('dd')
          dt.textContent = label; dd.textContent = value; list.append(dt, dd)
        }
        const note = document.createElement('p')
        note.className = 'node-note'
        note.textContent = 'Initialized by the C++ backend. Static position along the actual road geometry; no movement updates are produced yet.'
        section.append(title, list, note)
        popup = new Popup({ className: 'node-popup', offset: 18, closeOnClick: false, maxWidth: '340px' }).setLngLat(vehicle.coordinates).setDOMContent(section).addTo(map)
      })
      markers.push(new Marker({ element: button, rotation: vehicle.bearing, rotationAlignment: 'map' }).setLngLat(vehicle.coordinates).addTo(map))
      bounds.extend(vehicle.coordinates)
    }
    onReady(vehicles.length)
    focus()
  }).catch(error => { if (!disposed) onError(error instanceof Error ? error.message : 'Vehicle backend unavailable') }).finally(() => window.clearTimeout(timeout))
  return { focus, dispose() { disposed = true; abort.abort(); window.clearTimeout(timeout); popup?.remove(); markers.forEach(marker => marker.remove()) } }
}
