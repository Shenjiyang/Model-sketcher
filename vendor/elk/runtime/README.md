# Bundled ELK runtime

This directory contains the `elk.bundled.js` CommonJS runtime from `elkjs`
0.12.0 so Model Sketcher can perform deterministic layout without downloading
npm dependencies at installation time.

- Upstream package: `elkjs@0.12.0`
- Runtime SHA-256: `1222e44f953ce7746af23801e723708f8e6f436b8b377a6a5fc7552f34a307b3`
- License: EPL-2.0 OR GPL-3.0-or-later; see `LICENSE.md`

When updating ELK, change the pinned npm dependency and lockfile, run `npm ci`,
copy the matching bundled runtime, package metadata, and license into this
directory, update the checksum above, and run the complete test suite.
