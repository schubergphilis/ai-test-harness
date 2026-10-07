// pi harness: canary agent (pi-agent-core + pi-ai) over an OpenAI-compatible endpoint.
import { Agent } from "@mariozechner/pi-agent-core";
import type { AssistantMessage, Model } from "@mariozechner/pi-ai";
import { trace, SpanStatusCode, type Span } from "@opentelemetry/api";
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

export async function run(prompt: string, sessionId: string | null, user: string | null) {
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
      agent.subscribe((e) => {
        if (e.type === "tool_execution_start") {
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
      await agent.prompt(prompt);
      if (agent.state.errorMessage) throw new Error(agent.state.errorMessage);

      const assistant = agent.state.messages.filter((m): m is AssistantMessage => m.role === "assistant");
      const last = assistant.at(-1);
      const output = (last?.content ?? [])
        .filter((c) => c.type === "text")
        .map((c) => (c as { text: string }).text)
        .join("")
        .trim();
      const usage = {
        input_tokens: assistant.reduce((n, m) => n + (m.usage?.input ?? 0), 0),
        output_tokens: assistant.reduce((n, m) => n + (m.usage?.output ?? 0), 0),
      };
      root.setAttribute("output.value", output);
      root.setAttribute("gen_ai.usage.input_tokens", usage.input_tokens);
      root.setAttribute("gen_ai.usage.output_tokens", usage.output_tokens);
      return { output, tool_calls: toolCalls, usage };
    } catch (err) {
      root.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
      throw err;
    } finally {
      root.end();
    }
  });
}
