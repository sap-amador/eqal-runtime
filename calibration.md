| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| L | 630 | 0 | 54.4% | 537/49 | $0.00011 | 1237 ms |
| F | 474 | 0 | 92.4% | 592/45 | $0.00036 | 1712 ms |
| D (rules; 0.50 = not decidable by rules) | 1526 | 0 | 81.6% | 0/0 | $0.00000 | 0 ms |
| S (STUB until a verification service is connected) | 122 | 0 | 21.3% | 0/0 | $0.00000 | 0 ms |

Calibration (stated confidence bucket -> observed accuracy):
- L: 0.50: 54% (n=630)
- F: 0.60: 64% (n=100), 0.95: 100% (n=374)
- D: 0.50: 1% (n=278), 0.95: 100% (n=1248)
- S: 0.00: 21% (n=122)