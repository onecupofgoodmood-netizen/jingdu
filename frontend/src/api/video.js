import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

// Detect 775069 URLs and use browser-side relay
function is775069Url(url) {
  try {
    const host = new URL(url).hostname.toLowerCase()
    return host === '775069.xyz' || host === 'www.775069.xyz' || host === '775070.xyz' || host === 'www.775070.xyz'
  } catch { return false }
}

// Extract video_id, sid, nid from 775069 URL
function parse775069Url(url) {
  const match = url.match(/\/vodplay\/(\d+)-(\d+)-(\d+)/)
  if (!match) return null
  return { videoId: match[1], sid: match[2], nid: match[3] }
}

export async function parseVideo(url) {
  // 775069 专用路径: 浏览器 fetch playdata API，再发给后端
  if (is775069Url(url)) {
    const ids = parse775069Url(url)
    if (!ids) {
      return { success: false, error: '无法识别 775069 播放页地址格式' }
    }

    // Try sids starting from the URL's sid
    let playdataJson = null
    for (let trySid = parseInt(ids.sid); trySid < parseInt(ids.sid) + 5; trySid++) {
      try {
        const resp = await fetch(
          `http://775069.xyz/playdata/${ids.videoId}?sid=${trySid}`,
          { mode: 'cors', headers: { 'Accept': 'application/json' } }
        )
        if (resp.ok) {
          const text = await resp.text()
          if (text && text.includes('"code"') && text.includes('"url"')) {
            playdataJson = text
            break
          }
        }
      } catch (e) {
        // CORS or network error, try next sid
        continue
      }
    }

    if (!playdataJson) {
      return {
        success: false,
        error: '浏览器端无法获取播放数据（站点可能有跨域限制或 WAF 防护）。请确保您能正常访问 775069.xyz 后重试。'
      }
    }

    // Send browser-fetched data to backend for parsing
    try {
      const { data } = await api.post('/parse/775069-data', {
        url,
        video_id: ids.videoId,
        sid: ids.sid,
        nid: ids.nid,
        playdata_json: playdataJson,
      })
      return data
    } catch (e) {
      return { success: false, error: '解析失败: ' + (e.response?.data?.detail || e.message) }
    }
  }

  // Normal path: backend handles everything
  const { data } = await api.post('/parse', { url })
  return data
}

export async function getDirectUrl(url, formatId) {
  const { data } = await api.post('/direct-url', { url, format_id: formatId })
  return data
}

export function getDownloadUrl() {
  return '/api/download'
}

export async function downloadViaServer(url, formatId) {
  const response = await api.post(
    '/download',
    { url, format_id: formatId },
    { responseType: 'blob', timeout: 600000 }
  )
  return response
}
