# Working process

Every change travels the same path: **issue → branch → tests → PR → CI → dev → prod**.

1. **Specify.** Work starts from a GitHub issue with acceptance criteria
   (template: `.github/ISSUE_TEMPLATE/feature.md`). Functional details live in
   [specs.md](../specs.md); the issue links the relevant section.
2. **Branch.** `feat/<issue>-slug` or `fix/<issue>-slug` from `master`.
3. **Test first.** Write the failing test (unit for domain logic, integration for
   API behaviour), then the code. See [testing.md](testing.md).
4. **Run locally.** `make test`, and `make up` when the change touches the UI or Docker.
5. **Pull request.** Reference the issue (`Closes #N`), tick each acceptance criterion
   in the PR description. CI must be green (tests + frontend build).
6. **Review.** The reviewer agent (or a human) checks the diff against the acceptance
   criteria and the hard rules in [AGENTS.md](../AGENTS.md).
7. **Merge → dev.** Merging to `master` deploys automatically to the dev environment.
8. **Promote → production.** A human approves the `production` environment gate in
   GitHub Actions. See [deployment.md](deployment.md).
9. **Operate.** Alerts page the on-call agent ([oncall-agent.md](oncall-agent.md)).

## Definition of done

- Acceptance criteria in the issue are met and checked off
- Tests added/updated and green in CI
- No real data or secrets in the diff
- Docs updated if behaviour, commands or architecture changed
- Deployed to dev and smoke-checked (`/health`)

## Commit style

Short imperative subject, body explains *why*. Agent commits end with a
`Co-Authored-By` line naming the model.
