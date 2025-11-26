const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const chatWindow = document.getElementById("chat-window");
const micBtn = document.getElementById("mic-button");
const sendBtn = form.querySelector('button[type="submit"]');

// --- State Management ---
let sessionState = "initial_dream";
let conversationHistory = ""; 
let questionCount = 0; // This should be calculated from existing messages
const MAX_QUESTIONS = 10;
let currentSessionId = null;

// THIS IS THE FIX: Read the state from the server-rendered hidden element on page load
document.addEventListener("DOMContentLoaded", () => {
    const stateElement = document.getElementById("session-state");
    const sessionIdElement = document.getElementById("session-id-input");

    if (stateElement) {
        sessionState = stateElement.value;
        console.log("Session state initialized to:", sessionState);
    }
    if (sessionIdElement) {
        currentSessionId = parseInt(sessionIdElement.value);
        console.log("Current Session ID:", currentSessionId);
    }
    
    // Set placeholder and count questions based on the current state
    updateInputPlaceholder();
    if (sessionState === 'in_therapy_session' || sessionState === 'awaiting_therapy_start') {
        buildHistoryFromDOM();
    }
});

function updateInputPlaceholder() {
    if (sessionState === 'awaiting_therapy_start') {
        input.placeholder = "Type 'yes' to explore further...";
    } else if (sessionState === 'in_therapy_session') {
        // Count existing user questions in the therapy phase
        const userMessages = Array.from(document.querySelectorAll('.message.user'));
        const therapyStartIndex = userMessages.findIndex(msg => msg.querySelector('.message-text')?.innerText.toLowerCase().trim() === 'yes');
        
        if (therapyStartIndex !== -1) {
            questionCount = userMessages.length - (therapyStartIndex + 1);
        } else {
            questionCount = 0;
        }

        const remaining = MAX_QUESTIONS - questionCount;
        if (remaining <= 0) {
            endSession();
        } else {
            input.placeholder = `Ask your question (${remaining} remaining)...`;
        }

    } else { // initial_dream or session_ended
        input.placeholder = "I dreamt that . . .";
    }
}


function buildHistoryFromDOM() {
    const messages = document.querySelectorAll(".message");
    let history = "";
    messages.forEach(msg => {
        const sender = msg.classList.contains("user") ? "User" : "AI";
        const textElement = msg.querySelector('.message-text');
        if (textElement) {
            history += `${sender}: ${textElement.innerText}\n`;
        }
    });
    conversationHistory = history;
}

// 💬 Append message bubble to the chat window
// In chat.js, replace the entire appendMessage function with this:

function appendMessage(sender, content, type = 'text') {
  // 1. Create the outer container, its only job is alignment.
  const messageContainer = document.createElement("div");
  messageContainer.classList.add("message", sender);

  if (type === 'image') {
    // 2. Create the inner bubble for the image
    const imageBubble = document.createElement('div');
    imageBubble.classList.add('image-container');
    const img = document.createElement("img");
    img.src = content;
    img.alt = "Dream Visualization";
    img.classList.add("dream-image");
    imageBubble.appendChild(img);
    messageContainer.appendChild(imageBubble);
  } else {
    // 2. Create the inner, visible bubble for the text
    const textBubble = document.createElement('div');
    textBubble.classList.add('message-text');
    // The 'content' for text might be pre-formatted HTML
    textBubble.innerHTML = content;
    messageContainer.appendChild(textBubble);
  }

  chatWindow.appendChild(messageContainer);
  chatWindow.scrollTop = chatWindow.scrollHeight;
  return messageContainer;
}

// Disables the input form
function endSession() {
    input.disabled = true;
    micBtn.disabled = true;
    sendBtn.disabled = true;
    input.placeholder = "Session ended. Please start a new dream.";
    sessionState = "session_ended";
}

// Function for the initial dream submission
async function handleDreamSubmission(userText) {
    appendMessage("user", userText);
    const thinkingMsg = appendMessage("bot", "Dreaming up an interpretation...");
    input.value = "";
    sendBtn.disabled = true;

    try {
        const res = await fetch("/submit_message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ dream_text: userText })
        });

        if (!res.ok) {
            throw new Error(`Server responded with status: ${res.status}`);
        }

        const data = await res.json();

        if (data.session_id) {
             // Redirect to the new chat session page, which will load with the correct state
             window.location.href = `/chat/${data.session_id}`;
        } else {
            thinkingMsg.innerText = `Sorry, an error occurred: ${data.error || "Could not create a new session."}`;
            sendBtn.disabled = false;
        }

    } catch (err) {
        console.error(err);
        thinkingMsg.innerText = "Sorry, a connection error occurred while processing your dream.";
        sendBtn.disabled = false;
    }
}

// Function to handle the "yes" response to start therapy
async function handleTherapyStart(userText) {
    appendMessage("user", userText);
    const userTextLower = userText.toLowerCase().trim();
    input.value = "";

    if (['yes', 'y', 'sure', 'ok', 'okay'].includes(userTextLower)) {
        const thinkingMsg = appendMessage("bot", "...");
        sendBtn.disabled = true;

        try {
            const res = await fetch("/start_therapy", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ session_id: currentSessionId })
            });
             if (!res.ok) throw new Error(`Server error: ${res.status}`);
            const data = await res.json();
            thinkingMsg.remove();

            if (data.bot_message) {
                appendMessage("bot", data.bot_message.text, true); // True because it's HTML
                sessionState = "in_therapy_session";
                updateInputPlaceholder();
                buildHistoryFromDOM();
            } else {
                 appendMessage("bot", "Sorry, something went wrong starting the therapy session.");
            }

        } catch (err) {
            console.error(err);
            thinkingMsg.innerText = "An error occurred. Please try again.";
        } finally {
             sendBtn.disabled = false;
        }

    } else {
        appendMessage("bot", "No problem. This concludes our session. Feel free to start a new dream conversation anytime.");
        endSession();
    }
}


