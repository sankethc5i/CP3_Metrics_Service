# Independent ground-truth arithmetic audit

No service/compiler/catalog formula/view is imported. SQL references are cross-checked against raw-record Python integer arithmetic.

All amounts below are integer cents; divide by 100 only for displayed USD.

Full snapshot: 12848275 gross - 917659 line discounts - 306157 order discounts - 627496 refunds = **10996963 net**.

Worked order `1` (completed):

| Line | Quantity × unit price | Line discount | Line total | Allocated order discount |
|---|---:|---:|---:|---:|
| 1 | 2 × 14226 | 4267 | 24185 | 1210 |
| 2 | 1 × 5572 | 557 | 5015 | 250 |

Order net: 29200 - 1460 - 0 = 27740 cents.
Allocation check: 1210 + 250 = 1460 cents.
Shipping 0 and tax 2219 are excluded.

All 6 category totals independently match the handwritten SQL, including allocation before category filtering.
The scalar and category cross-checks passed. This audit constructs/verifies reference data; it does not evaluate locked questions.
