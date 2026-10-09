import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const source = fs.readFileSync('src/components/map/edges.ts', 'utf8')
let currentPopup
class Popup {
  constructor() { this.handlers = {}; currentPopup = this }
  setLngLat() { return this }
  setDOMContent(content) { this.content = content; return this }
  addTo() { return this }
  on(type, handler) { this.handlers[type] = handler; return this }
  off(type) { delete this.handlers[type]; return this }
  remove() { this.removed = true; this.handlers.close?.(); return this }
}
const exports = {}
const document = { createElement: tag => ({ tag, children: [], handlers: {}, setAttribute() {}, append(...children) { this.children.push(...children) }, addEventListener(type, handler) { this.handlers[type] = handler } }) }
vm.runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), {
  exports, document, Element: class {},
  require: name => name === 'maplibre-gl' ? { Popup } : { ROAD_LAYER_ID: 'roads', ROAD_HIT_LAYER_ID: 'hit' },
})
const filters = {}, visibility = {}, handlers = {}, containerHandlers = {}, selections = []
const feature = (id, y) => ({ properties: { id, source: 'node-a', target: 'node-b', length_m: 1234, names: ['Actual fixture road'], highways: ['primary'] }, geometry: { type: 'LineString', coordinates: [[0, y], [10, y]] } })
const map = {
  getLayer: () => true,
  setFilter: (id, value) => { filters[id] = value },
  setLayoutProperty: (id, property, value) => { visibility[id] = value },
  project: ([x, y]) => ({ x, y }),
  queryRenderedFeatures: () => [feature('far', 6), feature('near', 0)],
  on: (type, handler) => { handlers[type] = handler },
  off: type => { delete handlers[type] },
  getContainer: () => ({ addEventListener: (type, handler) => { containerHandlers[type] = handler }, removeEventListener: type => { delete containerHandlers[type] } }),
}
const controller = exports.addEdgeInteractions(map, edge => selections.push(edge))
const click = { point: { x: 5, y: 1 }, lngLat: [77.5946, 12.9716], originalEvent: { target: null }, defaultPrevented: false }
handlers.click(click)
assert.equal(selections.at(-1).id, 'near', 'The closest graph edge must win at dense crossings')
assert.equal(filters.roads[2], 'near')
assert.equal(filters.hit[2], 'near', 'Hidden roads must also be excluded from click targets')
assert.equal(currentPopup.content.children[1].textContent, 'Actual fixture road')
currentPopup.handlers.close()
assert.equal(filters.roads, null)
assert.equal(filters.hit, null)
assert.equal(selections.at(-1), null)
handlers.click(click)
controller.setVisible(false)
assert.equal(visibility.roads, 'none')
assert.equal(visibility.hit, 'none')
assert.equal(selections.at(-1), null)
const previous = selections.length
handlers.click(click)
assert.equal(selections.length, previous, 'Hidden overlays must not select roads')
controller.setVisible(true)
handlers.click({ ...click, defaultPrevented: true })
assert.equal(selections.length, previous, 'Node clicks must take priority over road clicks')
controller.dispose()
assert.equal(handlers.click, undefined)
assert.equal(containerHandlers.keydown, undefined)
console.log('Edge selection checks passed: nearest road, isolation, popup close/reset, overlay toggle, node priority and cleanup.')
