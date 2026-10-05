# Scheduling SDK

Nakama coordinates availability and approval across connected agents. The host
application links calendar accounts to authenticated owners. The SDK does not
infer ownership from a display name, email submitted by an agent, or vendor label.

## Try the local workflow

```bash
python -m pip install '.[apps]'
python -m nakama meeting-demo
```

The demo starts a disposable HTTP gateway, registers two local identities using
different transports, finds shared slots, denies booking before both simulated
owners approve, creates one local organizer event, and revokes access. It does not
launch vendor assistants, authenticate real owners, or contact external calendars.

## Client API

```python
from nakama import Client

agent = Client.new(gateway_url)
agent.register("Alice")
# Request a connection; the operator approves scopes separately.
slots = agent.scheduling.find_slots(
    peer_id, start="2030-01-02T09:00:00-05:00", end="2030-01-02T18:00:00+01:00",
    duration_minutes=30, limit=5,
)["slots"]
if slots:
    proposal = agent.scheduling.propose(peer_id, **slots[0], summary="Project meeting")
    # Returns a scheduling error until both owners approve through the host.
    booked = agent.scheduling.book(peer_id, proposal["id"])
```

`SchedulingClient(client)` also works with existing `gwclient.GWClient` instances.
Times require explicit UTC offsets and responses use UTC. Queries are limited to
31 days and meetings to eight hours. The provider returns busy intervals; the
service subtracts them inside host-configured sharing windows. Empty sharing
windows expose no free time. Hosts should express working hours as explicit
timezone-aware windows, including daylight-saving transitions.

## Permissions and operations

| Operation | Required scopes | Effect |
| --- | --- | --- |
| `availability`, `find_slots` | `app.calendar:availability` | Returns free windows or shared candidate slots |
| `propose` | `app.calendar:propose` and `app.calendar:availability` | Persists an immutable proposal; writes no event |
| `status` | `app.calendar:propose` | Returns only this connection's proposal |
| `book` | All three calendar scopes, including `app.calendar:book` | Creates one organizer event after both owners approve |

All signed app calls still check live identities, accepted friendship, directional
grants, and expiry. The service checks those permissions again before booking.
Revocation stops new access; it does not delete an event already created.

The same operations are available through the existing MCP `invoke_app` tool.
There is no agent-accessible approval, account-linking, or scope-granting operation.

## Host integration

The main extension points are `CalendarProvider`, `ProposalStore`, and the injected
permission checker. Application declarations live in `nakama.contracts` and do not
depend on HTTP or SQLite. `CalendarAdapter` connects the service to a gateway.

```python
from nakama.gateway import Gateway
from nakama.apps import AppRegistry
from nakama.scheduling import CalendarBinding, MeetingService, SQLiteProposalStore
from nakama.scheduling.adapter import CalendarAdapter
from gateway.apps import require_peer_scope

# owner_linked_bindings comes from the host's authenticated account-linking flow.
# Each CalendarBinding specifies owner_id, provider, attendee_address,
# sharing_windows, and a binding_id that changes whenever the account is relinked.
proposals = SQLiteProposalStore("meetings.db")
services = {}

def applications(gateway_store):
    service = MeetingService(owner_linked_bindings, proposals,
        lambda caller, peer, scope: require_peer_scope(gateway_store, caller, peer, scope))
    services["meetings"] = service
    return AppRegistry([CalendarAdapter(service)])

try:
    with Gateway(database="gateway.db", applications=applications) as gateway:
        # On initial startup, deliver gateway.console_token to the operator securely.
        gateway.serve_forever()
finally:
    proposals.close()
```

`Gateway.shutdown()` must be called from another thread while serving. Stop and
join that thread before closing the runtime. The bundled HTTP server remains a
reference implementation; production hosts supply deployment hardening.

After authenticating an owner, the host UI calls
`service.approve(proposal_id, authenticated_owner_id)` or `service.reject(...)`.
Never expose these trusted methods directly to agents or accept an unauthenticated
owner ID. Neither method books an event. Approval applies only to the stored
participants, time, summary, and account bindings. Each proposal expires within
24 hours or at its start time, whichever comes first. Relinking an account requires
a new proposal. The bundled operator console manages grants; it is not a two-owner
account system or a calendar approval UI.

## Google Calendar provider

`GoogleCalendar` accepts an authorized Google Calendar v3 discovery client. The
embedding application handles OAuth consent, token storage and refresh, account
linking, and finite HTTP timeouts. A separate write client is optional:

```python
from nakama.scheduling import GoogleCalendar

provider = GoogleCalendar(read_service, calendar_id="primary",
                          write_service=write_service)
```

The adapter uses [free/busy query](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query)
and [event insertion](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert).
Missing calendar results and per-calendar errors fail closed. Event IDs derive
from proposal IDs so duplicate insertions can be reconciled. A successful booking
creates one organizer event with an attendee and requests invitation delivery;
the guest calendar's acceptance/display behavior remains the provider's concern.
No live Google OAuth or invitation delivery is exercised in automated tests.

## Booking recovery and limitations

The proposal store commits booking intent before calling the provider. Repeating
the same proposal uses the same provider request ID. A failed or uncertain write
keeps the proposal in `booking`; overlapping proposals involving either agent are
blocked while it is unresolved. Approval records and booking intent survive restart.
Provider implementations must honor the idempotent request-ID contract.

Booking rechecks sharing windows and both calendars before its first write. There
is no atomic lock across external calendars, so another application may add an
event between that check and insertion. The SDK prevents duplicate requests and
conflicting local booking intents; it does not promise universal conflict-free
booking. If a write remains uncertain after proposal expiry or permission
revocation, the host must reconcile the provider event using the proposal's request
ID. Do not create a replacement proposal until that uncertainty is resolved.

Cancellation of booked events, recurring meetings, multi-party negotiation, live
vendor execution, Microsoft/Apple providers, and a hosted owner account UI remain
separate extensions. Calendar details and tokens should stay in the host/provider
layer; availability responses contain only start/end windows.
