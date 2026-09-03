# Third-party notices

This project pins the direct dependencies below for the Windows desktop build. The
table records the upstream license and the packaging checks required before a
redistributable installer is published. It is not a claim that license texts are
already present in the installer.

| Dependency (pinned) | License | Official homepage | Binary/model data bundled? | Redistributed-license path / requirement |
| --- | --- | --- | --- | --- |
| [pywebview](https://github.com/r0x0r/pywebview) 6.2.1 | BSD-3-Clause | [pywebview.org](https://pywebview.flowrl.com/) | No project model; runtime uses the selected Windows webview | Include the pywebview BSD-3-Clause text and copyright notice in the installer notices. |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) 5.13.0 | Apache-2.0 OR BSD-3-Clause | [pypdfium2 docs](https://pypdfium2.readthedocs.io/) | Yes: wheels can carry native PDFium binaries; PDFium is separately licensed under BSD-3-Clause | Preserve pypdfium2 Apache-2.0 OR BSD-3-Clause terms and the PDFium BSD-3-Clause notice. Audit the wheel's bundled PDFium license files and copy the wheel's bundled PDFium license files to `THIRD_PARTY_NOTICES/` at packaging time. |
| [python-docx](https://github.com/python-openxml/python-docx) 1.2.0 | MIT | [python-docx docs](https://python-docx.readthedocs.io/) | No | Include the python-docx MIT text and copyright notice. |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) 3.9.2 | Apache-2.0 | [RapidOCR docs](https://rapidai.github.io/RapidOCRdocs/) | Yes: OCR model assets are part of the RapidOCR distribution/runtime model set | Include RapidOCR Apache-2.0 terms and retain notices for every redistributed model asset; record the exact model files in the build manifest. |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) 1.29.0 | MIT | [onnxruntime.ai](https://onnxruntime.ai/) | Yes: wheels contain native runtime binaries | Include ONNX Runtime MIT text and copyright notice; retain any notices shipped in the wheel. |
| [Pillow](https://github.com/python-pillow/Pillow) 12.3.0 | HPND (Pillow license) | [python-pillow.org](https://python-pillow.org/) | Yes: wheels may contain compiled image-codec extensions | Include Pillow's license text and copyright notice, plus notices for any codecs actually redistributed. |
| [httpx](https://github.com/encode/httpx) 0.28.1 | BSD-3-Clause | [httpx docs](https://www.python-httpx.org/) | No | Include the HTTPX BSD-3-Clause text and copyright notice. |
| [keyring](https://github.com/jaraco/keyring) 25.7.0 | MIT | [keyring docs](https://keyring.readthedocs.io/) | No project model; backend selection may use installed OS components | Include keyring's MIT text and copyright notice. |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) 3.1.5 | MIT | [openpyxl docs](https://openpyxl.readthedocs.io/) | No | Include openpyxl's MIT text and copyright notice. |
| [matplotlib](https://github.com/matplotlib/matplotlib) 3.11.1 | Matplotlib license (PSF-compatible) | [matplotlib.org](https://matplotlib.org/) | Yes: wheels include compiled extensions; font data may be redistributed | Include Matplotlib's license and third-party notices, and audit bundled font licenses before release. |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) 6.22.2 | GPL-2.0-or-later (bootloader exception) | [pyinstaller.org](https://pyinstaller.org/) | Yes: the bootloader is a native binary included in the packaged app | Include PyInstaller's license and bootloader exception; retain its license files in the build notices directory. |
| [ReportLab](https://github.com/py-pdf/reportlab) 5.0.1 | BSD-3-Clause | [reportlab.com](https://www.reportlab.com/) | No required model; may include compiled extensions depending on wheel | Include ReportLab's BSD-3-Clause text and audit any bundled fonts or optional assets. |

## Packaging boundary

The build must generate a license bundle from the exact installed wheels, not from
this table alone. Before distribution, copy each dependency's license and required
copyright/NOTICE files into `THIRD_PARTY_NOTICES/`, include licenses for native
PDFium, ONNX Runtime, PyInstaller bootloader, OCR models, and fonts/codecs, and
record the source wheel hashes in the release manifest. Do not add PyMuPDF or
`fitz` to the desktop runtime dependency set.
