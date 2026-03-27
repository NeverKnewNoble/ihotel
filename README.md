# iHotel

A full-featured Hotel Property Management System (PMS) built as a native [Frappe](https://frappeframework.com) app on top of ERPNext. iHotel covers the complete guest lifecycle — from reservation through check-in, stay management, housekeeping, laundry, maintenance, night audit, and financial posting — all within a single Frappe site.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
3. [Architecture Overview](#architecture-overview)
4. [Module Breakdown](#module-breakdown)
   - [Front Desk & Reservations](#front-desk--reservations)
   - [Room Management](#room-management)
   - [Guest Profiles](#guest-profiles)
   - [Rate & Revenue Management](#rate--revenue-management)
   - [Housekeeping](#housekeeping)
   - [Maintenance](#maintenance)
   - [Laundry](#laundry)
   - [Night Audit](#night-audit)
   - [Reporting](#reporting)
5. [DocType Reference](#doctype-reference)
6. [Custom Pages](#custom-pages)
7. [Role & Permission Matrix](#role--permission-matrix)
8. [Scheduled Tasks](#scheduled-tasks)
9. [Fixtures & Configuration](#fixtures--configuration)
10. [Data Flow Diagrams](#data-flow-diagrams)
11. [Contributing](#contributing)
12. [License](#license)

---

## Requirements

| Dependency | Version |
|---|---|
| Frappe Framework | v15+ |
| ERPNext | v15+ (for accounting, Customer, Supplier, Sales Invoice) |
| Python | 3.10+ |
| MariaDB | 10.6+ |

---

## Installation

```bash
# From your bench directory
bench get-app https://github.com/your-org/ihotel --branch main
bench --site your-site.com install-app ihotel
bench --site your-site.com migrate
```

After installation, open **iHotel Settings** to configure:
- Default currency and tax template
- Check-in / check-out times
- Night audit schedule

---

## Architecture Overview

iHotel follows standard Frappe app conventions. Every feature is a **DocType** — a schema-defined document type with its own database table, Python controller, and JavaScript form handler.

```
ihotel/                          ← Python package (app root)
├── hooks.py                     ← App lifecycle hooks, scheduler, fixtures
├── tasks.py                     ← Scheduled background jobs
├── notifications.py             ← Document event handlers
│
└── ihotel/                      ← Module directory
    ├── doctype/                 ← All DocTypes (50+)
    │   ├── <doctype_name>/
    │   │   ├── <doctype_name>.json    ← Schema definition (fields, permissions)
    │   │   ├── <doctype_name>.py     ← Python controller (business logic)
    │   │   ├── <doctype_name>.js     ← Client-side form logic
    │   │   └── <doctype_name>_list.js ← List view customizations
    │   └── ...
    │
    ├── report/                  ← Script Reports (10)
    │   ├── <report_name>/
    │   │   ├── <report_name>.json    ← Report metadata
    │   │   └── <report_name>.py     ← Column + SQL definitions
    │   └── ...
    │
    ├── page/                    ← Custom Desk Pages (7)
    │   ├── <page_name>/
    │   │   ├── <page_name>.json
    │   │   ├── <page_name>.py
    │   │   ├── <page_name>.js
    │   │   └── <page_name>.css
    │   └── ...
    │
    ├── workspace_sidebar/
    │   └── ihotel.json          ← Sidebar navigation definition
    │
    └── public/
        └── css/
            └── ihotel.css       ← Global desk styles
```

### Key Architectural Decisions

**DocType-first design** — Every entity (room, guest, reservation, order) is a DocType. This gives each one a list view, form view, permissions, version history, comments, attachments, and API endpoints for free via the Frappe framework.

**Submittable documents for financial records** — `Checked In` and `Laundry Order` are submittable (`is_submittable: 1`). Submission locks the record and triggers financial posting (folio creation, Sales Invoice). Amendments create a new version linked via `amended_from`.

**Child tables for line items** — Rate lines, service items, laundry items, folio charges, and payments are child DocTypes (marked `istable: 1`) embedded inside their parent. They have no independent list view.

**ERPNext integration points** — iHotel creates and links ERPNext documents at key moments:
- `Checked In` submit → creates `iHotel Profile` + links `Sales Invoice` at checkout
- `Laundry Order` delivery → creates `Sales Invoice`
- `Supplier Batch` return → triggers `Purchase Invoice` creation

**Scheduled automation** — `hooks.py` registers background jobs for late checkout alerts, auto no-show marking, housekeeping task generation, birthday notifications, and night audit reminders.

---

## Module Breakdown

### Front Desk & Reservations

The core operational module. Manages the full guest stay lifecycle.

#### Reservation

The pre-arrival record. Captures all booking details before a guest physically arrives.

**Key fields:** guest, room type, check-in/out dates, adults/children, rate lines (child table), guarantee & payment method (Credit Card / Cash / Cheque / Direct Bill), color coding for the calendar view, business source.

**Key actions:**
- **Convert to Checked In** — copies all data (color, adults, children, rate lines, business source, deposit, payment method/detail) into a new `Checked In` document. No re-entry required at the desk.
- **Reservation Confirmation Letter** — triggered by the `Reservation Confirmation Letter` Notification fixture on save.
- Calendar view (`reservation_calendar.js`) — reservations appear color-coded on a calendar.

#### Checked In

The active stay document. Submittable.

**Key fields:** guest (Link → Guest), room, expected/actual check-in and check-out, status (Reserved / Checked In / Checked Out / No Show / Cancelled), rate lines, total charges, tax, total amount, deposit, iHotel Profile link, Sales Invoice link.

**On submit:**
1. Creates an `iHotel Profile` (the financial folio for the stay).
2. Posts the deposit as a payment row on the profile.
3. Maps the billing method from the reservation (Visa/Mastercard/Amex/Cash/Cheque/City Ledger).

**On checkout:** links the generated `Sales Invoice` to the profile.

**Guest Services flags:** Do Not Disturb, Make Up Room, Turndown Requested (managed via the Turndown page, hidden on the form).

#### Group Reservation

Handles multi-room bookings under a single group. Links to individual room assignments via `Group Room Assignment` child records.

#### iHotel Profile

The financial folio for a stay. Created automatically on `Checked In` submit.

**Child tables:**
- `Payment Items` — each payment row (method, amount, status). Per-row Print button.
- `Folio Charge` — each posted charge (room rate, laundry, services). Per-row Print and Scan buttons.

**Payment Status:** fetched from the profile and displayed on the `Checked In` form.

---

### Room Management

#### Room

The physical room master. Fields: room number, floor, building, room type, status, smoking preference, bed type, features (child table linking `Room Feature`).

#### Room Type

Defines a category of rooms (e.g., Deluxe King, Suite). Linked to by Reservations and Rate Schedules.

#### Room Feature / Room Feature Item / Room Amenity / Amenity

Master data describing what a room offers (minibar, sea view, jacuzzi, etc.).

#### Room Out of Order

Records periods when a room is unavailable. Blocks the room on the Room Board.

#### Buildings

Groups floors and rooms by building for multi-building properties.

---

### Guest Profiles

#### Guest

The central guest identity record. Named by `guest_name` (unique).

**Tabs:**
- **Profile** — name, title, contact (phone, email), demographics (DOB, nationality, gender, VIP type), identification (type, number, expiry, front/back ID scans with preview panel), address, restricted flag + reason.
- **Preferences** — `Guest Preference` child table.
- **Traces** — `Guest Trace` child table (operational notes attached to a stay).
- **Notes** — `Guest Note` child table (persistent notes across stays).
- **Stay Statistics** — total stays, total nights, total revenue, last stay date (computed via `get_guest_stats` API on form load).

**ID Scan:** The "Scan ID Document" button opens a dialog to capture front and back of a passport or ID. Uses `frappe.ui.FileUploader` restricted to image/PDF. A live preview panel shows thumbnails of both sides.

#### Guest Trace

Operational per-stay notes linked to a guest (e.g., "Guest requested extra pillows").

#### Guest Note / Guest Preference

Persistent records for long-term guest intelligence.

---

### Rate & Revenue Management

#### Rate Type

Defines a named rate plan (e.g., BAR, Corporate, Package). Contains pricing columns and optional tax schedules.

#### Rate Schedule / Stay Rate Line

`Rate Schedule` groups multiple `Stay Rate Line` child rows. Each line defines a rate for a specific room type under a rate type, including discount tiers and a per-person pricing flag.

**Rate resolution logic** (in the Room Board check-in dialog and Reservation form):
1. Look up the rate for the selected room type + rate type combination.
2. Apply discounts (up to 3 discount tiers).
3. If `per_person_pricing` is enabled, multiply by adults.
4. Show `sell_message` badges (e.g., "Includes Breakfast", "Min 2 nights").

#### Rate Tax / Rate Tax Schedule

Defines tax rules (percentage or fixed) applied to rate lines. A `Rate Tax Schedule` groups multiple `Rate Tax` entries.

#### Market Code / Source Code / Business Source Category / Business Source Type / Hotel Market Segment

Master data for revenue segmentation — used to classify where business comes from (OTA, corporate, walk-in, group, etc.).

---

### Housekeeping

#### Housekeeping Task

An individual cleaning or servicing task assigned to a room. Fields: room, status (Pending / In Progress / Completed), task type, priority, assigned housekeeper, dates, actual start/end times, notes, instructions.

#### Housekeeper

Staff member assigned to housekeeping. Links to an ERPNext Employee.

#### Housekeeping Assignment

Groups tasks assigned to a housekeeper for a given shift.

**Custom Pages:**
- **Housekeeping Board** (`housekeeping-board`) — visual drag-and-drop board showing room cleaning status by section.
- **Room Discrepancies** (`room-discrepancies`) — flags mismatches between the PMS room status and the physical status reported by housekeeping.
- **Turndown** (`turndown`) — dedicated interface for managing turndown service requests across all occupied rooms.

---

### Maintenance

#### Maintenance Request

Logs a fault or maintenance need for a room or facility. Fields: room, category, description, priority, status, assigned technician, resolution notes.

#### Maintenance Category

Master data classifying maintenance types (Plumbing, Electrical, HVAC, Furniture, etc.).

**Custom Pages:**
- **Room Maintenance History** (`room-maintenance-history`) — timeline view of all maintenance events per room.

---

### Laundry

A complete laundry management sub-system for hotel guests and walk-in customers.

#### Data Model

```
Laundry Item          ← master catalog (item_code, guest_price, outsider_price)
Laundry Service Type  ← service tiers (Regular, Express, Same Day) with lead time + surcharge
Laundry Supplier      ← external laundry vendors
Laundry Settings      ← single-doc global config (accounts, SMS, PMS, auto-invoice)

Laundry Order         ← core transaction (submittable, series LAU-.YYYY.-)
  └── Laundry Order Item (child) ← per-piece lines (qty, rate, amount, status)

Supplier Batch        ← outsource batch (series VB-.YYYY.-)
  └── Supplier Batch Order (child) ← links to Laundry Orders in the batch
```

#### Laundry Order Lifecycle

```
Draft → Collected → Processing → Quality Check → Ready → Delivered
                                                            ↓
                                               (Posts charge to iHotel Profile folio)
                                               (Creates Sales Invoice if configured)
```

Status advance buttons appear contextually on the submitted form. Staff click **→ Processing**, **→ Quality Check**, etc. without touching the status field directly.

#### Outsourcing Flow

1. Select multiple `Collected + Outsourced` orders in the List View.
2. Click **Create Supplier Batch** from the menu.
3. A `Supplier Batch` is created, orders are linked, and their status advances to **Processing**.
4. When the batch returns from the vendor, record the supplier invoice number and amount.
5. The batch `mark_batch_returned` function sets individual orders to **Quality Check** and prepares the Purchase Invoice.

#### Folio Integration

When a `Laundry Order` for a hotel guest is delivered and `Post to Guest Folio` is checked, a charge row is automatically appended to the linked `iHotel Profile`.

#### Roles (Laundry-specific)

| Role | Capabilities |
|---|---|
| Laundry Manager | Full CRUD, submit, cancel, manage suppliers and settings |
| Laundry Supervisor | Create/edit orders, quality check, create batches |
| Laundry Staff | Create orders, update item statuses |

---

### Night Audit

#### Night Audit

The end-of-day financial reconciliation record. Captures daily revenue summaries, room revenue, taxes, payments, and occupancy statistics. Triggered manually or via the `night_audit_reminder` cron job at 23:00.

---

### Reporting

All reports are **Script Reports** (Python + SQL) accessible from the sidebar and the standard Frappe report runner.

| Report | DocType | Description |
|---|---|---|
| Occupancy Report | Checked In | Daily/monthly occupancy % and RevPAR |
| Guest History | Checked In | Full stay history for a guest |
| Arrivals And Departures | Checked In | Arrivals and departures for a date range |
| Revenue Report | Checked In | Revenue breakdown by room type, source, date |
| Daily Tax Report | Checked In | Tax collected per day |
| Outstanding Balance | iHotel Profile | Unpaid folios and outstanding amounts |
| Housekeeping Status | Housekeeping Task | Task completion rates by housekeeper |
| Maintenance Report | Maintenance Request | Open and resolved maintenance by category |
| Laundry Profitability | Laundry Order | Revenue vs. supplier cost, profit, margin % |
| Supplier Performance | Supplier Batch | Turnaround time, on-time %, damage rate, cost per supplier |

---

## DocType Reference

### Transactional (Submittable)

| DocType | Naming | Purpose |
|---|---|---|
| Reservation | `RES-.YYYY.-` | Pre-arrival booking |
| Checked In | By guest field | Active hotel stay |
| Group Reservation | `GRP-.YYYY.-` | Multi-room group booking |
| Laundry Order | `LAU-.YYYY.-` | Guest or walk-in laundry order |
| Supplier Batch | `VB-.YYYY.-` | Batch of orders sent to a laundry supplier |

### Operational Masters

| DocType | Purpose |
|---|---|
| Guest | Guest identity and stay history |
| Room | Physical room definition |
| Room Type | Room category (Deluxe, Suite, etc.) |
| Housekeeper | Staff member for housekeeping |
| iHotel Profile | Financial folio for a stay |
| Night Audit | Daily end-of-day reconciliation |

### Task / Event Records

| DocType | Purpose |
|---|---|
| Housekeeping Task | Individual cleaning task |
| Housekeeping Assignment | Task batch per housekeeper per shift |
| Maintenance Request | Fault / repair request |
| Laundry Item | Laundry item catalog entry |
| Laundry Supplier | External laundry vendor |
| Laundry Service Type | Service tier with lead time |

### Settings (Single DocTypes)

| DocType | Purpose |
|---|---|
| iHotel Settings | Global PMS configuration |
| Laundry Settings | Laundry module configuration |

### Child Tables

| DocType | Parent | Purpose |
|---|---|---|
| Stay Rate Line | Reservation, Checked In | Per-night rate rows |
| Stay Service Item | Checked In | Additional services on a stay |
| Folio Charge | iHotel Profile | Posted charges on a folio |
| Payment Items | iHotel Profile | Payments received against a folio |
| Laundry Order Item | Laundry Order | Per-piece laundry items |
| Supplier Batch Order | Supplier Batch | Orders included in a supplier batch |
| Group Room Assignment | Group Reservation | Individual room assignments in a group |
| Rate Tax | Rate Tax Schedule | Tax rule row |
| Guest Preference | Guest | Guest preference row |
| Guest Note | Guest | Persistent note on a guest |
| Guest Trace | Guest | Operational trace for a stay |
| Room Feature Item | Room | Feature linked to a room |
| Room Amenity | Room Type | Amenity linked to a room type |

### Reference Masters

| DocType | Purpose |
|---|---|
| Rate Type | Named rate plan |
| Rate Schedule | Groups rate lines |
| Rate Tax Schedule | Groups tax rules |
| Market Code | Revenue segmentation code |
| Source Code | Booking source code |
| Business Source Category | Business source grouping |
| Business Source Type | Type of business source |
| Business Channel Category | Distribution channel |
| Hotel Market Segment | Market segment master |
| Hotel Service | Chargeable hotel service |
| Room Feature | Room feature definition |
| Amenity | Amenity definition |
| Maintenance Category | Maintenance type definition |
| Buildings | Building master for multi-building properties |
| Room Out of Order | Out-of-order period for a room |
| Hotel Market Segment | Market segment for revenue analysis |
| Assignment Room | Room assignment reference |

---

## Custom Pages

Custom Frappe Desk pages provide interactive visual interfaces beyond standard list/form views.

| Page | Route | Purpose |
|---|---|---|
| My Dashboard | `/my-dashboard` | Personalised KPI dashboard for the logged-in user |
| Room Board | `/room-board` | Visual grid of all rooms with real-time status, drag-to-assign, quick check-in dialog |
| Rate Query | `/rate-query` | Interactive rate availability search by date range and room type |
| Turndown | `/turndown` | Manage turndown requests across all occupied rooms |
| Housekeeping Board | `/housekeeping-board` | Visual cleaning status board by room section |
| Room Discrepancies | `/room-discrepancies` | Flag and resolve PMS vs. physical room status mismatches |
| Room Maintenance History | `/room-maintenance-history` | Timeline of maintenance events per room |

### Room Board — Check-In Dialog

The Room Board quick check-in dialog collects:
- Guest (Link to Guest)
- Expected check-in / check-out (auto-calculates Nights)
- Rate Type (triggers rate auto-fill via `resolve_rate()`)
- Room Rate (pre-filled; shows rack rate, sell message badges, includes-breakfast flag)
- Adults / Children
- Business Source
- Deposit amount

On confirm, calls `room_board.quick_check_in` which creates the `Checked In` document server-side.

---

## Role & Permission Matrix

| Role | Reservation | Checked In | Guest | iHotel Profile | Housekeeping Task | Maintenance Request | Laundry Order | Laundry Supplier | Reports |
|---|---|---|---|---|---|---|---|---|---|
| System Manager | Full | Full | Full | Full | Full | Full | Full | Full | Full |
| General Manager | Full | Full | Full | Full | Full | Full | Full | Full | Full |
| Front Desk Agent | C/R/W | C/R/W/Submit/Cancel/Amend | C/R/W | R | R | C/R/W | R | — | R |
| Revenue Manager | R/Export | R/Export | R/Export | — | — | — | — | — | Full |
| Hotel Accountant | R/Export | R/Export | R/Export | R/Export | — | — | — | — | Full |
| Housekeeping Supervisor | R | R | R | — | Full | R | — | — | R |
| Laundry Manager | — | R | R | R | — | — | Full | Full | Full |
| Laundry Supervisor | — | R | R | — | — | — | C/R/W/Submit | R | R |
| Laundry Staff | — | — | — | — | — | — | C/R | — | — |

---

## Scheduled Tasks

Registered in `hooks.py` → `scheduler_events`.

| Frequency | Function | Description |
|---|---|---|
| Hourly | `ihotel.tasks.late_checkout_alert` | Notifies front desk of guests past expected checkout time |
| Daily | `ihotel.tasks.auto_no_show` | Marks reserved stays with no activity as No Show |
| Daily | `ihotel.tasks.auto_generate_housekeeping` | Creates Housekeeping Tasks for all occupied rooms each morning |
| Daily | `ihotel.tasks.send_birthday_notifications` | Sends birthday greetings to guests checking in on their birthday |
| 23:00 daily | `ihotel.tasks.night_audit_reminder` | Reminds the night auditor to run the Night Audit |

Document Events (registered in `hooks.py` → `doc_events`):

| Event | Function | Description |
|---|---|---|
| `Checked In` — `on_update_after_submit` | `ihotel.notifications.on_hotel_stay_update` | Fires notifications when DND, Make Up Room, or status changes on a submitted stay |

---

## Fixtures & Configuration

Fixtures in `hooks.py` export the following records with the app:

| DocType | Filter | Purpose |
|---|---|---|
| Business Source Type | module = ihotel | Seed data for source types |
| Business Channel Category | module = ihotel | Seed data for channel categories |
| Notification | name = "Reservation Confirmation Letter" | Email template sent on reservation save |
| Workspace Sidebar | name = "iHotel" | Full sidebar navigation definition |

To re-export fixtures after making sidebar or notification changes:

```bash
bench --site your-site.com export-fixtures --app ihotel
```

To apply fixtures on a new site after installation:

```bash
bench --site your-site.com migrate
# Fixtures are synced automatically during migrate
```

---

## Data Flow Diagrams

### Guest Stay Lifecycle

```
Reservation (created)
    │
    │  [Convert to Checked In]
    ▼
Checked In (Draft)
    │
    │  [Submit]
    ▼
Checked In (Submitted)  ──────────────────────► iHotel Profile (folio created)
    │                                                    │
    │  [Status → Checked In]                             │  Folio Charges appended by:
    │                                                    │  • Room rate (nightly)
    │  [Status → Checked Out]                            │  • Additional services
    │                                                    │  • Laundry orders
    ▼                                                    │
Sales Invoice (created) ◄────────────────────────────────┘
```

### Laundry Order Flow (Internal)

```
New Order (Draft)
    │ [Submit]
    ▼
Collected → Processing → Quality Check → Ready → Delivered
                                                      │
                                         ┌────────────┴────────────┐
                                         ▼                         ▼
                                  Post to Folio             Sales Invoice
                                (iHotel Profile)           (ERPNext SI)
```

### Laundry Order Flow (Outsourced)

```
Collected Orders (Outsourced)
    │ [Create Supplier Batch from List View]
    ▼
Supplier Batch (Pending Pickup)
    │ [Pickup]
    ▼
With Supplier
    │ [Return + Invoice]
    ▼
Returned → individual orders → Quality Check → Ready → Delivered
    │
    ▼
Purchase Invoice (ERPNext PI for supplier cost)
```

### Rate Resolution

```
Room Type + Rate Type selected
    │
    ▼
Look up Stay Rate Line
    │
    ├── Apply discount tier 1/2/3
    ├── If per_person_pricing: × adults
    ├── Apply service type surcharge (Laundry)
    └── Show sell_message badges
    │
    ▼
Room Rate field auto-filled
```

---

## Contributing

This app uses `pre-commit` for code formatting and linting.

```bash
cd apps/ihotel
pre-commit install
```

Tools configured:
- **ruff** — Python linting and formatting
- **eslint** — JavaScript linting
- **prettier** — JavaScript / JSON formatting
- **pyupgrade** — Python syntax modernisation

Branch naming: `feature/<name>`, `fix/<name>`, `chore/<name>`

---

## License

MIT
