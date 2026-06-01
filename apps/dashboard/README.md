# Goal Harness Dashboard

This is the first product dashboard shell for Goal Harness. It renders the
status data contract with a React/Vite control-plane UI.

## Run

```bash
npm install
npm run build
npm run dev
```

The default screen uses the sanitized repository example at
`examples/status.example.json`.

## Load Real Status

Use a local static export:

```bash
python3 -m goal_harness.cli --format json status > apps/dashboard/public/status.local.json
cd apps/dashboard
npm run dev
```

Then load `/status.local.json` from the dashboard source control.

You can also import a JSON file directly in the browser, or load a local API
URL that returns the same `goal-harness --format json status` shape.
