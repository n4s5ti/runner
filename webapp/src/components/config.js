// Browser-side config — replaces Vane's server-side config.json + clientRegistry
// Persists to localStorage, read/written through useChat context.

const DEFAULTS = {
  mode: 'balanced',
  provider: 'ollama',
  model: 'llama3.2:3b',
  sources: ['web'],
  showWeatherWidget: true,
  showNewsWidget: true,
  autoMediaSearch: true,
};

function loadConfig() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem('vane_cfg') || '{}') };
  } catch {
    return { ...DEFAULTS };
  }
}

export function getCfg(key, def) {
  try {
    const c = JSON.parse(localStorage.getItem('vane_cfg') || '{}');
    return key in c ? c[key] : def;
  } catch {
    return def;
  }
}

export function setCfg(key, val) {
  try {
    const c = JSON.parse(localStorage.getItem('vane_cfg') || '{}');
    c[key] = val;
    localStorage.setItem('vane_cfg', JSON.stringify(c));
  } catch { /* quota exceeded */ }
}

export function getShowWeatherWidget() { return getCfg('showWeatherWidget', true); }
export function getShowNewsWidget() { return getCfg('showNewsWidget', true); }
export function getAutoMediaSearch() { return getCfg('autoMediaSearch', true); }

export { loadConfig };
