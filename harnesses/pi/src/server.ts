// Compat contract HTTP surface: GET /ping, POST /invocations on :8080.
import "./otel.js";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { HARNESS, run } from "./agent.js";

const send = (res: ServerResponse, status: number, body: unknown) => {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};

const readBody = async (req: IncomingMessage) => {
  const chunks: Buffer[] = [];
  for await (const c of req) chunks.push(c as Buffer);
  return Buffer.concat(chunks).toString("utf8");
};

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

    const result = await run(body.prompt, sessionId, user);
    send(res, 200, { ...result, harness: HARNESS, model: process.env.MODEL ?? "sovereign", session_id: sessionId, user });
  } catch (err) {
    console.error(err);
    send(res, 502, { error: String(err) });
  }
}).listen(Number(process.env.PORT ?? 8080), process.env.HOST ?? "0.0.0.0", () => console.log(`agent-pi listening on ${process.env.PORT ?? 8080}`));
