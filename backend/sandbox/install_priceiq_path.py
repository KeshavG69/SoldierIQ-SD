"""Put /opt/priceiq on the interpreter's import path, at E2B template build time.

`ENV PYTHONPATH` in the Dockerfile does not reach a running E2B sandbox, so the
path goes into site-packages as a .pth file, which the interpreter reads itself.
"""

import pathlib
import sys
import sysconfig

ROOT = "/opt/priceiq"

site_packages = pathlib.Path(sysconfig.get_paths()["purelib"])
site_packages.mkdir(parents=True, exist_ok=True)
pth = site_packages / "priceiq.pth"
pth.write_text(ROOT + "\n")
print(f"wrote {pth} -> {ROOT}", file=sys.stderr)
