# Post-mortem: INC-1042

## Summary
Deploy (DEP-7781) preceded CPU/5xx alerts and error logs. On-call acknowledged; rollback was initiated and alerts resolved with recovery.

## Impact
- **User impact:** Elevated 5xx and latency during incident window.
- **Duration:** 31 minutes
- **Severity:** high

## Decision integrity artifacts

- DEP-7781
- RB-7781

## Timeline
| ts | kind | service | ref | summary |
| --- | --- | --- | --- | --- |
| 2026-02-10T09:58:00.000Z | chat | communication | CHAT-7781-1 | [CHAT] DEP-7781 ready for api-gateway v2.14.0 — can we deploy at 10am? |
| 2026-02-10T09:59:00.000Z | chat | communication | CHAT-7781-2 | [CHAT] Reminder: prod deploys need 2 explicit approvals and must be in change window. |
| 2026-02-10T10:00:00.000Z | chat | communication | CHAT-7781-4 | [CHAT] Starting deploy DEP-7781 now. |
| 2026-02-10T10:00:00.000Z | change | ci | DEP-7781 | [CHANGE] Deploy api-gateway v2.14.0 to prod (approvals 1/2, window=out_of_window, author=ops-alice) |
| 2026-02-10T10:00:00.000Z | chat | communication | CHAT-7781-3 | [CHAT] Proceed with caution — keep an eye on metrics. |
| 2026-02-10T10:02:00.000Z | log | api-gateway | E-101 | [LOG] Memory pressure increasing; GC frequency up |
| 2026-02-10T10:02:50.000Z | log | api-gateway | E-102 | [LOG] Heap usage above 80% |
| 2026-02-10T10:03:00.000Z | alert | monitoring | ALT-CPU-1042 | [ALERT] api-gateway pool CPU 94% for 5m |
| 2026-02-10T10:03:15.000Z | log | api-gateway | E-103 | [LOG] Upstream timeouts from auth-service |
| 2026-02-10T10:03:40.000Z | log | api-gateway | E-104 | [LOG] Retry backoff for auth-service |
| 2026-02-10T10:04:00.000Z | chat | communication | CHAT-7781-5 | [CHAT] Acknowledged — investigating CPU and 5xx alerts. |
| 2026-02-10T10:04:00.000Z | alert | monitoring | ALT-5XX-1042 | [ALERT] 5xx rate 12% on api-gateway |
| 2026-02-10T10:04:10.000Z | log | api-gateway | E-105 | [LOG] 5xx errors spiking; returning 503 from multiple routes |
| 2026-02-10T10:05:30.000Z | log | api-gateway | E-106 | [LOG] Circuit breaker open for auth-service |
| 2026-02-10T10:25:00.000Z | ticket | incident | TKT-1042 | INC-1042: Production 5xx after DEP-7781 |
| 2026-02-10T10:27:00.000Z | ticket | ci | TKT-ROLLBACK-7781 | Rollback DEP-7781 api-gateway |
| 2026-02-10T10:27:00.000Z | change | ci | RB-7781 | [CHANGE] Rollback api-gateway to v2.13.2 |
| 2026-02-10T10:27:00.000Z | chat | communication | CHAT-7781-6 | [CHAT] Initiating rollback DEP-7781. |
| 2026-02-10T10:29:00.000Z | alert | monitoring | ALT-CPU-1042-RESOLVED | [ALERT] api-gateway pool CPU back to normal after rollback |
| 2026-02-10T10:29:00.000Z | alert | monitoring | ALT-5XX-1042-RESOLVED | [ALERT] 5xx rate normalized post-rollback |

## Claims
| claim_id | statement | evidence_refs | confidence |
| --- | --- | --- | --- |
| CLM-001 | Deploy started within the incident window. | DEP-7781 | 0.88 |
| CLM-002 | Alerts fired during the incident. | ALT-CPU-1042, ALT-5XX-1042 | 0.9 |
| CLM-003 | Error logs indicated 5xx and circuit issues. | E-105, E-106 | 0.85 |
| CLM-004 | On-call acknowledged and investigated. | CHAT-7781-5 | 0.82 |
| CLM-005 | Rollback was initiated. | RB-7781, CHAT-7781-6 | 0.87 |
| CLM-006 | Alerts resolved and service recovered. | ALT-CPU-1042-RESOLVED, ALT-5XX-1042-RESOLVED | 0.85 |

## Follow-ups
| action | owner_role | priority | evidence_refs |
| --- | --- | --- | --- |
| Post-mortem and approval policy review. | sre | high | DEP-7781 |
| Verify monitoring and rollback runbooks. | oncall | medium | ALT-CPU-1042 |