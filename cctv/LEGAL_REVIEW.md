# CCTV / DDS legal review

**🧑 HUMAN (HU1):** this file is a template only — the agent must not fill in
decisions, and must not fetch any of the URLs below itself (that would be an
automated request to an external site before a gate exists). Varun reads
each source's Terms of Service and `robots.txt`, fills every field below,
then sets the matching `decision` / `approved_by` / `approved_utc` /
`conditions_ack` in `cctv/legal_status.yaml`.

**Decision rule:**
- ToS explicitly prohibits automated access / scraping → **NO_GO**.
- ToS is silent (no explicit prohibition, no explicit permission) → **GO**
  only if every condition below is accepted *and* the BMA data-use request
  (`docs/stakeholder_requests/bma_cctv.md`) has been sent.
- ToS explicitly permits this kind of automated, low-rate, research use →
  **GO**.

**Conditions (apply to every GO):**
- ≤ 1 request / camera / 2 minutes (`configs/cctv.yaml: min_interval_s: 120`)
- ≤ 50 cameras (`configs/cctv.yaml: max_cameras: 50`)
- User-Agent identifies the project and includes a contact email
- Frames downscaled to ≤ 640 px wide before being written to disk
- Faces / plates blurred before being written to disk
- Purpose stated as flood observation research only, never redistributed
  outside the project without separate agreement

---

**🤖 Agent research pass (2026-10-08):** the fields below marked `checked_by:
agent (research only)` were filled from public ToS/robots.txt pages fetched
read-only on Varun's explicit instruction in-session (never the camera/data
endpoints themselves — those stay behind the legal gate regardless). Every
`Decision` / `Conditions accepted` cell is left blank: only Varun sets those,
per this file's own header and agent rule 4. Where a reading is strongly
suggested by what was found, it's noted separately as **"Agent's reading
(non-binding)"** — a starting point to confirm or overrule, not a decision.

## BMA Traffic — `http://www.bmatraffic.com/index.aspx`

