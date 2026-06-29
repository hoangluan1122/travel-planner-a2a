from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agents.root_agent import RootTravelPlannerAgent
from services.request_parser import parse_user_request
from web import app

console = Console()


def ask_request():
    console.print("[bold blue]AI Travel Planner A2A Demo[/bold blue]")
    user_text = input("Describe your trip request: ").strip()
    if not user_text:
        user_text = "I want to travel to Da Nang for 3 days with a budget of 8000000 VND, I like food, photo and beach, for 2 people"
    request = parse_user_request(user_text)
    console.print(Panel.fit(
        f"Destination: {request.destination}\nDays: {request.days}\nBudget: {request.budget:,} VND\nInterests: {', '.join(request.interests)}\nTravelers: {request.travelers}",
        title="Parsed Request",
        border_style="cyan",
    ))
    return request


def render_plan(plan):
    console.print(Panel.fit(plan.final_recommendation, title="Travel Plan Summary", border_style="blue"))

    for label, items in [("Flights", plan.flights), ("Hotels", plan.hotels), ("Attractions", plan.attractions)]:
        table = Table(title=label)
        table.add_column("Title")
        table.add_column("Details")
        table.add_column("Price", justify="right")
        table.add_column("Score", justify="right")
        for item in items:
            table.add_row(item.title, item.details, f"{item.price:,}", str(item.score))
        console.print(table)

    console.print(f"[bold green]Estimated total cost:[/bold green] {plan.estimated_cost:,} VND")


def main():
    request = ask_request()
    planner = RootTravelPlannerAgent()
    plan = planner.run(request)
    render_plan(plan)


if __name__ == "__main__":
    main()
