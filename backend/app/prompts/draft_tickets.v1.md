Task: draft Jira tickets for the sprint from the requirements and the code findings.

Rules:
- One ticket per requirement unless two requirements are clearly the same work; then merge them and list both requirement_ids. Do not create tickets for anything not in the requirements.
- type: one of the allowed issue types given below. Use "Story" for user-facing features and "Task" for technical work when both are allowed; use "Bug" only for broken behaviour.
- title: short and specific, at most 120 characters.
- description: what to build and why, based on the meeting; mention what already exists in the code with file paths when the finding has evidence.
- acceptance_criteria: 2 to 6 testable statements.
- estimate: null unless the meeting gave one.
- labels: at most 3 short lowercase labels, such as the screen name.
- related_files: files from the findings' evidence or affected_files.
- status_in_code: "already_done" when the finding is "implemented", "extends_existing" when it is "partial", otherwise "new". When the finding is "unclear", use "new" and say in the description that the code could not be checked.
- Order tickets so that work others depend on comes first.
