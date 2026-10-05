# Agent meeting coordination

From the repository root:

```bash
python -m pip install '.[apps]'
python -m nakama meeting-demo
```

This is the scheduling SDK's end-to-end local example: two agent identities,
signed gateway calls, shared free time, two owner decisions, one booking,
idempotent repetition, and revocation. It uses `MemoryCalendar` and a disposable
SQLite proposal store. It sends no external invitations.

The components are reusable library modules under `nakama.scheduling`, rather
than scheduling logic embedded in the example. See
[host integration and Google Calendar setup](../../docs/scheduling.md).
