# Headway Helm charts — stub

Helm/Kubernetes is a **first-class parallel target** for scale and gov-cloud
deployments, not a downstream generation of the Compose stack (ADR-0005).
Charts land here after the Compose stack in `deploy/compose/` is
live-verified (cold-start boot with green healthchecks, evidence recorded).

Commitments the charts must meet when they land:

- **Same artifacts.** Charts deploy the *identical image digests* the Compose
  stack runs — never a second image built for Kubernetes.
- **One config schema.** Helm `values` and Compose `env` both map onto the
  single documented configuration schema; no target-specific configuration
  surface.
- **Parity proven by CI.** The CI parity gate boots BOTH the Compose stack
  and a Helm/k3s stack and runs the identical smoke + health + migration
  suite against each, so drift is a red CI run, not a field incident.
