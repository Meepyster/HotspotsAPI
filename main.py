import asyncio
import os
from typing import List, Optional, Dict, Any, cast
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import uuid

# --- CONFIGURATION ---

# 1. Try to load from local .env file
load_dotenv()

# 2. Get variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# 3. Robust Check
if not SUPABASE_URL or not SUPABASE_KEY:
    print("CRITICAL ERROR: Environment variables not found.")
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# --- MODELS ---


class VoteRequest(BaseModel):
    photo_id: str
    user_id: str
    vote_type: str  # "up", "down", or "none"


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
    user_vote: Optional[str] = None


# --- ENDPOINTS ---


@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Hotspot Backend is running"}


@app.post("/upload")
async def upload_photo(
    user_id: str = Form(...),
    location_name: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    file: UploadFile = File(...),
):
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

        # FIX: Cast response data to handle type checking
        data = cast(List[Dict[str, Any]], response.data)

        if not data:
            print("Error: Database insert returned no data.")
            raise HTTPException(status_code=500, detail="Database insert failed.")

        return {"status": "success", "photo": data[0]}

    except Exception as e:
        print(f"Upload Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/locations/{location_name}/photos", response_model=List[PhotoResponse])
async def get_location_photos(location_name: str, viewer_id: Optional[str] = None):
    try:
        response = (
            supabase.table("photos")
            .select("*")
            .eq("location_name", location_name)
            .order("created_at", desc=True)
            .execute()
        )

        # FIX: Explicitly cast data to List[Dict]
        photos = cast(List[Dict[str, Any]], response.data)

        if viewer_id and photos:
            photo_ids = [p["id"] for p in photos]

            votes_response = (
                supabase.table("votes")
                .select("photo_id, vote_type")
                .eq("user_id", viewer_id)
                .in_("photo_id", photo_ids)
                .execute()
            )

            # FIX: Explicitly cast vote data
            votes_data = cast(List[Dict[str, Any]], votes_response.data)
            vote_map = {v["photo_id"]: v["vote_type"] for v in votes_data}

            for photo in photos:
                photo["user_vote"] = vote_map.get(photo["id"])

        return photos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{user_id}/photos", response_model=List[PhotoResponse])
async def get_user_photos(user_id: str, viewer_id: Optional[str] = None):
    try:
        response = (
            supabase.table("photos")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )

        # FIX: Explicitly cast data to List[Dict]
        photos = cast(List[Dict[str, Any]], response.data)

        if viewer_id and photos:
            photo_ids = [p["id"] for p in photos]

            votes_response = (
                supabase.table("votes")
                .select("photo_id, vote_type")
                .eq("user_id", viewer_id)
                .in_("photo_id", photo_ids)
                .execute()
            )

            # FIX: Explicitly cast vote data
            votes_data = cast(List[Dict[str, Any]], votes_response.data)
            vote_map = {v["photo_id"]: v["vote_type"] for v in votes_data}

            for photo in photos:
                photo["user_vote"] = vote_map.get(photo["id"])

        return photos
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/vote")
async def vote_photo(vote: VoteRequest):
    try:
        existing = (
            supabase.table("votes")
            .select("*")
            .eq("user_id", vote.user_id)
            .eq("photo_id", vote.photo_id)
            .execute()
        )

        # FIX: Cast existing data to safe type
        existing_data = cast(List[Dict[str, Any]], existing.data)
        existing_vote_type = existing_data[0]["vote_type"] if existing_data else None

        photo_res = (
            supabase.table("photos")
            .select("upvotes, downvotes")
            .eq("id", vote.photo_id)
            .execute()
        )

        # FIX: Cast photo data to safe type
        photo_data = cast(List[Dict[str, Any]], photo_res.data)

        if not photo_data:
            raise HTTPException(status_code=404, detail="Photo not found")

        photo = photo_data[0]

        # FIX: Cast numbers to int() before math to satisfy type checker
        up = int(photo.get("upvotes", 0))
        down = int(photo.get("downvotes", 0))

        # Calculate updates
        if vote.vote_type == "none":
            # Case A: Removing a vote
            if existing_vote_type == "up":
                up -= 1
            elif existing_vote_type == "down":
                down -= 1

            if existing_vote_type:
                supabase.table("votes").delete().eq("user_id", vote.user_id).eq(
                    "photo_id", vote.photo_id
                ).execute()

        else:
            # Case B: New Vote or Switching Vote
            if existing_vote_type == "up":
                up -= 1
            elif existing_vote_type == "down":
                down -= 1

            if vote.vote_type == "up":
                up += 1
            elif vote.vote_type == "down":
                down += 1

            vote_data = {
                "user_id": vote.user_id,
                "photo_id": vote.photo_id,
                "vote_type": vote.vote_type,
            }
            supabase.table("votes").upsert(
                vote_data, on_conflict="user_id, photo_id"
            ).execute()

        # Update Photo Table
        supabase.table("photos").update({"upvotes": up, "downvotes": down}).eq(
            "id", vote.photo_id
        ).execute()

        return {
            "status": "success",
            "vote": vote.vote_type,
            "new_up": up,
            "new_down": down,
        }

    except Exception as e:
        print(f"Vote Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
