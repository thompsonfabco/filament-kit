```
# AUT-5 findings on the Hub page that a later step removes (tests/aut5_run.mjs --allow). One line each:
#   <view> | <check> | <where, as the audit prints it> | <count> | <reason: the step that removes that markup>
# <view> is the section the finding is in: the same finding in another section is not covered, so it fails. <count> is
# how often the finding appears in the test's whole run (10 sections x 1280/320 x light/dark = 40 passes, so a visible
# finding counts 4): a run that finds it more often fails, and one that finds it less often fails as stale, so a rebuilt
# section has to lower or drop its lines (09 S1.11). The Hub page's selectors are generic (div.row > input), so the same
# selector appears under several sections. The audit also reads the fields of hidden regions. S1.11 changes no shipped
# file; the Hub page steps S2.x rebuild each section on the shared components (labelled fields, 44 px controls) and
# delete their lines.
```
