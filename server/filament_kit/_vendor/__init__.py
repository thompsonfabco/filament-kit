"""Third-party code, vendored unchanged (see VENDORED.txt and THIRD-PARTY.md). Their modules import each other by their
own top-level name, so this folder goes first on the import path: `import segno` finds the vendored copy."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
