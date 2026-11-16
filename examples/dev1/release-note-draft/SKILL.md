---
name: release-note-draft
description: Drafts release notes and changelog entries from merged pull requests and commit messages. Use when preparing a release, writing a changelog, or announcing what shipped in a new version.
---

# Release note draft

Write release notes a user can skim in under a minute.

1. Collect what changed since the last release: merged pull requests, commit messages, closed issues. Ask the user for the version number and the previous tag if you cannot find them.
2. Group changes under **Added**, **Changed**, **Fixed** and **Removed**. Drop internal-only changes (refactors, CI, test-only) unless the user asks for them.
3. Write each entry as one plain sentence from the user's point of view: what they can now do, or what no longer goes wrong. Link the pull request number at the end.
4. Put breaking changes first, under their own heading, with the action the user must take.
5. Fill in `assets/template.md` and show the result. Do not publish or tag anything yourself.
