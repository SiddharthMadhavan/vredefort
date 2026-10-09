import { Marker, Popup, type Map } from 'maplibre-gl'
import stationsUrl from '../../../data/bengaluru-fire-stations.geojson?url'

type Station = { geometry: { type: 'Point'; coordinates: [number, number] }; properties: Record<string, string> }

export function addFireStationOverlay(map: Map, onReady: () => void, onError: () => void) {
  const abort = new AbortController()
  const markers: Marker[] = []
  let visible = true, disposed = false
  let popup: Popup | null = null
  const timeout = window.setTimeout(() => { abort.abort(); if (!disposed) onError() }, 20000)
  fetch(stationsUrl, { signal: abort.signal }).then(async response => {
    if (!response.ok) throw new Error('Fire station data could not load')
    const data = await response.json() as { type: string; features: Station[] }
    if (data.type !== 'FeatureCollection' || !Array.isArray(data.features)) throw new Error('Invalid station data')
    if (disposed) return
    for (const station of data.features) {
      if (station.geometry.type !== 'Point' || station.geometry.coordinates.length !== 2 || !station.geometry.coordinates.every(Number.isFinite)) throw new Error('Invalid station coordinates')
      const p = station.properties
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'fire-station-marker'
      button.textContent = 'F'
      button.title = p.FIRE_STAName
      button.setAttribute('aria-label', `Fire station details: ${p.FIRE_STAName}`)
      button.addEventListener('click', event => {
        event.stopPropagation()
        popup?.remove()
        const section = document.createElement('section')
        section.className = 'node-details'
        const title = document.createElement('h2')
        title.textContent = p.FIRE_STAName || 'Fire station'
        const list = document.createElement('dl')
        for (const [label, value] of [['Station ID', p.KGISFIRE_STAID], ['Ward ID', p.KGISWardID], ['KGIS code', p.KGISCode], ['Latitude', station.geometry.coordinates[1].toFixed(6)], ['Longitude', station.geometry.coordinates[0].toFixed(6)]]) {
          const dt = document.createElement('dt'), dd = document.createElement('dd')
          dt.textContent = label
          dd.textContent = value || 'Not provided'
          list.append(dt, dd)
        }
        const note = document.createElement('p')
        note.className = 'node-note'
        note.textContent = 'Position supplied directly by the fire-station KML. Survey date is not specified.'
        section.append(title, list, note)
        popup = new Popup({ className: 'node-popup hospital-popup', closeOnClick: false, maxWidth: '340px', offset: 12 }).setLngLat(station.geometry.coordinates).setDOMContent(section).addTo(map)
      })
      const marker = new Marker({ element: button }).setLngLat(station.geometry.coordinates)
      markers.push(marker)
      if (visible) marker.addTo(map)
    }
    window.clearTimeout(timeout)
    onReady()
  }).catch(() => { window.clearTimeout(timeout); if (!disposed) { markers.forEach(marker => marker.remove()); onError() } })
  return {
    setVisible(value: boolean) { visible = value; popup?.remove(); markers.forEach(marker => value ? marker.addTo(map) : marker.remove()) },
    dispose() { disposed = true; abort.abort(); window.clearTimeout(timeout); popup?.remove(); markers.forEach(marker => marker.remove()) },
  }
}
