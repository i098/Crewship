---
name: ieee-documentation
description: Use when writing a design document (SDD, architecture doc, design section of a plan) or test documentation (test plan, cases, procedures, logs). IEEE 1016 and IEEE 829 rules.
---

# Documentation standards (IEEE 1016 and IEEE 829)

Design and test documentation follows IEEE 1016 and IEEE 829.
Apply them to the artifact actually being written, not as boilerplate everywhere.
A README, an ADR, a commit message, or a code comment is none of these documents and must not be padded into one.

## Design documents - IEEE 1016

Any software design description (an SDD, an architecture document, the design section of an implementation plan) is organized as design views, each answering an identified stakeholder concern.
Include at minimum:

- Identification: what system or component this describes, its version, its status, and where the authoritative copy lives.
- Stakeholders and their design concerns: name who the document is for and which question each part answers.
- Design views chosen to fit those concerns. Common viewpoints: context, composition, logical, dependency, information, interface, interaction, state dynamics, resource.
- Design elements within each view: entities, their attributes, their relationships, and the constraints on them.
- Design rationale: why this design, and which alternatives were rejected and why. A design document without rationale is a diagram, not a design description.

## Test documents - IEEE 829

Test documentation is written as the distinct document types the standard defines, not one undifferentiated "tests" page:

- Test Plan: scope, items under test, features tested and explicitly not tested, approach, pass and fail criteria, suspension and resumption criteria, deliverables, environment, responsibilities, risks.
- Test Design Specification: features to be tested, refinements to the approach, test identification, feature-level pass and fail criteria.
- Test Case Specification: unique identifier, inputs, expected outputs, environmental needs, and dependencies between cases.
- Test Procedure Specification: the ordered steps required to execute those cases.
- Test Log, Anomaly Report, and Test Summary Report: what actually ran, what failed with enough detail to reproduce it, and the resulting assessment.

Every test case carries a stable unique identifier and an explicit expected result.
"It passes" is not an expected result.

## Applying them proportionately

These standards fix the required content, not a page count.
A small component gets a short design description that still names its stakeholders, views, and rationale; it does not get a long template with empty headings.
Prefer a short filled-in document over a padded long one, and never add an empty section just to match a template.

Note for future work: IEEE 829 has been withdrawn and superseded by ISO/IEC/IEEE 29119-3, and IEEE 1016's architecture-description concerns are carried forward in ISO/IEC/IEEE 42010.
Follow 1016 and 829 as written here.
If a project has to satisfy a current certification or audit regime, raise the 29119-3 and 42010 question before writing rather than after.
