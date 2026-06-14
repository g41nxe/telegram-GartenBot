---
name: project-deployment-pattern
description: "For Python-only + DB migration changes on the Pi, only restart the service — setup.sh is first-time only"
metadata: 
  node_type: memory
  type: project
  originSessionId: 160bb039-2344-4f97-870c-e77eb367f98f
---

`scripts/setup.sh` is for first-time OS setup only: installing packages, Node.js, Zigbee2MQTT, and registering systemd units. It does not need to be re-run for code changes.

For Python source changes + DB schema migrations (the common case):
```bash
sudo systemctl restart garden-irrigation
journalctl -u garden-irrigation -n 50 --no-pager
```

The DB migration runs automatically on startup via `database.init_db()`, which uses `ALTER TABLE … ADD COLUMN` wrapped in `try/except OperationalError` — idempotent, safe to re-run.

**Why:** Confirmed during Feature 0007 deployment. Running setup.sh unnecessarily would re-run the Node.js/npm install step (slow, RAM-intensive on Pi Zero W).

**How to apply:** When answering "how do I deploy this?", default to the restart pattern. Only recommend `setup.sh` if systemd unit definitions changed, new system packages are required, or it's a fresh Pi.
