#!/usr/bin/env node
/**
 * Nous Runtime JavaScript SDK v0.1.0-alpha
 *
 * Usage:
 *   const { NousClient } = require('@nous-runtime/sdk');
 *   const client = new NousClient({ host: 'localhost', port: 8770, token: 'demo' });
 *   await client.health();
 *   const result = await client.run('model.reason', { prompt: 'Hello' });
 */

class NousClient {
  constructor({ baseUrl = '', host = 'localhost', port = 8770, token = '' } = {}) {
    this.token = token;
    this.base = (baseUrl || `http://${host}:${port}`).replace(/\/$/, '');
  }

  async _fetch(method, path, body = null) {
    const url = `${this.base}${path}`;
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (this.token) opts.headers.Authorization = `Bearer ${this.token}`;
    if (body) opts.body = JSON.stringify(body);

    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
    return resp.json();
  }

  // Runtime
  async health()           { return this._fetch('GET', '/api/v1/health'); }
  async status()           { return this._fetch('GET', '/api/v1/status'); }
  async version()          { return this._fetch('GET', '/api/v1/version'); }

  // Capabilities
  async listCapabilities() { return this._fetch('GET', '/api/v1/capabilities'); }
  async run(capabilityId, params = {}) {
    return this._fetch('POST', '/api/v1/capabilities/run', { capability_id: capabilityId, params });
  }

  // Providers
  async chat(message, params = {}) { return this.run("model.reason", { prompt: message, ...params }); }
  async workflow(workflowId, inputs = {}, version = "1.0.0") { return this._fetch("POST", "/api/workflow/run", { workflow_id: workflowId, version, inputs }); }
  async listRuns(limit = 20) { return this._fetch("GET", `/api/runtime/runs?limit=${Math.max(1, Math.min(limit, 200))}`); }
  async runEvents(runId, afterSequence = 0, limit = 200) {
    const run = encodeURIComponent(runId);
    const after = Math.max(0, afterSequence);
    const bounded = Math.max(1, Math.min(limit, 1000));
    return this._fetch('GET', `/api/runtime/runs/${run}/events?after_sequence=${after}&limit=${bounded}`);
  }
  events(runId, onEvent, { intervalMs = 1000, afterSequence = 0 } = {}) {
    let active = true;
    let cursor = Math.max(0, afterSequence);
    const poll = async () => {
      if (!active) return;
      try {
        const response = await this.runEvents(runId, cursor);
        for (const event of response.data?.events || []) onEvent(event);
        cursor = response.data?.next_after_sequence ?? cursor;
      } catch {
        // Preserve the cursor and retry after transient disconnects.
      } finally {
        if (active) setTimeout(poll, Math.max(250, intervalMs));
      }
    };
    void poll();
    return { close: () => { active = false; }, cursor: () => cursor };
  }
  async listProviders()    { return this._fetch('GET', '/api/v1/providers'); }
  async providerHealth()   { return this._fetch('GET', '/api/v1/providers/health'); }

  // Packs
  async listPacks()        { return this._fetch('GET', '/api/v1/packs'); }
  async installPack(path)  { return this._fetch('POST', '/api/v1/packs/install', { path }); }
  async removePack(name)   { return this._fetch('DELETE', `/api/v1/packs/${name}`); }

  // Jobs
  async listJobs(status = '') {
    const qs = status ? `?status=${status}` : '';
    return this._fetch('GET', `/api/v1/jobs${qs}`);
  }
  async getJob(jobId)      { return this._fetch('GET', `/api/v1/jobs/${jobId}`); }

  // Traces
  async listTraces(limit = 20) { return this._fetch('GET', `/api/v1/traces?limit=${limit}`); }
}

// Export
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { NousClient };
}
