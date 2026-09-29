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
| $75,000 | portfolio | low (VIX 14.5) | proposal | naked put XSP x1 | $2,366 | $6,000 | 1:7.0 | $4,255 of $7,500 (cut from 2) | 0 |
| $75,000 | portfolio | normal (VIX 17.5) | proposal | naked put XSP x1 | $1,977 | $6,000 | 1:9.5 | $3,770 of $7,500 (cut from 3) | 0 |
| $75,000 | portfolio | elevated (VIX 24.0) | proposal | strangle XSP x2 | $2,185 | $6,000 | 1:2944.0 | $5,254 of $7,500 (cut from 5) | 0 |
| $150,000 | reg_t | low (VIX 14.5) | proposal | naked put XSP x1 | $7,896 | $12,000 | 1:7.0 | $4,255 of $15,000 | 0 |
| $150,000 | reg_t | normal (VIX 17.5) | proposal | naked put XSP x1 | $7,614 | $12,000 | 1:9.5 | $3,770 of $15,000 | 0 |
| $150,000 | reg_t | elevated (VIX 24.0) | proposal | naked put XSP x1 | $7,695 | $12,000 | 1:19.3 | $2,880 of $15,000 | 0 |
| $150,000 | portfolio | low (VIX 14.5) | proposal | naked put XSP x3 | $7,099 | $12,000 | 1:7.0 | $12,765 of $15,000 (cut from 5) | 0 |
| $150,000 | portfolio | normal (VIX 17.5) | proposal | naked put XSP x3 | $5,930 | $12,000 | 1:9.5 | $11,310 of $15,000 (cut from 6) | 0 |
| $150,000 | portfolio | elevated (VIX 24.0) | proposal | strangle XSP x5 | $5,463 | $12,000 | 1:2944.0 | $13,136 of $15,000 (cut from 10) | 0 |
| $1,500,000 | reg_t | low (VIX 14.5) | proposal | naked put SPX x1 | $78,964 | $120,000 | 1:7.0 | $42,549 of $150,000 | 0 |
| $1,500,000 | reg_t | normal (VIX 17.5) | proposal | naked put SPX x1 | $76,052 | $120,000 | 1:9.6 | $37,504 of $150,000 | 0 |
| $1,500,000 | reg_t | elevated (VIX 24.0) | proposal | naked put SPX x1 | $76,912 | $120,000 | 1:19.4 | $28,713 of $150,000 | 0 |
| $1,500,000 | portfolio | low (VIX 14.5) | proposal | naked put SPX x3 | $70,988 | $120,000 | 1:7.0 | $127,646 of $150,000 (cut from 5) | 0 |
| $1,500,000 | portfolio | normal (VIX 17.5) | proposal | naked put SPX x3 | $58,831 | $120,000 | 1:9.6 | $112,513 of $150,000 (cut from 6) | 0 |
| $1,500,000 | portfolio | elevated (VIX 24.0) | proposal | strangle SPX x5 | $54,371 | $120,000 | 1:4021.5 | $130,941 of $150,000 (cut from 11) | 0 |

**24 cases, 0 violations** of the BP cap or delta:theta limit across every ranked candidate (target 24 cases, 0 violations). Worst-case limit breaches: 0 (not part of the KR as written).
