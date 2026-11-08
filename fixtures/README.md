# Fixtures

Used by the fake providers and by tests. Everything here is made up.

- `repo/`: a tiny "demo-app" served by `FakeCodeProvider` as repository `fixtures/demo-app`, branch `main`.
- `transcript.vtt`: a design review of the demo app's Login and Dashboard screens.
- `screenshots/`: two Figma-style mockups referenced in the meeting (01 Login, 02 Dashboard).

What the meeting asks for, and what the repo already has (useful for checking results):

| # | Request in the meeting | State in `repo/` |
|---|---|---|
| 1 | "Forgot password?" link on Login | missing |
| 2 | Show/hide password toggle on Login | implemented (`src/pages/Login.tsx`) |
| 3 | Inline error under the field instead of a top banner | partial (top banner only) |
| 4 | Date-range filter on Dashboard (7/30/90 days, custom) | partial (fixed 7 days in `src/api/orders.ts`) |
| 5 | Export orders as CSV | missing |
| 6 | Empty state when there are no orders | missing |
