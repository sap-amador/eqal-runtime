| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| L | 352 | 0 | 100.0% | 573/62 | $0.00012 | 1414 ms |
| D (rules; 0.50 = not decidable by rules) | 1526 | 0 | 99.4% | 0/0 | $0.00000 | 0 ms |
| S (STUB until a verification service is connected) | 122 | 0 | 21.3% | 0/0 | $0.00000 | 0 ms |
| F | 122 | 0 | 71.3% | 701/51 | $0.00043 | 2027 ms |

Calibration (stated confidence bucket -> observed accuracy):
- L: 0.95: 100% (n=352)
- D: 0.95: 99% (n=1526)
- S: 0.00: 21% (n=122)
- F: 0.55: 65% (n=100), 0.95: 100% (n=22)