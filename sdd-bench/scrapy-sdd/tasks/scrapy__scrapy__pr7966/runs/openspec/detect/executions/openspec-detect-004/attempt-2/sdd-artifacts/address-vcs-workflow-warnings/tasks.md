## 1. Warning inventory

- [ ] 1.1 Collect the warnings reported by the "VCS dependencies" workflow on the current base.
- [ ] 1.2 Classify each warning as Scrapy/test code, dependency internal, or environment noise.
- [ ] 1.3 Map dependency-internal warnings to the narrowest emitting test module or shared test base.

## 2. Fix avoidable warnings

- [ ] 2.1 Update deprecated dependency API calls in downloader/TLS and certificate-handling code or tests.
- [ ] 2.2 Preserve compatibility gates for older supported dependency releases.
- [ ] 2.3 Add targeted warning filters with explanatory comments only for warnings that cannot be avoided yet.

## 3. Verification

- [ ] 3.1 Run the candidate test modules identified in `detection-draft.json` with warnings enabled.
- [ ] 3.2 Run the affected download-handler matrix, including HTTP/1.1, HTTP/2, and httpx where available.
- [ ] 3.3 Confirm the VCS workflow completes without new warning entries tied to Scrapy.
- [ ] 3.4 Confirm no public behavior, settings, or stable/minimum test expectations changed.
