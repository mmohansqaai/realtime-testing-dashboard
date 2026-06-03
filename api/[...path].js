/**
 * Same-origin /api proxy (60s) → Render API. Used when the Vercel project root is the repo root.
 */
const RENDER_API_BASE =
  process.env.RENDER_API_BASE_URL || 'https://realtime-testing-dashboard-api-ld7t.onrender.com'

module.exports = async (req, res) => {
  try {
    const pathParts = req.query.path
    const subpath = Array.isArray(pathParts) ? pathParts.join('/') : String(pathParts || '')
    const rawUrl = req.url || ''
    const qIndex = rawUrl.indexOf('?')
    const search = qIndex >= 0 ? rawUrl.slice(qIndex) : ''
    const targetUrl = `${RENDER_API_BASE}/api/${subpath}${search}`

    const forwardHeaders = {}
    if (req.headers.accept) forwardHeaders.Accept = req.headers.accept
    if (req.headers['content-type']) forwardHeaders['Content-Type'] = req.headers['content-type']
    if (req.headers['x-ingest-token']) forwardHeaders['X-Ingest-Token'] = req.headers['x-ingest-token']

    const init = { method: req.method, headers: forwardHeaders }
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      const chunks = []
      for await (const chunk of req) {
        chunks.push(chunk)
      }
      if (chunks.length) init.body = Buffer.concat(chunks)
    }

    const upstream = await fetch(targetUrl, init)
    res.statusCode = upstream.status

    const skip = new Set(['transfer-encoding', 'connection', 'content-encoding'])
    upstream.headers.forEach((value, key) => {
      if (skip.has(key.toLowerCase())) return
      res.setHeader(key, value)
    })

    const body = Buffer.from(await upstream.arrayBuffer())
    res.end(body)
  } catch (err) {
    res.statusCode = 502
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify({ detail: err instanceof Error ? err.message : String(err) }))
  }
}
