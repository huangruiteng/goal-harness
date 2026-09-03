// Roarr is JSON-native and keeps this serverless-oriented example small.
// It reads ROARR_LOG at module load, so enable it before importing.
process.env.ROARR_LOG = "true";

const { ROARR, Roarr } = await import("roarr");
const command = process.argv[2] ?? "status";
const log = Roarr.child({ command });

if (command === "fail") {
  ROARR.write = (chunk) => process.stderr.write(chunk + "\n");
  log.error("failed");
  process.exitCode = 1;
} else {
  ROARR.write = (chunk) => process.stdout.write(chunk + "\n");
  log.info("completed");
}
