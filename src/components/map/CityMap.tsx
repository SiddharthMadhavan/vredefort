import { useEffect, useRef, useState } from 'react'
import { Map, AttributionControl } from 'maplibre-gl'
import { BENGALURU, INITIAL_ZOOM, KEY_FREE_MAP_STYLE, configurationError, mapRequest, mapStyle } from '../../config/map'
import { addRoadOverlay, ROAD_LAYER_ID, ROAD_SOURCE_ID } from './roads'
import { addNodeInteractions, NODE_SOURCE_ID } from './nodes'
import { addEdgeInteractions } from './edges'

type Status = 'loading' | 'ready' | 'error'
export default function CityMap() {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<Map | null>(null)
  const nodeInteractions = useRef<ReturnType<typeof addNodeInteractions> | null>(null)
  const edgeInteractions = useRef<ReturnType<typeof addEdgeInteractions> | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [attempt, setAttempt] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [roadsError, setRoadsError] = useState(false)
  const [keyFree, setKeyFree] = useState(false)
  const [roadsReady, setRoadsReady] = useState(false)
  const [roadsVisible, setRoadsVisible] = useState(true)
  const [nodesError, setNodesError] = useState(false)
  const [edgeSelected, setEdgeSelected] = useState(false)
  useEffect(() => {
    if (!container.current) return
    setStatus('loading')
    setErrorMessage('')
    setRoadsError(false)
    setRoadsReady(false)
    setRoadsVisible(true)
    setNodesError(false)
    setEdgeSelected(false)
    if (configurationError && !keyFree) {
      setErrorMessage(configurationError)
      setStatus('error')
      return
    }
    let instance: Map | null = null
    let timeout: ReturnType<typeof setTimeout> | undefined
    let roadsTimeout: ReturnType<typeof setTimeout> | undefined
    let observer: ResizeObserver | undefined
    try {
      instance = new Map({ container: container.current, style: keyFree ? KEY_FREE_MAP_STYLE : mapStyle, transformRequest: mapRequest, center: BENGALURU, zoom: INITIAL_ZOOM, attributionControl: false, dragRotate: false, pitchWithRotate: false })
      mapRef.current = instance
      instance.addControl(new AttributionControl({ compact: true }), 'bottom-right')
      instance.on('sourcedata', (event) => {
        if (event.sourceId === ROAD_SOURCE_ID && event.isSourceLoaded) {
          clearTimeout(roadsTimeout)
          setRoadsReady(true)
          setRoadsError(false)
        }
      })
      // Finish basemap loading before requesting the local road source. The
      // overlay must not keep the entire map behind a loading message.
      instance.once('load', () => {
        clearTimeout(timeout)
        setStatus('ready')
        try {
          if (instance) {
            roadsTimeout = setTimeout(() => setRoadsError(true), 20000)
            addRoadOverlay(instance)
            try { nodeInteractions.current = addNodeInteractions(instance, () => setNodesError(false), () => setNodesError(true)) }
            catch { setNodesError(true) }
            edgeInteractions.current = addEdgeInteractions(instance, edge => {
              setEdgeSelected(!!edge)
              nodeInteractions.current?.setEdgeEndpoints(edge ? [edge.source, edge.target] : null)
            })
          }
        } catch { clearTimeout(roadsTimeout); setRoadsError(true) }
      })
      instance.on('error', (event) => {
        if ('sourceId' in event && event.sourceId === NODE_SOURCE_ID) { setNodesError(true); return }
        if ('sourceId' in event && event.sourceId === ROAD_SOURCE_ID) { clearTimeout(roadsTimeout); setRoadsError(true); return }
        const { error } = event
        clearTimeout(timeout)
        const code = 'status' in error ? error.status : undefined
        setErrorMessage(code === 401 || code === 403 ? 'The map provider rejected the key. Check its provider and allowed website domains.' : code === 404 ? 'The map resource was not found. Check the configured style or tile URL.' : 'The map could not load. Check your connection and basemap configuration.')
        setStatus('error')
      })
      timeout = setTimeout(() => { setErrorMessage('Map loading timed out. Check your connection and provider configuration.'); setStatus('error') }, 20000)
      observer = new ResizeObserver(() => instance?.resize())
      observer.observe(container.current)
    } catch { setErrorMessage('The map could not start. Check that WebGL is enabled in your browser.'); setStatus('error') }
    return () => { clearTimeout(timeout); clearTimeout(roadsTimeout); observer?.disconnect(); edgeInteractions.current?.dispose(); edgeInteractions.current = null; nodeInteractions.current?.dispose(); nodeInteractions.current = null; instance?.remove(); mapRef.current = null }
  }, [attempt, keyFree])
  const toggleRoads = () => {
    const map = mapRef.current
    if (!map?.getLayer(ROAD_LAYER_ID)) return
    map.setLayoutProperty(ROAD_LAYER_ID, 'visibility', roadsVisible ? 'none' : 'visible')
    edgeInteractions.current?.setVisible(!roadsVisible)
    nodeInteractions.current?.setVisible(!roadsVisible)
    setRoadsVisible(!roadsVisible)
  }
  return <>
    <div ref={container} className="map-canvas" role="region" aria-label="Interactive Bengaluru map" />
    {!roadsError && <button className="roads-toggle" disabled={!roadsReady} aria-pressed={roadsVisible} onClick={toggleRoads} title="Show or hide the real OpenStreetMap major-road dataset"><span className={roadsVisible ? 'roads-swatch' : 'roads-swatch roads-swatch-off'} aria-hidden="true"/>{roadsReady ? `Roads ${roadsVisible ? 'on' : 'off'}` : 'Loading roads…'}</button>}
    {edgeSelected && <button className="clear-edge-selection" onClick={() => edgeInteractions.current?.reset()}>Show all roads</button>}
    {status !== 'ready' && <div className="map-status" role={status === 'error' ? 'alert' : 'status'}>{status === 'loading' ? 'Loading map…' : <>{errorMessage} <button onClick={() => setAttempt(attempt + 1)}>Retry</button>{!keyFree && <button onClick={() => setKeyFree(true)}>Use key-free basemap</button>}</>}</div>}
    {roadsError && <div className="roads-error" role="alert">Road overlay could not load. <button onClick={() => setAttempt(attempt + 1)}>Retry</button></div>}
    {nodesError && <div className="nodes-error" role="alert">Node details could not load. <button onClick={() => setAttempt(attempt + 1)}>Retry</button></div>}
  </>
}
