# Department onboarding runbook

1. Add the department to the project manifest and add provider-neutral `sourceAccessRules` entries that map its approved sources to `department:<PROJECT_ID>:<DEPARTMENT>`.
2. Add the same department value to the user's server-managed Entra `ProjectDepartments` custom security attribute. Never grant it through a client token claim.
3. Add a suite entry to `evaluation/suites.json` using one of the supported document-shape parsers. Include answerable questions, corpus-specific must-refuse questions, and zero-leakage assertions.
4. Validate the project configuration. A malformed or cross-project access policy must stop loading.
5. After the live-user scope preconditions pass, run an authorized **full** re-ingestion of the affected project/provider (`--full`); do not rely on an incremental run for initial department activation. Refresh the vocabulary record, then verify the complete `access_policy_id` distribution against the page-by-page prediction before evaluating answers. Stop and restore the approved checkpoint if any source retains its previous label, any unexpected label appears, or the total document/chunk count changes. Review the reported corpus shape and set a retrieval profile only after an evaluation sweep.
6. Run retrieval and generation evaluation for the project and department, split by English and Spanish. Confirm shared plus entitled-department visibility and zero visibility into every other department.
7. Confirm purge and reconciliation remove both shared and department-scoped test documents.
8. Publish only after the declared quality gates and persona matrix pass.

**A department is not live until its suite passes its declared gates.**

Adding a department must not require editing any file under `app/`.
