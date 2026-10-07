### A-KR3 sizing matrix: 4 account sizes x 2 margin types x 3 regimes

| net liq | margin | regime | outcome | best candidate | BP used | cap | delta:theta | worst case vs limit | violations |
|---|---|---|---|---|---|---|---|---|---|
| $100,000 | reg_t | low (VIX 14.5) | stand_down | no proposal could be sized for this account (reg_t, $8,000 p | - | $8,000 | - | - | 0 |
| $100,000 | reg_t | normal (VIX 17.5) | stand_down | no proposal could be sized for this account (reg_t, $8,000 p | - | $8,000 | - | - | 0 |
| $100,000 | reg_t | elevated (VIX 24.0) | stand_down | no proposal could be sized for this account (reg_t, $8,000 p | - | $8,000 | - | - | 0 |
| $100,000 | portfolio | low (VIX 14.5) | proposal | strangle XSP x1 | $6,583 | $8,000 | 1:509.8 | $4,064 of $5,000 | 0 |
| $100,000 | portfolio | normal (VIX 17.5) | proposal | strangle XSP x1 | $5,416 | $8,000 | 1:79.1 | $3,549 of $5,000 | 0 |
| $100,000 | portfolio | elevated (VIX 24.0) | proposal | strangle XSP x1 | $3,326 | $8,000 | 1:294.4 | $2,627 of $5,000 (cut from 2) | 0 |
| $150,000 | reg_t | low (VIX 14.5) | proposal | strangle XSP x1 | $8,734 | $12,000 | 1:509.8 | $4,064 of $7,500 | 0 |
| $150,000 | reg_t | normal (VIX 17.5) | proposal | strangle XSP x1 | $8,420 | $12,000 | 1:79.1 | $3,549 of $7,500 | 0 |
| $150,000 | reg_t | elevated (VIX 24.0) | proposal | strangle XSP x1 | $9,019 | $12,000 | 1:294.4 | $2,627 of $7,500 | 0 |
| $150,000 | portfolio | low (VIX 14.5) | proposal | strangle XSP x1 | $6,583 | $12,000 | 1:509.8 | $4,064 of $7,500 | 0 |
| $150,000 | portfolio | normal (VIX 17.5) | proposal | strangle XSP x2 | $10,831 | $12,000 | 1:79.1 | $7,098 of $7,500 | 0 |
| $150,000 | portfolio | elevated (VIX 24.0) | proposal | strangle XSP x2 | $6,653 | $12,000 | 1:294.4 | $5,254 of $7,500 (cut from 3) | 0 |
| $500,000 | reg_t | low (VIX 14.5) | proposal | strangle XSP x4 | $34,934 | $40,000 | 1:509.8 | $16,257 of $25,000 | 0 |
| $500,000 | reg_t | normal (VIX 17.5) | proposal | strangle XSP x4 | $33,678 | $40,000 | 1:79.1 | $14,196 of $25,000 | 0 |
| $500,000 | reg_t | elevated (VIX 24.0) | proposal | strangle XSP x4 | $36,076 | $40,000 | 1:294.4 | $10,509 of $25,000 | 0 |
| $500,000 | portfolio | low (VIX 14.5) | proposal | strangle XSP x6 | $39,499 | $40,000 | 1:509.8 | $24,386 of $25,000 | 0 |
| $500,000 | portfolio | normal (VIX 17.5) | proposal | strangle XSP x7 | $37,909 | $40,000 | 1:79.1 | $24,843 of $25,000 | 0 |
| $500,000 | portfolio | elevated (VIX 24.0) | proposal | strangle XSP x9 | $29,938 | $40,000 | 1:294.4 | $23,645 of $25,000 (cut from 12) | 0 |
| $1,500,000 | reg_t | low (VIX 14.5) | proposal | strangle SPX x1 | $87,341 | $120,000 | 1:509.7 | $40,643 of $75,000 | 0 |
| $1,500,000 | reg_t | normal (VIX 17.5) | proposal | strangle SPX x1 | $84,064 | $120,000 | 1:517.3 | $35,373 of $75,000 | 0 |
| $1,500,000 | reg_t | elevated (VIX 24.0) | proposal | strangle SPX x1 | $90,204 | $120,000 | 1:402.1 | $26,188 of $75,000 | 0 |
| $1,500,000 | portfolio | low (VIX 14.5) | proposal | strangle SPX x1 | $65,831 | $120,000 | 1:509.7 | $40,643 of $75,000 | 0 |
| $1,500,000 | portfolio | normal (VIX 17.5) | proposal | strangle SPX x2 | $107,793 | $120,000 | 1:517.3 | $70,746 of $75,000 | 0 |
| $1,500,000 | portfolio | elevated (VIX 24.0) | proposal | strangle SPX x2 | $66,233 | $120,000 | 1:402.1 | $52,377 of $75,000 (cut from 3) | 0 |

**24 cases, 0 violations** of the BP cap or delta:theta limit across every ranked candidate (target 24 cases, 0 violations). Worst-case limit breaches: 0 (not part of the KR as written).
