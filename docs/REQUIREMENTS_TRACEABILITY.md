# Foundation Traceability

| Requirement | Implementation |
|---|---|
| NFR-SEC-001 | Individual `users`, role membership, first-run administrator |
| NFR-SEC-002 | Argon2id password hashing |
| NFR-SEC-004 | User status and device revocation schema |
| NFR-SEC-006 | Configurable inactivity lock preserving open screen state |
| NFR-SEC-007 | Permission-filtered navigation and financial dashboard restriction |
| NFR-UX-001/002 | Labeled controls, visible focus styles, logical forms |
| NFR-UX-008 | Dark/orange default and light theme |
| FR-DASH-001 | Login load and configurable timed refresh |
| FR-DASH-002 | Metric cards emit drill-down route intent |
| FR-DASH-003 | Financial card checks `dashboard.financial` |
| NFR-SYNC-001/002 | UUID/version audit mixins and local sync queue schema |
| Windows Packaging | AppData mutable files, windowed PyInstaller build, official icon |

## Quote Builder v0.5.0

| Requirement | Implementation |
|---|---|
| FR-QUOTE-001 | Debounced live calculation updates charges, total, costs, profit, confidence, status, and warnings |
| FR-QUOTE-003 | Permission-controlled internal direct cost, profit, margin, and manual adjustments |
| FR-QUOTE-004 | Every automatic `ChargeLine` preserves rule ID and reason in UI, revision, and PDF data |
| FR-QUOTE-005/006 | Hazard, research, customer, contact, route, material, size/weight, readiness, and timing gates |
| FR-QUOTE-008 | Quote/revision audit metadata and immutable post-freeze revision creation |
| BR-PRICE-001–005 | Hazard, research dimensions, overweight, standard, and oversized classification |
| Section 16.2–16.6 | Oversized, PSL mileage, waiting, cancellation, loading, and calculation order |
| Appendix A A-001–A-040 | Automated threshold and rule matrix in `tests/test_pricing_engine.py` |
| NFR-PERF-003 | Pure calculation engine with 60 ms UI debounce and no provider/database dependency |
| NFR-MAINT-001 | Pricing engine independently testable without Qt, SQLite, maps, or internet |
| NFR-DATA-001 | Revision configuration, inputs, warnings, terms, charges, and generated PDF document links preserved |
