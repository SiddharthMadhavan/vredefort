import { useEffect, useRef, useState } from 'react'
import { Map, AttributionControl, type GeoJSONSource } from 'maplibre-gl'
import osmEdgesUrl from '../../../data/bengaluru-road-edges.geojson?url'
import osmNodesUrl from '../../../data/bengaluru-road-nodes.geojson?url'
import kmlEdgesUrl from '../../../data/bengaluru-kml-road-edges.geojson?url'
import kmlNodesUrl from '../../../data/bengaluru-kml-road-nodes.geojson?url'
import { BENGALURU, INITIAL_ZOOM, KEY_FREE_MAP_STYLE, configurationError, mapRequest, mapStyle } from '../../config/map'
import { addRoadOverlay, ROAD_LAYER_ID, ROAD_SOURCE_ID } from './roads'
import { addNodeInteractions, NODE_SOURCE_ID } from './nodes'
import { addEdgeInteractions } from './edges'
import { addWidthOverlay, WIDTH_SOURCE_ID, widthStatistics, type WidthField } from './widths'
import { addHospitalOverlay } from './hospitals'
import hospitalMetadata from '../../../data/bengaluru-hospitals.metadata.json'
import { addFireStationOverlay } from './fireStations'
import fireMetadata from '../../../data/bengaluru-fire-stations.metadata.json'
import { addVehicleOverlay } from './vehicles'

