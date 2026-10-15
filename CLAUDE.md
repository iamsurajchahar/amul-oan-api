# CLAUDE.md

## PR review standard (Suraj's rule)

When asked to review a pull request, do a proper review, not a rubber stamp.
Correctness alone is not enough. Check all of the following before saying
"approve":

1. **Size versus the work.** Compare the diff size to what the change actually
   needs. If the PR is several times larger than the job warrants, say so and
   ask "can this be smaller?" before approving. Example: a single Langfuse
   metric plus a registration script should be roughly 100 to 150 lines, not
   700.
2. **AI-generated padding.** Call out tests for one-off scripts, long README
   "validation" sections, and defensive checks for cases the real data never
   produces. Ask the author to trim them. Verbose PRs are harder to examine,
   and the team has agreed not to push AI-written code uncritically.
3. **Claims versus diff.** Verify the PR description against the actual code.
   Do not take "tests passed" or "idempotent" on trust; read the test and the
   code path.
4. **What exactly was approved.** An approval covers one commit. If new
   commits land after the approval, re-review them or leave a comment saying
   the review stopped at the earlier commit.
5. **Prod impact.** State clearly what merging changes and what needs a
   separate activation step.

Background: on OpenAgriNet/amul-infra PR 86 (Oct 2026) a 700-line PR was
approved and the maintainer later cut it to 132 lines with the same
behaviour, then asked the team to be more critical of AI-generated code.
Do not repeat that.
