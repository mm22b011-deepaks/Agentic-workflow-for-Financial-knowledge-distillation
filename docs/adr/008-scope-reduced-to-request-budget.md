# ADR 008: scope-reduced-to-request-budget

The human explicitly reduces the default scope because 50 free requests/day and 20/minute make the previous full model plan take months. The default is standard: a seeded fixed panel of 40 companies across the four latest completed calendar seasons. small is 20x4; large is 100x4; custom reads the supplied counts. custom with both counts zero retains explicit full-window capability. No algorithm contains company-specific cases.

A company must have a membership interval overlapping each selected season. Filing-date membership is still checked for the actual release. The same chosen companies appear in every season. data/manifests/panel.json freezes companies/pairs, seed, seasons, universe signature and hash under a file lock and atomic write. Changed seed, size, completed seasons or universe is an error, never an automatic redraw. A new data root or explicitly archived panel is required to choose a new panel. The prior verification/rejected panels remain untouched.

The primary configured free model handles each release; bakeoff measures the alternatives and may choose the priority. Listing two models no longer silently doubles production calls. Shipped/default repair count is zero and the default daily allowance is 50, never an implicit 1000. Transient retries remain counted attempts.

Forecasts use the same safety/reserve assumptions as the scheduler: floor(daily_limit * (1-safety_margin)) - retry_reserve. With default 50/day, margin .10 and reserve 5, usable capacity is 40. The standard base extraction plan is 160; bakeoff is 20; five model days reserve 25 potential retries, yielding 205 expected/held requests. These are forecasts with an UNSURE account allowance, not measured calls or a completion promise. Warnings give each season's numeric panel size and min_observations when the scope cannot publish.

Legacy full-window compatibility tests now explicitly select custom/0/0. The synthetic 500-release path is unchanged. Scheduler configuration types are introduced with the forecast so its implementation cannot invent a second budget calculation later.
