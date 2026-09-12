| class | calls | failures | accuracy | tokens in/out | measured cost per call | latency |
|---|---|---|---|---|---|---|
| D (rules; 0.50 = not decidable by rules) | 1717 | 0 | 99.2% | 0/0 | $0.00000 | 0 ms |
| L | 210 | 0 | 98.1% | 756/56 | $0.00015 | 1111 ms |
| S (STUB until a verification service is connected) | 76 | 0 | 18.4% | 0/0 | $0.00000 | 0 ms |
| F | 77 | 0 | 72.7% | 869/53 | $0.00051 | 1761 ms |

Calibration (stated confidence bucket -> observed accuracy):
- D: 0.50: 0% (n=3), 0.95: 99% (n=1714)
- L: 0.95: 98% (n=210)
- S: 0.00: 18% (n=76)
- F: 0.85: 56% (n=48), 0.90: 100% (n=5), 0.95: 100% (n=24)