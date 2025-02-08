import os
import torch
import subprocess
from flask import Flask, render_template, send_from_directory, request, send_file, jsonify
import speech_recognition as sr
import whisper
import g4f
# Force CPU execution if you're facing CUDA memory issues
os.environ["CUDA_VISIBLE_DEVICES"] = ""  # Forces the model to run on CPU
torch.cuda.empty_cache()  # Clears any cached memory in case of lingering GPU memory
whisper_model = whisper.load_model("turbo")
# Initialize Flask app
app = Flask(__name__, static_folder='tts_fronted', template_folder='tts_fronted')

OUTPUT_FILE = "output.mp3"

# Define the model and output file
models = {
    "amir": "epoch=5261-step=2455712.onnx",
    "amir1": "fa_IR-amir-medium.onnx",
    "ganji": "epoch=5719-step=2609600-ganji.onnx"
}
name = "amir1"

# Construct model path
model_path = f"./model/{name}/{models.get(name, '')}"
if not os.path.exists(model_path):
    raise FileNotFoundError(f"Model file not found: {model_path}")


# Load the Piper model once (lazy loading)
# This is only done once when the app starts
def load_piper_model():
    try:
        # No need for any model loading if the model is already loaded
        print("Piper model loaded successfully.")
    except Exception as e:
        print(f"Error loading Piper model: {str(e)}")


# Route for serving the HTML page
@app.route('/')
def home():
    return render_template('index.html')  # Flask will look in tts_fronted for index.html


# Custom route for serving static files (JS, CSS)
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('tts_fronted', filename)


# Route for text-to-speech conversion
@app.route("/tts", methods=["POST"])
def text_to_speech():
    data = request.json
    text = data.get("text", "")
    print('text=', text)
    if not text:
        return {"error": "No text provided"}, 400

    # Run Piper using subprocess
    try:
        # Run the Piper TTS model via subprocess
        process = subprocess.run(
            ["piper", "--model", model_path, "--output_file", OUTPUT_FILE],
            input=text,
            text=True,
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        return {"error": "Piper synthesis failed", "details": e.stderr}, 500
    except FileNotFoundError:
        return {"error": "Piper is not installed or not found"}, 500

    # Free up GPU memory (if any) after the TTS process
    torch.cuda.empty_cache()  # Clear any cached memory after processing

    # Send the generated audio file as a response
    return send_file(OUTPUT_FILE, as_attachment=True, mimetype="audio/mpeg")


# Route for speech-to-text conversion
@app.route("/stt", methods=["POST"])
def speech_to_text():
    # Check if an audio file was uploaded

    if 'audio' not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files['audio']


    save_dir = 'uploaded_audio_files'
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)


    file_path = os.path.join(save_dir, audio_file.filename)
    audio_file.save(file_path)

    result = whisper_model.transcribe(file_path, language='fa')
    # print(result["text"])



    # prompt = "بعنوان یک مصحح نگارشی عمل کن. متن زیر از طربق تبدیل گفتار به متن بدست آمده و احتمالا دارای بعضی خطاهای املایی است. علامت نگارشی اعمال کن و خطاهای املایی را برطرف کن"
    # content = f"{prompt}.\n\n متن تصحیح نشده:{result['text']}\n\n متن تصحیح شده:\n\n "
    # response = g4f.ChatCompletion.create(
    #     model="gpt-4",
    #     messages=[{"role": "user", "content": content}]
    # )

    print(result["text"] )
    try:

        return jsonify({"transcription": result["text"]})

    except Exception as e:
        return jsonify({"error": f"Could not transcribe audio: {str(e)}"}), 500


if __name__ == "__main__":
    load_piper_model()  # Load the TTS model once at the beginning of the app
    app.run(debug=False)
