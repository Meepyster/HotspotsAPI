import asyncio
import os
from typing import List, Optional, Dict, Any, cast
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import uuid

# --- CONFIGURATION ---
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env file")

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
        # Validate filename exists to satisfy type checker
        if not file.filename:
            raise HTTPException(status_code=400, detail="File must have a filename")

        # 1. Upload file to Supabase Storage
        file_ext = file.filename.split(".")[-1]
        file_name = f"{uuid.uuid4()}.{file_ext}"
        file_path = f"uploads/{file_name}"

        file_content = await file.read()

        # Handle optional content_type to satisfy type checker (FileOptions expects str, not None)
        content_type = file.content_type or "application/octet-stream"

        # Ensure your bucket is named 'hotspot_photos' and is Public
        supabase.storage.from_("hotspot_photos").upload(
            file_path, file_content, {"content-type": content_type}
        )

        # Get public URL
        public_url = supabase.storage.from_("hotspot_photos").get_public_url(file_path)

        # 2. Insert record into DB
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
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/locations/{location_name}/photos", response_model=List[PhotoResponse])
async def get_location_photos(location_name: str):
    """
    Get all photos for 'The Old Well' or 'The Pit'.
    """
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
    """
    Get all photos taken by a specific anonymous user.
    """
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
    """
    Handles voting logic:
    1. Check if user already voted in 'votes' table.
    2. If not, insert vote record.
    3. Update upvotes/downvotes in 'photos' table.
    """
    try:
        # 1. Check for existing vote
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

        # 2. Record the vote
        new_vote = {
            "user_id": vote.user_id,
            "photo_id": vote.photo_id,
            "vote_type": vote.vote_type,
        }
        supabase.table("votes").insert(new_vote).execute()

        # 3. Update photo counts
        # (Fetching first to add to existing count)
        photo_data = (
            supabase.table("photos")
            .select("upvotes, downvotes")
            .eq("id", vote.photo_id)
            .execute()
        )

        if not photo_data.data:
            raise HTTPException(status_code=404, detail="Photo not found")

        # FIX: Explicitly cast the data to a dictionary to satisfy Pylance
        current_photo = cast(Dict[str, Any], photo_data.data[0])

        # Use .get() to be safe against key errors, and int() to satisfy the type checker
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
