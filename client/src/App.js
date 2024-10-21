import React, { useState, useEffect, useRef } from 'react';

function App() {
  const [socket, setSocket] = useState(null);
  const [audioContext, setAudioContext] = useState(null);
  const [processor, setProcessor] = useState(null);
  const [microphoneStream, setMicrophoneStream] = useState(null);
  const [audioChunksQueue, setAudioChunksQueue] = useState([]);
  const [isRecording, setIsRecording] = useState(false);
  const [responseText, setResponseText] = useState('');
  const [logs, setLogs] = useState('');
  const [isPlaying, setIsPlaying] = useState(false);
  const audioSourceCounter = useRef(0);

  const logBoxRef = useRef(null);

  // Logging function
  const log = (message) => {
    setLogs((prevLogs) => prevLogs + `${new Date().toISOString()}: ${message}\n`);
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  };

  // Start recording function
  const startRecording = () => {
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then((stream) => {
        setMicrophoneStream(stream);
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        const newAudioContext = new AudioContext();
        setAudioContext(newAudioContext);

        const source = newAudioContext.createMediaStreamSource(stream);
        const newProcessor = newAudioContext.createScriptProcessor(1024, 1, 1);

        source.connect(newProcessor);
        newProcessor.connect(newAudioContext.destination);

        newProcessor.onaudioprocess = (e) => {
          const inputData = e.inputBuffer.getChannelData(0);
          const downsampledData = downsampleAudio(inputData, newAudioContext.sampleRate, 24000);
          const base64Audio = base64EncodeAudio(downsampledData);
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
              type: 'input_audio_buffer.append',
              audio: base64Audio,
            }));
          }
        };

        setProcessor(newProcessor);
        setIsRecording(true);

        // Connect to the backend WebSocket
        const newSocket = new WebSocket('ws://localhost:8000/ws/audio');

        newSocket.onopen = () => {
          log('WebSocket connection opened');
        };
        newSocket.onclose = () => {
          log('WebSocket connection closed');
          if (newProcessor) {
            newProcessor.disconnect();
          }
        };
        newSocket.onerror = (error) => log(`WebSocket error: ${error.message}`);
        newSocket.onmessage = handleServerMessage;

        setSocket(newSocket);
      })
      .catch((error) => {
        log(`Error accessing microphone: ${error.message}`);
        setIsRecording(false);
      });
  };

  // Stop recording function
  const stopRecording = () => {
    if (processor) {
      processor.disconnect();
      setProcessor(null);
    }
    if (microphoneStream) {
      microphoneStream.getTracks().forEach((track) => track.stop());
      setMicrophoneStream(null);
    }
    setIsRecording(false);
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'input_audio_buffer.commit' }));
      socket.close();
    }
    setSocket(null);
  };

  // Handle messages from the server
  const handleServerMessage = (event) => {
    const response = JSON.parse(event.data);
    log(`Received event: ${response.type}`);

    switch (response.type) {
      case 'response.audio_transcript.delta':
        setResponseText((prevText) => prevText + response.delta);
        break;
      case 'response.audio.delta':
        setAudioChunksQueue((prevQueue) => [...prevQueue, response.delta]);
        break;
      // Handle other event types as needed
      default:
        break;
    }
  };

  // Play queued audio chunks
  useEffect(() => {
    const playQueuedAudioChunks = async () => {
      if (isPlaying || audioChunksQueue.length === 0) return;

      setIsPlaying(true);

      while (audioChunksQueue.length > 0) {
        const chunk = audioChunksQueue.shift();
        await playAudioChunkPromise(chunk);
      }

      setIsPlaying(false);
    };

    const interval = setInterval(playQueuedAudioChunks, 100);

    return () => {
      clearInterval(interval);
    };
  }, [audioChunksQueue, isPlaying]);

  // Play a single audio chunk
  const playAudioChunkPromise = (base64Audio) => {
    return new Promise((resolve) => {
      if (!audioContext) {
        resolve();
        return;
      }

      audioSourceCounter.current += 1;
      console.log(`playAudioChunk called. Counter: ${audioSourceCounter.current}`);

      const audioData = base64ToArrayBuffer(base64Audio);
      const bufferLength = audioData.byteLength / 2;
      const audioBuffer = audioContext.createBuffer(1, bufferLength, 24000);
      const channelData = audioBuffer.getChannelData(0);
      const int16Array = new Int16Array(audioData);
      for (let i = 0; i < int16Array.length; i++) {
        channelData[i] = int16Array[i] / 32768;
      }

      const source = audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioContext.destination);
      source.start();

      source.onended = () => {
        console.log(`Audio playback ended. Source ID: ${audioSourceCounter.current}`);
        resolve();
      };
    });
  };

  // Utility functions
  const base64ToArrayBuffer = (base64) => {
    const binaryString = window.atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
  };

  const downsampleAudio = (audioData, originalSampleRate, targetSampleRate) => {
    const ratio = originalSampleRate / targetSampleRate;
    const newLength = Math.round(audioData.length / ratio);
    const result = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {
      result[i] = audioData[Math.floor(i * ratio)];
    }
    return result;
  };

  const base64EncodeAudio = (float32Array) => {
    const buffer = floatTo16BitPCM(float32Array);
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const chunkSize = 0x8000; // 32KB chunk size
    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, i + chunkSize);
      binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
  };

  const floatTo16BitPCM = (float32Array) => {
    const buffer = new ArrayBuffer(float32Array.length * 2);
    const view = new DataView(buffer);
    for (let i = 0; i < float32Array.length; i++) {
      let s = Math.max(-1, Math.min(1, float32Array[i]));
      view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return buffer;
  };

  return (
    <div style={{ margin: "8px" }}>
      <h1>Real-time Audio Chat</h1>
      <button onClick={startRecording} disabled={isRecording}>
        Start Recording
      </button>
      <button onClick={stopRecording} disabled={!isRecording}>
        Stop Recording
      </button>
      <div id="response">{responseText}</div>
      <textarea
        ref={logBoxRef}
        value={logs}
        readOnly
        style={{
          width: '100%',
          height: '200px',
          overflowY: 'scroll',
          border: '1px solid #ccc',
          padding: '10px',
          marginTop: '20px',
          whiteSpace: 'pre-wrap',
        }}
      />
    </div>
  );
}

export default App;
