import { interpretTurnJournal } from "../../loopx/control_plane/turn_driver/turn_journal.ts";

const request = JSON.parse(await readStdin());
const corpus = request.corpus;
const rows = corpus.cases.map((testCase) => {
  const probe = testCase.request;
  const result = interpretTurnJournal({
    schema_version: "loopx_turn_journal_interpretation_request_v0",
    journal: probe.journal,
    goal_id: probe.goal_id,
    agent_id: probe.agent_id,
    turn_key: probe.turn_key,
  });
  const { ok: _ok, schema_version: _schemaVersion, ...row } = result;
  return { case_id: testCase.case_id, ...row };
});

process.stdout.write(
  JSON.stringify({
    schema_version: "loopx_turn_journal_characterization_probe_v0",
    corpus_schema_version: corpus.schema_version,
    implementation_id: request.implementation_id,
    rows,
  }),
);

async function readStdin() {
  let raw = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) raw += chunk;
  return raw;
}
