import { useEffect, useRef, useState } from 'react'
import { Map, AttributionControl } from 'maplibre-gl'
import { BENGALURU, INITIAL_ZOOM, configurationError, mapRequest, mapStyle } from '../../config/map'

type Status = 'loading' | 'ready' | 'error'
export default function CityMap() {
  const container = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [attempt, setAttempt] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  useEffect(() => {
    if (!container.current) return
    setStatus('loading')
    setErrorMessage('')
    if (configurationError) {
      setErrorMessage(configurationError)
      setStatus('error')
      return
    }
    let instance: Map | null = null
    let timeout: ReturnType<typeof setTimeout> | undefined
    let observer: ResizeObserver | undefined
    try {
      instance = new Map({ container: container.current, style: mapStyle, transformRequest: mapRequest, center: BENGALURU, zoom: INITIAL_ZOOM, attributionControl: false, dragRotate: false, pitchWithRotate: false })
      instance.addControl(new AttributionControl({ compact: true }), 'bottom-right')
      const ready = () => { if (instance?.areTilesLoaded() && instance.isStyleLoaded()) { clearTimeout(timeout); setStatus('ready') } }
      instance.on('idle', ready)
      instance.on('error', ({ error }) => {
        clearTimeout(timeout)
        const code = 'status' in error ? error.status : undefined
        setErrorMessage(code === 401 || code === 403 ? 'The map provider rejected the key. Check its provider and allowed website domains.' : code === 404 ? 'The map resource was not found. Check the configured style or tile URL.' : 'The map could not load. Check your connection and basemap configuration.')
        setStatus('error')
      })
      timeout = setTimeout(() => { setErrorMessage('Map loading timed out. Check your connection and provider configuration.'); setStatus('error') }, 20000)
      observer = new ResizeObserver(() => instance?.resize())
      observer.observe(container.current)
    } catch { setErrorMessage('The map could not start. Check that WebGL is enabled in your browser.'); setStatus('error') }
    return () => { clearTimeout(timeout); observer?.disconnect(); instance?.remove() }
  }, [attempt])
  return <>
    <div ref={container} className="map-canvas" role="region" aria-label="Interactive Bengaluru map" />
    {status !== 'ready' && <div className="map-status" role={status === 'error' ? 'alert' : 'status'}>{status === 'loading' ? 'Loading map…' : <>{errorMessage} <button onClick={() => setAttempt(attempt + 1)}>Retry</button></>}</div>}
  </>
}
