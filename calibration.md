| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| D (rules; 0.50 = not decidable by rules) | 1717 | 0 | 87.5% | 0/0 | $0.00000 | 0 ms |
| L | 410 | 0 | 50.2% | 644/44 | $0.00012 | 1274 ms |
| S (STUB until a verification service is connected) | 76 | 0 | 18.4% | 0/0 | $0.00000 | 0 ms |
| F | 78 | 0 | 73.1% | 863/52 | $0.00051 | 1910 ms |

Calibration (stated confidence bucket -> observed accuracy):
- D: 0.50: 0% (n=203), 0.95: 99% (n=1514)
- L: 0.95: 50% (n=410)
- S: 0.00: 18% (n=76)
- F: 0.85: 60% (n=53), 0.90: 100% (n=7), 0.95: 100% (n=18)