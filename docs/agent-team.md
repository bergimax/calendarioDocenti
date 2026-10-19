# Agent team

The project is built and operated by a small team of specialised agents (Claude Code
sessions/sub-agents) supervised by one human maintainer, who owns priorities and
approves production deploys.

| Role | Responsibility | Inputs | Outputs | Must not |
|---|---|---|---|---|
| **Maintainer (human)** | Sets priorities, accepts issues, approves prod deploys | Ideas, user feedback | Issues, approvals | — |
| **Planner** | Turns a request into an issue with acceptance criteria; checks it against `specs.md` | Request, `specs.md` | GitHub issue (labels, criteria) | Write code |
| **Implementer** | Implements one issue, test first | Issue, `AGENTS.md`, docs | Branch + PR with `Closes #N` | Merge its own PR, touch unrelated code |
| **Tester** | Adds regression/integration tests, hunts edge cases, keeps `make test` green | Issue, diff | Tests, bug issues | Weaken a test to make it pass |
| **Reviewer** | Reviews the PR against acceptance criteria, hard rules, security (data leaks) | PR diff | Review comments, approve/request changes | Approve without CI green |
| **Release/Ops** | Maintains CI/CD, Docker, deploy scripts, observability stack | Issues labelled `ops` | Workflow/compose changes | Deploy to prod without the gate |
| **On-call agent** | Wakes on an alert, diagnoses with telemetry, opens a fix PR | Alert webhook payload, logs/traces | PR (or issue) with root cause and fix | Push to `master`, touch prod data, deploy |

## Handoffs

```
Planner ──issue──▶ Implementer ──PR──▶ Tester ──tests──▶ Reviewer ──approve──▶ Maintainer ──gate──▶ prod
                                                                           ▲
                                  On-call agent ──fix PR (same path)───────┘
```

- Handoffs happen through GitHub only (issue, PR, comments, labels), so the trail is
  public and auditable. Labels: `feature`, `bug`, `ops`, `docs`, `agent-fix`.
- An agent that is blocked writes the blocker in the issue and stops; it does not
  guess at product decisions (the maintainer decides).
- Agents read [AGENTS.md](../AGENTS.md) first and load only the docs they need.

## Evidence the team is used

Issues carry the acceptance criteria; commits and PRs reference them (`Closes #N`) and
agent commits carry a `Co-Authored-By` trailer. See `git log` and the closed issues.
