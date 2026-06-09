from agents.weather_agent import WeatherAgent
from schemas.models import UserRequest

request = UserRequest(destination="Da Nang", days=2, budget=5000000, interests=["beach"], travelers=2)
result = WeatherAgent().run(request)
print(result.model_dump())
