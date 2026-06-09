# ItineraryOptimizerAgent

`ItineraryOptimizerAgent` turns the itinerary step from a simple heuristic into an agent-style workflow with state, scoring, evaluation, and revision.

The agent uses LangGraph when `langgraph` is installed. If LangGraph is not available, it falls back to an internal runner so the app can still start.

## Goal

Optimize the day-by-day travel plan by balancing budget, number of travelers, number of days, transport, lodging, attractions, meals, local movement, weather, user interests, and schedule quality.

## Tools

The tools are internal decision functions, not external APIs:

- `score_candidates`: rank attractions by interest fit, weather risk, ticket price, original provider score, and signature experience value.
- `build_itinerary`: create a day-by-day plan from the best unique attractions.
- `evaluate_itinerary`: calculate budget and constraint quality.
- `revise_itinerary`: revise the plan when it is over budget, repetitive, or weather-sensitive.
- `build_budget_breakdown`: calculate the final budget model.

## Budget Model

The optimizer uses these cost components:

- round-trip transport: one-way transport price x travelers x 2
- lodging: selected hotel total price or fallback nightly estimate x nights
- attraction tickets: selected day attraction tickets x travelers
- meals: per-person daily meal allowance x days x travelers
- local transport: per-person daily local transport x days x travelers
- experience allowance: daily food/culture/photo/beach/activity budget
- shopping: small shopping buffer per traveler
- contingency: 8 percent of subtotal

## Optimization Criteria

- stay within the requested budget when possible
- match the requested number of days
- account for number of travelers
- prefer user interests
- avoid repeated attractions when enough candidates exist
- prefer indoor activities when rain or storm is detected
- reduce outdoor-heavy plans during bad weather
- keep the last day lighter for departure
- penalize high attraction ticket cost on tight budgets
- report issues instead of hiding impossible constraints

## Workflow

```text
score_candidates
  -> build_itinerary
  -> evaluate_itinerary
  -> revise_itinerary if score is below threshold
  -> evaluate_itinerary
```

The result is stored in `provider_status["itinerary_optimizer"]` with:

- `score`
- `issues`
- `notes` / decisions
- `revision_count`
- `budget_breakdown`
