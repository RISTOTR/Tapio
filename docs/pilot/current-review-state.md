# Authoritative current review state

The confirmation form previously initialized its dropdowns from the frozen suggestion,
using `suggestion[field] || 'UNKNOWN'`. The current-state text already came from the
server, so the text and dropdowns could contradict each other after reload. Applying a
decision updated the text but did not replace the form's source of state.

The browser now fetches `/pilot/confirmation/current` separately from historical card
evidence. Each field contains `value`, `field_status` and `authority`; the decision also
contains transaction/card IDs, review version and latest audit ID. Apply returns this
same projection, and the browser replaces the complete form with it.

A missing value selects a blank “Unresolved” option. A genuine persisted UNKNOWN has
status HUMAN_CONFIRMED_UNKNOWN. UNREVIEWED and UNRESOLVED remain separate statuses.
Frozen suggestions are explicitly labeled ORIGINAL SUGGESTION and do not initialize
current decisions. Confirming an original suggestion is a separate deliberate action.

Loading, refresh and pageshow discard previous form state. Fetches use no-store,
async generations prevent stale responses from replacing newer ones, and defaultSelected
is aligned with current values. Corrections carry their current review version, touched
fields and explicit UNKNOWN selections. The browser and server reject accidental
changes as UNCONFIRMED_UI_STATE_CHANGE; stale versions require refresh. Server preview,
explicit commit, CSRF checks and append-only audits remain mandatory.

The regression uses a real Chrome process, HTTP server and disposable migrated
PostgreSQL schema. It saves OTHER/PERSONAL, GROCERIES/PERSONAL, MAINTENANCE/PROPERTY,
TRAVEL/FORESTRY and explicit UNKNOWN; checks partial unresolved context; reloads,
navigates back and restarts the server; and checks accidental-reset and dirty-state
behavior. When the privately retained original page is available, it also reproduces
UNKNOWN dropdowns over a correct OTHER/PERSONAL backend. No real pilot labels are written.

Entity identity (ENTITY_TYPE_SUPPORT) is distinct from purchase-purpose evidence
(PURCHASE_PURPOSE_SUPPORT). Airline, airport-food-service, department-store, general-retail
and home-goods mappings require a compatible transaction-specific receipt category.
A concept alone cannot convert an onboard purchase into a travel purchase. All semantic
and category-mapping approvals remain separate human decisions.

Pending candidate support can be refreshed through versioned evidence overlays, without
rewriting original candidate snapshots or decision events. Overlays cannot modify identity,
classification, authority or approval; already decided candidates retain their snapshots.
