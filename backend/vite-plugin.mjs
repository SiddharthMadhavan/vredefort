import { createVehicleServer } from './vehicle-api.mjs'

export function vehicleBackendPlugin(enabled, compiler) {
  const attach = async host => {
    if (!enabled) return
    if (compiler) process.env.CXX = compiler
    const api = createVehicleServer()
    await new Promise((resolve, reject) => { api.once('error', reject); api.listen(8787, '127.0.0.1', resolve) })
    host.httpServer?.once('close', () => api.close())
    host.config.logger.info('Vehicle backend adapter: http://127.0.0.1:8787/api/vehicles')
  }
  return { name: 'citycollapse-vehicle-backend', configureServer: attach, configurePreviewServer: attach }
}
