# E2B sandbox image for the pricing agent: model-written Python and document builds.
#
# Ported from Kroolo's enterprise-fastapi e2b.Dockerfile. Model code used to run inside the
# API process; it now runs in a per-chat E2B microVM built from this image.
#
# Build (from backend/, with E2B_API_KEY set), then put the printed template id/name in
# E2B_TEMPLATE_ID on the web AND worker services:
#   npx @e2b/cli@2.19.1 template create priceiq-docgen --dockerfile e2b.Dockerfile \
#       --cpu-count 2 --memory-mb 4096
# Rebuilding under the same name keeps the template id. A docgen change without a rebuild
# still works (utils/docgen_runtime.py uploads the new docgen into each box), it is just
# ~2s slower on each fresh box.
FROM e2bdev/code-interpreter:latest

# ── system packages ──────────────────────────────────────────────────────────
# poppler-utils: pdftoppm (docx charts) and pdf2image for the pdf skill.
# libreoffice-*: docx/pptx layout verification (docgen/soffice.py) and the xlsx recalc
#   skill script. Component packages, not the metapackage, to keep the image small.
# fonts-dejavu-core: soffice needs a real font or PDF conversion draws boxes.
# qpdf, pdftk-java, pandoc, tesseract-ocr: CLI tools the pdf/docx skills tell the model
#   to run. The sandbox has no internet (E2B_ALLOW_INTERNET=false), so anything a skill
#   needs must be baked in here — it cannot be installed at runtime.
# nodejs/npm: only installed if the base image lacks them (it normally ships Node).
RUN apt-get update && apt-get install -y --no-install-recommends \
      poppler-utils \
      libreoffice-writer \
      libreoffice-impress \
      libreoffice-calc \
      fonts-dejavu-core \
      qpdf \
      pdftk-java \
      pandoc \
      tesseract-ocr \
      unzip \
      curl \
    && (command -v npm >/dev/null || apt-get install -y --no-install-recommends nodejs npm) \
    && rm -rf /var/lib/apt/lists/*

# ── python packages ──────────────────────────────────────────────────────────
# `python3 -m pip`, never bare `pip`: bare pip can bind to a different interpreter than
# the python3 that later runs our code.
RUN python3 -m pip install --no-cache-dir --break-system-packages \
      pdfplumber \
      pypdf \
      pypdfium2 \
      pdf2image \
      python-docx \
      openpyxl \
      xlrd \
      python-pptx \
      "reportlab>=4.4.7" \
      xlsxwriter \
      pandas \
      pydantic \
      matplotlib \
      pillow \
      lxml \
      defusedxml \
      pytesseract \
      "markitdown[pptx,docx,xlsx,pdf]"

# ── node packages (docx and pptx skills) ─────────────────────────────────────
# The docx skill builds documents with `require('docx')`, the pptx skill with
# `require('pptxgenjs')` plus react/react-dom/react-icons/sharp for icons. A global
# `npm -g` install is not on Node's require path for the sandbox user, and ENV
# (NODE_PATH) does not reach a running sandbox. So the modules go in /opt/priceiq/node
# and /home/user/node_modules points at them: scripts run from /home/user/out resolve
# `require()` by walking up to /home/user/node_modules.
RUN mkdir -p /opt/priceiq/node \
 && npm install --prefix /opt/priceiq/node --no-audit --no-fund \
      docx pptxgenjs react react-dom react-icons sharp \
 && mkdir -p /home/user \
 && ln -sfn /opt/priceiq/node/node_modules /home/user/node_modules \
 && chmod -R a+rX /opt/priceiq/node

# ── Inter ────────────────────────────────────────────────────────────────────
# The TTF release: apt's fonts-inter is OTF only, which reportlab cannot use and
# silently replaces with another face.
RUN mkdir -p /usr/share/fonts/truetype/inter \
 && curl -fsSL -o /tmp/inter.zip https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip \
 && echo "ff970a5d4561a04f102a7cb781adbd6ac4e9b6c460914c7a101f15acb7f7d1a4  /tmp/inter.zip" | sha256sum -c - \
 && unzip -j /tmp/inter.zip 'extras/ttf/Inter-Regular.ttf'      -d /usr/share/fonts/truetype/inter \
 && unzip -j /tmp/inter.zip 'extras/ttf/Inter-Bold.ttf'         -d /usr/share/fonts/truetype/inter \
 && unzip -j /tmp/inter.zip 'extras/ttf/Inter-Italic.ttf'       -d /usr/share/fonts/truetype/inter \
 && unzip -j /tmp/inter.zip 'extras/ttf/Inter-BoldItalic.ttf'   -d /usr/share/fonts/truetype/inter \
 && rm /tmp/inter.zip \
 && fc-cache -f

# ── PriceIQ code ─────────────────────────────────────────────────────────────
# docgen is the document component library; the runners are how the API drives it.
# /opt is read-only at runtime, so later repairs land under /home/user.
COPY docgen /opt/priceiq/docgen
COPY sandbox/runner.py sandbox/docgen_build.py /opt/priceiq/

# ENV does not reach a running E2B sandbox, so the import path is installed into the
# interpreter as a .pth file.
COPY sandbox/install_priceiq_path.py /tmp/install_priceiq_path.py
RUN python3 /tmp/install_priceiq_path.py && rm /tmp/install_priceiq_path.py

# ── LibreOffice profile, built once here ─────────────────────────────────────
# Otherwise the first conversion in each box boots soffice once just to create a
# profile (3-6s). Not /tmp: the image's /tmp doesn't survive into a running box.
# World-writable: the build runs as root, the sandbox as `user`.
RUN mkdir -p /opt/priceiq/lo-profile \
 && SAL_USE_VCLPLUGIN=svp soffice -env:UserInstallation=file:///opt/priceiq/lo-profile \
      --headless --terminate_after_init \
 && test -d /opt/priceiq/lo-profile/user/basic/Standard \
 && chmod -R a+rwX /opt/priceiq/lo-profile

# A fixed interpreter path: PATH differs between the root that ran pip and the runtime user.
RUN ln -sf "$(command -v python3)" /opt/priceiq/python

# Content hash of what is baked in, computed by the same function the API runs over its
# own checkout, so the API can tell when this image is older than its docgen.
RUN find /opt/priceiq/docgen -name __pycache__ -prune -exec rm -rf {} + || true
RUN python3 /opt/priceiq/docgen/staleness.py /opt/priceiq/docgen \
      /opt/priceiq/runner.py /opt/priceiq/docgen_build.py > /opt/priceiq/docgen.sha \
 && chmod -R a+rX /opt/priceiq \
 && chmod -R a+rwX /opt/priceiq/lo-profile

# ── build-time proof ─────────────────────────────────────────────────────────
# Fail the build, not a customer's document. `env -u PYTHONPATH` reproduces the real
# sandbox, where that variable is unset.
RUN env -u PYTHONPATH python3 -c "import pdfplumber, pypdf, pypdfium2, pdf2image, reportlab, docx, pptx, openpyxl, xlsxwriter, pydantic, pandas, matplotlib, PIL, lxml, defusedxml, pytesseract, markitdown" \
 && command -v qpdf && command -v pdftk && command -v pandoc && command -v tesseract && command -v pdftoppm \
 && cd /home/user && node -e "require('docx'); require('pptxgenjs'); require('react'); require('react-dom/server'); require('react-icons/fa'); require('sharp')" && cd / \
 && env -u PYTHONPATH python3 -c "import docgen.pdf, docgen.deck, docgen.word, docgen.book, docgen.checks" \
 && env -u PYTHONPATH python3 -c "from docgen import fonts; assert fonts.available(), 'Inter missing'" \
 && env -u PYTHONPATH python3 -c "from docgen import soffice; assert soffice.available(), 'soffice missing'" \
 && env -u PYTHONPATH python3 -c "from docgen import soffice; assert soffice.profile_ready(), 'LibreOffice profile missing'" \
 && env -u PYTHONPATH /opt/priceiq/python -c "import docgen.checks" \
 && test "$(cat /opt/priceiq/docgen.sha | wc -c)" -eq 17 \
 && chmod -R a+rwX /opt/priceiq/lo-profile