type Status = 'loading' | 'ready' | 'error'
export default function CityMap() {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<Map | null>(null)
  const nodeInteractions = useRef<ReturnType<typeof addNodeInteractions> | null>(null)
  const edgeInteractions = useRef<ReturnType<typeof addEdgeInteractions> | null>(null)
  const widthOverlay = useRef<ReturnType<typeof addWidthOverlay> | null>(null)
  const hospitalOverlay = useRef<ReturnType<typeof addHospitalOverlay> | null>(null)
  const fireOverlay = useRef<ReturnType<typeof addFireStationOverlay> | null>(null)
  const vehicleOverlay = useRef<ReturnType<typeof addVehicleOverlay> | null>(null)
  const [vehicleCount, setVehicleCount] = useState<number | null>(null)
  const [vehicleError, setVehicleError] = useState('')
  const [vehicleAttempt, setVehicleAttempt] = useState(0)
  const [fireReady, setFireReady] = useState(false)
  const [fireError, setFireError] = useState(false)
  const [fireVisible, setFireVisible] = useState(true)
  const [hospitalsReady, setHospitalsReady] = useState(false)
  const [hospitalsError, setHospitalsError] = useState(false)
  const [hospitalsVisible, setHospitalsVisible] = useState(true)
  const [status, setStatus] = useState<Status>('loading')
  const [attempt, setAttempt] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [roadsError, setRoadsError] = useState(false)
  const [keyFree, setKeyFree] = useState(false)
  const [roadsReady, setRoadsReady] = useState(false)
  const [roadsVisible, setRoadsVisible] = useState(true)
  const [nodesError, setNodesError] = useState(false)
  const [edgeSelected, setEdgeSelected] = useState(false)
  const [widthMode, setWidthMode] = useState(true)
  const [graphDataset, setGraphDataset] = useState<'kml' | 'osm'>('kml')
  const [widthField, setWidthField] = useState<WidthField>('RR_WIDTH_P')
  const [widthReady, setWidthReady] = useState(false)
  const [widthError, setWidthError] = useState(false)
  const [widthSelected, setWidthSelected] = useState(false)
  useEffect(() => {
    if (!container.current) return
    setStatus('loading')
    setErrorMessage('')
    setRoadsError(false)
    setRoadsReady(false)
    setRoadsVisible(true)
    setNodesError(false)
    setEdgeSelected(false)
    setWidthMode(true); setWidthField('RR_WIDTH_P'); setWidthReady(false); setWidthError(false); setWidthSelected(false)
    setGraphDataset('kml')
    setHospitalsReady(false); setHospitalsError(false); setHospitalsVisible(true)
    setFireReady(false); setFireError(false); setFireVisible(true)
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
      instance.addControl(new AttributionControl({ compact: true, customAttribution: 'Hospital locations: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a> (ODbL)' }), 'bottom-right')
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
        hospitalOverlay.current = addHospitalOverlay(instance!, () => setHospitalsReady(true), () => setHospitalsError(true))
        fireOverlay.current = addFireStationOverlay(instance!, () => setFireReady(true), () => setFireError(true))
        try {
          if (instance) {
            roadsTimeout = setTimeout(() => setRoadsError(true), 20000)
            addRoadOverlay(instance)
            try { nodeInteractions.current = addNodeInteractions(instance, () => setNodesError(false), () => setNodesError(true), kmlNodesUrl) }
            catch { setNodesError(true) }
            edgeInteractions.current = addEdgeInteractions(instance, edge => {
              setEdgeSelected(!!edge)
              nodeInteractions.current?.setEdgeEndpoints(edge ? [edge.source, edge.target] : null)
            })
            edgeInteractions.current.setVisible(false)
            try { widthOverlay.current = addWidthOverlay(instance, () => { setWidthReady(true); setWidthError(false) }, () => setWidthError(true), setWidthSelected) }
            catch { setWidthError(true) }
          }
        } catch { clearTimeout(roadsTimeout); setRoadsError(true) }
      })
      instance.on('error', (event) => {
        if ('sourceId' in event && event.sourceId === WIDTH_SOURCE_ID) { setWidthError(true); return }
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
    return () => { clearTimeout(timeout); clearTimeout(roadsTimeout); observer?.disconnect(); fireOverlay.current?.dispose(); fireOverlay.current = null; hospitalOverlay.current?.dispose(); hospitalOverlay.current = null; widthOverlay.current?.dispose(); widthOverlay.current = null; edgeInteractions.current?.dispose(); edgeInteractions.current = null; nodeInteractions.current?.dispose(); nodeInteractions.current = null; instance?.remove(); mapRef.current = null }
  }, [attempt, keyFree])
  useEffect(() => {
    const map = mapRef.current
    if (status !== 'ready' || !map) return
    setVehicleCount(null); setVehicleError('')
    const overlay = addVehicleOverlay(map, setVehicleCount, setVehicleError)
    vehicleOverlay.current = overlay
    return () => { overlay.dispose(); if (vehicleOverlay.current === overlay) vehicleOverlay.current = null }
  }, [status, vehicleAttempt, attempt, keyFree])
  const toggleRoads = () => {
    const map = mapRef.current
    if (!map?.getLayer(ROAD_LAYER_ID)) return
    edgeInteractions.current?.setVisible(!roadsVisible && !widthMode)
    nodeInteractions.current?.setVisible(!roadsVisible)
    widthOverlay.current?.setVisible(!roadsVisible && widthMode)
    setRoadsVisible(!roadsVisible)
  }
  const changeMode = (mode: string) => {
    const value = mode === 'width'
    edgeInteractions.current?.reset()
    nodeInteractions.current?.setEdgeEndpoints(null)
    if (!value) {
      const kml = mode === 'kml'
      const source = mapRef.current?.getSource(ROAD_SOURCE_ID) as GeoJSONSource | undefined
      source?.setData(kml ? kmlEdgesUrl : osmEdgesUrl)
      nodeInteractions.current?.setDataset(kml ? kmlNodesUrl : osmNodesUrl)
      setGraphDataset(kml ? 'kml' : 'osm')
    } else {
      nodeInteractions.current?.setDataset(kmlNodesUrl)
    }
    edgeInteractions.current?.setVisible(!value && roadsVisible)
    nodeInteractions.current?.setVisible(roadsVisible)
    widthOverlay.current?.setVisible(value && roadsVisible)
    setWidthMode(value)
  }
  return <>
    <div ref={container} className="map-canvas" role="region" aria-label="Interactive Bengaluru map" />
    <button className="roads-toggle" disabled={widthMode ? !widthReady : !roadsReady} aria-pressed={roadsVisible} onClick={toggleRoads} title="Show or hide the road dataset"><span className={roadsVisible ? 'roads-swatch' : 'roads-swatch roads-swatch-off'} aria-hidden="true"/>{(widthMode ? widthReady : roadsReady) ? `Roads ${roadsVisible ? 'on' : 'off'}` : 'Loading roads…'}</button>
    {edgeSelected && <button className="clear-edge-selection" onClick={() => edgeInteractions.current?.reset()}>Show all roads</button>}
    {widthSelected && <button className="clear-edge-selection" onClick={() => widthOverlay.current?.reset()}>Show all roads</button>}
    <div className="width-controls">
      <div className="vehicle-status" role="status">{vehicleError ? <><span>Backend: {vehicleError}</span><button onClick={() => setVehicleAttempt(value => value + 1)}>Retry connection</button></> : vehicleCount === null ? 'Connecting to vehicle backend...' : <><span>{vehicleCount} cars / backend initialized</span><button onClick={() => vehicleOverlay.current?.focus()}>Focus cars</button></>}</div>
      <button className="hospital-toggle" disabled={!hospitalsReady} aria-pressed={hospitalsVisible} onClick={() => { hospitalOverlay.current?.setVisible(!hospitalsVisible); setHospitalsVisible(!hospitalsVisible) }}>{hospitalsError ? 'Hospitals could not load' : !hospitalsReady ? 'Loading hospitals...' : `+ Hospitals ${hospitalsVisible ? 'on' : 'off'} (${hospitalMetadata.mappedCount})`}</button>
      <p className="hospital-summary">{hospitalMetadata.providedCoordinateCount} supplied coordinates + {hospitalMetadata.inferredCount} inferred; {hospitalMetadata.unresolvedCount} need review</p>
      <button className="hospital-toggle fire-toggle" disabled={!fireReady} aria-pressed={fireVisible} onClick={() => { fireOverlay.current?.setVisible(!fireVisible); setFireVisible(!fireVisible) }}>{fireError ? 'Fire stations could not load' : !fireReady ? 'Loading fire stations...' : `F Fire stations ${fireVisible ? 'on' : 'off'} (${fireMetadata.featureCount})`}</button>
      <label>Road view<select value={widthMode ? 'width' : graphDataset} onChange={event => changeMode(event.target.value)}><option value="width">KML width shading</option><option value="kml">KML road graph</option><option value="osm">OSM road graph</option></select></label>
      {widthMode && <><label>Width field<select value={widthField} disabled={!widthReady} onChange={event => { const field = event.target.value as WidthField; widthOverlay.current?.setField(field); setWidthField(field) }}><option value="RR_WIDTH_P">RR_WIDTH_P</option><option value="RR_width_B">RR_width_B</option></select></label><div className="width-gradient"/><div className="width-range"><span>Narrow · {widthStatistics[widthField].min}</span><span>Wide · {widthStatistics[widthField].max}</span></div><p>Width units not specified in KML</p></>}
    </div>
    {status !== 'ready' && <div className="map-status" role={status === 'error' ? 'alert' : 'status'}>{status === 'loading' ? 'Loading map…' : <>{errorMessage} <button onClick={() => setAttempt(attempt + 1)}>Retry</button>{!keyFree && <button onClick={() => setKeyFree(true)}>Use key-free basemap</button>}</>}</div>}
    {roadsError && !widthMode && <div className="roads-error" role="alert">Road overlay could not load. <button onClick={() => setAttempt(attempt + 1)}>Retry</button></div>}
    {nodesError && <div className="nodes-error" role="alert">Node details could not load. <button onClick={() => setAttempt(attempt + 1)}>Retry</button></div>}
    {widthError && widthMode && <div className="nodes-error" role="alert">Road widths could not load. <button onClick={() => setAttempt(attempt + 1)}>Retry</button></div>}
  </>
}
