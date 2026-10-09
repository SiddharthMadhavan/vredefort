import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import App from './App'
import 'maplibre-gl/dist/maplibre-gl.css'
import './styles/index.css'

// MapLibre 6 needs an explicit worker URL under Vite. Raster basemaps can
// render without it, but GeoJSON/vector sources cannot be processed.
setWorkerUrl(workerUrl)

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><BrowserRouter><App /></BrowserRouter></React.StrictMode>,
)
