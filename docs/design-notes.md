# Design notes

## Why a workbench

The architecture separates a centrally coordinated control plane (semantics, mappings, identity and location, source capabilities, policy) from a data plane that stays distributed. The first two demonstrators exercised the data plane and read the control plane from files. This one makes the control plane first-class:

- **It is operational infrastructure, not documentation.** The broker plans against a specific catalogue version. Each version is immutable, and every record states which version governed it.
- **Mappings are clinical-safety artefacts.** A mapping change alters what clinicians see. So every change needs a proportionate clinical sign-off, informed by evidence of its effect.
- **Capability claims are tested, not trusted.** Onboarding includes conformance tests, and a source that fails them cannot go live.

## Versioning model

- A version is a complete snapshot of three documents: catalogue, terminology and identity index.
- A change request is a list of typed operations. Applying them to the current snapshot gives a candidate snapshot. Nothing touches the live catalogue until approval, and approval commits the candidate as a new version.
- Restoring an earlier version is itself an operation, so a rollback is reviewed, assessed and versioned like any other change. History is never rewritten.
- The record-request log stores parameters, the as-at time and the version, but no values (P12). That is enough to re-assemble any record under any version.

## Impact analysis

For a draft change, the workbench assembles every person's record under both the current and the candidate snapshot, at the same moment and from the same sources. It then compares them:

| Class | Meaning | Examples |
|---|---|---|
| **hides** | Something a clinician currently sees would disappear | A review flag or conflict removed; a needs-review entry becoming routine; a clinical alert removed; a source that answered no longer answering |
| **raises** | Something new that needs attention | A new review flag or alert |
| **other** | Visible but not safety-relevant in itself | Entries or sources added; a source-level warning cleared because the source now answers |

"Hides" is the class that matters. It is how a housekeeping change, such as deprecating a formulary code that is about to be reused, is revealed as a decision that removes a medication discrepancy from a current patient's record.

A source-level warning that disappears because the source now answers (for example, *identity uncertain* after the steward confirms a match) is classed as *other*. The source-status change is reported separately, and nothing is being hidden.

## Conformance harness

It runs through the broker's own adapter for the source's interface, against the candidate snapshot:

| Check | Tests the claim that… |
|---|---|
| C1 | the source answers every record class it exposes, for the test subjects linked to it |
| C2 | it enforces the signed request context (a tampered signature is refused) |
| C3 | it refuses purposes it does not accept |
| C4 | its codes conform to the declared code system |
| C5 | every returned code resolves through the candidate concept maps (warning at 80–99%, fail below) |
| C6 | every statement carries an identifier and a date |
| C7 | observed latency is within twice the declared figure |

A warning does not block going live. It is recorded, and it shows up in the record as unmapped statements. That is the design's position that incompleteness should be explicit rather than prevented at any cost.

## Onboarding by configuration

The archived practice system joins through the same adapter as the current GP system, because both publish the same governed view contract. What differs is described in the catalogue: the code system of each view (Read v2 and a legacy drug dictionary rather than SNOMED CT and dm+d), the endpoint, the purposes accepted, and its authority ("historic record only"). The new concept maps arrive with the source in an onboarding pack.

## The medication supersede rule

Onboarding historic sources exposed a flaw in the second demonstrator's reconciliation. The old practice ended every medicine when the patient transferred out, so metformin would have been flagged as "stopped elsewhere". The rule is now: an ended assertion no longer disagrees if a prescribing source (GP repeat or acute, discharge or inpatient order) has since started the medicine again. A clinic list does not count as prescribing, so the amlodipine case is still flagged. That case is a stale list re-asserting a medicine the GP stopped, and it is exactly the kind of thing a federated record exists to catch.

## Identity stewardship

Identity links carry a method and a confidence, and the broker uses only those above the threshold for the purpose. A steward decision (confirm or reject) is a change request, which needs the identity steward's sign-off and is assessed for impact like any other change. Confirming Sam Patel's pharmacy match *raises* a flag: better identity can reveal problems as well as resolve uncertainty.

## Mapping to the architecture

| Architecture element | Here |
|---|---|
| Metadata catalogue as tier-one infrastructure, versioned and time-bounded | `controlplane/store.py` |
| Governance functions: catalogue stewardship, terminology and mapping authority, identity service, source conformance | Personas and roles; `controlplane/workbench.py` |
| Mapping lifecycle (proposed → approved → deprecated), with evidence and authorship | `ops.py`; sign-offs on change requests; element-level lifecycle in `terminology.py` |
| Catalogue version recorded in each result | `PatientRecord.catalogue_version`; request log |
| P4, federate metadata before data | `gp-legacy` refused until registered, tested and approved |
| P9, portable control plane | Full JSON snapshots per version; CDIF export per version |
| "Mappings are clinical-safety artefacts" | Impact analysis with the *hides* classification |

## Natural next step

**A materialised view registered as a source.** A steward registers an IPS summary view, built on a schedule from the federated record, as a catalogue source whose authority is "derived, not authoritative" and whose lineage points to the originals. It passes conformance and is made live. The outage comparison then follows: the federated view reports *unavailable* while the materialised view answers with a staleness indicator. That completes the hybrid (patterns C and D) that the design argues for.