// Handler for the therapy follow-up questions
async function handleTherapyFollowUp(question) {
    appendMessage("user", question);
    const thinkingMsg = appendMessage("bot", "Thinking...");
    input.value = "";
    sendBtn.disabled = true;

    try {
        buildHistoryFromDOM(); // Get the latest history
        const res = await fetch("/therapy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                question: question,
                history: conversationHistory,
                session_id: currentSessionId
            })
        });
        if (!res.ok) throw new Error(`Server error: ${res.status}`);
        const data = await res.json();
        thinkingMsg.remove();

        if (data.error){
            appendMessage("bot", data.error);
        } else {
            appendMessage("bot", data.answer, true); // True because answer is HTML
        }
        
        questionCount++; // Increment after successful question
        updateInputPlaceholder(); // This will check the limit and end the session if needed

    } catch (err) {
        console.error(err);
        thinkingMsg.innerText = "Sorry, an error occurred during the follow-up.";
    } finally {
        if(sessionState !== "session_ended") {
            sendBtn.disabled = false;
        }
    }
}


// --- Main Event Listener ---
form.addEventListener("submit", (e) => {
  e.preventDefault();
  const userText = input.value.trim();
  if (!userText || sendBtn.disabled) return;

  console.log(`Submitting with state: ${sessionState}`);

  if (sessionState === 'initial_dream') {
      handleDreamSubmission(userText);
  } else if (sessionState === 'awaiting_therapy_start') {
      handleTherapyStart(userText);
  } else if (sessionState === 'in_therapy_session') {
      handleTherapyFollowUp(userText);
  }
});


// 🎤 --- STABLE MICROPHONE IMPLEMENTATION --- 🎤
// 🎤 --- STABLE MICROPHONE IMPLEMENTATION (v2 - Continuous Mode) --- 🎤
if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SpeechRecognition();

  recognition.lang = "en-US";
  recognition.interimResults = true;   // REQUIRED for live updates
  recognition.continuous = true;     // CHANGE: Keep listening until manually stopped

  let isListening = false;

  micBtn.addEventListener("click", () => {
    if (input.disabled) return;

    if (isListening) {
      // If already listening, stop recognition manually
      recognition.stop();
    } else {
      // If not listening, start recognition
      recognition.start();
    }
  });

  recognition.onstart = () => {
    isListening = true;
    micBtn.classList.add('listening');
    input.placeholder = "Listening... click mic again to stop.";
  };

  recognition.onend = () => {
    isListening = false;
    micBtn.classList.remove('listening');
    updateInputPlaceholder(); // Reset placeholder when stopped
  };

  // UPDATED onresult logic for robust live transcription:
  recognition.onresult = (event) => {
    let transcript = "";
    // Iterate through all results received so far
    for (let i = 0; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    input.value = transcript; // Update input field in real-time
  };

  recognition.onerror = (event) => {
    isListening = false; // Ensure listening state resets on error
    micBtn.classList.remove('listening');
    updateInputPlaceholder();

    let errorMessage = `An unknown error occurred: ${event.error}`;
    if (event.error === 'no-speech') {
        errorMessage = "No speech was detected. Please try again.";
    } else if (event.error === 'audio-capture') {
        errorMessage = "Microphone problem. Please check its connection.";
    } else if (event.error === 'not-allowed') {
        errorMessage = "Microphone access was denied. Please allow it in your browser settings.";
    }
    appendMessage("bot", `🎤 **Error:** ${errorMessage}`);
    console.error("Speech recognition error: ", event);
  };

} else {
  micBtn.style.display = "none";
  console.log("Your browser does not support voice input.");
}
// --- Image Modal Logic ---
document.addEventListener("DOMContentLoaded", () => {
    const modal = document.getElementById("image-modal");
    const modalImg = document.getElementById("modal-img");
    const chatWindowForModal = document.getElementById("chat-window");
    const closeBtn = document.querySelector(".close-modal-btn");

    if (modal && chatWindowForModal && closeBtn) {
        // Use event delegation on the chat window to listen for clicks on images
        chatWindowForModal.addEventListener('click', function(event) {
            // Check if the clicked element is an image inside the chat
            if (event.target && event.target.classList.contains('dream-image')) {
                modal.style.display = "flex"; // Use 'flex' to enable centering
                modalImg.src = event.target.src;
            }
        });

        // Function to close the modal
        const closeModal = function() {
            modal.style.display = "none";
        }

        // Close the modal when the 'x' (close button) is clicked
        closeBtn.onclick = closeModal;

        // Close the modal when the user clicks on the dark background area
        modal.onclick = function(event) {
            // Only close if the click is on the modal background itself, not the image
            if (event.target === modal) {
                closeModal();
            }
        }
    }
});