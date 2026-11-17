# OHS East Africa baseline (Uganda-first) and product MVP

Imara OHS is framed **Uganda-first**, with Kenya and ISO 45001 as secondary alignment for multi-country tenants. Upstream Horilla has no OHS module; this is a greenfield Imara feature.

This document is the compliance and product baseline. Implementation follows the `asset` / `helpdesk` pattern: Django app + parallel `horilla_api`, React screens in `horilla-hr-ui` (not in this repo).

---

## 1. Uganda primary resources

### Legislation

| Instrument | Role | Canonical / useful links |
|---|---|---|
| **Occupational Safety and Health Act, 2006 (Act 9)** — Cap. 231 | Primary OSH duties, registration, General Register, medical records, PPE, committees, plant examination | [MoH library PDF](https://library.health.go.ug/sites/default/files/resources/occupational-safety-and-health-act-2006.pdf), [ULRC Laws of Uganda](https://publications.ulrc.go.ug/laws-of-uganda/16/acts/468), [Parliament attachment](https://bills.parliament.ug/attachments/Laws%20of%20Uganda%20(Acts)%20-%20THE%20OCCUPATIONAL%20SAFETY%20AND%20HEALTH%20ACT,%202006.pdf) |
| **Workers Compensation Act** (Act 8/2000; Cap. 225 / revised Cap. 233) | Injury/disease compensation, employer notification to labour officer, medical exam after accident, scheduled diseases | [MoH library PDF](https://library.health.go.ug/sites/default/files/resources/The%20workers%20Compensation%20Act.pdf), [ULII source](https://media.ulii.org/media/legislation/122778/source_file/ed5276bb6b0ad81f/2000-8.pdf), [UGGov Agent Cap. 233](https://www.uggovagent.ug/acts/workers-compensation-act-cap-233), [IRA PDF](https://ira.go.ug/cp/uploads/Workers%20Compensation%20Act%20Cap%20225.pdf) |
| **SI No. 87 of 2014** | OSH plant examination and workplace registration fees; registration validity **3 years** | Listed on [OSHMIS publications](https://oshmis.mglsd.go.ug/home/publications) |
| **Toxic Chemicals Prohibition and Control Act, 2016** | Chemical / CWC-adjacent controls (later phase; not v1) | [OSHMIS publications](https://oshmis.mglsd.go.ug/home/publications) |

### Official guidance and portals

| Resource | Why it matters |
|---|---|
| [OSHMIS (MGLSD)](https://oshmis.mglsd.go.ug/) | Workplace registration, inspections, statutory plant examination, training; OSHD is the enforcing department |
| [Short guide to OSH Act 9, 2006](https://www.businesslicences.go.ug/uploads/documents/A%20SHORT%20GUIDE%20TO%20THE%20OCCUPATIONAL%20SAFETY%20AND%20HEALTH%20ACT%209%2C%202006.pdf) | Employer-facing summary: Form F.11 registration, General Register (OSH.F.21), first aid, PPE, training, plant exam intervals |
| [OSH Guidelines for Office Work Environment (2021)](https://mglsd.go.ug/wp-content/uploads/2021/05/3-OSH-GUIDELINES-IN-AN-OFFICE-2021.pdf) | Risk-based office hazards; policy + worker participation |
| [SSH safeguards guidelines (LGs)](https://mglsd.go.ug/wp-content/uploads/2021/02/SIMPLIFIED-VERSION-OF-THE-NATIONAL-SSH-guidelines.pdf) | Accident/disease notice timelines useful for public-sector tenants |
| [NRC Employment Rights Guide (Uganda, 2025)](https://www.nrc.no/globalassets/pdf/guidelines/the-right-to-decent-work-in-uganda-new-employment-rights-guides/employment-rights-guide-in-uganda.pdf) | Plain-language workers’ compensation insurance and medical expense duties |

### Uganda duties that software must support

From OSH Act 2006 and the short guide:

1. **Workplace registration** — notify Commissioner; keep Certificate of Registration; renew every **3 years**; non-transferable; attach to General Register (ss. 40–41).
2. **OSH policy** — written policy if **≥ 20 workers** at a workplace; revise and communicate (s. 14; Schedule 2).
3. **Safety committee** — for ≥ 20 workers when requested by safety representatives; Commissioner may require setup within 6 months of registration (ss. 16, 41(2)).
4. **General Register** — prescribed form; certificate + accident and occupational disease particulars; extracts for inspectors; preserve **≥ 5 years** after last entry (ss. 112–114).
5. **Training / competence** — no work on injury-liable machines/processes without instruction and training or experienced supervision (s. 13; short guide §11).
6. **PPE** — provide and ensure use where required (ss. 19, 91–92).
7. **Medical supervision & records** — pre-assignment, periodic, post-assignment exams where hazards apply; keep medical records (ss. 21–22).
8. **First aid** — at least one box/cupboard under a responsible person always available in working hours (s. 55).
9. **Statutory plant examinations** — boilers, receivers, hoists/lifts, lifting gear on fixed intervals; reports enter/attach to General Register (ss. 69–80; short guide §§12–13).

From Workers Compensation Act:

1. Worker notice of accident (generally within **1 month**) / disease symptoms (within **3 months**) (s. 9).
2. Employer reports compensable accident **at once** to the area labour officer (any quick means), then **written report** before the worker leaves that employment (s. 10).
3. Death: notify labour officer as soon as reasonably practicable (s. 10).
4. Arrange medical examination after accident notice; employer pays (s. 11).
5. Scheduled occupational disease: employer submits written report with certificate particulars to labour officer at once (ss. 27–28).
6. Maintain workers’ compensation insurance (employer market practice / guide emphasis).

---

## 2. Secondary baselines (Kenya + ISO)

Use these for shared East Africa fields and later country packs — do not fork the whole domain model per country in v1.

### Kenya (already researched)

| Instrument | Parallel to Uganda |
|---|---|
| OSHA 2007 | Risk assessments, policy, training, PPE, workplace registration with DOSHS, annual safety audit, safety committee if **> 20** employees |
| WIBA 2007 | Injury compensation (Kenya counterpart to Workers Compensation Act) |
| ILO MSME OSH guide (Kenya) | Practical checklist overlap with Uganda short guide |

### ISO 45001:2018

Voluntary management-system layer: leadership, worker participation, hazard/risk, emergency preparedness, incident investigation, audits, continual improvement. Map Imara records to evidence packs; do not require certification workflows in v1.

### Shared East Africa capability map

| Capability | Uganda | Kenya | ISO 45001 | v1? |
|---|---|---|---|---|
| Incident / accident report | General Register + WC s.10 | OSHA/WIBA notification | Incident investigation | **Yes** |
| Near-miss / non-injury incident | Act defines “incident” (first-aid only / no injury) | Common practice | Yes | **Yes** |
| Occupational disease case | General Register + WC ss.27–28 | WIBA disease | Ill health | **Yes** |
| Labour-officer / authority notification log | WC s.10 mandatory | WIBA/DOSHS | Compliance evidence | **Yes** |
| Corrective / preventive actions | Implied by investigation & controls | Audit findings | CAPA | **Yes** |
| Workplace registration & certificate expiry | OSH registration, 3-year renew | Workplace registration | Legal register | **Yes** (compliance record) |
| OSH policy (≥20) | s. 14 | OSHA policy | OH&S policy | **Yes** (document + acknowledgement) |
| Safety committee | s. 16 | Committee if >20 | Consultation | **Yes** (membership + meetings) |
| Medical exam records | ss. 21–22 | Fitness / medical | Health surveillance | **Yes** (metadata + attachments; privacy-aware) |
| PPE issue / return | ss. 19, 91 | PPE duty | PPE as control | **Yes** (can link Asset later) |
| Training / competence | s. 13 | Training duty | Competence | **Yes** (records + expiry) |
| First-aid stations | s. 55 | First aid | Emergency | Phase 2 |
| Statutory plant exam schedules | ss. 69–80 | Plant/equipment | Operational control | Phase 2 |
| Formal risk assessment matrix | Guidance / good practice | OSHA s.6 risk assessment | Hazard/risk | Phase 2 |
| Inspections / internal audits | Inspector cooperation | Annual audit | Internal audit | Phase 2 |
| Chemical inventory / PTW | Toxic Chemicals Act; confined space rules | Chemical duties | Hierarchy of controls | Later |

---

## 3. Committed Imara OHS v1 product slice

### Goal

Give every employee a way to report events, give safety officers a General-Register-style case file, and give employers an audit trail for **Uganda WC notification** and **registration/policy/committee** duties — without building a full EHS suite.

### In scope (v1)

1. **Workplaces (OSH sites)** — link to company/location; registration number; certificate attachment; issued/expiry (3-year default hint); status.
2. **Events** — accident, near-miss/incident, occupational disease; employee (optional for visitor/contractor note); datetime; place; description; severity; injury/days lost; attachments.
3. **Authority notification** — channel, notified-at, labour officer/area, written-report-at, reference; required checklist for compensable accidents (Uganda WC s.10).
4. **Investigation + CAPA** — findings, root cause (simple enum + free text), corrective actions with owner, due date, status.
5. **General Register export** — filterable register of accidents/diseases + linked certificates for a workplace; retention awareness (5 years).
6. **Policy & committee** — policy document version + employee acknowledgement; committee members and meeting notes for workplaces ≥ 20 workers.
7. **Medical exam records** — type (pre-assignment / periodic / post-assignment / post-accident); date; fit/unfit/restricted; attachment; next-due (not a clinical EHR).
8. **PPE assignments** — item type, employee, issued/returned, condition (inventory depth can reuse Asset later).
9. **Safety training records** — course, employee, completed-on, valid-until, certificate attachment.
10. **Dashboard / reports** — open events, overdue CAPA, registration expiry, training/medical due, notification compliance gaps.

### Out of scope (v1)

- Statutory plant/boiler examination workflows  
- Full risk-assessment matrices and permit-to-work  
- Inspection checklist builder / annual audit productization  
- Chemical inventory / CWC licensing  
- Claims accounting or insurance premium calculation  
- Direct government OSHMIS filing API (record local evidence only)  
- Rewriting HTMX for React; HTMX gets a minimal parallel shell only if required for rebase parity — prefer API-first for Imara

### Architecture (when building)

```text
ohs/                          # Django app: models, permissions, HTMX optional
horilla_api/api_urls/ohs/
horilla_api/api_views/ohs/
horilla_api/api_serializers/ohs/
horilla_api/tests/test_ohs_*.py
```

- Models subclass `HorillaModel` + `HorillaCompanyManager` (tenant scope).
- Permissions: Django model perms (`ohs.view_*`, `add_*`, `change_*`, `delete_*`); expose codenames in `capabilities.py` for React gating.
- Follow fork rules: parallel API; do not break HTMX contracts; restart `horilla-hr-web-1` after backend changes.
- UI handoff to `D:\projects\horilla-hr-ui` with routes, endpoints, bodies, and permission codenames.

### Suggested core models (v1)

| Model | Purpose |
|---|---|
| `OshWorkplace` | Registered workplace / site |
| `OshEvent` | Accident, incident/near-miss, occupational disease |
| `OshNotification` | Authority / labour-officer notification log |
| `OshInvestigation` | Linked investigation |
| `OshCorrectiveAction` | CAPA items |
| `OshPolicy` | Policy document versions |
| `OshPolicyAcknowledgement` | Employee read/ack |
| `OshSafetyCommittee` / `OshCommitteeMeeting` | Committee + meetings |
| `OshMedicalRecord` | Fitness / surveillance metadata |
| `OshPpeAssignment` | PPE issue/return |
| `OshTrainingRecord` | Competence / induction |

### Country pack approach

Store `jurisdiction` (or company country) on workplace/event. v1 validation rules and notification checklists ship **Uganda** defaults; Kenya field labels/checklists as a thin overlay. Shared schema — not separate apps per country.

---

## 4. Implementation order (after this baseline)

1. Scaffold `ohs` app + models + migrations + admin.  
2. DRF CRUD + notification/CAPA actions + tests.  
3. Capabilities + sidebar entry.  
4. UI handoff: Events list/detail, report form, General Register, Workplace compliance, Training/Medical/PPE lists.  
5. Phase 2: risk assessments, inspections, plant examinations.

Do not start Phase 2 until v1 events + notification + register are live for a Uganda pilot tenant.
