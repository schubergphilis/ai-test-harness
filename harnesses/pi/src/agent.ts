// pi harness: canary agent (pi-agent-core + pi-ai) over an OpenAI-compatible endpoint.
import { Agent } from "@mariozechner/pi-agent-core";
import type { AssistantMessage, Model } from "@mariozechner/pi-ai";
import { trace, SpanStatusCode, type Span } from "@opentelemetry/api";
import { MAX_TURNS } from "./scenario.js";
import { SYSTEM_PROMPT, TOOLS } from "./tools.js";

export const HARNESS = "pi";
const tracer = trace.getTracer("agent-pi");

function model(): Model<"openai-completions"> {
  const id = process.env.MODEL ?? "sovereign";
  return {
    id,
    name: id,
    api: "openai-completions",
    provider: "litellm",
    baseUrl: process.env.OPENAI_BASE_URL ?? "http://litellm:4000/v1",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 128000,
    maxTokens: 4096,
    // litellm/generic proxies: don't rely on URL auto-detection
    compat: { supportsStore: false, supportsDeveloperRole: false, maxTokensField: "max_tokens" },
  };
}

export async function run(prompt: string, sessionId: string | null, user: string | null, signal: AbortSignal) {
  return tracer.startActiveSpan("invoke_agent pi", async (root) => {
    if (sessionId) root.setAttribute("session.id", sessionId);
    if (user) root.setAttribute("user.id", user);
    root.setAttribute("input.value", prompt);
    try {
      const agent = new Agent({
        initialState: { systemPrompt: SYSTEM_PROMPT, model: model(), tools: TOOLS },
        getApiKey: () => process.env.OPENAI_API_KEY,
        sessionId: sessionId ?? undefined,
      });
      const toolCalls: { name: string; args: Record<string, unknown> }[] = [];
      const toolSpans = new Map<string, Span>();
      let turns = 0;
      let stopReason = "end_turn";
      agent.subscribe((e) => {
        // pi has no turn limit of its own: stop before the next model call once MAX_TURNS calls were made
        if (e.type === "turn_end" && ++turns >= MAX_TURNS && e.toolResults.length) {
          stopReason = "max_turns";
          agent.abort();
        } else if (e.type === "tool_execution_start") {
          toolCalls.push({ name: e.toolName, args: e.args ?? {} });
          const s = tracer.startSpan(`execute_tool ${e.toolName}`);
          s.setAttribute("gen_ai.tool.name", e.toolName);
          if (sessionId) s.setAttribute("session.id", sessionId);
          toolSpans.set(e.toolCallId, s);
        } else if (e.type === "tool_execution_end") {
          const s = toolSpans.get(e.toolCallId);
          if (e.isError) s?.setStatus({ code: SpanStatusCode.ERROR });
          s?.end();
        }
      });
      const onAbort = () => agent.abort(); // client disconnect or RUN_TIMEOUT_S (server.ts)
      signal.addEventListener("abort", onAbort);
      try {
        await agent.prompt(prompt);
      } finally {
        signal.removeEventListener("abort", onAbort);
      }
      // pi-ai reports an upstream guardrail as an error ("Provider finish_reason: content_filter")
      if (/finish_reason: content_filter/.test(agent.state.errorMessage ?? "") && stopReason === "end_turn") {
        stopReason = "content_filter";
      } else if (agent.state.errorMessage && stopReason === "end_turn" && !signal.aborted) {
        throw new Error(agent.state.errorMessage);
      }

      const assistant = agent.state.messages.filter((m): m is AssistantMessage => m.role === "assistant");
      const last = assistant.at(-1);
      const output = stopReason !== "end_turn" ? "" : (last?.content ?? [])
        .filter((c) => c.type === "text")
        .map((c) => (c as { text: string }).text)
        .join("")
        .trim();
      // pi-ai reports 0 when the provider sent no usage; a prompt never costs 0 input tokens, so that is "unknown"
      const sum = (k: "input" | "output") => assistant.reduce((n, m) => n + (m.usage?.[k] ?? 0), 0);
      const known = sum("input") > 0;
      const usage = { input_tokens: known ? sum("input") : null, output_tokens: known ? sum("output") : null };
      root.setAttribute("output.value", output);
      if (known) {
        root.setAttribute("gen_ai.usage.input_tokens", sum("input"));
        root.setAttribute("gen_ai.usage.output_tokens", sum("output"));
      }
      return { output, tool_calls: toolCalls, usage, stop_reason: stopReason };
    } catch (err) {
      root.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
      throw err;
    } finally {
      root.end();
    }
  });
}
