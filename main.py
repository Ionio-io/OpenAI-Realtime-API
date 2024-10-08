import asyncio
import json
import os
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import aiohttp
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

async def connect_to_openai():
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(OPENAI_WS_URL, headers=headers) as ws:
            await ws.send_json({
                "type": "response.create",
                "response": {
                    "modalities": ["text"],
                    "instructions": "Please assist the user.",
                }
            })
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await manager.broadcast(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"WebSocket error: {ws.exception()}")

# @app.on_event("startup")
# async def startup_event():
#     asyncio.create_task(connect_to_openai())

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    asyncio.create_task(connect_to_openai())
    try:
        while True:
            data = await websocket.receive_text()
            # Forward the message to OpenAI
            # You'll need to implement this part to send to the OpenAI WebSocket
            print(f"Received message from client: {data}")
            # For now, we'll just echo back the message
            await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)