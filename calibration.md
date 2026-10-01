| class | calls | judged | failures | accuracy (judged) | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|---|
| D (rules; 0.50 = not decidable by rules) | 142 | 98 | 0 | 91.8% | 0/0 | $0.00000 | 0 ms |
| L | 112 | 104 | 0 | 83.7% | 840/55 | $0.00016 | 1416 ms |
| F | 45 | 37 | 0 | 48.6% | 838/54 | $0.00050 | 2019 ms |

Calibration (stated confidence bucket -> observed accuracy):
- D: 0.50: 92% (n=88), 0.95: 90% (n=10)
- L: 0.95: 84% (n=104)
- F: 0.85: 50% (n=12), 0.95: 48% (n=25)