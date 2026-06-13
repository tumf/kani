## MODIFIED Requirements

### Requirement: Doctor command provides safe operational diagnostics

The CLI MUST provide a read-only `doctor` command that reports configuration and local classifier asset health without exposing secrets. File presence alone MUST NOT be reported as evidence that a classifier asset is active in runtime routing. The classifier asset status MUST stay consistent with explicit runtime loading evidence.

#### Scenario: Legacy classifier asset is reported explicitly

**Given** the repository contains `models/tier_classifier.pkl`
**When** `kani doctor` inspects local classifier assets
**Then** the report must identify the asset as legacy or unused unless the current runtime actually loads it
**And** the report must not silently imply that the asset controls routing decisions

#### Scenario: Feature classifier asset presence is not treated as runtime activation

**Given** the repository contains `models/feature_classifier.pkl`
**When** `kani doctor` inspects local classifier assets
**Then** the report must describe the asset status in relation to explicit runtime loading evidence
**And** the report must not label it active based on file presence alone

#### Scenario: Feature classifier runtime loading is reported when code supports it

**Given** the repository contains `models/feature_classifier.pkl`
**And** current routing code explicitly loads `feature_classifier.pkl` at runtime
**When** `kani doctor` inspects local classifier assets
**Then** the report must not describe the asset as unused solely because the older heuristic runtime path existed
**And** the report must still avoid claiming successful runtime activation without executing the classifier path
