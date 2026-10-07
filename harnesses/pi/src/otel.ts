// Optional tracing: only when OTEL_EXPORTER_OTLP_ENDPOINT is set (standard OTEL_* env vars configure the exporter).
import { NodeSDK } from "@opentelemetry/sdk-node";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-proto";

if (process.env.OTEL_EXPORTER_OTLP_ENDPOINT) {
  const sdk = new NodeSDK({ traceExporter: new OTLPTraceExporter(), instrumentations: [] });
  sdk.start();
  process.on("SIGTERM", () => sdk.shutdown().finally(() => process.exit(0)));
}
