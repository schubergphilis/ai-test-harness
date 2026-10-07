// __HARNESS__ harness: framework-free tool-calling loop over an OpenAI-compatible endpoint.
// Scaffold baseline: replace run() with the framework under test, keep the return shape.
import OpenAI from "openai";
import { trace, type Span } from "@opentelemetry/api";
import { IMPLS, SYSTEM_PROMPT, TOOLS } from "./tools.js";

export const HARNESS = "__HARNESS__";
const MAX_TURNS = 10;
const client = new OpenAI({ baseURL: process.env.OPENAI_BASE_URL, apiKey: process.env.OPENAI_API_KEY });
const tracer = trace.getTracer(HARNESS);

const traced = <T>(name: string, attrs: Record<string, string | null>, fn: () => Promise<T> | T): Promise<T> =>
  tracer.startActiveSpan(name, async (span: Span) => {
    for (const [k, v] of Object.entries(attrs)) if (v != null) span.setAttribute(k, v);
    try {
      return await fn();
    } finally {
      span.end();
    }
  });

export async function run(prompt: string, sessionId: string | null, user: string | null) {
  const model = process.env.MODEL ?? "mock";
  const ids = { "session.id": sessionId, "user.id": user };
  const messages: OpenAI.Chat.ChatCompletionMessageParam[] = [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: prompt },
  ];
  const toolCalls: { name: string; args: Record<string, unknown> }[] = [];
  let inTok = 0, outTok = 0, output = "";

  await traced(`invoke_agent ${HARNESS}`, ids, async () => {
    for (let turn = 0; turn < MAX_TURNS; turn++) {
      const resp = await traced(`chat ${model}`, { ...ids, "gen_ai.request.model": model }, () =>
        client.chat.completions.create({ model, messages, tools: TOOLS }),
      );
      inTok += resp.usage?.prompt_tokens ?? 0;
      outTok += resp.usage?.completion_tokens ?? 0;
      const msg = resp.choices[0].message;
      if (!msg.tool_calls?.length) {
        output = msg.content ?? "";
        return;
      }
      messages.push(msg);
      for (const tc of msg.tool_calls) {
        if (tc.type !== "function") continue;
        const args = JSON.parse(tc.function.arguments || "{}");
        toolCalls.push({ name: tc.function.name, args });
        const result = await traced(`execute_tool ${tc.function.name}`, { ...ids, "gen_ai.tool.name": tc.function.name },
          () => IMPLS[tc.function.name]?.(args) ?? `error: unknown tool ${tc.function.name}`);
        messages.push({ role: "tool", tool_call_id: tc.id, content: String(result) });
      }
    }
  });
  return { output: output.trim(), tool_calls: toolCalls, usage: { input_tokens: inTok, output_tokens: outTok } };
}
