import { createServer } from 'node:http'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile, mkdir, stat, access } from 'node:fs/promises'
import { dirname, join, delimiter, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'
import { distanceMetres } from '../scripts/road-graph.mjs'

const root = fileURLToPath(new URL('../', import.meta.url))
const run = promisify(execFile)

export function positionAlongEdge(coordinates, distance, edgeLength) {
  const lengths = coordinates.slice(1).map((point, i) => distanceMetres(coordinates[i], point))
  const total = lengths.reduce((sum, length) => sum + length, 0)
  if (!(total > 0 && edgeLength > 0) || distance < 0 || distance > edgeLength + .01) throw new Error('Invalid backend vehicle distance')
  let remaining = Math.min(1, distance / edgeLength) * total
  for (let i = 0; i < lengths.length; i++) {
    if (remaining <= lengths[i] || i === lengths.length - 1) {
      const a = coordinates[i], b = coordinates[i + 1], fraction = lengths[i] ? remaining / lengths[i] : 0
      const rad = Math.PI / 180, delta = (b[0] - a[0]) * rad
      const bearing = Math.atan2(Math.sin(delta) * Math.cos(b[1] * rad), Math.cos(a[1] * rad) * Math.sin(b[1] * rad) - Math.sin(a[1] * rad) * Math.cos(b[1] * rad) * Math.cos(delta)) / rad
      return { coordinates: [a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction], bearing: (bearing + 360) % 360 }
    }
    remaining -= lengths[i]
  }
  throw new Error('Road has no usable geometry')
}

export function parseVehicles(stdout, edges) {
  const pattern = /Vehicle (\d+):\s+Start Node Index\s*:\s*(\d+)\s*\(([^)]+)\)\s+End Node Index\s*:\s*(\d+)\s*\(([^)]+)\)\s+Dist from Node\s*:\s*([\d.eE+-]+) m \/ ([\d.eE+-]+) m/g
  const vehicles = [...stdout.matchAll(pattern)].map((match, index) => {
    const edge = edges[index]
    if (!edge || match[3] !== edge.properties.source || match[5] !== edge.properties.target) throw new Error('Backend output does not match the loaded graph')
    const distance = Number(match[6]), length = edge.properties.length_m
    if (!Number.isFinite(distance) || Math.abs(Number(match[7]) - length) > Math.max(.02, length * .00001)) throw new Error('Invalid backend edge length')
    return { id: `vehicle_${match[1]}`, edgeId: edge.properties.id, source: match[3], target: match[5], startNodeIndex: Number(match[2]), endNodeIndex: Number(match[4]), distanceFromNodeM: distance, edgeLengthM: length, ...positionAlongEdge(edge.geometry.coordinates, distance, length) }
  })
  if (vehicles.length !== Math.min(5, edges.length)) throw new Error('Backend output did not contain all initialized vehicles')
  return vehicles
}

export async function initializeVehicles() {
  const compilerCandidates = [process.env.CXX, 'C:/msys64/ucrt64/bin/g++.exe', 'C:/msys64/mingw64/bin/g++.exe'].filter(Boolean)
  let compiler = 'g++'
  for (const candidate of compilerCandidates) { try { await access(candidate); compiler = candidate; break } catch { /* Try next installed toolchain. */ } }
  const binary = join(root, '.tmp', process.platform === 'win32' ? 'vehicle-backend.exe' : 'vehicle-backend')
  const source = join(root, 'backend/src/load_edges.cpp')
  const header = join(root, 'backend/src/json.hpp')
  await mkdir(dirname(binary), { recursive: true })
  const binaryTime = await stat(binary).then(file => file.mtimeMs).catch(() => 0)
  const sourcesTime = Math.max((await stat(source)).mtimeMs, (await stat(header)).mtimeMs)
  const env = { ...process.env, PATH: dirname(compiler) + delimiter + process.env.PATH }
  if (binaryTime < sourcesTime) {
    try { await run(compiler, ['-std=c++17', '-O2', source, '-o', binary], { cwd: root, env, timeout: 120000, maxBuffer: 2e6 }) }
    catch { throw new Error('C++ backend build failed. Set CXX to an installed g++ executable.') }
  }
  const { stdout } = await run(binary, [], { cwd: root, env, timeout: 15000, maxBuffer: 2e6 })
  const graph = JSON.parse(await readFile(join(root, 'data/bengaluru-kml-road-edges.geojson'), 'utf8'))
  return { snapshotId: randomUUID(), mode: 'initialization', generatedAt: new Date().toISOString(), vehicles: parseVehicles(stdout, graph.features) }
}

export function createVehicleServer() {
  let initialization
  return createServer(async (request, response) => {
    response.setHeader('Content-Type', 'application/json')
    response.setHeader('Cache-Control', 'no-store')
    if (request.method !== 'GET' || request.url?.split('?')[0] !== '/api/vehicles') { response.writeHead(404); response.end(JSON.stringify({ error: 'Not found' })); return }
    try {
      initialization ||= initializeVehicles().catch(error => { initialization = undefined; throw error })
      response.end(JSON.stringify(await initialization))
    } catch (error) { response.writeHead(503); response.end(JSON.stringify({ error: error.message || 'Vehicle backend unavailable' })) }
  })
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  createVehicleServer().listen(Number(process.env.PORT || 8787), '127.0.0.1', () => console.log('Vehicle backend listening on http://127.0.0.1:' + (process.env.PORT || 8787)))
}
