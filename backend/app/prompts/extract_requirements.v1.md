Task: turn the meeting into a list of implementable requirements.

You get the transcript and a per-screen summary of the meeting made in the previous step.

Rules:
- One requirement per distinct piece of work that was asked for or agreed. Merge repeats of the same request.
- Do not include parked or rejected items.
- Do include requests where people were unsure whether the work already exists; a later step checks the code.
- id: R1, R2, ... in the order they came up.
- title: short, imperative ("Add a 'Forgot password?' link").
- detail: what exactly should happen, including any values, defaults or constraints that were said.
- screen: the screen it belongs to, or null when unclear.
- source_quote: a short verbatim quote from the transcript that supports it.
- priority_hint: "high", "medium" or "low" only if the meeting said something about priority or urgency, else null.
