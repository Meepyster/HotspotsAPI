import asyncio
import os
from typing import List, Optional, Dict, Any, cast
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import uuid

# --- CONFIGURATION ---

# 1. Try to load from local .env file (swallows error if file missing)
load_dotenv()

# 2. Get variables (works for both .env and Render Environment)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 3. Robust Check
if not SUPABASE_URL or not SUPABASE_KEY:
    # Print to logs so you can see it in Render Dashboard
    print("CRITICAL ERROR: Environment variables not found.")
    print(f"SUPABASE_URL Found: {SUPABASE_URL is not None}")
    print(f"SUPABASE_KEY Found: {SUPABASE_KEY is not None}")
    raise ValueError(
        "Missing SUPABASE_URL or SUPABASE_KEY. Check Render Environment Settings."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# --- MODELS ---


class VoteRequest(BaseModel):
    photo_id: str
    user_id: str
    vote_type: str  # "up" or "down"


class PhotoResponse(BaseModel):
    id: str
    user_id: str
    location_name: str
    image_url: str
    title: Optional[str]
    description: Optional[str]
    upvotes: int
    downvotes: int
    created_at: str


# --- ENDPOINTS ---


@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Hotspot Backend is running"}


@app.post("/upload")
async def upload_photo(
    user_id: str = Form(...),
    location_name: str = Form(...),  # Pass "The Old Well" here
    title: str = Form(...),
    description: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    file: UploadFile = File(...),
):
    """
    1. Uploads image to Supabase Storage
    2. Creates record in 'photos' table
    """
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="File must have a filename")

        file_ext = file.filename.split(".")[-1]
        file_name = f"{uuid.uuid4()}.{file_ext}"
        file_path = f"uploads/{file_name}"

        file_content = await file.read()

        content_type = file.content_type or "application/octet-stream"

        supabase.storage.from_("hotspot_photos").upload(
            file_path, file_content, {"content-type": content_type}
        )

        public_url = supabase.storage.from_("hotspot_photos").get_public_url(file_path)

        new_photo = {
            "user_id": user_id,
            "location_name": location_name,
            "image_url": public_url,
            "title": title,
            "description": description,
            "latitude": latitude,
            "longitude": longitude,
        }

        response = supabase.table("photos").insert(new_photo).execute()

        return {"status": "success", "photo": response.data[0]}

    except Exception as e:
        print(f"Upload Error: {e}")  # Log error for Render
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/locations/{location_name}/photos", response_model=List[PhotoResponse])
async def get_location_photos(location_name: str):
    try:
        response = (
            supabase.table("photos")
            .select("*")
            .eq("location_name", location_name)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{user_id}/photos", response_model=List[PhotoResponse])
async def get_user_photos(user_id: str):
    try:
        response = (
            supabase.table("photos")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/vote")
async def vote_photo(vote: VoteRequest):
    try:
        existing_vote = (
            supabase.table("votes")
            .select("*")
            .eq("user_id", vote.user_id)
            .eq("photo_id", vote.photo_id)
            .execute()
        )

        if existing_vote.data:
            return {
                "status": "ignored",
                "message": "You have already voted on this photo.",
            }

        new_vote = {
            "user_id": vote.user_id,
            "photo_id": vote.photo_id,
            "vote_type": vote.vote_type,
        }
        supabase.table("votes").insert(new_vote).execute()

        photo_data = (
            supabase.table("photos")
            .select("upvotes, downvotes")
            .eq("id", vote.photo_id)
            .execute()
        )

        if not photo_data.data:
            raise HTTPException(status_code=404, detail="Photo not found")

        current_photo = cast(Dict[str, Any], photo_data.data[0])

        current_upvotes = int(current_photo.get("upvotes", 0))
        current_downvotes = int(current_photo.get("downvotes", 0))

        update_data = {}

        if vote.vote_type == "up":
            update_data["upvotes"] = current_upvotes + 1
        else:
            update_data["downvotes"] = current_downvotes + 1

        supabase.table("photos").update(update_data).eq("id", vote.photo_id).execute()

        return {"status": "success", "vote": vote.vote_type}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
