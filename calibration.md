| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| D (rules; 0.50 = not decidable by rules) | 429 | 0 | 98.8% | 0/0 | $0.00000 | 0 ms |
| L | 54 | 0 | 100.0% | 730/55 | $0.00014 | 788 ms |
| S (STUB until a verification service is connected) | 17 | 0 | 23.5% | 0/0 | $0.00000 | 0 ms |
| F | 18 | 0 | 77.8% | 874/51 | $0.00051 | 1349 ms |

Calibration (stated confidence bucket -> observed accuracy):
- D: 0.95: 99% (n=429)
- L: 0.95: 100% (n=54)
- S: 0.00: 24% (n=17)
- F: 0.85: 56% (n=9), 0.90: 100% (n=1), 0.95: 100% (n=8)