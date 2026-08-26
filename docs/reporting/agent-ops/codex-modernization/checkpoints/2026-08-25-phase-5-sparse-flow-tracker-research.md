# Phase 5 Sparse Flow Tracker Research

Date: 2026-08-25

Issue: PXE-0158

Status: research decision complete; implementation and target evidence pending

## Scope

- Inspect the operator-supplied Teravolt screen recording without treating a
  promotional reel as source-code or performance proof.
- Identify the most defensible published algorithm family.
- Map a candidate onto PixEagle's current tracker, estimator, loss, recovery,
  and follower-safety contracts.
- Define evidence gates before implementation is exposed to operators.

## Findings

- Visible `MedianFlowTracker`, `fbErrorMaxPx`, point-count, confidence, and
  `revalidated` labels support a custom classic sparse optical-flow design with
  forward-backward validation.
- Public Teravolt material reports an ARM/global-shutter high-rate path but does
  not publish the tracker implementation. AI detection, sensor fusion, and the
  meaning of `revalidated` are not established by available evidence.
- Published MedianFlow and OpenCV primitives provide a reproducible starting
  point. Long-term recovery still requires PixEagle's estimator/search and
  detector-assisted re-detection boundary.
- PixEagle's Core OpenCV provider already contains the required primitives, so
  the first candidate should not add a package or setup prompt.

## Decision

Track a `SparseFlow` candidate built from maintained OpenCV primitives. Keep it
behind development/benchmark gates until it passes deterministic, aerial-media,
cadence, target-hardware, and follower-ineligibility acceptance. Do not ship a
thin wrapper around the legacy MedianFlow API and do not add tracker-local
prediction or recovery policy.

The detailed design and source record is in
`docs/trackers/05-development/sparse-flow-tracker-proposal.md`.

## Validation

```text
documentation, API inventory, and parameter reload
104 passed

schema
39 sections / 518 parameters, current

git diff --check
passed
```

No runtime code, dependency, configuration, schema, PX4 path, or flight-control
behavior changed in this slice.

## Risks And Open Inputs

- A polished screen recording cannot prove accuracy, latency, failure behavior,
  or parity.
- Original media, camera/capture details, target hardware, annotations, and
  representative failure cases are needed from the customer.
- PXE-0131 cadence-independent recovery work and the benchmark harness should
  precede any production-quality claim.

## Next Slice

Build the offline comparison harness and deterministic fixtures first. Implement
the minimal candidate only after metric and target-test contracts are fixed.
