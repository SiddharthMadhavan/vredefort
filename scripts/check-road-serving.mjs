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
  const nodesModule = await fetch(`${origin}/src/components/map/nodes.ts`).then(r => r.text())
  const nodesImport = nodesModule.match(/from\s+["']([^"']+bengaluru-road-nodes[^"']+)["']/)?.[1]
  assert.ok(nodesImport, 'Node interaction must import the generated graph nodes')
  const nodesWrapper = await fetch(new URL(nodesImport, origin)).then(r => r.text())
  const nodesUrl = nodesWrapper.match(/export default\s+["']([^"']+)["']/)?.[1]
  assert.ok(nodesUrl, 'Vite must generate a graph node asset URL')
  const nodesResponse = await fetch(new URL(nodesUrl, origin))
  assert.equal(nodesResponse.status, 200)
  const nodes = await nodesResponse.json()
  assert.equal(nodes.type, 'FeatureCollection')
  const expectedNodes = JSON.parse(await fs.readFile('data/bengaluru-road-nodes.geojson', 'utf8'))
  assert.deepEqual(nodes, expectedNodes)
  assert.ok(nodes.features.every(node => node.properties.kind !== 'continuation'))
  assert.ok(nodes.features.every(node => node.geometry.type === 'Point' && Number.isInteger(node.properties.number) && Number.isInteger(node.properties.degree)))
  console.log(`Development node dataset loads with ${nodes.features.length} graph points and no continuations.`)
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
  const nodesFile = files.find(file => /^bengaluru-road-nodes-.*\.geojson$/.test(file))
  assert.ok(nodesFile, 'Production must contain the generated graph node asset')
  const nodesResponse = await fetch(`http://127.0.0.1:${address.port}/assets/${nodesFile}`)
  assert.equal(nodesResponse.status, 200)
  const nodes = await nodesResponse.json()
  const original = JSON.parse(await fs.readFile('data/bengaluru-road-nodes.geojson', 'utf8'))
  assert.deepEqual(nodes, original)
  console.log('Production node dataset is bundled and matches the stored road graph.')
} finally {
  await new Promise(resolve => built.httpServer.close(resolve))
}
