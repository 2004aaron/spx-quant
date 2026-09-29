### A-KR3 sizing matrix: 4 account sizes x 2 margin types x 3 regimes

| net liq | margin | regime | outcome | best candidate | BP used | cap | delta:theta | violations |
|---|---|---|---|---|---|---|---|---|
| $25,000 | reg_t | low (VIX 14.5) | stand_down | no candidate passed the risk checks | - | $2,000 | - | 0 |
| $25,000 | reg_t | normal (VIX 17.5) | stand_down | no candidate passed the risk checks | - | $2,000 | - | 0 |
| $25,000 | reg_t | elevated (VIX 24.0) | stand_down | no candidate passed the risk checks | - | $2,000 | - | 0 |
| $25,000 | portfolio | low (VIX 14.5) | stand_down | no candidate passed the risk checks | - | $2,000 | - | 0 |
| $25,000 | portfolio | normal (VIX 17.5) | proposal | naked put XSP x1 | $1,977 | $2,000 | 1:9.5 | 0 |
| $25,000 | portfolio | elevated (VIX 24.0) | proposal | strangle XSP x1 | $1,093 | $2,000 | 1:2944.0 | 0 |
| $75,000 | reg_t | low (VIX 14.5) | stand_down | no candidate passed the risk checks | - | $6,000 | - | 0 |
| $75,000 | reg_t | normal (VIX 17.5) | stand_down | no candidate passed the risk checks | - | $6,000 | - | 0 |
| $75,000 | reg_t | elevated (VIX 24.0) | stand_down | no candidate passed the risk checks | - | $6,000 | - | 0 |
| $75,000 | portfolio | low (VIX 14.5) | proposal | naked put XSP x2 | $4,733 | $6,000 | 1:7.0 | 0 |
| $75,000 | portfolio | normal (VIX 17.5) | proposal | naked put XSP x3 | $5,930 | $6,000 | 1:9.5 | 0 |
| $75,000 | portfolio | elevated (VIX 24.0) | proposal | strangle XSP x5 | $5,463 | $6,000 | 1:2944.0 | 0 |
| $150,000 | reg_t | low (VIX 14.5) | proposal | naked put XSP x1 | $7,896 | $12,000 | 1:7.0 | 0 |
| $150,000 | reg_t | normal (VIX 17.5) | proposal | naked put XSP x1 | $7,614 | $12,000 | 1:9.5 | 0 |
| $150,000 | reg_t | elevated (VIX 24.0) | proposal | naked put XSP x1 | $7,695 | $12,000 | 1:19.3 | 0 |
| $150,000 | portfolio | low (VIX 14.5) | proposal | naked put XSP x5 | $11,831 | $12,000 | 1:7.0 | 0 |
| $150,000 | portfolio | normal (VIX 17.5) | proposal | naked put XSP x6 | $11,860 | $12,000 | 1:9.5 | 0 |
| $150,000 | portfolio | elevated (VIX 24.0) | proposal | strangle SPX x1 | $10,874 | $12,000 | 1:4021.5 | 0 |
| $1,500,000 | reg_t | low (VIX 14.5) | proposal | naked put SPX x1 | $78,964 | $120,000 | 1:7.0 | 0 |
| $1,500,000 | reg_t | normal (VIX 17.5) | proposal | naked put SPX x1 | $76,052 | $120,000 | 1:9.6 | 0 |
| $1,500,000 | reg_t | elevated (VIX 24.0) | proposal | naked put SPX x1 | $76,912 | $120,000 | 1:19.4 | 0 |
| $1,500,000 | portfolio | low (VIX 14.5) | proposal | naked put SPX x5 | $118,314 | $120,000 | 1:7.0 | 0 |
| $1,500,000 | portfolio | normal (VIX 17.5) | proposal | naked put SPX x6 | $117,663 | $120,000 | 1:9.6 | 0 |
| $1,500,000 | portfolio | elevated (VIX 24.0) | proposal | strangle SPX x11 | $119,617 | $120,000 | 1:4021.5 | 0 |

**24 cases, 0 violations** across every ranked candidate (target 24 cases, 0 violations).
