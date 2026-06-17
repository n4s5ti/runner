// Browser client for Vane edge proxy → GitHub Actions relay.
// Point PROXY at your deployed Cloudflare Worker URL.

const PROXY = 'https://vane-relay.YOUR_SUBDOMAIN.workers.dev';

export function setProxyUrl(url) {
  // Allow override at runtime (e.g. from localStorage or URL param)
  if (url) window.__VANE_PROXY_URL__ = url;
}

function proxyUrl() {
  return window.__VANE_PROXY_URL__ || localStorage.getItem('vane_proxy_url') || PROXY;
}

export async function dispatchResearch({ query, mode = 'balanced', provider = 'ollama', model }) {
  const res = await fetch(`${proxyUrl()}/api/dispatch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, mode, provider, ...(model ? { model } : {}) }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Dispatch failed (${res.status}): ${text}`);
  }
  return res.json(); // { run_id, run_url, status }
}

export async function pollRun(runId) {
  const res = await fetch(`${proxyUrl()}/api/run/${runId}`);
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`);
  return res.json(); // { status, conclusion }
}

export async function waitForRun(runId, intervalMs = 3000, signal) {
  while (true) {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const { status, conclusion } = await pollRun(runId);
    if (status === 'completed') return conclusion;
    if (status !== 'queued' && status !== 'in_progress') {
      throw new Error(`Run ended unexpectedly: status=${status}, conclusion=${conclusion}`);
    }
    await new Promise(r => setTimeout(r, intervalMs));
  }
}

export async function getArtifacts(runId) {
  const res = await fetch(`${proxyUrl()}/api/run/${runId}/artifacts`);
  if (!res.ok) throw new Error(`Artifacts fetch failed: ${res.status}`);
  return res.json(); // [{ name, download_url }]
}

export async function downloadResult(downloadUrl) {
  const res = await fetch(downloadUrl);
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const { unzipSync } = window.fflate || {};
  if (!unzipSync) throw new Error('fflate not loaded — add <script src="https://unpkg.com/fflate@0.8.2/umd/index.min.js">');
  const files = unzipSync(new Uint8Array(await blob.arrayBuffer()));
  const resultFile = files['result.json'];
  if (!resultFile) throw new Error('result.json not found in artifact');
  return JSON.parse(new TextDecoder().decode(resultFile));
}
