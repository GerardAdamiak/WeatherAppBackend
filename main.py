from fastapi import FastAPI, Query, HTTPException
from pydantic import BaseModel
import httpx
from typing import List
from collections import defaultdict
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_URL = "https://api.open-meteo.com/v1/forecast"
POWER_KW = 2.5
EFFICIENCY = 0.2

class DailyForecast(BaseModel):
    date: str
    weather_code: int
    temp_min: float
    temp_max: float
    solar_energy_kwh: float

class WeeklySummary(BaseModel):
    avg_pressure: float
    avg_sunshine_hours: float
    min_temp: float
    max_temp: float
    weekly_summary: str

def validate_coordinates(lat: float, lon: float):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(status_code=400, detail="Invalid coordinates")

def calculate_energy(sunshine_sec: int) -> float:
    return round((POWER_KW * (sunshine_sec / 3600) * EFFICIENCY), 2)

@app.get("/forecast", response_model=List[DailyForecast])
async def get_forecast(lat: float = Query(...), lon: float = Query(...)):
    validate_coordinates(lat, lon)
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "weathercode",
            "sunshine_duration"
        ],
        "timezone": "auto"
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(BASE_URL, params=params)
            res.raise_for_status()
            data = res.json()

            result = []
            for i in range(7):
                day = DailyForecast(
                    date=data["daily"]["time"][i],
                    weather_code=data["daily"]["weathercode"][i],
                    temp_min=data["daily"]["temperature_2m_min"][i],
                    temp_max=data["daily"]["temperature_2m_max"][i],
                    solar_energy_kwh=calculate_energy(data["daily"]["sunshine_duration"][i])
                )
                result.append(day)
            return result
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="External API error")

@app.get("/summary", response_model=WeeklySummary)
async def get_summary(lat: float = Query(...), lon: float = Query(...)):
    validate_coordinates(lat, lon)
    params_daily = {
        "latitude": lat,
        "longitude": lon,
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "sunshine_duration",
            "weathercode"
        ],
        "timezone": "auto"
    }

    params_hourly = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ["pressure_msl"],
        "timezone": "auto"
    }

    try:
        async with httpx.AsyncClient() as client:
            res_daily = await client.get(BASE_URL, params=params_daily)
            res_hourly = await client.get(BASE_URL, params=params_hourly)
            res_daily.raise_for_status()
            res_hourly.raise_for_status()
            data_daily = res_daily.json()
            data_hourly = res_hourly.json()

            print("Daily response:", data_daily)
            print("Hourly response:", data_hourly)

            daily = data_daily.get("daily", {})
            hourly = data_hourly.get("hourly", {})

            if not all(key in daily for key in ["temperature_2m_min", "temperature_2m_max", "sunshine_duration", "weathercode"]):
                raise HTTPException(status_code=500, detail="Brak wymaganych danych dziennych z API.")
            if "pressure_msl" not in hourly or "time" not in hourly:
                raise HTTPException(status_code=500, detail="Brak danych godzinowych ciśnienia z API.")

            min_temp = min(daily["temperature_2m_min"])
            max_temp = max(daily["temperature_2m_max"])
            avg_sunshine = round(sum(s / 3600 for s in daily["sunshine_duration"]) / len(daily["sunshine_duration"]), 2)


            pressure_by_day = defaultdict(list)
            for time_str, pressure in zip(hourly["time"], hourly["pressure_msl"]):
                date = time_str.split("T")[0]
                pressure_by_day[date].append(pressure)


            pressures = [sum(vals) / len(vals) for key, vals in sorted(pressure_by_day.items())[:7]]
            avg_pressure = round(sum(pressures) / len(pressures), 2)

            rain_days = sum(1 for code in daily["weathercode"] if code in range(51, 99))
            weekly_summary = "z opadami" if rain_days >= 4 else "bez opadów"

            return WeeklySummary(
                avg_pressure=avg_pressure,
                avg_sunshine_hours=avg_sunshine,
                min_temp=min_temp,
                max_temp=max_temp,
                weekly_summary=weekly_summary
            )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="External API error")
    except Exception as e:
        print(f"Wystąpił błąd: {e}")
        raise HTTPException(status_code=500, detail="Błąd przetwarzania danych")