# Publishing checklist

Everything in this folder is the repository root. Placeholders to confirm before publishing:
the GitHub owner/repo (`samclapp170/ha-leave-by`) appears in `manifest.json`, `README.md`
and the badges, and the codeowner in `manifest.json` is `@samclapp170`.

## 0. Move the workflow files

The two GitHub Actions files could not be written into `.github/` from here, so they are in
`github-workflows/`. Before your first push:

```bash
mkdir -p .github/workflows
mv github-workflows/*.yml .github/workflows/
rmdir github-workflows
```

## 1. First publish (installable as a HACS custom repository)

1. Create a **public** GitHub repo named `ha-leave-by`. Give it a description and a few
   topics (for example `home-assistant`, `hacs`, `integration`, `calendar`, `travel-time`).
2. Push this folder as the repo root.
3. In the repo's **Actions** tab, confirm the three checks pass: Hassfest, HACS, Tests.
   (They have not been run on GitHub yet. The tests have been run locally.)
4. Create a release: tag `v0.1.0` (must match `version` in `manifest.json`) and publish it.
   `release.yml` verifies the tag matches the manifest.
5. Install it yourself first: HACS → ⋮ → Custom repositories → add the repo as *Integration*.

## 2. Try it for real before wider release

Automated tests use mocked Google responses. Before telling others about it:

- Add it to your own Home Assistant and walk through the interview with a real API key.
- Make a calendar event ~1 hour out with a real address and check the countdown.
- Make one tagged `#transit` and check the departure time against Google Maps.
- Press **Send test alert** with your real lights and speakers.

## 3. Listing in the default HACS store (optional)

Submit a pull request to [hacs/default](https://github.com/hacs/default). The requirements
change over time, so follow the current
[HACS publishing docs](https://hacs.xyz/docs/publish/integration/). Typically you need a
public repo with description and topics, a GitHub release, and passing HACS and Hassfest
actions.

## Releasing later versions

1. Bump `version` in `custom_components/leave_by/manifest.json`.
2. Commit, tag `vX.Y.Z`, push the tag. The release workflow publishes it.