| Field | Value |
|---|---|
| checked_utc | 2026-10-08T14:48:51Z |
| checked_by | agent (research only) |
| ToS URL / text | **Unreachable from this environment** — `http://www.bmatraffic.com/index.aspx` and `/robots.txt` both connection-timed-out (port 80) / connection-refused (port 443, no TLS configured) on every attempt (plain `curl`, with explicit User-Agent, and via the fetch tool). A related BMA subsystem, `https://cpudapp.bangkok.go.th/bmatraffic/`, and the main `https://www.bangkok.go.th/` both returned **HTTP 403 Forbidden** to the same fetch tool — i.e. BMA's infrastructure appears to actively block non-browser/automated requests at the edge (WAF or similar), which is itself a signal worth weighing even without reading the ToS text directly. |
| robots.txt lines | Not retrievable (see above). |
| Automation allowed (YES / NO / SILENT) | **Unknown** — could not reach the ToS or robots.txt. The 403s on BMA's other properties suggest the infrastructure itself resists automated access, independent of what the ToS says. |
| Redistribution terms | Unknown — not reachable. |
| PDPA exposure (faces/plates visible?) | Assume YES until proven otherwise (it's a live traffic CCTV feed) — doesn't change with reachability. |
| **Decision** | *(Varun — see conditions-decision rule above; note the 403s before assuming SILENT just because the ToS text itself wasn't found)* |
| Conditions accepted (list any exceptions) | |
| Escalation (if NO_GO or unclear) | Retry the fetch from a normal browser / Thailand-based connection (this environment's requests may be geo- or WAF-filtered in a way a real browser session wouldn't be) before concluding SILENT; if still unreachable, treat as "can't verify terms" rather than defaulting to GO. |

## iTIC Live — `https://live.iticfoundation.org/` (main site: `https://www.iticfoundation.org/`)

| Field | Value |
|---|---|
| checked_utc | 2026-10-08T14:48:51Z |
| checked_by | agent (research only) |
| ToS URL / text | No dedicated Terms of Service / Terms of Use / data-redistribution page found on `www.iticfoundation.org` (checked the homepage and footer). The only legal text present is a bare copyright line: *"© 2024 ALL RIGHT RESERVED. iTIC"*. `live.iticfoundation.org` (the actual traffic-map subdomain) wasn't separately checked for a ToS page beyond its robots.txt. |
| robots.txt lines (relevant disallow/allow) | `live.iticfoundation.org/robots.txt`: generic Drupal boilerplate — `Crawl-delay: 10`, `Disallow:` only on CMS internals (`/includes/`, `/admin/`, `/user/login/`, etc.). **No disallow on the traffic-data pages/API themselves.** |
| Automation allowed (YES / NO / SILENT) | **SILENT** — no explicit prohibition found anywhere reachable, but also no explicit permission; a bare copyright notice doesn't address automated access at all. |
| Redistribution terms | Not addressed anywhere found. |
| PDPA exposure (faces/plates visible?) | Assume YES (live traffic CCTV, sourced partly from BMA/police cameras per iTIC's own "how it works" page). |
| **Decision** | |
| Conditions accepted | |
| Escalation | None found needing escalation; SILENT → the decision rule's "GO only with all conditions + BMA data-use request sent" path applies if Varun agrees with this reading. |

## Longdo Traffic — `https://traffic.longdo.com/`

| Field | Value |
|---|---|
| checked_utc | 2026-10-08T14:48:51Z |
| checked_by | agent (research only) |
| ToS URL / text | `traffic.longdo.com` itself has no visible ToS link on the page, but its footer identifies the operator as **Metamedia Technology Co., Ltd.** (`© 2005-2026 metamedia technology`) — the same company whose **Longdo Map Terms of Use** (`https://map.longdo.com/terms`) explicitly cover the wider Longdo product family. Relevant clauses quoted verbatim: *"You may not use Longdo Map in a manner which gives you or any other person access to mass downloads or bulk feeds of map imagery, search results, and numerical latitude and longitude coordinates."* and *"[do not] use any robot, spider, site search/retrieval application, or other device to retrieve or index any portion of Longdo services or collect information about users for any unauthorized purpose."* Also: no commercial use without a license from Metamedia Technology, and no redistribution beyond internal use. |
| robots.txt lines | `traffic.longdo.com/robots.txt`: generic Drupal boilerplate (same shape as iTIC's), no explicit disallow on the traffic pages themselves. (`longdo.com/robots.txt` 404s — no file at the root domain.) |
| Automation allowed (YES / NO / SILENT) | **NO** by the strongest available reading — the Longdo Map ToS's bot/crawler and bulk-feed/mass-download clauses read squarely over what a CCTV/traffic archiver would do, even though they weren't found on the `traffic.longdo.com` page itself. *(Not confirmed that this exact document legally governs `traffic.longdo.com` rather than just `map.longdo.com` — same operator and product family, but a different subdomain/service; worth a direct question to Metamedia if GO is otherwise attractive.)* |
| Redistribution terms | Explicitly prohibited beyond internal use without a Metamedia Technology license (per the Map ToS). |
| PDPA exposure | Assume YES (live traffic CCTV). |
| **Decision** | |
| Conditions accepted | |
| Escalation | **Agent's reading (non-binding): leans NO_GO** given the explicit bot/bulk-download prohibition — Varun to confirm whether the Map ToS is understood to govern Longdo Traffic too, directly with Metamedia Technology (`info@mm.co.th`) if there's any doubt before relying on it either way. |

## DDS floodbangkok — `http://dds.bangkok.go.th/Floodmon`

| Field | Value |
|---|---|
| checked_utc | 2026-10-08T14:48:51Z |
| checked_by | agent (research only) |
| ToS URL / text | **Unreachable from this environment** — `dds.bangkok.go.th` (root, `/Floodmon`, `/robots.txt`) all connection-timed-out on every attempt (`curl` and the fetch tool). Same pattern as `bangkok.go.th` returning 403 to automated requests elsewhere, consistent with BMA infrastructure resisting non-browser access generally (see BMA Traffic row above). |
| robots.txt lines | Not retrievable. |
| Automation allowed (YES / NO / SILENT) | Unknown — could not reach. |
| Redistribution terms | Unknown. |
| PDPA exposure (faces/plates visible?) | N/A for this source — it's road-flood depth points (T21), not camera frames; still a public-infrastructure data source subject to the same courtesy/rate-limit conditions. |
| **Decision** | |
| Conditions accepted | |
| Escalation | Same as BMA Traffic: retry from a browser / Thailand-based connection before concluding anything; don't default to GO just because the ToS couldn't be read. |

## DDS SCADA — `http://dds.bangkok.go.th/Canal`

| Field | Value |
|---|---|
| checked_utc | 2026-10-08T14:48:51Z |
| checked_by | agent (research only) |
| ToS URL / text | Same domain as DDS floodbangkok above (`dds.bangkok.go.th`) — **unreachable from this environment** for the same reason. |
| robots.txt lines | Not retrievable. |
| Automation allowed (YES / NO / SILENT) | Unknown — could not reach. |
| Redistribution terms | Unknown. |
| PDPA exposure | N/A — canal water-level gauge readings, not imagery. |
| **Decision** | |
| Conditions accepted | |
| Escalation | Same as DDS floodbangkok — likely the same decision for both, since they're the same domain/operator, but confirm independently once reachable in case BMA's terms differ by subsystem. |
