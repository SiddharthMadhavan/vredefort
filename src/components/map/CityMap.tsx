import { useEffect, useRef, useState } from 'react'
import { Map, AttributionControl } from 'maplibre-gl'
import { BENGALURU, INITIAL_ZOOM, mapStyle } from '../../config/map'

type Status = 'loading' | 'ready' | 'error'
export default function CityMap() {
  const container = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!container.current) return
    setStatus('loading')
    let instance: Map | null = null
    let timeout: ReturnType<typeof setTimeout> | undefined
    let observer: ResizeObserver | undefined
    try {
      instance = new Map({ container: container.current, style: mapStyle, center: BENGALURU, zoom: INITIAL_ZOOM, attributionControl: false, dragRotate: false, pitchWithRotate: false })
      instance.addControl(new AttributionControl({ compact: true }), 'bottom-right')
      const ready = () => { if (instance?.areTilesLoaded() && instance.isStyleLoaded()) { clearTimeout(timeout); setStatus('ready') } }
      instance.on('idle', ready)
      instance.on('error', () => { clearTimeout(timeout); setStatus('error') })
      timeout = setTimeout(() => setStatus('error'), 20000)
      observer = new ResizeObserver(() => instance?.resize())
      observer.observe(container.current)
    } catch { setStatus('error') }
    return () => { clearTimeout(timeout); observer?.disconnect(); instance?.remove() }
  }, [attempt])
  return <>
    <div ref={container} className="map-canvas" role="region" aria-label="Interactive Bengaluru map" />
    {status !== 'ready' && <div className="map-status" role={status === 'error' ? 'alert' : 'status'}>{status === 'loading' ? 'Loading map…' : <>Unable to load the map. <button onClick={() => setAttempt(attempt + 1)}>Retry</button></>}</div>}
  </>
}
