# Third-party notices

APEIR Distribution is licensed under Apache License 2.0. It uses third-party
packages under their own licenses.

The authoritative dependency sets for this source release are:

- Python: `pyproject.toml`
- Desktop JavaScript: `desktop/package-lock.json`
- Desktop Rust: `desktop/src-tauri/Cargo.lock`
- Kernel binaries: `runtime-components.lock.json`

Release archives include a generated dependency-license report and CycloneDX
SBOM. Those generated files are evidence for that exact archive and are kept
outside the source repository. Redistributors must retain all notices required
by the dependency licenses included in their build.

## FlexLayout — bundled Studio presentation dependency

`flexlayout-react` 0.11.1, https://github.com/caplin/FlexLayout, MIT.
The following notice is retained from the version-pinned package's LICENSE.

MIT License

Copyright (c) 2017 Caplin Systems Ltd

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Playwright — development tests only

`@playwright/test` 1.64.1 and its browser-testing libraries are Apache-2.0.
Their pinned package licenses are installed with the development dependencies;
they are not imported into the Studio application bundle. Browser downloads are
test prerequisites, not Runtime or Kernel components.

