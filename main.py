import asyncio
from fastapi import FastAPI

app = FastAPI()


@app.post("/connect/test")
async def emulate_connection():
    await asyncio.sleep(5)
    return {"status": "connected", "message": "Connection successful"}


@app.get("/location/test/pit")
async def get_chapel_hill_location():
    return {"name": "The Pit", "latitude": 35.9101, "longitude": -79.0486}
