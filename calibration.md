| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| D (rules; 0.50 = not decidable by rules) | 511 | 0 | 29.9% | 0/0 | $0.00000 | 0 ms |
| L | 447 | 0 | 9.8% | 686/49 | $0.00013 | 1368 ms |
| F | 70 | 0 | 32.9% | 698/51 | $0.00042 | 2010 ms |

Calibration (stated confidence bucket -> observed accuracy):
- D: 0.95: 100% (n=153)
- L: 0.95: 64% (n=69)
- F: 0.85: 100% (n=4), 0.95: 41% (n=46)