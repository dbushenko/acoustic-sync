# Local validation report

Recorded 2026-09-10. This summarizes the completed local test and browser QA results, plus saved sample and benchmark artifacts.

| Check | Result |
| --- | --- |
| Full automated suite | 145 passed, plus 28 passing subtests |
| Warnings | Two upstream deprecation warnings involving Starlette/httpx and AnyIO |
| Dependency/package checks | `pip check`, exact dependency closure, distribution build and package-asset checks passed |
| Release contents | Sdist includes docs, scripts, requirements, tests and assets; wheel includes application package and metadata only |
| Windows installer | Dev profile succeeded using the project-local Python and existing venv; no system provisioning requested |
| macOS/Linux installers | Syntax checked only; not executed |
| Documentation | ASCII-compatible UTF-8, local links and launcher/CLI port consistency checked |

## Browser QA

The local UI at [127.0.0.1:8765](http://127.0.0.1:8765) was active at validation. A browser-submitted job processed all 13 sample sources with rational FPS `30000/1001` and finished with the correct `PARTIAL` status. The page showed eight accepted match edges, two groups and four recordings needing review. Tables displayed nine aligned clips and four orphans; five download links were visible. Screenshot inspection confirmed readable UI text. Link visibility does not establish that every download was opened or imported.

## Sample and benchmark

The saved full-pipeline sample report records all 13 media preserved, nine aligned in two groups, four orphans, approximately 4.39 seconds elapsed, three video tracks and eight audio tracks. Structural XML validation passed. All original audio channels are exported enabled. See [sample details](premiere-validation.md) for orphan names and reasons.

The separate matching-only benchmark used 100 eight-second deterministic mono sources and produced 20 groups with zero unmatched sources in 7.156 seconds, at 140.18 MiB peak RSS. It excludes extraction and XML export; see [benchmark scope](development.md).

## Scope limits

These results validate local execution, not deployment or the six-platform/Python CI matrix. Clean-machine setup and winget/Homebrew/apt provisioning remain unverified. Actual Adobe Premiere import and manual channel/timing validation have not been performed. The supplied XML is a structural reference only; its offsets differ from the acoustic results and are not timing ground truth.
