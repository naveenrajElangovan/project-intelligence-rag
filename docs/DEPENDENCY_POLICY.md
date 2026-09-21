# Project Intelligence dependency policy

All Project Intelligence repositories use **exact versions for direct runtime,
development, evaluation, and quality-tool dependencies**. A direct dependency
must not use an unbounded or compatible-release range. Ecosystems with supported
lockfiles also commit the resolved transitive graph (`package-lock.json` for Forge
and Gradle lockfiles for mobile).

`pyproject.toml` is the sole dependency declaration for each Python repository.
Optional dependency groups separate development, evaluation, or worker tooling
without creating a second manifest. Shared Python packages use the same safe minor
line where their application constraints permit it; a tested incompatibility must
be recorded in that repository's `docs/QUALITY_STATUS.md` rather than hidden by a
range or forced upgrade.

Dependency removal requires both an unused-dependency analyzer and a repository
reference search. Runtime-discovered drivers, command-line entry points, and
genuinely untyped third-party boundaries may use only narrow, named exceptions
documented in the owning repository's quality status.
