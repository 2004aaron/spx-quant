### A-KR3 sizing matrix: 4 account sizes x 2 margin types x 3 regimes

| net liq | margin | regime | outcome | best candidate | BP used | cap | delta:theta | worst case vs limit | violations |
|---|---|---|---|---|---|---|---|---|---|
| $25,000 | reg_t | low (VIX 14.5) | stand_down | no candidate passed the risk checks | - | $2,000 | - | - | 0 |
| $25,000 | reg_t | normal (VIX 17.5) | stand_down | no candidate passed the risk checks | - | $2,000 | - | - | 0 |
| $25,000 | reg_t | elevated (VIX 24.0) | stand_down | no candidate passed the risk checks | - | $2,000 | - | - | 0 |
| $25,000 | portfolio | low (VIX 14.5) | stand_down | no candidate passed the risk checks | - | $2,000 | - | - | 0 |
| $25,000 | portfolio | normal (VIX 17.5) | stand_down | no candidate passed the risk checks | - | $2,000 | - | - | 0 |
| $25,000 | portfolio | elevated (VIX 24.0) | stand_down | no candidate passed the risk checks | - | $2,000 | - | - | 0 |
| $75,000 | reg_t | low (VIX 14.5) | stand_down | no candidate passed the risk checks | - | $6,000 | - | - | 0 |
| $75,000 | reg_t | normal (VIX 17.5) | stand_down | no candidate passed the risk checks | - | $6,000 | - | - | 0 |
| $75,000 | reg_t | elevated (VIX 24.0) | stand_down | no candidate passed the risk checks | - | $6,000 | - | - | 0 |
| $75,000 | portfolio | low (VIX 14.5) | stand_down | no candidate passed the risk checks | - | $6,000 | - | - | 0 |
| $75,000 | portfolio | normal (VIX 17.5) | proposal | naked put XSP x1 | $5,701 | $6,000 | 1:9.5 | $3,770 of $7,500 | 0 |
| $75,000 | portfolio | elevated (VIX 24.0) | proposal | naked put XSP x1 | $3,680 | $6,000 | 1:19.3 | $2,880 of $7,500 | 0 |
| $150,000 | reg_t | low (VIX 14.5) | proposal | naked put XSP x1 | $7,896 | $12,000 | 1:7.0 | $4,255 of $15,000 | 0 |
| $150,000 | reg_t | normal (VIX 17.5) | proposal | naked put XSP x1 | $7,614 | $12,000 | 1:9.5 | $3,770 of $15,000 | 0 |
| $150,000 | reg_t | elevated (VIX 24.0) | proposal | naked put XSP x1 | $7,695 | $12,000 | 1:19.3 | $2,880 of $15,000 | 0 |
| $150,000 | portfolio | low (VIX 14.5) | proposal | naked put XSP x1 | $6,821 | $12,000 | 1:7.0 | $4,255 of $15,000 | 0 |
| $150,000 | portfolio | normal (VIX 17.5) | proposal | naked put XSP x2 | $11,403 | $12,000 | 1:9.5 | $7,540 of $15,000 | 0 |
| $150,000 | portfolio | elevated (VIX 24.0) | proposal | naked put XSP x3 | $11,041 | $12,000 | 1:19.3 | $8,639 of $15,000 | 0 |
| $1,500,000 | reg_t | low (VIX 14.5) | proposal | naked put SPX x1 | $78,964 | $120,000 | 1:7.0 | $42,549 of $150,000 | 0 |
| $1,500,000 | reg_t | normal (VIX 17.5) | proposal | naked put SPX x1 | $76,052 | $120,000 | 1:9.6 | $37,504 of $150,000 | 0 |
| $1,500,000 | reg_t | elevated (VIX 24.0) | proposal | naked put SPX x1 | $76,912 | $120,000 | 1:19.4 | $28,713 of $150,000 | 0 |
| $1,500,000 | portfolio | low (VIX 14.5) | proposal | naked put SPX x1 | $68,209 | $120,000 | 1:7.0 | $42,549 of $150,000 | 0 |
| $1,500,000 | portfolio | normal (VIX 17.5) | proposal | naked put SPX x2 | $113,320 | $120,000 | 1:9.6 | $75,009 of $150,000 | 0 |
| $1,500,000 | portfolio | elevated (VIX 24.0) | proposal | naked put SPX x3 | $109,967 | $120,000 | 1:19.4 | $86,140 of $150,000 | 0 |

**24 cases, 0 violations** of the BP cap or delta:theta limit across every ranked candidate (target 24 cases, 0 violations). Worst-case limit breaches: 0 (not part of the KR as written).
