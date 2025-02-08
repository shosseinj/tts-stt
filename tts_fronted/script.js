// Function to convert text to speech (this remains unchanged)
async function convertTextToSpeech() {
    const text = document.getElementById("textInput").value;

    if (!text) {
        alert("Please enter some text!");
        return;
    }

    try {
        const response = await fetch("http://127.0.0.1:5000/tts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: text }),
        });

        if (!response.ok) {
            const errorText = await response.text();
            alert("Error: " + errorText);
            return;
        }

        const audioBlob = await response.blob();
        const audioURL = URL.createObjectURL(audioBlob);
        document.getElementById("audioPlayer").src = audioURL;
        document.getElementById("audioPlayer").play();
    } catch (error) {
        console.error("Error:", error);
        alert("Something went wrong!");
    }
}

// Function to transcribe the uploaded audio file
async function transcribeAudio() {
    const fileInput = document.getElementById("audioInput");
    const file = fileInput.files[0];

    if (!file) {
        alert("Please upload an audio file!");
        return;
    }

    const formData = new FormData();
    formData.append("audio", file);

    try {
        const response = await fetch("http://127.0.0.1:5000/stt", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            const errorText = await response.text();
            alert("Error: " + errorText);
            return;
        }

        const data = await response.json();
        if (data.transcription) {
            document.getElementById("transcriptionResult").textContent = `Transcription: ${data.transcription}`;
        } else {
            document.getElementById("transcriptionResult").textContent = "No transcription available.";
        }
    } catch (error) {
        console.error("Error:", error);
        alert("Something went wrong!");
    }
}
