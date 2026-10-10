# Data-use request — BMA traffic CCTV (draft)

**🧑 HUMAN:** draft only — fill in the blanks and send from a project
contact, do not send as-is. Needed whenever a source's ToS is silent on
automation (see `cctv/LEGAL_REVIEW.md` decision rule).

---

To: Bangkok Metropolitan Administration (BMA) — Traffic & Transportation
Department / CCTV operations contact

From: [name], [affiliation], [contact email]

**Subject:** Data-use request — low-rate CCTV snapshot capture for a flood
feasibility research prototype

**Purpose:** We are building a short feasibility prototype ("Bangkok Flood
POC") that compares a hydraulic flood model against publicly visible road
conditions during rain events. We would like to periodically capture single
still frames from a small set of public traffic cameras to build a
visual flood-severity indicator (never described as a depth measurement).

**Cameras:** [attach/paste the specific camera list and IDs/locations once
HU2 — the camera registry input — is available; ≤ 50 cameras total]

**Frequency:** At most 1 request per camera per 2 minutes, capped at 50
cameras — well below any rate that would affect normal camera operation.

**Retention & processing:**
- Every captured frame is downscaled to ≤ 640 px wide.
- Every captured frame has faces and license plates automatically blurred
  **before** it is written to disk; the original frame is never stored.
- No identity analytics, face recognition, or vehicle tracking of any kind
  is performed.
- Frames and derived classifications are used only for this research
  prototype and are not redistributed outside the project team.

**What we're asking for:**
1. Confirmation that this kind of low-rate, privacy-filtered automated
   capture is acceptable, or guidance on an approved alternative (e.g. an
   official API).
2. If available, camera coordinates and heading/orientation for the
   cameras we plan to use, to improve the accuracy of our analysis.

**Contact:** [name / email / phone]

We're happy to share more detail on the methodology or adjust the request
frequency/camera count if useful.
