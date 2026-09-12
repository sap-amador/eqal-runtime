| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| D | 260 | 0 | 94.2% | 0/0 | $0.00000 | 0 ms |
| L | 39 | 0 | 97.4% | 465/20 | $0.00008 | 2 ms |
| F | 40 | 0 | 97.5% | 530/20 | $0.00030 | 1 ms |
| S | 11 | 0 | 18.2% | 0/0 | $0.00000 | 0 ms |

Calibration (stated confidence bucket -> observed accuracy):
- D: 0.50: 0% (n=10), 0.95: 98% (n=250)
- L: 0.85: 100% (n=21), 0.95: 94% (n=18)
- F: 0.70: 0% (n=1), 0.85: 100% (n=21), 0.90: 100% (n=10), 0.95: 100% (n=8)
- S: 0.00: 18% (n=11)