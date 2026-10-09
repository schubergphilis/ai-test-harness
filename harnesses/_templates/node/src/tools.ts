// Tools offered to the model: exactly the ENABLED set from scenario.ts (canary by default), dispatched via call().
import { ENABLED, SYSTEM_PROMPT, TOOL_SPECS, call } from "./scenario.js";

export { SYSTEM_PROMPT };

export const TOOLS = ENABLED.map((name) => ({
  type: "function" as const,
  function: { name, description: TOOL_SPECS[name].description, parameters: TOOL_SPECS[name].parameters },
}));

export const IMPLS: Record<string, (args: any) => string> = Object.fromEntries(
  ENABLED.map((name) => [name, (args: any) => call(name, args)]),
);
