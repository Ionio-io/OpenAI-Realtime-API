from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import websockets
import asyncio
import json
import os
from dotenv import load_dotenv

from pydub import AudioSegment
import io
import base64

load_dotenv()

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_WEBSOCKET_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"



def process_audio(base64_audio):
    # Decode base64 to raw audio data
    raw_audio = base64.b64decode(base64_audio)
    
    # Convert to AudioSegment
    audio = AudioSegment.from_mp3(io.BytesIO(raw_audio))
    
    # Resample to 24kHz
    audio = audio.set_frame_rate(24000)
    
    # Convert to mono
    audio = audio.set_channels(1)
    
    # Convert to 16-bit PCM
    audio = audio.set_sample_width(2)
    
    # Get raw PCM data
    raw_pcm = audio.raw_data
    
    # Encode back to base64
    return base64.b64encode(raw_pcm).decode()





async def openai_websocket_proxy(websocket: WebSocket):
    try:
        async with websockets.connect(
            OPENAI_WEBSOCKET_URL,
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1",
            }
        ) as openai_ws:
            client_to_openai = asyncio.create_task(forward_messages(websocket, openai_ws))
            openai_to_client = asyncio.create_task(forward_messages(openai_ws, websocket))

            await asyncio.wait(
                [client_to_openai, openai_to_client],
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in [client_to_openai, openai_to_client]:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
    except Exception as e:
        print(f"Error in openai_websocket_proxy: {str(e)}")
    finally:
        print("WebSocket connection closed")

async def forward_messages(source, destination):
    try:
        while True:
            if isinstance(source, WebSocket):
                message = await source.receive_text()
            else:
                message = await source.recv()
            
            print(f"Forwarding message: {message}")
            
            if isinstance(destination, WebSocket):
                await destination.send_text(message)
            else:
                await destination.send(message)
    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"Error in forward_messages: {str(e)}")

@app.websocket("/ws/openai")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        await openai_websocket_proxy(websocket)
    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)