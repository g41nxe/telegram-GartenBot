---
name: project-quickchart-version
description: "QuickChart.io requires version \"4\" in POST payload for Chart.js v3+ syntax — without it the API returns 400 Bad Request"
metadata: 
  node_type: memory
  type: project
  originSessionId: 160bb039-2344-4f97-870c-e77eb367f98f
---

QuickChart.io defaults to Chart.js v2.9.4. Any Chart.js v3/v4 syntax — scales defined as objects with ID-keys (`"yTemp": {...}`), mixed chart types with per-dataset `type:` overrides — will be rejected with HTTP 400 Bad Request unless the payload explicitly includes `"version": "4"`.

**Why:** Discovered live on the Raspberry Pi during Feature 0007 deployment. The chart adapter (`adapters/chart.py`) initially omitted the version field and failed in production despite passing local tests (which only checked payload structure, not API acceptance).

**How to apply:** Any future work in `adapters/chart.py` or any new QuickChart.io integration must include `"version": "4"` at the top level of the POST body:
```python
payload = json.dumps({"chart": chart_config, "width": 600, "height": 300, "version": "4"})
```
Add a regression test that asserts `body["version"] == "4"` (see `tests/adapters/test_chart.py::test_payload_includes_version_4`).

**Zweites Gotcha — datalabels formatter:** QuickChart führt JavaScript-Strings in `formatter`-Callbacks **nicht** aus. Ein Formatter wie `"function(v, ctx) { return labels[ctx.dataIndex]; }"` wird ignoriert — QuickChart zeigt stattdessen den rohen Datenwert. Lösung: datalabels komplett weglassen oder nur statische Strings verwenden. Entdeckt 2026-06-14 beim Versuch Regenwahrscheinlichkeits-Labels auf Balken zu zeigen (`test_bar_dataset_has_no_datalabels`).
