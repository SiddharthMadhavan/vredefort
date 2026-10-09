import { mkdir, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'

// Published OSM extract. Download data only; never run code from the source repository.
const repository = 'saifimd1234/emission-inventory-dashboard'
const path = 'public/data/bengaluru-roads.json'
const commits = await fetch(`https://api.github.com/repos/${repository}/commits?path=${path}&per_page=1`).then(async response => {
  if (!response.ok) throw new Error(`GitHub returned HTTP ${response.status}`)
  return response.json()
})
const commit = commits[0]?.sha
if (!commit) throw new Error('Could not identify dataset revision')
const url = `https://raw.githubusercontent.com/${repository}/${commit}/${path}`
const response = await fetch(url)
if (!response.ok) throw new Error(`Dataset download returned HTTP ${response.status}`)
const text = await response.text()
const data = JSON.parse(text)
if (!data.ways?.length || !Array.isArray(data.classes)) throw new Error('Unexpected dataset format')
const features = data.ways.map(([code, flat, name, ref], index) => {
  const classIndex = code % 10
  if (!data.classes[classIndex] || flat.length < 4 || flat.length % 2) throw new Error('Invalid road geometry or class')
  const coordinates = []
  for (let i = 0; i < flat.length; i += 2) {
    const lat = flat[i] / 1e5, lon = flat[i + 1] / 1e5
    if (!Number.isFinite(lon) || !Number.isFinite(lat) || lon < 77 || lon > 79 || lat < 12 || lat > 14) throw new Error('Road outside expected Bengaluru region')
    coordinates.push([lon, lat])
  }
  const isLink = code % 100 >= 10
  return {
    type: 'Feature', id: index,
    properties: { highway: `${data.classes[classIndex]}${isLink ? '_link' : ''}`, ...(name ? { name } : {}), ...(ref ? { ref } : {}) },
    geometry: { type: 'LineString', coordinates },
  }
})
const output = new URL('../public/data/', import.meta.url)
await mkdir(output, { recursive: true })
await writeFile(new URL('bengaluru-roads.geojson', output), JSON.stringify({ type: 'FeatureCollection', features }))
await writeFile(new URL('bengaluru-roads.metadata.json', output), JSON.stringify({
  source: data.source, sourceUrl: url, sourceCommit: commit, sourceSha256: createHash('sha256').update(text).digest('hex'),
  sourceExtractedAt: data.fetched, retrievedAt: new Date().toISOString(),
  license: 'ODbL-1.0', licenseUrl: 'https://www.openstreetmap.org/copyright',
  queryBounds: { south: data.bbox[0], west: data.bbox[1], north: data.bbox[2], east: data.bbox[3] },
  classes: data.classes, featureCount: features.length,
  processing: 'Decoded integer lat/lon at 1e5 precision to WGS84 GeoJSON lon/lat. Source geometry simplified to 6 metres. Local feature IDs are not OSM IDs.',
  coverage: 'Major roads and their links in a roughly 60×60 km Bengaluru bounding box. Whole ways can extend beyond that box. Not every local street or an official municipal inventory.',
}, null, 2))
console.log(`Imported ${features.length} OSM roads, snapshot ${data.fetched}.`)
