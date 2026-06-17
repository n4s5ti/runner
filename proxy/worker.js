const REPO = "n4sti/runner";
const WORKFLOW_FILE = "research-relay.yml";
const GITHUB_API = "https://api.github.com";

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders() },
  });
}

function error(msg, status = 500) {
  return json({ error: msg }, status);
}

async function github(path, token, init = {}) {
  const url = `${GITHUB_API}${path}`;
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "vane-relay-worker",
    ...(init.headers || {}),
  };
  return fetch(url, { ...init, headers });
}

async function pollLatestDispatchRun(token) {
  for (let i = 0; i < 5; i++) {
    const res = await github(
      `/repos/${REPO}/actions/runs?event=workflow_dispatch&per_page=1`,
      token
    );
    if (!res.ok) throw new Error(`GitHub runs API: ${res.status}`);
    const data = await res.json();
    if (data.workflow_runs && data.workflow_runs.length > 0) {
      const run = data.workflow_runs[0];
      return { run_id: run.id, run_url: run.html_url, status: run.status };
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  return null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    if (method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    if (!env.GITHUB_PAT) {
      return error("GITHUB_PAT not configured", 500);
    }
    const token = env.GITHUB_PAT;

    try {
      // POST /api/dispatch — trigger workflow and return run info
      if (method === "POST" && path === "/api/dispatch") {
        let body;
        try {
          body = await request.json();
        } catch {
          return error("Invalid JSON body", 400);
        }
        const { query, mode, provider, model } = body;
        const provider_key = body.provider_key || '';
        if (!query) return error("Missing required 'query' field", 400);

        const inputs = { query: String(query) };
        if (mode) inputs.mode = String(mode);
        if (provider) inputs.provider = String(provider);
        if (model) inputs.model = String(model);
        inputs.provider_key = String(provider_key);

        const dispatchRes = await github(
          `/repos/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
          token,
          {
            method: "POST",
            body: JSON.stringify({ ref: "main", inputs }),
          }
        );

        if (!dispatchRes.ok) {
          const errText = await dispatchRes.text();
          return error(`Dispatch failed (${dispatchRes.status}): ${errText}`, 502);
        }

        // workflow_dispatch returns 204; poll for the run_id
        await new Promise((r) => setTimeout(r, 2000));
        const runInfo = await pollLatestDispatchRun(token);
        if (!runInfo) {
          return json(
            { message: "Dispatched, but run not yet visible. Poll /api/run later." },
            202
          );
        }

        return json(runInfo, 201);
      }

      // GET /api/run/:id — poll run status
      const runMatch = path.match(/^\/api\/run\/(\d+)$/);
      if (method === "GET" && runMatch) {
        const runId = runMatch[1];
        const res = await github(`/repos/${REPO}/actions/runs/${runId}`, token);
        if (!res.ok) return error(`Run fetch failed (${res.status})`, 502);
        const run = await res.json();
        return json({
          run_id: run.id,
          run_url: run.html_url,
          status: run.status,
          conclusion: run.conclusion,
          created_at: run.created_at,
          updated_at: run.updated_at,
        });
      }

      // GET /api/run/:id/artifacts — list artifact download URLs
      const artMatch = path.match(/^\/api\/run\/(\d+)\/artifacts$/);
      if (method === "GET" && artMatch) {
        const runId = artMatch[1];
        const res = await github(
          `/repos/${REPO}/actions/runs/${runId}/artifacts`,
          token
        );
        if (!res.ok) return error(`Artifacts fetch failed (${res.status})`, 502);
        const data = await res.json();
        return json({
          run_id: Number(runId),
          artifacts: (data.artifacts || []).map((a) => ({
            id: a.id,
            name: a.name,
            size_in_bytes: a.size_in_bytes,
            archive_download_url: a.archive_download_url,
            expired: a.expired,
          })),
        });
      }

      return error("Not found", 404);
    } catch (e) {
      return error(e.message || "Internal error", 500);
    }
  },
};
