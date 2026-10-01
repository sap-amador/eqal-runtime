| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| D (rules; 0.50 = not decidable by rules) | 492 | 0 | 51.2% | 0/0 | $0.00000 | 0 ms |
| L | 447 | 0 | 54.8% | 669/56 | $0.00013 | 1441 ms |
| F | 106 | 0 | 73.6% | 673/50 | $0.00041 | 2340 ms |

Calibration (stated confidence bucket -> observed accuracy):
- D: 0.50: 29% (n=339), 0.95: 100% (n=153)
- L: 0.95: 55% (n=447)
- F: 0.85: 76% (n=38), 0.95: 72% (n=68)