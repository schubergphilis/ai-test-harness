// Tools registered with pi: exactly the ENABLED set from scenario.ts (canary by default), all dispatched via call().
import type { AgentTool } from "@mariozechner/pi-agent-core";
import { ENABLED, SYSTEM_PROMPT, TOOL_SPECS, call } from "./scenario.js";

export { SYSTEM_PROMPT };

const text = (value: string) => ({ content: [{ type: "text" as const, text: value }], details: value });

// pi-ai validates tool arguments against plain JSON schema as well as TypeBox schemas.
export const TOOLS: AgentTool<any>[] = ENABLED.map((name) => ({
  name,
  label: name,
  description: TOOL_SPECS[name].description,
  parameters: TOOL_SPECS[name].parameters as any,
  execute: async (_id: string, args: unknown) => text(call(name, (args ?? {}) as Record<string, unknown>)),
}));
