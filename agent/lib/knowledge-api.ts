// Identity is configured by the operator, never chosen by a model tool argument.
export async function knowledgeApi(path: string, payload: unknown) {
  const base = process.env.KNOWLEDGE_API_URL ?? 'http://127.0.0.1:8102';
  const url = new URL(base);
  if (!['127.0.0.1', 'localhost'].includes(url.hostname) || url.protocol !== 'http:') {
    throw new Error('This demo only supports the local knowledge API');
  }
  const token = process.env.KNOWLEDGE_DEMO_TOKEN ?? 'demo-acme-support';
  const response = await fetch(new URL(path, url), {
    method: 'POST', headers: {'Content-Type':'application/json', Authorization:`Bearer ${token}`},
    body: JSON.stringify(payload), signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`Knowledge API rejected request (${response.status})`);
  return await response.json();
}
