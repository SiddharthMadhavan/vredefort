import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { createServer, preview } from 'vite'

const server = await createServer({ server: { host: '127.0.0.1', port: 0 }, logLevel: 'silent' })
try {
  await server.listen()
  const address = server.httpServer.address()
  const response = await fetch(`http://127.0.0.1:${address.port}/data/bengaluru-roads.geojson`)
  assert.equal(response.status, 200)
  const data = await response.json()
  assert.equal(data.type, 'FeatureCollection')
  assert.equal(data.features.length, 19229)
  console.log('Vite serves the road overlay URL correctly: HTTP 200, 19,229 features.')
  const origin = `http://127.0.0.1:${address.port}`
  const main = await fetch(`${origin}/src/main.tsx`).then(r => r.text())
  const workerModule = main.match(/from\s+["']([^"']+\?worker&url[^"']*)["']/)?.[1]
  assert.ok(workerModule, 'The app must import the worker through Vite')
  const wrapper = await fetch(new URL(workerModule, origin)).then(r => r.text())
  const workerUrl = wrapper.match(/export default\s+["']([^"']+)["']/)?.[1]
  assert.ok(workerUrl, 'Vite must generate a worker URL')
  const worker = await fetch(new URL(workerUrl, origin))
  assert.equal(worker.status, 200)
  assert.match(worker.headers.get('content-type'), /javascript/)
  console.log('Development MapLibre worker URL resolves to JavaScript (HTTP 200).')
} finally {
  await server.close()
}

const built = await preview({ preview: { host: '127.0.0.1', port: 0 }, logLevel: 'silent' })
try {
  const address = built.httpServer.address()
  const files = await fs.readdir('dist/assets')
  const workerFile = files.find(file => /^maplibre-gl-worker-.*\.js$/.test(file))
  assert.ok(workerFile, 'Production must contain the bundled MapLibre worker')
  const worker = await fetch(`http://127.0.0.1:${address.port}/assets/${workerFile}`)
  assert.equal(worker.status, 200)
  assert.match(worker.headers.get('content-type'), /javascript/)
  const source = await worker.text()
  assert.ok(source.length > 100000)
  assert.ok(!source.includes('maplibre-gl-shared.mjs'), 'Bundled worker must not reference a missing sibling module')
  console.log('Production MapLibre worker is bundled and served correctly (HTTP 200).')
} finally {
  await new Promise(resolve => built.httpServer.close(resolve))
}
