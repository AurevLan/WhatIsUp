// Common User-Agent strings for monitors that need to bypass UA filters
// (Cloudflare, sites that block python-httpx, etc.).
// Keep the list short and stable — these are convenience defaults, not an exhaustive catalog.

export const UA_PRESETS = [
  {
    id: 'chrome_windows',
    labelKey: 'monitors.customHeaders.presets.chromeWindows',
    value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  },
  {
    id: 'firefox_windows',
    labelKey: 'monitors.customHeaders.presets.firefoxWindows',
    value: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
  },
  {
    id: 'safari_mac',
    labelKey: 'monitors.customHeaders.presets.safariMac',
    value: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15',
  },
  {
    id: 'chrome_android',
    labelKey: 'monitors.customHeaders.presets.chromeAndroid',
    value: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36',
  },
  {
    id: 'curl',
    labelKey: 'monitors.customHeaders.presets.curl',
    value: 'curl/8.10.1',
  },
]

// Apply a preset: returns a new headers list with User-Agent set to the preset value.
// If a User-Agent row exists (case-insensitive), updates it; otherwise prepends a new one.
export function applyUaPreset(headersList, presetValue) {
  const idx = headersList.findIndex(h => h.key.trim().toLowerCase() === 'user-agent')
  if (idx >= 0) {
    const next = [...headersList]
    next[idx] = { ...next[idx], key: 'User-Agent', value: presetValue }
    return next
  }
  return [{ key: 'User-Agent', value: presetValue }, ...headersList]
}
