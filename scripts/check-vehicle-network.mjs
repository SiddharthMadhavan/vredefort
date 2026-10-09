import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createServer } from 'vite'
import { positionAlongEdge, parseVehicles } from '../backend/vehicle-api.mjs'

const curve = [[77.5, 12.9], [77.51, 12.9], [77.51, 12.91]]
assert.deepEqual(positionAlongEdge(curve, 0, 100).coordinates, curve[0])
assert.deepEqual(positionAlongEdge(curve, 100, 100).coordinates, curve.at(-1))
const interior = positionAlongEdge(curve, 75, 100).coordinates
assert.equal(interior[0], 77.51, 'Position must follow the curve, not the straight endpoint chord')
assert.ok(interior[1] > 12.9 && interior[1] < 12.91)
assert.throws(() => positionAlongEdge(curve, -1, 100))
assert.throws(() => parseVehicles('malformed backend output', [{}]))

const original = await readFile('backend/src/load_edges.cpp', 'utf8')
const vite = await createServer({ server: { host: '127.0.0.1', port: 0 }, logLevel: 'silent' })
try {
  await vite.listen()
  const origin = `http://127.0.0.1:${vite.httpServer.address().port}`
  const response = await fetch(`${origin}/api/vehicles`)
  const snapshot = await response.json()
  assert.equal(response.status, 200, JSON.stringify(snapshot))
  assert.equal(snapshot.mode, 'initialization')
  assert.equal(snapshot.vehicles.length, 5)
  const roads = JSON.parse(await readFile('data/bengaluru-kml-road-edges.geojson', 'utf8'))
  snapshot.vehicles.forEach((vehicle, index) => {
    const edge = roads.features[index]
    assert.equal(vehicle.edgeId, edge.properties.id)
    assert.equal(vehicle.source, edge.properties.source)
    assert.equal(vehicle.target, edge.properties.target)
    assert.deepEqual(vehicle.coordinates, positionAlongEdge(edge.geometry.coordinates, vehicle.distanceFromNodeM, edge.properties.length_m).coordinates)
    assert.ok(vehicle.distanceFromNodeM >= 0 && vehicle.distanceFromNodeM <= vehicle.edgeLengthM + .01)
  })
  const second = await fetch(`${origin}/api/vehicles`).then(response => response.json())
  assert.deepEqual(second, snapshot, 'Fetching must not rerandomize vehicles')
  assert.equal(await readFile('backend/src/load_edges.cpp', 'utf8'), original, 'Existing C++ code must remain unchanged')
  console.log('Actual C++ backend compiled and executed; five vehicles loaded through the frontend HTTP proxy. Road interpolation and stable snapshot checks passed.')
} finally { await vite.close() }
