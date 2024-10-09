import asyncio
import json
import os
from fastapi import FastAPI, WebSocket
from websockets.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from rich import print

from dotenv import load_dotenv
load_dotenv()

import logging

# Configure logging (this should be done at the top of the file, outside of any function)
logging.basicConfig(filename='openai_responses.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"

async def handle_openai_responses(openai_ws, websocket):
    while True:
        try:
            openai_response = await openai_ws.recv()
            print("RECEIVED RESPONSE")
            response_data = json.loads(openai_response)

            # Log the responses
            logging.info(f"OpenAI Response: {openai_response} \n")
            logging.info(f"Response Data: {json.dumps(response_data, indent=2)} \n")
            
            # Forward all event types to the frontend
            print("Sending to frontend")
            await websocket.send_json(response_data)
            print("Sent to frontend")
        except Exception as e:
            print(f"Error handling OpenAI response: {e}")
            await websocket.send_json({"type": "error", "message": f"Error handling OpenAI response: {str(e)}"})

async def openai_ws_handler(websocket: WebSocket):
    try:
        async with ws_connect(
            OPENAI_WS_URL,
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1",
            }
        ) as openai_ws:
            await openai_ws.send(json.dumps({
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": "You are a helpful AI assistant. Respond concisely.",
                }
            }))
            
            await openai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": "Your knowledge cutoff is 2023-10. You are a helpful assistant.",
                    "voice": "alloy",
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 200
                    }
                }
            }))
            
            logging.info("Session Updated \n")

            # Start a task to handle OpenAI responses
            openai_response_task = asyncio.create_task(handle_openai_responses(openai_ws, websocket))

            while True:
                print("ACTIVE")
                try:
                    data = await websocket.receive_text()
                    message = json.loads(data)
                    print(f"Message: {message} \n")
                    
                    if message['type'] == 'input_audio_buffer.append':
                        logging.info(f"Input Audio Buffer Append: {message} \n")
                        await openai_ws.send(json.dumps(message))
                    elif message['type'] == 'input_audio_buffer.commit':
                        await openai_ws.send(json.dumps(message))
                        await openai_ws.send(json.dumps({"type": "response.create"}))
                    
                except ConnectionClosed:
                    break
                except Exception as e:
                    print(f"Error in WebSocket communication: {e}")
                    await websocket.send_json({"type": "error", "message": str(e)})

            # Cancel the OpenAI response handling task when the main loop exits
            openai_response_task.cancel()
            
    except Exception as e:
        print(f"Error in OpenAI WebSocket connection: {e}")
        await websocket.send_json({"type": "error", "message": "Failed to connect to OpenAI"})

@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await openai_ws_handler(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)