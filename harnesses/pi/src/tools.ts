// Canary tools, identical across harnesses (see compat/CONTRACT.md).
import { readFileSync } from "node:fs";
import { Type } from "@mariozechner/pi-ai";
import type { AgentTool } from "@mariozechner/pi-agent-core";

const fixture = JSON.parse(readFileSync(process.env.CANARY_FIXTURE ?? "/app/canary.json", "utf8"));
const TABLE: Record<string, number> = Object.fromEntries(
  Object.entries(fixture.lookup_table as Record<string, number>).map(([k, v]) => [k.toLowerCase(), v]),
);

export const SYSTEM_PROMPT =
  "You are a precise assistant. Always use the provided tools for lookups and arithmetic; never guess numbers.";

const text = (value: unknown) => ({ content: [{ type: "text" as const, text: String(value) }], details: value });

const lookupParams = Type.Object({ key: Type.String() });
const lookup: AgentTool<typeof lookupParams> = {
  name: "lookup",
  label: "lookup",
  description: "Look up the population of a place by name.",
  parameters: lookupParams,
  execute: async (_id, { key }) => text(TABLE[String(key).trim().toLowerCase()] ?? `error: unknown key '${key}'`),
};

const addParams = Type.Object({ a: Type.Integer(), b: Type.Integer() });
const add: AgentTool<typeof addParams> = {
  name: "add",
  label: "add",
  description: "Add two integers.",
  parameters: addParams,
  execute: async (_id, { a, b }) => text(Number(a) + Number(b)),
};

export const TOOLS: AgentTool<any>[] = [lookup, add];
