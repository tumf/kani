## ADDED Requirements

### Requirement: Doctor command provides safe operational diagnostics

The CLI MUST provide a read-only `doctor` command that reports configuration and local classifier asset health without exposing secrets. File presence alone MUST NOT be reported as evidence that a classifier asset is active in runtime routing.

#### Scenario: Valid configuration reports health summary

**Given** a valid kani config path
**When** `kani doctor --config <path>` is executed
**Then** the command must print a concise health report containing providers, profiles, model metadata status, and classifier asset status
**And** the command must exit with status 0 when only warnings are present

#### Scenario: Doctor output redacts secrets

**Given** a config file whose provider API key resolves to a non-empty secret
**When** `kani doctor --config <path>` is executed
**Then** the output must not contain the literal API key
**And** the output may indicate whether an API key is configured using masked or boolean status only

#### Scenario: Invalid configuration fails clearly

**Given** a missing or incomplete config path
**When** `kani doctor --config <path>` is executed
**Then** the command must exit non-zero
**And** the output must identify the config loading problem without a Python traceback

#### Scenario: Legacy classifier asset is reported explicitly

**Given** the repository contains `models/tier_classifier.pkl`
**When** `kani doctor` inspects local classifier assets
**Then** the report must identify the asset as legacy or unused unless the current runtime actually loads it
**And** the report must not silently imply that the asset controls routing decisions

#### Scenario: Feature classifier asset presence is not treated as runtime activation

**Given** the repository contains `models/feature_classifier.pkl`
**And** current routing code does not explicitly load that asset
**When** `kani doctor` inspects local classifier assets
**Then** the report must identify the asset as present but not loaded by current runtime routing
**And** the report must not label it active based on file presence alone
