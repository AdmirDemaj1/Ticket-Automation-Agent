Task: for each requirement, decide whether the code already implements it, and say whether this repository is the codebase the meeting is about.

You get the requirements, the repository files that were read (each with line numbers), and search hits: lines in those files that contain words from each requirement. Search hits are only pointers to where to look; a word match is not proof. Files that were not read are not available; do not guess what they contain.

For every requirement, return exactly one finding:
- status: "implemented" (the code clearly does what was asked), "partial" (some of it exists), "missing" (the files read show it is not there), or "unclear" (the files read are not enough to tell).
- evidence: for "implemented" and "partial", at least one item with the path, start_line and end_line of the relevant lines and a note quoting or describing them. For "missing", cite the place where it would be expected, if there is one. Use only paths and line numbers from the files given.
- affected_files: files that would need to change.
- confidence: "high" only when the evidence is direct; otherwise "medium" or "low".

When a person in the meeting was unsure whether something exists, check it carefully and cite what you found.

Then judge repository_fit:
- "matches": the files are clearly the product discussed (same screens, features, platform).
- "partly": some of the discussed product is here, other parts likely live elsewhere (for example a separate backend or mobile app).
- "does_not_match": the files are a different product or platform than the one discussed.
- "cannot_tell": too little code was read to judge.
Give the reason in one or two sentences, naming what the files show and what the meeting was about.
