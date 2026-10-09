# CityCollapse

A full-screen interactive Bengaluru map. Drag to pan; scroll or pinch to zoom. Keyboard arrows and +/− work when the map canvas is focused. Only the map and provider attribution remain; loading and retry messages appear when needed.

## Run

```sh
npm install
npm run dev
```

`npm run build` checks TypeScript and creates `dist/`. `npm run preview` serves the production build.

## Basemap configuration

The default is the OSM-derived CARTO Dark Matter raster basemap, centered on Bengaluru at zoom 11. Internet access and WebGL are required. Copy `.env.example` to `.env.local` to configure `VITE_MAP_STYLE_URL` (a MapLibre style JSON URL) or `VITE_MAP_TILE_URL` (a raster tile URL template). The style URL takes precedence. Set `VITE_MAP_ATTRIBUTION` to match your raster provider; custom style files should include source attribution. Restart Vite after environment changes. Use only browser-safe provider tokens and check the provider’s terms before production deployment.
