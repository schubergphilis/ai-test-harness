// Compat contract HTTP surface: GET /ping, POST /invocations on :8080.
// Every run is bounded: AGENT_MAX_TURNS model calls (the harness) and RUN_TIMEOUT_S wall clock (here). A run is
// aborted when the client disconnects. A failed or cut-off run still answers 200, with `stop_reason`, `error` and
// the tool calls executed so far, so callers can score partial behaviour. With SCENARIO_EXEC=box each run gets its own
// box container (scenario.ts withBox), and the response a `sandbox` report.
import "./otel.js";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { HARNESS, run } from "./agent.js";
import { RUN_TIMEOUT_S, partial, recordCalls, withBox } from "./scenario.js";

const send = (res: ServerResponse, status: number, body: unknown) => {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};

const readBody = async (req: IncomingMessage) => {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  return Buffer.concat(chunks).toString("utf8");
};

async function bounded(prompt: string, sessionId: string | null, user: string | null, res: ServerResponse) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort("timeout"), RUN_TIMEOUT_S * 1000);
  const onClose = () => res.writableEnded || ctrl.abort("cancelled");
  res.on("close", onClose);
  const cut = () =>
    ctrl.signal.reason === "timeout"
      ? partial("timeout", `run exceeded RUN_TIMEOUT_S=${RUN_TIMEOUT_S}`)
      : partial("cancelled", "client disconnected");
  try {
    const result = await run(prompt, sessionId, user, ctrl.signal);
    return ctrl.signal.aborted ? cut() : { error: null, ...result };
  } catch (err) {
    if (ctrl.signal.aborted) return cut();
    console.error(err);
    return partial("error", String(err));
  } finally {
    clearTimeout(timer);
    res.off("close", onClose);
  }
}

const header = (req: IncomingMessage, name: string) => {
  const v = req.headers[name];
  return (Array.isArray(v) ? v[0] : v) ?? null;
};

createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/ping") return send(res, 200, { status: "Healthy" });
    if (req.method !== "POST" || req.url !== "/invocations") return send(res, 404, { error: "not found" });

    let body: { prompt?: unknown; session_id?: unknown };
    try {
      body = JSON.parse((await readBody(req)) || "{}");
    } catch {
      return send(res, 400, { error: "invalid JSON" });
    }
    if (typeof body.prompt !== "string" || !body.prompt.trim()) return send(res, 400, { error: "prompt is required" });
    const sessionId = typeof body.session_id === "string" ? body.session_id : null;
    const user = header(req, "x-agent-user") ?? header(req, "x-amzn-bedrock-agentcore-runtime-custom-agent-user");

    const prompt = body.prompt;
    const result = await recordCalls(() => withBox(() => bounded(prompt, sessionId, user, res)));
    send(res, 200, { ...result, harness: HARNESS, model: process.env.MODEL ?? "sovereign", session_id: sessionId, user });
  } catch (err) {
    console.error(err);
    send(res, 502, { error: String(err) });
  }
}).listen(Number(process.env.PORT ?? 8080), process.env.HOST ?? "0.0.0.0", () => console.log(`agent-pi listening on ${process.env.PORT ?? 8080}`));
