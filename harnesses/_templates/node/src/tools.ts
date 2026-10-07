// Canary tools, identical across harnesses (see compat/CONTRACT.md).
import { readFileSync } from "node:fs";

const fixture = JSON.parse(readFileSync(process.env.CANARY_FIXTURE ?? "/app/canary.json", "utf8"));
const TABLE: Record<string, number | string> = Object.fromEntries(
  Object.entries(fixture.lookup_table as Record<string, number | string>).map(([k, v]) => [k.toLowerCase(), v]),
);

export const SYSTEM_PROMPT =
  "You are a precise assistant. Always use the provided tools for lookups and arithmetic; never guess numbers.";

export const TOOLS = [
  {
    type: "function" as const,
    function: {
      name: "lookup",
      description: "Look up the population of a place by name.",
      parameters: { type: "object", properties: { key: { type: "string" } }, required: ["key"] },
    },
  },
  {
    type: "function" as const,
    function: {
      name: "add",
      description: "Add two integers.",
      parameters: {
        type: "object",
        properties: { a: { type: "integer" }, b: { type: "integer" } },
        required: ["a", "b"],
      },
    },
  },
];

export const IMPLS: Record<string, (args: any) => number | string> = {
  lookup: ({ key }) => TABLE[String(key).trim().toLowerCase()] ?? `error: unknown key '${key}'`,
  add: ({ a, b }) => Number(a) + Number(b),
};
