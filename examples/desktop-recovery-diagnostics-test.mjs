import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const script = readFileSync(new URL('../apps/desktop/loopx-control-plane/static/boot.js', import.meta.url), 'utf8');
function page() {
  const elements = new Map();
  const context = {
    document: {querySelector(id) {
      if (!elements.has(id)) elements.set(id, {dataset: {}, setAttribute() {}, focus() {}, select() {this.selected = true;}});
      return elements.get(id);
    }},
    window: {}, navigator: {clipboard: {writeText: async () => {throw new Error('denied');}}},
    setInterval() {},
  };
  runInNewContext(script, context);
  return {context, elements};
}
test('export uses bounded fields and preserves the last failure after a check', () => {
  const {context, elements} = page();
  context.packet = {app_version: '1.0.0', state: {phase: 'up_to_date'}, last_failure: {
    phase: 'runtime_required', details: {code: 'runtime_setup_required', installed_identity_available: false, revision_matches: false, content: 'PRIVATE', path: 'PRIVATE'},
  }};
  runInNewContext('renderDiagnostics(packet)', context);
  const value = JSON.parse(elements.get('#diagnostics').value);
  assert.equal(value.error_code, 'runtime_setup_required');
  assert.equal(value.failure_phase, 'runtime_required');
  assert.equal(value.installed_identity_available, false);
  assert.ok(!JSON.stringify(value).includes('PRIVATE'));
  context.packet.last_failure.details.code = 'PRIVATE';
  context.packet.app_version = 'PRIVATE';
  runInNewContext('renderDiagnostics(packet)', context);
  assert.ok(!elements.get('#diagnostics').value.includes('PRIVATE'));
});
test('installer failure is actionable and clipboard denial leaves selectable text', async () => {
  const {context, elements} = page();
  runInNewContext('render({phase:"error",details:{code:"runtime_install_exit_23"}})', context);
  assert.match(elements.get('#update-status').textContent, /23/);
  assert.equal(elements.get('#repair').disabled, false);
  await elements.get('#copy-diagnostics').onclick();
  assert.equal(elements.get('#diagnostics').selected, true);
});
