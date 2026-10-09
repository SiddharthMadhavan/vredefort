import { Marker, Popup, type Map } from 'maplibre-gl'
import hospitalsUrl from '../../../data/bengaluru-hospitals.geojson?url'

type Hospital = { type: 'Feature'; geometry: { type: 'Point'; coordinates: [number, number] }; properties: Record<string, unknown> }

export function addHospitalOverlay(map: Map, onReady: () => void, onError: () => void) {
  const abort = new AbortController()
  const markers: Marker[] = []
  let visible = true, disposed = false
  let popup: Popup | null = null
  const timeout = window.setTimeout(() => { abort.abort(); if (!disposed) onError() }, 20000)
  fetch(hospitalsUrl, { signal: abort.signal }).then(async response => {
    if (!response.ok) throw new Error('Hospital data could not load')
    const data = await response.json() as { type: string; features: Hospital[] }
    if (data.type !== 'FeatureCollection' || !Array.isArray(data.features)) throw new Error('Invalid hospital data')
    if (disposed) return
    for (const hospital of data.features) {
      if (hospital.geometry.type !== 'Point' || hospital.geometry.coordinates.length !== 2 || !hospital.geometry.coordinates.every(Number.isFinite)) throw new Error('Invalid hospital location')
      const p = hospital.properties
      const dot = document.createElement('button')
      dot.type = 'button'
      dot.className = 'hospital-marker'
      dot.textContent = '+'
      dot.title = String(p.Name)
      dot.setAttribute('aria-label', `Hospital details: ${p.Name}`)
      dot.addEventListener('click', event => {
        event.stopPropagation()
        popup?.remove()
        const section = document.createElement('section')
        section.className = 'node-details'
        const title = document.createElement('h2')
        title.textContent = String(p.Name)
        const list = document.createElement('dl')
        for (const [label, key] of [['Type', 'Type'], ['Address', 'Address'], ['Beds', 'Beds'], ['Contact', 'Contact'], ['OSM match', 'matched_name']]) {
          const dt = document.createElement('dt'), dd = document.createElement('dd')
          dt.textContent = label
          dd.textContent = p[key] ? String(p[key]) : 'Not provided'
          list.append(dt, dd)
        }
        const note = document.createElement('p')
        note.className = 'node-note'
        note.textContent = p.match_status === 'provided_coordinates'
          ? 'Coordinates and address supplied by the user. Not independently verified.'
          : 'Inferred facility match from OpenStreetMap. Location needs verification; the CSV supplies no coordinates. Details reflect the original dataset.'
        section.append(title, list, note)
        if (typeof p.search_url === 'string') {
          const url = new URL(p.search_url)
          if (url.protocol === 'https:' && url.hostname === 'www.google.com' && url.pathname === '/search') {
            const link = document.createElement('a')
            link.href = url.href
            link.target = '_blank'
            link.rel = 'noopener noreferrer'
            link.className = 'hospital-reference'
            link.textContent = 'Hospital search reference ↗'
            section.append(link)
          }
        }
        popup = new Popup({ className: 'node-popup hospital-popup', closeOnClick: false, maxWidth: '340px', offset: 15 }).setLngLat(hospital.geometry.coordinates).setDOMContent(section).addTo(map)
      })
      const marker = new Marker({ element: dot }).setLngLat(hospital.geometry.coordinates)
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
