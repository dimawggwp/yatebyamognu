import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from supabase import create_client, Client
from ai_engine import analyze_face

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

app = FastAPI()

waiting_player = None

# Автоматически ищет index.html и в templates/, и в корне
@app.get("/", response_class=HTMLResponse)
async def get_frontend():
    possible_paths = ["templates/index.html", "index.html"]
    for path in possible_paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return "<h1>Файл index.html не найден!</h1>"

@app.websocket("/ws/battle/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    global waiting_player
    await websocket.accept()

    try:
        image_bytes = await websocket.receive_bytes()
        my_score = analyze_face(image_bytes)

        if waiting_player is None:
            waiting_player = {
                "ws": websocket, 
                "id": user_id, 
                "score": my_score
            }
            await websocket.send_json({"status": "waiting", "message": "Поиск оппонента..."})
            
            while True:
                await asyncio.sleep(1) 
        else:
            opponent = waiting_player
            waiting_player = None

            opp_id = opponent["id"]
            opp_score = opponent["score"]
            opp_ws = opponent["ws"]

            if my_score >= opp_score:
                winner_id, loser_id = user_id, opp_id
            else:
                winner_id, loser_id = opp_id, user_id

            update_elo_in_db(winner_id, loser_id)

            await websocket.send_json({
                "status": "finished",
                "result": "WIN" if winner_id == user_id else "LOSE",
                "your_score": my_score,
                "opp_score": opp_score
            })
            
            await opp_ws.send_json({
                "status": "finished",
                "result": "WIN" if winner_id == opp_id else "LOSE",
                "your_score": opp_score,
                "opp_score": my_score
            })

    except WebSocketDisconnect:
        if waiting_player and waiting_player["id"] == user_id:
            waiting_player = None
        print(f"Игрок {user_id} покинул игру.")

def update_elo_in_db(winner_id: str, loser_id: str):
    try:
        winner = supabase.table("profiles").select("elo").eq("id", winner_id).execute()
        loser = supabase.table("profiles").select("elo").eq("id", loser_id).execute()

        if winner.data and loser.data:
            w_elo = winner.data[0]["elo"] + 30
            l_elo = max(0, loser.data[0]["elo"] - 30)

            supabase.table("profiles").update({"elo": w_elo}).eq("id", winner_id).execute()
            supabase.table("profiles").update({"elo": l_elo}).eq("id", loser_id).execute()

            supabase.table("matches").insert({"winner_id": winner_id, "loser_id": loser_id}).execute()
    except Exception as e:
        print("Ошибка при обновлении базы данных:", e)