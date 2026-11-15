# Allow-lists

One folder per list, one file per source file the list names (aut5_hub: one per Hub section, aut5: one per web app
screen). A line goes in the file named for its source: `<path with / as __>.txt` (the file `a/b.js` is `a__b.js.txt`),
so two branches that change different source files never change the same file. Lines are sorted (plain byte order)
inside each file, without comments or blank lines; the format of each list is in its folder's README.md.

A new line: create the file if it is not there, add the line, keep the file sorted. Dropping the last line of a file:
delete the file. `tests/test_allowlist_files.py` fails on an unsorted file, a duplicate line, a line in the wrong file,
a CR, or an old single-file `tests/*_allowlist.txt`.
